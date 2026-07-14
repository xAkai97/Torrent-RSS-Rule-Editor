import pytest
from src.api.subsplease import (
    find_subsplease_title_match,
    _normalize_title,
)
try:
    from src.gui_qt.main_window import run_qt_batch_apply_subsplease
    pyside_available = True
except ImportError:
    pyside_available = False
from src.config import config


def test_normalize_title_supports_ordinal_seasons():
    """Verify that _normalize_title normalizes ordinal season numbers (e.g. 2nd Season, 7th)."""
    assert _normalize_title("Tongari Boushi no Atelier 2nd Season") == "tongari boushi no atelier 2"
    assert _normalize_title("Boku no Hero Academia 7th Season") == "boku no hero academia 7"
    assert _normalize_title("Some Show 1st Season") == "some show 1"
    assert _normalize_title("Another Show 3rd") == "another show 3"
    assert _normalize_title("S4 Show") == "4 show"


def test_find_subsplease_title_match_with_season_prefixes(monkeypatch):
    """Verify that find_subsplease_title_match strips season prefixes and matches titles."""
    # Mock SubsPlease cache with clean titles
    monkeypatch.setattr(
        "src.api.subsplease.load_subsplease_cache",
        lambda: {
            "Tongari Boushi no Atelier": {"subsplease": "Tongari Boushi no Atelier"},
            "Boku no Hero Academia 7": {"subsplease": "Boku no Hero Academia 7"},
        }
    )
    monkeypatch.setattr("src.api.subsplease.load_title_variations_cache", lambda: {})

    # Match rule title with season prefix
    assert find_subsplease_title_match("Spring 2026 - Tongari Boushi no Atelier") == "Tongari Boushi no Atelier"
    assert find_subsplease_title_match("Fall 2024 - Boku no Hero Academia 7") == "Boku no Hero Academia 7"
    assert find_subsplease_title_match("   Winter 2025  -   Tongari Boushi no Atelier   ") == "Tongari Boushi no Atelier"


def test_find_subsplease_title_match_with_sequel_suffixes(monkeypatch):
    """Verify that find_subsplease_title_match handles suffix differences via normalization."""
    monkeypatch.setattr(
        "src.api.subsplease.load_subsplease_cache",
        lambda: {
            "Tongari Boushi no Atelier S2": {"subsplease": "Tongari Boushi no Atelier S2"},
        }
    )
    monkeypatch.setattr("src.api.subsplease.load_title_variations_cache", lambda: {})

    # Match rule with 2nd Season to cached S2
    assert find_subsplease_title_match("Tongari Boushi no Atelier 2nd Season") == "Tongari Boushi no Atelier S2"
    assert find_subsplease_title_match("Spring 2026 - Tongari Boushi no Atelier 2nd Season") == "Tongari Boushi no Atelier S2"


def test_find_subsplease_title_match_with_anilist_variations(monkeypatch):
    """Verify that find_subsplease_title_match utilizes AniList aliases cache correctly."""
    monkeypatch.setattr(
        "src.api.subsplease.load_subsplease_cache",
        lambda: {
            "Boku no Hero Academia 7": {"subsplease": "Boku no Hero Academia 7"},
        }
    )
    # Mock variations (aliases) cache
    monkeypatch.setattr(
        "src.api.subsplease.load_title_variations_cache",
        lambda: {
            "Boku no Hero Academia 7": {
                "aliases": [
                    "My Hero Academia Season 7",
                    "My Hero Academia 7th Season",
                ]
            }
        }
    )

    # Search by one of the aliases (with and without prefix)
    assert find_subsplease_title_match("My Hero Academia Season 7") == "Boku no Hero Academia 7"
    assert find_subsplease_title_match("Spring 2024 - My Hero Academia 7th Season") == "Boku no Hero Academia 7"


@pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")
def test_run_qt_batch_apply_subsplease(monkeypatch):
    """Verify that run_qt_batch_apply_subsplease updates multiple local rule dicts in bulk."""
    # Mock SubsPlease caches
    monkeypatch.setattr(
        "src.api.subsplease.load_subsplease_cache",
        lambda: {
            "Tongari Boushi no Atelier": {"subsplease": "Tongari Boushi no Atelier"},
            "Boku no Hero Academia 7": {"subsplease": "Boku no Hero Academia 7"},
        }
    )
    monkeypatch.setattr("src.api.subsplease.load_title_variations_cache", lambda: {})

    # Set up config.ALL_TITLES
    config.ALL_TITLES = {
        "anime": [
            {
                "ruleName": "Spring 2026 - Tongari Boushi no Atelier",
                "mustContain": "",
                "savePath": "Spring 2026/tongari",
                "node": {"title": "Spring 2026 - Tongari Boushi no Atelier"},
                "torrentParams": {"save_path": "Spring 2026/tongari"}
            },
            {
                "ruleName": "Boku no Hero Academia 7th Season",
                "mustContain": "",
                "savePath": "Boku no Hero",
                "node": {"title": "Boku no Hero Academia 7th Season"},
                "torrentParams": {"save_path": "Boku no Hero"}
            },
            {
                "ruleName": "Unmatched Show",
                "mustContain": "",
                "savePath": "Unmatched",
                "node": {"title": "Unmatched Show"}
            }
        ]
    }

    # Track callback invocations
    undos = []
    def on_before_update(name, before_dict):
        undos.append((name, before_dict))

    # Trigger batch apply for the rules
    result = run_qt_batch_apply_subsplease(
        rule_names=["Spring 2026 - Tongari Boushi no Atelier", "Boku no Hero Academia 7th Season", "Unmatched Show"],
        update_match=True,
        update_title=True,
        update_path=True,
        on_before_update=on_before_update
    )

    assert result["success"] is True
    assert result["updated_count"] == 2
    assert len(undos) == 2

    # Check updated rule values
    rules = config.ALL_TITLES["anime"]
    
    # 1. Spring 2026 - Tongari Boushi no Atelier
    rule1 = rules[0]
    assert rule1["mustContain"] == "Tongari Boushi no Atelier"
    assert rule1["ruleName"] == "Spring 2026 - Tongari Boushi no Atelier"  # title prefix preserved, title part replaced with "Tongari Boushi no Atelier"
    assert rule1["savePath"] == "Spring 2026/Tongari Boushi no Atelier"  # savePath prefix preserved, name sanitized
    assert rule1["torrentParams"]["save_path"] == "Spring 2026/Tongari Boushi no Atelier"

    # 2. Boku no Hero Academia 7th Season
    rule2 = rules[1]
    assert rule2["mustContain"] == "Boku no Hero Academia 7"
    assert rule2["ruleName"] == "Boku no Hero Academia 7"  # sequel suffix normalized and replaced
    assert rule2["savePath"] == "Boku no Hero Academia 7"
    assert rule2["torrentParams"]["save_path"] == "Boku no Hero Academia 7"

    # 3. Unmatched Show remains unchanged
    rule3 = rules[2]
    assert rule3["mustContain"] == ""
    assert rule3["ruleName"] == "Unmatched Show"
