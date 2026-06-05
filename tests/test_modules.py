#!/usr/bin/env python
"""
Test script to verify core module behavior.

Run this to check if all modules can be imported and basic functions work.
"""
import sys


def test_imports():
    """Test that all modules can be imported."""
    print("Testing module imports...")
    
    from src import constants, config, cache, utils
    from src.api import subsplease as subsplease_api
    print("âœ… All core modules imported successfully")


def test_constants():
    """Test constants module."""
    print("\nTesting constants module...")
    
    try:
        from src.constants import Season, CacheKeys, FileSystem
        
        assert Season.WINTER == "Winter"
        assert Season.FALL == "Fall"
        assert CacheKeys.RECENT_FILES == 'recent_files'
        assert '<' in FileSystem.INVALID_CHARS
        
        print("âœ… Constants module works correctly")
    except Exception as e:
        print(f"âŒ Constants test failed: {e}")
        assert False, str(e)


def test_config():
    """Test config module."""
    print("\nTesting config module...")
    
    try:
        from src.config import config
        
        assert hasattr(config, 'CONFIG_FILE')
        assert hasattr(config, 'DEFAULT_RSS_FEED')
        assert hasattr(config, 'get_pref')
        assert hasattr(config, 'set_pref')
        
        print("âœ… Config module works correctly")
    except Exception as e:
        print(f"âŒ Config test failed: {e}")
        assert False, str(e)


def test_utils():
    """Test utils module."""
    print("\nTesting utils module...")
    
    try:
        from src.utils import get_current_anime_season, sanitize_folder_name
        from src.config import config
        
        season, year = get_current_anime_season()
        assert season in ["Winter", "Spring", "Summer", "Fall"]
        assert len(year) == 4
        
        # Force deterministic sanitization behavior regardless of local prefs.
        config.set_pref('filesystem_type', 'windows')
        sanitized = sanitize_folder_name("Test<>Title")
        assert '<' not in sanitized
        assert '>' not in sanitized
        
        print(f"âœ… Utils module works correctly (Current: {season} {year})")
    except Exception as e:
        print(f"âŒ Utils test failed: {e}")
        assert False, str(e)


def test_cache():
    """Test cache module."""
    print("\nTesting cache module...")
    
    try:
        from src.cache import load_prefs, get_pref
        
        prefs = load_prefs()
        assert isinstance(prefs, dict)
        
        # Test get_pref with default
        value = get_pref('nonexistent_key', 'default_value')
        assert value == 'default_value'
        
        print("âœ… Cache module works correctly")
    except Exception as e:
        print(f"âŒ Cache test failed: {e}")
        assert False, str(e)


def test_subsplease():
    """Test SubsPlease API module."""
    print("\nTesting SubsPlease API module...")
    
    try:
        from src.api.subsplease import load_subsplease_cache
        
        cached = load_subsplease_cache()
        assert isinstance(cached, dict)
        
        print(f"âœ… SubsPlease module works (Cache: {len(cached)} titles)")
    except Exception as e:
        print(f"âŒ SubsPlease test failed: {e}")
        assert False, str(e)


def main():
    """Run all tests."""
    print("=" * 60)
    print("qBittorrent RSS Rule Editor - Module Test")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_constants,
        test_config,
        test_utils,
        test_cache,
        test_subsplease,
    ]
    
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as e:
            print(f"âŒ Test crashed: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("\nAll tests passed!")
        return 0
    else:
        print(f"\nâš ï¸  {total - passed} test(s) failed. Check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

