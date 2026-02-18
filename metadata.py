# metadata.py

import os             # For ScannerThread (os.walk, os.path.join)
import time           # For ScannerThread (progress updates)
from pathlib import Path  # For handling file paths

# PyQt6 components needed for the ScannerThread
from PyQt6.QtCore import QThread, pyqtSignal

# Mutagen and ID3 components for tag reading/writing
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.id3 import POPM, ID3
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

# Our custom data model
from models import Song
from database_logic import DatabaseManager

# ------------------------
# Config & paths
# ------------------------
PROJECT_DIR = Path(__file__).resolve().parent
# We don't need CONFIG_FILE here as that's in config.py
# We keep DEFAULT_MUSIC_PATH in app.py as it's a default setting, not I/O logic.
# ------------------------------------------
class ScannerThread(QThread):
    finished = pyqtSignal(dict, list) # dict: library tree, list: tags to fix
    progress = pyqtSignal(str)
    artist_changed = pyqtSignal()

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path

    def run(self):
        # --- Step 1: Get initial state ---
        db_paths = set(DatabaseManager.get_all_filepaths())
        found_paths = set()
        
        tree = {} # This is for the old tree logic, can be removed later
        song_batch = []
        tags_to_fix = [] # New list for collecting sanitization tasks
        self.last_artist = None

        # --- Step 2: Scan file system ---
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d.lower() != 'parking' and d != 'Library']
            
            current_folder_name = os.path.basename(dirpath)
            if current_folder_name.lower() == 'parking' or current_folder_name == 'Library':
                continue

            rel = os.path.relpath(dirpath, self.root_path)
            if rel == ".":
                rel = ""
            
            mp3s = [f for f in filenames if f.endswith('.mp3')]
            
            parts = rel.split(os.sep) if rel else []
            node = tree
            for p in parts:
                if p == "" or p == ".":
                    continue
                node = node.setdefault(p, {})
            
            if mp3s:
                node.setdefault('Unsorted', []).extend(sorted(mp3s))
                for filename in mp3s:
                    full_path = Path(os.path.join(dirpath, filename))
                    found_paths.add(str(full_path)) # Add found path to our set

                    artist = title = album = genre = year = comment = tracknumber = None
                    duration = 0.0
                    
                    try:
                        audio = EasyID3(full_path)
                        artist = audio.get("artist", [""])[0]
                        title = audio.get("title", [""])[0]
                        album = audio.get("album", [""])[0]
                        genre = audio.get("genre", [""])[0]
                        year = audio.get("date", [""])[0]
                        tracknumber = audio.get("tracknumber", [""])[0] # Original funky value
                        
                        # Sanitize the track number
                        was_changed, clean_tracknumber = sanitize_track_number(tracknumber)
                        if was_changed:
                            tags_to_fix.append((str(full_path), clean_tracknumber))
                        
                        audio_file = MP3(full_path)
                        duration = audio_file.info.length if audio_file.info else 0.0
                        
                    except Exception as e:
                        print(f"Warning: Could not read tags for {full_path}: {e}")
                        title = filename
                        clean_tracknumber = "" # Ensure clean_tracknumber exists
                    
                    # --- Artist tracking for batching ---
                    current_artist = artist or 'Unknown Artist'
                    if self.last_artist is None:
                        self.last_artist = current_artist

                    if current_artist != self.last_artist:
                        if song_batch:
                            DatabaseManager.add_songs_batch(song_batch)
                            song_batch = []
                        self.artist_changed.emit()
                        self.last_artist = current_artist
                        
                    song = Song(
                        file_path=str(full_path),
                        artist=artist,
                        title=title,
                        album=album,
                        genre=genre,
                        year=year,
                        duration=duration,
                        ext_1=clean_tracknumber # Use the clean value for the DB
                    )
                    song_batch.append(song)

            if hasattr(self, "progress") and int(time.time()) % 2 == 0:
                self.progress.emit(f"Scanning: {dirpath}")
        
        # --- Step 3: Commit final batch and prune database ---
        if song_batch:
            DatabaseManager.add_songs_batch(song_batch)
        
        stale_paths = db_paths - found_paths
        if stale_paths:
            DatabaseManager.delete_songs_by_paths(list(stale_paths))

        # --- Step 4: Finalize and emit finished signal ---
        try:
            def prune(n):
                keys = list(n.keys())
                for k in keys:
                    if k == 'Unsorted':
                        continue
                    prune(n[k])
                    if not n[k]:
                        n.pop(k, None)
            prune(tree)
            self.finished.emit(tree, tags_to_fix) # Emit both tree and the list of tags to fix
        except Exception as e:
            print("!!! CRITICAL ERROR IN SCANNER THREAD !!!")
            import traceback
            traceback.print_exc()



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
        """Saves standard ID3 tags to a file and updates the database."""
        try:
            audio = EasyID3(path)
            for tag, text in tag_data.items():
                audio[tag] = text
            audio.save()

            # Remap 'tracknumber' from UI to 'ext_1' for the database model
            if 'tracknumber' in tag_data:
                tag_data['ext_1'] = tag_data.pop('tracknumber')

            # Update the database
            song = Song(file_path=path, **tag_data) # Create a Song object from updated tags
            DatabaseManager.add_song(song) # This will update existing entry or add new one

            return True
        except Exception as e:
            print(f"Failed to save tags for {path}: {e}")
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
        """Saves the 0-5 rating to the POPM tag of the file at the given path and updates the database."""
        try:
            audio = MP3(path)
            popms = audio.tags.getall("POPM") if audio.tags else []

            if popms:
                popm = popms[0]
            else:
                popm = POPM(email="user@example.com", rating=0, count=0)
                if not audio.tags:
                    audio.add_tags()
                audio.tags.add(popm)

            # Convert 0-5 rating back to 0-255 integer
            popm.rating = int(round(rating / 5 * 255))
            audio.save()

            # Update the database
            song = DatabaseManager.get_song_by_path(path)
            if song:
                song.rating = rating
                DatabaseManager.add_song(song) # Add_song will update the existing entry
            else:
                print(f"Warning: Song not found in database for path: {path}. Cannot update rating in DB.")

            return True
        except Exception as e:
            print(f"Failed to save rating for {path}: {e}")
            return False
    
# Utility function to create a library snapshot
def create_library_snapshot(music_path):
    """
    Creates a snapshot of the library's state based on file count and latest modification time.
    Returns a dictionary: {'latest_mod_time': float, 'file_count': int}
    """
    latest_mod_time = 0.0
    file_count = 0
    
    if not os.path.isdir(music_path):
        return {'latest_mod_time': 0.0, 'file_count': 0}

    for root, dirs, files in os.walk(music_path):
        try:
            # Check modification time of the directory itself
            dir_mtime = os.path.getmtime(root)
            latest_mod_time = max(latest_mod_time, dir_mtime)
        except OSError:
            # Ignore directories we don't have permission to read
            pass

        for file in files:
            file_path = os.path.join(root, file)
            try:
                if file.lower().endswith('.mp3'): # Only count MP3s
                    file_count += 1
                file_mtime = os.path.getmtime(file_path)
                latest_mod_time = max(latest_mod_time, file_mtime)
            except OSError:
                # Ignore files we don't have permission to read
                pass
    
    return {'latest_mod_time': latest_mod_time, 'file_count': file_count}

def sanitize_track_number(original_str):
    """
    Sanitizes a track number string according to specific rules.
    Returns a tuple: (was_changed, new_value)
    """
    if not original_str or not isinstance(original_str, str):
        return (False, "") # Nothing to do

    original_str = original_str.strip()
    
    # Take the part before a slash
    track_part = original_str.split('/')[0].strip()

    try:
        # Convert to integer to strip leading zeros and validate it's a number
        num = int(track_part)
        clean_str = str(num)
        
        # If the original string representation is different from the clean one, it was sanitized
        was_changed = original_str != clean_str
        return (was_changed, clean_str)

    except (ValueError, TypeError):
        # This handles non-numeric cases like "A1", ".", etc.
        # Rule: make it blank.
        if original_str: # It had a non-empty, non-numeric value
             return (True, "") # It was sanitized to blank
        else:
             return (False, "") # It was already blank