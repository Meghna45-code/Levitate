import os
import datetime
import asyncio
import hashlib
import random
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.db import engine, Base, get_db
from backend.app.models import User, Task, Notification
from backend.app.services.calendar import (
    get_oauth_flow, save_user_credentials, get_free_slots, create_calendar_event
)
from backend.app.services.text_parser import transcribe_audio_bytes, parse_text_input
from backend.app.services.task_extractor import (
    check_if_follow_up_input, extract_and_fill_task, process_follow_up_input, check_pending_tasks
)

# Password hashing helpers using standard library pbkdf2_hmac
def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}:{key.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    if not hashed_password or ":" not in hashed_password:
        return False
    salt, hex_key = hashed_password.split(":", 1)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return key.hex() == hex_key

# Authentication Schemas
class SignupSchema(BaseModel):
    username: str
    email: str
    password: str

class VerifyOtpSchema(BaseModel):
    email: str
    otp_code: str

class LoginSchema(BaseModel):
    username: str
    password: str

class ForgotPasswordSchema(BaseModel):
    email: str

class ResetPasswordSchema(BaseModel):
    email: str
    otp_code: str
    new_password: str

class CreateTaskSchema(BaseModel):
    title: str
    duration_mins: int
    scheduled_time: Optional[str] = None
    priority: Optional[str] = None

class TextInputSchema(BaseModel):
    text: str

# Resolve frontend directory path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
frontend_dir = os.path.join(BASE_DIR, "frontend")

# Initialize database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Backend API for the Levitate voice-activated predictive scheduling assistant."
)

# Enable CORS for frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files if frontend folder exists
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# Middleware to log User Interaction
@app.middleware("http")
async def log_user_interaction(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/users/reset") and "api" in request.url.path:
        try:
            from backend.app.db import SessionLocal
            db = SessionLocal()
            try:
                user = get_default_user(db)
                from backend.app.models import UserInteraction
                log = UserInteraction(user_id=user.id)
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass
    return response

# Startup background task initialization
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_autofill_worker())

# Helper function to get or create a default test user
def get_default_user(db: Session) -> User:
    # Try to find the first verified user
    user = db.query(User).filter(User.is_verified == True).first()
    if not user:
        # Fallback to any user
        user = db.query(User).first()
    if not user:
        # Create a default verified user
        user = User(
            email="test@example.com",
            username="testuser",
            password_hash=hash_password("password"),
            is_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.get("/")
def read_root():
    frontend_index = os.path.join(frontend_dir, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "message": "Welcome to Levitate Backend API!"
    }

# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/api/auth/signup")
def signup(payload: SignupSchema, db: Session = Depends(get_db)):
    existing_email = db.query(User).filter(User.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email is already registered")
        
    existing_username = db.query(User).filter(User.username == payload.username).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username is already taken")
        
    otp = f"{random.randint(100000, 999999)}"
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    
    new_user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        otp_code=otp,
        otp_expires_at=expires_at,
        is_verified=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "status": "success",
        "message": "Verification OTP sent. For demo/testing, the OTP is returned in this response.",
        "otp": otp,
        "email": payload.email
    }

@app.post("/api/auth/verify-otp")
def verify_otp(payload: VerifyOtpSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.is_verified:
        return {"status": "success", "message": "User is already verified"}
        
    if user.otp_code != payload.otp_code:
        raise HTTPException(status_code=400, detail="Invalid OTP code")
        
    if user.otp_expires_at and user.otp_expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="OTP code has expired")
        
    user.is_verified = True
    user.otp_code = None
    user.otp_expires_at = None
    db.commit()
    
    return {
        "status": "success",
        "message": "Email verified successfully. Account is now active.",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }

@app.post("/api/auth/login")
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        (User.username == payload.username) | (User.email == payload.username)
    ).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
        
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")
        
    if not user.is_verified:
        raise HTTPException(status_code=400, detail="Please verify your email before logging in")
        
    return {
        "status": "success",
        "message": "Logged in successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }

@app.get("/api/auth/status")
def get_auth_status(db: Session = Depends(get_db)):
    user = get_default_user(db)
    return {
        "status": "success",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "google_connected": user.google_credentials is not None
        }
    }

@app.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")
        
    otp = f"{random.randint(100000, 999999)}"
    user.otp_code = otp
    user.otp_expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    db.commit()
    
    return {
        "status": "success",
        "message": "Reset OTP sent. For demo/testing, the OTP is returned in this response.",
        "otp": otp,
        "email": payload.email
    }

@app.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.otp_code != payload.otp_code:
        raise HTTPException(status_code=400, detail="Invalid OTP code")
        
    if user.otp_expires_at and user.otp_expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="OTP code has expired")
        
    user.password_hash = hash_password(payload.new_password)
    user.otp_code = None
    user.otp_expires_at = None
    user.is_verified = True
    db.commit()
    
    return {
        "status": "success",
        "message": "Password reset successfully. You can now log in."
    }

@app.post("/api/tasks/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...)
):
    """
    Transcribes audio to text.
    Does NOT save to the database.
    """
    file_bytes = await file.read()
    filename = file.filename or "audio.wav"
    file_ext = os.path.splitext(filename)[1].lstrip(".") or "wav"
    
    transcription = await transcribe_audio_bytes(file_bytes, file_ext)
    return {
        "status": "success",
        "transcription": transcription
    }

@app.post("/api/tasks/parse")
async def parse_command(
    payload: TextInputSchema,
    db: Session = Depends(get_db)
):
    """
    Parses a natural language command and returns the extracted fields.
    Does NOT save to the database.
    """
    user = get_default_user(db)
    now = datetime.datetime.utcnow()
    end_window = now + datetime.timedelta(days=3)
    free_slots = get_free_slots(user, now, end_window)
    
    parsed_fields = await parse_text_input(payload.text, now, free_slots)
    
    return {
        "title": parsed_fields.get("task_name"),
        "duration_mins": parsed_fields.get("duration_mins") or 60,
        "scheduled_time": parsed_fields.get("deadline"),
        "priority": parsed_fields.get("implied_priority")
    }

@app.post("/api/tasks")
def create_task_directly(payload: CreateTaskSchema, db: Session = Depends(get_db)):
    user = get_default_user(db)
    
    scheduled_time = None
    if payload.scheduled_time:
        try:
            scheduled_time = datetime.datetime.fromisoformat(payload.scheduled_time)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ISO format for scheduled_time")
            
    from backend.app.services.scheduler import is_high_focus, schedule_task
    focus_score = 3 if is_high_focus(payload.title) else 1
    
    status = "SCHEDULED" if scheduled_time else "PENDING_CONTEXT"
    
    db_task = Task(
        user_id=user.id,
        title=payload.title,
        priority=payload.priority,
        status=status,
        entity_type="Chore",
        scheduled_time=scheduled_time,
        duration_mins=payload.duration_mins,
        focus_score=focus_score
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    if status == "SCHEDULED":
        schedule_task(db_task, db, datetime.datetime.utcnow())
        
    return {
        "status": "success",
        "task": format_task_response(db_task)
    }

# ==================== OAUTH ENDPOINTS ====================

@app.get("/api/auth/google")
def google_auth_redirect():
    """Generates the Google Consent Screen redirect URL."""
    try:
        flow = get_oauth_flow()
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return {"authorization_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize OAuth flow: {str(e)}")

@app.get("/api/auth/google/callback")
def google_auth_callback(code: str, state: Optional[str] = None, db: Session = Depends(get_db)):
    """Handles Google OAuth redirect callback, exchanges token, and saves it."""
    try:
        flow = get_oauth_flow(state=state)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        user = get_default_user(db)
        save_user_credentials(db, user.email, credentials)
        
        return {
            "status": "success",
            "message": f"Successfully authenticated Google account for {user.email}. You can close this window."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to authenticate code: {str(e)}")

# ==================== PIPELINE CORE & HELPERS ====================

async def process_user_input(text: str, db: Session, user: User) -> dict:
    now = datetime.datetime.utcnow()
    
    # 1. Fetch pending tasks created within the timeout period (e.g. 1 hour)
    one_hour_ago = now - datetime.timedelta(seconds=settings.PENDING_TIMEOUT_SECONDS)
    pending_tasks = db.query(Task).filter(
        Task.user_id == user.id,
        Task.status == "PENDING_CONTEXT",
        Task.input_received_at >= one_hour_ago
    ).order_by(Task.input_received_at.desc()).all()
    
    pending_list = [
        {
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "scheduled_time": t.scheduled_time.isoformat() if t.scheduled_time else None,
            "entity_type": t.entity_type,
            "created_at": t.input_received_at.isoformat(),
            "duration_mins": t.duration_mins
        }
        for t in pending_tasks
    ]
    
    # 2. Check if the input is a follow-up addressing a pending task
    follow_up_res = await check_if_follow_up_input(text, pending_list, now)
    
    if follow_up_res.get("is_follow_up") and follow_up_res.get("task_id"):
        task_id = follow_up_res["task_id"]
        updates = follow_up_res.get("updates") or {}
        
        db_task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
        if db_task:
            return await process_follow_up_input(text, db_task, updates, db, now)
            
    # 3. Process as new task
    end_window = now + datetime.timedelta(days=3)
    free_slots = get_free_slots(user, now, end_window)
    
    parsed_task = await parse_text_input(text, now, free_slots)
    return await extract_and_fill_task(parsed_task, db, user, now)

# ==================== TASK & VOICE ENDPOINTS ====================

@app.post("/api/tasks/voice-ingest")
async def voice_ingest(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    """
    Core Voice Ingestion Pipeline:
    1. Transcribes audio file.
    2. Runs text processing to schedule or request context.
    """
    user = get_default_user(db)
    
    file_bytes = await file.read()
    filename = file.filename or "audio.wav"
    file_ext = os.path.splitext(filename)[1].lstrip(".") or "wav"
    
    transcription = await transcribe_audio_bytes(file_bytes, file_ext)
    result = await process_user_input(transcription, db, user)
    result["transcription"] = transcription
    return result

@app.post("/api/tasks/text-ingest")
async def text_ingest(
    payload: TextInputSchema,
    db: Session = Depends(get_db)
):
    """
    Core Text Ingestion Pipeline:
    Processes raw text commands.
    """
    user = get_default_user(db)
    result = await process_user_input(payload.text, db, user)
    return result

def format_task_response(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "priority": t.priority,
        "status": t.status,
        "entity_type": t.entity_type,
        "scheduled_time": t.scheduled_time.isoformat() if t.scheduled_time else None,
        "input_received_at": t.input_received_at.isoformat() if t.input_received_at else None,
        "created_at": t.created_at.isoformat(),
        "is_time_deadline": t.is_time_deadline,
        "duration_mins": t.duration_mins,
        "actual_duration_mins": t.actual_duration_mins,
        "priority_rank": t.priority_rank,
        "focus_score": t.focus_score,
        "allocations": [
            {
                "start_time": a.start_time.isoformat(),
                "end_time": a.end_time.isoformat(),
                "duration_mins": a.duration_mins
            }
            for a in t.allocations
        ],
        "reschedule_logs": [
            {
                "old_time": log.old_time.isoformat() if log.old_time else None,
                "new_time": log.new_time.isoformat(),
                "reason": log.reason,
                "timestamp": log.timestamp.isoformat()
            }
            for log in (t.reschedule_logs or [])
        ]
    }

@app.get("/api/tasks", response_model=List[dict])
def list_tasks(db: Session = Depends(get_db)):
    """Returns all tasks stored in the local database."""
    user = get_default_user(db)
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    return [format_task_response(t) for t in tasks]

@app.get("/api/tasks/overdue", response_model=List[dict])
def list_overdue_tasks(db: Session = Depends(get_db)):
    """Returns all overdue tasks for the default user."""
    user = get_default_user(db)
    tasks = db.query(Task).filter(Task.user_id == user.id, Task.status == "OVERDUE").all()
    return [format_task_response(t) for t in tasks]

@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    """Retrieves a single task detail."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return format_task_response(task)
    
class CompleteTaskSchema(BaseModel):
    completed: bool
    actual_duration_mins: Optional[int] = None
    
@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: CompleteTaskSchema, db: Session = Depends(get_db)):
    """Toggles completion of a task, triggering either saving actual duration or rescheduling."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if payload.completed:
        task.status = "COMPLETED"
        task.actual_completion_time = datetime.datetime.utcnow()
        task.actual_duration_mins = payload.actual_duration_mins or task.duration_mins
        # Clear allocations on completion and delete Google Calendar events
        from backend.app.models import TaskAllocation
        from backend.app.services.calendar import delete_calendar_event
        allocs = db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).all()
        for alloc in allocs:
            if alloc.google_event_id:
                try:
                    delete_calendar_event(user, alloc.google_event_id)
                except Exception as e:
                    print(f"Failed to delete Google Calendar event {alloc.google_event_id} on completion: {e}")
        db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).delete()
    else:
        # Reschedule task - delete previous allocations/calendar events first
        from backend.app.models import TaskAllocation
        from backend.app.services.calendar import delete_calendar_event
        allocs = db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).all()
        for alloc in allocs:
            if alloc.google_event_id:
                try:
                    delete_calendar_event(user, alloc.google_event_id)
                except Exception as e:
                    print(f"Failed to delete Google Calendar event {alloc.google_event_id} on completion: {e}")
        db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).delete()
        task.input_received_at = datetime.datetime.utcnow()
        task.status = "SCHEDULED"
        from backend.app.services.scheduler import schedule_task
        schedule_task(task, db, datetime.datetime.utcnow())
        
    db.commit()
    db.refresh(task)
    return {"status": "success", "task_status": task.status}

class RescheduleTaskSchema(BaseModel):
    deadline: str
    is_time_deadline: Optional[bool] = False
    priority: Optional[str] = None
    duration_mins: Optional[int] = None

@app.post("/api/tasks/{task_id}/reschedule")
def reschedule_task(task_id: int, payload: RescheduleTaskSchema, db: Session = Depends(get_db)):
    """Reschedules an overdue (or any) task to a new deadline with optional priority/duration updates."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    try:
        new_deadline = datetime.datetime.fromisoformat(payload.deadline)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid deadline ISO format.")
        
    # Reset allocations
    from backend.app.models import TaskAllocation
    db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).delete()
    
    task.scheduled_time = new_deadline
    task.is_time_deadline = bool(payload.is_time_deadline)
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.duration_mins is not None:
        task.duration_mins = payload.duration_mins
    task.status = "SCHEDULED"
    task.input_received_at = datetime.datetime.utcnow()
    
    from backend.app.services.scheduler import schedule_task
    schedule_task(task, db, datetime.datetime.utcnow())
    
    db.commit()
    db.refresh(task)
    return {"status": "success", "task": format_task_response(task)}

@app.post("/api/tasks/{task_id}/autofill")
async def trigger_autofill(task_id: int, db: Session = Depends(get_db)):
    """Triggers immediate ML autofill for missing fields on the specified task."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # Fetch historical tasks
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
    
    from backend.app.services.task_extractor import predict_missing_fields
    predictions = await predict_missing_fields(task, history_list, db, datetime.datetime.utcnow())
    
    task.title = predictions.get("task_name") or task.title or f"Auto-filled {task.entity_type}"
    task.priority = predictions.get("implied_priority") or "Low"
    task.status = "SCHEDULED"
    
    from backend.app.services.scheduler import schedule_task
    from backend.app.models import TaskAllocation
    db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).delete()
    schedule_task(task, db, datetime.datetime.utcnow())
    
    db.commit()
    db.refresh(task)
    return {"status": "success", "task": format_task_response(task)}

class FollowUpResponseSchema(BaseModel):
    text: str

@app.post("/api/tasks/{task_id}/respond")
async def respond_to_task(task_id: int, payload: FollowUpResponseSchema, db: Session = Depends(get_db)):
    """Receives a voice or text conversational reply to update a pending task's missing fields."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status != "PENDING_CONTEXT":
        raise HTTPException(status_code=400, detail="Task is not pending additional context.")
        
    from backend.app.services.text_parser import parse_text_input
    from backend.app.services.task_extractor import process_follow_up_input
    
    now = datetime.datetime.utcnow()
    end_window = now + datetime.timedelta(days=3)
    free_slots = get_free_slots(user, now, end_window)
    raw_fields = await parse_text_input(payload.text, now, free_slots)
    result = await process_follow_up_input(payload.text, task, raw_fields, db, now)
    return result

@app.post("/api/tasks/{task_id}/voice-respond")
async def voice_respond_to_task(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Receives an audio follow-up reply, transcribes it, and updates the pending task."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status != "PENDING_CONTEXT":
        raise HTTPException(status_code=400, detail="Task is not pending additional context.")
        
    file_bytes = await file.read()
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".wav"
    
    transcription = await transcribe_audio_bytes(file_bytes, file_ext)
    
    from backend.app.services.text_parser import parse_text_input
    from backend.app.services.task_extractor import process_follow_up_input
    
    now = datetime.datetime.utcnow()
    end_window = now + datetime.timedelta(days=3)
    free_slots = get_free_slots(user, now, end_window)
    raw_fields = await parse_text_input(transcription, now, free_slots)
    result = await process_follow_up_input(transcription, task, raw_fields, db, now)
    result["transcription"] = transcription
    return result


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Deletes a task completely, including all allocations and Google Calendar events."""
    user = get_default_user(db)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # Delete calendar events
    from backend.app.models import TaskAllocation
    from backend.app.services.calendar import delete_calendar_event
    allocs = db.query(TaskAllocation).filter(TaskAllocation.task_id == task.id).all()
    for alloc in allocs:
        if alloc.google_event_id:
            try:
                delete_calendar_event(user, alloc.google_event_id)
            except Exception as e:
                print(f"Failed to delete Google Calendar event {alloc.google_event_id} on task deletion: {e}")
                
    db.delete(task)
    db.commit()
    return {"status": "success", "message": "Task and associated calendar events deleted successfully."}

# ==================== NOTIFICATION ENDPOINTS ====================

@app.get("/api/notifications")
def list_notifications(db: Session = Depends(get_db)):
    """Returns all notifications for the default user."""
    user = get_default_user(db)
    notifications = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).all()
    return [
        {
            "id": n.id,
            "task_id": n.task_id,
            "message": n.message,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat()
        }
        for n in notifications
    ]

@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    """Marks a specific notification as read."""
    user = get_default_user(db)
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == user.id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    return {"status": "success", "message": "Notification marked as read"}

@app.post("/api/users/reset")
def reset_db(db: Session = Depends(get_db)):
    """Utility endpoint to clear data for clean testing runs."""
    from backend.app.models import TaskAllocation, UserInteraction, CachedCalendarEvent
    from backend.app.services.calendar_cache import last_sync_times
    
    db.query(Notification).delete()
    db.query(TaskAllocation).delete()
    db.query(UserInteraction).delete()
    db.query(CachedCalendarEvent).delete()
    db.query(Task).delete()
    db.query(User).delete()
    db.commit()
    
    last_sync_times.clear()
    return {"message": "Database tables reset successfully."}

# ==================== BACKGROUND ML AUTOFILL WORKER ====================

async def run_autofill_check(db: Session):
    now = datetime.datetime.utcnow()
    await check_pending_tasks(db, now)

async def periodic_autofill_worker():
    while True:
        try:
            await asyncio.sleep(0.1)  # Check every 0.1 second for responsive testing/runs
            from backend.app.db import SessionLocal
            db = SessionLocal()
            try:
                await run_autofill_check(db)
            finally:
                db.close()
        except Exception as e:
            print(f"Exception in periodic autofill worker loop: {e}")

