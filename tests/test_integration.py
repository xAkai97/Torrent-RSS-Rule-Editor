"""
Integration Tests for qBittorrent RSS Rule Editor

This test suite validates that all modules work together correctly
and tests complete workflows from start to finish.
"""
import os
import json
import pytest
from pathlib import Path
from src.config import config



def test_complete_module_integration():
    """Test that all modules can be imported together."""
    from src import config as src_config, rss_rules
    from src.api import qbittorrent as qbittorrent_api
    from src.api import subsplease as subsplease_api
    from src import cache, utils, constants
    from src.services import rule_editor

    assert src_config is not None
    assert qbittorrent_api is not None
    assert rss_rules is not None
    assert subsplease_api is not None
    assert cache is not None
    assert utils is not None
    assert constants is not None
    assert rule_editor is not None


def test_config_to_cache_integration():
    """Test config and cache modules working together."""
    from src.cache import save_recent_files, load_recent_files

    # Test saving recent files directly through cache module
    test_files = ['/path/to/file1.json', '/path/to/file2.json']
    success = save_recent_files(test_files)
    assert success, "Failed to save recent files"

    # Load back
    loaded = load_recent_files()
    assert loaded == test_files, "Recent files mismatch"


def test_utils_to_rss_rules_integration():
    """Test utils functions used by RSS rules module."""
    from src.utils import sanitize_folder_name, get_current_anime_season
    from src.rss_rules import create_rule, build_save_path

    # Test sanitization in rule creation
    dirty_title = "Test/Show/Name"
    clean_title = sanitize_folder_name(dirty_title)
    assert clean_title == "Test_Show_Name"

    # Create rule with sanitized name
    rule = create_rule(
        title=dirty_title,
        must_contain=clean_title,
        save_path=f"/anime/{clean_title}"
    )
    assert rule.title == dirty_title
    assert rule.must_contain == clean_title

    # Test seasonal path building
    season, year = get_current_anime_season()
    path = build_save_path("Test Show", season, year)
    assert path is not None
    assert "Test Show" in path


def test_rss_rules_to_qbt_api_integration():
    """Test creating rules and preparing for qBittorrent upload."""
    from src.rss_rules import create_rule
    from src.api.qbittorrent import QBittorrentClient

    # Create a rule
    rule = create_rule(
        title="Test Anime",
        must_contain="Test Anime 1080p",
        save_path="/anime/Test Anime",
        feed_url="https://example.com/rss",
        category="anime"
    )

    # Convert to qBittorrent format
    rule_dict = rule.to_dict()
    assert 'mustContain' in rule_dict
    assert 'affectedFeeds' in rule_dict
    assert 'torrentParams' in rule_dict

    # Verify format is compatible (client would accept this)
    client = QBittorrentClient(
        protocol='http',
        host='localhost',
        port='8080',
        username='test',
        password='test'
    )
    assert client is not None


def test_subsplease_to_rss_rules_integration():
    """Test fetching SubsPlease data and creating rules."""
    from src.api.subsplease import fetch_subsplease_schedule
    from src.rss_rules import build_rules_from_titles

    # Fetch schedule (will use cache or fail gracefully)
    success, result = fetch_subsplease_schedule(force_refresh=False)

    if success and isinstance(result, list):
        titles = result
    else:
        # Use mock data if fetch failed
        titles = ['Test Anime 1', 'Test Anime 2']

    # Create rules from titles
    rules_data = {
        'anime': [
            {'node': {'title': title}, 'mustContain': title}
            for title in titles[:5]
        ]
    }
    rules = build_rules_from_titles(rules_data)
    assert isinstance(rules, dict)


def test_complete_workflow(tmp_path):
    """Test a complete end-to-end workflow."""
    from src.utils import get_current_anime_season
    from src.rss_rules import build_rules_from_titles, export_rules_to_json, validate_rules

    # Step 1: Get current season
    season, year = get_current_anime_season()

    # Step 2: Create mock anime titles
    titles = {
        'anime': [
            {
                'node': {'title': 'Anime Show 1'},
                'mustContain': 'Anime Show 1',
                'season': None,
                'year': None,
                'affectedFeeds': ['https://example.com/rss'],
                'assignedCategory': 'anime'
            },
            {
                'node': {'title': 'Anime Show 2'},
                'mustContain': 'Anime Show 2',
                'season': None,
                'year': None,
                'affectedFeeds': ['https://example.com/rss'],
                'assignedCategory': 'anime'
            }
        ]
    }

    # Step 3: Build rules from titles
    rules = build_rules_from_titles(titles)
    assert len(rules) == 2

    # Step 4: Validate rules
    errors = validate_rules(rules)
    assert not errors, f"Validation errors found: {errors}"

    # Step 5: Export to JSON
    temp_path = tmp_path / "rules_export.json"
    success, msg = export_rules_to_json(rules, str(temp_path))
    assert success, f"Export failed: {msg}"
    assert temp_path.exists()

    # Step 6: Verify file exists and is valid JSON
    with open(temp_path, 'r') as f:
        loaded = json.load(f)
    assert len(loaded) == len(rules)


def test_error_handling():
    """Test error handling across modules."""
    from src.rss_rules import RSSRule
    from src.utils import sanitize_folder_name
    from src.api.qbittorrent import ping_qbittorrent

    # Test 1: Invalid rule validation
    invalid_rule = RSSRule(title="Test", must_contain="", feed_url="")
    is_valid, error = invalid_rule.validate()
    assert not is_valid, "Invalid rule passed validation"

    # Test 2: Invalid folder name sanitization
    dangerous_name = "../../etc/passwd"
    sanitized = sanitize_folder_name(dangerous_name)
    assert sanitized != dangerous_name, "Dangerous path not sanitized"

    # Test 3: Connection to invalid server
    success, msg = ping_qbittorrent(
        protocol='http',
        host='invalid-host-12345',
        port='9999',
        username='test',
        password='test',
        timeout=2
    )
    assert not success, "Invalid connection succeeded"


def test_all_exports():
    """Test that all module exports are accessible."""
    from src import config as src_config, rss_rules
    from src.api import qbittorrent as qbittorrent_api
    from src.api import subsplease as subsplease_api

    # Test submodule exports
    from src.api.qbittorrent import QBittorrentClient, ping_qbittorrent
    from src.rss_rules import RSSRule, create_rule
    from src.api.subsplease import fetch_subsplease_schedule
    from src.utils import sanitize_folder_name, get_current_anime_season
    from src.cache import load_recent_files, save_recent_files
    from src.constants import Season, CacheKeys

    assert QBittorrentClient is not None
    assert ping_qbittorrent is not None
    assert RSSRule is not None
    assert create_rule is not None
    assert fetch_subsplease_schedule is not None
    assert sanitize_folder_name is not None
    assert get_current_anime_season is not None
    assert load_recent_files is not None
    assert save_recent_files is not None

    # Test __all__ exports
    modules_with_all = [
        ('src.api.qbittorrent', qbittorrent_api),
        ('src.rss_rules', rss_rules),
        ('src.api.subsplease', subsplease_api),
    ]

    for name, module in modules_with_all:
        if hasattr(module, '__all__'):
            assert isinstance(module.__all__, list)


def test_version_consistency():
    """Test version numbers are consistent."""
    from src import __version__ as src_version
    assert isinstance(src_version, str)
    assert len(src_version) > 0


def test_documentation_exists():
    """Verify key documentation files exist."""
    docs = [
        'README.md',
        'TODO.md',
        'AGENTS.md',
        'SECURITY.md'
    ]

    for doc in docs:
        path = Path(doc)
        assert path.exists(), f"Missing doc: {doc}"
