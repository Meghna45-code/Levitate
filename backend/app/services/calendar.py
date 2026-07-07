import json
import datetime
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from backend.app.config import settings
from backend.app.models import User

# Standard read/write scope for Calendar events
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_oauth_flow(state=None):
    """Initializes Google OAuth Flow from client config settings."""
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI]
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow

def save_user_credentials(db: Session, email: str, credentials) -> User:
    """Saves serialized Google credentials for a user in the database."""
    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, google_credentials=json.dumps(creds_data))
        db.add(user)
    else:
        user.google_credentials = json.dumps(creds_data)
    
    db.commit()
    db.refresh(user)
    return user

def load_user_credentials(user: User) -> Credentials:
    """Loads and deserializes Credentials object for a user. Refreshes if expired."""
    if not user.google_credentials:
        raise ValueError(f"No Google credentials configured for user: {user.email}")
        
    creds_dict = json.loads(user.google_credentials)
    creds = Credentials(
        token=creds_dict.get('token'),
        refresh_token=creds_dict.get('refresh_token'),
        token_uri=creds_dict.get('token_uri'),
        client_id=creds_dict.get('client_id'),
        client_secret=creds_dict.get('client_secret'),
        scopes=creds_dict.get('scopes')
    )
    
    # Refresh token if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save updated credentials back to db
            creds_data = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
            # Since we don't pass the DB session in directly to load_user_credentials in all places,
            # callers can save, but we can also handle refresh in a separate save_credentials flow.
            # For simplicity, we just return the refreshed creds.
        except Exception as e:
            print(f"Error refreshing credentials: {e}")
            
    return creds

def get_calendar_service(user: User):
    """Builds and returns Google Calendar API client."""
    creds = load_user_credentials(user)
    return build('calendar', 'v3', credentials=creds)

def get_calendar_events(user: User, start_time: datetime.datetime, end_time: datetime.datetime):
    """Fetches list of events on user's calendar for a specific time range."""
    try:
        service = get_calendar_service(user)
        # Format times as ISO strings with 'Z' suffix
        time_min_str = start_time.isoformat() + 'Z'
        time_max_str = end_time.isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min_str,
            timeMax=time_max_str,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])
    except Exception as e:
        print(f"Error retrieving calendar events: {e}")
        return []

def get_free_slots(user: User, start_time: datetime.datetime, end_time: datetime.datetime, slot_duration_mins: int = 60):
    """
    Returns list of free datetime blocks (tuples of start and end times) in user's calendar.
    For local development, if no Google credentials are set up, fallback to mock slots.
    """
    if not user.google_credentials:
        # Mock slots for testing (3 slots starting tomorrow)
        tomorrow = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=1), datetime.time(9, 0))
        return [
            (tomorrow + datetime.timedelta(hours=i), tomorrow + datetime.timedelta(hours=i+1))
            for i in range(3)
        ]
        
    events = get_calendar_events(user, start_time, end_time)
    
    # Parse event ranges into datetime objects
    busy_intervals = []
    for event in events:
        start_str = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        end_str = event.get('end', {}).get('dateTime') or event.get('end', {}).get('date')
        if not start_str or not end_str:
            continue
            
        # Parse ISO datetime strings (handling timezone offsets)
        try:
            start_dt = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_dt = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            # Convert to naive or tz-agnostic as per start_time
            if start_time.tzinfo is None and start_dt.tzinfo is not None:
                start_dt = start_dt.replace(tzinfo=None)
            if end_time.tzinfo is None and end_dt.tzinfo is not None:
                end_dt = end_dt.replace(tzinfo=None)
            busy_intervals.append((start_dt, end_dt))
        except ValueError:
            continue
            
    # Simple algorithm to find slot_duration_mins gaps within working hours (9 AM - 6 PM)
    free_slots = []
    current_cursor = start_time
    
    # Max days to search
    days_to_search = (end_time - start_time).days + 1
    
    for day_offset in range(days_to_search):
        search_date = (start_time + datetime.timedelta(days=day_offset)).date()
        # Working hours boundary
        work_start = datetime.datetime.combine(search_date, datetime.time(9, 0))
        work_end = datetime.datetime.combine(search_date, datetime.time(18, 0))
        
        # Adjust start limit on the first day
        if day_offset == 0:
            work_start = max(work_start, start_time)
            
        slot_candidate = work_start
        while slot_candidate + datetime.timedelta(minutes=slot_duration_mins) <= work_end:
            candidate_end = slot_candidate + datetime.timedelta(minutes=slot_duration_mins)
            
            # Check for conflict with any busy interval
            conflict = False
            for b_start, b_end in busy_intervals:
                if max(slot_candidate, b_start) < min(candidate_end, b_end):
                    conflict = True
                    break
                    
            if not conflict:
                free_slots.append((slot_candidate, candidate_end))
                
            # Step forward by 30 mins to search next slot
            slot_candidate += datetime.timedelta(minutes=30)
            
    return free_slots

def create_calendar_event(user: User, title: str, start_time: datetime.datetime, duration_mins: int = 60, entity_type: str = "Chore") -> dict:
    """Inserts a new event on user's primary calendar."""
    if not user.google_credentials:
        # Mock successful insert response
        return {
            "id": "mock_event_id_" + str(int(datetime.datetime.utcnow().timestamp())),
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/mock",
            "summary": title,
            "start": {"dateTime": start_time.isoformat()},
            "end": {"dateTime": (start_time + datetime.timedelta(minutes=duration_mins)).isoformat()}
        }
        
    try:
        service = get_calendar_service(user)
        end_time = start_time + datetime.timedelta(minutes=duration_mins)
        
        event_body = {
            'summary': title,
            'description': f'Created by Levitate assistant (Type: {entity_type})',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'reminders': {
                'useDefault': True,
            },
        }
        
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        return event
    except Exception as e:
        print(f"Error creating calendar event: {e}")
        raise e

def delete_calendar_event(user: User, event_id: str):
    """Deletes an event from the user's primary calendar by ID."""
    if not user.google_credentials or not event_id:
        return
        
    try:
        service = get_calendar_service(user)
        service.events().delete(calendarId='primary', eventId=event_id).execute()
    except Exception as e:
        print(f"Error deleting calendar event {event_id}: {e}")

