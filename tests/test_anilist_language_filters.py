"""Tests for AniList variation language filtering behavior."""

from typing import Optional

from src.api import subsplease as subsplease_api
from src.constants import AniListRefreshScope
from src.gui.components.feed_lookup import build_feed_variation_state, evaluate_anilist_refresh


def test_build_feed_variation_state_filters_selected_languages():
    def _find_match(_title: str) -> Optional[str]:
        return "Digimon Beatbreak"

    def _load_cache():
        return {
            "Digimon Beatbreak": {
                "aliases": [
                    {"text": "Dejimon Bitorubureiku", "lang": "romaji"},
                    {"text": "Digimon Beatbreak", "lang": "english"},
                    {"text": "デジモンビートブレイク", "lang": "native"},
                    {"text": "ดิจิมอน บีทเบรก", "lang": "synonym"},
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Digimon Beatbreak",
        current_must="Digimon Beatbreak",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=["native", "romaji"],
    )

    aliases = state.get("aliases", [])
    assert "Dejimon Bitorubureiku" in aliases
    assert "デジモンビートブレイク" in aliases
    assert "ดิจิมอน บีทเบรก" not in aliases


def test_build_feed_variation_state_supports_legacy_alias_string_format():
    def _find_match(_title: str) -> Optional[str]:
        return "Legacy Anime"

    def _load_cache():
        return {
            "Legacy Anime": {
                "aliases": [
                    "Legacy Alt Name",
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Legacy Anime",
        current_must="",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=["synonym"],
    )

    assert "Legacy Alt Name" in state.get("aliases", [])


def test_build_feed_variation_state_enforces_non_empty_selection_defaults():
    def _find_match(_title: str) -> Optional[str]:
        return "Anime"

    def _load_cache():
        return {
            "Anime": {
                "aliases": [
                    {"text": "Anime Native", "lang": "native"},
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Anime",
        current_must="",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=[],
    )

    assert "Anime Native" in state.get("aliases", [])


def test_build_feed_variation_state_prefers_match_pattern_over_prefixed_title():
    calls = []

    def _find_match(query: str) -> Optional[str]:
        calls.append(query)
        if query == "Digimon Beatbreak":
            return "Digimon Beatbreak"
        return None

    def _load_cache():
        return {
            "Digimon Beatbreak": {
                "aliases": [
                    {"text": "Dejimon Bitorubureiku", "lang": "romaji"},
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Fall 2026 - Digimon Beatbreak",
        current_must="Digimon Beatbreak",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=["romaji"],
    )

    assert calls[0] == "Digimon Beatbreak"
    assert "Dejimon Bitorubureiku" in state.get("aliases", [])


def test_refresh_title_variations_cache_overwrites_key_and_dedupes_aliases(monkeypatch):
    existing_cache = {
        "Digimon Beatbreak": {
            "aliases": [
                {"text": "Old Alias", "lang": "english"},
            ],
            "last_updated": "2026-04-01T00:00:00",
        }
    }
    saved = {}

    monkeypatch.setattr(subsplease_api, "load_title_variations_cache", lambda: dict(existing_cache))
    monkeypatch.setattr(
        subsplease_api,
        "_fetch_anilist_title_aliases",
        lambda _title: [
            {"text": "New Alias", "lang": "romaji"},
            {"text": "New Alias", "lang": "romaji"},
        ],
    )
    monkeypatch.setattr(
        subsplease_api,
        "save_title_variations_cache",
        lambda variations, **_kwargs: saved.update(variations) or True,
    )

    updated = subsplease_api.refresh_title_variations_cache(["Digimon Beatbreak"], force_refresh=True, max_updates=12)

    assert updated == 1
    assert "Digimon Beatbreak" in saved
    aliases = saved["Digimon Beatbreak"]["aliases"]
    assert aliases == [
        {"text": "New Alias", "lang": "romaji"},
    ]


def test_apply_title_variation_cache_retention_prunes_by_age(monkeypatch):
    monkeypatch.setattr(
        subsplease_api.config,
        "get_pref",
        lambda key, default=None: {
            subsplease_api.PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE: "age",
            subsplease_api.PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS: 7,
        }.get(key, default),
    )

    cache = {
        "Old Title": {"aliases": [{"text": "Old", "lang": "english"}], "last_updated": "2026-03-20T00:00:00"},
        "New Title": {"aliases": [{"text": "New", "lang": "english"}], "last_updated": "2026-06-01T00:00:00"},
    }

    pruned = subsplease_api.apply_title_variation_cache_retention(cache)

    assert "Old Title" not in pruned
    assert "New Title" in pruned


def test_apply_title_variation_cache_retention_prunes_by_size(monkeypatch):
    monkeypatch.setattr(
        subsplease_api.config,
        "get_pref",
        lambda key, default=None: {
            subsplease_api.PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE: "size",
            subsplease_api.PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB: 1,
        }.get(key, default),
    )

    cache = {
        "Old Title": {"aliases": [{"text": "x" * 900_000, "lang": "english"}], "last_updated": "2026-03-20T00:00:00"},
        "New Title": {"aliases": [{"text": "y" * 900_000, "lang": "english"}], "last_updated": "2026-04-02T00:00:00"},
        "Newest Title": {"aliases": [{"text": "z" * 900_000, "lang": "english"}], "last_updated": "2026-04-03T00:00:00"},
    }

    pruned = subsplease_api.apply_title_variation_cache_retention(cache)

    assert len(pruned) < len(cache)
    assert "Newest Title" in pruned


def test_apply_title_variation_cache_retention_archives_when_rotate_mode(tmp_path, monkeypatch):
    archive_cache_file = tmp_path / "cache.json"
    archive_cache_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(subsplease_api.config, "CACHE_FILE", str(archive_cache_file))
    monkeypatch.setattr(
        subsplease_api.config,
        "get_pref",
        lambda key, default=None: {
            subsplease_api.PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE: "rotate",
        }.get(key, default),
    )

    cache = {
        "Rotate Me": {"aliases": [{"text": "Rotate", "lang": "english"}], "last_updated": "2026-04-02T00:00:00"},
    }

    retained = subsplease_api.apply_title_variation_cache_retention(cache, archive_current=True)

    assert retained == cache
    archive_files = list(tmp_path.glob("anime_title_variations-*.json"))
    assert len(archive_files) == 1
    archived = archive_files[0].read_text(encoding="utf-8")
    assert "Rotate Me" in archived


def test_refresh_title_variations_cache_for_season_writes_all_title_variants(monkeypatch):
    saved = {}

    monkeypatch.setattr(
        subsplease_api,
        "_fetch_anilist_season_media",
        lambda _season, _year: [
            {
                "title": {
                    "userPreferred": "Anime Preferred",
                    "romaji": "Anime Romaji",
                    "english": "Anime English",
                    "native": "Anime Native",
                },
                "synonyms": ["Anime Alt", "Anime Alt"],
            }
        ],
    )
    monkeypatch.setattr(
        subsplease_api,
        "save_title_variations_cache",
        lambda variations, **_kwargs: saved.update(variations) or True,
    )
    monkeypatch.setattr(subsplease_api, "load_title_variations_cache", lambda: {})

    updated = subsplease_api.refresh_title_variations_cache_for_season("SUMMER", "2026")

    assert updated == 4
    assert saved["Anime Preferred"]["aliases"] == [
        {"text": "Anime Preferred", "lang": "romaji"},
        {"text": "Anime Romaji", "lang": "romaji"},
        {"text": "Anime English", "lang": "english"},
        {"text": "Anime Native", "lang": "native"},
        {"text": "Anime Alt", "lang": "synonym"},
    ]
    assert saved["Anime English"]["aliases"] == saved["Anime Preferred"]["aliases"]


def test_evaluate_anilist_refresh_passes_season_scope_arguments():
    captured = {}

    def _refresh_anilist_cache_with_limit(titles, **kwargs):
        captured["titles"] = list(titles)
        captured.update(kwargs)
        return True, 3, "ok"

    result = evaluate_anilist_refresh(
        can_pull_anilist_cache=lambda: (True, 0),
        load_subsplease_cache=lambda: {"Season Title": {}},
        refresh_anilist_cache_with_limit=_refresh_anilist_cache_with_limit,
        current_title="Anime Preferred",
        current_must="Anime Pattern",
        selected_season="SUMMER",
        selected_year="2026",
        refresh_scope=AniListRefreshScope.TITLE_AND_SEASON,
    )

    assert result["fetch_status"] == "✅ AniList cache refreshed (3 updates)"
    assert captured["titles"] == ["Anime Pattern", "Anime Preferred"]
    assert captured["season"] == "SUMMER"
    assert captured["year"] == "2026"
    assert captured["refresh_scope"] == AniListRefreshScope.TITLE_AND_SEASON


def test_anilist_alias_cache_ttl_zero_means_never_expire():
    assert subsplease_api._is_variation_stale("2020-01-01T00:00:00", ttl_days=0) is False


def test_build_feed_variation_state_uses_match_pattern_aliases_without_subsplease_match():
    def _find_match(_title: str) -> Optional[str]:
        return None

    def _load_cache():
        return {
            "Darwin Jihen": {
                "aliases": [
                    {"text": "Darwin Incident", "lang": "english"},
                    {"text": "ダーウィン事変", "lang": "native"},
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Winter 2026 - Darwin Jihen",
        current_must="Darwin Jihen",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=["english", "native"],
    )

    aliases = state.get("aliases", [])
    assert "Darwin Incident" in aliases
    assert "ダーウィン事変" in aliases


def test_build_feed_variation_state_supports_other_language_synonym_filter():
    def _find_match(_title: str) -> Optional[str]:
        return "Tongari Boushi no Atelier"

    def _load_cache():
        return {
            "Tongari Boushi no Atelier": {
                "aliases": [
                    {"text": "Tongari Boushi no Atelier", "lang": "romaji"},
                    {"text": "Witch Hat Atelier", "lang": "english"},
                    {"text": "Atelier of Witch Hat", "lang": "synonym"},
                    {"text": "Atelier spiczastych kapeluszy", "lang": "synonym"},
                ]
            }
        }

    state = build_feed_variation_state(
        current_title="Tongari Boushi no Atelier",
        current_must="Tongari Boushi no Atelier",
        find_subsplease_title_match=_find_match,
        load_title_variations_cache=_load_cache,
        selected_languages=["synonym_other"],
    )

    aliases = state.get("aliases", [])
    assert "Atelier spiczastych kapeluszy" in aliases
    assert "Atelier of Witch Hat" not in aliases
