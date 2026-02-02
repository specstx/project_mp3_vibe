import sqlite3
from models import DB_PATH

class DatabaseManager:
    @staticmethod
    def initialize():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''CREATE TABLE IF NOT EXISTS tracks (
            filepath TEXT PRIMARY KEY, title TEXT, artist TEXT, 
            album TEXT, rating REAL, duration INTEGER)''')
        conn.commit()
        conn.close()

    @staticmethod
    def add_song(s_dict):
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute('''INSERT OR REPLACE INTO tracks 
                (filepath, title, artist, album, rating, duration) 
                VALUES (?, ?, ?, ?, ?, ?)''', 
                (s_dict['path'], s_dict['title'], s_dict['artist'], 
                 s_dict['album'], s_dict['rating'], s_dict['duration']))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_all_rows():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks ORDER BY filepath")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows