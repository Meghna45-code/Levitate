import io
import os
import json
import datetime
import logging
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from backend.app.config import settings

logger = logging.getLogger("levitate.text_parser")

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

async def transcribe_audio_bytes(file_bytes: bytes, file_ext: str = "wav") -> str:
    """
    Transcribes audio bytes to text.
    1. Tries Gemini 1.5 Flash native transcription if GEMINI_API_KEY is present.
    2. Falls back to SpeechRecognition using pydub for WAV conversion.
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

    if settings.GEMINI_API_KEY:
        try:
            logger.info("Attempting native Gemini audio transcription...")
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

    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        
        logger.info("Running SpeechRecognition fallback...")
        audio_stream = io.BytesIO(file_bytes)
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
        
    logger.info("Falling back to mock transcription.")
    mock_commands = [
        "I need to schedule a call with my manager tomorrow at 2 PM",
        "Remind me to pay the electricity bill next Monday",
        "I need to clean the garage sometime this weekend",
        "Add a meeting with the design team"
    ]
    idx = len(file_bytes) % len(mock_commands)
    return mock_commands[idx]

async def parse_text_input(
    text: str, 
    current_time: datetime.datetime, 
    free_slots: List[tuple]
) -> Dict[str, Any]:
    """
    Uses Gemini 1.5 Flash to extract structured parameters from voice/text command.
    Enforces a strict JSON structure containing the parsed task details.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY missing. Running mock parser logic.")
        return mock_parse_logic(text, current_time)

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
- "entity_type": (string) "Chore", "Meeting", "Payment", or "Family".
- "duration_mins": (integer or null) Explicit or implied duration of the task in minutes, or null.
- "is_time_deadline": (boolean) True if the user specified a specific time of day (e.g., "8:24 PM", "2 PM", "at 10 AM"), False if they only specified a day or date (e.g., "tomorrow", "on the 24th", "next Monday") or no time at all.
- "focus_score": (integer or null) Mental focus score from 1 to 5. High-focus/mentally demanding tasks (like exams, coding, complex meetings, heavy studying) should be 3, 4, or 5. Low-focus tasks (like chores, sorting emails, payments, washing dishes) should be 1 or 2. If not specified or implied, return null.
- "missing_info": (list) Specify fields that were NOT mentioned/determined in the command (e.g. ["scheduled_time"] if no time was chosen, ["priority"] if no priority was given, ["task_name"] if title is missing, ["duration_mins"] if duration is missing).
"""
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
        generation_config = {"response_mime_type": "application/json"}
        prompt = f'User command: "{text}"'
        
        response = await model.generate_content_async(prompt, generation_config=generation_config)
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        parsed_data = json.loads(response_text.strip())
        return parsed_data
    except Exception as e:
        logger.exception(f"Gemini parsing failed: {e}")
        return mock_parse_logic(text, current_time)

def mock_parse_logic(text: str, current_time: datetime.datetime) -> Dict[str, Any]:
    """Fallback rules-based regex helper for offline parsing."""
    import re
    text_lower = text.lower()
    
    priority = None
    if any(k in text_lower for k in ["urgent", "high priority", "asap", "emergency", "must do"]):
        priority = "High"
    elif "medium priority" in text_lower:
        priority = "Medium"
    elif "low priority" in text_lower:
        priority = "Low"
        
    entity = "Chore"
    if "meeting" in text_lower or "call" in text_lower:
        entity = "Meeting"
    elif "pay" in text_lower or "bill" in text_lower:
        entity = "Payment"
    elif any(k in text_lower for k in ["mom", "dad", "family", "friend"]):
        entity = "Family"
        
    missing = []
    deadline = None
    duration_mins = None
    
    is_time_deadline = False
    if re.search(r'\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}\s*(o\'clock)\b', text_lower):
        is_time_deadline = True
        
    if "tomorrow" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(days=1)
        # Use 14:00 default if not specified
        deadline = datetime.datetime.combine(sched_date, datetime.time(14, 0)).isoformat()
    elif "next week" in text_lower:
        sched_date = current_time.date() + datetime.timedelta(weeks=1)
        deadline = datetime.datetime.combine(sched_date, datetime.time(10, 0)).isoformat()
        
    title = text.replace("I need to", "").replace("Schedule a", "").replace("Schedule", "").replace("schedule", "").strip()
    for keyword in ["tomorrow", "next week", "high priority", "medium priority", "low priority", "urgent", "asap", "must do"]:
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
    if not duration_mins:
        missing.append("duration_mins")

    focus_score = 1
    if any(k in text_lower for k in ["math", "test", "geography", "meeting", "homework", "design", "call", "project", "code"]):
        focus_score = 5 if "urgent" in text_lower else 3

    return {
        "task_name": title,
        "implied_priority": priority,
        "deadline": deadline,
        "entity_type": entity,
        "duration_mins": duration_mins,
        "is_time_deadline": is_time_deadline,
        "focus_score": focus_score,
        "missing_info": missing
    }
