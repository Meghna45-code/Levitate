import os
import sys

# Ensure the root directory and Vercel task environments are in Python's search path
sys.path.append("/var/task")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.app.main import app





