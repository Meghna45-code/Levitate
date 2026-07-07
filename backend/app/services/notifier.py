import logging
from sqlalchemy.orm import Session
from backend.app.models import Notification, Task

logger = logging.getLogger("levitate.notifier")

def send_missing_info_notification(db: Session, task: Task, message: str) -> Notification:
    """
    Sends/creates a notification asking the user to fill the required missing task details.
    Triggered after 15 minutes of the first instruction (File B logic).
    """
    noti = Notification(
        user_id=task.user_id,
        task_id=task.id,
        message=message
    )
    db.add(noti)
    db.commit()
    db.refresh(noti)
    logger.info(f"Missing info notification sent for task {task.id}: {message}")
    return noti

def send_scheduled_notification(db: Session, task: Task, message: str) -> Notification:
    """
    Sends/creates a notification indicating a task is successfully scheduled.
    """
    noti = Notification(
        user_id=task.user_id,
        task_id=task.id,
        message=message
    )
    db.add(noti)
    db.commit()
    db.refresh(noti)
    logger.info(f"Scheduled notification sent for task {task.id}: {message}")
    return noti

def send_task_reminder_notification(db: Session, task: Task, message: str) -> Notification:
    """
    Sends/creates a task reminder notification (e.g. start, end, or buffer reminders).
    """
    noti = Notification(
        user_id=task.user_id,
        task_id=task.id,
        message=message
    )
    db.add(noti)
    db.commit()
    db.refresh(noti)
    logger.info(f"Task reminder notification sent for task {task.id}: {message}")
    return noti

def send_simultaneous_notification(db: Session, task1: Task, task2: Task) -> Notification:
    """
    Sends a warning notification to the user that two tasks run simultaneously.
    """
    message = f"Warning: Task '{task1.title}' and Task '{task2.title}' are scheduled at the same time ({task1.scheduled_time.strftime('%I:%M %p')}) and must be performed simultaneously."
    return send_task_reminder_notification(db, task1, message)
