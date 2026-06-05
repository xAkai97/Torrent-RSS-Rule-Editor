"""Rule editor service helpers.

This module keeps Rule Editor orchestration logic UI-agnostic so both
Tkinter and future frontends (e.g., PySide6) can share the same behavior.
"""

from __future__ import annotations

from typing import Callable, Dict, Sequence

from src.config import config
from src.constants import AniListRefreshScope, PrefKeys
from src.gui.components.feed_lookup import (
    build_feed_variation_state,
    evaluate_anilist_refresh,
    evaluate_subsplease_refresh,
)


def get_selected_anilist_languages() -> list[str]:
    """Return configured AniList alias language filters with safe defaults."""
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
    """Resolve AniList refresh scope from explicit override or user preference."""
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
    """Build feed lookup state for Rule Editor title variations section."""
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
    """Run SubsPlease refresh evaluation and return UI-neutral status payload."""
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
    """Run AniList refresh evaluation and return UI-neutral status payload."""
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
