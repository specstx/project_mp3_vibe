import sqlite3
import os

# --- Configuration ---
# Update this path to your actual library.db location
DB_PATH = os.path.expanduser("/home/timothy/Documents/project_mp3_vibe/music_library.db") 
OUTPUT_FILE = "the_48.txt"

def audit_metadata():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    try:
        # Connect using URI mode to ensure we don't interfere with WAL
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()

        # The Query: Check for NULL, empty, whitespace, or 'Unknown' placeholders
        # Targeting the 'Big 4' critical for the Sovereign Tree
        query = """
        SELECT file_path, artist, title, album, genre 
        FROM library 
        WHERE is_present = 1 AND (
            (artist IS NULL OR trim(artist) = '' OR artist = 'Unknown') OR 
            (title IS NULL OR trim(title) = '') OR 
            (album IS NULL OR trim(album) = '' OR album = 'Unknown') OR
            (genre IS NULL OR trim(genre) = '' OR genre = 'Unknown')
        )
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()

        if not rows:
            print("Perfect Score! No missing metadata found.")
            return

        with open(OUTPUT_FILE, "w") as f:
            f.write(f"--- Metadata Audit: {len(rows)} Tracks Found ---\n\n")
            for row in rows:
                path, artist, title, album, genre = row
                # Flag which specific field is the culprit
                missing = []
                if not artist or not artist.strip() or artist == 'Unknown': missing.append("Artist")
                if not title or not title.strip(): missing.append("Title")
                if not album or not album.strip() or album == 'Unknown': missing.append("Album")
                if not genre or not genre.strip() or genre == 'Unknown': missing.append("Genre")
                
                f.write(f"FILE: {path}\n")
                f.write(f"MISSING: {', '.join(missing)}\n")
                f.write("-" * 40 + "\n")

        print(f"Audit complete. {len(rows)} ghosts identified in {OUTPUT_FILE}")

    except Exception as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    audit_metadata()
