import os
import shutil
import logging
import re
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1

# --- Configuration ---
DEFAULT_SOURCE = os.path.expanduser("~/Music/parking")
DEFAULT_MASTER = "/media/timothy/SideShow/Music"
DEFAULT_MIRROR = "/media/timothy/Ext/Tim/Music"

WHITELIST = {".mp3", ".jpg", ".jpeg", ".png"}
NTFS_RESERVED = re.compile(r'[<>:"/\|?*]')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sovereign_sync.log"),
        logging.StreamHandler()
    ]
)

class SovereignSync:
    def __init__(self, source=None, master=None, mirror=None, dry_run=False):
        self.source = Path(source or DEFAULT_SOURCE)
        self.master = Path(master or DEFAULT_MASTER)
        self.mirror = Path(mirror or DEFAULT_MIRROR)
        self.dry_run = dry_run

    def sanitize_ntfs(self, path_str):
        """Removes Windows reserved characters for NTFS Mirror."""
        return NTFS_RESERVED.sub("_", path_str)

    def clean_space_ghosts(self, path_obj):
        """Strips leading/trailing spaces from all path components."""
        parts = [p.strip() for p in path_obj.parts]
        return Path(*parts)

    def validate_tags(self, file_path):
        """Verifies Artist and Title tags for MP3 files."""
        if file_path.suffix.lower() != ".mp3":
            return True
        try:
            audio = MP3(file_path, ID3=ID3)
            artist = audio.get("TPE1") or audio.get("TPE2")
            title = audio.get("TIT2")
            if not artist or not title:
                return False
            return True
        except Exception as e:
            logging.error(f"Tag check failed for {file_path}: {e}")
            return False

    def get_rel_dest_path(self, source_file):
        """Constructs the relative destination path, cleaning 'Space Ghosts'."""
        rel_path = source_file.relative_to(self.source)
        return self.clean_space_ghosts(rel_path)

    def sync_to_master(self, src_file, master_file):
        """Implements the Sovereign Size Rule for Master (EXT4)."""
        if not master_file.exists():
            logging.info(f"New File: {src_file.name} -> Master")
            return self.copy_file(src_file, master_file)

        src_size = src_file.stat().st_size
        mst_size = master_file.stat().st_size

        if src_size > mst_size:
            logging.info(f"Upgrade: {src_file.name} ({src_size} > {mst_size}) -> Master")
            return self.copy_file(src_file, master_file)
        elif src_size < mst_size:
            logging.warning(f"Quality Gate: Source smaller than Master. Skipping {src_file.name}. (Source: {src_size}, Master: {mst_size})")
            return False
        else:
            # logging.info(f"Identical: {src_file.name} matches Master size. Skipping.")
            return False

    def sync_to_mirror(self, master_file, rel_path):
        """Implements Master-Mirror Lock with NTFS sanitization."""
        # Sanitize parts for NTFS
        sanitized_parts = [self.sanitize_ntfs(p) for p in rel_path.parts]
        mirror_file = self.mirror.joinpath(*sanitized_parts)

        if self.dry_run:
            logging.info(f"[Dry Run] Mirroring to: {mirror_file}")
            return

        mirror_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master_file, mirror_file)

        # Verification
        if master_file.stat().st_size != mirror_file.stat().st_size:
            logging.critical(f"ALERT: Size mismatch on Mirror for {mirror_file.name}!")
        else:
            logging.info(f"Mirror Verified: {mirror_file.name}")

    def copy_file(self, src, dst):
        if self.dry_run:
            logging.info(f"[Dry Run] Copying {src} to {dst}")
            return True
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            logging.error(f"Failed to copy {src}: {e}")
            return False

    def run(self):
        logging.info(f"Starting Sovereign Sync: {self.source} -> {self.master} -> {self.mirror}")
        
        if not self.source.exists():
            logging.error(f"Source path does not exist: {self.source}")
            return

        for root, dirs, files in os.walk(self.source):
            for filename in files:
                src_file = Path(root) / filename
                
                # 1. Whitelist Filter
                if src_file.suffix.lower() not in WHITELIST:
                    continue

                # 2. Tag Validation (MP3 only)
                if not self.validate_tags(src_file):
                    logging.error(f"Validation Failed: {filename} missing Artist/Title tags. Skipping.")
                    continue

                # 3. Pathing & Space Ghosts
                rel_path = self.get_rel_dest_path(src_file)
                master_file = self.master / rel_path

                # 4. Sync Source -> Master
                updated = self.sync_to_master(src_file, master_file)

                # 5. Sync Master -> Mirror (The Lock)
                # Force mirror if master was updated or if mirror doesn't exist/size differs
                if updated or master_file.exists():
                    self.sync_to_mirror(master_file, rel_path)

        logging.info("Sovereign Sync Complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sovereign Sync Engine")
    parser.add_argument("--source", help="Source parking folder")
    parser.add_argument("--master", help="Master EXT4 destination")
    parser.add_argument("--mirror", help="Mirror NTFS destination")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without copying")
    
    args = parser.parse_args()
    
    engine = SovereignSync(
        source=args.source,
        master=args.master,
        mirror=args.mirror,
        dry_run=args.dry_run
    )
    engine.run()
