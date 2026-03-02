# Project Progress Summary

This file documents the key progress and architectural decisions made in the MP3 Vibe Player project.

## Key Logic Implementations

### 1. Flat Grid View Logic
The application's library and playlist views are styled to appear as flat grids while maintaining their underlying tree structure.
- **Implementation in `app.py`:**
  - `self.tree.setRootIsDecorated(False)`: Removes the expander triangles for a cleaner, flat appearance.
  - `self.tree.setIndentation(0)`: Eliminates staggered indentation, ensuring all items align to the left.
- **Result:** Provides a modern, list-like or "grid" feel while preserving the Genre -> Artist -> Album hierarchy.

### 2. 'Unknown Album/Artist' Bug Solution
To prevent crashes and ensure every track is visible even without metadata, a fallback mechanism was implemented in the library population logic.
- **Logic in `app.py`:**
  ```python
  g, ar, al = getattr(s, "genre", None) or "Unknown", 
              getattr(s, "artist", None) or "Unknown", 
              getattr(s, "album", None) or "Unknown"
  ```
- **Outcome:** Tracks missing Genre, Artist, or Album tags are automatically grouped under "Unknown" instead of causing indexing errors or being omitted from the view.

### 3. Sovereign Ingestion & Mirrored Ledger
A two-stage synchronization and ingestion system designed for library portability and data integrity.
- **Ingestion (Parking -> SideShow)**: Moves files based on filesystem structure, not tags. Includes a "Size Rule" (Upgrade if New > Old) and a "Safety Trashcan" (`processed_trashcan`) for all successfully processed or redundant files.
- **Mirroring (SideShow -> External)**: Uses a database-level `is_mirrored` flag to track sync state. 
- **Sovereign Pathing**: The database uses **Relative Paths** keyed to the library root. This allows the database and its history (play counts, etc.) to remain valid even if the library is moved between different drives or mount points.

## Core Mandates & Constraints

### UI Logic Modifications
- **RULE:** **NEVER** modify the UI logic without confirming with the user first.
- **Scope:** This applies to layouts, widget behaviors, custom controls (like the Volume Slider), and styling configurations.
- **Rationale:** The current UI state is carefully tuned for specific user preferences and perceptual behaviors.

### Data Integrity
- **Mark Offline vs Delete**: Files missing during a scan are marked as `is_present = 0` (Offline) rather than deleted. This preserves their 'Sovereign' history (play logs, ratings).
- **Audit Logging**: All failed tag fixes and metadata health checks are logged to `audit_log.txt` for manual review.
