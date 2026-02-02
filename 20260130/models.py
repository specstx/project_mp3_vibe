# models.py

import json
from pathlib import Path

# --- Configuration for CacheManager ---
PROJECT_DIR = Path(__file__).resolve().parent
# Define the path to the library cache file
LIB_CACHE = PROJECT_DIR / "data" / "library_cache.json" 


class CacheManager:
    """Manages serialization and deserialization of the main library structure."""

    @staticmethod
    def load_library_cache():
        """Loads music data from library_cache.json and returns the tree structure."""
        if LIB_CACHE.exists():
            try:
                with open(LIB_CACHE, 'r') as f:
                    data = json.load(f)
                    return data
            except (json.JSONDecodeError, FileNotFoundError):
                # Critical: Return empty structure on corruption or file error
                print("Warning: Library cache corrupted. Starting fresh scan.")
                return {}
        return {}

    @staticmethod
    def save_library_cache(tree):
        """Saves the library tree structure to library_cache.json."""
        # Ensure the 'data' directory exists before writing
        LIB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(LIB_CACHE, 'w') as f:
                json.dump(tree, f, indent=4)
        except Exception as e:
            print(f"Error saving library cache: {e}")
            pass


class Song:
    """Represents a single music track with all its metadata."""

    def __init__(self, filepath, title=None, artist=None, rating=0, playtime_ms=0):
        # Setting the attributes (data) for each track object
        self.filepath = Path(filepath) # Store path as a Path object for safety
        self.title = title
        self.artist = artist
        self.rating = rating
        self.playtime_ms = playtime_ms

    def to_dict(self):
        """Converts the Song object to a dictionary for JSON serialization."""
        return {
            "path": str(self.filepath),
            "title": self.title,
            "artist": self.artist,
            "rating": self.rating,
            "duration": self.playtime_ms
        }

    @staticmethod
    def from_dict(data):
        """Creates a Song object from a dictionary loaded from JSON."""
        return Song(
            filepath=data.get("path"),
            title=data.get("title"),
            artist=data.get("artist"),
            rating=data.get("rating", 0),
            playtime_ms=data.get("duration", 0)
        )