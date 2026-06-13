"""
Utility Functions — Shared Helpers for the Entire Application.

This module is the "toolbox" — it provides reusable helper functions that are
used throughout the codebase. Nothing in here has side effects or state; these
are all pure-ish functions that transform data.

Main categories:
  1. **Title Entry Helpers** — Safe access to the hybrid title entry format
     used in config.ALL_TITLES (where entries mix qBittorrent fields with
     internal tracking fields like 'node' and 'ruleName').
  2. **Path Composition** — Building effective download paths from the three
     layers: default_download_path + category_save_path + rule_save_path.
  3. **Validation** — Checking title entries for structural correctness and
     metadata pollution before export.
  4. **Filesystem Sanitization** — Making arbitrary strings safe to use as
     folder names on Windows or Linux.
  5. **Misc** — Anime season detection, server display names, app restart.
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
#
# Why these exist: Instead of scattered `.get('node', {}).get('title')` calls
# all over the codebase, these functions centralize the extraction logic and
# handle all the edge cases (missing fields, string entries, None values).
# ============================================================================

# Fields that exist only for internal GUI tracking and must never be sent
# to qBittorrent or included in exported JSON files.
INTERNAL_FIELDS = frozenset(['node', 'ruleName'])


def get_display_title(entry: Any, fallback: str = '') -> str:
    """
    Get the human-readable display title from a title entry.

    This is what the user sees in the GUI treeview. It tries multiple
    fields in priority order because entries come from different sources
    (manual creation, qBittorrent import, SubsPlease, etc.) and may
    have different fields populated.

    Priority order:
      1. entry['node']['title'] — primary display title (set by the GUI)
      2. entry['title'] — direct title field
      3. entry['mustContain'] — the RSS match pattern (last resort)
      4. str(entry) — for simple string entries
      5. fallback — caller-provided default

    Args:
        entry: A title entry (dict or plain string).
        fallback: Value to return if no title can be found.

    Returns:
        The display title string.
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

    The rule name is the key used when syncing rules to qBittorrent —
    it's the name that appears in qBittorrent's RSS Downloader.

    Priority order:
      1. entry['ruleName'] — explicitly set rule name
      2. entry['name'] — alternative name field
      3. entry['node']['title'] — display title as fallback
      4. entry['mustContain'] — match pattern as last resort
      5. fallback — caller-provided default

    Args:
        entry: A title entry (dict or plain string).
        fallback: Value to return if no name can be found.

    Returns:
        The rule name string.
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
    Get the RSS match pattern (mustContain) from a title entry.

    This is the text pattern that qBittorrent searches for in RSS feed
    item titles to decide whether to auto-download them.

    Args:
        entry: A title entry (dict or plain string).
        fallback: Value to return if no pattern is found.

    Returns:
        The mustContain pattern string.
    """
    if not entry:
        return fallback

    if isinstance(entry, dict):
        must = entry.get('mustContain')
        if must:
            return str(must)
        # Fall back to display title (the title IS the match pattern in simple cases)
        return get_display_title(entry, fallback)

    return str(entry) if entry else fallback


def strip_internal_fields(entry: Any) -> Any:
    """
    Remove internal tracking fields from a single title entry.

    Creates a clean copy without 'node' and 'ruleName' fields, suitable
    for export to JSON or syncing to qBittorrent. Non-dict entries are
    returned unchanged.

    Args:
        entry: A title entry (dict or any type).

    Returns:
        A clean copy without internal fields (dicts are shallow-copied).
    """
    if not isinstance(entry, dict):
        return entry

    return {k: v for k, v in entry.items() if k not in INTERNAL_FIELDS}


def strip_internal_fields_from_titles(titles: Dict[str, List[Any]]) -> Dict[str, List[Any]]:
    """
    Remove internal tracking fields from ALL entries in a titles structure.

    This is the bulk version of strip_internal_fields() — it processes the
    entire ALL_TITLES dictionary and returns a clean copy suitable for export.

    Args:
        titles: The full titles dictionary (media_type → list of entries).

    Returns:
        A new dictionary with all internal fields removed from every entry.
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
    Create a properly structured title entry from scratch.

    This is the factory function for creating new entries with both the
    internal tracking fields (node, ruleName) and qBittorrent fields
    (mustContain, savePath, etc.) properly set up.

    Args:
        display_title: Title shown in the GUI treeview.
        must_contain: RSS match pattern (defaults to display_title).
        rule_name: Rule key for qBittorrent (defaults to display_title).
        save_path: Relative download directory.
        category: qBittorrent torrent category.
        feed_url: RSS feed URL to watch.
        enabled: Whether the rule is active.
        **extra_fields: Any additional qBittorrent fields to include.

    Returns:
        A properly structured title entry dictionary.
    """
    entry = {
        # Internal tracking fields (removed before export)
        'node': {'title': display_title},
        'ruleName': rule_name or display_title,
        # qBittorrent rule fields (sent to server)
        'mustContain': must_contain or display_title,
        'enabled': enabled,
    }

    # Only include optional fields if they have values
    if save_path:
        entry['savePath'] = save_path
    if category:
        entry['assignedCategory'] = category
    if feed_url:
        entry['affectedFeeds'] = [feed_url]

    # Merge in any extra qBittorrent fields the caller wants to set
    entry.update(extra_fields)

    return entry


# ============================================================================
# PATH HELPERS
# ============================================================================
# Functions for extracting, normalizing, and composing download paths.
#
# qBittorrent composes the final download location from three layers:
#   default_download_path + category_save_path + rule_save_path
#
# These functions replicate that logic so the GUI can show the user
# where their files will actually end up.
# ============================================================================

def get_category_save_path(category_info: Any) -> str:
    """
    Extract the save path from a qBittorrent category info object.

    Handles multiple formats because qBittorrent uses 'save_path' internally
    but some parts of this app used 'savePath' historically.

    Args:
        category_info: Category data — can be a dict (from API) or a plain
                       string path.

    Returns:
        The normalized save path with forward slashes, or empty string.
    """
    if isinstance(category_info, str):
        return category_info.replace('\\', '/').strip()

    if not isinstance(category_info, dict):
        return ''

    # Try multiple key names for backward compatibility
    path = (
        category_info.get('save_path')
        or category_info.get('savePath')
        or category_info.get('path')
        or ''
    )
    # Normalize: backslashes to forward slashes, collapse double slashes
    normalized = str(path).replace('\\', '/').strip()
    while '//' in normalized:
        normalized = normalized.replace('//', '/')
    return normalized


# Regex to detect Windows absolute paths like "C:/" or "D:/"
_RE_ABS_PATH_WIN = re.compile(r'^[A-Za-z]:/')


def is_absolute_path(path: str) -> bool:
    """
    Check whether a path is absolute (Unix or Windows style).

    Handles:
      - Unix absolute: /home/user/downloads
      - UNC paths: //server/share
      - Windows drive: C:/Users/Downloads

    Args:
        path: The path string to check.

    Returns:
        True if the path is absolute.
    """
    if not path or not isinstance(path, str):
        return False

    p = path.strip().replace('\\', '/')
    if not p:
        return False

    # Unix absolute or UNC-style path
    if p.startswith('/') or p.startswith('//'):
        return True

    # Windows drive letter path (e.g., C:/Downloads)
    return bool(_RE_ABS_PATH_WIN.match(p))


def compose_effective_download_path(
    default_download_path: str,
    category_save_path: str,
    rule_save_path: str
) -> str:
    """
    Compose the final download destination path from three layers.

    This replicates qBittorrent's path resolution logic so the GUI can
    preview where files will be saved. The resolution rules are:

      1. If rule_save_path is absolute → use it directly (ignores everything else)
      2. If category_save_path is absolute → use it as base, append rule_save_path
      3. Otherwise → join all three: default + category + rule

    Examples:
      compose_effective_download_path("/dl", "anime", "Spring 2026/Show")
      → "/dl/anime/Spring 2026/Show"

      compose_effective_download_path("/dl", "anime", "D:/Anime/Show")
      → "D:/Anime/Show"  (absolute rule path wins)

    Args:
        default_download_path: qBittorrent's global default download directory.
        category_save_path: Category-level subdirectory.
        rule_save_path: Rule-level subdirectory.

    Returns:
        The composed path with forward slashes, or empty string if all inputs are empty.
    """
    def _normalize(value: Any) -> str:
        """Normalize a path segment: strip whitespace, backslashes → forward slashes."""
        path = str(value or '').strip().replace('\\', '/')
        while '//' in path:
            path = path.replace('//', '/')
        return path

    def _strip_slashes(value: str) -> str:
        """Remove leading and trailing slashes from a relative path segment."""
        return value.strip('/').strip()

    default_path = _normalize(default_download_path)
    category_path = _normalize(category_save_path)
    rule_path = _normalize(rule_save_path)

    # Rule 1: Absolute rule path wins over everything
    if is_absolute_path(rule_path):
        return rule_path

    parts: List[str] = []

    # Rule 2: Absolute category path replaces the default path
    if category_path and is_absolute_path(category_path):
        base = category_path.rstrip('/')
        if rule_path:
            return f"{base}/{_strip_slashes(rule_path)}"
        return base

    # Rule 3: Join all relative parts
    if default_path:
        parts.append(default_path.rstrip('/'))
    if category_path:
        parts.append(_strip_slashes(category_path))
    if rule_path:
        parts.append(_strip_slashes(rule_path))

    if not parts:
        return ''

    return '/'.join(p for p in parts if p)


# ============================================================================
# TITLE SEARCH HELPERS
# ============================================================================

def find_entry_by_title(
    titles: Dict[str, List[Any]],
    search_title: str,
    case_sensitive: bool = False
) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    """
    Search for a title entry by its display title across all media types.

    Args:
        titles: The full titles dictionary (media_type → list of entries).
        search_title: The title string to search for.
        case_sensitive: Whether to match case exactly.

    Returns:
        A tuple of (media_type, index_in_list, entry_dict) if found,
        or None if not found.
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

    Used before adding new entries to prevent duplicates.

    Args:
        titles: The full titles dictionary.
        check_title: Title to check for.
        case_sensitive: Whether to match case exactly.

    Returns:
        True if the title already exists in any media type group.
    """
    return find_entry_by_title(titles, check_title, case_sensitive) is not None


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================
# These functions validate title entries to prevent metadata pollution
# and ensure data integrity before exporting rules.
#
# "Metadata pollution" = unexpected fields sneaking into the title entries
# from external data sources (like AniList responses) that shouldn't be
# sent to qBittorrent.
# ============================================================================

# The complete set of fields that qBittorrent's RSS rule API accepts.
# Any field NOT in this set is either an internal tracking field or
# metadata pollution from external sources.
VALID_QBT_FIELDS = frozenset([
    'addPaused', 'affectedFeeds', 'assignedCategory', 'enabled',
    'episodeFilter', 'ignoreDays', 'lastMatch', 'mustContain',
    'mustNotContain', 'previouslyMatchedEpisodes', 'priority',
    'savePath', 'smartFilter', 'torrentContentLayout', 'torrentParams',
    'useRegex'
])

# Valid sub-fields inside the 'torrentParams' nested object.
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
      - No unexpected fields that could indicate metadata pollution
      - Correct types for internal tracking fields (node=dict, ruleName=str)
      - Valid torrentParams sub-fields

    Non-dict entries (plain strings) are always considered valid.

    Args:
        entry: The title entry to validate.

    Returns:
        A tuple of (is_valid, list_of_warning_messages).
        is_valid is True only if there are zero warnings.
    """
    warnings = []

    if not isinstance(entry, dict):
        return True, []  # Non-dict entries (strings) are allowed

    # Check for fields that shouldn't be there
    all_valid_fields = VALID_QBT_FIELDS | INTERNAL_FIELDS
    for key in entry.keys():
        if key not in all_valid_fields:
            warnings.append(f"Unexpected field '{key}' found (may be metadata pollution)")

    # Validate torrentParams sub-fields
    torrent_params = entry.get('torrentParams')
    if isinstance(torrent_params, dict):
        for key in torrent_params.keys():
            if key not in VALID_TORRENT_PARAMS_FIELDS:
                warnings.append(f"Unexpected torrentParams field '{key}'")

    # Validate internal field types
    node = entry.get('node')
    if node is not None and not isinstance(node, dict):
        warnings.append("'node' field should be a dictionary")

    rule_name = entry.get('ruleName')
    if rule_name is not None and not isinstance(rule_name, str):
        warnings.append("'ruleName' field should be a string")

    return len(warnings) == 0, warnings


def validate_entries_for_export(titles: Dict[str, List[Any]]) -> Tuple[bool, List[str]]:
    """
    Validate ALL entries in a titles structure before export.

    Runs validate_entry_structure() on every entry and collects all
    warnings. This is a pre-flight check before exporting or syncing
    to catch any data integrity issues.

    Args:
        titles: The full titles dictionary (media_type → list of entries).

    Returns:
        A tuple of (all_valid, list_of_all_warnings).
        all_valid is True only if zero warnings were found.
    """
    all_warnings = []

    for media_type, items in titles.items():
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                # Internal fields being present is expected — they'll be stripped on export
                for field in INTERNAL_FIELDS:
                    if field in item:
                        pass

                # Check for structural problems
                _, warnings = validate_entry_structure(item)
                for warning in warnings:
                    all_warnings.append(f"{media_type}[{idx}]: {warning}")

    return len(all_warnings) == 0, all_warnings


def sanitize_entry_for_export(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggressively sanitize an entry for export — keep ONLY known qBittorrent fields.

    This is stricter than strip_internal_fields(): while that function only
    removes 'node' and 'ruleName', this function also removes any unknown
    fields that may have leaked in from external data sources.

    Also recursively sanitizes the torrentParams sub-object.

    Args:
        entry: The title entry to sanitize.

    Returns:
        A clean copy containing only valid qBittorrent fields.
    """
    if not isinstance(entry, dict):
        return entry

    clean = {}
    for key, value in entry.items():
        if key in VALID_QBT_FIELDS:
            # Also sanitize the nested torrentParams object
            if key == 'torrentParams' and isinstance(value, dict):
                clean[key] = {k: v for k, v in value.items() if k in VALID_TORRENT_PARAMS_FIELDS}
            else:
                clean[key] = value

    return clean


# ============================================================================
# ANIME SEASON DETECTION
# ============================================================================

def get_current_anime_season() -> Tuple[str, str]:
    """
    Determine the current anime season and year based on today's date.

    Anime seasons follow the broadcast calendar:
      - Winter: January – March
      - Spring: April – June
      - Summer: July – September
      - Fall: October – December

    Returns:
        A tuple of (season_name, year_string), e.g. ("Spring", "2026").
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

    return "Fall", year  # Fallback (shouldn't happen — all months are covered)


# ============================================================================
# FILESYSTEM SANITIZATION
# ============================================================================
# These functions clean up arbitrary strings so they can be safely used as
# folder names on the target filesystem (Windows or Linux).
#
# This matters because anime titles often contain characters that are
# illegal in Windows filenames: colons (Re:Zero), question marks (Is It
# Wrong?), etc.
# ============================================================================

def sanitize_folder_name(name: str, replacement_char: str = '_', max_length: int = 255) -> str:
    """
    Make a string safe to use as a folder name by replacing invalid characters.

    The behavior is controlled by user preferences:
      - sanitize_replace_all: If True, replace ALL invalid chars with one
        character. If False, use per-character custom mapping.
      - sanitize_global_char: The single replacement character when replace_all=True.
      - sanitize_custom_map: Per-character replacement map when replace_all=False.
        Supports special tokens: '__remove__' (delete char), '__space__' (replace with space).
      - filesystem_type: 'windows' (strict) or 'linux' (only '/' is invalid).

    Examples:
      sanitize_folder_name("Re:Zero")       → "Re_Zero"     (windows, replace_all=True)
      sanitize_folder_name("Is It Wrong?")  → "Is It Wrong" (windows, custom_map={'?': '__remove__'})
      sanitize_folder_name("My/Show")       → "My_Show"     (linux)

    Args:
        name: The original string to sanitize.
        replacement_char: Fallback replacement character (default: '_').
        max_length: Maximum allowed length for the result.

    Returns:
        A sanitized string safe for filesystem use.
    """
    if not name:
        return replacement_char

    try:
        # Lazy import to avoid circular dependency during module import
        from src.config import config  # type: ignore

        replace_all_specials = bool(config.get_pref(PrefKeys.SANITIZE_REPLACE_ALL, True))
        global_char_pref = config.get_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, replacement_char)
        custom_map_pref = config.get_pref(PrefKeys.SANITIZE_CUSTOM_MAP, {}) or {}
        filesystem_type_pref = str(config.get_pref('filesystem_type', 'linux') or 'linux').strip().lower()
        if not isinstance(custom_map_pref, dict):
            custom_map_pref = {}
    except Exception:
        # Fallback defaults if config isn't available (e.g. during testing)
        replace_all_specials = True
        global_char_pref = replacement_char
        custom_map_pref = {}
        filesystem_type_pref = 'linux'

    # Determine which characters are invalid based on filesystem type
    if filesystem_type_pref == 'windows':
        invalid_chars = FileSystem.INVALID_CHARS  # <>:"/\|?*
    else:
        # Linux/Unix: basically everything is valid except the path separator
        invalid_chars = '/'

    # Normalize the global replacement character
    global_char = str(global_char_pref) if global_char_pref is not None else replacement_char
    if not global_char:
        global_char = replacement_char
    if len(global_char) > 1:
        # Only use the first character to keep filenames predictable
        global_char = global_char[0]

    # --- Replace invalid characters ---
    sanitized = name
    if replace_all_specials:
        # Simple mode: replace every invalid char with the same character
        for char in invalid_chars:
            sanitized = sanitized.replace(char, global_char)
    else:
        # Custom mode: look up each invalid char in the user's replacement map
        for char in invalid_chars:
            has_override = char in custom_map_pref
            replacement = custom_map_pref.get(char) if has_override else replacement_char
            replacement_text = '' if replacement is None else str(replacement)
            token = replacement_text.strip().lower()

            # Handle special action tokens
            if token in ('__remove__', 'remove'):
                replacement_value = ''               # Delete the character entirely
            elif token in ('__space__', 'space'):
                replacement_value = ' '              # Replace with a space
            elif replacement_text == '':
                # Empty string: use it as-is if explicitly set, else use default
                replacement_value = '' if has_override else replacement_char
            else:
                replacement_value = replacement_text  # Use the custom replacement

            sanitized = sanitized.replace(char, replacement_value)

    # --- Platform-specific post-processing ---
    if filesystem_type_pref == 'windows':
        # Windows doesn't allow trailing spaces or dots in folder names
        sanitized = sanitized.strip().strip('.')

        # Windows reserves certain device names (CON, PRN, NUL, etc.)
        base_name = sanitized.split('.')[0].upper()
        if base_name in FileSystem.RESERVED_NAMES:
            sanitized = f"{replacement_char}{sanitized}"
    else:
        sanitized = sanitized.strip()

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    # Never return an empty string
    if not sanitized:
        sanitized = replacement_char

    return sanitized


def validate_folder_name(name: str) -> Tuple[bool, str]:
    """
    Check if a string is a valid Windows folder name.

    This is the strict Windows validator — always checks against Windows rules
    regardless of user preferences. For filesystem-aware validation that
    respects the user's filesystem_type preference, use
    validate_folder_name_by_filesystem() instead.

    Checks:
      - Not empty
      - No invalid Windows characters (<>:"/\\|?*)
      - Doesn't end with space or period
      - Not a Windows reserved name (CON, PRN, NUL, etc.)
      - Within 255-character limit

    Args:
        name: The folder name to validate.

    Returns:
        A tuple of (is_valid, error_message). Error message is empty if valid.
    """
    if not name or not isinstance(name, str) or not name.strip():
        return False, 'Folder name cannot be empty'

    s = name.strip()

    # Check for invalid characters
    found_invalid = [c for c in s if c in FileSystem.INVALID_CHARS]
    if found_invalid:
        return False, f"Contains invalid characters: {', '.join(found_invalid)}"

    # Check for trailing space or dot (Windows disallows these)
    if s.endswith(' ') or s.endswith('.'):
        return False, 'Cannot end with space or period'

    # Check for Windows reserved device names
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
    Validate a folder name based on the target filesystem type.

    This is the preference-aware validator — it checks against different
    rules depending on whether the user's qBittorrent server runs on
    Windows or Linux.

    Linux rules: Only forward slash '/' is invalid.
    Windows rules: Full set of invalid chars, reserved names, trailing dots.

    Args:
        folder_name: The folder name to validate.
        filesystem_type: 'linux' or 'windows'. If None, reads from preferences.

    Returns:
        A tuple of (is_valid, error_message_or_None).

    Examples:
        >>> validate_folder_name_by_filesystem("Title: Name", "linux")
        (True, None)       # Colons are fine on Linux
        >>> validate_folder_name_by_filesystem("Title: Name", "windows")
        (False, "Invalid characters")  # Colons are invalid on Windows
    """
    try:
        if not folder_name or not isinstance(folder_name, str):
            return True, None  # Skip validation on empty input

        s = str(folder_name)
        if not s.strip():
            return True, None

        # Get filesystem type from user preference if not explicitly provided
        if filesystem_type is None:
            from .config import config
            filesystem_type = config.get_pref('filesystem_type', 'linux')

        filesystem_type = filesystem_type.lower()

        if filesystem_type == 'windows':
            # Windows-specific checks
            if s.endswith(' ') or s.endswith('.'):
                return False, 'Ends with space or dot'

            found_invalid = [c for c in s if c in FileSystem.INVALID_CHARS]
            if found_invalid:
                return False, 'Invalid characters'

            base = s.split('.')[0].upper()
            if base in FileSystem.RESERVED_NAMES:
                return False, 'Reserved name'
        else:
            # Linux/Unraid: only '/' is truly invalid in a folder name
            if '/' in s:
                return False, 'Contains forward slash'

        # Length limit applies to both platforms
        if len(s) > FileSystem.MAX_PATH_LENGTH:
            return False, 'Name too long'

        return True, None
    except Exception:
        return True, None  # Fail open — don't block the user on validation errors


# ============================================================================
# DISPLAY HELPERS
# ============================================================================

def get_server_display_name(server_key: Optional[str]) -> str:
    """
    Convert a server identifier key to a human-friendly display name.

    Example: 'qbittorrent' → 'qBittorrent'
    """
    mapping = {
        'qbittorrent': 'qBittorrent',
    }
    key = str(server_key or 'qbittorrent').strip().lower()
    return mapping.get(key, key.title() if key else 'qBittorrent')


def get_validation_profile_label(
    filesystem_type: Optional[str] = None,
    main_server: Optional[str] = None,
) -> str:
    """
    Build a human-readable label describing the active validation profile.

    Used in the GUI to show users which validation rules are being applied.
    Example: "Linux/Unix for qBittorrent" or "Windows strict for qBittorrent"

    Args:
        filesystem_type: 'linux' or 'windows'. Reads from preferences if None.
        main_server: Server key. Reads from config if None.

    Returns:
        A descriptive label string.
    """
    # Determine filesystem type
    fs = str(filesystem_type or '').strip().lower()
    if not fs:
        try:
            from .config import config
            fs = str(config.get_pref('filesystem_type', 'linux')).strip().lower()
        except Exception:
            fs = 'linux'

    fs_label = 'Windows strict' if fs == 'windows' else 'Linux/Unix'

    # Determine server name
    server = str(main_server or '').strip().lower()
    if not server:
        try:
            from .config import config
            server = str(getattr(config, 'MAIN_SERVER', 'qbittorrent')).strip().lower()
        except Exception:
            server = 'qbittorrent'

    return f"{fs_label} for {get_server_display_name(server)}"


# ============================================================================
# APPLICATION LIFECYCLE
# ============================================================================

import sys
import os
import subprocess


def restart_application() -> None:
    """
    Restart the entire application process.

    Used after applying settings changes that require a fresh start
    (like theme changes). Handles both frozen (PyInstaller) and
    development (python script) execution modes.
    """
    if getattr(sys, 'frozen', False):
        # Running as a compiled executable (PyInstaller) — re-launch the .exe
        subprocess.Popen([sys.executable] + sys.argv[1:])
    else:
        # Running as a Python script — re-launch with the same interpreter
        subprocess.Popen([sys.executable] + sys.argv)
    os._exit(0)  # Hard exit (skips cleanup) to avoid conflicting with the new process
