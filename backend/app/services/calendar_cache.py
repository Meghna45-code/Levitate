import datetime
from sqlalchemy.orm import Session
from backend.app.models import User, CachedCalendarEvent
from backend.app.services.calendar import get_calendar_events

CACHE_TTL_SECONDS = 10
last_sync_times = {}

def sync_calendar_cache(user: User, db: Session):
    """
    Fetches events from Google Calendar API and updates CachedCalendarEvent table.
    """
    # Delete existing cached events for this user
    db.query(CachedCalendarEvent).filter(CachedCalendarEvent.user_id == user.id).delete()
    
    # Fetch events for the next 30 days
    start_search = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    end_search = start_search + datetime.timedelta(days=30)
    
    try:
        events = get_calendar_events(user, start_search, end_search)
    except Exception:
        events = []
        
    holiday_keywords = ["holiday", "puja", "ganpati", "ganesha", "chaturthi", "diwali", "christmas", "eid", "dussehra", "navratri"]
    
    for ev in events:
        s_str = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
        e_str = ev.get('end', {}).get('dateTime') or ev.get('end', {}).get('date')
        if s_str and e_str:
            try:
                # Handle timezones or date-only
                s_dt = datetime.datetime.fromisoformat(s_str.replace('Z', '+00:00')).replace(tzinfo=None)
                e_dt = datetime.datetime.fromisoformat(e_str.replace('Z', '+00:00')).replace(tzinfo=None)
                
                title = (ev.get("summary") or "").lower()
                desc = (ev.get("description") or "").lower()
                is_h = any(k in title or k in desc for k in holiday_keywords)
                
                cached_event = CachedCalendarEvent(
                    user_id=user.id,
                    event_id=ev.get("id"),
                    summary=ev.get("summary"),
                    description=ev.get("description"),
                    start_time=s_dt,
                    end_time=e_dt,
                    is_holiday=is_h
                )
                db.add(cached_event)
            except Exception:
                pass
    db.commit()

def get_cached_calendar_events(user: User, db: Session) -> list:
    """
    Retrieves events from the local database cache.
    Triggers sync if the cache is stale.
    """
    now = datetime.datetime.utcnow()
    last_sync = last_sync_times.get(user.id)
    
    if last_sync is None or (now - last_sync).total_seconds() > CACHE_TTL_SECONDS:
        sync_calendar_cache(user, db)
        last_sync_times[user.id] = now
        
    cached_events = db.query(CachedCalendarEvent).filter(
        CachedCalendarEvent.user_id == user.id
    ).all()
    
    # Convert DB models to dict structure expected by the scheduler
    event_dicts = []
    for ev in cached_events:
        event_dicts.append({
            "id": ev.event_id,
            "summary": ev.summary,
            "description": ev.description,
            "start": {
                "dateTime": ev.start_time.isoformat()
            },
            "end": {
                "dateTime": ev.end_time.isoformat()
            }
        })
    return event_dicts
