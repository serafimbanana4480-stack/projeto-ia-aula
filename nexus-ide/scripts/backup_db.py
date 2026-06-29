#!/usr/bin/env python3
"""Database backup script for NEXUS IDE.

Creates timestamped backups of the SQLite database.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """Get the path to the database file."""
    # Try to find the database in the data directory
    current_dir = Path(__file__).resolve().parent
    db_path = current_dir.parent / "data" / "nexus.db"

    if not db_path.exists():
        # Try relative to script location
        db_path = current_dir / ".." / "data" / "nexus.db"

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    return db_path.resolve()


def get_backup_dir() -> Path:
    """Get the backup directory."""
    current_dir = Path(__file__).resolve().parent
    backup_dir = current_dir.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir.resolve()


def create_backup(compress: bool = False) -> Path:
    """Create a backup of the database.

    Args:
        compress: Whether to compress the backup using gzip.

    Returns:
        Path to the backup file.
    """
    db_path = get_db_path()
    backup_dir = get_backup_dir()

    # Create timestamp for backup filename
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_name = f"nexus_backup_{timestamp}.db"
    backup_path = backup_dir / backup_name

    # Verify database is not corrupted before backup
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA integrity_check")
        conn.close()
        logger.info("Database integrity check passed")
    except sqlite3.DatabaseError as e:
        logger.error("Database integrity check failed: %s", e)
        raise

    # Create backup
    logger.info("Creating backup: %s", backup_path)
    shutil.copy2(db_path, backup_path)
    logger.info("Backup created successfully")

    # Compress if requested
    if compress:
        import gzip

        compressed_path = backup_dir / f"{backup_name}.gz"
        logger.info("Compressing backup: %s", compressed_path)
        with open(backup_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        # Remove uncompressed backup
        backup_path.unlink()
        logger.info("Backup compressed successfully")
        return compressed_path

    return backup_path


def list_backups() -> list[Path]:
    """List all available backups.

    Returns:
        List of backup file paths sorted by modification time (newest first).
    """
    backup_dir = get_backup_dir()
    backups = sorted(
        [f for f in backup_dir.glob("nexus_backup_*.db*") if f.is_file()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    return backups


def restore_backup(backup_path: Path) -> None:
    """Restore a backup of the database.

    Args:
        backup_path: Path to the backup file to restore.
    """
    db_path = get_db_path()

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Handle compressed backups
    if backup_path.suffix == ".gz":
        import gzip

        logger.info("Decompressing backup: %s", backup_path)
        temp_path = backup_path.parent / backup_path.stem
        with gzip.open(backup_path, "rb") as f_in:
            with open(temp_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        backup_path = temp_path

    # Create a backup of the current database before restoring
    logger.info("Creating safety backup of current database")
    current_backup = create_backup(compress=False)

    try:
        logger.info("Restoring backup: %s", backup_path)
        shutil.copy2(backup_path, db_path)
        logger.info("Database restored successfully")
        logger.info("Safety backup saved at: %s", current_backup)
    except Exception as e:
        logger.error("Restore failed: %s", e)
        logger.info("Attempting to restore from safety backup")
        shutil.copy2(current_backup, db_path)
        raise
    finally:
        # Clean up temporary decompressed file if it exists
        if backup_path.suffix == "":
            temp_path = backup_path
            if temp_path.exists() and temp_path != backup_path:
                temp_path.unlink()


def cleanup_old_backups(keep_count: int = 10) -> None:
    """Remove old backups, keeping only the most recent ones.

    Args:
        keep_count: Number of backups to keep.
    """
    backups = list_backups()
    if len(backups) <= keep_count:
        logger.info("No old backups to clean up (keeping %d backups)", len(backups))
        return

    old_backups = backups[keep_count:]
    for backup in old_backups:
        logger.info("Removing old backup: %s", backup)
        backup.unlink()
    logger.info("Cleaned up %d old backup(s)", len(old_backups))


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Database backup and restore for NEXUS IDE"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create a database backup")
    backup_parser.add_argument(
        "--compress", "-c", action="store_true", help="Compress the backup with gzip"
    )

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore a database backup")
    restore_parser.add_argument(
        "backup_file", help="Path to the backup file to restore"
    )

    # List command
    subparsers.add_parser("list", help="List all available backups")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove old backups")
    cleanup_parser.add_argument(
        "--keep",
        "-k",
        type=int,
        default=10,
        help="Number of backups to keep (default: 10)",
    )

    args = parser.parse_args()

    if args.command == "backup":
        backup_path = create_backup(compress=args.compress)
        logger.info("Backup created: %s", backup_path)
    elif args.command == "restore":
        restore_backup(Path(args.backup_file))
    elif args.command == "list":
        backups = list_backups()
        if not backups:
            logger.info("No backups found")
        else:
            logger.info("Available backups (newest first):")
            for backup in backups:
                size_mb = backup.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(backup.stat().st_mtime)
                logger.info("  %s (%.2f MB, %s)", backup.name, size_mb, mtime)
    elif args.command == "cleanup":
        cleanup_old_backups(keep_count=args.keep)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()