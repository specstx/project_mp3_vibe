# models.py

import sqlite3
from pathlib import Path

# --- Configuration for Database ---
PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "music_library.db" 

class Song:
    """Represents a single music track with all its metadata."""

    def __init__(self, file_path, artist=None, title=None, album=None, genre=None, year=None, comment=None, duration=0.0, play_count=0, rating=0.0, **kwargs):
        self.file_path = Path(file_path) # Store path as a Path object for safety
        self.artist = artist
        self.title = title
        self.album = album
        self.genre = genre
        self.year = year
        self.comment = comment
        self.duration = duration
        self.play_count = play_count
        self.rating = rating
        
        # Handle extended fields (ext_1 to ext_20)
        for i in range(1, 21):
            setattr(self, f"ext_{i}", kwargs.get(f"ext_{i}"))

    def to_dict(self):
        """Converts the Song object to a dictionary for database insertion or serialization."""
        data = {
            "file_path": str(self.file_path),
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "comment": self.comment,
            "duration": self.duration,
            "play_count": self.play_count,
            "rating": self.rating
        }
        for i in range(1, 21):
            data[f"ext_{i}"] = getattr(self, f"ext_{i}")
        return data

    @property
    def length_display(self):
        """Returns the duration formatted as MM:SS."""
        if not self.duration:
            return "00:00"
        try:
            d = int(float(self.duration))
            mins = d // 60
            secs = d % 60
            return f"{mins:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "00:00"

    @staticmethod
    def from_dict(data):
        """Creates a Song object from a dictionary loaded from the database."""
        return Song(
            file_path=data.get("file_path"),
            artist=data.get("artist"),
            title=data.get("title"),
            album=data.get("album"),
            genre=data.get("genre"),
            year=data.get("year"),
            comment=data.get("comment"),
            duration=data.get("duration", 0.0),
            play_count=data.get("play_count", 0),
            rating=data.get("rating", 0.0),
            **{f"ext_{i}": data.get(f"ext_{i}") for i in range(1, 21)}
        )