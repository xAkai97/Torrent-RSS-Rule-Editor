"""
Cache management for storing and retrieving application data.
"""
# Standard library imports
import json
import logging
import os
from typing import Any, Dict, List

# Local application imports
from .config import config
from .constants import CacheKeys

logger = logging.getLogger(__name__)


def _load_cache_data() -> Dict[str, Any]:
    """
    Loads cache data from the cache file.
    
    Returns:
        Dict containing all cached data, or empty dict if file doesn't exist
    """
    if not os.path.exists(config.CACHE_FILE):
        return {}
    
    try:
        with open(config.CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.debug(f"Loaded cache data with keys: {list(data.keys())}")
        return data
    except Exception as e:
        logger.error(f"Failed to load cache file '{config.CACHE_FILE}': {e}")
        return {}


def _save_cache_data(data: Dict[str, Any]) -> bool:
    """
    Saves cache data to the cache file.
    
    Args:
        data: Dictionary containing all cache data
    
    Returns:
        bool: True if successful
    """
    try:
        with open(config.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved cache data with keys: {list(data.keys())}")
        return True
    except Exception as e:
        logger.error(f"Failed to save cache file '{config.CACHE_FILE}': {e}")
        return False


def _update_cache_key(key: str, value: Any) -> bool:
    """
    Updates a specific key in the cache file.
    
    Args:
        key: Cache key to update
        value: New value for the key
    
    Returns:
        bool: True if successful
    """
    data = _load_cache_data()
    data[key] = value
    return _save_cache_data(data)


def load_recent_files() -> List[str]:
    """
    Loads the list of recently opened files from cache.
    
    Returns:
        List of file paths
    """
    data = _load_cache_data()
    files = data.get(CacheKeys.RECENT_FILES, [])
    logger.info(f"Loaded {len(files)} recent files")
    return files


def load_cached_categories() -> Dict[str, Any]:
    """
    Loads cached qBittorrent categories.
    
    Returns:
        Dict of categories
    """
    data = _load_cache_data()
    categories = data.get(CacheKeys.CATEGORIES, {})
    logger.info(f"Loaded {len(categories)} cached categories")
    return categories


def load_cached_feeds() -> Dict[str, Any]:
    """
    Loads cached RSS feeds.
    
    Returns:
        Dict of feeds
    """
    data = _load_cache_data()
    feeds = data.get(CacheKeys.FEEDS, {})
    logger.info(f"Loaded {len(feeds)} cached feeds")
    return feeds


def save_cached_feeds(feeds: Dict[str, Any]) -> bool:
    """
    Saves RSS feeds to cache.
    
    Args:
        feeds: Dictionary of feeds to cache
    
    Returns:
        bool: True if successful
    """
    try:
        success = _update_cache_key(CacheKeys.FEEDS, feeds)
        if success:
            logger.info(f"Saved {len(feeds)} feeds to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save cached feeds: {e}")
        return False


def save_cached_categories(categories: Dict[str, Any]) -> bool:
    """
    Saves categories to cache.
    
    Args:
        categories: Dictionary of categories to cache
    
    Returns:
        bool: True if successful
    """
    try:
        success = _update_cache_key(CacheKeys.CATEGORIES, categories)
        if success:
            logger.info(f"Saved {len(categories)} categories to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save cached categories: {e}")
        return False


def save_recent_files(files: List[str]) -> bool:
    """
    Saves recent files list to cache.
    
    Args:
        files: List of file paths
    
    Returns:
        bool: True if successful
    """
    try:
        success = _update_cache_key(CacheKeys.RECENT_FILES, files)
        if success:
            logger.info(f"Saved {len(files)} recent files to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save recent files: {e}")
        return False


def load_prefs() -> Dict[str, Any]:
    """
    Loads user preferences from cache.
    
    Returns:
        Dict of preferences
    """
    try:
        data = _load_cache_data()
        prefs = data.get(CacheKeys.PREFS, {})
        logger.info(f"Loaded {len(prefs)} preferences")
        return prefs
    except Exception as e:
        logger.error(f"Failed to load preferences: {e}")
        return {}


def save_prefs(prefs: Dict[str, Any]) -> bool:
    """
    Saves user preferences to cache.
    
    Args:
        prefs: Dictionary of preferences
    
    Returns:
        bool: True if successful
    """
    try:
        success = _update_cache_key(CacheKeys.PREFS, prefs)
        if success:
            logger.info(f"Saved {len(prefs)} preferences to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save preferences: {e}")
        return False


def get_pref(key: str, default: Any = None) -> Any:
    """
    Gets a single preference value.
    
    Args:
        key: Preference key
        default: Default value if key doesn't exist
    
    Returns:
        The preference value or default
    """
    try:
        prefs = load_prefs()
        return prefs.get(key, default)
    except Exception as e:
        logger.warning(f"Failed to get preference '{key}': {e}")
        return default


def set_pref(key: str, value: Any) -> bool:
    """
    Sets a single preference value.
    
    Args:
        key: Preference key
        value: Value to set
    
    Returns:
        bool: True if successful
    """
    try:
        prefs = load_prefs()
        prefs[key] = value
        return save_prefs(prefs)
    except Exception as e:
        logger.error(f"Failed to set preference '{key}': {e}")
        return False


def add_recent_file(path: str, limit: int = 10) -> bool:
    """
    Adds a file to the recent files list.
    
    Args:
        path: File path to add
        limit: Maximum number of recent files to keep
    
    Returns:
        bool: True if successful
    """
    try:
        files = load_recent_files()
        if path in files:
            files.remove(path)
        files.insert(0, path)
        files = files[:limit]
        return save_recent_files(files)
    except Exception as e:
        logger.error(f"Failed to add recent file: {e}")
        return False


def clear_recent_files() -> bool:
    """
    Clears the recent files list.
    
    Returns:
        bool: True if successful
    """
    try:
        return save_recent_files([])
    except Exception as e:
        logger.error(f"Failed to clear recent files: {e}")
        return False


# ==================== Template Management ====================

def load_templates() -> Dict[str, Dict[str, Any]]:
    """
    Loads saved rule templates from cache.
    
    Returns:
        Dict mapping template names to template configurations
    """
    data = _load_cache_data()
    templates = data.get(CacheKeys.TEMPLATES, {})
    logger.info(f"Loaded {len(templates)} templates")
    return templates


def save_templates(templates: Dict[str, Dict[str, Any]]) -> bool:
    """
    Saves rule templates to cache.
    
    Args:
        templates: Dict mapping template names to configurations
    
    Returns:
        bool: True if successful
    """
    try:
        logger.info(f"Saving {len(templates)} templates")
        return _update_cache_key(CacheKeys.TEMPLATES, templates)
    except Exception as e:
        logger.error(f"Failed to save templates: {e}")
        return False


def add_template(name: str, template: Dict[str, Any]) -> bool:
    """
    Adds or updates a template.
    
    Args:
        name: Template name
        template: Template configuration dict
    
    Returns:
        bool: True if successful
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
    Deletes a template.
    
    Args:
        name: Template name to delete
    
    Returns:
        bool: True if successful
    """
    try:
        templates = load_templates()
        if name in templates:
            del templates[name]
            return save_templates(templates)
        return False
    except Exception as e:
        logger.error(f"Failed to delete template '{name}': {e}")
        return False


def get_default_templates() -> Dict[str, Dict[str, Any]]:
    """
    Returns a set of built-in default templates.
    
    Returns:
        Dict of default templates
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
            'must_not_contain': '1080p',
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
    Initializes cache with default templates if none exist.
    
    Returns:
        bool: True if templates were initialized
    """
    try:
        templates = load_templates()
        if not templates:
            logger.info("Initializing default templates")
            return save_templates(get_default_templates())
        return False
    except Exception as e:
        logger.error(f"Failed to initialize default templates: {e}")
        return False
