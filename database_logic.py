import sqlite3
from models import DB_PATH, Song

class DatabaseManager:
    @staticmethod
    def add_song(song: Song):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        song_dict = song.to_dict()
        
        columns = ["file_path", "artist", "title", "album", "genre", "year", "comment", "duration", "play_count", "rating"]
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
                
                columns = ["file_path", "artist", "title", "album", "genre", "year", "comment", "duration", "play_count", "rating"]
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
        """Deletes songs from the database for a given list of file paths."""
        if not paths:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            # Using placeholders for a safe query
            placeholders = ','.join('?' for _ in paths)
            query = f"DELETE FROM library WHERE file_path IN ({placeholders})"
            cursor.execute(query, tuple(paths))
            conn.commit()
            print(f"Successfully pruned {cursor.rowcount} stale records.")
        finally:
            conn.close()