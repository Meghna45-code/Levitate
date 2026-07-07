import os
from dotenv import load_dotenv

# Load from backend/.env if it exists
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(backend_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    load_dotenv()  # Fallback to system env or root .env

class Settings:
    PROJECT_NAME: str = "Levitate Voice Scheduling Assistant"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./levitate.db")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-prod")
    PENDING_TIMEOUT_SECONDS: int = int(os.getenv("PENDING_TIMEOUT_SECONDS", "3600"))

settings = Settings()
