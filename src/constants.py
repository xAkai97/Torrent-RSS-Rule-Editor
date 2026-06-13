"""
Application-Wide Constants.

This module defines all the shared constants, configuration keys, and custom
exception classes used across the entire application. Centralizing them here
prevents magic strings/numbers from being scattered throughout the codebase
and makes it easy to find and update values in one place.

Sections:
  - Custom Exceptions     — Error types for qBittorrent communication failures
  - Season Constants      — Anime season names (Winter, Spring, Summer, Fall)
  - Cache Keys            — String keys for accessing sections of the cache file
  - Preference Keys       — String keys for user preferences stored in config
  - AniList Constants     — Refresh scope and cache retention mode enums
  - Filesystem Constants  — Invalid characters, reserved names, path limits
  - Network Constants     — Timeouts, API URLs, User-Agent string
  - UI Constants          — Window dimensions and layout values
  - Cache Limits          — Size and TTL caps for cached data
"""


# ============================================================================
# Custom Exception Classes
#
# These are raised by the qBittorrent API module when something goes wrong
# during communication with the qBittorrent server.
# ============================================================================

class QBittorrentAuthenticationError(Exception):
    """Raised when qBittorrent rejects the username/password credentials."""
    pass


class QBittorrentError(Exception):
    """Raised for general qBittorrent communication errors (timeout, bad response, etc.)."""
    pass


# ============================================================================
# Anime Season Names
# ============================================================================

class Season:
    """Standard anime season names, matching the typical broadcast calendar."""
    WINTER = "Winter"   # January – March
    SPRING = "Spring"   # April – June
    SUMMER = "Summer"   # July – September
    FALL = "Fall"       # October – December


# ============================================================================
# Cache Keys
#
# These are the top-level keys used in the cache.json file. Each key
# corresponds to a different section of cached data.
# ============================================================================

class CacheKeys:
    """String keys for sections within the cache.json file."""
    RECENT_FILES = 'recent_files'                     # List of recently opened rule files
    CATEGORIES = 'categories'                          # qBittorrent torrent categories
    FEEDS = 'feeds'                                    # qBittorrent RSS feed URLs
    TEMPLATES = 'rule_templates'                       # Saved rule templates for quick creation
    PREFS = 'prefs'                                    # User preferences (UI settings, etc.)
    SUBSPLEASE_TITLES = 'subsplease_titles'             # Cached SubsPlease anime schedule
    ANIME_TITLE_VARIATIONS = 'anime_title_variations'   # AniList title alias cache


# ============================================================================
# User Preference Keys
#
# These are the keys used to store individual user preferences in the
# config's preferences dictionary. They control UI behavior, sanitization
# rules, API cooldowns, and display settings.
# ============================================================================

class PrefKeys:
    """String keys for individual user preferences stored in config."""
    TIME_24 = 'time_24'                                               # Use 24-hour time format in the UI
    AUTO_SANITIZE = 'auto_sanitize_imports'                            # Automatically sanitize imported rule names
    SANITIZE_REPLACE_ALL = 'sanitize_replace_all'                      # Replace all invalid chars (vs. individual mapping)
    SANITIZE_GLOBAL_CHAR = 'sanitize_global_char'                      # The replacement character for sanitization
    SANITIZE_CUSTOM_MAP = 'sanitize_custom_map'                        # Custom per-character replacement map
    ANILIST_PULL_COOLDOWN_MINUTES = 'anilist_pull_cooldown_minutes'     # Minutes between manual AniList cache refreshes
    ANILIST_REFRESH_SCOPE = 'anilist_refresh_scope'                    # What to refresh: titles only, or titles + season
    ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE = 'anilist_title_variation_cache_retention_mode'  # Cache cleanup mode
    SUBSPLEASE_PULL_COOLDOWN_MINUTES = 'subsplease_pull_cooldown_minutes'  # Minutes between manual SubsPlease pulls
    ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS = 'anilist_title_variation_cache_ttl_days'  # Days before cache entry expires
    ANILIST_TITLE_VARIATION_CACHE_MAX_MB = 'anilist_title_variation_cache_max_mb'      # Max cache size in MB (size mode)
    ANILIST_DISPLAY_LANGUAGES = 'anilist_display_languages'             # Which title languages to show in the UI
    FONT_FAMILY = 'font_family'                                        # User-selected UI font family
    UI_STYLE_THEME = 'ui_style_theme'                                  # UI color theme name


# ============================================================================
# AniList Refresh Scope Options
# ============================================================================

class AniListRefreshScope:
    """Controls what gets refreshed when the user manually pulls AniList data."""
    TITLE_ONLY = 'title_only'               # Only refresh aliases for titles in the SubsPlease list
    TITLE_AND_SEASON = 'title_and_season'    # Also bulk-refresh all titles for the selected anime season


# ============================================================================
# Cache Retention Modes
# ============================================================================

class CacheRetentionMode:
    """Controls how old cache entries are cleaned up to prevent unbounded growth."""
    AGE = 'age'        # Delete entries older than a configurable TTL (default)
    SIZE = 'size'      # Delete oldest entries when cache exceeds a size limit
    ROTATE = 'rotate'  # Archive the full cache to a timestamped file before overwriting


# ============================================================================
# Filesystem Constants
#
# Used when sanitizing filenames/paths (e.g. rule names that become filenames).
# These are Windows-specific restrictions since qBittorrent runs on Windows.
# ============================================================================

class FileSystem:
    """Constants for filesystem validation and sanitization."""
    INVALID_CHARS = '<>:"/\\|?*'       # Characters that are illegal in Windows filenames
    RESERVED_NAMES = {                  # Windows reserved device names that can't be used as filenames
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    MAX_PATH_LENGTH = 255               # Maximum filename length (not full path length)


# ============================================================================
# Network Constants
# ============================================================================

class NetworkConfig:
    """Constants for HTTP requests and API communication."""
    DEFAULT_TIMEOUT = 10                # Seconds to wait before giving up on a request
    SUBSPLEASE_API_URL = "https://subsplease.org/api/?f=schedule&tz=UTC"  # SubsPlease schedule endpoint
    USER_AGENT = 'Torrent-RSS-Rule-Editor/1.0 (https://github.com/xAkai97/Torrent-RSS-Rule-Editor)'  # Identifies our app in requests


# ============================================================================
# UI Layout Constants
# ============================================================================

class UIConfig:
    """Default dimensions and layout values for the application windows."""
    DEFAULT_WINDOW_WIDTH = 1400         # Starting width of the main window
    DEFAULT_WINDOW_HEIGHT = 900         # Starting height of the main window
    WINDOW_TOP_MARGIN = 50              # Pixels of margin from the top of the screen
    MIN_WINDOW_WIDTH = 1400             # Minimum resizable width (prevents UI breakage)
    MIN_WINDOW_HEIGHT = 700             # Minimum resizable height
    SETTINGS_WINDOW_WIDTH = 800         # Width of the settings dialog
    SETTINGS_WINDOW_MIN_HEIGHT = 500    # Minimum height of the settings dialog


# ============================================================================
# Cache Size Limits
# ============================================================================

class CacheLimits:
    """Hard limits for cached data to prevent unbounded growth."""
    MAX_RECENT_FILES = 10               # Maximum number of recent files to remember
    CACHE_TTL_DAYS = 30                 # Default TTL for cached data (in days)
