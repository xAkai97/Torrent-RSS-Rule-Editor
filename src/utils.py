"""
Utility functions for the application.

Includes helper functions for title entry handling (hybrid format) and
filesystem operations.
"""
# Standard library imports
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Local application imports
from .constants import FileSystem, PrefKeys

logger = logging.getLogger(__name__)

# ============================================================================
# TITLE ENTRY HELPERS
# ============================================================================
# These functions provide safe access to the hybrid title entry format used
# in config.ALL_TITLES. Entries contain both qBittorrent fields and internal
# tracking fields ('node', 'ruleName'). See config.py for full documentation.
# ============================================================================

# Internal tracking fields that should be filtered before export
INTERNAL_FIELDS = frozenset(['node', 'ruleName'])


def get_display_title(entry: Any, fallback: str = '') -> str:
    """
    Get the display title from a title entry.
    
    Tries to extract the title in this priority order:
    1. entry['node']['title'] - primary display title
    2. entry['title'] - direct title field
    3. entry['mustContain'] - qBittorrent search pattern
    4. str(entry) - convert non-dict entries to string
    5. fallback - provided fallback value
    
    Args:
        entry: Title entry (dict or string)
        fallback: Value to return if no title found
        
    Returns:
        str: Display title for the entry
    """
    if not entry:
        return fallback
        
    if isinstance(entry, dict):
        node = entry.get('node') or {}
        title = node.get('title') or entry.get('title') or entry.get('mustContain')
        return str(title) if title else fallback
    
    return str(entry) if entry else fallback


def get_rule_name(entry: Any, fallback: str = '') -> str:
    """
    Get the rule name from a title entry.
    
    The rule name is used as the key when syncing to qBittorrent.
    
    Tries to extract in this priority order:
    1. entry['ruleName'] - explicit rule name
    2. entry['name'] - alternative name field
    3. entry['node']['title'] - display title as fallback
    4. entry['mustContain'] - search pattern
    5. fallback - provided fallback value
    
    Args:
        entry: Title entry (dict or string)
        fallback: Value to return if no name found
        
    Returns:
        str: Rule name for the entry
    """
    if not entry:
        return fallback
        
    if isinstance(entry, dict):
        name = entry.get('ruleName') or entry.get('name')
        if name:
            return str(name)
        # Fall back to display title
        node = entry.get('node') or {}
        title = node.get('title') or entry.get('mustContain')
        return str(title) if title else fallback
    
    return str(entry) if entry else fallback


def get_must_contain(entry: Any, fallback: str = '') -> str:
    """
    Get the mustContain pattern from a title entry.
    
    Args:
        entry: Title entry (dict or string)
        fallback: Value to return if not found
        
    Returns:
        str: The search pattern for RSS matching
    """
    if not entry:
        return fallback
        
    if isinstance(entry, dict):
        must = entry.get('mustContain')
        if must:
            return str(must)
        # Fall back to display title
        return get_display_title(entry, fallback)
    
    return str(entry) if entry else fallback


def strip_internal_fields(entry: Any) -> Any:
    """
    Remove internal tracking fields from a title entry.
    
    Creates a clean copy of the entry without 'node' and 'ruleName' fields,
    suitable for export to JSON or syncing to qBittorrent.
    
    Args:
        entry: Title entry (dict or any type)
        
    Returns:
        Clean entry without internal fields (dict entries are copied)
    """
    if not isinstance(entry, dict):
        return entry
    
    return {k: v for k, v in entry.items() if k not in INTERNAL_FIELDS}


def strip_internal_fields_from_titles(titles: Dict[str, List[Any]]) -> Dict[str, List[Any]]:
    """
    Remove internal tracking fields from all entries in a titles structure.
    
    Creates a clean copy of the entire ALL_TITLES structure without
    'node' and 'ruleName' fields, suitable for export.
    
    Args:
        titles: Dictionary of titles organized by media type
        
    Returns:
        Clean titles structure without internal fields
    """
    clean_titles = {}
    for media_type, items in titles.items():
        clean_items = []
        for item in items:
            if isinstance(item, dict):
                clean_items.append(strip_internal_fields(item))
            else:
                clean_items.append(item)
        clean_titles[media_type] = clean_items
    return clean_titles


def create_title_entry(
    display_title: str,
    must_contain: Optional[str] = None,
    rule_name: Optional[str] = None,
    save_path: Optional[str] = None,
    category: Optional[str] = None,
    feed_url: Optional[str] = None,
    enabled: bool = True,
    **extra_fields
) -> Dict[str, Any]:
    """
    Create a properly structured title entry.
    
    Creates an entry with both qBittorrent fields and internal tracking fields.
    
    Args:
        display_title: Title to display in the GUI
        must_contain: RSS search pattern (defaults to display_title)
        rule_name: Rule name for qBittorrent (defaults to display_title)
        save_path: Download save path
        category: qBittorrent category
        feed_url: RSS feed URL
        enabled: Whether rule is enabled
        **extra_fields: Additional qBittorrent fields to include
        
    Returns:
        dict: Properly structured title entry
    """
    entry = {
        # Internal tracking fields
        'node': {'title': display_title},
        'ruleName': rule_name or display_title,
        # qBittorrent fields
        'mustContain': must_contain or display_title,
        'enabled': enabled,
    }
    
    if save_path:
        entry['savePath'] = save_path
    if category:
        entry['assignedCategory'] = category
    if feed_url:
        entry['affectedFeeds'] = [feed_url]
    
    # Add any extra fields
    entry.update(extra_fields)
    
    return entry


def get_category_save_path(category_info: Any) -> str:
    """
    Extract category save path from qBittorrent category info.

    Supports both qBittorrent's native ``save_path`` key and legacy
    ``savePath`` key used by parts of this app.

    Args:
        category_info: Category data (dict or string)

    Returns:
        str: Normalized save path using forward slashes, or empty string
    """
    if isinstance(category_info, str):
        return category_info.replace('\\', '/').strip()

    if not isinstance(category_info, dict):
        return ''

    path = (
        category_info.get('save_path')
        or category_info.get('savePath')
        or category_info.get('path')
        or ''
    )
    normalized = str(path).replace('\\', '/').strip()
    while '//' in normalized:
        normalized = normalized.replace('//', '/')
    return normalized


def is_absolute_path(path: str) -> bool:
    """
    Check whether a path is absolute in either Unix or Windows style.

    Args:
        path: Path string to inspect

    Returns:
        bool: True if absolute
    """
    if not path or not isinstance(path, str):
        return False

    p = path.strip().replace('\\', '/')
    if not p:
        return False

    # Unix absolute or UNC-like normalized prefix
    if p.startswith('/') or p.startswith('//'):
        return True

    # Windows drive path (e.g., C:/Downloads)
    return bool(re.match(r'^[A-Za-z]:/', p))


def compose_effective_download_path(
    default_download_path: str,
    category_save_path: str,
    rule_save_path: str
) -> str:
    """
    Compose the effective full destination path.

    Resolution order:
    1. Absolute rule path wins.
    2. Otherwise join relative parts in order:
       default_download_path + category_save_path + rule_save_path
    3. Absolute category path bypasses default_download_path.

    Args:
        default_download_path: qBittorrent global default path
        category_save_path: Category-level save path
        rule_save_path: Rule-level save path

    Returns:
        str: Normalized path using forward slashes
    """
    def _normalize(value: Any) -> str:
        path = str(value or '').strip().replace('\\', '/')
        while '//' in path:
            path = path.replace('//', '/')
        return path

    def _strip_slashes(value: str) -> str:
        return value.strip('/').strip()

    default_path = _normalize(default_download_path)
    category_path = _normalize(category_save_path)
    rule_path = _normalize(rule_save_path)

    if is_absolute_path(rule_path):
        return rule_path

    parts: List[str] = []

    if category_path and is_absolute_path(category_path):
        base = category_path.rstrip('/')
        if rule_path:
            return f"{base}/{_strip_slashes(rule_path)}"
        return base

    if default_path:
        parts.append(default_path.rstrip('/'))
    if category_path:
        parts.append(_strip_slashes(category_path))
    if rule_path:
        parts.append(_strip_slashes(rule_path))

    if not parts:
        return ''

    return '/'.join(p for p in parts if p)


def find_entry_by_title(
    titles: Dict[str, List[Any]], 
    search_title: str, 
    case_sensitive: bool = False
) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    """
    Find a title entry by its display title.
    
    Args:
        titles: Dictionary of titles organized by media type
        search_title: Title to search for
        case_sensitive: Whether to match case-sensitively
        
    Returns:
        Tuple of (media_type, index, entry) if found, None otherwise
    """
    search = search_title if case_sensitive else search_title.lower()
    
    for media_type, items in titles.items():
        for idx, item in enumerate(items):
            title = get_display_title(item)
            compare = title if case_sensitive else title.lower()
            if compare == search:
                return (media_type, idx, item)
    
    return None


def is_duplicate_title(
    titles: Dict[str, List[Any]], 
    check_title: str,
    case_sensitive: bool = False
) -> bool:
    """
    Check if a title already exists in the titles structure.
    
    Args:
        titles: Dictionary of titles organized by media type
        check_title: Title to check for duplicates
        case_sensitive: Whether to match case-sensitively
        
    Returns:
        bool: True if title already exists
    """
    return find_entry_by_title(titles, check_title, case_sensitive) is not None


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================
# These functions validate title entries to prevent metadata pollution
# and ensure data integrity.
# ============================================================================

# Valid qBittorrent RSS rule fields (from qBittorrent API)
VALID_QBT_FIELDS = frozenset([
    'addPaused', 'affectedFeeds', 'assignedCategory', 'enabled',
    'episodeFilter', 'ignoreDays', 'lastMatch', 'mustContain',
    'mustNotContain', 'previouslyMatchedEpisodes', 'priority',
    'savePath', 'smartFilter', 'torrentContentLayout', 'torrentParams',
    'useRegex'
])

# Valid torrentParams sub-fields
VALID_TORRENT_PARAMS_FIELDS = frozenset([
    'category', 'download_limit', 'download_path', 'inactive_seeding_time_limit',
    'operating_mode', 'ratio_limit', 'save_path', 'seeding_time_limit',
    'share_limit_action', 'skip_checking', 'ssl_certificate', 'ssl_dh_params',
    'ssl_private_key', 'stopped', 'tags', 'upload_limit', 'use_auto_tmm'
])


def validate_entry_structure(entry: Any) -> Tuple[bool, List[str]]:
    """
    Validate that a title entry has the correct structure.
    
    Checks for:
    - Required fields present
    - No unexpected fields that could indicate metadata pollution
    - Valid field types
    
    Args:
        entry: Title entry to validate
        
    Returns:
        Tuple[bool, List[str]]: (is_valid, list_of_warnings)
    """
    warnings = []
    
    if not isinstance(entry, dict):
        return True, []  # Non-dict entries are allowed (simple strings)
    
    # Check for unexpected fields (not qBT fields or known internal fields)
    all_valid_fields = VALID_QBT_FIELDS | INTERNAL_FIELDS
    for key in entry.keys():
        if key not in all_valid_fields:
            warnings.append(f"Unexpected field '{key}' found (may be metadata pollution)")
    
    # Validate torrentParams if present
    torrent_params = entry.get('torrentParams')
    if isinstance(torrent_params, dict):
        for key in torrent_params.keys():
            if key not in VALID_TORRENT_PARAMS_FIELDS:
                warnings.append(f"Unexpected torrentParams field '{key}'")
    
    # Check internal fields have correct structure
    node = entry.get('node')
    if node is not None and not isinstance(node, dict):
        warnings.append("'node' field should be a dictionary")
    
    rule_name = entry.get('ruleName')
    if rule_name is not None and not isinstance(rule_name, str):
        warnings.append("'ruleName' field should be a string")
    
    return len(warnings) == 0, warnings


def validate_entries_for_export(titles: Dict[str, List[Any]]) -> Tuple[bool, List[str]]:
    """
    Validate all entries in a titles structure before export.
    
    Checks that no internal fields or unexpected data will leak into export.
    
    Args:
        titles: Dictionary of titles organized by media type
        
    Returns:
        Tuple[bool, List[str]]: (all_valid, list_of_all_warnings)
    """
    all_warnings = []
    
    for media_type, items in titles.items():
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                # Check for internal fields that shouldn't be in export
                for field in INTERNAL_FIELDS:
                    if field in item:
                        # This is expected - just note it will be filtered
                        pass
                
                # Validate structure
                _, warnings = validate_entry_structure(item)
                for warning in warnings:
                    all_warnings.append(f"{media_type}[{idx}]: {warning}")
    
    return len(all_warnings) == 0, all_warnings


def sanitize_entry_for_export(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize an entry for export, removing internal fields and unknown fields.
    
    This is more aggressive than strip_internal_fields - it only keeps
    known qBittorrent fields to prevent any metadata pollution.
    
    Args:
        entry: Title entry to sanitize
        
    Returns:
        dict: Clean entry with only valid qBittorrent fields
    """
    if not isinstance(entry, dict):
        return entry
    
    clean = {}
    for key, value in entry.items():
        if key in VALID_QBT_FIELDS:
            # Deep copy torrentParams to sanitize it too
            if key == 'torrentParams' and isinstance(value, dict):
                clean[key] = {k: v for k, v in value.items() if k in VALID_TORRENT_PARAMS_FIELDS}
            else:
                clean[key] = value
    
    return clean


def get_current_anime_season() -> Tuple[str, str]:
    """
    Returns the current anime season and year based on the current date.
    
    Returns:
        Tuple[str, str]: (season_name, year_string)
        
    Anime seasons:
    - Winter: January-March
    - Spring: April-June
    - Summer: July-September
    - Fall: October-December
    """
    now = datetime.now()
    month = now.month
    year = str(now.year)
    
    season_map = {
        (1, 2, 3): "Winter",
        (4, 5, 6): "Spring",
        (7, 8, 9): "Summer",
        (10, 11, 12): "Fall"
    }
    
    for months, season in season_map.items():
        if month in months:
            return season, year
    
    return "Fall", year  # Fallback (shouldn't happen)


def sanitize_folder_name(name: str, replacement_char: str = '_', max_length: int = 255) -> str:
    """
    Sanitizes a folder name by removing or replacing invalid characters.
    
    Respects user preferences for how special characters should be handled:
    - `sanitize_replace_all`: if True, replace every invalid char with a single
      user-specified character.
    - `sanitize_global_char`: the character to use when replacing all.
    - `sanitize_custom_map`: per-character replacement mapping used when
      `sanitize_replace_all` is False.
    
    Args:
        name: The original folder name
        replacement_char: Fallback character for replacing invalid characters
        max_length: Maximum length for the folder name
    
    Returns:
        str: Sanitized folder name safe for filesystem use
    """
    if not name:
        return replacement_char

    try:
        # Lazy import to avoid circular dependency during module import
        from src.config import config  # type: ignore

        replace_all_specials = bool(config.get_pref(PrefKeys.SANITIZE_REPLACE_ALL, True))
        global_char_pref = config.get_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, replacement_char)
        custom_map_pref = config.get_pref(PrefKeys.SANITIZE_CUSTOM_MAP, {}) or {}
        if not isinstance(custom_map_pref, dict):
            custom_map_pref = {}
    except Exception:
        replace_all_specials = True
        global_char_pref = replacement_char
        custom_map_pref = {}

    global_char = str(global_char_pref) if global_char_pref is not None else replacement_char
    if not global_char:
        global_char = replacement_char
    if len(global_char) > 1:
        # Use the first character to keep filenames predictable
        global_char = global_char[0]

    # Remove or replace invalid characters using user preferences
    sanitized = name
    if replace_all_specials:
        for char in FileSystem.INVALID_CHARS:
            sanitized = sanitized.replace(char, global_char)
    else:
        # Apply per-character overrides, falling back to provided replacement_char
        for char in FileSystem.INVALID_CHARS:
            replacement = custom_map_pref.get(char, replacement_char)
            sanitized = sanitized.replace(char, str(replacement))
    
    # Remove leading/trailing spaces and dots (Windows doesn't allow these)
    sanitized = sanitized.strip().strip('.')
    
    # Check for Windows reserved names
    base_name = sanitized.split('.')[0].upper()
    if base_name in FileSystem.RESERVED_NAMES:
        sanitized = f"{replacement_char}{sanitized}"
    
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    # Ensure we didn't end up with an empty string
    if not sanitized:
        sanitized = replacement_char
    
    return sanitized


def validate_folder_name(name: str) -> Tuple[bool, str]:
    """
    Validates if a string is a valid folder name.
    
    Args:
        name: Folder name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not name or not isinstance(name, str) or not name.strip():
        return False, 'Folder name cannot be empty'
    
    s = name.strip()
    
    # Check for invalid characters
    found_invalid = [c for c in s if c in FileSystem.INVALID_CHARS]
    if found_invalid:
        return False, f"Contains invalid characters: {', '.join(found_invalid)}"
    
    # Check for trailing space or dot
    if s.endswith(' ') or s.endswith('.'):
        return False, 'Cannot end with space or period'
    
    # Check for Windows reserved names
    base = s.split('.')[0].upper()
    if base in FileSystem.RESERVED_NAMES:
        return False, f"'{base}' is a reserved Windows name"
    
    # Check length
    if len(s) > FileSystem.MAX_PATH_LENGTH:
        return False, f'Exceeds maximum length ({FileSystem.MAX_PATH_LENGTH} characters)'
    
    return True, ''


def validate_folder_name_by_filesystem(
    folder_name: str, 
    filesystem_type: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate folder name based on target filesystem type.
    
    This is the centralized validation function that respects user preferences
    for filesystem type (Linux/Unraid vs Windows). Use this instead of local
    validation implementations.
    
    Args:
        folder_name: Folder name to validate
        filesystem_type: 'linux' or 'windows'. If None, reads from preferences.
    
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message or None)
        
    Examples:
        >>> validate_folder_name_by_filesystem("Title: Name", "linux")
        (True, None)
        >>> validate_folder_name_by_filesystem("Title: Name", "windows")
        (False, "Invalid characters")
    """
    try:
        if not folder_name or not isinstance(folder_name, str):
            return True, None  # Skip validation on empty
        
        s = str(folder_name)
        if not s.strip():
            return True, None
        
        # Get filesystem type from preference if not provided
        if filesystem_type is None:
            from .config import config
            filesystem_type = config.get_pref('filesystem_type', 'linux')
        
        filesystem_type = filesystem_type.lower()
        
        if filesystem_type == 'windows':
            # Windows-specific validation
            # Check for trailing space or dot
            if s.endswith(' ') or s.endswith('.'):
                return False, 'Ends with space or dot'
            
            # Check for invalid characters
            found_invalid = [c for c in s if c in FileSystem.INVALID_CHARS]
            if found_invalid:
                return False, 'Invalid characters'
            
            # Check for reserved names
            base = s.split('.')[0].upper()
            if base in FileSystem.RESERVED_NAMES:
                return False, 'Reserved name'
        else:
            # Linux/Unraid validation
            # Only forward slash is invalid on Linux
            if '/' in s:
                return False, 'Contains forward slash'
        
        # Check length (applies to both)
        if len(s) > FileSystem.MAX_PATH_LENGTH:
            return False, 'Name too long'
        
        return True, None
    except Exception:
        return True, None  # Fail gracefully on unexpected errors


def get_server_display_name(server_key: Optional[str]) -> str:
    """Return human-friendly display name for supported server keys."""
    mapping = {
        'qbittorrent': 'qBittorrent',
        'deluge': 'Deluge',
        'transmission': 'Transmission',
        'sonarr': 'Sonarr',
        'autobrr': 'Autobrr',
    }
    key = str(server_key or 'qbittorrent').strip().lower()
    return mapping.get(key, key.title() if key else 'qBittorrent')


def get_validation_profile_label(
    filesystem_type: Optional[str] = None,
    main_server: Optional[str] = None,
) -> str:
    """
    Build a label describing the active validation profile.

    The profile includes both filesystem mode and selected main server so
    validation output can state what model/profile the checks apply to.
    """
    fs = str(filesystem_type or '').strip().lower()
    if not fs:
        try:
            from .config import config
            fs = str(config.get_pref('filesystem_type', 'linux')).strip().lower()
        except Exception:
            fs = 'linux'

    fs_label = 'Windows strict' if fs == 'windows' else 'Linux/Unix'

    server = str(main_server or '').strip().lower()
    if not server:
        try:
            from .config import config
            server = str(getattr(config, 'MAIN_SERVER', 'qbittorrent')).strip().lower()
        except Exception:
            server = 'qbittorrent'

    return f"{fs_label} for {get_server_display_name(server)}"

