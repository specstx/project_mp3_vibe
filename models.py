# models.py

from pathlib import Path

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