import logging
from backend.app.models import Task

logger = logging.getLogger("levitate.conversational_helper")

def generate_voice_friendly_question(task: Task) -> str:
    """
    Inspects missing fields of a pending task and returns a highly conversational,
    natural, voice-friendly question to query the user for details.
    """
    missing = []
    if not task.title:
        missing.append("name")
    if not task.priority:
        missing.append("priority")
    if not task.scheduled_time:
        missing.append("deadline")
    if not task.duration_mins:
        missing.append("duration")
        
    if len(missing) == 4:
        return "I heard your instruction, but I'm missing the task name, deadline, priority, and duration. Could you tell me what task you would like to schedule, when it's due, how urgent it is, and how long it will take?"
        
    # specific name missing logic
    if "name" in missing:
        return "I heard your instruction, but I didn't catch the task name. What should I call this task?"
        
    # single missing field
    if len(missing) == 1:
        field = missing[0]
        if field == "priority":
            return f"I've noted down '{task.title}', but how urgent is it? Is it high, medium, or low priority?"
        elif field == "deadline":
            return f"I've scheduled '{task.title}', but I don't know the deadline. When is it due?"
        elif field == "duration":
            return f"I've scheduled '{task.title}', but I don't know the duration. How long is it going to take?"
            
    # double missing fields
    if len(missing) == 2:
        if "priority" in missing and "deadline" in missing:
            return f"I've noted down '{task.title}', but I'm missing its deadline and priority. When is it due, and how urgent is it?"
        elif "priority" in missing and "duration" in missing:
            return f"I've noted down '{task.title}', but how urgent is it, and how long will it take?"
        elif "deadline" in missing and "duration" in missing:
            return f"I've scheduled '{task.title}', but when is it due, and how long will it take?"
            
    # General fallback
    fields_str = " and ".join(missing) if len(missing) == 2 else ", ".join(missing[:-1]) + ", and " + missing[-1]
    return f"I have scheduled '{task.title or 'your task'}', but I'm missing the {fields_str}. Could you provide these details?"
