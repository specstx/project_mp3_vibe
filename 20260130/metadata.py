# metadata.py

import os             # For ScannerThread (os.walk, os.path.join)
import json           # For CacheManager (json.load, json.dump)
import time           # For ScannerThread (progress updates)
from pathlib import Path  # For handling file paths (LIB_CACHE, etc.)

# PyQt6 components needed for the ScannerThread
from PyQt6.QtCore import QThread, pyqtSignal 

# Mutagen and ID3 components for tag reading/writing
from mutagen.mp3 import MP3          # To open and save MP3 files
from mutagen.easyid3 import EasyID3  # To handle standard ID3 tags easily
from mutagen.id3 import POPM, ID3    # To handle the custom POPM (rating) tag

# Our custom data model
# NOTE: This import requires you to have a finished 'models.py' file
from models import Song, CacheManager

# ------------------------
# Config & paths (MOVED from app.py)
# ------------------------
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
LIB_CACHE = DATA_DIR / "library.json"
# We don't need CONFIG_FILE here as that's in config.py
# We keep DEFAULT_MUSIC_PATH in app.py as it's a default setting, not I/O logic.
# ------------------------------------------
class ScannerThread(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path

    def run(self):
        tree = {}
        # Walk the directory; produce nested dict structure
        # We'll follow the structure: folder keys -> subdict; files are added to 'tracks' list
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            # relative path from root
            rel = os.path.relpath(dirpath, self.root_path)
            if rel == ".":
                rel = ""
            # collect mp3s only
            mp3s = [f for f in filenames if f.lower().endswith('.mp3')]
            # set in tree
            parts = rel.split(os.sep) if rel else []
            node = tree
            for p in parts:
                if p == "" or p == ".":
                    continue
                node = node.setdefault(p, {})
            if mp3s:
                node.setdefault('Unsorted', []).extend(sorted(mp3s))
            # emit a light progress ping occasionally
            if hasattr(self, "progress") and int(time.time()) % 2 == 0:
                self.progress.emit(f"Scanning: {dirpath}")
        # Prune empty branches (remove nodes without 'tracks' or children)
        def prune(n):
            keys = list(n.keys())
            for k in keys:
                if k == 'Unsorted':
                    continue
                prune(n[k])
                if not n[k]:  # empty dict
                    n.pop(k, None)
            # if only tracks empty leave it; otherwise if no keys return
        prune(tree)
        self.finished.emit(tree)



# metadata.py (Add this class)

class MetadataManager:
    """Handles read/write operations for individual track metadata (tags) and rating."""

    # Extracted from MP3Player.load_track_info (Tags & Album Art)
    @staticmethod
    def load_tags_and_art(path):
        """Loads ID3 tags and album art data from a file."""
        tags = {}
        album_art_data = None
        try:
            # EasyID3 for standard tags
            audio = EasyID3(path)
            for key in ["artist", "title", "albumartist", "tracknumber", "album", "genre"]:
                tags[key] = audio.get(key, [""])[0]

            # MP3 for album art
            mp3_file = MP3(path)
            if 'APIC:' in mp3_file:
                album_art_data = mp3_file['APIC:'].data
        except Exception:
            pass
        return tags, album_art_data

    # Extracted from MP3Player.save_tags
    @staticmethod
    def save_tags(path, tag_data):
        """Saves standard ID3 tags to a file."""
        try:
            audio = EasyID3(path)
            for tag, text in tag_data.items():
                audio[tag] = text
            audio.save()
            return True
        except Exception:
            return False

    # Extracted from YinYangRatingWidget.load_rating
    @staticmethod
    def load_rating(path):
        """Reads the POPM rating from a single file path and returns the 0-5 value."""
        try:
            mp3_file = MP3(path)
            popms = mp3_file.tags.getall("POPM") if mp3_file.tags else []
            rating_val = 0
            if popms:
                rating_val = popms[0].rating
            # Convert 0-255 to 0-5 in 0.5 steps
            return round(rating_val / 255 * 5 * 2) / 2
        except Exception:
            return 0

    # Extracted from YinYangRatingWidget._make_click_handler
    @staticmethod
    def save_rating(path, rating):
        """Saves the 0-5 rating to the POPM tag of the file at the given path."""
        try:
            audio = MP3(path)
            popms = audio.tags.getall("POPM") if audio.tags else []

            if popms:
                popm = popms[0]
            else:
                from mutagen.id3 import POPM # Need to import POPM again if not at file top
                popm = POPM(email="user@example.com", rating=0, count=0)
                if not audio.tags:
                    from mutagen.id3 import ID3 # Need to import ID3 again if not at file top
                    audio.add_tags()
                audio.tags.add(popm)

            # Convert 0-5 rating back to 0-255 integer
            popm.rating = int(round(rating / 5 * 255))
            audio.save()
            return True
        except Exception as e:
            print(f"Failed to save rating for {path}: {e}")
            return False