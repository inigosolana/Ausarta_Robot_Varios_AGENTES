import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("BRIDGE_SERVER_URL_INTERNAL", "http://backend:8001")
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()
