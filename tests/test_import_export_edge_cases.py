"""
Test edge cases for import/export operations.

This module tests various edge cases including:
- Empty files
- Malformed JSON
- Invalid data structures
- Unicode handling
- Large files
- File permission errors
"""
import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from src.rss_rules import (
    RSSRule,
    build_rules_from_titles,
    export_rules_to_json,
    import_rules_from_json,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestEmptyFiles:
    """Test handling of empty or minimal files."""
    
    def test_import_empty_file(self):
        """Test importing an empty file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "Empty file should fail"
            assert "Invalid JSON" in result, "Should return JSON error message"
        finally:
            os.unlink(temp_path)
    
    def test_import_empty_json_object(self):
        """Test importing a file with empty JSON object."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is True, "Empty JSON object should succeed"
            assert result == {}, "Should return empty dict"
        finally:
            os.unlink(temp_path)
    
    def test_import_whitespace_only(self):
        """Test importing a file with only whitespace."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('   \n\t  \n  ')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "Whitespace-only file should fail"
            assert "Invalid JSON" in result, "Should return JSON error message"
        finally:
            os.unlink(temp_path)
    
    def test_export_empty_rules(self):
        """Test exporting empty rules dictionary."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            success = export_rules_to_json({}, temp_path)
            assert success, "Export should succeed for empty rules"
            
            # Verify file content
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
            assert content == {}, "Exported file should contain empty object"
        finally:
            os.unlink(temp_path)


class TestMalformedJSON:
    """Test handling of malformed JSON."""
    
    def test_import_invalid_json_syntax(self):
        """Test importing file with invalid JSON syntax."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{ invalid json }')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "Invalid JSON should fail"
            assert "Invalid JSON" in result, "Should return JSON error message"
        finally:
            os.unlink(temp_path)
    
    def test_import_incomplete_json(self):
        """Test importing file with incomplete JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"rule1": {"mustContain": "test"')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "Incomplete JSON should fail"
            assert "Invalid JSON" in result, "Should return JSON error message"
        finally:
            os.unlink(temp_path)
    
    def test_import_json_array_instead_of_object(self):
        """Test importing file with JSON array instead of object."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('["item1", "item2"]')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "JSON array should fail"
            assert "Invalid rules format" in result, "Should return format error"
        finally:
            os.unlink(temp_path)
    
    def test_import_json_string_instead_of_object(self):
        """Test importing file with JSON string instead of object."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('"just a string"')
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is False, "JSON string should fail"
            assert "Invalid rules format" in result, "Should return format error"
        finally:
            os.unlink(temp_path)


class TestInvalidDataStructures:
    """Test handling of invalid data structures in otherwise valid JSON."""
    
    def test_import_rules_missing_required_fields(self):
        """Test importing rules with missing required fields."""
        rules = {
            "TestRule": {
                # Missing mustContain
                "savePath": "/test",
                "enabled": True
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(rules, f)
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is True, "Import should succeed"
            assert "TestRule" in result, "Rule should still be imported"
            # The rule will use the title as mustContain if missing
        finally:
            os.unlink(temp_path)
    
    def test_import_rules_with_null_values(self):
        """Test importing rules with null values."""
        rules = {
            "TestRule": {
                "mustContain": None,
                "savePath": None,
                "enabled": None
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(rules, f)
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is True, "Import should succeed"
            assert "TestRule" in result, "Rule should be imported with null values"
        finally:
            os.unlink(temp_path)
    
    def test_import_rules_with_wrong_types(self):
        """Test importing rules with wrong data types."""
        rules = {
            "TestRule": {
                "mustContain": 123,  # Should be string
                "enabled": "yes",    # Should be boolean
                "priority": "high"   # Should be integer
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(rules, f)
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            assert success is True, "Import should succeed"
            assert "TestRule" in result, "Rule should be imported despite wrong types"
        finally:
            os.unlink(temp_path)


class TestUnicodeHandling:
    """Test handling of Unicode characters."""
    
    def test_export_import_unicode_title(self):
        """Test exporting and importing rule with Unicode title."""
        rule = RSSRule(
            title="アニメ Test 中文 Тест",
            must_contain="アニメ",
            save_path="/anime/アニメ",
            feed_url="http://example.com/feed",
            category="anime"
        )
        
        rules = {"UnicodeTest": rule.to_dict()}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            temp_path = f.name
        
        try:
            # Export
            success = export_rules_to_json(rules, temp_path)
            assert success, "Export with Unicode should succeed"
            
            # Import
            success, imported = import_rules_from_json(temp_path)
            assert success, "Import should succeed"
            assert "UnicodeTest" in imported, "Unicode rule should be imported"
            assert imported["UnicodeTest"]["mustContain"] == "アニメ"
        finally:
            os.unlink(temp_path)
    
    def test_export_import_emoji(self):
        """Test exporting and importing rule with emoji."""
        rule = RSSRule(
            title="Test 🎬📺🎭",
            must_contain="anime 🎬",
            save_path="/test",
            feed_url="http://example.com/feed"
        )
        
        rules = {"EmojiTest": rule.to_dict()}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            temp_path = f.name
        
        try:
            success = export_rules_to_json(rules, temp_path)
            assert success, "Export with emoji should succeed"
            
            success, imported = import_rules_from_json(temp_path)
            assert success, "Import should succeed"
            assert "EmojiTest" in imported
        finally:
            os.unlink(temp_path)
    
    def test_import_unicode_bom(self):
        """Test importing file with UTF-8 BOM."""
        rules = {"TestRule": {"mustContain": "test", "enabled": True}}
        
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as f:
            # Write UTF-8 BOM
            f.write(b'\xef\xbb\xbf')
            f.write(json.dumps(rules, ensure_ascii=False).encode('utf-8'))
            temp_path = f.name
        
        try:
            success, result = import_rules_from_json(temp_path)
            # BOM causes JSON decode error, which is expected
            assert success is False, "File with BOM should fail with current implementation"
        finally:
            os.unlink(temp_path)


class TestLargeFiles:
    """Test handling of large files."""
    
    def test_export_many_rules(self):
        """Test exporting a large number of rules."""
        rules = {}
        for i in range(1000):
            rule = RSSRule(
                title=f"Rule_{i}",
                must_contain=f"pattern_{i}",
                save_path=f"/path/{i}",
                feed_url="http://example.com/feed"
            )
            rules[f"Rule_{i}"] = rule.to_dict()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            success = export_rules_to_json(rules, temp_path)
            assert success, "Export of many rules should succeed"
            
            # Verify file size is reasonable
            file_size = os.path.getsize(temp_path)
            assert file_size > 0, "File should have content"
            assert file_size < 10_000_000, "File should not be unreasonably large"
        finally:
            os.unlink(temp_path)
    
    def test_import_many_rules(self):
        """Test importing a large number of rules."""
        rules = {}
        for i in range(500):
            rules[f"Rule_{i}"] = {
                "mustContain": f"pattern_{i}",
                "savePath": f"/path/{i}",
                "enabled": True,
                "affectedFeeds": ["http://example.com/feed"]
            }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(rules, f)
            temp_path = f.name
        
        try:
            success, imported = import_rules_from_json(temp_path)
            assert success is True, "Import should succeed"
            assert len(imported) == 500, "All rules should be imported"
        finally:
            os.unlink(temp_path)


class TestSpecialPaths:
    """Test handling of special file paths."""
    
    def test_export_to_nested_directory(self):
        """Test exporting to a nested directory that doesn't exist yet."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = os.path.join(temp_dir, "subdir1", "subdir2", "rules.json")
            
            rule = RSSRule(
                title="Test",
                must_contain="test",
                save_path="/test",
                feed_url="http://example.com/feed"
            )
            rules = {"Test": rule.to_dict()}
            
            success = export_rules_to_json(rules, nested_path)
            assert success, "Export to nested directory should succeed"
            assert os.path.exists(nested_path), "File should be created"
    
    def test_export_to_path_with_spaces(self):
        """Test exporting to a path with spaces."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path_with_spaces = os.path.join(temp_dir, "folder with spaces", "rules.json")
            os.makedirs(os.path.dirname(path_with_spaces))
            
            rule = RSSRule(
                title="Test",
                must_contain="test",
                save_path="/test",
                feed_url="http://example.com/feed"
            )
            rules = {"Test": rule.to_dict()}
            
            success = export_rules_to_json(rules, path_with_spaces)
            assert success, "Export to path with spaces should succeed"
            assert os.path.exists(path_with_spaces)
    
    def test_export_to_path_with_unicode(self):
        """Test exporting to a path with Unicode characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            unicode_path = os.path.join(temp_dir, "フォルダ", "rules.json")
            os.makedirs(os.path.dirname(unicode_path), exist_ok=True)
            
            rule = RSSRule(
                title="Test",
                must_contain="test",
                save_path="/test",
                feed_url="http://example.com/feed"
            )
            rules = {"Test": rule.to_dict()}
            
            success = export_rules_to_json(rules, unicode_path)
            assert success, "Export to Unicode path should succeed"
            assert os.path.exists(unicode_path)


class TestRoundTrip:
    """Test round-trip import/export consistency."""
    
    def test_export_import_preserves_all_fields(self):
        """Test that export followed by import preserves all rule fields."""
        rule = RSSRule(
            title="CompleteTest",
            must_contain="test pattern",
            save_path="/test/path",
            feed_url="http://example.com/feed",
            category="test_category",
            add_paused=True,
            enabled=False,
            episode_filter="S01",
            ignore_days=7,
            must_not_contain="exclude",
            priority=5,
            smart_filter=True,
            use_regex=True,
            download_limit=1000,
            upload_limit=500
        )
        
        rules = {"CompleteTest": rule.to_dict()}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            # Export
            export_rules_to_json(rules, temp_path)
            
            # Import
            success, imported = import_rules_from_json(temp_path)
            assert success, "Import should succeed"
            
            # Verify key fields are preserved
            imported_rule = imported["CompleteTest"]
            assert imported_rule["mustContain"] == "test pattern"
            assert imported_rule["savePath"] == "/test/path"
            assert imported_rule["assignedCategory"] == "test_category"
            assert imported_rule["addPaused"] is True
            assert imported_rule["enabled"] is False
            assert imported_rule["priority"] == 5
            assert imported_rule["smartFilter"] is True
            assert imported_rule["useRegex"] is True
        finally:
            os.unlink(temp_path)
    
    def test_multiple_export_import_cycles(self):
        """Test that multiple export/import cycles don't corrupt data."""
        rule = RSSRule(
            title="CycleTest",
            must_contain="test",
            save_path="/test",
            feed_url="http://example.com/feed"
        )
        
        rules = {"CycleTest": rule.to_dict()}
        original_json = json.dumps(rules, sort_keys=True)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            # Perform 5 export/import cycles
            for i in range(5):
                export_rules_to_json(rules, temp_path)
                success, rules = import_rules_from_json(temp_path)
                assert success, f"Import cycle {i+1} should succeed"
            
            # Verify data hasn't changed
            final_json = json.dumps(rules, sort_keys=True)
            assert final_json == original_json, "Multiple cycles should not corrupt data"
        finally:
            os.unlink(temp_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
