"""
SubsPlease & AniList Integration Module.

This module connects to two external anime data sources:

1. **SubsPlease** (subsplease.org)
   - Fetches the current anime release schedule (which shows air on which days)
   - Provides a list of currently-airing anime titles
   - Used to auto-populate the rule editor with available shows

2. **AniList** (anilist.co — GraphQL API)
   - Looks up alternative names for anime titles (Romaji, English, Japanese, synonyms)
   - These "title variations" help match rules across different naming conventions
     (e.g. "Shingeki no Kyojin" vs "Attack on Titan" vs "進撃の巨人")
   - Results are cached locally to avoid hammering the API

RATE LIMITING:
  Both APIs have user-configurable cooldown periods to prevent abuse.
  The cooldown is enforced via timestamps stored in the app's preferences.

CACHING:
  Title variations from AniList are cached in the app's cache.json file with
  configurable retention policies (age-based TTL, size cap, or rotation/archiving).
"""

# Standard library imports
import json
import os
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

# Local application imports
from src.config import config
from src.constants import CacheKeys, PrefKeys

logger = logging.getLogger(__name__)

# requests is optional — if not installed, API calls will gracefully return empty results
try:
    import requests
except ImportError:
    requests = None


# ============================================================================
# Constants and configuration keys
# ============================================================================

# AniList GraphQL endpoint URL
ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"

# Default limits for AniList title variation cache behavior
TITLE_VARIATION_TTL_DAYS = 30                       # How many days before a cached entry is considered "stale"
TITLE_VARIATION_MAX_UPDATES = 12                    # Max number of titles to refresh per pull (prevents API flooding)
TITLE_VARIATION_DEFAULT_MAX_SIZE_MB = 10             # Default max cache size in megabytes

# Preference keys for AniList cooldown and cache settings
ANILIST_PULL_COOLDOWN_PREF = PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES
ANILIST_LAST_PULL_PREF = 'anilist_last_pull_timestamp'
DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES = 15

# Preference keys for AniList cache retention policy
ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE
ANILIST_TITLE_VARIATION_CACHE_TTL_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS
DEFAULT_ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS = 30
ANILIST_TITLE_VARIATION_CACHE_MAX_MB_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB

# Preference keys for SubsPlease cooldown
SUBSPLEASE_PULL_COOLDOWN_PREF = PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES
SUBSPLEASE_LAST_PULL_PREF = 'subsplease_last_pull_timestamp'
DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES = 15


# ============================================================================
# Title normalization regex patterns
#
# These are used to make title matching resilient to different season numbering
# formats. For example, "My Hero Academia S7", "My Hero Academia Season 7",
# and "My Hero Academia 7th Season" should all match each other.
# ============================================================================

# Matches short season format like "S3", "s12" → extracts the number
_RE_S_NUM = re.compile(r'\bs(\d+)\b')

# Matches long season format like "Season 3", "season 12" → extracts the number
_RE_SEASON_NUM = re.compile(r'\bseason\s+(\d+)\b')

# Matches ordinal season format like "3rd Season", "2nd" → extracts the number
_RE_ORDINAL = re.compile(r'\b(\d+)(?:st|nd|rd|th)(?:\s+season)?\b', re.IGNORECASE)

# Matches seasonal prefix like "Spring 2026 - " that SubsPlease adds to titles
_RE_SEASON_PREFIX = re.compile(r'^\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*', re.IGNORECASE)

# Translation table for fast punctuation removal/replacement during title normalization.
# Hyphens and colons become spaces (to merge "One-Punch" → "One Punch"),
# while other punctuation is simply stripped out.
_PUNCT_TRANS = str.maketrans({
    '-': ' ', ':': ' ', '!': None, '?': None, '"': ' ', "'": ' ',
    ',': ' ', '.': ' ', ';': ' ', '(': ' ', ')': ' ',
    '[': ' ', ']': ' ', '{': ' ', '}': ' ',
})


def _normalize_title(title: str) -> str:
    """
    Normalize a title string for fuzzy matching.

    This strips punctuation, lowercases everything, and converts all season
    numbering formats ("S3", "Season 3", "3rd Season") into just the bare number.
    This way, "One-Punch Man S3" and "One Punch Man Season 3" both become
    "one punch man 3" and will match each other.

    Args:
        title: The original title string.

    Returns:
        A cleaned, lowercased, normalized version of the title.
    """
    normalized = str(title or '').lower().translate(_PUNCT_TRANS)
    # Convert all season formats to just the number
    normalized = _RE_S_NUM.sub(r'\1', normalized)         # "s3" → "3"
    normalized = _RE_SEASON_NUM.sub(r'\1', normalized)    # "season 3" → "3"
    normalized = _RE_ORDINAL.sub(r'\1', normalized)       # "3rd season" → "3"
    # Collapse multiple spaces into one
    normalized = ' '.join(normalized.split())
    return normalized


# ============================================================================
# AniList Title Variation Cache — Load / Save / Retention
#
# The cache stores alternative title names for anime so the app can match
# rules even when different sources use different names for the same show.
# For example, AniList tells us that "Shingeki no Kyojin" is also known as
# "Attack on Titan" and "進撃の巨人", so a rule for any of these will match.
# ============================================================================

def load_title_variations_cache() -> Dict[str, Dict[str, Any]]:
    """
    Load the AniList title variations cache from disk.

    Returns:
        A dictionary mapping anime titles to their cached variation data.
        Each entry has 'aliases' (list of name variants) and 'last_updated' (timestamp).
        Returns an empty dict if the cache doesn't exist or can't be loaded.
    """
    try:
        data = config._load_cache_data()
        cached = data.get(CacheKeys.ANIME_TITLE_VARIATIONS, {}) or {}
        if isinstance(cached, dict):
            return cached
    except Exception as e:
        logger.error(f"Failed to load anime title variations cache: {e}")
    return {}


def save_title_variations_cache(
    variations: Dict[str, Dict[str, Any]],
    archive_current: bool = False,
) -> bool:
    """
    Save the AniList title variations cache to disk.

    Before saving, the configured retention policy is applied (age-based pruning,
    size-based pruning, or rotation archiving) to keep the cache from growing
    indefinitely.

    Args:
        variations: The full cache dictionary to save.
        archive_current: If True and retention mode is 'rotate', save a timestamped
                         snapshot of the current cache before overwriting it.

    Returns:
        True if the save was successful, False otherwise.
    """
    try:
        # If using 'rotate' retention mode, archive the old cache before replacing it
        if archive_current and get_anilist_title_variation_cache_retention_mode() == 'rotate':
            try:
                _archive_title_variations_cache_snapshot(load_title_variations_cache())
            except Exception:
                pass

        # Apply the configured retention policy (prune old/large entries)
        prepared = apply_title_variation_cache_retention(dict(variations or {}), archive_current=False)
        from src import cache as cache_module
        return bool(cache_module._update_cache_key(CacheKeys.ANIME_TITLE_VARIATIONS, prepared))
    except Exception as e:
        logger.error(f"Failed to save anime title variations cache: {e}")
        return False


def _is_variation_stale(last_updated: str, ttl_days: int = TITLE_VARIATION_TTL_DAYS) -> bool:
    """
    Check if a cached title variation entry is too old and needs refreshing.

    Args:
        last_updated: ISO-format timestamp string of when the entry was last updated.
        ttl_days: Maximum age in days before the entry is considered stale.
                  A value of 0 or negative means entries never expire.

    Returns:
        True if the entry is stale (or has no valid timestamp), False if still fresh.
    """
    try:
        if int(ttl_days) <= 0:
            return False  # TTL disabled — entries never expire
        if not last_updated:
            return True   # No timestamp means we don't know how old it is — treat as stale
        dt = datetime.fromisoformat(last_updated)
        age_days = (datetime.now() - dt).days
        return age_days >= int(ttl_days)
    except Exception:
        return True  # If anything goes wrong parsing, assume stale


def get_anilist_title_variation_cache_retention_mode() -> str:
    """
    Get the user's configured cache retention strategy.

    There are three modes:
      - 'age'    — Delete entries older than a configurable TTL (default)
      - 'size'   — Delete oldest entries when the cache exceeds a size limit
      - 'rotate' — Keep everything but save dated snapshots before overwriting

    Returns:
        One of: 'age', 'size', 'rotate'
    """
    try:
        value = str(config.get_pref(
            ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE_PREF,
            'age',
        ) or 'age').strip().lower()
    except Exception:
        value = 'age'
    if value not in {'age', 'size', 'rotate'}:
        value = 'age'
    return value


def get_anilist_title_variation_cache_max_size_mb() -> int:
    """
    Get the max allowed size for the AniList title variation cache (in MB).

    Only relevant when retention mode is 'size'. Clamped between 1 MB and 1024 MB.

    Returns:
        The max cache size in megabytes.
    """
    try:
        value = int(config.get_pref(
            ANILIST_TITLE_VARIATION_CACHE_MAX_MB_PREF,
            TITLE_VARIATION_DEFAULT_MAX_SIZE_MB,
        ))
    except (TypeError, ValueError, AttributeError):
        value = TITLE_VARIATION_DEFAULT_MAX_SIZE_MB
    return max(1, min(1024, value))


def _variation_cache_size_bytes(cache: Dict[str, Dict[str, Any]]) -> int:
    """
    Estimate how many bytes the cache would take when serialized to JSON.

    This is used by the size-based retention policy to decide if pruning is needed.

    Returns:
        Approximate size in bytes, or 0 if estimation fails.
    """
    try:
        return len(json.dumps(cache or {}, ensure_ascii=False).encode('utf-8'))
    except Exception:
        return 0


def _archive_title_variations_cache_snapshot(cache: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Save a dated backup of the current AniList cache to a JSON file.

    Used by the 'rotate' retention mode to preserve historical data before
    the cache is overwritten with fresh data.

    The archive file is saved in the same directory as cache.json with a
    timestamped filename like: anime_title_variations-20260612-153000.json

    Returns:
        The file path of the created archive, or None on failure.
    """
    try:
        cache_path = os.path.abspath(getattr(config, 'CACHE_FILE', 'cache.json'))
        archive_dir = os.path.dirname(cache_path) or os.getcwd()
        archive_name = f"anime_title_variations-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        archive_path = os.path.join(archive_dir, archive_name)
        payload = {
            'archive_created': datetime.now().isoformat(),
            CacheKeys.ANIME_TITLE_VARIATIONS: cache or {},
        }
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return archive_path
    except Exception as e:
        logger.error(f"Failed to archive AniList title variation cache: {e}")
        return None


def _get_active_library_titles() -> set[str]:
    """
    Collect all title strings that are currently "in use" by the user's rules.

    This scans the user's library (ALL_TITLES) and gathers:
      - Display titles (from the 'node' → 'title' field)
      - Original qBittorrent rule names
      - Pattern strings from 'mustContain' fields

    The returned set is used to protect active entries from being pruned
    during cache cleanup — we never want to delete a cache entry that's
    still being used by a live download rule.

    Returns:
        A set of lowercased title strings that are currently referenced.
    """
    active = set()
    try:
        all_titles = getattr(config, 'ALL_TITLES', {}) or {}
        if isinstance(all_titles, dict):
            for media_type, items in all_titles.items():
                if isinstance(items, list):
                    for entry in items:
                        if not isinstance(entry, dict):
                            continue
                        # The display title shown in the rule editor
                        node = entry.get('node')
                        if isinstance(node, dict):
                            t = str(node.get('title', '')).strip()
                            if t:
                                active.add(t.lower())
                        # The original rule name from qBittorrent
                        rn = str(entry.get('ruleName', '')).strip()
                        if rn:
                            active.add(rn.lower())
                        # The regex/text pattern used for RSS matching
                        mc = str(entry.get('mustContain', '')).strip()
                        if mc:
                            active.add(mc.lower())
    except Exception as e:
        logger.warning(f"Error collecting active library titles: {e}")
    return active


def _is_cache_entry_used(key: str, value: Any, active_titles: set[str]) -> bool:
    """
    Check if a cache entry is currently referenced by any active download rule.

    An entry is considered "used" if either its key or any of its alias texts
    appear in the active titles set. Used entries are protected from pruning.

    Args:
        key: The cache entry key (usually the primary anime title).
        value: The cache entry value dict (contains 'aliases' list).
        active_titles: Set of lowercased title strings from active rules.

    Returns:
        True if this entry is referenced by at least one active rule.
    """
    if not active_titles:
        return False
    # Check if the entry key itself matches
    if key.lower() in active_titles:
        return True
    # Check if any of the entry's aliases match
    if isinstance(value, dict):
        aliases = value.get("aliases") or []
        for alias in aliases:
            txt = ""
            if isinstance(alias, str):
                txt = alias.strip().lower()
            elif isinstance(alias, dict):
                txt = str(alias.get('text', '')).strip().lower()
            if txt and txt in active_titles:
                return True
    return False


# ============================================================================
# Cache Pruning Strategies
#
# These functions implement the different retention policies for keeping
# the AniList title variation cache from growing without bounds.
# ============================================================================

def _prune_title_variations_by_age(cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Remove cache entries that are older than the configured TTL.

    IMPORTANT: Entries that are actively used by current download rules are
    never pruned, regardless of age. This prevents breaking live rules.

    Returns:
        A new dict with stale, unused entries removed.
    """
    ttl_days = get_anilist_title_variation_cache_ttl_days()
    if ttl_days <= 0:
        # TTL is disabled — keep everything
        return dict(cache or {})

    active_titles = _get_active_library_titles()
    pruned: Dict[str, Dict[str, Any]] = {}

    for key, value in (cache or {}).items():
        if not isinstance(value, dict):
            continue
        # Never prune entries that are still being used by active rules
        if _is_cache_entry_used(key, value, active_titles):
            pruned[key] = value
            continue
        # Skip stale entries (they won't be copied to the pruned dict)
        if _is_variation_stale(str(value.get('last_updated', '')), ttl_days=ttl_days):
            continue
        pruned[key] = value

    return pruned


def _prune_title_variations_by_size(cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Remove the oldest cache entries until the cache fits within the size limit.

    Entries are removed in this priority order:
      1. Unused entries (oldest first) — these are safe to remove
      2. Used entries (oldest first) — only if still over the limit after step 1

    This ensures that actively-used entries are the last to be evicted.

    Returns:
        A new dict that fits within the configured size limit.
    """
    max_bytes = get_anilist_title_variation_cache_max_size_mb() * 1024 * 1024
    working = dict(cache or {})

    # If we're already under the limit, no pruning needed
    if _variation_cache_size_bytes(working) <= max_bytes:
        return working

    active_titles = _get_active_library_titles()

    def _entry_age(value: Any) -> datetime:
        """Extract the last_updated timestamp from a cache entry, or return epoch if missing."""
        try:
            if isinstance(value, dict):
                raw = str(value.get('last_updated', '') or '').strip()
                if raw:
                    return datetime.fromisoformat(raw)
        except Exception:
            pass
        return datetime.min

    # Sort entries so unused+oldest come first (will be pruned first),
    # and used+newest come last (will be preserved longest)
    ordered_keys = sorted(
        working.keys(),
        key=lambda k: (1 if _is_cache_entry_used(k, working.get(k), active_titles) else 0, _entry_age(working.get(k)))
    )

    # Remove entries one by one until we're under the size limit
    for key in ordered_keys:
        if len(working) <= 1:
            break  # Always keep at least one entry
        if _variation_cache_size_bytes(working) <= max_bytes:
            break  # We're under the limit now
        working.pop(key, None)

    return working


def apply_title_variation_cache_retention(
    cache: Dict[str, Dict[str, Any]],
    archive_current: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Apply whichever retention policy the user has configured.

    This is the main entry point for cache cleanup. It reads the user's
    preferred retention mode and delegates to the appropriate strategy:
      - 'rotate' → archive the current cache, then keep everything
      - 'size'   → prune oldest entries until under the size cap
      - 'age'    → prune entries older than the TTL (default)

    Args:
        cache: The full cache dictionary to process.
        archive_current: If True, trigger archiving (only used in 'rotate' mode).

    Returns:
        The cleaned cache dictionary.
    """
    mode = get_anilist_title_variation_cache_retention_mode()
    working = dict(cache or {})

    if mode == 'rotate':
        # In rotate mode, save a snapshot but keep all entries in the active cache
        if archive_current and working:
            _archive_title_variations_cache_snapshot(working)
        return working

    if mode == 'size':
        return _prune_title_variations_by_size(working)

    # Default: age-based pruning
    return _prune_title_variations_by_age(working)


# ============================================================================
# AniList GraphQL API — Title Variation Fetching
#
# These functions query AniList's GraphQL API to find all the different names
# an anime is known by (Romaji, English, Japanese, and user-submitted synonyms).
# ============================================================================

# Regex to detect season/part suffixes at the end of a title.
# Matches things like: "S3", "Season 2", "3rd Season", "Part 2", "Cour 1", "III"
_RE_SEASON_SUFFIX = re.compile(
    r'\s+((?:s\d+|season\s+\d+|\d+(?:st|nd|rd|th)\s+season|part\s+(?:\d+|ii|iii|iv|v|vi)|cour\s+\d+|\d+|ii|iii|iv|v|vi))\s*$',
    re.IGNORECASE
)


def _execute_anilist_search(search_term: str) -> List[Dict[str, str]]:
    """
    Run a single AniList GraphQL search and return all title aliases found.

    Queries AniList for an anime matching the search term, then extracts:
      - Romaji title (Japanese in Latin characters, e.g. "Shingeki no Kyojin")
      - English title (e.g. "Attack on Titan")
      - Native title (original script, e.g. "進撃の巨人")
      - Synonyms (any other known names submitted by users)

    Args:
        search_term: The title to search for on AniList.

    Returns:
        A list of alias dicts, each with 'text' (the name) and 'lang' (the type).
        Returns an empty list if the search fails or finds nothing.
    """
    from src.constants import NetworkConfig

    # GraphQL query to search for an anime by name and get all its titles
    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        title {
          romaji
          english
          native
        }
        synonyms
      }
    }
    """
    payload = {'query': query, 'variables': {'search': search_term}}
    headers = {
        'User-Agent': NetworkConfig.USER_AGENT,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            ANILIST_GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=NetworkConfig.DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json() or {}
        media = (data.get('data') or {}).get('Media') or {}

        # Collect all title variants into a flat list
        aliases: List[Dict[str, str]] = []
        title_obj = media.get('title') or {}
        for key in ('romaji', 'english', 'native'):
            value = title_obj.get(key)
            if value and isinstance(value, str):
                aliases.append({'text': value.strip(), 'lang': key})

        # Add user-submitted synonyms (these don't have a specific language)
        synonyms = media.get('synonyms') or []
        if isinstance(synonyms, list):
            for item in synonyms:
                if isinstance(item, str) and item.strip():
                    aliases.append({'text': item.strip(), 'lang': 'synonym'})

        # Deduplicate: remove entries with the same text (case-insensitive)
        seen = set()
        unique = []
        for alias in aliases:
            text = str(alias.get('text', '')).strip()
            lang = str(alias.get('lang', 'synonym')).strip().lower() or 'synonym'
            key = text.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append({'text': text, 'lang': lang})
        return unique
    except Exception as e:
        logger.debug(f"AniList query failed for '{search_term}': {e}")
        return []


def _fetch_anilist_title_aliases(title: str) -> List[Dict[str, str]]:
    """
    Look up all known names for an anime on AniList, with smart fallback matching.

    If the exact title doesn't return results (common with sequels like
    "My Hero Academia S7"), this function tries a fallback strategy:
      1. Strip the season/part suffix from the title
      2. Search for the base title instead
      3. Append the original suffix to all results

    This way, "My Hero Academia S7" can still find aliases even if AniList
    only knows it as "Boku no Hero Academia 7th Season".

    Args:
        title: The anime title to look up.

    Returns:
        A list of alias dicts with 'text' and 'lang' keys.
    """
    if not requests:
        return []

    # Remove seasonal prefixes like "Spring 2026 - " that SubsPlease adds
    title = re.sub(r'^\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*', '', title, flags=re.IGNORECASE).strip()

    # Check if the title has a season/part suffix (e.g. "S3", "2nd Season", "Part II")
    match = _RE_SEASON_SUFFIX.search(title)
    base_title = ""
    suffix = ""
    if match:
        suffix_matched = match.group(1)
        suffix = " " + suffix_matched.strip()
        base_title = title[:-len(suffix_matched)].strip()

    # First attempt: search with the full title as-is
    aliases = _execute_anilist_search(title)

    # Fallback: if the full title didn't match, try the base title without suffix
    # then append the suffix to all results
    if not aliases and base_title and len(base_title) >= 3:
        logger.info(f"AniList search for '{title}' returned no results. Trying base title: '{base_title}' with suffix: '{suffix}'")
        base_aliases = _execute_anilist_search(base_title)
        if base_aliases:
            seen = set()
            for alias in base_aliases:
                text = alias.get('text', '')
                lang = alias.get('lang', 'synonym')
                if text:
                    # Reconstruct: "Attack on Titan" + " S7" = "Attack on Titan S7"
                    reconstructed = f"{text}{suffix}"
                    key = reconstructed.lower()
                    if key not in seen:
                        seen.add(key)
                        aliases.append({'text': reconstructed, 'lang': lang})

    return aliases


def _build_alias_records_from_media(media: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract and deduplicate all title aliases from a single AniList media object.

    This is used when processing bulk season data (where we get full media objects
    with title + synonyms fields) rather than individual search results.

    Args:
        media: A single AniList media object dict containing 'title' and 'synonyms'.

    Returns:
        A deduplicated list of alias records with 'text' and 'lang' keys.
    """
    aliases: List[Dict[str, str]] = []
    if not isinstance(media, dict):
        return aliases

    # Extract official titles (romaji, english, native, userPreferred)
    title_obj = media.get('title') or {}
    if isinstance(title_obj, dict):
        for key in ('userPreferred', 'romaji', 'english', 'native'):
            value = title_obj.get(key)
            if value and isinstance(value, str):
                # Map 'userPreferred' to 'romaji' since it's not a distinct language
                aliases.append({'text': value.strip(), 'lang': key if key != 'userPreferred' else 'romaji'})

    # Extract user-submitted synonyms
    synonyms = media.get('synonyms') or []
    if isinstance(synonyms, list):
        for item in synonyms:
            if isinstance(item, str) and item.strip():
                aliases.append({'text': item.strip(), 'lang': 'synonym'})

    return _dedupe_alias_records(aliases)


def _build_media_lookup_keys(media: Dict[str, Any]) -> List[str]:
    """
    Generate all the different title strings that should map to the same cache entry.

    When we cache AniList data, we want to store it under every known title variant
    so that a lookup by any variant name will find the cached data.

    For example, for "Attack on Titan", we'd cache the same data under:
      - "Shingeki no Kyojin" (romaji)
      - "Attack on Titan" (english)
      - "進撃の巨人" (native)

    Args:
        media: A single AniList media object dict.

    Returns:
        A list of unique title strings to use as cache keys.
    """
    keys: List[str] = []
    if not isinstance(media, dict):
        return keys

    title_obj = media.get('title') or {}
    if not isinstance(title_obj, dict):
        return keys

    for key in ('userPreferred', 'romaji', 'english', 'native'):
        value = title_obj.get(key)
        if value and isinstance(value, str):
            cleaned = value.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)

    return keys


def _parse_anilist_season_year(season: str, year: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Validate and normalize season/year inputs for AniList GraphQL queries.

    AniList expects season as an uppercase string (WINTER, SPRING, SUMMER, FALL)
    and year as an integer.

    Args:
        season: Season name string (case-insensitive).
        year: Year string or number.

    Returns:
        A tuple of (season_str, year_int), or (None, None) if inputs are invalid.
    """
    season_value = str(season or '').strip().upper()
    if season_value not in {'WINTER', 'SPRING', 'SUMMER', 'FALL'}:
        return None, None

    try:
        year_value = int(str(year or '').strip())
    except Exception:
        return None, None

    # Sanity check: AniList doesn't have data outside reasonable year ranges
    if year_value < 1900 or year_value > 3000:
        return None, None

    return season_value, year_value


def _fetch_anilist_season_media(season: str, year: str) -> List[Dict[str, Any]]:
    """
    Fetch all anime entries from AniList for a specific season and year.

    For example, "SPRING 2026" would return all anime that aired in Spring 2026.
    This is used for bulk cache refreshing — when the user wants to pre-cache
    aliases for an entire season's worth of shows at once.

    Uses pagination to fetch all results (AniList returns max 50 per page).
    Safety limit of 20 pages (1000 anime) prevents infinite loops.

    Args:
        season: Season name (e.g. "SPRING", "SUMMER").
        year: Year string (e.g. "2026").

    Returns:
        A list of AniList media objects, each containing 'title' and 'synonyms'.
    """
    if not requests:
        return []

    season_value, year_value = _parse_anilist_season_year(season, year)
    if not season_value or not year_value:
        return []

    from src.constants import NetworkConfig

    # GraphQL query with pagination to get all anime for a season
    query = """
    query ($season: MediaSeason, $seasonYear: Int, $page: Int) {
      Page(page: $page, perPage: 50) {
        pageInfo {
          hasNextPage
        }
        media(season: $season, seasonYear: $seasonYear, type: ANIME) {
          title {
            userPreferred
            romaji
            english
            native
          }
          synonyms
        }
      }
    }
    """
    headers = {
        'User-Agent': NetworkConfig.USER_AGENT,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    results: List[Dict[str, Any]] = []
    page = 1

    # Fetch pages until there are no more, with a safety cap of 20 pages
    for _ in range(20):
        payload = {
            'query': query,
            'variables': {'season': season_value, 'seasonYear': year_value, 'page': page},
        }
        try:
            response = requests.post(
                ANILIST_GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=NetworkConfig.DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json() or {}
            page_data = (data.get('data') or {}).get('Page') or {}
            media_items = page_data.get('media') or []
            if isinstance(media_items, list):
                for item in media_items:
                    if isinstance(item, dict):
                        results.append(item)

            # Check if there are more pages to fetch
            has_next = bool((page_data.get('pageInfo') or {}).get('hasNextPage'))
            if not has_next:
                break
            page += 1
        except Exception as e:
            logger.debug(f"AniList season lookup failed for '{season_value} {year_value}' page {page}: {e}")
            break

    return results


# ============================================================================
# AniList Cache Refresh — Triggered by user or scheduled
# ============================================================================

def refresh_title_variations_cache_for_season(season: str, year: str) -> int:
    """
    Bulk-refresh the AniList alias cache for all anime in a given season/year.

    Fetches the full list of anime for the season from AniList, extracts all
    their title variations, and stores them in the cache. This is much more
    efficient than looking up titles one at a time.

    Args:
        season: Season name (e.g. "SPRING").
        year: Year string (e.g. "2026").

    Returns:
        The number of cache entries that were created or updated.
    """
    if not requests:
        return 0

    media_items = _fetch_anilist_season_media(season, year)
    if not media_items:
        return 0

    cache = load_title_variations_cache()
    updated_keys: set[str] = set()
    timestamp = datetime.now().isoformat()

    for media in media_items:
        aliases = _build_alias_records_from_media(media)
        if not aliases:
            continue

        # Store the same alias data under every known title for this anime
        for key in _build_media_lookup_keys(media):
            cache[key] = {
                'aliases': aliases,
                'last_updated': timestamp,
            }
            updated_keys.add(key)

    if updated_keys:
        save_title_variations_cache(cache, archive_current=True)

    return len(updated_keys)


def refresh_title_variations_cache(
    subsplease_titles: List[str],
    force_refresh: bool = False,
    max_updates: int = TITLE_VARIATION_MAX_UPDATES,
) -> int:
    """
    Refresh cached AniList aliases for a list of SubsPlease titles.

    Goes through the title list and updates any entries that are missing or stale.
    Stops after max_updates to avoid flooding the AniList API.

    Args:
        subsplease_titles: List of anime titles to look up.
        force_refresh: If True, refresh all entries regardless of staleness.
        max_updates: Maximum number of titles to update in this run.

    Returns:
        The number of titles that were actually updated.
    """
    if not requests or not subsplease_titles:
        return 0

    cache = load_title_variations_cache()
    updated = 0

    for title in subsplease_titles:
        # Stop if we've hit the update limit (prevents API rate limiting)
        if updated >= max_updates:
            break

        # Check if this title already has a fresh cache entry
        cached_entry = cache.get(title, {}) if isinstance(cache.get(title), dict) else {}
        if not force_refresh:
            ttl_days = get_anilist_title_variation_cache_ttl_days()
            if cached_entry and not _is_variation_stale(str(cached_entry.get('last_updated', '')), ttl_days=ttl_days):
                continue  # Entry is still fresh — skip it

        # Fetch new aliases from AniList and update the cache
        aliases = _dedupe_alias_records(_fetch_anilist_title_aliases(title))
        cache[title] = {
            'aliases': aliases,
            'last_updated': datetime.now().isoformat(),
        }
        updated += 1

    if updated > 0:
        save_title_variations_cache(cache, archive_current=True)
    return updated


# ============================================================================
# Alias text extraction and deduplication helpers
# ============================================================================

def _extract_alias_texts(alias_values: Any) -> List[str]:
    """
    Extract plain text strings from a list of alias records.

    Handles both legacy format (plain strings) and new format (dicts with 'text' key).
    This is needed because the cache format evolved over time.

    Args:
        alias_values: A list of alias records (strings or dicts).

    Returns:
        A flat list of alias text strings.
    """
    texts: List[str] = []
    if not isinstance(alias_values, list):
        return texts

    for alias in alias_values:
        if isinstance(alias, str):
            txt = alias.strip()
            if txt:
                texts.append(txt)
        elif isinstance(alias, dict):
            txt = str(alias.get('text', '')).strip()
            if txt:
                texts.append(txt)
    return texts


def _dedupe_alias_records(alias_records: Any) -> List[Dict[str, str]]:
    """
    Normalize and deduplicate a list of alias records.

    Handles both legacy strings and new dict format. Deduplicates by the
    combination of (lowercased text, language) — so "Attack on Titan" (english)
    and "Attack on Titan" (synonym) would both be kept since they have
    different language tags.

    Args:
        alias_records: A list of alias records (strings or dicts).

    Returns:
        A deduplicated list of alias dicts, each with 'text' and 'lang' keys.
    """
    unique: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    if not isinstance(alias_records, list):
        return unique

    for alias in alias_records:
        if isinstance(alias, str):
            text = alias.strip()
            lang = 'synonym'
        elif isinstance(alias, dict):
            text = str(alias.get('text', '')).strip()
            lang = str(alias.get('lang', 'synonym')).strip().lower() or 'synonym'
        else:
            continue

        if not text:
            continue

        key = (text.lower(), lang)
        if key in seen:
            continue
        seen.add(key)
        unique.append({'text': text, 'lang': lang})

    return unique


# ============================================================================
# Cooldown management — rate limiting for API pulls
#
# Both AniList and SubsPlease have configurable cooldown periods to prevent
# the user (or automated processes) from hitting the APIs too frequently.
# The cooldown is tracked via timestamps stored in the app's preferences.
# ============================================================================

def get_anilist_pull_cooldown_minutes() -> int:
    """
    Get how many minutes must pass between manual AniList cache pulls.

    Clamped between 1 minute (minimum) and 1440 minutes (24 hours, maximum).

    Returns:
        The cooldown period in minutes.
    """
    try:
        value = int(config.get_pref(ANILIST_PULL_COOLDOWN_PREF, DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES))
    except (TypeError, ValueError, AttributeError):
        value = DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES
    return max(1, min(1440, value))


def get_anilist_title_variation_cache_ttl_days() -> int:
    """
    Get how many days a cached AniList entry stays valid before needing a refresh.

    A value of 0 means entries never expire (infinite TTL).
    Clamped between 0 and 3650 days (~10 years).

    Returns:
        The TTL in days.
    """
    try:
        value = int(config.get_pref(
            ANILIST_TITLE_VARIATION_CACHE_TTL_PREF,
            DEFAULT_ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS,
        ))
    except (TypeError, ValueError, AttributeError):
        value = DEFAULT_ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS
    return max(0, min(3650, value))


def _get_anilist_last_pull_dt() -> Optional[datetime]:
    """
    Read the timestamp of the last manual AniList pull from preferences.

    Returns:
        A datetime object, or None if no pull has ever been recorded.
    """
    try:
        raw = str(config.get_pref(ANILIST_LAST_PULL_PREF, '') or '').strip()
    except Exception:
        raw = ''
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def get_anilist_pull_remaining_seconds() -> int:
    """
    Calculate how many seconds remain before the next AniList pull is allowed.

    Returns:
        Seconds remaining (0 if the cooldown has passed and a pull is allowed).
    """
    last_pull = _get_anilist_last_pull_dt()
    if not last_pull:
        return 0  # No previous pull recorded — pulling is allowed immediately

    cooldown_seconds = get_anilist_pull_cooldown_minutes() * 60
    elapsed_seconds = max(0, int((datetime.now() - last_pull).total_seconds()))
    remaining = cooldown_seconds - elapsed_seconds
    return max(0, remaining)


def can_pull_anilist_cache() -> Tuple[bool, int]:
    """
    Check if a manual AniList cache pull is currently allowed.

    Returns:
        A tuple of (is_allowed: bool, seconds_remaining: int).
        If is_allowed is True, seconds_remaining will be 0.
    """
    remaining = get_anilist_pull_remaining_seconds()
    return remaining == 0, remaining


def get_subsplease_pull_cooldown_minutes() -> int:
    """
    Get how many minutes must pass between manual SubsPlease schedule pulls.

    Clamped between 1 minute and 1440 minutes (24 hours).

    Returns:
        The cooldown period in minutes.
    """
    try:
        value = int(config.get_pref(SUBSPLEASE_PULL_COOLDOWN_PREF, DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES))
    except (TypeError, ValueError, AttributeError):
        value = DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES
    return max(1, min(1440, value))


def _get_subsplease_last_pull_dt() -> Optional[datetime]:
    """
    Read the timestamp of the last manual SubsPlease pull from preferences.

    Returns:
        A datetime object, or None if no pull has ever been recorded.
    """
    try:
        raw = str(config.get_pref(SUBSPLEASE_LAST_PULL_PREF, '') or '').strip()
    except Exception:
        raw = ''
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def get_subsplease_pull_remaining_seconds() -> int:
    """
    Calculate how many seconds remain before the next SubsPlease pull is allowed.

    Returns:
        Seconds remaining (0 if the cooldown has passed and a pull is allowed).
    """
    last_pull = _get_subsplease_last_pull_dt()
    if not last_pull:
        return 0

    cooldown_seconds = get_subsplease_pull_cooldown_minutes() * 60
    elapsed_seconds = max(0, int((datetime.now() - last_pull).total_seconds()))
    remaining = cooldown_seconds - elapsed_seconds
    return max(0, remaining)


def can_pull_subsplease_cache() -> Tuple[bool, int]:
    """
    Check if a manual SubsPlease schedule pull is currently allowed.

    Returns:
        A tuple of (is_allowed: bool, seconds_remaining: int).
    """
    remaining = get_subsplease_pull_remaining_seconds()
    return remaining == 0, remaining


# ============================================================================
# High-level refresh functions — called by the GUI
# ============================================================================

def refresh_anilist_cache_with_limit(
    subsplease_titles: List[str],
    max_updates: int = TITLE_VARIATION_MAX_UPDATES,
    season: str = '',
    year: str = '',
    refresh_scope: str = '',
) -> Tuple[bool, int, str]:
    """
    Manually refresh the AniList alias cache, with cooldown enforcement.

    This is the function called when the user clicks "Refresh AniList Cache"
    in the GUI. It:
      1. Checks if enough time has passed since the last pull (cooldown)
      2. Refreshes aliases for the given SubsPlease titles
      3. Optionally also refreshes the entire season's worth of titles
      4. Records the pull timestamp so the cooldown restarts

    Args:
        subsplease_titles: List of anime titles to refresh aliases for.
        max_updates: Maximum number of individual title lookups per refresh.
        season: Optional season name for bulk season refresh (e.g. "SPRING").
        year: Optional year for bulk season refresh (e.g. "2026").
        refresh_scope: If "title_and_season", also does a bulk season refresh.

    Returns:
        A tuple of (success: bool, count: int, message: str).
    """
    if not requests:
        return False, 0, 'requests library not available'

    # Validate that we have titles to work with
    titles = [str(t).strip() for t in (subsplease_titles or []) if str(t).strip()]
    if not titles:
        return False, 0, 'No SubsPlease cached titles found. Fetch SubsPlease titles first.'

    # Enforce cooldown — prevent spamming the AniList API
    allowed, remaining = can_pull_anilist_cache()
    if not allowed:
        mins = remaining // 60
        secs = remaining % 60
        return False, 0, f'Please wait {mins}m {secs}s before the next AniList pull.'

    # Refresh individual titles
    scope = str(refresh_scope or '').strip().lower()
    updated = refresh_title_variations_cache(titles, force_refresh=True, max_updates=max_updates)

    # If requested, also refresh all titles from the specified anime season
    if scope == 'title_and_season':
        season_updated = refresh_title_variations_cache_for_season(season, year)
        updated += season_updated

    # Record the pull timestamp for cooldown tracking
    try:
        config.set_pref(ANILIST_LAST_PULL_PREF, datetime.now().isoformat())
    except Exception:
        pass

    # Build a human-readable result message
    if updated > 0:
        if scope == 'title_and_season':
            season_label = f' for {str(season).strip().title()} {str(year).strip()}' if str(season).strip() and str(year).strip() else ''
            return True, updated, f'Refreshed AniList aliases for {updated} title(s){season_label}.'
        return True, updated, f'Refreshed AniList aliases for {updated} title(s).'

    return True, 0, 'AniList cache checked; no stale entries needed updates.'


# ============================================================================
# SubsPlease Schedule — Fetching and Caching
# ============================================================================

def load_subsplease_cache() -> Dict[str, Dict[str, Any]]:
    """
    Load the cached SubsPlease schedule data from disk.

    The cache maps anime titles to their metadata:
        {
            "Anime Title": {
                "subsplease": "SubsPlease Title",
                "last_updated": "2024-01-15T10:30:00",
                "exact_match": True
            }
        }

    Returns:
        The cached schedule dictionary, or empty dict if not available.
    """
    try:
        data = config._load_cache_data()
        cached = data.get(CacheKeys.SUBSPLEASE_TITLES, {}) or {}
        logger.info(f"Loaded {len(cached)} cached SubsPlease titles")
        return cached
    except Exception as e:
        logger.error(f"Failed to load SubsPlease cache: {e}")
        return {}


def save_subsplease_cache(titles_dict: Dict[str, Dict[str, Any]]) -> bool:
    """
    Save SubsPlease schedule data to the cache file (if enabled) or memory.

    Args:
        titles_dict: Dictionary mapping title strings to their metadata.

    Returns:
        True if the save was successful.
    """
    try:
        from src.config import config
        if not config.get_pref('save_subsplease_cache', False):
            # Only store in memory, do not persist to disk
            from src.constants import CacheKeys
            data = config._cache_data_in_memory if config._cache_data_in_memory is not None else {}
            data[CacheKeys.SUBSPLEASE_TITLES] = titles_dict
            config._cache_data_in_memory = data
            logger.info(f"Saved {len(titles_dict)} SubsPlease titles to memory (disk cache disabled)")
            return True

        from src import cache as cache_module
        from src.constants import CacheKeys
        success = cache_module._update_cache_key(CacheKeys.SUBSPLEASE_TITLES, titles_dict)
        if success:
            logger.info(f"Saved {len(titles_dict)} SubsPlease titles to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save SubsPlease cache: {e}")
        return False


def fetch_subsplease_schedule(force_refresh: bool = False) -> Tuple[bool, Union[List[str], str]]:
    """
    Fetch the current anime season's schedule from SubsPlease.

    This is one of the main entry points called by the GUI. It:
      1. Checks for cached data first (unless force_refresh is True)
      2. If cache miss, fetches from SubsPlease's JSON API
      3. Parses the schedule to extract all show titles
      4. Caches the results for future use
      5. Triggers a best-effort AniList alias enrichment in the background

    The SubsPlease API returns a schedule organized by day of the week,
    with each day containing a list of shows. We flatten this into a
    simple sorted list of unique title strings.

    IMPORTANT: Uses SubsPlease's public API responsibly:
      - Rate limiting is handled through configurable cooldowns
      - Proper User-Agent headers identify the application
      - Results are cached to minimize API calls

    Args:
        force_refresh: If True, bypass the cache and fetch fresh data from the API.
                       Still subject to cooldown enforcement.

    Returns:
        A tuple of (success: bool, result).
        On success: (True, ["Title A", "Title B", ...])
        On failure: (False, "error message string")
    """
    if not requests:
        return False, "requests library not available"

    # Enforce cooldown when force-refreshing
    if force_refresh:
        allowed, remaining = can_pull_subsplease_cache()
        if not allowed:
            mins = remaining // 60
            secs = remaining % 60
            return False, f"Please wait {mins}m {secs}s before the next SubsPlease pull."

    # --- Try serving from cache first ---
    if not force_refresh:
        cached = load_subsplease_cache()
        if cached:
            titles = list(cached.keys())
            # Best-effort: update any stale AniList aliases while we're at it
            try:
                refresh_title_variations_cache(titles, force_refresh=False)
            except Exception:
                pass
            logger.info(f"Using cached SubsPlease titles: {len(titles)} entries")
            return True, titles

    # --- Cache miss or force refresh: fetch from the API ---
    try:
        from src.constants import NetworkConfig
        url = NetworkConfig.SUBSPLEASE_API_URL
        logger.info(f"Fetching SubsPlease schedule from API: {url}")

        headers = {
            'User-Agent': NetworkConfig.USER_AGENT,
            'Accept': 'application/json'
        }

        response = requests.get(url, timeout=NetworkConfig.DEFAULT_TIMEOUT, headers=headers)
        response.raise_for_status()

        # Parse the JSON response
        data = response.json()

        if not isinstance(data, dict) or 'schedule' not in data:
            return False, "Invalid API response format"

        # Extract unique titles from all days of the week
        titles = []
        schedule = data['schedule']

        for day, shows in schedule.items():
            if isinstance(shows, list):
                for show in shows:
                    if isinstance(show, dict):
                        title = show.get('title', '').strip()
                        if title and title not in titles:
                            titles.append(title)

        if not titles:
            return False, "No titles found in API response"

        # Merge the new results into the existing cache
        timestamp = datetime.now().isoformat()
        cache_dict = load_subsplease_cache() or {}
        
        for title in titles:
            cache_dict[title] = {
                "subsplease": title,
                "last_updated": timestamp,
                "exact_match": True
            }

        # Apply the same retention logic used by AniList to clean up old SubsPlease entries
        cache_dict = apply_title_variation_cache_retention(cache_dict, archive_current=False)

        save_subsplease_cache(cache_dict)

        # Record the pull timestamp for cooldown tracking (only on manual refresh)
        if force_refresh:
            try:
                config.set_pref(SUBSPLEASE_LAST_PULL_PREF, datetime.now().isoformat())
            except Exception:
                pass

        # Best-effort: enrich titles with AniList aliases for cross-site matching
        try:
            refresh_title_variations_cache(list(cache_dict.keys()), force_refresh=force_refresh)
        except Exception:
            pass

        logger.info(f"Successfully fetched {len(titles)} titles from SubsPlease API")
        return True, sorted(titles)

    except requests.exceptions.RequestException as e:
        error_msg = f"Network error fetching SubsPlease schedule: {e}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Error parsing SubsPlease schedule: {e}"
        logger.error(error_msg)
        return False, error_msg


# ============================================================================
# Title Matching — Finding SubsPlease titles that match MAL/user titles
# ============================================================================

def find_subsplease_title_match(mal_title: str) -> Optional[str]:
    """
    Find the SubsPlease title that best matches a given anime title.

    This is used when importing anime from MyAnimeList (MAL) to find the
    corresponding SubsPlease release name. Anime titles can vary wildly
    between sites, so this uses a multi-pass matching strategy:

    Pass 1: Exact match (case-sensitive, after cleaning)
    Pass 2: Case-insensitive match
    Pass 3: Normalized match (ignoring punctuation and season format differences)
    Pass 4: Substring containment (e.g. "Oshi no Ko" matches "Oshi no Ko Season 2")
    Pass 5: Word overlap scoring (for multi-word titles with >60% word overlap)

    At each pass, AniList aliases are also checked — so searching for
    "Attack on Titan" can match SubsPlease's "Shingeki no Kyojin" via
    the cached alias data.

    Args:
        mal_title: The anime title from MyAnimeList to look up.

    Returns:
        The matching SubsPlease title string, or None if no good match is found.
    """
    cached = load_subsplease_cache()
    variations = load_title_variations_cache()

    # Clean up the input: remove seasonal prefixes like "Spring 2026 - "
    cleaned_mal = _RE_SEASON_PREFIX.sub('', mal_title).strip()
    if not cleaned_mal:
        return None

    # --- Pass 1: Exact match (case-sensitive) ---
    if cleaned_mal in cached:
        match_data = cached[cleaned_mal]
        if isinstance(match_data, dict):
            return match_data.get('subsplease', cleaned_mal)
        return str(match_data)

    # --- Pass 2: Case-insensitive match ---
    mal_lower = cleaned_mal.lower()
    for cached_title, data in cached.items():
        cleaned_cached = _RE_SEASON_PREFIX.sub('', cached_title).strip()
        if cleaned_cached.lower() == mal_lower:
            if isinstance(data, dict):
                return data.get('subsplease', cached_title)
            return cached_title

    # --- Pre-build lookup table for fuzzy matching passes ---
    # For each cached title, collect all its variants (including AniList aliases),
    # normalize them, and compute word sets for word-overlap matching.
    mal_normalized = _normalize_title(cleaned_mal)

    lookup_entries: list[tuple[str, list[str], list[set[str]]]] = []
    for cached_title, data in cached.items():
        subsplease_title = data.get('subsplease', cached_title) if isinstance(data, dict) else cached_title

        # Clean seasonal prefixes from both the cached title and SubsPlease title
        clean_cached = _RE_SEASON_PREFIX.sub('', cached_title).strip()
        clean_sp = _RE_SEASON_PREFIX.sub('', subsplease_title).strip()

        # Pull in AniList aliases for this title (if cached)
        alias_entry = variations.get(cached_title, {})
        alias_list = alias_entry.get('aliases', []) if isinstance(alias_entry, dict) else []
        alias_texts = _extract_alias_texts(alias_list)
        clean_aliases = [_RE_SEASON_PREFIX.sub('', a).strip() for a in alias_texts]

        # Combine all variants and pre-compute normalized forms + word sets
        candidates = [clean_cached, clean_sp] + clean_aliases
        normalized_candidates = [_normalize_title(c) for c in candidates]
        candidate_word_sets = [set(nc.split()) for nc in normalized_candidates]

        lookup_entries.append((subsplease_title, normalized_candidates, candidate_word_sets))

    # --- Pass 3: Exact normalized match ---
    # After normalization, "One-Punch Man S3" == "one punch man 3"
    for subsplease_title, normalized_candidates, _ in lookup_entries:
        for nc in normalized_candidates:
            if mal_normalized == nc:
                return subsplease_title

    # --- Pass 4: Substring containment match ---
    # Check if one title contains the other (handles sequel suffixes)
    best_match = None
    best_score = 0
    for subsplease_title, normalized_candidates, _ in lookup_entries:
        for nc in normalized_candidates:
            if not nc or not mal_normalized:
                continue
            if mal_normalized in nc or nc in mal_normalized:
                # Score by the length of the shorter string (longer overlap = better match)
                score = min(len(mal_normalized), len(nc))
                if score > best_score:
                    best_score = score
                    best_match = subsplease_title

    # --- Pass 5: Word overlap matching ---
    # For multi-word titles, check what percentage of words match
    if not best_match:
        mal_words = set(mal_normalized.split())
        if len(mal_words) >= 2:  # Only for titles with 2+ words (single words are too ambiguous)
            for subsplease_title, _, candidate_word_sets in lookup_entries:
                for cached_words in candidate_word_sets:
                    common_words = mal_words & cached_words
                    if len(common_words) >= 2:
                        # Score: what fraction of words overlap?
                        score = len(common_words) / max(len(mal_words), len(cached_words))
                        # Require >60% word overlap to be considered a match
                        if score > 0.6 and score * 100 > best_score:
                            best_score = score * 100
                            best_match = subsplease_title

    return best_match
