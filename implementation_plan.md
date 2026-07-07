# Implementation Plan: Google Calendar Two-Way Sync & Deletion (Option A)

This plan details how to resolve the Google Calendar event duplication and clutter bug by implementing Option A (Delete & Recreate) sync.

## User Review Required

> [!IMPORTANT]
> This change introduces a schema modification to the `task_allocations` table. To apply this locally, we will drop the local `levitate.db` database file and let SQLAlchemy recreate it automatically with the new schema. This will reset all current database state (mock users and tasks will be re-created fresh during the integration tests).

---

## Proposed Changes

### 1. Database Model (`TaskAllocation`)
*   **Modify**: [models.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/models.py)
*   **Change**: Add `google_event_id = Column(String, nullable=True)` to the `TaskAllocation` model.

### 2. Google Calendar API Helper (`delete_calendar_event`)
*   **Modify**: [calendar.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/services/calendar.py)
*   **Change**: Implement a new `delete_calendar_event(user, event_id)` function.
    *   If `user.google_credentials` is not configured, it acts as a silent mock return.
    *   If credentials exist, it calls:
        `service.events().delete(calendarId='primary', eventId=event_id).execute()`

### 3. Scheduler Rescheduling Deletion (`schedule_all_tasks`)
*   **Modify**: [scheduler.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/services/scheduler.py)
*   **Change**:
    *   Before deleting existing `TaskAllocation` database records (e.g. `db.query(TaskAllocation).filter(TaskAllocation.task_id == t.id).delete()`), retrieve all allocations for the target tasks.
    *   For each allocation that has a non-null `google_event_id`, invoke `delete_calendar_event` to remove the stale event from Google Calendar.

### 4. Scheduler Calendar Creation (`schedule_task`)
*   **Modify**: [scheduler.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/services/scheduler.py)
*   **Change**:
    *   Capture the return value of `create_calendar_event`.
    *   Extract the returned event ID: `event.get("id")`.
    *   Save this event ID into the database allocation record: `alloc.google_event_id = event_id` and commit.

---

## Verification Plan

### Automated Integration Tests
We will add a new test case to [test_pipeline.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/test_pipeline.py):
1. **Test Case 28 (Calendar Event Deletion & Rescheduling Sync)**:
   * Mock the Google Calendar API calls so that `create_calendar_event` returns a mock event ID, and `delete_calendar_event` is tracked.
   * Schedule a task to create its initial allocation.
   * Modify the task to trigger a reschedule (e.g., change time or priority).
   * Verify that `delete_calendar_event` was called with the old mock event ID, and the database now has a new allocation with a new mock event ID.
