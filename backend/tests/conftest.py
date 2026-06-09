import os
import sys
from pathlib import Path


os.environ.setdefault("BRIDGE_SERVER_URL_INTERNAL", "http://backend:8001")
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
