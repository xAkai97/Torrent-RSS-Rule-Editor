"""
Test script for internal field filtering logic and title entry helpers.

This script validates that:
1. Internal tracking fields ('node', 'ruleName') are properly filtered out
2. Title entry helper functions work correctly
3. qBittorrent fields are preserved after filtering

See config.py ALL_TITLES and src/utils.py for the hybrid format documentation.
"""
import sys
import os
import logging
import json

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Import centralized helper functions
from src.utils import (
    strip_internal_fields,
    strip_internal_fields_from_titles,
    get_display_title,
    get_rule_name,
    get_must_contain,
    create_title_entry,
    find_entry_by_title,
    is_duplicate_title,
    validate_entry_structure,
    validate_entries_for_export,
    sanitize_entry_for_export,
    INTERNAL_FIELDS,
    VALID_QBT_FIELDS
)

# Expected qBittorrent fields that should be preserved
QBITTORRENT_FIELDS = [
    'mustContain', 'mustNotContain', 'savePath', 'assignedCategory',
    'enabled', 'affectedFeeds', 'torrentParams', 'addPaused',
    'episodeFilter', 'ignoreDays', 'lastMatch', 'previouslyMatchedEpisodes',
    'priority', 'smartFilter', 'torrentContentLayout', 'useRegex'
]

def test_strip_internal_fields_basic():
    """Test that internal fields are removed from a simple entry."""
    print("\n" + "="*60)
    print("Test 1: Basic Internal Field Filtering")
    print("="*60)
    
    # Entry with both qBittorrent and internal fields
    entry = {
        'mustContain': 'Test Anime',
        'savePath': '/downloads/anime/Test Anime',
        'assignedCategory': 'anime',
        'enabled': True,
        'affectedFeeds': ['https://example.com/rss'],
        'torrentParams': {'category': 'anime'},
        # Internal tracking fields (should be filtered)
        'node': {'title': 'Test Anime Display Title'},
        'ruleName': 'Test Anime'
    }
    
    filtered = strip_internal_fields(entry)
    
    # Verify internal fields are removed
    assert 'node' not in filtered, "Internal field 'node' was not filtered"
    assert 'ruleName' not in filtered, "Internal field 'ruleName' was not filtered"
    
    # Verify qBittorrent fields are preserved
    assert filtered['mustContain'] == 'Test Anime', "mustContain was modified"
    assert filtered['savePath'] == '/downloads/anime/Test Anime', "savePath was modified"
    assert filtered['assignedCategory'] == 'anime', "assignedCategory was modified"
    assert filtered['enabled'] == True, "enabled was modified"
    assert filtered['affectedFeeds'] == ['https://example.com/rss'], "affectedFeeds was modified"
    assert filtered['torrentParams'] == {'category': 'anime'}, "torrentParams was modified"
    
    print("[OK] Internal fields ('node', 'ruleName') properly removed")
    print("[OK] All qBittorrent fields preserved")
def test_strip_internal_fields_empty_entry():
    """Test filtering an empty entry."""
    print("\n" + "="*60)
    print("Test 2: Empty Entry Filtering")
    print("="*60)
    
    try:
        entry = {}
        filtered = strip_internal_fields(entry)
        
        assert filtered == {}, "Empty entry should remain empty"
        print("[OK] Empty entry handled correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_strip_internal_fields_only_internal():
    """Test filtering an entry with only internal fields."""
    print("\n" + "="*60)
    print("Test 3: Only Internal Fields Entry")
    print("="*60)
    
    try:
        entry = {
            'node': {'title': 'Test'},
            'ruleName': 'Test'
        }
        filtered = strip_internal_fields(entry)
        
        assert filtered == {}, "Entry with only internal fields should become empty"
        print("[OK] Entry with only internal fields properly emptied")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_strip_internal_fields_only_qbt():
    """Test filtering an entry with only qBittorrent fields (no change expected)."""
    print("\n" + "="*60)
    print("Test 4: Only qBittorrent Fields Entry")
    print("="*60)
    
    try:
        entry = {
            'mustContain': 'Clean Entry',
            'savePath': '/downloads/clean',
            'enabled': True
        }
        filtered = strip_internal_fields(entry)
        
        assert filtered == entry, "Entry without internal fields should be unchanged"
        print("[OK] Clean entry preserved without modification")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_strip_internal_fields_non_dict():
    """Test filtering non-dict entries (should return as-is)."""
    print("\n" + "="*60)
    print("Test 5: Non-Dictionary Entry Handling")
    print("="*60)
    
    try:
        # String entry
        assert strip_internal_fields("test string") == "test string", "String should pass through"
        
        # List entry
        assert strip_internal_fields([1, 2, 3]) == [1, 2, 3], "List should pass through"
        
        # None
        assert strip_internal_fields(None) is None, "None should pass through"
        
        print("[OK] Non-dict entries handled correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_filter_all_titles_structure():
    """Test filtering the full ALL_TITLES structure."""
    print("\n" + "="*60)
    print("Test 6: Full ALL_TITLES Structure Filtering")
    print("="*60)
    
    try:
        # Simulate config.ALL_TITLES structure
        all_titles = {
            'existing': [
                {
                    'mustContain': 'Existing Show',
                    'savePath': '/downloads/existing',
                    'assignedCategory': 'anime',
                    'enabled': True,
                    'affectedFeeds': ['https://feed.url'],
                    'torrentParams': {},
                    'node': {'title': 'Existing Show'},
                    'ruleName': 'Existing Show'
                },
                {
                    'mustContain': 'Another Show',
                    'savePath': '/downloads/another',
                    'node': {'title': 'Another Display Name'},
                    'ruleName': 'Another Show'
                }
            ],
            'anime': [
                {
                    'mustContain': 'New Anime',
                    'savePath': '/downloads/new',
                    'node': {'title': 'New Anime'},
                    'ruleName': 'New Anime'
                }
            ]
        }
        
        # Apply filtering (same logic as file_operations.py)
        clean_titles = {}
        for media_type, items in all_titles.items():
            clean_items = []
            for item in items:
                if isinstance(item, dict):
                    clean_item = strip_internal_fields(item)
                    clean_items.append(clean_item)
                else:
                    clean_items.append(item)
            clean_titles[media_type] = clean_items
        
        # Verify structure
        assert 'existing' in clean_titles, "existing media type missing"
        assert 'anime' in clean_titles, "anime media type missing"
        assert len(clean_titles['existing']) == 2, "Wrong number of existing items"
        assert len(clean_titles['anime']) == 1, "Wrong number of anime items"
        
        # Verify no internal fields in any entry
        for media_type, items in clean_titles.items():
            for item in items:
                assert 'node' not in item, f"'node' found in {media_type} entry"
                assert 'ruleName' not in item, f"'ruleName' found in {media_type} entry"
        
        # Verify qBittorrent fields preserved
        assert clean_titles['existing'][0]['mustContain'] == 'Existing Show'
        assert clean_titles['existing'][0]['savePath'] == '/downloads/existing'
        assert clean_titles['anime'][0]['mustContain'] == 'New Anime'
        
        print("[OK] Full ALL_TITLES structure filtered correctly")
        print("[OK] All internal fields removed from all entries")
        print("[OK] All qBittorrent fields preserved")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        assert False, "Test reported failure"
def test_filtered_output_is_valid_json():
    """Test that filtered output can be serialized to valid JSON."""
    print("\n" + "="*60)
    print("Test 7: JSON Serialization of Filtered Output")
    print("="*60)
    
    try:
        entry = {
            'mustContain': 'Test Show',
            'savePath': '/downloads/test',
            'assignedCategory': 'anime',
            'enabled': True,
            'affectedFeeds': ['https://example.com/rss'],
            'torrentParams': {
                'category': 'anime',
                'save_path': '/downloads/test',
                'download_limit': -1,
                'upload_limit': -1
            },
            'node': {'title': 'Test Show Display'},
            'ruleName': 'Test Show'
        }
        
        filtered = strip_internal_fields(entry)
        
        # Attempt JSON serialization
        json_str = json.dumps(filtered, indent=2, ensure_ascii=False)
        
        # Verify we can parse it back
        parsed = json.loads(json_str)
        
        # Verify parsed data matches filtered
        assert parsed == filtered, "Parsed JSON does not match filtered data"
        
        # Verify no internal fields in JSON output
        assert 'node' not in json_str, "'node' found in JSON output"
        assert 'ruleName' not in json_str, "'ruleName' found in JSON output"
        
        print("[OK] Filtered output successfully serialized to JSON")
        print("[OK] JSON can be parsed back correctly")
        print("[OK] No internal fields in JSON string")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
    except json.JSONDecodeError as e:
        print(f"[FAIL] JSON serialization failed: {e}")
        assert False, "Test reported failure"
def test_nested_node_structure():
    """Test that nested 'node' structure with various data is handled."""
    print("\n" + "="*60)
    print("Test 8: Nested Node Structure Handling")
    print("="*60)
    
    try:
        # Complex node structure
        entry = {
            'mustContain': 'Complex Entry',
            'savePath': '/downloads/complex',
            'node': {
                'title': 'Complex Entry',
                'media_type': 'anime',
                'extra_data': {
                    'year': 2025,
                    'season': 'Fall'
                }
            },
            'ruleName': 'Complex Entry Rule Name'
        }
        
        filtered = strip_internal_fields(entry)
        
        # Entire node should be removed
        assert 'node' not in filtered, "Complex 'node' structure was not filtered"
        assert 'ruleName' not in filtered, "'ruleName' was not filtered"
        
        # qBittorrent fields preserved
        assert filtered['mustContain'] == 'Complex Entry'
        assert filtered['savePath'] == '/downloads/complex'
        
        print("[OK] Complex nested 'node' structure properly removed")
        print("[OK] qBittorrent fields preserved")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_integration_with_build_rules():
    """Test filtering integration with build_rules_from_titles."""
    print("\n" + "="*60)
    print("Test 9: Integration with build_rules_from_titles")
    print("="*60)
    
    try:
        from src.rss_rules import build_rules_from_titles
        
        # Simulate pre-filtered data (as it would be passed to build_rules_from_titles)
        clean_titles = {
            'anime': [
                {
                    'mustContain': 'Integration Test Show',
                    'savePath': '/downloads/integration',
                    'assignedCategory': 'anime',
                    'enabled': True,
                    'affectedFeeds': ['https://example.com/rss']
                }
            ]
        }
        
        # Build rules from clean data
        rules = build_rules_from_titles(clean_titles)
        
        # Verify rules are built correctly
        assert len(rules) > 0, "No rules were built"
        
        # Get the first rule
        rule_name = list(rules.keys())[0]
        rule_data = rules[rule_name]
        
        # Verify no internal fields in output
        assert 'node' not in rule_data, "'node' found in built rule"
        assert 'ruleName' not in rule_data, "'ruleName' found in built rule"
        
        # Verify expected qBittorrent fields
        assert 'mustContain' in rule_data, "mustContain missing from built rule"
        assert 'savePath' in rule_data, "savePath missing from built rule"
        assert 'affectedFeeds' in rule_data, "affectedFeeds missing from built rule"
        
        print("[OK] build_rules_from_titles works with filtered data")
        print("[OK] Output contains no internal fields")
        print("[OK] Output contains expected qBittorrent fields")
    except ImportError as e:
        print(f"[FAIL] Import failed: {e}")
        assert False, "Test reported failure"
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        assert False, "Test reported failure"
# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================

def test_get_display_title():
    """Test get_display_title helper function."""
    print("\n" + "="*60)
    print("Test 10: get_display_title Helper")
    print("="*60)
    
    try:
        # Test with node.title
        entry1 = {'node': {'title': 'Display Title'}, 'mustContain': 'Search Pattern'}
        assert get_display_title(entry1) == 'Display Title', "Should use node.title first"
        
        # Test without node, fallback to title
        entry2 = {'title': 'Direct Title', 'mustContain': 'Pattern'}
        assert get_display_title(entry2) == 'Direct Title', "Should fallback to title"
        
        # Test without node or title, fallback to mustContain
        entry3 = {'mustContain': 'Pattern Only'}
        assert get_display_title(entry3) == 'Pattern Only', "Should fallback to mustContain"
        
        # Test with string
        assert get_display_title('String Entry') == 'String Entry', "Should handle strings"
        
        # Test with empty/None
        assert get_display_title(None, 'fallback') == 'fallback', "Should use fallback for None"
        assert get_display_title({}, 'fallback') == 'fallback', "Should use fallback for empty dict"
        
        print("[OK] get_display_title works correctly for all cases")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_get_rule_name():
    """Test get_rule_name helper function."""
    print("\n" + "="*60)
    print("Test 11: get_rule_name Helper")
    print("="*60)
    
    try:
        # Test with explicit ruleName
        entry1 = {'ruleName': 'My Rule', 'node': {'title': 'Display'}}
        assert get_rule_name(entry1) == 'My Rule', "Should use ruleName first"
        
        # Test with name field
        entry2 = {'name': 'Named Rule', 'node': {'title': 'Display'}}
        assert get_rule_name(entry2) == 'Named Rule', "Should fallback to name"
        
        # Test fallback to display title
        entry3 = {'node': {'title': 'Display Title'}}
        assert get_rule_name(entry3) == 'Display Title', "Should fallback to node.title"
        
        # Test with string
        assert get_rule_name('String Entry') == 'String Entry', "Should handle strings"
        
        print("[OK] get_rule_name works correctly for all cases")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_create_title_entry():
    """Test create_title_entry helper function."""
    print("\n" + "="*60)
    print("Test 12: create_title_entry Helper")
    print("="*60)
    
    try:
        # Create a basic entry
        entry = create_title_entry(
            display_title='My Show',
            save_path='/downloads/my-show',
            category='anime'
        )
        
        # Verify structure
        assert entry['node']['title'] == 'My Show', "node.title should be set"
        assert entry['ruleName'] == 'My Show', "ruleName should default to display_title"
        assert entry['mustContain'] == 'My Show', "mustContain should default to display_title"
        assert entry['savePath'] == '/downloads/my-show', "savePath should be set"
        assert entry['assignedCategory'] == 'anime', "assignedCategory should be set"
        assert entry['enabled'] == True, "enabled should default to True"
        
        # Create with custom must_contain and rule_name
        entry2 = create_title_entry(
            display_title='Display Name',
            must_contain='Search Pattern',
            rule_name='Custom Rule'
        )
        
        assert entry2['node']['title'] == 'Display Name', "node.title should match display_title"
        assert entry2['mustContain'] == 'Search Pattern', "mustContain should use custom value"
        assert entry2['ruleName'] == 'Custom Rule', "ruleName should use custom value"
        
        print("[OK] create_title_entry creates properly structured entries")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_find_entry_by_title():
    """Test find_entry_by_title helper function."""
    print("\n" + "="*60)
    print("Test 13: find_entry_by_title Helper")
    print("="*60)
    
    try:
        titles = {
            'anime': [
                {'node': {'title': 'Show A'}, 'mustContain': 'Show A'},
                {'node': {'title': 'Show B'}, 'mustContain': 'Show B'}
            ],
            'existing': [
                {'node': {'title': 'Existing Show'}, 'mustContain': 'Existing'}
            ]
        }
        
        # Find existing entry
        result = find_entry_by_title(titles, 'Show B')
        assert result is not None, "Should find existing entry"
        assert result[0] == 'anime', "Should return correct media type"
        assert result[1] == 1, "Should return correct index"
        
        # Case-insensitive search
        result2 = find_entry_by_title(titles, 'show b', case_sensitive=False)
        assert result2 is not None, "Should find with case-insensitive search"
        
        # Case-sensitive search (should not find)
        result3 = find_entry_by_title(titles, 'show b', case_sensitive=True)
        assert result3 is None, "Should not find with case-sensitive search"
        
        # Non-existent entry
        result4 = find_entry_by_title(titles, 'Non Existent')
        assert result4 is None, "Should return None for non-existent entry"
        
        print("[OK] find_entry_by_title works correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_is_duplicate_title():
    """Test is_duplicate_title helper function."""
    print("\n" + "="*60)
    print("Test 14: is_duplicate_title Helper")
    print("="*60)
    
    try:
        titles = {
            'anime': [
                {'node': {'title': 'Unique Show'}, 'mustContain': 'Unique Show'}
            ]
        }
        
        # Check existing title
        assert is_duplicate_title(titles, 'Unique Show') == True, "Should detect duplicate"
        
        # Check non-existing title
        assert is_duplicate_title(titles, 'New Show') == False, "Should not be duplicate"
        
        # Case-insensitive check
        assert is_duplicate_title(titles, 'unique show', case_sensitive=False) == True, "Should detect case-insensitive duplicate"
        
        print("[OK] is_duplicate_title works correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_strip_internal_fields_from_titles():
    """Test strip_internal_fields_from_titles helper function."""
    print("\n" + "="*60)
    print("Test 15: strip_internal_fields_from_titles Helper")
    print("="*60)
    
    try:
        titles = {
            'anime': [
                {'node': {'title': 'Show'}, 'ruleName': 'Show', 'mustContain': 'Show', 'savePath': '/path'}
            ],
            'existing': [
                {'node': {'title': 'Old'}, 'ruleName': 'Old', 'enabled': True}
            ]
        }
        
        clean = strip_internal_fields_from_titles(titles)
        
        # Verify internal fields removed
        assert 'node' not in clean['anime'][0], "node should be removed"
        assert 'ruleName' not in clean['anime'][0], "ruleName should be removed"
        assert 'node' not in clean['existing'][0], "node should be removed from existing"
        
        # Verify qBT fields preserved
        assert clean['anime'][0]['mustContain'] == 'Show', "mustContain should be preserved"
        assert clean['anime'][0]['savePath'] == '/path', "savePath should be preserved"
        assert clean['existing'][0]['enabled'] == True, "enabled should be preserved"
        
        print("[OK] strip_internal_fields_from_titles works correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
# ============================================================================
# VALIDATION TESTS
# ============================================================================

def test_validate_entry_structure():
    """Test validate_entry_structure function."""
    print("\n" + "="*60)
    print("Test 16: validate_entry_structure")
    print("="*60)
    
    try:
        # Valid entry with only known fields
        valid_entry = {
            'mustContain': 'Test',
            'savePath': '/path',
            'node': {'title': 'Test'},
            'ruleName': 'Test'
        }
        is_valid, warnings = validate_entry_structure(valid_entry)
        assert is_valid, "Valid entry should pass validation"
        assert len(warnings) == 0, "Valid entry should have no warnings"
        
        # Entry with unknown field (potential pollution)
        polluted_entry = {
            'mustContain': 'Test',
            'unknownField': 'bad data',
            'anotherBadField': 123
        }
        is_valid, warnings = validate_entry_structure(polluted_entry)
        assert not is_valid, "Polluted entry should fail validation"
        assert len(warnings) >= 2, "Should have warnings for unknown fields"
        
        # Entry with malformed node (not a dict)
        bad_node_entry = {
            'mustContain': 'Test',
            'node': 'should be a dict'
        }
        is_valid, warnings = validate_entry_structure(bad_node_entry)
        assert not is_valid, "Entry with bad node should fail"
        
        # Non-dict entry should pass (strings are allowed)
        is_valid, warnings = validate_entry_structure("simple string")
        assert is_valid, "String entries should be valid"
        
        print("[OK] validate_entry_structure correctly detects issues")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_validate_entries_for_export():
    """Test validate_entries_for_export function."""
    print("\n" + "="*60)
    print("Test 17: validate_entries_for_export")
    print("="*60)
    
    try:
        # Valid titles structure
        valid_titles = {
            'anime': [
                {'mustContain': 'Show A', 'node': {'title': 'Show A'}},
                {'mustContain': 'Show B', 'enabled': True}
            ]
        }
        is_valid, warnings = validate_entries_for_export(valid_titles)
        assert is_valid, "Valid titles should pass"
        assert len(warnings) == 0, "Should have no warnings"
        
        # Titles with pollution
        polluted_titles = {
            'anime': [
                {'mustContain': 'Show', 'badField': 'pollution'}
            ]
        }
        is_valid, warnings = validate_entries_for_export(polluted_titles)
        assert not is_valid, "Polluted titles should fail"
        assert any('badField' in w for w in warnings), "Should warn about badField"
        
        print("[OK] validate_entries_for_export works correctly")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def test_sanitize_entry_for_export():
    """Test sanitize_entry_for_export function."""
    print("\n" + "="*60)
    print("Test 18: sanitize_entry_for_export")
    print("="*60)
    
    try:
        # Entry with pollution
        polluted_entry = {
            'mustContain': 'Test Show',
            'savePath': '/downloads/test',
            'enabled': True,
            'node': {'title': 'Test'},  # Internal - should be removed
            'ruleName': 'Test',  # Internal - should be removed
            'unknownField': 'bad',  # Unknown - should be removed
            'randomData': 123,  # Unknown - should be removed
            'torrentParams': {
                'category': 'anime',
                'badSubField': 'pollution'  # Unknown - should be removed
            }
        }
        
        sanitized = sanitize_entry_for_export(polluted_entry)
        
        # Check valid fields are preserved
        assert sanitized['mustContain'] == 'Test Show', "mustContain should be preserved"
        assert sanitized['savePath'] == '/downloads/test', "savePath should be preserved"
        assert sanitized['enabled'] == True, "enabled should be preserved"
        
        # Check internal fields are removed
        assert 'node' not in sanitized, "node should be removed"
        assert 'ruleName' not in sanitized, "ruleName should be removed"
        
        # Check unknown fields are removed
        assert 'unknownField' not in sanitized, "unknownField should be removed"
        assert 'randomData' not in sanitized, "randomData should be removed"
        
        # Check torrentParams is sanitized
        assert 'torrentParams' in sanitized, "torrentParams should be preserved"
        assert sanitized['torrentParams']['category'] == 'anime', "Valid sub-field preserved"
        assert 'badSubField' not in sanitized['torrentParams'], "Bad sub-field removed"
        
        print("[OK] sanitize_entry_for_export removes all pollution")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
        assert False, "Test reported failure"
def run_all_tests():
    """Run all filtering tests and report results."""
    print("\n" + "="*60)
    print("INTERNAL FIELD FILTERING & HELPERS TEST SUITE")
    print("="*60)
    print("\nTests validate filtering logic and title entry helper functions.")
    
    tests = [
        # Original filtering tests
        test_strip_internal_fields_basic,
        test_strip_internal_fields_empty_entry,
        test_strip_internal_fields_only_internal,
        test_strip_internal_fields_only_qbt,
        test_strip_internal_fields_non_dict,
        test_filter_all_titles_structure,
        test_filtered_output_is_valid_json,
        test_nested_node_structure,
        test_integration_with_build_rules,
        # Helper function tests
        test_get_display_title,
        test_get_rule_name,
        test_create_title_entry,
        test_find_entry_by_title,
        test_is_duplicate_title,
        test_strip_internal_fields_from_titles,
        # Validation tests
        test_validate_entry_structure,
        test_validate_entries_for_export,
        test_sanitize_entry_for_export,
    ]
    
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as e:
            print(f"[FAIL] {test.__name__} crashed: {e}")
            results.append(False)
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\n[OK] All tests passed!")
        return True
    else:
        print(f"\n[FAIL] {total - passed} test(s) failed")
        return False
if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)



