"""
Rule Editor Service — Title Variation Lookup and Cache Refresh Orchestration.

This module provides the business logic behind the Rule Editor dialog's
"Feed Lookup" section. When a user selects a title to edit, this module:

  1. Looks up the title in the SubsPlease schedule cache
  2. Finds AniList title variations (synonyms in different languages)
  3. Filters variations by the user's selected languages
  4. Handles SubsPlease and AniList cache refresh with cooldown enforcement

All functions are UI-agnostic — they return plain data payloads that the
Qt GUI renders. This separation allows the same logic to be tested without
a GUI and shared across different UI implementations.

Key concept: "Feed variations" are alternative names for an anime title
(English, Romaji, Native Japanese, etc.) sourced from AniList's GraphQL API
and cached locally to avoid rate-limiting.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

from src.config import config
from src.constants import AniListRefreshScope, PrefKeys
from src.services.language_detection import is_other_language_synonym


# ---------------------------------------------------------------------------
# Feed-variation helpers
# ---------------------------------------------------------------------------
# These were originally in the legacy Tk GUI (src.gui.components.feed_lookup)
# and have been moved here to make them UI-agnostic and testable.
# ---------------------------------------------------------------------------

# Matches season/year prefixes like "Spring 2026 - " at the start of titles.
# These prefixes are added by the app during import and need to be stripped
# before querying AniList (which doesn't know about our season prefixes).
_RE_SEASON_PREFIX = re.compile(r'^\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*', re.IGNORECASE)


def normalize_aliases(aliases: Iterable[str], current_must: str) -> List[str]:
    """
    Deduplicate a list of alias strings, preserving order.

    All values are kept even if they match the current mustContain pattern,
    since users may want to see/select them for regex building.

    Args:
        aliases: Raw alias strings to deduplicate.
        current_must: The current mustContain value (kept for interface compat).

    Returns:
        A deduplicated list of non-empty alias strings.
    """
    cleaned: List[str] = []
    seen: set[str] = set()

    for alias in aliases or []:
        text_val = str(alias or "").strip()
        if not text_val:
            continue
        norm = text_val.lower()
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(text_val)

    return cleaned


def build_feed_variation_state(
    current_title: str,
    current_must: str,
    find_subsplease_title_match: Callable[[str], str | None],
    load_title_variations_cache: Callable[[], Dict[str, Dict]],
    selected_languages: Sequence[str] | None = None,
) -> Dict[str, object]:
    """
    Resolve the complete feed-variation state for the Rule Editor's title panel.

    This is the main orchestrator for the title variations section. It:
      1. Tries to find a SubsPlease match for the current title
      2. Looks up AniList variations in the local cache
      3. Classifies each variation by language (romaji, english, native, synonym)
      4. Filters by the user's selected language preferences
      5. Returns a display-ready payload for the GUI

    The function accepts callbacks for SubsPlease lookup and cache loading
    so it can be tested without actual API calls.

    Args:
        current_title: The display title currently being edited.
        current_must: The current mustContain match pattern.
        find_subsplease_title_match: Callback to look up SubsPlease schedule.
        load_title_variations_cache: Callback to load the AniList variations cache.
        selected_languages: Which language types to include (e.g. ['romaji', 'english']).

    Returns:
        A state dictionary with:
          subsplease_title  — matched SubsPlease title or status message
          status            — emoji-prefixed status line for the GUI
          aliases           — filtered and deduplicated alias list
          alias_display_map — maps alias text to "[lang] text" for display
          alias_empty_text  — placeholder text when no aliases are available
    """
    title = str(current_title or "").strip()
    must = str(current_must or "").strip()

    # No title selected — return empty state
    if not title and not must:
        return {
            "subsplease_title": "(No title selected)",
            "status": "",
            "aliases": [],
            "alias_empty_text": "(Select a title to see AniList variations)",
        }

    # Build lookup candidates — try mustContain first, then display title
    lookup_candidates: List[str] = []
    if must:
        lookup_candidates.append(must)
    if title and title.lower() != must.lower():
        lookup_candidates.append(title)

    # --- Step 1: Find SubsPlease match ---
    sp_match = None
    for candidate in lookup_candidates:
        sp_match = find_subsplease_title_match(candidate)
        if sp_match:
            break

    # --- Step 2: Load AniList variations from cache ---
    variations_cache = load_title_variations_cache() or {}

    # --- Step 3: Extract and classify aliases by language ---
    aliases_with_lang: List[Tuple[str, str]] = []
    selected = {str(v).strip().lower() for v in (selected_languages or []) if str(v).strip()}
    if not selected:
        # Default: show all language types
        selected = {'romaji', 'english', 'native', 'synonym', 'synonym_other'}

    def _extract_aliases(alias_values: Any) -> List[Tuple[str, str]]:
        """Extract (text, language) pairs from a cache entry's alias list."""
        extracted: List[Tuple[str, str]] = []
        if not isinstance(alias_values, list):
            return extracted
        for alias in alias_values:
            if isinstance(alias, str):
                # Simple string alias — classify as generic synonym
                txt = alias.strip()
                if txt:
                    extracted.append((txt, 'synonym'))
            elif isinstance(alias, dict):
                # Rich alias with language metadata
                txt = str(alias.get('text', '')).strip()
                lang = str(alias.get('lang', 'synonym')).strip().lower() or 'synonym'
                # Use heuristic to reclassify unknown-language synonyms
                if lang == 'synonym' and is_other_language_synonym(txt):
                    lang = 'synonym_other'
                if txt:
                    extracted.append((txt, lang))
        return extracted

    # Try to find cached aliases — first by SubsPlease match, then by title/must
    if sp_match:
        cached_entry = variations_cache.get(sp_match)
        if isinstance(cached_entry, dict):
            aliases_with_lang = _extract_aliases(cached_entry.get("aliases") or [])

        # Fallback: case-insensitive cache key lookup
        if not aliases_with_lang:
            target_norm = str(sp_match).strip().lower()
            for cache_key, value in variations_cache.items():
                if str(cache_key).strip().lower() == target_norm and isinstance(value, dict):
                    aliases_with_lang = _extract_aliases(value.get("aliases") or [])
                    break
    else:
        # No SubsPlease match — try looking up by title/must directly
        for candidate in lookup_candidates:
            cached_entry = variations_cache.get(candidate)
            if isinstance(cached_entry, dict):
                aliases_with_lang = _extract_aliases(cached_entry.get("aliases") or [])
                if aliases_with_lang:
                    break

            # Fallback: case-insensitive lookup
            target_norm = str(candidate).strip().lower()
            for cache_key, value in variations_cache.items():
                if str(cache_key).strip().lower() == target_norm and isinstance(value, dict):
                    aliases_with_lang = _extract_aliases(value.get("aliases") or [])
                    break
            if aliases_with_lang:
                break

    # --- Step 4: Filter by selected languages and build display data ---
    filtered_aliases_with_lang = [(text, lang) for text, lang in aliases_with_lang if lang in selected]
    filtered_aliases = [text for text, _lang in filtered_aliases_with_lang]
    cleaned_aliases = normalize_aliases(filtered_aliases, must)

    # Build display map: "Title" → "[romaji] Title" for the GUI list
    alias_display_map: Dict[str, str] = {}
    for text, lang in filtered_aliases_with_lang:
        if text in cleaned_aliases and text not in alias_display_map:
            alias_display_map[text] = f"[{lang}] {text}"

    # --- Step 5: Build the final state payload ---
    if sp_match:
        if str(sp_match) != must:
            return {
                "subsplease_title": str(sp_match),
                "status": f"✅ Match found (AniList variations: {len(cleaned_aliases)})",
                "aliases": cleaned_aliases,
                "alias_display_map": alias_display_map,
                "alias_empty_text": "(No AniList variations for this title yet - click Refresh AniList Cache)",
            }
        return {
            "subsplease_title": str(sp_match),
            "status": "✅ Already using SubsPlease title",
            "aliases": cleaned_aliases,
            "alias_display_map": alias_display_map,
            "alias_empty_text": "(No AniList variations for this title yet - click Refresh AniList Cache)",
        }

    if cleaned_aliases:
        return {
            "subsplease_title": "(No matching SubsPlease title in cache)",
            "status": f"ℹ️ No SubsPlease match (AniList variations from Match Pattern/Title: {len(cleaned_aliases)})",
            "aliases": cleaned_aliases,
            "alias_display_map": alias_display_map,
            "alias_empty_text": "(No AniList variations cached yet)",
        }

    return {
        "subsplease_title": "(No matching SubsPlease title in cache)",
        "status": "⚠️ No AniList cache for Match Pattern/Title - click Refresh AniList Cache",
        "aliases": [],
        "alias_display_map": {},
        "alias_empty_text": "(No AniList variations cached for current Match Pattern/Title)",
    }


# ---------------------------------------------------------------------------
# Cache refresh orchestrators
# ---------------------------------------------------------------------------
# These functions handle the refresh flow with cooldown enforcement.
# They're called when the user clicks "Refresh SubsPlease Cache" or
# "Refresh AniList Cache" in the Rule Editor.
# ---------------------------------------------------------------------------

def format_cooldown_wait(source: str, remaining_seconds: int) -> str:
    """
    Build a human-readable cooldown message with minutes and seconds.

    Example: "⏳ AniList cooldown: wait 2m 30s"
    """
    mins = int(remaining_seconds) // 60
    secs = int(remaining_seconds) % 60
    return f"⏳ {source} cooldown: wait {mins}m {secs}s"


def evaluate_subsplease_refresh(
    force_refresh: bool,
    can_pull_subsplease_cache: Callable[[], tuple[bool, int]],
    fetch_subsplease_schedule: Callable[[bool], tuple[bool, object]],
) -> Dict[str, object]:
    """
    Evaluate and execute a SubsPlease schedule cache refresh.

    Respects the cooldown timer — if the user refreshed too recently,
    returns a cooldown message instead of hitting the API.

    Args:
        force_refresh: True if the user explicitly clicked refresh.
        can_pull_subsplease_cache: Returns (allowed, remaining_seconds).
        fetch_subsplease_schedule: Actually fetches the schedule.

    Returns:
        A UI-neutral status payload with:
          fetch_status             — status string for the SubsPlease section
          app_status               — status string for the app status bar
          should_update_variations — whether to re-run variation lookup
    """
    if force_refresh:
        allowed, remaining = can_pull_subsplease_cache()
        if not allowed:
            return {
                "fetch_status": format_cooldown_wait("SubsPlease", remaining),
                "app_status": "SubsPlease pull skipped due to cooldown",
                "should_update_variations": False,
            }

    success, result = fetch_subsplease_schedule(force_refresh=force_refresh)
    if success:
        count = len(result) if isinstance(result, list) else 0
        if force_refresh:
            fetch_status = f"✅ Fetched {count} titles from API"
        else:
            fetch_status = f"📦 {count} titles in cache"
        return {
            "fetch_status": fetch_status,
            "app_status": "",
            "should_update_variations": True,
        }

    return {
        "fetch_status": f"❌ {result}",
        "app_status": "",
        "should_update_variations": False,
    }


def evaluate_anilist_refresh(
    can_pull_anilist_cache: Callable[[], tuple[bool, int]],
    load_subsplease_cache: Callable[[], Dict[str, Dict]],
    refresh_anilist_cache_with_limit: Callable[..., tuple[bool, int, str]],
    current_title: str = '',
    current_must: str = '',
    selected_season: str = '',
    selected_year: str = '',
    refresh_scope: str = '',
) -> Dict[str, object]:
    """
    Evaluate and execute an AniList title variation cache refresh.

    Respects the cooldown timer. The refresh scope controls what gets updated:
      - TITLE_ONLY: Only refresh the current title's variations
      - TITLE_AND_SEASON: Refresh the current title plus all titles in the
        selected season (slower but more comprehensive)

    Season prefixes (like "Spring 2026 - ") are stripped from titles before
    querying AniList, since AniList doesn't know about our prefixes.

    Args:
        can_pull_anilist_cache: Returns (allowed, remaining_seconds).
        load_subsplease_cache: Loads the SubsPlease schedule for title list.
        refresh_anilist_cache_with_limit: Actually refreshes the AniList cache.
        current_title / current_must: The title being edited.
        selected_season / selected_year: Current season/year for scope filtering.
        refresh_scope: 'title_only' or 'title_and_season'.

    Returns:
        A UI-neutral status payload (same shape as evaluate_subsplease_refresh).
    """
    allowed, remaining = can_pull_anilist_cache()
    if not allowed:
        return {
            "fetch_status": format_cooldown_wait("AniList", remaining),
            "app_status": "AniList pull skipped due to cooldown",
            "should_update_variations": False,
        }


    cached = load_subsplease_cache() or {}
    titles = list(cached.keys()) if isinstance(cached, dict) else []
    must = str(current_must or '').strip()
    title = str(current_title or '').strip()

    # Strip season/year prefixes before querying AniList
    if must:
        must = _RE_SEASON_PREFIX.sub('', must).strip()
    if title:
        title = _RE_SEASON_PREFIX.sub('', title).strip()

    scope = str(refresh_scope or AniListRefreshScope.TITLE_ONLY).strip().lower()

    if scope == AniListRefreshScope.TITLE_AND_SEASON:
        # Refresh only the current title(s), not the full schedule
        titles = []
        if must:
            titles.append(must)
        if title and title.lower() != must.lower():
            titles.append(title)
    else:
        # Add current title to front of the schedule list for priority refresh
        if must and must not in titles:
            titles.insert(0, must)
        if title and title not in titles:
            insert_at = 1 if must and must in titles else 0
            titles.insert(insert_at, title)

    ok, updated, msg = refresh_anilist_cache_with_limit(
        titles,
        season=selected_season,
        year=selected_year,
        refresh_scope=scope,
    )
    if ok:
        if updated > 0:
            fetch_status = f"✅ AniList cache refreshed ({updated} updates)"
        else:
            fetch_status = "✅ AniList cache is already up to date"
        return {
            "fetch_status": fetch_status,
            "app_status": str(msg),
            "should_update_variations": True,
        }

    return {
        "fetch_status": f"⚠️ {msg}",
        "app_status": str(msg),
        "should_update_variations": False,
    }


# ---------------------------------------------------------------------------
# Rule editor service wrappers
# ---------------------------------------------------------------------------
# These are thin wrappers that inject user preferences (selected languages,
# refresh scope) into the core functions above. They're the main entry points
# called by the Qt GUI.
# ---------------------------------------------------------------------------

def get_selected_anilist_languages() -> list[str]:
    """
    Get the user's selected AniList language filters from preferences.

    Defaults to all languages if not configured.

    Returns:
        A list of language type strings (e.g. ['romaji', 'english', 'native']).
    """
    try:
        selected_langs = config.get_pref(
            PrefKeys.ANILIST_DISPLAY_LANGUAGES,
            ['romaji', 'english', 'native', 'synonym', 'synonym_other'],
        )
    except Exception:
        selected_langs = ['romaji', 'english', 'native', 'synonym', 'synonym_other']

    if not isinstance(selected_langs, list):
        return ['romaji', 'english', 'native', 'synonym', 'synonym_other']

    return [str(v).strip().lower() for v in selected_langs if str(v).strip()]


def resolve_anilist_refresh_scope(refresh_scope_override: str | None = None) -> str:
    """
    Determine the AniList refresh scope from an explicit override or user preference.

    Args:
        refresh_scope_override: Explicit scope string, or None to use preference.

    Returns:
        Either 'title_only' or 'title_and_season'.
    """
    if refresh_scope_override:
        return str(refresh_scope_override).strip().lower()

    try:
        value = config.get_pref(PrefKeys.ANILIST_REFRESH_SCOPE, AniListRefreshScope.TITLE_ONLY)
    except Exception:
        value = AniListRefreshScope.TITLE_ONLY

    scope = str(value or AniListRefreshScope.TITLE_ONLY).strip().lower()
    if scope not in (AniListRefreshScope.TITLE_ONLY, AniListRefreshScope.TITLE_AND_SEASON):
        return AniListRefreshScope.TITLE_ONLY
    return scope


def build_rule_editor_feed_state(
    current_title: str,
    current_must: str,
    find_subsplease_title_match: Callable[[str], str | None],
    load_title_variations_cache: Callable[[], Dict[str, Dict]],
) -> Dict[str, object]:
    """
    Build the complete feed lookup state for the Rule Editor panel.

    This is the main entry point called by the Qt GUI when a title is
    selected. It injects the user's language preferences automatically.
    """
    return build_feed_variation_state(
        current_title=current_title,
        current_must=current_must,
        find_subsplease_title_match=find_subsplease_title_match,
        load_title_variations_cache=load_title_variations_cache,
        selected_languages=get_selected_anilist_languages(),
    )


def run_subsplease_refresh(
    force_refresh: bool,
    can_pull_subsplease_cache: Callable[[], tuple[bool, int]],
    fetch_subsplease_schedule: Callable[[bool], tuple[bool, object]],
) -> Dict[str, object]:
    """
    Run a SubsPlease cache refresh and return a UI-neutral status payload.

    Thin wrapper that delegates to evaluate_subsplease_refresh().
    """
    return evaluate_subsplease_refresh(
        force_refresh=force_refresh,
        can_pull_subsplease_cache=can_pull_subsplease_cache,
        fetch_subsplease_schedule=fetch_subsplease_schedule,
    )


def run_anilist_refresh(
    can_pull_anilist_cache: Callable[[], tuple[bool, int]],
    load_subsplease_cache: Callable[[], Dict[str, Dict]],
    refresh_anilist_cache_with_limit: Callable[..., tuple[bool, int, str]],
    current_title: str = '',
    current_must: str = '',
    selected_season: str = '',
    selected_year: str = '',
    refresh_scope_override: str | None = None,
) -> Dict[str, object]:
    """
    Run an AniList cache refresh and return a UI-neutral status payload.

    Resolves the refresh scope from override or preferences, then delegates
    to evaluate_anilist_refresh().
    """
    refresh_scope = resolve_anilist_refresh_scope(refresh_scope_override)
    return evaluate_anilist_refresh(
        can_pull_anilist_cache=can_pull_anilist_cache,
        load_subsplease_cache=load_subsplease_cache,
        refresh_anilist_cache_with_limit=refresh_anilist_cache_with_limit,
        current_title=current_title,
        current_must=current_must,
        selected_season=selected_season,
        selected_year=selected_year,
        refresh_scope=refresh_scope,
    )
