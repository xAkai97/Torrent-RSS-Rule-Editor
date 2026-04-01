"""
Test script for Phase 5: RSS Rules Management Module

This script validates the RSS rules management functionality.
"""
import sys
import logging
import tempfile
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def test_rss_rules_imports():
    """Test that RSS rules module imports correctly."""
    print("\n" + "="*60)
    print("Test 1: RSS Rules Module Imports")
    print("="*60)
    
    try:
        from src import rss_rules
        print("[OK] src.rss_rules imported")
        
        from src.rss_rules import (
            RSSRule,
            create_rule,
            build_save_path,
            parse_title_metadata,
            build_rules_from_titles,
            export_rules_to_json,
            import_rules_from_json,
            validate_rules,
            sanitize_rules
        )
        print("[OK] All RSS rules components imported")
    except ImportError as e:
        print(f"[FAIL] Import failed: {e}")
        assert False, str(e)


def test_rss_rule_creation():
    """Test RSSRule class instantiation."""
    print("\n" + "="*60)
    print("Test 2: RSSRule Creation")
    print("="*60)
    
    try:
        from src.rss_rules import RSSRule, create_rule
        
        # Create a rule manually
        rule1 = RSSRule(
            title="Test Anime",
            must_contain="Test Anime",
            save_path="/downloads/anime/Test Anime",
            feed_url="https://example.com/rss",
            category="anime"
        )
        print(f"[OK] Rule created: {rule1.title}")
        print(f"  Must contain: {rule1.must_contain}")
        print(f"  Save path: {rule1.save_path}")
        print(f"  Feed: {rule1.feed_url}")
        
        # Create using helper function
        rule2 = create_rule(
            title="Another Show",
            save_path="/downloads/anime/Another Show"
        )
        print(f"[OK] Rule created via helper: {rule2.title}")
    except Exception as e:
        print(f"[FAIL] Rule creation failed: {e}")
        assert False, str(e)


def test_rule_to_dict():
    """Test converting rule to dictionary."""
    print("\n" + "="*60)
    print("Test 3: Rule to Dictionary Conversion")
    print("="*60)
    
    try:
        from src.rss_rules import RSSRule
        
        rule = RSSRule(
            title="Test Show",
            must_contain="Test Show 1080p",
            save_path="/anime/Test Show",
            feed_url="https://example.com/rss",
            category="anime"
        )
        
        rule_dict = rule.to_dict()
        
        # Verify key fields
        assert rule_dict['mustContain'] == "Test Show 1080p", "mustContain mismatch"
        assert rule_dict['savePath'] == "/anime/Test Show", "savePath mismatch"
        assert rule_dict['assignedCategory'] == "anime", "category mismatch"
        assert rule_dict['affectedFeeds'] == ["https://example.com/rss"], "feeds mismatch"
        assert rule_dict['enabled'] == True, "enabled mismatch"
        assert 'torrentParams' in rule_dict, "torrentParams missing"
        
        print("[OK] Rule converted to dict successfully")
        print(f"  Keys: {len(rule_dict)} top-level fields")
        print(f"  torrentParams keys: {len(rule_dict['torrentParams'])}")
    except Exception as e:
        print(f"[FAIL] Rule to dict failed: {e}")
        assert False, str(e)


def test_rule_from_dict():
    """Test creating rule from dictionary."""
    print("\n" + "="*60)
    print("Test 4: Rule from Dictionary")
    print("="*60)
    
    try:
        from src.rss_rules import RSSRule
        
        rule_dict = {
            'mustContain': 'My Anime',
            'savePath': '/downloads/anime',
            'affectedFeeds': ['https://test.com/rss'],
            'assignedCategory': 'anime',
            'enabled': True,
            'addPaused': False,
            'useRegex': False,
            'torrentParams': {
                'category': 'anime',
                'save_path': '/downloads/anime'
            }
        }
        
        rule = RSSRule.from_dict('My Anime', rule_dict)
        
        assert rule.title == 'My Anime', "Title mismatch"
        assert rule.must_contain == 'My Anime', "must_contain mismatch"
        assert rule.save_path == '/downloads/anime', "save_path mismatch"
        assert rule.feed_url == 'https://test.com/rss', "feed_url mismatch"
        assert rule.category == 'anime', "category mismatch"
        
        print("[OK] Rule created from dictionary")
        print(f"  Title: {rule.title}")
        print(f"  Category: {rule.category}")
    except Exception as e:
        print(f"[FAIL] Rule from dict failed: {e}")
        assert False, str(e)


def test_save_path_building():
    """Test save path generation."""
    print("\n" + "="*60)
    print("Test 5: Save Path Building")
    print("="*60)
    
    try:
        from src.rss_rules import build_save_path
        
        # Test without season/year
        path1 = build_save_path("Test Anime")
        print(f"[OK] Simple path: {path1}")
        
        # Test with season/year
        path2 = build_save_path("Test Anime", "Winter", "2025")
        print(f"[OK] Seasonal path: {path2}")
        
        # Verify forward slashes
        assert '\\' not in path2, "Path contains backslashes"
        print("[OK] Paths use forward slashes")
    except Exception as e:
        print(f"[FAIL] Save path building failed: {e}")
        assert False, str(e)


def test_rules_from_titles():
    """Test building rules from titles dictionary."""
    print("\n" + "="*60)
    print("Test 6: Build Rules from Titles")
    print("="*60)
    
    try:
        from src.rss_rules import build_rules_from_titles
        
        titles = {
            'anime': [
                {
                    'node': {'title': 'Anime Show 1'},
                    'mustContain': 'Anime Show 1',
                    'season': 'Winter',
                    'year': '2025',
                    'affectedFeeds': ['https://example.com/rss'],
                    'assignedCategory': 'anime'
                },
                {
                    'node': {'title': 'Anime Show 2'},
                    'mustContain': 'Anime Show 2',
                    'affectedFeeds': ['https://example.com/rss']
                }
            ]
        }
        
        rules = build_rules_from_titles(titles, 'https://default.com/rss')
        
        assert len(rules) == 2, f"Expected 2 rules, got {len(rules)}"
        assert 'Anime Show 1' in rules, "Rule 1 missing"
        assert 'Anime Show 2' in rules, "Rule 2 missing"
        
        print(f"[OK] Built {len(rules)} rules from titles")
        for name in rules.keys():
            print(f"  - {name}")
    except Exception as e:
        print(f"[FAIL] Build rules from titles failed: {e}")
        assert False, str(e)


def test_export_import_json():
    """Test exporting and importing rules as JSON."""
    print("\n" + "="*60)
    print("Test 7: Export/Import JSON")
    print("="*60)
    
    try:
        from src.rss_rules import (
            create_rule,
            export_rules_to_json,
            import_rules_from_json
        )
        
        # Create test rules
        rule1 = create_rule("Test 1", save_path="/test1")
        rule2 = create_rule("Test 2", save_path="/test2")
        
        rules = {
            'Test 1': rule1.to_dict(),
            'Test 2': rule2.to_dict()
        }
        
        # Export to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            success, msg = export_rules_to_json(rules, temp_path)
            assert success, f"Export failed: {msg}"
            print(f"[OK] Exported rules to {temp_path}")
            
            # Import back
            success, imported = import_rules_from_json(temp_path)
            assert success, f"Import failed: {imported}"
            assert len(imported) == 2, f"Expected 2 rules, got {len(imported)}"
            print(f"[OK] Imported {len(imported)} rules")
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
    except Exception as e:
        print(f"[FAIL] Export/Import failed: {e}")
        assert False, str(e)


def test_rule_validation():
    """Test rule validation."""
    print("\n" + "="*60)
    print("Test 8: Rule Validation")
    print("="*60)
    
    try:
        from src.rss_rules import RSSRule, validate_rules
        
        # Valid rule
        valid_rule = RSSRule(
            title="Valid Rule",
            must_contain="Valid Rule",
            feed_url="https://example.com/rss"
        )
        is_valid, msg = valid_rule.validate()
        assert is_valid, f"Valid rule marked invalid: {msg}"
        print(f"[OK] Valid rule passed: {msg}")
        
        # Invalid rule (no feed)
        invalid_rule = RSSRule(
            title="Invalid Rule",
            must_contain="Invalid Rule",
            feed_url=""  # Missing!
        )
        is_valid, msg = invalid_rule.validate()
        assert not is_valid, "Invalid rule marked valid"
        print(f"[OK] Invalid rule detected: {msg}")
        
        # Validate multiple rules
        rules_dict = {
            'Valid': valid_rule.to_dict(),
            'Invalid': invalid_rule.to_dict()
        }
        errors = validate_rules(rules_dict)
        assert len(errors) == 1, f"Expected 1 error, got {len(errors)}"
        print(f"[OK] Batch validation found {len(errors)} error(s)")
    except Exception as e:
        print(f"[FAIL] Validation failed: {e}")
        assert False, str(e)


def test_rule_sanitization():
    """Test rule sanitization."""
    print("\n" + "="*60)
    print("Test 9: Rule Sanitization")
    print("="*60)
    
    try:
        from src.rss_rules import sanitize_rules
        
        rules = {
            'Test Show': {
                'mustContain': 'Test: Show? <Invalid>',
                'savePath': 'path/with\\backslashes',
                'affectedFeeds': ['https://test.com/rss'],
                'assignedCategory': '',
                'enabled': True,
                'torrentParams': {}
            }
        }
        
        sanitized = sanitize_rules(rules)
        
        # Check mustContain was sanitized
        must_contain = sanitized['Test Show']['mustContain']
        assert ':' not in must_contain, "Colon not removed"
        assert '?' not in must_contain, "Question mark not removed"
        assert '<' not in must_contain, "< not removed"
        print(f"[OK] Sanitized mustContain: '{must_contain}'")
        
        # Check path uses forward slashes
        save_path = sanitized['Test Show']['savePath']
        assert '\\' not in save_path, "Backslashes not converted"
        print(f"[OK] Sanitized savePath: '{save_path}'")
    except Exception as e:
        print(f"[FAIL] Sanitization failed: {e}")
        assert False, str(e)


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print(" "*15 + "Phase 5: RSS Rules Management Tests")
    print("="*70)
    
    tests = [
        test_rss_rules_imports,
        test_rss_rule_creation,
        test_rule_to_dict,
        test_rule_from_dict,
        test_save_path_building,
        test_rules_from_titles,
        test_export_import_json,
        test_rule_validation,
        test_rule_sanitization
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
    print("Test Summary")
    print("="*70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\nSUCCESS All Phase 5 tests passed!")
        return 0
    else:
        print(f"\n[WARN]  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())



