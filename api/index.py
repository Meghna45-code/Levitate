import os
import sys

# Ensure the root directory and Vercel task environments are in Python's search path
sys.path.append("/var/task")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.app.main import app
except Exception as e:
    print(f"CRITICAL ERROR: Failed to import backend.app.main: {e}", file=sys.stderr)
    print(f"Current sys.path: {sys.path}", file=sys.stderr)
    print(f"Current working directory: {os.getcwd()}", file=sys.stderr)
    raise


