"""
Cache Management Module.

This module provides a convenient API for storing and retrieving application
data that needs to persist between app launches but isn't part of the user's
primary configuration. Think of it as a key-value store backed by a JSON file.

What gets cached (and why):
  - Recent files       → quick access to previously opened rule files
  - Categories         → qBittorrent categories (avoids re-fetching from server each time)
  - RSS feeds          → qBittorrent RSS feed URLs (same reason)
  - Rule templates     → user-saved and built-in rule presets
  - User preferences   → UI settings like time format, font, theme

Architecture note:
  This module is a thin wrapper around config.py's low-level cache I/O.
  It adds domain-specific methods (load_recent_files, save_cached_categories, etc.)
  so the rest of the app doesn't need to know about cache keys or file formats.
  The actual file I/O (reading/writing cache.json) is handled by config.py.
"""

# Standard library imports
import logging
from typing import Any, Dict, List

# Local application imports
from .config import config
from .constants import CacheKeys

logger = logging.getLogger(__name__)


# ============================================================================
# Low-level cache operations
#
# These are internal helpers that read/write the entire cache file.
# Higher-level functions below use these to access specific cache sections.
# ============================================================================

def _load_cache_data() -> Dict[str, Any]:
    """
    Load the entire cache file from disk.

    Returns:
        A dictionary containing all cached data sections, or an empty dict
        if the cache file doesn't exist or can't be read.
    """
    try:
        data = config._load_cache_data()
        logger.debug(f"Loaded cache data with keys: {list(data.keys())}")
        return data
    except Exception as e:
        logger.error(f"Failed to load cache file '{config.CACHE_FILE}': {e}")
        return {}


def _save_cache_data(data: Dict[str, Any]) -> bool:
    """
    Write the entire cache dictionary back to disk.

    This overwrites the entire cache file, so callers should load the
    existing data first, modify it, then save the whole thing back.

    Args:
        data: The complete cache dictionary to write.

    Returns:
        True if the save was successful, False otherwise.
    """
    try:
        success = bool(config._save_cache_data(data))
        if success:
            logger.debug(f"Saved cache data with keys: {list(data.keys())}")
        return success
    except Exception as e:
        logger.error(f"Failed to save cache file '{config.CACHE_FILE}': {e}")
        return False


def _update_cache_key(key: str, value: Any) -> bool:
    """
    Update a single section of the cache without touching other sections.

    This is a convenience method that loads the full cache, updates one key,
    and saves everything back. It's the most common pattern used by the
    higher-level save functions below.

    Args:
        key: The cache section key (use CacheKeys constants).
        value: The new value to store under that key.

    Returns:
        True if the update was successful, False otherwise.
    """
    data = _load_cache_data()
    data[key] = value
    return _save_cache_data(data)


# ============================================================================
# Recent Files — tracks which rule files the user has opened recently
# ============================================================================

def load_recent_files() -> List[str]:
    """
    Get the list of recently opened file paths.

    Returns:
        A list of file path strings, most recent first.
    """
    data = _load_cache_data()
    files = data.get(CacheKeys.RECENT_FILES, [])
    logger.info(f"Loaded {len(files)} recent files")
    return files


def save_recent_files(files: List[str]) -> bool:
    """
    Save the recent files list to cache.

    Args:
        files: List of file path strings to save.

    Returns:
        True if successful.
    """
    try:
        success = _update_cache_key(CacheKeys.RECENT_FILES, files)
        if success:
            logger.info(f"Saved {len(files)} recent files to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save recent files: {e}")
        return False


def add_recent_file(path: str, limit: int = 10) -> bool:
    """
    Add a file to the top of the recent files list.

    If the file is already in the list, it gets moved to the top (most recent).
    The list is capped at `limit` entries to prevent it from growing forever.

    Args:
        path: The file path to add.
        limit: Maximum number of recent files to remember (default: 10).

    Returns:
        True if successful.
    """
    try:
        files = load_recent_files()
        # If already in the list, remove it first so it moves to the top
        if path in files:
            files.remove(path)
        # Insert at the beginning (most recent position)
        files.insert(0, path)
        # Trim to the limit
        files = files[:limit]
        return save_recent_files(files)
    except Exception as e:
        logger.error(f"Failed to add recent file: {e}")
        return False


def clear_recent_files() -> bool:
    """
    Clear the entire recent files list.

    Returns:
        True if successful.
    """
    try:
        return save_recent_files([])
    except Exception as e:
        logger.error(f"Failed to clear recent files: {e}")
        return False


# ============================================================================
# Categories — cached copy of qBittorrent's torrent categories
#
# Categories are cached so the GUI can populate category dropdowns instantly
# without needing to connect to the qBittorrent server on every app launch.
# ============================================================================

def load_cached_categories() -> Dict[str, Any]:
    """
    Load the cached qBittorrent categories.

    Returns:
        A dictionary mapping category names to their settings.
    """
    data = _load_cache_data()
    categories = data.get(CacheKeys.CATEGORIES, {})
    logger.info(f"Loaded {len(categories)} cached categories")
    return categories


def save_cached_categories(categories: Dict[str, Any]) -> bool:
    """
    Save qBittorrent categories to the cache.

    Typically called after fetching fresh categories from the qBittorrent server.

    Args:
        categories: Dictionary of category names to their settings.

    Returns:
        True if successful.
    """
    try:
        success = _update_cache_key(CacheKeys.CATEGORIES, categories)
        if success:
            logger.info(f"Saved {len(categories)} categories to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save cached categories: {e}")
        return False


# ============================================================================
# RSS Feeds — cached copy of qBittorrent's RSS feed list
#
# Same idea as categories — cached for instant GUI population.
# ============================================================================

def load_cached_feeds() -> Dict[str, Any]:
    """
    Load the cached RSS feeds.

    Returns:
        A dictionary of cached feed data.
    """
    data = _load_cache_data()
    feeds = data.get(CacheKeys.FEEDS, {})
    logger.info(f"Loaded {len(feeds)} cached feeds")
    return feeds


def save_cached_feeds(feeds: Dict[str, Any]) -> bool:
    """
    Save RSS feeds to the cache.

    Typically called after fetching fresh feeds from the qBittorrent server.

    Args:
        feeds: Dictionary of feed data to cache.

    Returns:
        True if successful.
    """
    try:
        success = _update_cache_key(CacheKeys.FEEDS, feeds)
        if success:
            logger.info(f"Saved {len(feeds)} feeds to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save cached feeds: {e}")
        return False


# ============================================================================
# User Preferences — settings like time format, theme, font, etc.
#
# Preferences are stored in config.ini (not cache.json) for easier manual
# editing, but this module provides the access API for consistency.
# ============================================================================

def load_prefs() -> Dict[str, Any]:
    """
    Load all user preferences from the config.ini file.

    Returns:
        A dictionary of all user preferences.
    """
    try:
        prefs = config._load_ini_prefs()
        logger.info(f"Loaded {len(prefs)} preferences")
        return prefs
    except Exception as e:
        logger.error(f"Failed to load preferences: {e}")
        return {}


def save_prefs(prefs: Dict[str, Any]) -> bool:
    """
    Save all user preferences to the config.ini file.

    Args:
        prefs: Dictionary of all preferences to save.

    Returns:
        True if successful.
    """
    try:
        success = config._save_ini_prefs(prefs)
        if success:
            logger.info(f"Saved {len(prefs)} preferences to config.ini")
        return success
    except Exception as e:
        logger.error(f"Failed to save preferences: {e}")
        return False


def get_pref(key: str, default: Any = None) -> Any:
    """
    Read a single user preference value.

    Args:
        key: The preference key (use PrefKeys constants).
        default: Value to return if the key doesn't exist.

    Returns:
        The stored preference value, or the default if not found.
    """
    try:
        return config.get_pref(key, default)
    except Exception as e:
        logger.warning(f"Failed to get preference '{key}': {e}")
        return default


def set_pref(key: str, value: Any) -> bool:
    """
    Write a single user preference value.

    Args:
        key: The preference key (use PrefKeys constants).
        value: The value to store.

    Returns:
        True if successful.
    """
    try:
        return config.set_pref(key, value)
    except Exception as e:
        logger.error(f"Failed to set preference '{key}': {e}")
        return False


# ============================================================================
# Rule Templates — saved presets for quickly creating new rules
#
# Templates let users save their preferred rule settings (resolution filter,
# category, exclusion patterns, etc.) and reuse them when creating new rules.
# A set of built-in defaults is also provided for first-time users.
# ============================================================================

def load_templates() -> Dict[str, Dict[str, Any]]:
    """
    Load all saved rule templates from the cache.

    Returns:
        A dictionary mapping template names to their configuration dicts.
    """
    data = _load_cache_data()
    templates = data.get(CacheKeys.TEMPLATES, {})
    logger.info(f"Loaded {len(templates)} templates")
    return templates


def save_templates(templates: Dict[str, Dict[str, Any]]) -> bool:
    """
    Save rule templates to the cache.

    Args:
        templates: Dictionary mapping template names to configurations.

    Returns:
        True if successful.
    """
    try:
        logger.info(f"Saving {len(templates)} templates")
        return _update_cache_key(CacheKeys.TEMPLATES, templates)
    except Exception as e:
        logger.error(f"Failed to save templates: {e}")
        return False


def add_template(name: str, template: Dict[str, Any]) -> bool:
    """
    Add or update a single rule template.

    If a template with the same name already exists, it will be overwritten.

    Args:
        name: Display name for the template.
        template: The template configuration dictionary.

    Returns:
        True if successful.
    """
    try:
        templates = load_templates()
        templates[name] = template
        return save_templates(templates)
    except Exception as e:
        logger.error(f"Failed to add template '{name}': {e}")
        return False


def delete_template(name: str) -> bool:
    """
    Remove a rule template by name.

    Args:
        name: Name of the template to delete.

    Returns:
        True if the template was found and deleted, False otherwise.
    """
    try:
        templates = load_templates()
        if name in templates:
            del templates[name]
            return save_templates(templates)
        return False  # Template didn't exist
    except Exception as e:
        logger.error(f"Failed to delete template '{name}': {e}")
        return False


def get_default_templates() -> Dict[str, Dict[str, Any]]:
    """
    Return the built-in default rule templates.

    These are provided for first-time users who don't have any saved templates.
    They cover common anime download scenarios with sensible default settings.

    Returns:
        A dictionary of template name → template configuration.
    """
    return {
        '1080p Seasonal': {
            'description': 'High quality seasonal anime (1080p)',
            'must_contain': '1080p',
            'must_not_contain': '',
            'category': 'anime',
            'save_path': '',
            'enabled': True,
            'episode_filter': '',
            'use_regex': False,
        },
        '720p Seasonal': {
            'description': 'Standard quality seasonal anime (720p)',
            'must_contain': '720p',
            'must_not_contain': '1080p',    # Exclude 1080p to avoid duplicates
            'category': 'anime',
            'save_path': '',
            'enabled': True,
            'episode_filter': '',
            'use_regex': False,
        },
        'Movie': {
            'description': 'Anime movies',
            'must_contain': 'Movie',
            'must_not_contain': '',
            'category': 'anime-movies',
            'save_path': '',
            'enabled': True,
            'episode_filter': '',
            'use_regex': False,
        },
        'OVA/Special': {
            'description': 'OVAs and special episodes',
            'must_contain': '',
            'must_not_contain': '',
            'category': 'anime-ova',
            'save_path': '',
            'enabled': True,
            'episode_filter': '',
            'use_regex': False,
        },
        'Batch Download': {
            'description': 'Complete series batch downloads',
            'must_contain': 'Batch',
            'must_not_contain': '',
            'category': 'anime-batch',
            'save_path': '',
            'enabled': True,
            'episode_filter': '',
            'use_regex': False,
        },
    }


def initialize_default_templates() -> bool:
    """
    Seed the cache with built-in default templates if none exist yet.

    Called on first app launch to give new users some templates to start with.
    Does nothing if the user already has saved templates.

    Returns:
        True if defaults were written, False if templates already existed.
    """
    try:
        templates = load_templates()
        if not templates:
            logger.info("Initializing default templates")
            return save_templates(get_default_templates())
        return False  # Templates already exist — don't overwrite
    except Exception as e:
        logger.error(f"Failed to initialize default templates: {e}")
        return False
