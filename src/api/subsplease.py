"""
SubsPlease API integration for fetching anime schedule and titles.

IMPORTANT: This uses SubsPlease's public API responsibly with caching.
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

try:
    import requests
except ImportError:
    requests = None


ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
TITLE_VARIATION_TTL_DAYS = 30
TITLE_VARIATION_MAX_UPDATES = 12
TITLE_VARIATION_DEFAULT_MAX_SIZE_MB = 10
ANILIST_PULL_COOLDOWN_PREF = PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES
ANILIST_LAST_PULL_PREF = 'anilist_last_pull_timestamp'
DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES = 15
ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE
ANILIST_TITLE_VARIATION_CACHE_TTL_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS
DEFAULT_ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS = 30
ANILIST_TITLE_VARIATION_CACHE_MAX_MB_PREF = PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB
SUBSPLEASE_PULL_COOLDOWN_PREF = PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES
SUBSPLEASE_LAST_PULL_PREF = 'subsplease_last_pull_timestamp'
DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES = 15


def _normalize_title(title: str) -> str:
    """Normalize titles for resilient matching across punctuation/season formats."""
    normalized = str(title or '').lower()
    normalized = normalized.replace('-', ' ').replace(':', ' ').replace('!', '').replace('?', '')
    normalized = normalized.replace('"', ' ').replace("'", ' ')
    normalized = re.sub(r'\bs(\d+)\b', r'\1', normalized)
    normalized = re.sub(r'\bseason\s+(\d+)\b', r'\1', normalized)
    normalized = ' '.join(normalized.split())
    return normalized


def load_title_variations_cache() -> Dict[str, Dict[str, Any]]:
    """Load cached title variation aliases from cache file."""
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
    """Persist cached title variation aliases."""
    try:
        if archive_current and get_anilist_title_variation_cache_retention_mode() == 'rotate':
            try:
                _archive_title_variations_cache_snapshot(load_title_variations_cache())
            except Exception:
                pass

        prepared = apply_title_variation_cache_retention(dict(variations or {}), archive_current=False)
        from src import cache as cache_module
        return bool(cache_module._update_cache_key(CacheKeys.ANIME_TITLE_VARIATIONS, prepared))
    except Exception as e:
        logger.error(f"Failed to save anime title variations cache: {e}")
        return False


def _is_variation_stale(last_updated: str, ttl_days: int = TITLE_VARIATION_TTL_DAYS) -> bool:
    try:
        if int(ttl_days) <= 0:
            return False
        if not last_updated:
            return True
        dt = datetime.fromisoformat(last_updated)
        age_days = (datetime.now() - dt).days
        return age_days >= int(ttl_days)
    except Exception:
        return True


def get_anilist_title_variation_cache_retention_mode() -> str:
    """Return the configured AniList title variation retention mode."""
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
    """Return the configured maximum AniList title variation cache size in MB."""
    try:
        value = int(config.get_pref(
            ANILIST_TITLE_VARIATION_CACHE_MAX_MB_PREF,
            TITLE_VARIATION_DEFAULT_MAX_SIZE_MB,
        ))
    except (TypeError, ValueError, AttributeError):
        value = TITLE_VARIATION_DEFAULT_MAX_SIZE_MB
    return max(1, min(1024, value))


def _variation_cache_size_bytes(cache: Dict[str, Dict[str, Any]]) -> int:
    """Estimate serialized size of the AniList variation cache."""
    try:
        return len(json.dumps(cache or {}, ensure_ascii=False).encode('utf-8'))
    except Exception:
        return 0


def _archive_title_variations_cache_snapshot(cache: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Write a dated snapshot of the current AniList cache and return the archive path."""
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


def _prune_title_variations_by_age(cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Remove stale AniList entries using the age-based TTL policy."""
    ttl_days = get_anilist_title_variation_cache_ttl_days()
    if ttl_days <= 0:
        return dict(cache or {})

    pruned: Dict[str, Dict[str, Any]] = {}
    for key, value in (cache or {}).items():
        if not isinstance(value, dict):
            continue
        if _is_variation_stale(str(value.get('last_updated', '')), ttl_days=ttl_days):
            continue
        pruned[key] = value
    return pruned


def _prune_title_variations_by_size(cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Remove oldest AniList entries until the cache fits the configured size cap."""
    max_bytes = get_anilist_title_variation_cache_max_size_mb() * 1024 * 1024
    working = dict(cache or {})
    if _variation_cache_size_bytes(working) <= max_bytes:
        return working

    def _entry_age(value: Any) -> datetime:
        try:
            if isinstance(value, dict):
                raw = str(value.get('last_updated', '') or '').strip()
                if raw:
                    return datetime.fromisoformat(raw)
        except Exception:
            pass
        return datetime.min

    ordered_keys = sorted(working.keys(), key=lambda key: _entry_age(working.get(key)))
    for key in ordered_keys:
        if len(working) <= 1:
            break
        if _variation_cache_size_bytes(working) <= max_bytes:
            break
        working.pop(key, None)
    return working


def apply_title_variation_cache_retention(
    cache: Dict[str, Dict[str, Any]],
    archive_current: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Apply the configured AniList cache retention policy."""
    mode = get_anilist_title_variation_cache_retention_mode()
    working = dict(cache or {})

    if mode == 'rotate':
        if archive_current and working:
            _archive_title_variations_cache_snapshot(working)
        return working

    if mode == 'size':
        return _prune_title_variations_by_size(working)

    return _prune_title_variations_by_age(working)


def _fetch_anilist_title_aliases(title: str) -> List[Dict[str, str]]:
    """Fetch title aliases for one anime from AniList GraphQL API."""
    if not requests:
        return []

    from src.constants import NetworkConfig

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
    payload = {'query': query, 'variables': {'search': title}}
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

        aliases: List[Dict[str, str]] = []
        title_obj = media.get('title') or {}
        for key in ('romaji', 'english', 'native'):
            value = title_obj.get(key)
            if value and isinstance(value, str):
                aliases.append({'text': value.strip(), 'lang': key})

        synonyms = media.get('synonyms') or []
        if isinstance(synonyms, list):
            for item in synonyms:
                if isinstance(item, str) and item.strip():
                    aliases.append({'text': item.strip(), 'lang': 'synonym'})

        # Keep unique aliases while preserving order.
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
        logger.debug(f"AniList alias lookup failed for '{title}': {e}")
        return []


def _build_alias_records_from_media(media: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build normalized alias records from a single AniList media payload."""
    aliases: List[Dict[str, str]] = []
    if not isinstance(media, dict):
        return aliases

    title_obj = media.get('title') or {}
    if isinstance(title_obj, dict):
        for key in ('userPreferred', 'romaji', 'english', 'native'):
            value = title_obj.get(key)
            if value and isinstance(value, str):
                aliases.append({'text': value.strip(), 'lang': key if key != 'userPreferred' else 'romaji'})

    synonyms = media.get('synonyms') or []
    if isinstance(synonyms, list):
        for item in synonyms:
            if isinstance(item, str) and item.strip():
                aliases.append({'text': item.strip(), 'lang': 'synonym'})

    return _dedupe_alias_records(aliases)


def _build_media_lookup_keys(media: Dict[str, Any]) -> List[str]:
    """Return title variants that should point to the same AniList alias cache entry."""
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
    """Normalize AniList season/year inputs for GraphQL queries."""
    season_value = str(season or '').strip().upper()
    if season_value not in {'WINTER', 'SPRING', 'SUMMER', 'FALL'}:
        return None, None

    try:
        year_value = int(str(year or '').strip())
    except Exception:
        return None, None

    if year_value < 1900 or year_value > 3000:
        return None, None

    return season_value, year_value


def _fetch_anilist_season_media(season: str, year: str) -> List[Dict[str, Any]]:
    """Fetch all AniList anime entries for a season/year window."""
    if not requests:
        return []

    season_value, year_value = _parse_anilist_season_year(season, year)
    if not season_value or not year_value:
        return []

    from src.constants import NetworkConfig

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

            has_next = bool((page_data.get('pageInfo') or {}).get('hasNextPage'))
            if not has_next:
                break
            page += 1
        except Exception as e:
            logger.debug(f"AniList season lookup failed for '{season_value} {year_value}' page {page}: {e}")
            break

    return results


def refresh_title_variations_cache_for_season(season: str, year: str) -> int:
    """Refresh AniList aliases for every title in the selected season/year window."""
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
    """Refresh cached title aliases for SubsPlease titles (best-effort)."""
    if not requests or not subsplease_titles:
        return 0

    cache = load_title_variations_cache()
    updated = 0

    for title in subsplease_titles:
        if updated >= max_updates:
            break

        cached_entry = cache.get(title, {}) if isinstance(cache.get(title), dict) else {}
        if not force_refresh:
            ttl_days = get_anilist_title_variation_cache_ttl_days()
            if cached_entry and not _is_variation_stale(str(cached_entry.get('last_updated', '')), ttl_days=ttl_days):
                continue

        aliases = _dedupe_alias_records(_fetch_anilist_title_aliases(title))
        cache[title] = {
            'aliases': aliases,
            'last_updated': datetime.now().isoformat(),
        }
        updated += 1

    if updated > 0:
        save_title_variations_cache(cache, archive_current=True)
    return updated


def _extract_alias_texts(alias_values: Any) -> List[str]:
    """Return plain alias texts from mixed legacy/new alias cache formats."""
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
    """Normalize and dedupe alias records by text and language."""
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


def get_anilist_pull_cooldown_minutes() -> int:
    """Return user-configured AniList pull cooldown in minutes."""
    try:
        value = int(config.get_pref(ANILIST_PULL_COOLDOWN_PREF, DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES))
    except (TypeError, ValueError, AttributeError):
        value = DEFAULT_ANILIST_PULL_COOLDOWN_MINUTES
    return max(1, min(1440, value))


def get_anilist_title_variation_cache_ttl_days() -> int:
    """Return how long AniList title variation cache entries stay valid, in days.

    A value of 0 means never expire.
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
    """Return last manual AniList pull timestamp, if available."""
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
    """Return remaining cooldown seconds before next manual AniList pull."""
    last_pull = _get_anilist_last_pull_dt()
    if not last_pull:
        return 0

    cooldown_seconds = get_anilist_pull_cooldown_minutes() * 60
    elapsed_seconds = max(0, int((datetime.now() - last_pull).total_seconds()))
    remaining = cooldown_seconds - elapsed_seconds
    return max(0, remaining)


def can_pull_anilist_cache() -> Tuple[bool, int]:
    """Return whether manual AniList pull is allowed and remaining seconds."""
    remaining = get_anilist_pull_remaining_seconds()
    return remaining == 0, remaining


def get_subsplease_pull_cooldown_minutes() -> int:
    """Return user-configured SubsPlease pull cooldown in minutes."""
    try:
        value = int(config.get_pref(SUBSPLEASE_PULL_COOLDOWN_PREF, DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES))
    except (TypeError, ValueError, AttributeError):
        value = DEFAULT_SUBSPLEASE_PULL_COOLDOWN_MINUTES
    return max(1, min(1440, value))


def _get_subsplease_last_pull_dt() -> Optional[datetime]:
    """Return last manual SubsPlease pull timestamp, if available."""
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
    """Return remaining cooldown seconds before next manual SubsPlease pull."""
    last_pull = _get_subsplease_last_pull_dt()
    if not last_pull:
        return 0

    cooldown_seconds = get_subsplease_pull_cooldown_minutes() * 60
    elapsed_seconds = max(0, int((datetime.now() - last_pull).total_seconds()))
    remaining = cooldown_seconds - elapsed_seconds
    return max(0, remaining)


def can_pull_subsplease_cache() -> Tuple[bool, int]:
    """Return whether manual SubsPlease pull is allowed and remaining seconds."""
    remaining = get_subsplease_pull_remaining_seconds()
    return remaining == 0, remaining


def refresh_anilist_cache_with_limit(
    subsplease_titles: List[str],
    max_updates: int = TITLE_VARIATION_MAX_UPDATES,
    season: str = '',
    year: str = '',
    refresh_scope: str = '',
) -> Tuple[bool, int, str]:
    """Manually refresh AniList alias cache with cooldown protection."""
    if not requests:
        return False, 0, 'requests library not available'

    titles = [str(t).strip() for t in (subsplease_titles or []) if str(t).strip()]
    if not titles:
        return False, 0, 'No SubsPlease cached titles found. Fetch SubsPlease titles first.'

    allowed, remaining = can_pull_anilist_cache()
    if not allowed:
        mins = remaining // 60
        secs = remaining % 60
        return False, 0, f'Please wait {mins}m {secs}s before the next AniList pull.'

    scope = str(refresh_scope or '').strip().lower()
    updated = refresh_title_variations_cache(titles, force_refresh=True, max_updates=max_updates)
    if scope == 'title_and_season':
        season_updated = refresh_title_variations_cache_for_season(season, year)
        updated += season_updated
    try:
        config.set_pref(ANILIST_LAST_PULL_PREF, datetime.now().isoformat())
    except Exception:
        pass

    if updated > 0:
        if scope == 'title_and_season':
            season_label = f' for {str(season).strip().title()} {str(year).strip()}' if str(season).strip() and str(year).strip() else ''
            return True, updated, f'Refreshed AniList aliases for {updated} title(s){season_label}.'
        return True, updated, f'Refreshed AniList aliases for {updated} title(s).'

    return True, 0, 'AniList cache checked; no stale entries needed updates.'


def load_subsplease_cache() -> Dict[str, Dict[str, Any]]:
    """
    Loads cached SubsPlease schedule titles from cache.
    
    Returns:
        Dict with title as key and metadata dict as value:
        {
            "Anime Title": {
                "subsplease": "SubsPlease Title",
                "last_updated": "2024-01-15T10:30:00",
                "exact_match": True
            }
        }
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
    Saves SubsPlease schedule titles to cache.
    
    Args:
        titles_dict: Dictionary of titles with metadata
    
    Returns:
        bool: True if successful
    """
    try:
        from . import cache as cache_module
        success = cache_module._update_cache_key(CacheKeys.SUBSPLEASE_TITLES, titles_dict)
        if success:
            logger.info(f"Saved {len(titles_dict)} SubsPlease titles to cache")
        return success
    except Exception as e:
        logger.error(f"Failed to save SubsPlease cache: {e}")
        return False


def fetch_subsplease_schedule(force_refresh: bool = False) -> Tuple[bool, Union[List[str], str]]:
    """
    Fetches current anime titles from SubsPlease API.
    
    Uses the SubsPlease API (https://subsplease.org/api/?f=schedule&tz=UTC) 
    to get the current season's anime schedule and extract all show titles.
    
    IMPORTANT: This uses SubsPlease's public API. Usage notes:
    - SubsPlease has no published terms restricting API access
    - Multiple open-source projects use this API
    - Rate limiting is handled through caching
    - Proper User-Agent headers identify the application
    
    Args:
        force_refresh: If True, fetches from API even if cache exists
    
    Returns:
        Tuple[bool, Union[List[str], str]]: (success, list_of_titles or error_message)
    """
    if not requests:
        return False, "requests library not available"

    if force_refresh:
        allowed, remaining = can_pull_subsplease_cache()
        if not allowed:
            mins = remaining // 60
            secs = remaining % 60
            return False, f"Please wait {mins}m {secs}s before the next SubsPlease pull."
    
    # Check cache first unless force refresh
    if not force_refresh:
        cached = load_subsplease_cache()
        if cached:
            titles = list(cached.keys())
            try:
                refresh_title_variations_cache(titles, force_refresh=False)
            except Exception:
                pass
            logger.info(f"Using cached SubsPlease titles: {len(titles)} entries")
            return True, titles
    
    try:
        # Use SubsPlease API instead of scraping HTML
        from src.constants import NetworkConfig
        url = NetworkConfig.SUBSPLEASE_API_URL
        logger.info(f"Fetching SubsPlease schedule from API: {url}")
        
        # Add proper headers to identify the application
        headers = {
            'User-Agent': NetworkConfig.USER_AGENT,
            'Accept': 'application/json'
        }
        
        response = requests.get(url, timeout=NetworkConfig.DEFAULT_TIMEOUT, headers=headers)
        response.raise_for_status()
        
        # Parse JSON response
        data = response.json()
        
        if not isinstance(data, dict) or 'schedule' not in data:
            return False, "Invalid API response format"
        
        # Extract titles from all days
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
        
        # Cache the results with timestamp
        timestamp = datetime.now().isoformat()
        cache_dict = {}
        for title in titles:
            cache_dict[title] = {
                "subsplease": title,
                "last_updated": timestamp,
                "exact_match": True
            }
        
        save_subsplease_cache(cache_dict)
        if force_refresh:
            try:
                config.set_pref(SUBSPLEASE_LAST_PULL_PREF, datetime.now().isoformat())
            except Exception:
                pass
        try:
            # Best-effort alias enrichment from AniList for better cross-site title matching.
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


def find_subsplease_title_match(mal_title: str) -> Optional[str]:
    """
    Finds matching SubsPlease title for a given MAL title from cache.
    
    Uses improved fuzzy matching to handle title variations like:
    - "One Punch Man 3" vs "One-Punch Man S3"
    - Different punctuation (spaces, hyphens, colons)
    - Season numbering formats (3, S3, Season 3)
    
    Args:
        mal_title: The anime title from MyAnimeList
    
    Returns:
        Optional[str]: Matching SubsPlease title or None if no match
    """
    cached = load_subsplease_cache()
    variations = load_title_variations_cache()
    
    # Try exact match first
    if mal_title in cached:
        match_data = cached[mal_title]
        if isinstance(match_data, dict):
            return match_data.get('subsplease', mal_title)
        return str(match_data)
    
    # Try case-insensitive match
    mal_lower = mal_title.lower()
    for cached_title, data in cached.items():
        if cached_title.lower() == mal_lower:
            if isinstance(data, dict):
                return data.get('subsplease', cached_title)
            return cached_title
    
    # Try normalized fuzzy matching
    mal_normalized = _normalize_title(mal_title)
    best_match = None
    best_score = 0

    # Prefer exact alias matches (from AniList variations cache)
    for cached_title, data in cached.items():
        subsplease_title = data.get('subsplease', cached_title) if isinstance(data, dict) else cached_title
        alias_entry = variations.get(cached_title, {})
        alias_list = alias_entry.get('aliases', []) if isinstance(alias_entry, dict) else []
        alias_texts = _extract_alias_texts(alias_list)
        candidates = [cached_title, subsplease_title] + alias_texts
        for candidate in candidates:
            if mal_normalized == _normalize_title(candidate):
                return subsplease_title
    
    for cached_title, data in cached.items():
        subsplease_title = data.get('subsplease', cached_title) if isinstance(data, dict) else cached_title
        alias_entry = variations.get(cached_title, {})
        alias_list = alias_entry.get('aliases', []) if isinstance(alias_entry, dict) else []
        alias_texts = _extract_alias_texts(alias_list)
        title_variants = [cached_title, subsplease_title] + alias_texts
        
        for variant in title_variants:
            cached_normalized = _normalize_title(variant)

            # Exact normalized match (handles punctuation differences)
            if mal_normalized == cached_normalized:
                return subsplease_title

            # Check if one contains the other (with normalized versions)
            if mal_normalized in cached_normalized or cached_normalized in mal_normalized:
                # Calculate match score based on length similarity
                score = min(len(mal_normalized), len(cached_normalized))
                if score > best_score:
                    best_score = score
                    best_match = subsplease_title
    
    # Try partial word matching for multi-word titles
    if not best_match:
        mal_words = set(mal_normalized.split())
        for cached_title, data in cached.items():
            subsplease_title = data.get('subsplease', cached_title) if isinstance(data, dict) else cached_title
            alias_entry = variations.get(cached_title, {})
            alias_list = alias_entry.get('aliases', []) if isinstance(alias_entry, dict) else []
            alias_texts = _extract_alias_texts(alias_list)
            title_variants = [cached_title, subsplease_title] + alias_texts

            for variant in title_variants:
                cached_words = set(_normalize_title(variant).split())
                common_words = mal_words & cached_words
                if len(common_words) >= 2:
                    score = len(common_words) / max(len(mal_words), len(cached_words))
                    if score > 0.6 and score * 100 > best_score:
                        best_score = score * 100
                        best_match = subsplease_title
    
    return best_match
