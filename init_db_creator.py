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
        "rating REAL DEFAULT 0.0",
        "last_played TEXT",
        "is_present INTEGER DEFAULT 1",
        "is_mirrored INTEGER DEFAULT 0"
    ]
    for i in range(1, 21):
        columns.append(f"ext_{i} TEXT")
    
    cursor.execute(f"CREATE TABLE IF NOT EXISTS library ({', '.join(columns)})")
    
    # New Play Log table for advanced metrics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS play_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration_played REAL,
            total_duration REAL,
            was_fully_played INTEGER DEFAULT 0,
            FOREIGN KEY(file_path) REFERENCES library(file_path)
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")

if __name__ == "__main__":
    initialize_database()
