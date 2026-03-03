import sqlite3
import os

def initialize_database(db_path="music_library.db"):
    """
    Initializes the database, creating tables and adding missing columns if they don't exist.
    """
    db_exists = os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Define expected columns for the 'library' table
    # Mapping column name to its definition
    expected_columns = {
        "file_path": "TEXT PRIMARY KEY",
        "artist": "TEXT",
        "title": "TEXT",
        "album": "TEXT",
        "genre": "TEXT",
        "year": "TEXT",
        "comment": "TEXT",
        "duration": "REAL",
        "play_count": "INTEGER DEFAULT 0",
        "rating": "REAL DEFAULT 0.0",
        "last_played": "TEXT",
        "is_present": "INTEGER DEFAULT 1",
        "is_mirrored": "INTEGER DEFAULT 0"
    }
    # Add extended fields
    for i in range(1, 21):
        expected_columns[f"ext_{i}"] = "TEXT"

    # 2. Create 'library' table if it doesn't exist
    column_defs = [f"{name} {dtype}" for name, dtype in expected_columns.items()]
    cursor.execute(f"CREATE TABLE IF NOT EXISTS library ({', '.join(column_defs)})")

    # 3. Migration: Add missing columns if the table already existed
    cursor.execute("PRAGMA table_info(library)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for col_name, col_def in expected_columns.items():
        if col_name not in existing_columns:
            print(f"Adding missing column '{col_name}' to 'library' table...")
            # SQLite ALTER TABLE is limited, but adding columns is supported
            try:
                cursor.execute(f"ALTER TABLE library ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError as e:
                print(f"Error adding column {col_name}: {e}")

    # 4. Create 'play_log' table
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
    
    status = "created" if not db_exists else "updated/verified"
    print(f"Database {status}: {db_path}")

if __name__ == "__main__":
    initialize_database()
