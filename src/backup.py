"""
Backup and Restore Module.

This module provides a simple backup system for the user's qBittorrent rule
configuration. Before making destructive changes (like syncing rules to the
server), the app can save a snapshot of the current state so the user can
roll back if something goes wrong.

How it works:
  - Backups are saved as timestamped JSON files in the 'backups/' directory
  - Each backup contains: rules, categories, RSS feeds, and optional metadata
  - Old backups are automatically cleaned up (only the 10 most recent are kept)
  - Backups can be listed, loaded, and their contents inspected

Backup file format (backup_2026-06-12_15-30-00.json):
  {
    "version": "1.0",
    "backup_timestamp": "2026-06-12T15:30:00",
    "rules": { ... },
    "categories": { ... },
    "feeds": [ ... ],
    "metadata": { "qbittorrent_version": "v4.6.2", ... }
  }
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Backups are stored in a 'backups/' folder at the project root (one level up from src/)
DEFAULT_BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', 'backups')


def _ensure_backup_dir(backup_dir: Optional[str] = None) -> str:
    """
    Make sure the backup directory exists, creating it if necessary.

    Args:
        backup_dir: Custom backup directory path. If None, uses the default
                    'backups/' folder in the project root.

    Returns:
        The absolute path to the backup directory.

    Raises:
        OSError: If the directory can't be created (e.g. permissions issue).
    """
    target_dir = backup_dir or DEFAULT_BACKUP_DIR
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    return str(target_path)


def create_backup(
    rules: Dict[str, Any],
    categories: Optional[Dict[str, Any]] = None,
    feeds: Optional[List[str]] = None,
    backup_dir: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Save a snapshot of the current qBittorrent configuration to a JSON file.

    The backup file is named with a timestamp (e.g. "backup_2026-06-12_15-30-00.json")
    so multiple backups can coexist. After creating the backup, old backups are
    automatically pruned to keep only the 10 most recent.

    Args:
        rules: Dictionary of RSS rules to back up ({rule_name: rule_definition}).
        categories: Optional dict of qBittorrent categories to include.
        feeds: Optional list of RSS feed URLs to include.
        backup_dir: Custom directory to store the backup file.
                    Defaults to the project's 'backups/' folder.
        metadata: Optional extra info to embed (e.g. qBittorrent version, server URL).

    Returns:
        A tuple of (success: bool, message: str).
        On success: (True, "Backup created: backup_2026-06-12_15-30-00.json")
        On failure: (False, "Failed to create backup: <error>")
    """
    try:
        backup_dir = _ensure_backup_dir(backup_dir)

        # Generate a timestamped filename so backups don't overwrite each other
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f'backup_{timestamp}.json'
        backup_path = os.path.join(backup_dir, backup_filename)

        # Assemble all the data we want to save
        backup_data = {
            'version': '1.0',                            # Backup format version (for future compatibility)
            'backup_timestamp': datetime.now().isoformat(),
            'rules': rules or {},
            'categories': categories or {},
            'feeds': feeds or [],
        }

        # Include any extra metadata (like qBittorrent version, server info)
        if metadata:
            backup_data['metadata'] = metadata

        # Write the backup file
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Backup created: {backup_path}")
        message = f"Backup created: {backup_filename}"

        # Clean up old backups to prevent the backups folder from growing forever
        _cleanup_old_backups(backup_dir, keep_count=10)

        return True, message

    except Exception as e:
        error_msg = f"Failed to create backup: {e}"
        logger.error(error_msg)
        return False, error_msg


def load_backup(backup_path: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Read a backup file from disk and parse its contents.

    This only loads and validates the file — it doesn't automatically restore
    anything. The caller is responsible for deciding what to do with the
    loaded data (e.g. pushing rules back to qBittorrent).

    Args:
        backup_path: Full path to the backup JSON file.

    Returns:
        A tuple of (success: bool, backup_data: dict or None, message: str).
        On success: backup_data contains the full backup dictionary.
        On failure: backup_data is None and message explains the error.
    """
    try:
        if not os.path.isfile(backup_path):
            return False, None, f"Backup file not found: {backup_path}"

        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        # Basic sanity check: the top level should be a JSON object
        if not isinstance(backup_data, dict):
            return False, None, "Invalid backup format: expected JSON object"

        logger.info(f"Backup loaded: {backup_path}")
        return True, backup_data, "Backup loaded successfully"

    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in backup file: {e}"
        logger.error(error_msg)
        return False, None, error_msg
    except Exception as e:
        error_msg = f"Failed to load backup: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def list_backups(backup_dir: Optional[str] = None) -> List[Tuple[str, str, datetime]]:
    """
    List all backup files in the backup directory, sorted newest-first.

    Only files matching the naming pattern "backup_*.json" are included.

    Args:
        backup_dir: Directory to scan. Uses DEFAULT_BACKUP_DIR if None.

    Returns:
        A list of tuples: (filename, full_path, last_modified_datetime).
        Sorted by modification time with the newest backup first.
        Returns an empty list if no backups exist or on error.
    """
    try:
        backup_dir = _ensure_backup_dir(backup_dir)

        backups = []
        for filename in os.listdir(backup_dir):
            # Only include files that match our naming convention
            if filename.startswith('backup_') and filename.endswith('.json'):
                full_path = os.path.join(backup_dir, filename)
                mtime = os.path.getmtime(full_path)
                mod_time = datetime.fromtimestamp(mtime)
                backups.append((filename, full_path, mod_time))

        # Newest first — so the most recent backup is at index 0
        backups.sort(key=lambda x: x[2], reverse=True)
        return backups

    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []


def _cleanup_old_backups(backup_dir: str, keep_count: int = 10) -> int:
    """
    Delete old backup files to prevent the backups folder from growing indefinitely.

    Keeps the most recent `keep_count` backups and deletes everything older.
    This is called automatically after every new backup is created.

    Args:
        backup_dir: Directory containing the backup files.
        keep_count: How many recent backups to keep (default: 10).

    Returns:
        The number of backup files that were deleted.
    """
    try:
        backups = list_backups(backup_dir)

        # Nothing to clean up if we're under the limit
        if len(backups) <= keep_count:
            return 0

        deleted_count = 0
        # backups is sorted newest-first, so [keep_count:] gives us the oldest ones
        for filename, full_path, _ in backups[keep_count:]:
            try:
                os.remove(full_path)
                logger.info(f"Deleted old backup: {filename}")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete backup {filename}: {e}")

        return deleted_count

    except Exception as e:
        logger.warning(f"Backup cleanup failed: {e}")
        return 0


def extract_backup_metadata(backup_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Pull out human-readable summary info from a loaded backup.

    This is used by the GUI to display a quick overview of what's inside a
    backup file before the user decides to restore it — showing things like
    how many rules it contains, when it was created, etc.

    Args:
        backup_data: The backup dictionary from load_backup().

    Returns:
        A dictionary with string values suitable for display:
          'backup_time'           — when the backup was created
          'rule_count'            — number of RSS rules in the backup
          'category_count'        — number of categories
          'feed_count'            — number of RSS feeds
          'qbittorrent_version'   — version of qBittorrent at backup time
    """
    try:
        metadata = backup_data.get('metadata', {})
        backup_time = backup_data.get('backup_timestamp', 'Unknown')
        rule_count = len(backup_data.get('rules', {}))
        category_count = len(backup_data.get('categories', {}))
        feed_count = len(backup_data.get('feeds', []))
        qbt_version = metadata.get('qbittorrent_version', 'Unknown')

        return {
            'backup_time': backup_time,
            'rule_count': str(rule_count),
            'category_count': str(category_count),
            'feed_count': str(feed_count),
            'qbittorrent_version': qbt_version,
        }
    except Exception as e:
        logger.error(f"Failed to extract backup metadata: {e}")
        return {}
