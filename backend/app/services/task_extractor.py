import datetime
import logging
import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
import google.generativeai as genai
from backend.app.config import settings
from backend.app.models import Task, User
from backend.app.services.notifier import send_missing_info_notification, send_scheduled_notification
from backend.app.services.ml_predictor import predict_missing_fields
from backend.app.services.scheduler import schedule_task

logger = logging.getLogger("levitate.task_extractor")

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

async def check_if_follow_up_input(
    text: str,
    pending_tasks: List[Dict[str, Any]],
    current_time: datetime.datetime
) -> Dict[str, Any]:
    """
    Checks if a new user input provides details for an existing pending task.
    """
    if not pending_tasks:
        return {"is_follow_up": False, "task_id": None, "updates": None}

    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY missing. Running mock follow-up detector.")
        return mock_check_follow_up(text, pending_tasks, current_time)

    try:
        system_prompt = f"""You are the Levitate Follow-up Classifier.
Your job is to determine if a new user command provides updates/details (like title, priority, deadline, or duration) to address the missing info for one of the pending tasks.

=== CURRENT TIME ===
{current_time.isoformat()}

=== PENDING TASKS ===
{json.dumps(pending_tasks, default=str)}

=== OUTPUT FORMAT ===
You must return a JSON object with:
- "is_follow_up": (boolean) true if the command is addressing a pending task, false if it's a new separate task.
- "task_id": (integer or null) The ID of the pending task it addresses.
- "updates": (object or null) If is_follow_up is true, contains the fields resolved:
    - "task_name": (string or null) New/corrected title if provided.
    - "implied_priority": (string or null) "High", "Medium", or "Low" if provided.
    - "deadline": (string or null) ISO format YYYY-MM-DDTHH:MM:SS if date/time was provided.
    - "duration_mins": (integer or null) Duration in minutes if provided.
    - "focus_score": (integer or null) Mental focus score from 1 to 5 if provided.
"""
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
        generation_config = {"response_mime_type": "application/json"}
        prompt = f'User input: "{text}"'

        response = await model.generate_content_async(prompt, generation_config=generation_config)
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        return json.loads(response_text.strip())
    except Exception as e:
        logger.exception(f"Gemini follow-up classifier failed: {e}")
        return mock_check_follow_up(text, pending_tasks, current_time)

def mock_check_follow_up(
    text: str,
    pending_tasks: List[Dict[str, Any]],
    current_time: datetime.datetime
) -> Dict[str, Any]:
    if not pending_tasks:
        return {"is_follow_up": False, "task_id": None, "updates": None}
    
    target_task = pending_tasks[0]
    text_lower = text.lower()
    updates = {}
    
    if "high" in text_lower or "urgent" in text_lower:
        updates["implied_priority"] = "High"
    elif "medium" in text_lower:
        updates["implied_priority"] = "Medium"
    elif "low" in text_lower:
        updates["implied_priority"] = "Low"
        
    if "high focus" in text_lower or "demanding" in text_lower or "stressful" in text_lower:
        updates["focus_score"] = 5
    elif "low focus" in text_lower or "easy" in text_lower:
        updates["focus_score"] = 1
        
    if "tomorrow" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(days=1)
        updates["deadline"] = datetime.datetime.combine(sched_date, datetime.time(14, 0)).isoformat()
    elif "next week" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(weeks=1)
        updates["deadline"] = datetime.datetime.combine(sched_date, datetime.time(10, 0)).isoformat()
        
    if not target_task.get("title") and not any(kw in text_lower for kw in ["high", "medium", "low", "urgent", "tomorrow", "next week"]):
        updates["task_name"] = text.strip().capitalize()
        
    if updates:
        return {
            "is_follow_up": True,
            "task_id": target_task["id"],
            "updates": updates
        }
        
    return {"is_follow_up": False, "task_id": None, "updates": None}

async def extract_and_fill_task(
    raw_fields: Dict[str, Any],
    db: Session,
    user: User,
    now: datetime.datetime
) -> Dict[str, Any]:
    """
    Processes the raw parsed fields from File A.
    Fills the 4 variables: task_name, priority, deadline, duration.
    Coordinates scheduling and status transitions.
    """
    task_name = raw_fields.get("task_name")
    priority = raw_fields.get("implied_priority")
    entity_type = raw_fields.get("entity_type", "Chore")
    deadline_str = raw_fields.get("deadline")
    duration_mins = raw_fields.get("duration_mins")

    scheduled_time = None
    if deadline_str:
        try:
            scheduled_time = datetime.datetime.fromisoformat(deadline_str)
        except Exception:
            pass

    # If other fields are present but duration is missing, we auto-fill duration
    if task_name is not None and priority is not None and scheduled_time is not None and duration_mins is None:
        title_lower = task_name.lower()
        if "meeting" in title_lower or "call" in title_lower:
            duration_mins = 120
        elif "homework" in title_lower:
            duration_mins = 120
        elif "geography" in title_lower and "test" in title_lower:
            duration_mins = 180
        elif "math" in title_lower and "test" in title_lower:
            duration_mins = 300
        else:
            duration_mins = 60

    # Check completeness: all 4 fields must be present
    is_complete = (
        task_name is not None and 
        priority is not None and 
        scheduled_time is not None and 
        duration_mins is not None
    )

    status = "SCHEDULED" if is_complete else "PENDING_CONTEXT"

    focus_score = raw_fields.get("focus_score")
    if focus_score is None:
        from backend.app.services.scheduler import is_high_focus
        focus_score = 3 if (task_name and is_high_focus(task_name)) else 1

    db_task = Task(
        user_id=user.id,
        title=task_name,
        priority=priority,
        status=status,
        entity_type=entity_type,
        input_received_at=now,
        scheduled_time=scheduled_time,
        duration_mins=duration_mins or 60,  # Default to 60 mins if not set
        is_time_deadline=raw_fields.get("is_time_deadline", False),
        focus_score=focus_score,
        context_request_sent=False
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    if is_complete:
        # Schedule the task via File E (Scheduler)
        schedule_task(db_task, db, now)
        send_scheduled_notification(db, db_task, f"Task '{db_task.title}' has been successfully scheduled.")
    # If incomplete, we do NOT notify immediately anymore!
    # File C will send a notification 15 minutes later if still incomplete.

    return {
        "action": "created_new_task",
        "task": {
            "id": db_task.id,
            "title": db_task.title,
            "priority": db_task.priority,
            "status": db_task.status,
            "entity_type": db_task.entity_type,
            "scheduled_time": db_task.scheduled_time.isoformat() if db_task.scheduled_time else None,
            "duration_mins": db_task.duration_mins,
            "focus_score": db_task.focus_score
        }
    }

async def process_follow_up_input(
    text: str,
    db_task: Task,
    updates: Dict[str, Any],
    db: Session,
    now: datetime.datetime
) -> Dict[str, Any]:
    """
    Applies updates from a follow-up command to an existing pending task.
    """
    if "task_name" in updates and updates["task_name"]:
        db_task.title = updates["task_name"]
    if "implied_priority" in updates and updates["implied_priority"]:
        db_task.priority = updates["implied_priority"]
    if "deadline" in updates and updates["deadline"]:
        try:
            db_task.scheduled_time = datetime.datetime.fromisoformat(updates["deadline"])
        except Exception:
            pass
    if "duration_mins" in updates and updates["duration_mins"]:
        db_task.duration_mins = int(updates["duration_mins"])
    if "is_time_deadline" in updates:
        db_task.is_time_deadline = bool(updates["is_time_deadline"])
    if "focus_score" in updates and updates["focus_score"] is not None:
        db_task.focus_score = int(updates["focus_score"])
    else:
        from backend.app.services.scheduler import is_high_focus
        db_task.focus_score = 3 if (db_task.title and is_high_focus(db_task.title)) else 1

    # Re-evaluate completeness
    # If other fields are present but duration is missing, we auto-fill duration
    if db_task.title is not None and db_task.priority is not None and db_task.scheduled_time is not None and db_task.duration_mins is None:
        title_lower = db_task.title.lower()
        if "meeting" in title_lower or "call" in title_lower:
            db_task.duration_mins = 120
        elif "homework" in title_lower:
            db_task.duration_mins = 120
        elif "geography" in title_lower and "test" in title_lower:
            db_task.duration_mins = 180
        elif "math" in title_lower and "test" in title_lower:
            db_task.duration_mins = 300
        else:
            db_task.duration_mins = 60

    is_complete = (
        db_task.title is not None and 
        db_task.priority is not None and 
        db_task.scheduled_time is not None and 
        db_task.duration_mins is not None
    )

    if is_complete:
        db_task.status = "SCHEDULED"
        schedule_task(db_task, db, now)
        send_scheduled_notification(db, db_task, f"Task '{db_task.title}' has been successfully scheduled.")

    db.commit()
    db.refresh(db_task)

    return {
        "action": "updated_pending_task",
        "task": {
            "id": db_task.id,
            "title": db_task.title,
            "priority": db_task.priority,
            "status": db_task.status,
            "entity_type": db_task.entity_type,
            "scheduled_time": db_task.scheduled_time.isoformat() if db_task.scheduled_time else None,
            "duration_mins": db_task.duration_mins,
            "focus_score": db_task.focus_score
        }
    }

async def check_pending_tasks(db: Session, current_time: datetime.datetime):
    """
    Periodic background check (called from main worker loop).
    Handles:
    - 15-minute missing info notifications.
    - 1-hour ML auto-fill timeout.
    
    Testing Timeouts:
    - 1 Hour = PENDING_TIMEOUT_SECONDS (3 seconds in test environment)
    - 15 Minutes = PENDING_TIMEOUT_SECONDS / 4 (0.75 seconds in test environment)
    """
    timeout_seconds = settings.PENDING_TIMEOUT_SECONDS
    notification_seconds = timeout_seconds / 4

    pending_tasks = db.query(Task).filter(Task.status == "PENDING_CONTEXT").all()

    for task in pending_tasks:
        elapsed = (current_time - task.input_received_at).total_seconds()
        
        # 1. 15-minute missing info notification
        if elapsed >= notification_seconds and not task.context_request_sent:
            from backend.app.services.conversational_helper import generate_voice_friendly_question
            message = generate_voice_friendly_question(task)
            send_missing_info_notification(db, task, message)
            task.context_request_sent = True
            db.commit()
            logger.info(f"Sent missing context notification for task ID {task.id} (Elapsed: {elapsed:.2f}s).")

        # 2. 1-hour ML auto-fill timeout
        if elapsed >= timeout_seconds:
            # Fetch historical tasks for user context (excluding pending tasks)
            historical_tasks = db.query(Task).filter(
                Task.user_id == task.user_id,
                Task.status != "PENDING_CONTEXT"
            ).all()
            
            history_list = [
                {
                    "title": t.title,
                    "priority": t.priority,
                    "scheduled_time": t.scheduled_time.isoformat() if t.scheduled_time else None,
                    "entity_type": t.entity_type,
                    "duration_mins": t.duration_mins
                }
                for t in historical_tasks
            ]
            
            predictions = await predict_missing_fields(task, history_list, db, current_time)
            
            # Apply predictions
            task.title = predictions.get("task_name") or task.title or f"Auto-filled {task.entity_type}"
            task.priority = predictions.get("implied_priority") or "Low"
            
            predicted_time = None
            if predictions.get("deadline"):
                try:
                    predicted_time = datetime.datetime.fromisoformat(predictions["deadline"])
                except Exception:
                    pass
            task.scheduled_time = predicted_time or (current_time + datetime.timedelta(days=1))
            task.duration_mins = predictions.get("duration_mins") or task.duration_mins or 60
            from backend.app.services.scheduler import is_high_focus
            task.focus_score = 3 if (task.title and is_high_focus(task.title)) else 1
            task.status = "SCHEDULED"
            
            # Resolve scheduling via File E
            schedule_task(task, db, current_time)
            
            # Send notification
            send_scheduled_notification(db, task, f"Task '{task.title}' was automatically scheduled using historical predictive data.")
            db.commit()
            logger.info(f"Task ID {task.id} has been automatically filled and scheduled (Elapsed: {elapsed:.2f}s).")

    # 3. Overdue task check (for tasks that are past their deadline and still SCHEDULED)
    overdue_tasks = db.query(Task).filter(
        Task.status == "SCHEDULED",
        Task.scheduled_time < current_time
    ).all()
    
    for overdue_task in overdue_tasks:
        overdue_task.status = "OVERDUE"
        overdue_task.allocations.clear()
        from backend.app.services.notifier import send_task_reminder_notification
        send_task_reminder_notification(
            db, overdue_task,
            f"Have you completed your task: {overdue_task.title}? Yes or No"
        )
        db.commit()
        logger.info(f"Task ID {overdue_task.id} transitioned to OVERDUE and completion prompt sent.")

    # 4. Auto-dismiss unread notifications after 1 hour (timeout_seconds)
    # and auto-reschedule the associated task if it is a completion prompt
    from backend.app.models import Notification, TaskAllocation
    unread_notifications = db.query(Notification).filter(Notification.is_read == False).all()
    for noti in unread_notifications:
        noti_elapsed = (current_time - noti.created_at).total_seconds()
        if noti_elapsed >= timeout_seconds:
            noti.is_read = True
            db.commit()
            logger.info(f"Notification ID {noti.id} has timed out and was auto-dismissed (elapsed: {noti_elapsed:.2f}s).")
            
            # Reschedule if it's a completion prompt
            if noti.task_id and "completed" in noti.message.lower():
                task = db.query(Task).filter(Task.id == noti.task_id).first()
                if task and task.status != "COMPLETED" and task.status != "CANCELLED":
                    # Reschedule task 1 day later
                    task.scheduled_time = current_time + datetime.timedelta(days=1)
                    task.status = "SCHEDULED"
                    db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).delete()
                    schedule_task(task, db, current_time)
                    db.commit()
                    logger.info(f"Task ID {task.id} automatically rescheduled on completion prompt timeout.")
