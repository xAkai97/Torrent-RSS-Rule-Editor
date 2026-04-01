"""
Backup and restore functionality for qBittorrent rules.

Provides functions to:
- Create snapshots of current qBittorrent rules, categories, and feeds
- Restore from backup snapshots
- Manage backup file rotation and cleanup
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default backup directory
DEFAULT_BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', 'backups')


def _ensure_backup_dir(backup_dir: Optional[str] = None) -> str:
    """
    Ensure backup directory exists.
    
    Args:
        backup_dir: Custom backup directory path, uses DEFAULT_BACKUP_DIR if None
        
    Returns:
        Path to backup directory
        
    Raises:
        OSError: If directory cannot be created
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
    Create a backup of qBittorrent rules, categories, and feeds.
    
    Args:
        rules: Dictionary of RSS rules {rule_name: rule_definition}
        categories: Dictionary of categories (optional)
        feeds: List of feed URLs (optional)
        backup_dir: Directory to store backup, uses DEFAULT_BACKUP_DIR if None
        metadata: Additional metadata to include in backup
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        backup_dir = _ensure_backup_dir(backup_dir)
        
        # Create backup filename with timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f'backup_{timestamp}.json'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Prepare backup data
        backup_data = {
            'version': '1.0',
            'backup_timestamp': datetime.now().isoformat(),
            'rules': rules or {},
            'categories': categories or {},
            'feeds': feeds or [],
        }
        
        # Add optional metadata
        if metadata:
            backup_data['metadata'] = metadata
        
        # Write backup file
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Backup created: {backup_path}")
        message = f"Backup created: {backup_filename}"
        
        # Auto-cleanup old backups (keep last 10)
        _cleanup_old_backups(backup_dir, keep_count=10)
        
        return True, message
        
    except Exception as e:
        error_msg = f"Failed to create backup: {e}"
        logger.error(error_msg)
        return False, error_msg


def load_backup(backup_path: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Load a backup from file.
    
    Args:
        backup_path: Path to backup JSON file
        
    Returns:
        Tuple of (success: bool, backup_data: dict or None, message: str)
    """
    try:
        if not os.path.isfile(backup_path):
            return False, None, f"Backup file not found: {backup_path}"
        
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
        
        # Validate backup structure
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
    List all backup files in backup directory.
    
    Args:
        backup_dir: Directory containing backups, uses DEFAULT_BACKUP_DIR if None
        
    Returns:
        List of tuples: (filename, full_path, modification_time)
        Sorted by modification time (newest first)
    """
    try:
        backup_dir = _ensure_backup_dir(backup_dir)
        
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith('backup_') and filename.endswith('.json'):
                full_path = os.path.join(backup_dir, filename)
                mtime = os.path.getmtime(full_path)
                mod_time = datetime.fromtimestamp(mtime)
                backups.append((filename, full_path, mod_time))
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x[2], reverse=True)
        return backups
        
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []


def _cleanup_old_backups(backup_dir: str, keep_count: int = 10) -> int:
    """
    Delete old backup files, keeping only the most recent ones.
    
    Args:
        backup_dir: Directory containing backups
        keep_count: Number of backups to keep
        
    Returns:
        Number of backups deleted
    """
    try:
        backups = list_backups(backup_dir)
        
        if len(backups) <= keep_count:
            return 0
        
        deleted_count = 0
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
    Extract display metadata from backup data.
    
    Args:
        backup_data: Backup dictionary from load_backup()
        
    Returns:
        Dictionary with display information
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
