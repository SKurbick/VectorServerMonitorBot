import json
import os
import tempfile
from datetime import datetime, timezone
from app.config import STATE_FILE


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict):
    state_dir = os.path.dirname(STATE_FILE)
    os.makedirs(state_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=state_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def should_alert(state: dict, key: str, repeat_min: int) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    last = state.get(key)
    if last is None or (now - last) >= repeat_min * 60:
        state[key] = now
        return True
    return False
