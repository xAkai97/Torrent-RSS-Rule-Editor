"""Tests for Rule Editor UI-agnostic service helpers."""

from src.constants import AniListRefreshScope
from src.services import rule_editor


def test_resolve_anilist_refresh_scope_uses_override():
    assert (
        rule_editor.resolve_anilist_refresh_scope(AniListRefreshScope.TITLE_AND_SEASON)
        == AniListRefreshScope.TITLE_AND_SEASON
    )


def test_resolve_anilist_refresh_scope_falls_back_to_title_only_for_invalid_pref(monkeypatch):
    monkeypatch.setattr(rule_editor.config, "get_pref", lambda *_args, **_kwargs: "invalid")

    assert rule_editor.resolve_anilist_refresh_scope() == AniListRefreshScope.TITLE_ONLY


def test_run_anilist_refresh_passes_resolved_scope_and_inputs():
    captured = {}

    def _refresh(titles, **kwargs):
        captured["titles"] = list(titles)
        captured.update(kwargs)
        return True, 2, "ok"

    result = rule_editor.run_anilist_refresh(
        can_pull_anilist_cache=lambda: (True, 0),
        load_subsplease_cache=lambda: {"Cache Title": {}},
        refresh_anilist_cache_with_limit=_refresh,
        current_title="Editor Title",
        current_must="Match Pattern",
        selected_season="SUMMER",
        selected_year="2026",
        refresh_scope_override=AniListRefreshScope.TITLE_AND_SEASON,
    )

    assert result["should_update_variations"] is True
    assert captured["refresh_scope"] == AniListRefreshScope.TITLE_AND_SEASON
    assert captured["season"] == "SUMMER"
    assert captured["year"] == "2026"


def test_build_rule_editor_feed_state_uses_language_pref(monkeypatch):
    monkeypatch.setattr(
        rule_editor.config,
        "get_pref",
        lambda key, default=None: ["native"] if key else default,
    )

    def _find_match(_title: str):
        return "Anime"

    def _load_cache():
        return {
            "Anime": {
                "aliases": [
                    {"text": "Anime Native", "lang": "native"},
                    {"text": "Anime English", "lang": "english"},
                ]
            }
        }

    state = rule_editor.build_rule_editor_feed_state(
        current_title="Anime",
        current_must="",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
    )

    aliases = state.get("aliases", [])
    assert "Anime Native" in aliases
    assert "Anime English" not in aliases


def test_run_anilist_refresh_strips_season_prefixes():
    captured = {}

    def _refresh(titles, **kwargs):
        captured["titles"] = list(titles)
        return True, 1, "ok"

    rule_editor.run_anilist_refresh(
        can_pull_anilist_cache=lambda: (True, 0),
        load_subsplease_cache=lambda: {},
        refresh_anilist_cache_with_limit=_refresh,
        current_title="Spring 2026 - Anime Title",
        current_must="Fall 2025 - Match Pattern",
        selected_season="SUMMER",
        selected_year="2026",
        refresh_scope_override=AniListRefreshScope.TITLE_ONLY,
    )

    assert "Anime Title" in captured["titles"]
    assert "Match Pattern" in captured["titles"]
    assert not any("Spring" in t for t in captured["titles"])
    assert not any("Fall" in t for t in captured["titles"])
