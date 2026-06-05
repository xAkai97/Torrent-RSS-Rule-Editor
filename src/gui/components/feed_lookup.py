"""Feed lookup helpers for editor panel UI.

This module keeps title-variation lookup and rendering logic isolated from
main_window to reduce setup_editor_panel complexity.
"""

from __future__ import annotations

from tkinter import ttk
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

from src.constants import AniListRefreshScope
from src.gui.helpers.language_detection import is_other_language_synonym


def normalize_aliases(aliases: Iterable[str], current_must: str) -> List[str]:
    """Deduplicate aliases and drop values already used in match pattern."""
    cleaned: List[str] = []
    seen: set[str] = set()
    current_norm = str(current_must or "").strip().lower()

    for alias in aliases or []:
        text_val = str(alias or "").strip()
        if not text_val:
            continue
        norm = text_val.lower()
        if norm in seen:
            continue
        seen.add(norm)
        if norm == current_norm:
            continue
        cleaned.append(text_val)

    return cleaned


def build_feed_variation_state(
    current_title: str,
    current_must: str,
    find_subsplease_title_match: Callable[[str], str | None],
    load_title_variations_cache: Callable[[], Dict[str, Dict]],
    selected_languages: Sequence[str] | None = None,
) -> Dict[str, object]:
    """Return resolved feed-variation state for the current editor title."""
    title = str(current_title or "").strip()
    must = str(current_must or "").strip()
    if not title and not must:
        return {
            "subsplease_title": "(No title selected)",
            "status": "",
            "aliases": [],
            "alias_empty_text": "(Select a title to see AniList variations)",
        }

    lookup_candidates: List[str] = []
    if must:
        lookup_candidates.append(must)
    if title and title.lower() != must.lower():
        lookup_candidates.append(title)

    sp_match = None
    for candidate in lookup_candidates:
        sp_match = find_subsplease_title_match(candidate)
        if sp_match:
            break

    variations_cache = load_title_variations_cache() or {}

    aliases_with_lang: List[Tuple[str, str]] = []
    selected = {str(v).strip().lower() for v in (selected_languages or []) if str(v).strip()}
    if not selected:
        selected = {'romaji', 'english', 'native', 'synonym', 'synonym_other'}

    def _extract_aliases(alias_values: Any) -> List[Tuple[str, str]]:
        extracted: List[Tuple[str, str]] = []
        if not isinstance(alias_values, list):
            return extracted
        for alias in alias_values:
            if isinstance(alias, str):
                txt = alias.strip()
                if txt:
                    extracted.append((txt, 'synonym'))
            elif isinstance(alias, dict):
                txt = str(alias.get('text', '')).strip()
                lang = str(alias.get('lang', 'synonym')).strip().lower() or 'synonym'
                if lang == 'synonym' and is_other_language_synonym(txt):
                    lang = 'synonym_other'
                if txt:
                    extracted.append((txt, lang))
        return extracted

    if sp_match:
        cached_entry = variations_cache.get(sp_match)
        if isinstance(cached_entry, dict):
            aliases_with_lang = _extract_aliases(cached_entry.get("aliases") or [])

        if not aliases_with_lang:
            target_norm = str(sp_match).strip().lower()
            for cache_key, value in variations_cache.items():
                if str(cache_key).strip().lower() == target_norm and isinstance(value, dict):
                    aliases_with_lang = _extract_aliases(value.get("aliases") or [])
                    break
    else:
        # Fallback: allow Match Pattern/title to resolve directly in AniList cache
        # even when there is no SubsPlease cache match.
        for candidate in lookup_candidates:
            cached_entry = variations_cache.get(candidate)
            if isinstance(cached_entry, dict):
                aliases_with_lang = _extract_aliases(cached_entry.get("aliases") or [])
                if aliases_with_lang:
                    break

            target_norm = str(candidate).strip().lower()
            for cache_key, value in variations_cache.items():
                if str(cache_key).strip().lower() == target_norm and isinstance(value, dict):
                    aliases_with_lang = _extract_aliases(value.get("aliases") or [])
                    break
            if aliases_with_lang:
                break

    filtered_aliases_with_lang = [(text, lang) for text, lang in aliases_with_lang if lang in selected]
    filtered_aliases = [text for text, _lang in filtered_aliases_with_lang]
    cleaned_aliases = normalize_aliases(filtered_aliases, must)
    alias_display_map: Dict[str, str] = {}
    for text, lang in filtered_aliases_with_lang:
        if text in cleaned_aliases and text not in alias_display_map:
            alias_display_map[text] = f"[{lang}] {text}"

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


def render_anilist_variations(
    container: ttk.Frame,
    aliases: Iterable[str],
    link_color: str,
    on_apply: Callable[[str], None],
    alias_display_map: Dict[str, str] | None = None,
    empty_text: str = "(No AniList variations cached yet)",
) -> None:
    """Render clickable AniList variation labels inside a container."""
    try:
        for child in container.winfo_children():
            child.destroy()
    except Exception:
        pass

    alias_list = [str(a).strip() for a in (aliases or []) if str(a).strip()]
    if not alias_list:
        ttk.Label(
            container,
            text=str(empty_text or "(No AniList variations cached yet)"),
            font=("Segoe UI", 9),
            foreground="#1f6feb",
            padding=(4, 2),
        ).pack(anchor="w", fill="x")
        return

    alias_display_map = alias_display_map or {}

    for alias in alias_list:
        display_text = alias_display_map.get(alias, alias)
        label = ttk.Label(
            container,
            text=display_text,
            font=("Segoe UI", 10, "bold"),
            foreground=link_color,
            cursor="hand2",
            padding=(4, 2),
        )
        label.pack(anchor="w", fill="x")
        label.bind("<Button-1>", lambda _e, v=alias: on_apply(v))


def format_cooldown_wait(source: str, remaining_seconds: int) -> str:
    """Build a consistent cooldown wait message."""
    mins = int(remaining_seconds) // 60
    secs = int(remaining_seconds) % 60
    return f"⏳ {source} cooldown: wait {mins}m {secs}s"


def evaluate_subsplease_refresh(
    force_refresh: bool,
    can_pull_subsplease_cache: Callable[[], tuple[bool, int]],
    fetch_subsplease_schedule: Callable[[bool], tuple[bool, object]],
) -> Dict[str, object]:
    """Evaluate and execute SubsPlease refresh, returning UI status updates."""
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
    """Evaluate and execute AniList cache refresh, returning UI status updates."""
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
    scope = str(refresh_scope or AniListRefreshScope.TITLE_ONLY).strip().lower()

    if scope == AniListRefreshScope.TITLE_AND_SEASON:
        titles = []
        if must:
            titles.append(must)
        if title and title.lower() != must.lower():
            titles.append(title)
    else:
        if must and must not in titles:
            titles.insert(0, must)
        if title and title not in titles:
            insert_at = 1 if must and must in titles else 0
            titles.insert(insert_at, title)

    ok, updated, msg = refresh_anilist_cache_with_limit(
        titles,
        current_title=title,
        current_must=must,
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
