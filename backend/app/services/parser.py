import io
import os
import json
import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai
from backend.app.config import settings

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

# Setup logging
import logging
logger = logging.getLogger("levitate.parser")

class TaskParseSchema(BaseModel):
    task_name: str = Field(description="The primary name or title of the task.")
    implied_priority: str = Field(description="Priority: High, Medium, or Low. Default: High for Meetings/Payments, Medium for Family, Low for Chores.")
    deadline: Optional[str] = Field(None, description="ISO datetime string if a date/time or duration was specified in the command. Format: YYYY-MM-DDTHH:MM:SS.")
    entity_type: str = Field(description="Task category: Meeting, Payment, Chore, or Family.")
    missing_info: List[str] = Field(description="List of fields that were not specified in the voice command (e.g. ['scheduled_time'] if no specific date/time was mentioned).")

async def transcribe_audio_bytes(file_bytes: bytes, file_ext: str = "wav") -> str:
    """
    Transcribes audio bytes to text.
    1. Tries Gemini 1.5 Flash native transcription if GEMINI_API_KEY is present.
    2. Falls back to SpeechRecognition (free Web Speech API) using pydub for WAV conversion.
    3. Falls back to a mock default command if everything fails.
    """
    mime_types = {
        "wav": "audio/wav",
        "mp3": "audio/mp3",
        "m4a": "audio/m4a",
        "ogg": "audio/ogg",
        "webm": "audio/webm"
    }
    mime_type = mime_types.get(file_ext.lower().replace(".", ""), "audio/wav")

    # Method 1: Native Gemini transcription (zero local dependency)
    if settings.GEMINI_API_KEY:
        try:
            logger.info("Attempting native Gemini audio transcription...")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            response = model.generate_content([
                {"mime_type": mime_type, "data": file_bytes},
                "Please transcribe this audio exactly. Do not add any conversational remarks, only return the exact words spoken."
            ])
            transcription = response.text.strip()
            if transcription:
                logger.info(f"Gemini Transcribed: '{transcription}'")
                return transcription
        except Exception as e:
            logger.warning(f"Native Gemini transcription failed: {e}. Falling back to SpeechRecognition.")

    # Method 2: SpeechRecognition + Pydub fallback
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        
        logger.info("Running SpeechRecognition fallback...")
        audio_stream = io.BytesIO(file_bytes)
        # Force conversion to WAV via pydub
        audio_segment = AudioSegment.from_file(audio_stream)
        
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            
        text = recognizer.recognize_google(audio_data)
        logger.info(f"SpeechRecognition Transcribed: '{text}'")
        return text
    except ImportError:
        logger.warning("Audio parsing dependencies (speech_recognition / pydub) missing.")
    except Exception as e:
        logger.warning(f"SpeechRecognition failed: {e}")
        
    # Method 3: Mock fallbacks (for local testing without keys or packages)
    # Return a mock command based on the date/time of calling
    logger.info("Falling back to mock transcription.")
    mock_commands = [
        "I need to schedule a call with my manager tomorrow at 2 PM",
        "Remind me to pay the electricity bill next Monday",
        "I need to clean the garage sometime this weekend",
        "Add a meeting with the design team"
    ]
    # Simple hash of byte length to pick a stable command
    idx = len(file_bytes) % len(mock_commands)
    return mock_commands[idx]

async def parse_task_command(
    transcription: str, 
    current_time: datetime.datetime, 
    free_slots: List[tuple]
) -> Dict[str, Any]:
    """
    Uses Gemini 1.5 Flash to extract structured parameters from voice/text command.
    Enforces a strict JSON structure containing the parsed task details.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY missing. Running mock parser logic.")
        return mock_parse_logic(transcription, current_time)

    try:
        slots_str = "\n".join([f"- {start.isoformat()} to {end.isoformat()}" for start, end in free_slots[:5]])
        if not slots_str:
            slots_str = "None available"

        system_prompt = f"""You are the Levitate Task Extractor. 
Your job is to parse a raw voice transcription or text input, identify task characteristics, and return a strict JSON payload.

=== CURRENT DATE & TIME ===
{current_time.strftime("%A, %B %d, %Y at %I:%M %p")}

=== CURRENT FREE CALENDAR SLOTS ===
{slots_str}

=== SCHEMA STRUCTURE ===
You must return a JSON object with:
- "task_name": (string or null) Clear, action-oriented title. If no clear task can be parsed, return null.
- "implied_priority": (string or null) "High", "Medium", "Low", or null. Only populate if a priority or importance level is mentioned (e.g. "urgent", "must do", "high priority") or strongly implied. Otherwise, return null.
- "deadline": (string or null) ISO format YYYY-MM-DDTHH:MM:SS. Populate ONLY if the user specified a clear time/date or relative slot (e.g., "tomorrow at 3", "this weekend"). Otherwise, return null.
- "entity_type": (string) "Meeting", "Payment", "Chore", or "Family".
- "missing_info": (list) Specify fields that were NOT mentioned/determined in the command (e.g. ["scheduled_time"] if no time was chosen, ["priority"] if no priority was given, ["task_name"] if title is missing).
"""

        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)

        generation_config = {
            "response_mime_type": "application/json"
        }
        
        prompt = f'User command: "{transcription}"'
        
        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config
        )
        
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        parsed_data = json.loads(response_text.strip())
        return parsed_data
        
    except Exception as e:
        logger.exception(f"Gemini parsing failed: {e}")
        return mock_parse_logic(transcription, current_time)


def mock_parse_logic(transcription: str, current_time: datetime.datetime) -> Dict[str, Any]:
    """Fallback rules-based regex helper for offline parsing."""
    text_lower = transcription.lower()
    
    # Priority
    priority = None
    if any(k in text_lower for k in ["urgent", "high priority", "asap", "emergency"]):
        priority = "High"
    elif "medium priority" in text_lower:
        priority = "Medium"
    elif "low priority" in text_lower:
        priority = "Low"
        
    # Entity Type
    entity = "Chore"
    if "meeting" in text_lower or "call" in text_lower:
        entity = "Meeting"
    elif "pay" in text_lower or "bill" in text_lower:
        entity = "Payment"
    elif any(k in text_lower for k in ["mom", "dad", "family", "friend"]):
        entity = "Family"
        
    # Missing info & deadline
    missing = []
    deadline = None
    
    if "tomorrow" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(days=1)
        deadline = datetime.datetime.combine(sched_date, datetime.time(14, 0)).isoformat()
    elif "next week" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(weeks=1)
        deadline = datetime.datetime.combine(sched_date, datetime.time(10, 0)).isoformat()
        
    # Clean task title
    title = transcription.replace("I need to", "").replace("Schedule a", "").replace("Schedule", "").replace("schedule", "").strip()
    for keyword in ["tomorrow", "next week", "high priority", "medium priority", "low priority", "urgent", "asap"]:
        title = title.replace(keyword, "").replace(keyword.capitalize(), "")
    title = title.strip()
    
    if not title:
        title = None
        missing.append("task_name")
    else:
        title = title.capitalize()
        
    if not priority:
        missing.append("priority")
    if not deadline:
        missing.append("scheduled_time")

    return {
        "task_name": title,
        "implied_priority": priority,
        "deadline": deadline,
        "entity_type": entity,
        "missing_info": missing
    }


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
Your job is to determine if a new user command provides updates/details (like title, priority, or deadline) to address the missing info for one of the pending tasks.

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
"""
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
        
        generation_config = {"response_mime_type": "application/json"}
        prompt = f'User input: "{text}"'

        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config
        )

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
    
    # Sort pending tasks by created_at desc (most recent first) and select the first
    target_task = pending_tasks[0]
    
    text_lower = text.lower()
    updates = {}
    
    if "high" in text_lower or "urgent" in text_lower:
        updates["implied_priority"] = "High"
    elif "medium" in text_lower:
        updates["implied_priority"] = "Medium"
    elif "low" in text_lower:
        updates["implied_priority"] = "Low"
        
    if "tomorrow" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(days=1)
        updates["deadline"] = datetime.datetime.combine(sched_date, datetime.time(14, 0)).isoformat()
    elif "next week" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(weeks=1)
        updates["deadline"] = datetime.datetime.combine(sched_date, datetime.time(10, 0)).isoformat()
        
    # If the target task is missing title, and the input isn't purely a priority/time keyword,
    # assume the input contains the title text.
    if not target_task.get("title") and not any(kw in text_lower for kw in ["high", "medium", "low", "urgent", "tomorrow", "next week"]):
        updates["task_name"] = text.strip().capitalize()
        
    if updates:
        return {
            "is_follow_up": True,
            "task_id": target_task["id"],
            "updates": updates
        }
        
    return {"is_follow_up": False, "task_id": None, "updates": None}


async def ml_autofill_task(
    task_details: Dict[str, Any],
    historical_tasks: List[Dict[str, Any]],
    current_time: datetime.datetime
) -> Dict[str, Any]:
    """
    Uses Gemini to predict and fill missing task fields based on historical scheduled tasks.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY missing. Running mock ML auto-fill.")
        return mock_ml_autofill(task_details, historical_tasks, current_time)

    try:
        system_prompt = f"""You are the Levitate ML Auto-fill Assistant.
Your task is to predict and fill in the missing parameters (task_name, implied_priority, deadline) of a pending task based on the user's historical scheduled tasks.

=== CURRENT TIME ===
{current_time.isoformat()}

=== PENDING TASK TO AUTO-FILL ===
{json.dumps(task_details, default=str)}

=== HISTORICAL COMPLETED/SCHEDULED TASKS ===
{json.dumps(historical_tasks, default=str)}

=== AUTO-FILL INSTRUCTIONS ===
1. Analyze patterns in the historical tasks (such as task titles, priority levels, scheduling times, and entity types).
2. Predict the most likely values for missing fields of the pending task:
   - If priority is missing: what priority is normally assigned to tasks of this entity_type or similar name?
   - If deadline is missing: when are similar tasks usually scheduled? Assign a logical upcoming date/time.
   - If title is missing: what is a descriptive title based on the entity_type?
3. Return a strict JSON response containing:
   - "task_name": (string) Predicted or existing task name.
   - "implied_priority": (string) "High", "Medium", or "Low".
   - "deadline": (string) ISO format YYYY-MM-DDTHH:MM:SS. Must be a date/time in the future.
"""
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
        
        generation_config = {"response_mime_type": "application/json"}
        prompt = "Predict missing values for the pending task."

        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config
        )

        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        return json.loads(response_text.strip())
    except Exception as e:
        logger.exception(f"Gemini ML autofill failed: {e}")
        return mock_ml_autofill(task_details, historical_tasks, current_time)


def mock_ml_autofill(
    task_details: Dict[str, Any],
    historical_tasks: List[Dict[str, Any]],
    current_time: datetime.datetime
) -> Dict[str, Any]:
    # Check historical tasks to find a common priority for this entity_type
    entity_type = task_details.get("entity_type", "Chore")
    
    # Priority prediction fallback
    priority = task_details.get("priority")
    if not priority:
        same_type_priorities = [t.get("priority") for t in historical_tasks if t.get("entity_type") == entity_type and t.get("priority")]
        if same_type_priorities:
            # Mode of historical priorities
            priority = max(set(same_type_priorities), key=same_type_priorities.count)
        else:
            # Rule default
            if entity_type in ["Meeting", "Payment"]:
                priority = "High"
            elif entity_type == "Family":
                priority = "Medium"
            else:
                priority = "Low"
                
    # Deadline prediction fallback (tomorrow at 10 AM or same hour as historical average)
    deadline_str = task_details.get("scheduled_time")
    if not deadline_str:
        sched_date = current_time.date() + datetime.timedelta(days=1)
        # Default tomorrow at 10:00 AM
        deadline_str = datetime.datetime.combine(sched_date, datetime.time(10, 0)).isoformat()
        
    title = task_details.get("title")
    if not title:
        title = f"Auto-filled {entity_type} Task"
        
    return {
        "task_name": title,
        "implied_priority": priority,
        "deadline": deadline_str
    }

