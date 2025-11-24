# config.py

import json
from pathlib import Path

# The paths defined in your original app.py
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / "config.json"

def load_config():
    """Loads configuration settings from config.json."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            # Return empty config if file is corrupted
            pass
    return {}

def save_config(cfg_dict):
    """Saves configuration settings to config.json."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg_dict, f, indent=4)
        return True
    except Exception:
        return False