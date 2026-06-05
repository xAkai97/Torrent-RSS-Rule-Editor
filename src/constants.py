"""
Constants used throughout the application.
"""


# ==================== Custom Exception Classes ====================
class QBittorrentAuthenticationError(Exception):
    """Raised when authentication with qBittorrent fails."""
    pass


class QBittorrentError(Exception):
    """General qBittorrent-related errors."""
    pass


# ==================== Constants ====================
class Season:
    """Season name constants."""
    WINTER = "Winter"
    SPRING = "Spring"
    SUMMER = "Summer"
    FALL = "Fall"


class CacheKeys:
    """Cache dictionary key constants."""
    RECENT_FILES = 'recent_files'
    CATEGORIES = 'categories'
    FEEDS = 'feeds'
    TEMPLATES = 'rule_templates'
    PREFS = 'prefs'
    SUBSPLEASE_TITLES = 'subsplease_titles'
    ANIME_TITLE_VARIATIONS = 'anime_title_variations'


class PrefKeys:
    """User preference key constants."""
    TIME_24 = 'time_24'
    AUTO_SANITIZE = 'auto_sanitize_imports'
    SANITIZE_REPLACE_ALL = 'sanitize_replace_all'
    SANITIZE_GLOBAL_CHAR = 'sanitize_global_char'
    SANITIZE_CUSTOM_MAP = 'sanitize_custom_map'
    ANILIST_PULL_COOLDOWN_MINUTES = 'anilist_pull_cooldown_minutes'
    ANILIST_REFRESH_SCOPE = 'anilist_refresh_scope'
    ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE = 'anilist_title_variation_cache_retention_mode'
    SUBSPLEASE_PULL_COOLDOWN_MINUTES = 'subsplease_pull_cooldown_minutes'
    ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS = 'anilist_title_variation_cache_ttl_days'
    ANILIST_TITLE_VARIATION_CACHE_MAX_MB = 'anilist_title_variation_cache_max_mb'
    ANILIST_DISPLAY_LANGUAGES = 'anilist_display_languages'
    FONT_FAMILY = 'font_family'
    UI_STYLE_THEME = 'ui_style_theme'


class AniListRefreshScope:
    """AniList manual refresh scope constants."""
    TITLE_ONLY = 'title_only'
    TITLE_AND_SEASON = 'title_and_season'


class AniListCacheRetentionMode:
    """AniList title variation cache retention modes."""
    AGE = 'age'
    SIZE = 'size'
    ROTATE = 'rotate'


class FileSystem:
    """Filesystem-related constants."""
    INVALID_CHARS = '<>:"/\\|?*'
    RESERVED_NAMES = {
        'CON', 'PRN', 'AUX', 'NUL',
        'CON1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    MAX_PATH_LENGTH = 255


class NetworkConfig:
    """Network-related constants."""
    DEFAULT_TIMEOUT = 10
    SUBSPLEASE_API_URL = "https://subsplease.org/api/?f=schedule&tz=UTC"
    USER_AGENT = 'Torrent-RSS-Rule-Editor/1.0 (https://github.com/your-username/Torrent-RSS-Rule-Editor)'


class UIConfig:
    """UI-related constants."""
    DEFAULT_WINDOW_WIDTH = 1400
    DEFAULT_WINDOW_HEIGHT = 900
    WINDOW_TOP_MARGIN = 50
    MIN_WINDOW_WIDTH = 1400
    MIN_WINDOW_HEIGHT = 700
    SETTINGS_WINDOW_WIDTH = 800
    SETTINGS_WINDOW_MIN_HEIGHT = 500


class CacheLimits:
    """Cache size limits."""
    MAX_RECENT_FILES = 10
    CACHE_TTL_DAYS = 30
