import sqlite3
from models import DB_PATH, Song

class DatabaseManager:
    @staticmethod
    def add_song(song: Song):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        song_dict = song.to_dict()
        
        columns = ["file_path", "artist", "title", "album", "genre", "year", "comment", "duration", "play_count", "rating", "last_played", "is_present"]
        placeholders = ["?"] * len(columns)
        values = [song_dict[col] for col in columns]

        # Add extended fields
        for i in range(1, 21):
            col_name = f"ext_{i}"
            columns.append(col_name)
            placeholders.append("?")
            values.append(song_dict.get(col_name))

        try:
            cursor.execute(f'''INSERT OR REPLACE INTO library 
                ({', '.join(columns)}) 
                VALUES ({', '.join(placeholders)})''', tuple(values))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def add_songs_batch(songs: list[Song]):
        if not songs:
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            for song in songs:
                song_dict = song.to_dict()
                
                columns = ["file_path", "artist", "title", "album", "genre", "year", "comment", "duration", "play_count", "rating", "last_played", "is_present"]
                placeholders = ["?"] * len(columns)
                values = [song_dict.get(col) for col in columns]

                # Add extended fields
                for i in range(1, 21):
                    col_name = f"ext_{i}"
                    columns.append(col_name)
                    placeholders.append("?")
                    values.append(song_dict.get(col_name))

                cursor.execute(f'''INSERT OR REPLACE INTO library 
                    ({', '.join(columns)}) 
                    VALUES ({', '.join(placeholders)})''', tuple(values))
            
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def mark_offline(rel_paths: list[str]):
        """Marks songs as offline instead of deleting them."""
        if not rel_paths:
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        chunk_size = 900
        
        try:
            for i in range(0, len(rel_paths), chunk_size):
                chunk = rel_paths[i:i + chunk_size]
                placeholders = ','.join('?' for _ in chunk)
                query = f"UPDATE library SET is_present = 0 WHERE file_path IN ({placeholders})"
                cursor.execute(query, tuple(chunk))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_present_songs():
        """Retrieves all songs currently marked as present."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM library WHERE is_present = 1 ORDER BY genre, artist, album, file_path")
        rows = cursor.fetchall()
        conn.close()
        return [Song.from_dict(dict(row)) for row in rows]

    @staticmethod
    def increment_play_count(filepath):
        """Increments play count and updates last_played timestamp."""
        import datetime
        now = datetime.datetime.now().isoformat()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE library 
                SET play_count = play_count + 1, last_played = ?
                WHERE file_path = ?
            """, (now, filepath))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def log_play_event(filepath, duration_played, total_duration, was_fully_played):
        """Records a detailed play event to the play_log."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO play_log (file_path, duration_played, total_duration, was_fully_played)
                VALUES (?, ?, ?, ?)
            """, (filepath, duration_played, total_duration, 1 if was_fully_played else 0))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_statistics():
        """Returns a dictionary of library statistics."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        stats = {}
        try:
            # Total tracks
            cursor.execute("SELECT COUNT(*) FROM library")
            stats['total_tracks'] = cursor.fetchone()[0]

            # Total duration
            cursor.execute("SELECT SUM(duration) FROM library")
            stats['total_duration'] = cursor.fetchone()[0] or 0

            # Top Genre
            cursor.execute("SELECT genre, COUNT(*) as c FROM library GROUP BY genre ORDER BY c DESC LIMIT 1")
            row = cursor.fetchone()
            stats['top_genre'] = row[0] if row else "N/A"

            # Top Artist
            cursor.execute("SELECT artist, COUNT(*) as c FROM library GROUP BY artist ORDER BY c DESC LIMIT 1")
            row = cursor.fetchone()
            stats['top_artist'] = row[0] if row else "N/A"

            # Metadata Health (missing Artist or Title or Album)
            cursor.execute("""
                SELECT COUNT(*) FROM library 
                WHERE artist IS NULL OR artist = 'Unknown' 
                   OR title IS NULL OR title = ''
                   OR album IS NULL OR album = 'Unknown'
            """)
            stats['missing_metadata'] = cursor.fetchone()[0]

            # Top Rated (4.0+)
            cursor.execute("SELECT COUNT(*) FROM library WHERE rating >= 4.0")
            stats['top_rated_count'] = cursor.fetchone()[0]

        finally:
            conn.close()
        return stats

    @staticmethod
    def get_song_by_path(filepath):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM library WHERE file_path = ?", (filepath,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Song.from_dict(dict(row))
        return None

    @staticmethod
    def get_all_songs():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM library ORDER BY file_path")
        rows = cursor.fetchall()
        conn.close()
        return [Song.from_dict(dict(row)) for row in rows]

    @staticmethod
    def get_all_songs_sorted():
        """Retrieves all songs sorted by genre, artist, and album for efficient hierarchy building."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Use the newly created indices for a fast sorted query
        cursor.execute("SELECT * FROM library ORDER BY genre, artist, album, file_path")
        rows = cursor.fetchall()
        conn.close()
        return [Song.from_dict(dict(row)) for row in rows]

    @staticmethod
    def get_all_filepaths():
        """Retrieves a list of all file paths currently in the database."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM library")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    @staticmethod
    def delete_songs_by_paths(paths: list[str]):
        """Deletes songs from the database for a given list of file paths in chunks."""
        if not paths:
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        chunk_size = 900 # Staying well under the 999 limit
        
        try:
            for i in range(0, len(paths), chunk_size):
                chunk = paths[i:i + chunk_size]
                placeholders = ','.join('?' for _ in chunk)
                query = f"DELETE FROM library WHERE file_path IN ({placeholders})"
                cursor.execute(query, tuple(chunk))
            
            conn.commit()
            print(f"Successfully pruned stale records.")
        finally:
            conn.close()
    