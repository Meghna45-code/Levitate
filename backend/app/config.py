import os
from dotenv import load_dotenv

# Load from backend/.env if it exists
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(backend_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)
else:
    load_dotenv(override=True)  # Fallback to system env or root .env

class Settings:
    PROJECT_NAME: str = "Levitate Voice Scheduling Assistant"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:////tmp/levitate.db" if os.getenv("VERCEL") else "sqlite:///./levitate.db"
    )
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-prod")
    PENDING_TIMEOUT_SECONDS: int = int(os.getenv("PENDING_TIMEOUT_SECONDS", "3600"))
    
    # SMTP Email Configuration
    SEND_REAL_EMAILS: bool = os.getenv("SEND_REAL_EMAILS", "False").lower() in ("true", "1", "yes")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_SENDER: str = os.getenv("SMTP_SENDER", "")

    def __init__(self):
        # Resolve SQLAlchemy postgres:// schema issue (SQLAlchemy 1.4+ expects postgresql://)
        if self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)

settings = Settings()
