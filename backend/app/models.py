import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from backend.app.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)
    password_hash = Column(String, nullable=True)
    otp_code = Column(String, nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    is_verified = Column(Boolean, default=False)
    # google_credentials stores OAuth tokens (JSON serialized)
    google_credentials = Column(Text, nullable=True)

    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=True)
    priority = Column(String, nullable=True)  # High, Medium, Low, or Null
    status = Column(String, default="PENDING_CONTEXT")  # PENDING_CONTEXT, SCHEDULED, COMPLETED, CANCELLED
    entity_type = Column(String, default="Chore")  # Meeting, Payment, Chore, Family
    
    # Timing fields
    input_received_at = Column(DateTime, default=datetime.datetime.utcnow)
    scheduled_time = Column(DateTime, nullable=True)
    actual_completion_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Added columns for scheduling pipeline
    duration_mins = Column(Integer, default=60, nullable=True)
    context_request_sent = Column(Boolean, default=False)
    priority_rank = Column(Integer, nullable=True)
    is_time_deadline = Column(Boolean, default=False)
    actual_duration_mins = Column(Integer, nullable=True)
    focus_score = Column(Integer, default=1, nullable=False)
    reschedule_count = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="tasks")
    allocations = relationship("TaskAllocation", back_populates="task", cascade="all, delete-orphan")
    reschedule_logs = relationship("TaskRescheduleLog", back_populates="task", cascade="all, delete-orphan")

class TaskAllocation(Base):
    __tablename__ = "task_allocations"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    duration_mins = Column(Integer, nullable=False)
    google_event_id = Column(String, nullable=True)

    task = relationship("Task", back_populates="allocations")

class UserInteraction(Base):
    __tablename__ = "user_interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
    task = relationship("Task")

class TaskRescheduleLog(Base):
    __tablename__ = "task_reschedule_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    old_time = Column(DateTime, nullable=True)
    new_time = Column(DateTime, nullable=False)
    reason = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="reschedule_logs")

class CachedCalendarEvent(Base):
    __tablename__ = "cached_calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(String, unique=True, index=True, nullable=True)
    summary = Column(String, nullable=True)
    description = Column(String, nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_holiday = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
