import sqlite3

def initialize_database(db_path="music_library.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    columns = [
        "file_path TEXT PRIMARY KEY",
        "artist TEXT",
        "title TEXT",
        "album TEXT",
        "genre TEXT",
        "year TEXT",
        "comment TEXT",
        "duration REAL",
        "play_count INTEGER DEFAULT 0",
        "rating REAL DEFAULT 0.0"
    ]
    for i in range(1, 21):
        columns.append(f"ext_{i} TEXT")
    
    cursor.execute(f"CREATE TABLE IF NOT EXISTS library ({', '.join(columns)})")
    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")

if __name__ == "__main__":
    initialize_database()
