import os
import shutil
import logging
import re
import datetime
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1
from database_logic import DatabaseManager
from models import Song

# --- Configuration ---
DEFAULT_SOURCE = os.path.expanduser("~/Music/parking")
DEFAULT_MASTER = "/media/timothy/SideShow/Music"
DEFAULT_MIRROR = "/media/timothy/Ext/Tim/Music"

WHITELIST = {".mp3", ".jpg", ".jpeg", ".png"}
NTFS_RESERVED = re.compile(r'[<>:"/\\|?*]')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sovereign_sync.log"),
        logging.StreamHandler()
    ]
)

class SovereignIngest:
    """Handles the transition from Parking -> SideShow (Master)."""
    
    def __init__(self, source=None, master=None, dry_run=False):
        self.source = Path(source or DEFAULT_SOURCE)
        self.master = Path(master or DEFAULT_MASTER)
        self.trashcan = self.source / "processed_trashcan"
        self.report_path = self.source / "ingestion_report.txt"
        self.dry_run = dry_run
        self.report_lines = []

    def log_report(self, msg):
        self.report_lines.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
        logging.info(msg)

    def is_ntfs_safe(self, path_obj):
        """Checks if all parts of the path are NTFS friendly."""
        for part in path_obj.parts:
            if NTFS_RESERVED.search(part):
                return False, f"Illegal character in: {part}"
            if part.endswith(" ") or part.startswith(" "):
                return False, f"Space Ghost (leading/trailing space) in: {part}"
            if part.endswith("."):
                return False, f"Trailing period in: {part}"
        return True, ""

    def run(self):
        self.report_lines = [f"--- SOVEREIGN INGESTION REPORT: {datetime.date.today()} ---"]
        self.log_report(f"Source: {self.source} | Master: {self.master}")
        
        if not self.source.exists():
            self.log_report("ERROR: Source folder not found.")
            return

        # 1. Walk Parking
        for root, dirs, files in os.walk(self.source):
            # Skip the trashcan itself
            if "processed_trashcan" in root:
                continue

            for filename in files:
                src_file = Path(root) / filename
                if src_file.suffix.lower() not in WHITELIST:
                    continue

                # 2. Validation
                rel_path = src_file.relative_to(self.source)
                safe, reason = self.is_ntfs_safe(rel_path)
                
                if not safe:
                    self.log_report(f"[FAILED] {rel_path} -> {reason}")
                    continue

                master_file = self.master / rel_path
                
                # 3. Size Rule & Execution
                action_taken = self.process_file(src_file, master_file, rel_path)
                
                # 4. Trashcan Move (if not failed)
                if action_taken:
                    self.move_to_trash(src_file, rel_path)

        # 5. Finalize Report
        with open(self.report_path, "w") as f:
            f.write("\n".join(self.report_lines))
        
        self.log_report(f"Ingestion Finished. Report saved to {self.report_path}")

    def process_file(self, src, dst, rel):
        """Logic for Master upgrade/copy."""
        if not dst.exists():
            self.log_report(f"[NEW] {rel} -> SideShow")
            return self.perform_copy(src, dst, rel)

        src_size = src.stat().st_size
        dst_size = dst.stat().st_size

        if src_size > dst_size:
            self.log_report(f"[UPGRADE] {rel} ({src_size} > {dst_size}) -> SideShow")
            return self.perform_copy(src, dst, rel)
        else:
            self.log_report(f"[SKIPPED] {rel} (Master version is larger/equal).")
            return True # Still counts as processed

    def perform_copy(self, src, dst, rel):
        if self.dry_run: return True
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            
            # Sovereign: Flag for mirroring in DB
            DatabaseManager.mark_as_unmirrored([str(rel)])
            
            return True
        except Exception as e:
            self.log_report(f"[ERROR] Could not copy {rel}: {e}")
            return False

    def move_to_trash(self, src, rel):
        if self.dry_run: return
        trash_dst = self.trashcan / rel
        try:
            trash_dst.parent.mkdir(parents=True, exist_ok=True)
            # Move instead of copy to clear parking
            shutil.move(str(src), str(trash_dst))
        except Exception as e:
            self.log_report(f"[WARNING] Could not move to trashcan: {rel} - {e}")

class SovereignSync:
    """Handles the Mirroring from SideShow (Master) -> External (NTFS)."""
    def __init__(self, source=None, master=None, mirror=None, dry_run=False):
        self.source = Path(source or DEFAULT_SOURCE)
        self.master = Path(master or DEFAULT_MASTER)
        self.mirror = Path(mirror or DEFAULT_MIRROR)
        self.dry_run = dry_run

    def sanitize_ntfs(self, path_str):
        """Removes Windows reserved characters for NTFS Mirror."""
        return NTFS_RESERVED.sub("_", path_str)

    def sync_to_mirror(self, master_file, rel_path):
        """Implements Master-Mirror Lock with NTFS sanitization and DB updates."""
        sanitized_parts = [self.sanitize_ntfs(p) for p in rel_path.parts]
        mirror_file = self.mirror.joinpath(*sanitized_parts)

        if self.dry_run:
            logging.info(f"[Dry Run] Mirroring to: {mirror_file}")
            return True

        try:
            mirror_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(master_file, mirror_file)

            if master_file.stat().st_size != mirror_file.stat().st_size:
                logging.critical(f"ALERT: Size mismatch on Mirror for {mirror_file.name}!")
                return False
            else:
                logging.info(f"Mirror Verified: {mirror_file.name}")
                DatabaseManager.mark_as_mirrored([str(rel_path)])
                return True
        except Exception as e:
            logging.error(f"Mirror failed for {rel_path}: {e}")
            return False

    def run_mirror(self):
        """Sync Master -> Mirror (NTFS) using the 'is_mirrored' flag."""
        logging.info(f"--- Mirroring: {self.master} -> {self.mirror} ---")
        
        if not self.mirror.exists():
            logging.error(f"Sovereign: Mirror drive NOT FOUND at {self.mirror}. Please plug in the drive and try again.")
            return

        unmirrored = DatabaseManager.get_unmirrored_songs()
        if not unmirrored:
            logging.info("Sovereign: Mirror drive is already in sync.")
            return

        for song in unmirrored:
            rel_path = Path(song.file_path)
            master_file = self.master / rel_path
            if master_file.exists():
                self.sync_to_mirror(master_file, rel_path)
            else:
                logging.warning(f"Sovereign: Master file missing for {rel_path}.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sovereign Sync & Ingest Engine")
    parser.add_argument("--ingest", action="store_true", help="Run Parking -> SideShow Ingestion")
    parser.add_argument("--mirror", action="store_true", help="Run SideShow -> External Mirroring")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    
    args = parser.parse_args()
    
    if args.ingest:
        SovereignIngest(dry_run=args.dry_run).run()
    
    if args.mirror:
        SovereignSync(dry_run=args.dry_run).run_mirror()
    
    if not args.ingest and not args.mirror:
        # Default: Full Cycle
        SovereignIngest(dry_run=args.dry_run).run()
        SovereignSync(dry_run=args.dry_run).run_mirror()
