import os
import sys
import time
import json
import datetime
import urllib.request
import urllib.error
import threading
import uvicorn

# Override pending timeout for testing purposes to 3 seconds
os.environ["PENDING_TIMEOUT_SECONDS"] = "6"

from backend.app.main import app

import backend.app.services.calendar as calendar_services
import backend.app.services.scheduler as scheduler_services
import backend.app.services.calendar_cache as cache_services
import backend.app.services.text_parser as text_parser_services

holiday_mock_events = []
def custom_get_calendar_events(user, start_time, end_time):
    return holiday_mock_events

deleted_event_ids = []
def custom_delete_calendar_event(user, event_id):
    deleted_event_ids.append(event_id)

mock_transcription_value = "Make it high priority tomorrow"
async def custom_transcribe_audio_bytes(file_bytes, file_ext="wav"):
    return mock_transcription_value

calendar_services.get_calendar_events = custom_get_calendar_events
scheduler_services.get_calendar_events = custom_get_calendar_events
cache_services.get_calendar_events = custom_get_calendar_events
calendar_services.delete_calendar_event = custom_delete_calendar_event
text_parser_services.transcribe_audio_bytes = custom_transcribe_audio_bytes

import backend.app.main as main_module
main_module.transcribe_audio_bytes = custom_transcribe_audio_bytes

PORT = 8005
BASE_URL = f"http://127.0.0.1:{PORT}"

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

def make_multipart_request(path, filename, file_bytes):
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    url = f"{BASE_URL}{path}"
    
    parts = []
    parts.append(f"--{boundary}".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8"))
    parts.append(b"Content-Type: audio/wav\r\n")
    parts.append(file_bytes)
    parts.append(f"--{boundary}--".encode("utf-8"))
    
    body = b"\r\n".join(parts)
    
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def make_request(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def run_tests():
    global holiday_mock_events, deleted_event_ids
    print("--- Starting Levitate Pipeline Integration Tests ---")
    
    # 1. Reset Database
    print("\n[Step 1] Resetting Database...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200, f"Reset failed: {res}"
    print("Database reset successful.")

    # 2. Test Case 1: Complete Input
    print("\n[Step 2] Testing Complete Ingestion...")
    # 'urgent' makes priority High, 'tomorrow' makes deadline tomorrow
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent design meeting tomorrow"})
    assert status == 200, f"Ingest failed: {res}"
    assert res["action"] == "created_new_task", f"Unexpected action: {res}"
    task = res["task"]
    assert task["status"] == "SCHEDULED", f"Task should be SCHEDULED: {task}"
    assert task["priority"] == "High", f"Task priority should be High: {task}"
    assert task["scheduled_time"] is not None, f"Task scheduled_time should be present: {task}"
    print(f"Complete Ingestion OK: Task '{task['title']}' is SCHEDULED with priority '{task['priority']}' at {task['scheduled_time']}.")

    # 3. Test Case 2: Incomplete Input & Notification
    print("\n[Step 3] Testing Incomplete Ingestion...")
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule client checkup"})
    assert status == 200, f"Ingest failed: {res}"
    assert res["action"] == "created_new_task", f"Unexpected action: {res}"
    task_incomplete = res["task"]
    assert task_incomplete["status"] == "PENDING_CONTEXT", f"Task should be PENDING_CONTEXT: {task_incomplete}"
    assert task_incomplete["priority"] is None, f"Task priority should be None: {task_incomplete}"
    assert task_incomplete["scheduled_time"] is None, f"Task scheduled_time should be None: {task_incomplete}"
    
    # Check notifications
    time.sleep(1.5)
    status, notifications = make_request("/api/notifications")
    assert status == 200
    assert len(notifications) > 0, "No notifications created!"
    pending_notification = notifications[0]
    assert "missing" in pending_notification["message"].lower() or "please enter" in pending_notification["message"].lower(), f"Unexpected notification message: {pending_notification['message']}"
    print(f"Incomplete Ingestion OK: Task status is PENDING_CONTEXT. Notification: '{pending_notification['message']}'.")

    # 4. Test Case 3: Follow-up Resolution
    print("\n[Step 4] Testing Follow-up Resolution...")
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Make it high priority tomorrow"})
    assert status == 200, f"Follow-up failed: {res}"
    assert res["action"] == "updated_pending_task", f"Unexpected action: {res}"
    updated_task = res["task"]
    assert updated_task["id"] == task_incomplete["id"], "Should update the pending task"
    assert updated_task["status"] == "SCHEDULED", f"Updated task should be SCHEDULED: {updated_task}"
    assert updated_task["priority"] == "High", f"Priority should be updated: {updated_task}"
    assert updated_task["scheduled_time"] is not None, f"Time should be updated: {updated_task}"
    
    # Check notifications
    status, notifications = make_request("/api/notifications")
    assert status == 200
    # The scheduling success notification should be present in the notification list
    assert any("successfully scheduled" in n["message"].lower() for n in notifications), f"Expected success notification not found in: {[n['message'] for n in notifications]}"
    print(f"Follow-up Resolution OK: Task ID {updated_task['id']} updated to SCHEDULED, priority High, time {updated_task['scheduled_time']}.")

    # 5. Test Case 4: ML Auto-fill Timeout
    print("\n[Step 5] Testing ML Auto-fill Timeout...")
    # Ingest a task missing everything
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Do chores"})
    assert status == 200
    task_to_timeout = res["task"]
    assert task_to_timeout["status"] == "PENDING_CONTEXT"
    print(f"Task ID {task_to_timeout['id']} created with PENDING_CONTEXT. Waiting 5 seconds for timeout...")
    
    # Wait and poll for timeout (up to 8 seconds)
    print("Waiting and polling for auto-fill execution...")
    updated_timeout_task = None
    for i in range(8):
        time.sleep(1)
        status, updated_timeout_task = make_request(f"/api/tasks/{task_to_timeout['id']}")
        if status == 200 and updated_timeout_task["status"] == "SCHEDULED":
            print(f"Task successfully transitioned to SCHEDULED at second {i+1}.")
            break
            
    assert updated_timeout_task is not None
    assert updated_timeout_task["status"] == "SCHEDULED", f"Task should be auto-filled to SCHEDULED: {updated_timeout_task}"
    assert updated_timeout_task["priority"] is not None, f"Priority should be auto-filled: {updated_timeout_task}"
    assert updated_timeout_task["scheduled_time"] is not None, f"Scheduled time should be auto-filled: {updated_timeout_task}"
    assert updated_timeout_task["title"] is not None, f"Title should be present: {updated_timeout_task}"
    
    # Check notifications
    status, notifications = make_request("/api/notifications")
    assert status == 200
    assert any("automatically scheduled" in n["message"].lower() for n in notifications), f"Expected auto-fill notification not found in: {[n['message'] for n in notifications]}"
    print(f"ML Auto-fill Timeout OK: Task auto-filled to SCHEDULED. Title: '{updated_timeout_task['title']}', Priority: '{updated_timeout_task['priority']}', Time: {updated_timeout_task['scheduled_time']}.")
    
    # 6. Test Case 5: Overlap and Shifting Scheduler
    print("\n[Step 6] Testing Overlap & Shifting Scheduler...")
    # Clean/Reset DB again to have a clean schedule state
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Ingest Task 1: High priority
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent design meeting tomorrow"})
    assert status == 200
    task1 = res1["task"]
    assert task1["status"] == "SCHEDULED"
    assert task1["priority"] == "High"
    
    # Ingest Task 2: Low priority with same deadline/time
    # Since it's low priority and overlaps, it should be back-shifted
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority clean the garage tomorrow"})
    assert status == 200
    task2 = res2["task"]
    
    # Retrieve updated tasks to verify scheduled times
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    # Assert Task 1 priority rank is higher and starts at the original or resolved slot
    # Assert Task 2 is shifted
    t1 = next(t for t in tasks if t["id"] == task1["id"])
    t2 = next(t for t in tasks if t["id"] == task2["id"])
    
    assert len(t1["allocations"]) > 0, "Task 1 should have allocations"
    assert len(t2["allocations"]) > 0, "Task 2 should have allocations"
    alloc1 = t1["allocations"][0]
    alloc2 = t2["allocations"][0]
    assert alloc1["start_time"] != alloc2["start_time"], f"Tasks should not overlap! Task 1: {alloc1['start_time']}, Task 2: {alloc2['start_time']}"
    print(f"Overlap Resolution OK: Task 1 '{t1['title']}' at {alloc1['start_time']} and Task 2 '{t2['title']}' scheduled at {alloc2['start_time']}.")
    
    # 7. Test Case 6: 6-Hour Budget & Allocation Splitting
    print("\n[Step 7] Testing 6-Hour Budget & Allocation Splitting...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Ingest Task 1: Math test tomorrow (takes 5 hours / 300 mins)
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    
    # Ingest Task 2: Geography test tomorrow (takes 3 hours / 180 mins)
    # Day limit: 360 mins (6 hours). Math test (300) leaves 60 mins.
    # So Geography test must split: 60 mins scheduled tomorrow, 120 mins next day!
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority geography test tomorrow"})
    assert status == 200
    
    # Retrieve tasks to check allocations
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    t_geography = next(t for t in tasks if "geography" in t["title"].lower())
    assert len(t_geography["allocations"]) > 1, "Geography task should have split allocations!"
    print(f"6-Hour Budget OK: Split allocations created successfully: {t_geography['allocations']}.")

    # 8. Test Case 7: Task Completion Feedback and Rescheduling
    print("\n[Step 8] Testing Completion Feedback...")
    status, res_comp = make_request(f"/api/tasks/{t_geography['id']}/complete", "POST", {"completed": True, "actual_duration_mins": 240})
    assert status == 200
    assert res_comp["task_status"] == "COMPLETED"
    
    # Check completed task fields
    status, updated_task = make_request(f"/api/tasks/{t_geography['id']}")
    assert status == 200
    assert updated_task["status"] == "COMPLETED"
    assert updated_task["actual_duration_mins"] == 240
    print("Completion Feedback OK: Task marked COMPLETED and actual duration recorded.")

    # 9. Test Case 8: Rescheduling on Completion Failure ("No" Ticks)
    print("\n[Step 9] Testing Rescheduling on completion failure...")
    # Create another task
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule client checkup"})
    assert status == 200
    task_checkup = res["task"]
    
    # Complete follow-up to schedule it
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Make it high priority tomorrow"})
    assert status == 200
    
    # Try completing it with False (No tick)
    status, res_resched = make_request(f"/api/tasks/{task_checkup['id']}/complete", "POST", {"completed": False})
    assert status == 200
    assert res_resched["task_status"] == "SCHEDULED"
    
    # Check that allocations are recreated
    status, updated_task = make_request(f"/api/tasks/{task_checkup['id']}")
    assert status == 200
    assert len(updated_task["allocations"]) > 0, "Allocations should be recreated!"
    print("Rescheduling OK: Task correctly rescheduled after completion failure.")
    
    # 10. Test Case 9: Decimal Priority Scoring
    print("\n[Step 10] Testing Decimal Priority Scoring...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Task 1: High priority homework (takes 2 hours / 120 mins)
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent school homework tomorrow"})
    assert status == 200
    t1 = res1["task"]
    
    # Task 2: High priority math test (takes 5 hours / 300 mins)
    # Math test has larger duration, so its decimal score should be higher and it should get rank 1!
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    t2 = res2["task"]
    
    # Retrieve updated tasks to verify priority ranks
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    db_t1 = next(t for t in tasks if t["id"] == t1["id"])
    db_t2 = next(t for t in tasks if t["id"] == t2["id"])
    
    assert db_t2["priority_rank"] == 1, "The longer task (Math test) should have priority rank 1!"
    assert db_t1["priority_rank"] == 2, "The shorter task (Homework) should have priority rank 2!"
    print("Decimal Priority OK: Longer task scheduled with higher rank.")

    # 11. Test Case 10: Overdue Rescheduling
    print("\n[Step 11] Testing Overdue Rescheduling...")
    # Clean DB and set a task that we manually mark as overdue
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent design meeting tomorrow"})
    assert status == 200
    t_overdue = res["task"]
    
    # Retrieve database model via backend API and reschedule to new deadline
    new_deadline = (datetime.datetime.utcnow() + datetime.timedelta(days=2)).isoformat()
    status, res_resched = make_request(f"/api/tasks/{t_overdue['id']}/reschedule", "POST", {"deadline": new_deadline})
    assert status == 200
    assert res_resched["status"] == "success"
    
    rescheduled_task = res_resched["task"]
    assert rescheduled_task["status"] == "SCHEDULED"
    assert len(rescheduled_task["allocations"]) > 0
    print("Overdue Rescheduling OK: Overdue task successfully rescheduled to new deadline.")
    
    # 12. Test Case 11: Focus-Based Scheduling
    print("\n[Step 12] Testing Focus-Based Scheduling Peak Hours...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Establish peak active hour by calling tasks 5 times
    current_hour = datetime.datetime.utcnow().hour
    for _ in range(5):
        make_request("/api/tasks")
        
    # Manually fill today's schedule completely using mock events to force task tomorrow
    today_date = datetime.date.today()
    holiday_mock_events = [
        {
            "summary": "Busy event blocking today",
            "description": "Blocking today's slot",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    # Ingest a high-focus task (should start at current_hour tomorrow)
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent design project tomorrow"})
    assert status == 200
    t_focus = res["task"]
    
    # Retrieve details
    status, tasks = make_request("/api/tasks")
    db_t = next(t for t in tasks if t["id"] == t_focus["id"])
    assert len(db_t["allocations"]) > 0
    alloc_start = datetime.datetime.fromisoformat(db_t["allocations"][0]["start_time"])
    
    from backend.app.db import SessionLocal
    from backend.app.services.ml_predictor import get_user_active_hours
    from backend.app.models import UserInteraction
    db = SessionLocal()
    print("DEBUG ACTIVE HOURS:", get_user_active_hours(db, 1))
    print("DEBUG ALLOC START HOUR:", alloc_start.hour)
    for u in db.query(UserInteraction).all():
        print(f"DEBUG INTERACTION: {u.timestamp} (hour {u.timestamp.hour})")
    
    # Reset mock events
    holiday_mock_events = []
    
    assert alloc_start.hour in [current_hour, 9, 11], f"High-focus task should align with peak hour {current_hour}, fallback 9, or continuous-matched 11, got {alloc_start.hour}."
    print(f"Focus-Based Scheduling OK: High-focus task scheduled at hour {alloc_start.hour}.")

    # 13. Test Case 12: Interactive Voice Response Endpoint
    print("\n[Step 13] Testing Interactive Voice Response...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Ingest incomplete task
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule client checkup"})
    assert status == 200
    t_pending = res["task"]
    assert t_pending["status"] == "PENDING_CONTEXT"
    
    # Call respond endpoint
    status, res_resp = make_request(f"/api/tasks/{t_pending['id']}/respond", "POST", {"text": "Make it high priority tomorrow"})
    assert status == 200
    assert res_resp["action"] == "updated_pending_task"
    assert res_resp["task"]["status"] == "SCHEDULED"
    print("Voice Response OK: Responded and scheduled successfully.")

    # 14. Test Case 13: Holiday Work Budget Scaling
    print("\n[Step 14] Testing Holiday Work Budget Scaling...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Mock Durga Puja holiday on tomorrow's date
    tomorrow_date = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).date()
    holiday_mock_events = [
        {
            "summary": "Durga Puja Festive Holiday",
            "description": "Durga Puja holiday celebration",
            "start": {"date": tomorrow_date.isoformat()},
            "end": {"date": (tomorrow_date + datetime.timedelta(days=1)).isoformat()}
        }
    ]
    
    # Math test tomorrow (300 mins)
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    
    # Geography test tomorrow (180 mins)
    # Under holiday budget (360 mins), both should schedule tomorrow (Math 300 + Geo 60)
    # Geography task should get split to start tomorrow!
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority geography test tomorrow"})
    assert status == 200
    
    # Verify allocations for geography tomorrow
    status, tasks = make_request("/api/tasks")
    t_geo = next(t for t in tasks if "geography" in t["title"].lower())
    allocs_tomorrow = [a for a in t_geo["allocations"] if datetime.datetime.fromisoformat(a["start_time"]).date() == tomorrow_date]
    assert len(allocs_tomorrow) > 0, "Geography task should have an allocation on tomorrow's holiday!"
    holiday_mock_events = []
    
    # 15. Test Case 14: Low-Priority Chore Postponement
    print("\n[Step 15] Testing Low-Priority Chore Postponement...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Block today completely using mock event
    today_date = datetime.date.today()
    holiday_mock_events = [
        {
            "summary": "Busy event blocking today",
            "description": "Blocking today's slot",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    # Math test tomorrow (300 mins) - High priority
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    
    # Garage cleaning tomorrow (120 mins) - Low priority
    # Budget tomorrow: 240 mins (weekday) or 360 mins (weekend). Since Math test takes 300 mins,
    # the Low priority task must postpone its deadline by 1 day!
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority clean the garage tomorrow"})
    assert status == 200
    
    # Update duration of clean the garage to 120 mins and reschedule to force postponement
    from backend.app.db import SessionLocal
    db_session = SessionLocal()
    from backend.app.models import Task
    t_garage_db = db_session.query(Task).filter(Task.id == res2["task"]["id"]).first()
    t_garage_db.duration_mins = 120
    db_session.commit()
    from backend.app.services.scheduler import schedule_task
    schedule_task(t_garage_db, db_session, datetime.datetime.utcnow())
    db_session.close()
    
    # Retrieve tasks to check deadlines
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    t_garage = next(t for t in tasks if "garage" in t["title"].lower())
    tomorrow_date = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).date()
    garage_deadline = datetime.datetime.fromisoformat(t_garage["scheduled_time"]).date()
    
    # Reset mock events
    holiday_mock_events = []
    
    assert garage_deadline > tomorrow_date, f"Chore deadline should have been postponed! Got {garage_deadline}, expected after {tomorrow_date}."
    print(f"Chore Postponement OK: Garage cleaning deadline postponed to {garage_deadline}.")
    
    # 16. Test Case 15: Minimum Allocation Coalescing Check
    print("\n[Step 16] Testing Minimum Allocation Coalescing...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Block today completely using mock event
    today_date = datetime.date.today()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    day_after = today_date + datetime.timedelta(days=2)
    
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    # Ingest a task tomorrow taking 210 mins (leaves 30 mins in tomorrow's budget)
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent presentation preparation tomorrow"})
    assert status == 200
    # Update duration of presentation preparation and reschedule
    from backend.app.db import SessionLocal
    db_session = SessionLocal()
    from backend.app.models import Task
    t_pres = db_session.query(Task).filter(Task.id == res1["task"]["id"]).first()
    
    is_weekend = (tomorrow_date.weekday() >= 5)
    budget = 360 if is_weekend else 240
    t_pres.duration_mins = budget - 30
    
    db_session.commit()
    # Trigger rescheduling
    from backend.app.services.scheduler import schedule_task
    schedule_task(t_pres, db_session, datetime.datetime.utcnow())
    
    # Ingest a second task tomorrow (120 mins duration)
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority write code tomorrow"})
    assert status == 200
    # Update duration of write code to 120 mins and reschedule
    t_code = db_session.query(Task).filter(Task.id == res2["task"]["id"]).first()
    t_code.duration_mins = 120
    db_session.commit()
    schedule_task(t_code, db_session, datetime.datetime.utcnow())
    
    # Verify allocations of 'write code'
    status, tasks = make_request("/api/tasks")
    db_t_code = next(t for t in tasks if "code" in t["title"].lower())
    
    print("DEBUG CODE ALLOCATIONS:", db_t_code["allocations"])
    print("DEBUG TOMORROW DATE:", tomorrow_date)
    print("DEBUG DAY AFTER DATE:", day_after)
    
    # Tomorrow should have 0 allocations because 30 mins left is < 60 mins coalescing limit
    allocs_tomorrow = [a for a in db_t_code["allocations"] if datetime.datetime.fromisoformat(a["start_time"]).date() == tomorrow_date]
    assert len(allocs_tomorrow) == 0, f"Should have 0 allocations tomorrow due to coalescing, got: {allocs_tomorrow}"
    
    # All 120 mins should be scheduled in total
    total_allocated_mins = sum(a["duration_mins"] for a in db_t_code["allocations"])
    assert total_allocated_mins == 120, f"Should have 120 mins allocated in total, got {total_allocated_mins}"
    
    # Reset mock events
    holiday_mock_events = []
    print("Allocation Coalescing OK: Tiny slice budget skipped and scheduled fully on next day.")

    # 17. Test Case 16: Reschedule Audit Logs
    print("\n[Step 17] Testing Reschedule Audit Logging...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Block today completely using mock event
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    # Ingest urgent math test tomorrow (300 mins)
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    
    # Ingest low priority garage cleaning tomorrow (120 mins)
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority clean the garage tomorrow"})
    assert status == 200
    
    # Retrieve details
    status, tasks = make_request("/api/tasks")
    db_t_garage = next(t for t in tasks if "garage" in t["title"].lower())
    assert len(db_t_garage["reschedule_logs"]) > 0, "Task should have reschedule logs populated"
    log = db_t_garage["reschedule_logs"][0]
    assert "overflow" in log["reason"].lower() or "collision" in log["reason"].lower()
    
    # Reset mock events
    holiday_mock_events = []
    print(f"Reschedule Audit Logging OK: Log entry recorded successfully. Reason: '{log['reason']}'.")

    # 18. Test Case 17: Local Google Calendar Event Caching
    print("\n[Step 18] Testing Calendar Cache Sync...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Set a mock event in the calendar
    holiday_mock_events = [
        {
            "summary": "Urgent project sync meeting",
            "start": {"dateTime": datetime.datetime.combine(tomorrow_date, datetime.time(10, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(tomorrow_date, datetime.time(11, 0)).isoformat()}
        }
    ]
    
    # Trigger a schedule run (ingesting a task) to populate cache
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent client status tomorrow"})
    assert status == 200
    
    # Verify the event is cached in the SQLite database
    db_session.close()  # Close the old session to avoid stale cache
    
    db_session_new = SessionLocal()
    from backend.app.models import CachedCalendarEvent
    try:
        cached_evs = db_session_new.query(CachedCalendarEvent).all()
        assert len(cached_evs) > 0, "Calendar events should be cached locally in database"
        assert cached_evs[0].summary == "Urgent project sync meeting"
    finally:
        db_session_new.close()
    
    # Reset mock events
    holiday_mock_events = []
    print("Calendar Cache OK: Google calendar event successfully synced to local database cache.")
    
    # 19. Test Case 18: Cognitive Load Focus Threshold Scheduling
    print("\n[Step 19] Testing Cognitive Load / Focus Threshold Scheduling...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Task 1: High focus task next week
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test next week"})
    assert status == 200
    t1 = res1["task"]
    assert t1["focus_score"] >= 3
    
    # Task 2: Another High focus task next week
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent design project next week"})
    assert status == 200
    t2 = res2["task"]
    assert t2["focus_score"] >= 3
    
    # Retrieve tasks to check allocations
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    db_t1 = next(t for t in tasks if t["id"] == t1["id"])
    db_t2 = next(t for t in tasks if t["id"] == t2["id"])
    
    assert len(db_t1["allocations"]) > 0, "Task 1 should have allocations"
    assert len(db_t2["allocations"]) > 0, "Task 2 should have allocations"
    
    day1 = datetime.datetime.fromisoformat(db_t1["allocations"][0]["start_time"]).date()
    day2 = datetime.datetime.fromisoformat(db_t2["allocations"][0]["start_time"]).date()
    
    assert day1 != day2, f"Tasks should be scheduled on different days due to cognitive load limits! Task 1: {day1}, Task 2: {day2}"
    print(f"Cognitive Load Scheduling OK: Task 1 scheduled on {day1}, Task 2 scheduled on {day2}.")

    # 20. Test Case 19: Sequential Task Rescheduling (Dependencies)
    print("\n[Step 20] Testing Sequential Task Chain Rescheduling...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Predecessor task: "Schedule low priority buy paint tomorrow"
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule low priority buy paint tomorrow"})
    assert status == 200
    t1 = res1["task"]
    
    # Successor task: "Schedule high priority paint the house tomorrow"
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule high priority paint the house tomorrow"})
    assert status == 200
    t2 = res2["task"]
    
    # Retrieve tasks to verify schedule ordering
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    db_t1 = next(t for t in tasks if t["id"] == t1["id"])
    db_t2 = next(t for t in tasks if t["id"] == t2["id"])
    
    assert len(db_t1["allocations"]) > 0, "Predecessor task should have allocations"
    assert len(db_t2["allocations"]) > 0, "Successor task should have allocations"
    
    end_t1 = datetime.datetime.fromisoformat(db_t1["allocations"][-1]["end_time"])
    start_t2 = datetime.datetime.fromisoformat(db_t2["allocations"][0]["start_time"])
    
    # Successor must start at least 30 minutes after predecessor completes
    assert start_t2 >= end_t1 + datetime.timedelta(minutes=30), f"Successor should start after predecessor + 30m buffer! Predecessor end: {end_t1}, Successor start: {start_t2}"
    print(f"Sequential Rescheduling OK: Predecessor ends at {end_t1}, Successor starts at {start_t2}.")

    # 21. Test Case 20: Predictive Location Travel Buffers
    print("\n[Step 21] Testing Predictive Location Travel Buffers...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    # Block today completely using mock event to force scheduling tomorrow
    today_date = datetime.date.today()
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    tomorrow_date = (datetime.date.today() + datetime.timedelta(days=1))
    dentist_time = datetime.datetime.combine(tomorrow_date, datetime.time(10, 0))
    
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {
        "text": f"Schedule urgent dentist appointment tomorrow at 10 AM"
    })
    assert status == 200
    
    from backend.app.db import SessionLocal
    db_session = SessionLocal()
    from backend.app.models import Task
    t_dentist = db_session.query(Task).filter(Task.id == res1["task"]["id"]).first()
    t_dentist.scheduled_time = dentist_time
    t_dentist.is_time_deadline = True
    t_dentist.duration_mins = 60
    db_session.commit()
    from backend.app.services.scheduler import schedule_task
    schedule_task(t_dentist, db_session, datetime.datetime.utcnow())
    
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule low priority write code tomorrow"
    })
    assert status == 200
    t_code = db_session.query(Task).filter(Task.id == res2["task"]["id"]).first()
    t_code.duration_mins = 60
    db_session.commit()
    schedule_task(t_code, db_session, datetime.datetime.utcnow())
    db_session.close()
    
    # Reset mock events
    holiday_mock_events = []
    
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    db_t_code = next(t for t in tasks if "code" in t["title"].lower())
    assert len(db_t_code["allocations"]) > 0
    code_start = datetime.datetime.fromisoformat(db_t_code["allocations"][0]["start_time"])
    
    assert code_start >= datetime.datetime.combine(tomorrow_date, datetime.time(11, 0)), f"Write code task should start after travel buffer (>= 11 AM)! Got: {code_start}"
    print(f"Location Travel Buffers OK: Dentist is scheduled at 9-10 AM, Write Code scheduled at {code_start} (after travel buffer).")

    # 22. Test Case 21: Dynamic Bedtime Extension
    print("\n[Step 22] Testing Dynamic Bedtime Extension...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    today_date = datetime.date.today()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        },
        {
            "summary": "Busy tomorrow daytime",
            "start": {"dateTime": datetime.datetime.combine(tomorrow_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(tomorrow_date, datetime.time(20, 0)).isoformat()}
        }
    ]
    
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent presentation preparation tomorrow"})
    assert status == 200
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule urgent math test tomorrow"})
    assert status == 200
    
    db_session = SessionLocal()
    t_pres = db_session.query(Task).filter(Task.id == res1["task"]["id"]).first()
    t_pres.duration_mins = 300
    t_pres.priority = "High"
    db_session.commit()
    schedule_task(t_pres, db_session, datetime.datetime.utcnow())
    
    t_math = db_session.query(Task).filter(Task.id == res2["task"]["id"]).first()
    t_math.duration_mins = 300
    t_math.priority = "High"
    db_session.commit()
    schedule_task(t_math, db_session, datetime.datetime.utcnow())
    db_session.close()
    
    holiday_mock_events = []
    
    status, tasks = make_request("/api/tasks")
    assert status == 200
    
    db_t_pres = next(t for t in tasks if t["id"] == res1["task"]["id"])
    db_t_math = next(t for t in tasks if t["id"] == res2["task"]["id"])
    
    assert len(db_t_pres["allocations"]) > 0
    assert len(db_t_math["allocations"]) > 0
    
    end_t_pres = datetime.datetime.fromisoformat(db_t_pres["allocations"][-1]["end_time"])
    end_t_math = datetime.datetime.fromisoformat(db_t_math["allocations"][-1]["end_time"])
    
    latest_end = max(end_t_pres, end_t_math)
    midnight = datetime.datetime.combine(tomorrow_date, datetime.time(23, 59))
    
    assert latest_end > midnight, f"Scheduler should extend schedule past midnight! Latest end: {latest_end}"
    
    status, notifications = make_request("/api/notifications")
    assert status == 200
    extension_notif = next((n for n in notifications if "extended your active hours tonight" in n["message"]), None)
    assert extension_notif is not None, "Bedtime extension notice notification should be sent!"
    print(f"Bedtime Extension OK: Tasks scheduled up to {latest_end} (past midnight), Notification: '{extension_notif['message']}'.")

    # 23. Test Case 22: Dynamic Urgency
    print("\n[Step 23] Testing Dynamic Urgency...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    from backend.app.services.scheduler import get_global_score
    from backend.app.models import Task
    
    task_urg = Task(
        user_id=1,
        title="Check urgent feedback",
        priority="Medium",
        scheduled_time=datetime.datetime.utcnow() + datetime.timedelta(days=2),
        duration_mins=60
    )
    
    current_time = datetime.datetime.utcnow()
    
    score_far = get_global_score(task_urg, current_time)
    
    task_urg.scheduled_time = current_time + datetime.timedelta(hours=12)
    score_close = get_global_score(task_urg, current_time)
    
    task_urg.scheduled_time = current_time - datetime.timedelta(hours=1)
    score_overdue = get_global_score(task_urg, current_time)
    
    print(f"Dynamic Urgency Scores: Far (2d): {score_far:.2f}, Close (12h): {score_close:.2f}, Overdue (-1h): {score_overdue:.2f}")
    assert score_close > score_far
    assert score_overdue > score_close
    print("Dynamic Urgency OK: Urgency scales up continuously.")

    # 24. Test Case 23: Focus Preemption
    print("\n[Step 24] Testing Focus Preemption...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    import backend.app.services.scheduler as scheduler
    original_get_user_active_hours = scheduler.get_user_active_hours
    scheduler.get_user_active_hours = lambda db, u_id: [10, 14]
    
    today_date = datetime.date.today()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    status, res_low = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule low priority wash the dishes tomorrow"
    })
    assert status == 200
    task_low = res_low["task"]
    
    status, res_high = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent math exam tomorrow"
    })
    assert status == 200
    
    from backend.app.db import SessionLocal
    from backend.app.models import Task as DBTask
    db = SessionLocal()
    
    deadline_time = datetime.datetime.combine(tomorrow_date, datetime.time(18, 0))
    
    db_task_high = db.query(DBTask).filter(DBTask.id == res_high["task"]["id"]).first()
    db_task_high.focus_score = 5
    db_task_high.duration_mins = 60
    db_task_high.scheduled_time = deadline_time
    db_task_high.entity_type = "Chore"
    
    db_task_low = db.query(DBTask).filter(DBTask.id == task_low["id"]).first()
    db_task_low.focus_score = 1
    db_task_low.duration_mins = 60
    db_task_low.scheduled_time = deadline_time
    db.commit()
    
    from backend.app.services.scheduler import schedule_task
    schedule_task(db_task_high, db, current_time)
    
    db.refresh(db_task_high)
    db.refresh(db_task_low)
    
    alloc_high = db_task_high.allocations[0]
    alloc_low = db_task_low.allocations[0]
    
    print(f"Allocated: High-focus at hour {alloc_high.start_time.hour}, Low-focus at hour {alloc_low.start_time.hour}")
    assert alloc_high.start_time.hour == 10
    assert alloc_low.start_time.hour == 14
    
    status, res_project = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent project project project tomorrow"
    })
    assert status == 200
    db_project = db.query(DBTask).filter(DBTask.id == res_project["task"]["id"]).first()
    db_project.focus_score = 5
    db_project.duration_mins = 60
    db_project.scheduled_time = deadline_time
    db_project.entity_type = "Meeting"
    db.commit()
    
    schedule_task(db_project, db, current_time)
    
    db.refresh(db_task_high)
    db.refresh(db_task_low)
    db.refresh(db_project)
    
    alloc_project = db_project.allocations[0]
    alloc_high_new = db_task_high.allocations[0]
    
    print(f"After preemption: New high-priority focus task at hour {alloc_project.start_time.hour}, Old high-focus task pushed to hour {alloc_high_new.start_time.hour}")
    assert alloc_project.start_time.hour == 10
    assert alloc_high_new.start_time.hour == 14
    
    scheduler.get_user_active_hours = original_get_user_active_hours
    holiday_mock_events = []
    db.close()
    print("Focus Preemption OK: Bidirectional fallback and preemption verified.")

    # 25. Test Case 24: Reschedule Fatigue & Starvation
    print("\n[Step 25] Testing Reschedule Fatigue & Starvation...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    from backend.app.db import SessionLocal
    from backend.app.models import Task as DBTask
    from backend.app.services.scheduler import get_global_score
    db = SessionLocal()
    
    from backend.app.models import User as DBUser
    default_user = db.query(DBUser).filter(DBUser.email == "test@example.com").first()
    user_id = default_user.id if default_user else 1
    
    task_low = DBTask(user_id=user_id, title="Low Chore", priority="Low", scheduled_time=datetime.datetime.utcnow(), reschedule_count=0)
    task_high = DBTask(user_id=user_id, title="High Meeting", priority="High", scheduled_time=datetime.datetime.utcnow(), reschedule_count=0)
    db.add(task_low)
    db.add(task_high)
    db.commit()
    
    now = datetime.datetime.utcnow()
    base_low = get_global_score(task_low, now)
    base_high = get_global_score(task_high, now)
    
    task_low.reschedule_count = 5
    task_high.reschedule_count = 1
    db.commit()
    
    score_low = get_global_score(task_low, now)
    score_high = get_global_score(task_high, now)
    
    print(f"Low Task (reschedule=5): {score_low:.2f} (Base: {base_low:.2f})")
    print(f"High Task (reschedule=1): {score_high:.2f} (Base: {base_high:.2f})")
    
    assert abs(score_low - (base_low + 5.0)) < 1e-9
    assert abs(score_high - (base_high + 5.0)) < 1e-9
    
    task_low.reschedule_count = 10
    db.commit()
    score_low_10 = get_global_score(task_low, now)
    assert abs(score_low_10 - (base_low + 10.0)) < 1e-9
    db.close()
    print("Reschedule Fatigue & Starvation OK: Boost matches priority-scaled count.")

    # 26. Test Case 25: Cognitive Fatigue Decay
    print("\n[Step 26] Testing Cognitive Fatigue Decay...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    import backend.app.services.scheduler as scheduler
    original_get_user_active_hours = scheduler.get_user_active_hours
    scheduler.get_user_active_hours = lambda db, u_id: [10, 11, 12, 13]
    
    today_date = datetime.date.today()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    
    holiday_mock_events = [
        {
            "summary": "Busy today",
            "start": {"dateTime": datetime.datetime.combine(today_date, datetime.time(9, 0)).isoformat()},
            "end": {"dateTime": datetime.datetime.combine(today_date, datetime.time(18, 0)).isoformat()}
        }
    ]
    
    status, res1 = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent math study tomorrow"
    })
    status, res2 = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent chemistry study tomorrow"
    })
    status, res3 = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent physics study tomorrow"
    })
    
    db = SessionLocal()
    tasks_to_update = db.query(DBTask).filter(DBTask.title.in_([
        "Math study", "Chemistry study", "Physics study"
    ])).all()
    
    for t in tasks_to_update:
        t.focus_score = 4
        t.duration_mins = 60
        t.scheduled_time = datetime.datetime.combine(tomorrow_date, datetime.time(18, 0))
    db.commit()
    
    from backend.app.services.scheduler import schedule_task
    schedule_task(tasks_to_update[0], db, current_time)
    
    for t in tasks_to_update:
        db.refresh(t)
    
    allocs = [t.allocations[0] for t in tasks_to_update if t.allocations]
    hours = sorted([a.start_time.hour for a in allocs])
    print(f"Scheduled hours for focus tasks: {hours}")
    
    assert hours != [10, 11, 12], f"Focus tasks should not be scheduled back-to-back to exceed 10.0 fatigue!"
    db.close()
    print("Cognitive Fatigue Decay OK: High-focus tasks spaced out or postponed due to fatigue decay constraint.")

    # 27. Test Case 26: Adaptive Duration Prediction
    print("\n[Step 27] Testing Adaptive Duration Prediction...")
    status, res = make_request("/api/users/reset", "POST")
    assert status == 200
    
    db = SessionLocal()
    from backend.app.models import User as DBUser
    default_user = db.query(DBUser).filter(DBUser.email == "test@example.com").first()
    user_id = default_user.id if default_user else 1
    
    for i in range(3):
        t = DBTask(
            user_id=user_id,
            title=f"Completed Chore {i}",
            status="COMPLETED",
            entity_type="Chore",
            actual_duration_mins=90
        )
        db.add(t)
    db.commit()
    
    status, res_new = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule low priority wash the car tomorrow"
    })
    assert status == 200
    task_new = db.query(DBTask).filter(DBTask.id == res_new["task"]["id"]).first()
    
    schedule_task(task_new, db, current_time)
    db.refresh(task_new)
    
    total_duration = sum(a.duration_mins for a in task_new.allocations)
    print(f"Wash the car total duration allocated: {total_duration} mins across {len(task_new.allocations)} allocations")
    assert total_duration == 90, f"Duration should adapt to 90 mins, got {total_duration}"
    
    scheduler.get_user_active_hours = original_get_user_active_hours
    holiday_mock_events = []
    db.close()
    print("Adaptive Duration Prediction OK: Adapted duration to historical completions.")

    # 28. Test Case 27: Google Calendar Sync Deletion & Reschedule
    print("\n[Step 28] Testing Google Calendar Sync Deletion & Reschedule...")
    deleted_event_ids.clear()
    
    # Ingest a task
    status, res_init = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent clean the garage tomorrow"
    })
    assert status == 200
    task_id = res_init["task"]["id"]
    
    db = SessionLocal()
    task_init = db.query(DBTask).filter(DBTask.id == task_id).first()
    schedule_task(task_init, db, current_time)
    db.refresh(task_init)
    
    # Verify initial allocation has a google_event_id
    assert task_init.allocations, "Task allocations should not be empty"
    first_event_id = task_init.allocations[0].google_event_id
    assert first_event_id is not None, "First allocation should have a google_event_id saved"
    print(f"Task scheduled with Google Event ID: {first_event_id}")
    
    # Now, reschedule the task by calling schedule_all_tasks
    from backend.app.services.scheduler import schedule_all_tasks
    schedule_all_tasks(user_id, db, current_time)
    
    # Verify the deleted event ID list contains the first event ID
    print(f"Deleted Event IDs: {deleted_event_ids}")
    assert first_event_id in deleted_event_ids, f"Stale Google Calendar event {first_event_id} should be deleted"
    
    db.close()
    print("Google Calendar Sync Deletion OK: Stale calendar events successfully cleaned up.")

    # 29. Test Case 28: Complete & Delete Calendar Event Cleanup
    print("\n[Step 29] Testing Complete & Delete Calendar Event Cleanup...")
    deleted_event_ids.clear()
    
    # Ingest task A (for completion cleanup testing)
    status, res_a = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent buy groceries tomorrow"
    })
    assert status == 200
    task_a_id = res_a["task"]["id"]
    
    db = SessionLocal()
    task_a = db.query(DBTask).filter(DBTask.id == task_a_id).first()
    schedule_task(task_a, db, current_time)
    db.refresh(task_a)
    event_id_a = task_a.allocations[0].google_event_id
    assert event_id_a is not None
    
    # Complete task A via API and verify cleanup
    status, _ = make_request(f"/api/tasks/{task_a_id}/complete", "POST", {
        "completed": True
    })
    assert status == 200
    assert event_id_a in deleted_event_ids, "Completed task's calendar event should be deleted"
    
    # Ingest task B (for delete cleanup testing)
    status, res_b = make_request("/api/tasks/text-ingest", "POST", {
        "text": "Schedule urgent clean the gutters tomorrow"
    })
    assert status == 200
    task_b_id = res_b["task"]["id"]
    
    task_b = db.query(DBTask).filter(DBTask.id == task_b_id).first()
    schedule_task(task_b, db, current_time)
    db.refresh(task_b)
    event_id_b = task_b.allocations[0].google_event_id
    assert event_id_b is not None
    
    # Delete task B via API and verify cleanup and removal from DB
    deleted_event_ids.clear()
    status, delete_res = make_request(f"/api/tasks/{task_b_id}", "DELETE")
    assert status == 200
    assert event_id_b in deleted_event_ids, "Deleted task's calendar event should be deleted"
    
    # Verify task B is deleted from database
    task_b_db = db.query(DBTask).filter(DBTask.id == task_b_id).first()
    assert task_b_db is None, "Task should be completely deleted from DB"
    
    db.close()
    print("Complete/Delete Calendar Cleanup OK: Stale events cleaned up on complete and task delete.")

    # 30. Test Case 29: Voice Follow-Up Response
    print("\n[Step 30] Testing Voice Follow-Up Response...")
    global mock_transcription_value
    mock_transcription_value = "Make it high priority tomorrow"
    
    # Ingest incomplete task
    status, res = make_request("/api/tasks/text-ingest", "POST", {"text": "Schedule client checkup"})
    assert status == 200
    t_pending = res["task"]
    assert t_pending["status"] == "PENDING_CONTEXT"
    
    # Call voice-respond endpoint with mock WAV bytes
    mock_wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x11\x2b\x00\x00\x11\x2b\x00\x00\x01\x00\x08\x00data\x00\x00\x00\x00"
    status, res_voice = make_multipart_request(f"/api/tasks/{t_pending['id']}/voice-respond", "test.wav", mock_wav_bytes)
    assert status == 200, f"Voice response failed: {res_voice}"
    assert res_voice["transcription"] == "Make it high priority tomorrow", f"Unexpected transcription: {res_voice}"
    assert res_voice["action"] == "updated_pending_task"
    assert res_voice["task"]["status"] == "SCHEDULED"
    
    print("Voice Follow-Up Response OK: Voice respond transcribed and scheduled successfully.")

    print("\n--- All Integration Tests Passed Successfully! ---")

if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(2)
    
    try:
        run_tests()
    except AssertionError as e:
        print(f"\nAssertion Failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during tests: {e}", file=sys.stderr)
        sys.exit(1)
    
    sys.exit(0)
