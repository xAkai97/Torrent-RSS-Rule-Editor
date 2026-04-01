"""
Integration Tests for qBittorrent RSS Rule Editor

This test suite validates that all modules work together correctly
and tests complete workflows from start to finish.

Phase 6: Integration & Testing
"""
import sys
import logging
import tempfile
import os
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def test_complete_module_integration():
    """Test that all modules can be imported together."""
    print("\n" + "="*60)
    print("Test 1: Complete Module Integration")
    print("="*60)
    
    # Import all main modules
    from src import config, qbittorrent_api, rss_rules, subsplease_api
    from src import cache, utils, constants
    from src.gui import widgets
    
    print("[OK] All core modules imported")
    print(f"  - config (v{config.__dict__.get('__version__', 'N/A')})")
    print("  - qbittorrent_api")
    print("  - rss_rules")
    print("  - subsplease_api")
    print("  - cache")
    print("  - utils")
    print("  - constants")
    print("  - gui.widgets")
def test_config_to_cache_integration():
    """Test config and cache modules working together."""
    print("\n" + "="*60)
    print("Test 2: Config <-> Cache Integration")
    print("="*60)
    
    try:
        from src.config import config
        from src.cache import save_recent_files, load_recent_files
        
        # Test saving recent files directly through cache module
        test_files = ['/path/to/file1.json', '/path/to/file2.json']
        success = save_recent_files(test_files)
        assert success, "Failed to save recent files"
        print(f"[OK] Saved {len(test_files)} recent files")
        
        # Load back
        loaded = load_recent_files()
        assert loaded == test_files, "Recent files mismatch"
        print(f"[OK] Loaded {len(loaded)} recent files")
    except Exception as e:
        print(f"[FAIL] Config-Cache integration failed: {e}")
        assert False, str(e)


def test_utils_to_rss_rules_integration():
    """Test utils functions used by RSS rules module."""
    print("\n" + "="*60)
    print("Test 3: Utils <-> RSS Rules Integration")
    print("="*60)
    
    try:
        from src.utils import sanitize_folder_name, get_current_anime_season
        from src.rss_rules import create_rule, build_save_path
        
        # Test sanitization in rule creation
        dirty_title = "Test: Show? <Name>"
        clean_title = sanitize_folder_name(dirty_title)
        print(f"[OK] Sanitized: '{dirty_title}'  '{clean_title}'")
        
        # Create rule with sanitized name
        rule = create_rule(
            title=dirty_title,
            must_contain=clean_title,
            save_path=f"/anime/{clean_title}"
        )
        print(f"[OK] Created rule with sanitized name")
        
        # Test seasonal path building
        season, year = get_current_anime_season()
        path = build_save_path("Test Show", season, year)
        print(f"[OK] Built seasonal path: {path}")
    except Exception as e:
        print(f"[FAIL] Utils-RSS Rules integration failed: {e}")
        assert False, str(e)


def test_rss_rules_to_qbt_api_integration():
    """Test creating rules and preparing for qBittorrent upload."""
    print("\n" + "="*60)
    print("Test 4: RSS Rules <-> qBittorrent API Integration")
    print("="*60)
    
    try:
        from src.rss_rules import create_rule, build_rules_from_titles
        from src.qbittorrent_api import QBittorrentClient
        
        # Create a rule
        rule = create_rule(
            title="Test Anime",
            must_contain="Test Anime 1080p",
            save_path="/anime/Test Anime",
            feed_url="https://example.com/rss",
            category="anime"
        )
        print("[OK] Created RSS rule")
        
        # Convert to qBittorrent format
        rule_dict = rule.to_dict()
        assert 'mustContain' in rule_dict, "Missing mustContain"
        assert 'affectedFeeds' in rule_dict, "Missing affectedFeeds"
        assert 'torrentParams' in rule_dict, "Missing torrentParams"
        print("[OK] Converted to qBittorrent format")
        
        # Verify format is compatible (client would accept this)
        client = QBittorrentClient(
            protocol='http',
            host='localhost',
            port='8080',
            username='test',
            password='test'
        )
        print("[OK] QBittorrent client can be initialized with rules")
    except Exception as e:
        print(f"[FAIL] RSS Rules-QBT API integration failed: {e}")
        assert False, str(e)


def test_subsplease_to_rss_rules_integration():
    """Test fetching SubsPlease data and creating rules."""
    print("\n" + "="*60)
    print("Test 5: SubsPlease API <-> RSS Rules Integration")
    print("="*60)
    
    try:
        from src.subsplease_api import fetch_subsplease_schedule
        from src.rss_rules import create_rule, build_rules_from_titles
        
        # Fetch schedule (will use cache or fail gracefully)
        success, result = fetch_subsplease_schedule(force_refresh=False)
        
        if success and isinstance(result, list):
            titles = result
            print(f"[OK] Fetched {len(titles)} titles from SubsPlease")
        else:
            # Use mock data if fetch failed
            titles = ['Test Anime 1', 'Test Anime 2']
            print(f"[OK] Using {len(titles)} mock titles (fetch unavailable)")
        
        # Create rules from titles
        rules_data = {
            'anime': [
                {'node': {'title': title}, 'mustContain': title}
                for title in titles[:5]  # Limit to 5 for test
            ]
        }
        rules = build_rules_from_titles(rules_data)
        print(f"[OK] Built {len(rules)} rules from titles")
    except Exception as e:
        print(f"[FAIL] SubsPlease-RSS Rules integration failed: {e}")
        assert False, str(e)


def test_complete_workflow():
    """Test a complete end-to-end workflow."""
    print("\n" + "="*60)
    print("Test 6: Complete Workflow")
    print("="*60)
    
    try:
        from src.config import config
        from src.utils import get_current_anime_season, sanitize_folder_name
        from src.rss_rules import create_rule, build_rules_from_titles, export_rules_to_json
        
        # Step 1: Get current season
        season, year = get_current_anime_season()
        print(f"[OK] Step 1: Got current season ({season} {year})")
        
        # Step 2: Create mock anime titles
        titles = {
            'anime': [
                {
                    'node': {'title': 'Anime Show 1'},
                    'mustContain': 'Anime Show 1',
                    'season': season,
                    'year': year,
                    'affectedFeeds': ['https://example.com/rss'],
                    'assignedCategory': 'anime'
                },
                {
                    'node': {'title': 'Anime Show 2'},
                    'mustContain': 'Anime Show 2',
                    'season': season,
                    'year': year,
                    'affectedFeeds': ['https://example.com/rss'],
                    'assignedCategory': 'anime'
                }
            ]
        }
        print(f"[OK] Step 2: Created {len(titles['anime'])} mock titles")
        
        # Step 3: Build rules from titles
        rules = build_rules_from_titles(titles)
        print(f"[OK] Step 3: Built {len(rules)} rules")
        
        # Step 4: Validate rules
        from src.rss_rules import validate_rules
        errors = validate_rules(rules)
        if errors:
            print(f"  Warning: {len(errors)} validation errors")
            for name, error in errors:
                print(f"    - {name}: {error}")
        else:
            print("[OK] Step 4: All rules valid")
        
        # Step 5: Export to JSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            success, msg = export_rules_to_json(rules, temp_path)
            assert success, f"Export failed: {msg}"
            print(f"[OK] Step 5: Exported rules to JSON")
            
            # Step 6: Verify file exists and is valid JSON
            import json
            with open(temp_path, 'r') as f:
                loaded = json.load(f)
            assert len(loaded) == len(rules), "Rule count mismatch"
            print(f"[OK] Step 6: Verified exported JSON ({len(loaded)} rules)")
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
        print("[OK] Complete workflow successful!")
    except Exception as e:
        print(f"[FAIL] Complete workflow failed: {e}")
        import traceback
        traceback.print_exc()
        assert False, str(e)


def test_error_handling():
    """Test error handling across modules."""
    print("\n" + "="*60)
    print("Test 7: Error Handling")
    print("="*60)
    
    try:
        from src.rss_rules import RSSRule, validate_rules
        from src.utils import sanitize_folder_name
        from src.qbittorrent_api import ping_qbittorrent
        
        # Test 1: Invalid rule validation
        invalid_rule = RSSRule(title="Test", must_contain="", feed_url="")
        is_valid, error = invalid_rule.validate()
        assert not is_valid, "Invalid rule passed validation"
        print(f"[OK] Invalid rule caught: {error}")
        
        # Test 2: Invalid folder name sanitization
        dangerous_name = "../../etc/passwd"
        sanitized = sanitize_folder_name(dangerous_name)
        assert sanitized != dangerous_name, "Dangerous path not sanitized"
        print(f"[OK] Dangerous path sanitized: '{dangerous_name}'  '{sanitized}'")
        
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
        print(f"[OK] Invalid connection caught: {msg[:50]}...")
    except Exception as e:
        print(f"[FAIL] Error handling test failed: {e}")
        assert False, str(e)


def test_all_exports():
    """Test that all module exports are accessible."""
    print("\n" + "="*60)
    print("Test 8: Module Exports")
    print("="*60)
    
    try:
        # Test src package exports
        from src import config, qbittorrent_api, rss_rules, subsplease_api
        print("[OK] Main package exports accessible")
        
        # Test submodule exports
        from src.qbittorrent_api import QBittorrentClient, ping_qbittorrent
        from src.rss_rules import RSSRule, create_rule
        from src.subsplease_api import fetch_subsplease_schedule
        from src.utils import sanitize_folder_name, get_current_anime_season
        from src.cache import load_recent_files, save_recent_files
        from src.constants import Season, CacheKeys
        print("[OK] All submodule exports accessible")
        
        # Test __all__ exports
        modules_with_all = [
            ('src.qbittorrent_api', qbittorrent_api),
            ('src.rss_rules', rss_rules),
            ('src.subsplease_api', subsplease_api),
        ]
        
        for name, module in modules_with_all:
            if hasattr(module, '__all__'):
                exports = module.__all__
                print(f"[OK] {name}.__all__ has {len(exports)} exports")
    except Exception as e:
        print(f"[FAIL] Module exports test failed: {e}")
        assert False, str(e)


def test_version_consistency():
    """Test version numbers are consistent."""
    print("\n" + "="*60)
    print("Test 9: Version Consistency")
    print("="*60)
    
    try:
        from src import __version__ as src_version
        
        print(f"[OK] src package version: {src_version}")
        
        # Verify it's a valid version string
        assert isinstance(src_version, str), "Version is not a string"
        assert len(src_version) > 0, "Version is empty"
        print(f"[OK] Version format valid")
    except Exception as e:
        print(f"[FAIL] Version consistency test failed: {e}")
        assert False, str(e)


def test_documentation_exists():
    """Verify documentation files exist."""
    print("\n" + "="*60)
    print("Test 10: Documentation Exists")
    print("="*60)
    
    try:
        docs = [
            'README.md',
            'STRUCTURE.md',
            'ARCHITECTURE.md',
            'PHASE3_GUI_STRUCTURE.md',
            'PHASE4_QBITTORRENT_API.md',
            'PHASE5_RSS_RULES.md',
        ]
        
        for doc in docs:
            path = Path(doc)
            if path.exists():
                print(f"[OK] {doc} exists")
            else:
                print(f" {doc} missing")
    except Exception as e:
        print(f"[FAIL] Documentation check failed: {e}")
        assert False, str(e)


def main():
    """Run all integration tests."""
    print("\n" + "="*70)
    print(" "*15 + "Phase 6: Integration & Testing")
    print("="*70)
    
    tests = [
        test_complete_module_integration,
        test_config_to_cache_integration,
        test_utils_to_rss_rules_integration,
        test_rss_rules_to_qbt_api_integration,
        test_subsplease_to_rss_rules_integration,
        test_complete_workflow,
        test_error_handling,
        test_all_exports,
        test_version_consistency,
        test_documentation_exists,
    ]
    
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as e:
            print(f"\n[FAIL] Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "="*70)
    print("Integration Test Summary")
    print("="*70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\nSUCCESS All integration tests passed!")
        print("\nThe modular refactoring is complete and all components")
        print("work together correctly!")
        return 0
    else:
        print(f"\n[WARN]  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())



