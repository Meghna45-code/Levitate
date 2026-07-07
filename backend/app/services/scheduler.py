import datetime
import logging
import threading
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.app.models import Task, TaskAllocation, User, TaskRescheduleLog
from backend.app.services.notifier import send_task_reminder_notification, send_simultaneous_notification
from backend.app.services.calendar import create_calendar_event
from backend.app.services.calendar_cache import get_cached_calendar_events
from backend.app.services.ml_predictor import get_user_active_hours

logger = logging.getLogger("levitate.scheduler")
scheduler_lock = threading.RLock()
DAILY_FOCUS_THRESHOLD = 5

def with_scheduler_lock(func):
    def wrapper(*args, **kwargs):
        with scheduler_lock:
            return func(*args, **kwargs)
    return wrapper

def get_global_score(task: Task, current_time: datetime.datetime) -> float:
    """
    Global priority scoring (decimal format):
    1. Base Priority: High = 30.0, Medium = 20.0, Low = 10.0
    2. Category Score: Meeting = 0.4, Payment = 0.3, Family = 0.2, Chore = 0.1
    3. Time Urgency:
        - hours_until <= 0 (Overdue): 100.0 + abs(hours_until) * 5.0
        - 0 < hours_until <= 24: 10.0 + (24.0 - hours_until) * (90.0 / 24.0)
        - hours_until > 24: 10.0 / ((hours_until / 24.0) + 1.0)
    4. Duration Burden: min(2.0, duration_hours * 0.05). Larger tasks get slightly more priority.
    """
    priority_map = {"High": 3.0, "Medium": 2.0, "Low": 1.0}
    entity_map = {"Meeting": 0.4, "Payment": 0.3, "Family": 0.2, "Chore": 0.1}
    
    base_score = priority_map.get(task.priority, 1.0) * 10.0
    category_score = entity_map.get(task.entity_type, 0.1)
    
    deadline = task.scheduled_time or (current_time + datetime.timedelta(days=1))
    hours_until = (deadline - current_time).total_seconds() / 3600.0
    
    if hours_until <= 0:
        time_urgency = 100.0 + abs(hours_until) * 5.0
    elif hours_until <= 24:
        time_urgency = 10.0 + (24.0 - hours_until) * (90.0 / 24.0)
    else:
        time_urgency = 10.0 / ((hours_until / 24.0) + 1.0)
    
    duration_hours = (task.duration_mins or 60) / 60.0
    duration_factor = min(2.0, duration_hours * 0.05)
    
    multiplier_map = {"High": 5.0, "Medium": 3.0, "Low": 1.0}
    multiplier = multiplier_map.get(task.priority, 1.0)
    postponement_boost = (task.reschedule_count or 0) * multiplier
    
    return base_score + category_score + time_urgency + duration_factor + postponement_boost

def check_cognitive_fatigue(
    day: datetime.date,
    new_start: datetime.datetime,
    new_end: datetime.datetime,
    new_focus: int,
    hourly_focus: dict
) -> bool:
    """
    Simulates the fatigue curve for the day from hour 0 to 23.
    Returns True if the fatigue level never exceeds MAX_FATIGUE_LIMIT (10.0).
    """
    MAX_FATIGUE_LIMIT = 6.0
    DECAY_RATE = 1.5
    
    day_hours_focus = {}
    
    # 1. Populate with existing hourly focus scores
    for (d, h), f in hourly_focus.items():
        if d == day:
            day_hours_focus[h] = max(day_hours_focus.get(h, 0), f)
            
    # 2. Add the new slot
    start_hour = new_start.hour
    end_hour = (new_end - datetime.timedelta(seconds=1)).hour
    
    for h in range(start_hour, end_hour + 1):
        day_hours_focus[h] = max(day_hours_focus.get(h, 0), new_focus)
        
    # 3. Simulate fatigue decay hour-by-hour
    fatigue = 0.0
    for h in range(24):
        hour_f = day_hours_focus.get(h, 0)
        if hour_f > 0:
            fatigue += hour_f
        else:
            fatigue = max(0.0, fatigue - DECAY_RATE)
            
        if fatigue > MAX_FATIGUE_LIMIT:
            return False
            
    return True

def update_hourly_focus(
    day: datetime.date,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    focus_score: int,
    hourly_focus: dict
):
    start_hour = start_time.hour
    end_hour = (end_time - datetime.timedelta(seconds=1)).hour
    for h in range(start_hour, end_hour + 1):
        hourly_focus[(day, h)] = max(hourly_focus.get((day, h), 0), focus_score)

def is_holiday_day(day: datetime.date, cal_events: list) -> bool:
    """
    Checks if there's any Google Calendar event on 'day' containing holiday keywords.
    """
    holiday_keywords = ["holiday", "puja", "ganpati", "ganesha", "chaturthi", "diwali", "christmas", "eid", "dussehra", "navratri"]
    for ev in cal_events:
        s_str = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
        if s_str and len(s_str) >= 10:
            try:
                ev_date = datetime.date.fromisoformat(s_str[:10])
                if ev_date == day:
                    title = ev.get("summary", "").lower()
                    desc = ev.get("description", "").lower()
                    if any(k in title or k in desc for k in holiday_keywords):
                        return True
            except Exception:
                pass
    return False

def is_high_focus(title: str) -> bool:
    """
    Determines if a task title indicates high focus requirement.
    """
    t_lower = (title or "").lower()
    focus_keywords = ["math", "test", "geography", "meeting", "homework", "design", "call", "project"]
    return any(k in t_lower for k in focus_keywords)

def find_free_slot_on_day(
    day: datetime.date,
    duration_mins: int,
    busy_slots: list,
    active_hours: list,
    current_time: datetime.datetime
) -> Optional[tuple]:
    """
    Searches for a free slot of duration_mins within working hours (9 AM - 6 PM)
    on a given day, prioritizing the user's high active hours. Enforces a 30-minute break buffer.
    """
    for hour in active_hours:
        if 9 <= hour <= 18:
            candidate_start = datetime.datetime.combine(day, datetime.time(hour, 0))
            candidate_end = candidate_start + datetime.timedelta(minutes=duration_mins)
            
            if day == current_time.date() and candidate_start < current_time:
                continue
                
            overlap = False
            for b_start, b_end in busy_slots:
                buffered_start = b_start - datetime.timedelta(minutes=30)
                buffered_end = b_end + datetime.timedelta(minutes=30)
                if max(candidate_start, buffered_start) < min(candidate_end, buffered_end):
                    overlap = True
                    break
            
            if not overlap and candidate_end.hour <= 18:
                return candidate_start, candidate_end
                
    # Fallback: search sequentially from 9 AM to 6 PM by 15 min steps
    candidate_start = datetime.datetime.combine(day, datetime.time(9, 0))
    work_end = datetime.datetime.combine(day, datetime.time(18, 0))
    
    while candidate_start + datetime.timedelta(minutes=duration_mins) <= work_end:
        candidate_end = candidate_start + datetime.timedelta(minutes=duration_mins)
        if day == current_time.date() and candidate_start < current_time:
            candidate_start += datetime.timedelta(minutes=15)
            continue
        overlap = False
        for b_start, b_end in busy_slots:
            buffered_start = b_start - datetime.timedelta(minutes=30)
            buffered_end = b_end + datetime.timedelta(minutes=30)
            if max(candidate_start, buffered_start) < min(candidate_end, buffered_end):
                overlap = True
                break
        if not overlap:
            return candidate_start, candidate_end
        candidate_start += datetime.timedelta(minutes=15)
        
    # Force fallback if absolutely no slot inside work hours: search entire day by 15 min steps
    candidate_start = datetime.datetime.combine(day, datetime.time(0, 0))
    day_end = datetime.datetime.combine(day, datetime.time(23, 59))
    while candidate_start + datetime.timedelta(minutes=duration_mins) <= day_end:
        candidate_end = candidate_start + datetime.timedelta(minutes=duration_mins)
        if day == current_time.date() and candidate_start < current_time:
            candidate_start += datetime.timedelta(minutes=15)
            continue
        overlap = False
        for b_start, b_end in busy_slots:
            buffered_start = b_start - datetime.timedelta(minutes=30)
            buffered_end = b_end + datetime.timedelta(minutes=30)
            if max(candidate_start, buffered_start) < min(candidate_end, buffered_end):
                overlap = True
                break
        if not overlap:
            return candidate_start, candidate_end
        candidate_start += datetime.timedelta(minutes=15)
        
    return None

@with_scheduler_lock
def schedule_all_tasks(user_id: int, db: Session, current_time: datetime.datetime):
    """
    Comprehensive Scheduling & Allocation engine:
    1. Removes all existing TaskAllocations for active scheduled tasks.
    2. Fetches Google Calendar events as fixed busy slots.
    3. Sorts tasks globally by their priority scores (decimal).
    4. Time-deadline tasks are placed exactly at their deadlines. Overlapping time tasks run simultaneously.
    5. Day-deadline tasks are distributed across available days (current day to deadline) under holiday/weekend budgets.
    """
    logger.info(f"Running global scheduler for user ID {user_id}...")
    
    tasks = db.query(Task).filter(
        Task.user_id == user_id,
        Task.status == "SCHEDULED"
    ).all()
    
    user = db.query(User).filter(User.id == user_id).first()
    
    from backend.app.services.calendar import delete_calendar_event
    for t in tasks:
        allocs = db.query(TaskAllocation).filter(TaskAllocation.task_id == t.id).all()
        if user:
            for alloc in allocs:
                if alloc.google_event_id:
                    try:
                        delete_calendar_event(user, alloc.google_event_id)
                    except Exception as e:
                        logger.warning(f"Failed to delete Google Calendar event {alloc.google_event_id} for task {t.id}: {e}")
        db.query(TaskAllocation).filter(TaskAllocation.task_id == t.id).delete()
    db.commit()

    cal_events = []
    if user:
        try:
            cal_events = get_cached_calendar_events(user, db)
        except Exception as e:
            logger.warning(f"Failed to fetch calendar events: {e}")
            
    busy_slots = []
    holiday_keywords = ["holiday", "puja", "ganpati", "ganesha", "chaturthi", "diwali", "christmas", "eid", "dussehra", "navratri"]
    for ev in cal_events:
        title = (ev.get("summary") or "").lower()
        desc = (ev.get("description") or "").lower()
        is_holiday = any(k in title or k in desc for k in holiday_keywords)
        if is_holiday:
            continue
            
        s_str = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
        e_str = ev.get('end', {}).get('dateTime') or ev.get('end', {}).get('date')
        if s_str and e_str:
            try:
                s_dt = datetime.datetime.fromisoformat(s_str.replace('Z', '+00:00')).replace(tzinfo=None)
                e_dt = datetime.datetime.fromisoformat(e_str.replace('Z', '+00:00')).replace(tzinfo=None)
                busy_slots.append((s_dt, e_dt))
            except Exception:
                pass

    tasks_sorted = sorted(
        tasks,
        key=lambda t: get_global_score(t, current_time),
        reverse=True
    )

    daily_schedules = {}
    for s_start, s_end in busy_slots:
        day = s_start.date()
        if day not in daily_schedules:
            daily_schedules[day] = []
        daily_schedules[day].append((s_start, s_end))

    daily_focus_scores = {}
    hourly_focus = {}
    time_task_allocations = []

    def inject_travel_buffer_if_external(task, s_start, s_end, day):
        from backend.app.services.ml_predictor import is_external_task, get_travel_buffer_mins
        if is_external_task(task.title):
            buf = get_travel_buffer_mins(task.title)
            daily_schedules[day].append((s_start - datetime.timedelta(minutes=buf), s_start))
            daily_schedules[day].append((s_end, s_end + datetime.timedelta(minutes=buf)))

    scheduled_task_keys = set()
    visiting_task_keys = set()

    def allocate_task(task):
        task_key = task.id if task.id is not None else id(task)
        if task_key in scheduled_task_keys:
            return

        if task_key in visiting_task_keys:
            logger.warning(f"Circular dependency detected for task '{task.title}'. Breaking loop.")
            return

        visiting_task_keys.add(task_key)

        # 1. Resolve predecessor first
        from backend.app.services.ml_predictor import find_predecessor_in_list
        pred = find_predecessor_in_list(task, tasks)
        if pred:
            pred_key = pred.id if pred.id is not None else id(pred)
            if pred_key not in scheduled_task_keys:
                allocate_task(pred)

        visiting_task_keys.remove(task_key)

        # 2. Determine minimum start time based on predecessor completion
        min_start_time = current_time
        if pred:
            pred_allocs = db.query(TaskAllocation).filter(TaskAllocation.task_id == pred.id).all()
            if pred_allocs:
                latest_end = max(alloc.end_time for alloc in pred_allocs)
                min_start_time = max(min_start_time, latest_end + datetime.timedelta(minutes=30))

        # 3. Schedule the current task
        duration = task.duration_mins or 60
        historical_durations = db.query(Task.actual_duration_mins).filter(
            Task.user_id == task.user_id,
            Task.entity_type == task.entity_type,
            Task.status == "COMPLETED",
            Task.actual_duration_mins.isnot(None)
        ).all()
        
        
        if historical_durations:
            valid_vals = [d[0] for d in historical_durations if d[0] is not None]
            if valid_vals:
                avg_actual = sum(valid_vals) / len(valid_vals)
                duration = int(avg_actual)

        # Scenario A: Time-specific deadlines
        if task.is_time_deadline and task.scheduled_time:
            end_time = task.scheduled_time
            start_time = end_time - datetime.timedelta(minutes=duration)
            
            if start_time < min_start_time:
                start_time = min_start_time
                end_time = start_time + datetime.timedelta(minutes=duration)
                task.scheduled_time = end_time

            day = start_time.date()
            if day not in daily_schedules:
                daily_schedules[day] = []

            for prev_task, prev_start, prev_end in time_task_allocations:
                if max(start_time, prev_start) < min(end_time, prev_end):
                    send_simultaneous_notification(db, task, prev_task)

            alloc = TaskAllocation(
                task_id=task.id,
                start_time=start_time,
                end_time=end_time,
                duration_mins=duration
            )
            db.add(alloc)
            db.commit()

            daily_schedules[day].append((start_time, end_time))
            inject_travel_buffer_if_external(task, start_time, end_time, day)
            update_hourly_focus(day, start_time, end_time, task.focus_score or 1, hourly_focus)
            daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
            time_task_allocations.append((task, start_time, end_time))
            task.scheduled_time = end_time

        # Scenario B: Day deadlines (distributable & budget-constrained)
        else:
            deadline_date = (task.scheduled_time or (current_time + datetime.timedelta(days=1))).date()
            start_date = max(current_time.date(), min_start_time.date())

            remaining_duration = duration

            days_range = []
            curr = start_date
            while curr <= deadline_date:
                days_range.append(curr)
                curr += datetime.timedelta(days=1)

            active_hours = get_user_active_hours(db, user_id)
            hour_focus_ratings = {}
            if active_hours:
                for idx, hour in enumerate(active_hours):
                    hour_focus_ratings[hour] = 5.0 - (idx * (4.0 / len(active_hours)))
            task_focus = task.focus_score or 1.0
            candidate_hours = sorted(
                active_hours,
                key=lambda h: abs(task_focus - hour_focus_ratings.get(h, 1.0))
            )

            days_count = len(days_range)
            daily_rate = int(duration / days_count) if days_count > 0 else duration
            if daily_rate < 60:
                daily_rate = 60

            for day in days_range:
                if remaining_duration <= 0:
                    break

                if day not in daily_schedules:
                    daily_schedules[day] = []

                used_mins = sum(
                    int((slot[1] - slot[0]).total_seconds() / 60)
                    for slot in daily_schedules[day]
                )

                is_weekend = (day.weekday() >= 5)
                is_h = is_holiday_day(day, cal_events)
                budget_limit = 360 if (is_weekend or is_h) else 240

                budget_left = max(0, budget_limit - used_mins)

                if budget_left < 60 and remaining_duration > budget_left:
                    continue

                if budget_left > 0:
                    slice_duration = min(remaining_duration, daily_rate, budget_left)

                    candidate_current_time = max(current_time, min_start_time) if day == min_start_time.date() else current_time
                    slot = find_free_slot_on_day(day, slice_duration, daily_schedules[day], candidate_hours, candidate_current_time)
                    if slot:
                        s_start, s_end = slot
                        if day != deadline_date and not check_cognitive_fatigue(day, s_start, s_end, task.focus_score or 1, hourly_focus):
                            logger.info(f"Skipping day {day} for task ID {task.id} due to hourly cognitive fatigue violation.")
                            continue

                        alloc = TaskAllocation(
                            task_id=task.id,
                            start_time=s_start,
                            end_time=s_end,
                            duration_mins=slice_duration
                        )
                        db.add(alloc)
                        db.commit()

                        daily_schedules[day].append((s_start, s_end))
                        inject_travel_buffer_if_external(task, s_start, s_end, day)
                        update_hourly_focus(day, s_start, s_end, task.focus_score or 1, hourly_focus)
                        daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
                        remaining_duration -= slice_duration

            # Force schedule remaining hours on the deadline day if still left
            if remaining_duration > 0:
                day = deadline_date
                if day < min_start_time.date():
                    day = min_start_time.date()
                    old_deadline = task.scheduled_time
                    orig_time = task.scheduled_time.time() if task.scheduled_time else datetime.time(12, 0)
                    task.scheduled_time = datetime.datetime.combine(day, orig_time)
                    db.commit()

                if task.priority == "High":
                    if day not in daily_schedules:
                        daily_schedules[day] = []

                    candidate_start = max(datetime.datetime.combine(day, datetime.time(9, 0)), min_start_time)
                    # Bedtime extension to 2 AM next day
                    day_end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(2, 0))
                    placed = False
                    while candidate_start + datetime.timedelta(minutes=remaining_duration) <= day_end:
                         candidate_end = candidate_start + datetime.timedelta(minutes=remaining_duration)
                         overlap = False
                         for b_start, b_end in daily_schedules[day]:
                             buffered_start = b_start - datetime.timedelta(minutes=30)
                             buffered_end = b_end + datetime.timedelta(minutes=30)
                             if max(candidate_start, buffered_start) < min(candidate_end, buffered_end):
                                 overlap = True
                                 break
                         if not overlap:
                             alloc = TaskAllocation(
                                 task_id=task.id,
                                 start_time=candidate_start,
                                 end_time=candidate_end,
                                 duration_mins=remaining_duration
                             )
                             db.add(alloc)
                             db.commit()
                             daily_schedules[day].append((candidate_start, candidate_end))
                             inject_travel_buffer_if_external(task, candidate_start, candidate_end, day)
                             update_hourly_focus(day, candidate_start, candidate_end, task.focus_score or 1, hourly_focus)
                             daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
                             if candidate_end > datetime.datetime.combine(day, datetime.time(23, 59)):
                                 from backend.app.services.notifier import send_task_reminder_notification
                                 send_task_reminder_notification(
                                     db, task,
                                     f"Notice: We extended your active hours tonight to fit '{task.title}' before its deadline."
                                 )
                             placed = True
                             break
                         candidate_start += datetime.timedelta(minutes=15)

                    if not placed:
                        # Bedtime extension fallback
                        s_end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(2, 0))
                        s_start = max(s_end - datetime.timedelta(minutes=remaining_duration), min_start_time)
                        alloc = TaskAllocation(
                            task_id=task.id,
                            start_time=s_start,
                            end_time=s_end,
                            duration_mins=remaining_duration
                        )
                        db.add(alloc)
                        db.commit()
                        daily_schedules[day].append((s_start, s_end))
                        inject_travel_buffer_if_external(task, s_start, s_end, day)
                        update_hourly_focus(day, s_start, s_end, task.focus_score or 1, hourly_focus)
                        daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
                        from backend.app.services.notifier import send_task_reminder_notification
                        send_task_reminder_notification(
                            db, task,
                            f"Notice: We extended your active hours tonight to fit '{task.title}' before its deadline."
                        )
                else:
                    old_deadline = task.scheduled_time
                    new_deadline_date = max(deadline_date + datetime.timedelta(days=1), min_start_time.date())
                    orig_time = task.scheduled_time.time() if task.scheduled_time else datetime.time(12, 0)
                    task.scheduled_time = datetime.datetime.combine(new_deadline_date, orig_time)
                    task.reschedule_count = (task.reschedule_count or 0) + 1
                    db.commit()
                    logger.info(f"Postponed task ID {task.id} ('{task.title}') by 1 day due to conflict (Reschedule Count: {task.reschedule_count}).")

                    resched_log = TaskRescheduleLog(
                        task_id=task.id,
                        old_time=old_deadline,
                        new_time=task.scheduled_time,
                        reason="Budget overflow or dependency conflict"
                    )
                    db.add(resched_log)
                    db.commit()

                    day = new_deadline_date
                    if day not in daily_schedules:
                        daily_schedules[day] = []

                    candidate_current_time = max(current_time, min_start_time) if day == min_start_time.date() else current_time
                    slot = find_free_slot_on_day(day, remaining_duration, daily_schedules[day], candidate_hours, candidate_current_time)
                    if slot:
                        s_start, s_end = slot
                        alloc = TaskAllocation(
                            task_id=task.id,
                            start_time=s_start,
                            end_time=s_end,
                            duration_mins=remaining_duration
                        )
                        db.add(alloc)
                        db.commit()
                        daily_schedules[day].append((s_start, s_end))
                        inject_travel_buffer_if_external(task, s_start, s_end, day)
                        update_hourly_focus(day, s_start, s_end, task.focus_score or 1, hourly_focus)
                        daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
                        remaining_duration = 0
                    else:
                        s_start = max(datetime.datetime.combine(day, datetime.time(18, 0)) - datetime.timedelta(minutes=remaining_duration), min_start_time)
                        s_end = s_start + datetime.timedelta(minutes=remaining_duration)
                        alloc = TaskAllocation(
                            task_id=task.id,
                            start_time=s_start,
                            end_time=s_end,
                            duration_mins=remaining_duration
                        )
                        db.add(alloc)
                        db.commit()
                        daily_schedules[day].append((s_start, s_end))
                        inject_travel_buffer_if_external(task, s_start, s_end, day)
                        update_hourly_focus(day, s_start, s_end, task.focus_score or 1, hourly_focus)
                        daily_focus_scores[day] = daily_focus_scores.get(day, 0) + (task.focus_score or 1)
                        remaining_duration = 0

        scheduled_task_keys.add(task_key)

    for rank, task in enumerate(tasks_sorted, 1):
        task.priority_rank = rank
        allocate_task(task)

    db.commit()

def schedule_task(task: Task, db: Session, current_time: datetime.datetime):
    """
    Main entry point for scheduling a task.
    """
    schedule_all_tasks(task.user_id, db, current_time)
    db.refresh(task)
    
    user = db.query(User).filter(User.id == task.user_id).first()
    if user:
        allocations = db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).all()
        for alloc in allocations:
            try:
                event = create_calendar_event(
                    user=user,
                    title=task.title,
                    start_time=alloc.start_time,
                    duration_mins=alloc.duration_mins,
                    entity_type=task.entity_type
                )
                if event and isinstance(event, dict) and "id" in event:
                    alloc.google_event_id = event["id"]
                    db.commit()
            except Exception as e:
                logger.warning(f"Calendar sync failed for allocation {alloc.id}: {e}")

    allocations = db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).order_by(TaskAllocation.start_time.asc()).all()
    if allocations:
        start_time = allocations[0].start_time
        end_time = allocations[-1].end_time
        
        send_task_reminder_notification(
            db, task, 
            f"Task '{task.title}' starts now."
        )
        
        send_task_reminder_notification(
            db, task, 
            f"Task '{task.title}' should be completed now."
        )
        
        if (end_time - current_time).total_seconds() >= 3600:
            send_task_reminder_notification(
                db, task, 
                f"Reminder: You have 1 hour left to complete Task '{task.title}' (Deadline: {end_time.strftime('%I:%M %p')})."
            )
