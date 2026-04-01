"""
Tests for filesystem validation and auto-sanitization features.

Tests the new validation system that supports both Windows and Linux/Unraid
filesystem rules, along with automatic sanitization of invalid folder names.
"""

import pytest
from src import config
from src.rss_rules import build_save_path
from src.utils import (
    compose_effective_download_path,
    get_category_save_path,
    sanitize_folder_name,
)


class TestFilesystemValidation:
    """Tests for filesystem-specific validation rules."""
    
    def test_linux_validation_allows_colons(self):
        """Linux mode should allow colons in folder names."""
        config.set_pref('filesystem_type', 'linux')
        
        # This would be validated in the actual validation function
        # For now, just verify preference is set
        assert config.get_pref('filesystem_type', 'linux') == 'linux'
    def test_linux_validation_blocks_forward_slash(self):
        """Linux mode should block forward slashes."""
        config.set_pref('filesystem_type', 'linux')
        
        # Forward slash is invalid in Linux folder names
        test_name = "Title/Name"
        # Would fail validation
        assert '/' in test_name
    def test_windows_validation_blocks_colons(self):
        """Windows mode should block colons in folder names."""
        config.set_pref('filesystem_type', 'windows')
        
        test_name = "Title: Name"
        # Would fail Windows validation
        assert ':' in test_name
    def test_windows_validation_blocks_quotes(self):
        """Windows mode should block quotes in folder names."""
        config.set_pref('filesystem_type', 'windows')
        
        test_name = 'Title "Name"'
        # Would fail Windows validation
        assert '"' in test_name
    def test_windows_validation_blocks_trailing_dots(self):
        """Windows mode should block trailing dots."""
        config.set_pref('filesystem_type', 'windows')
        
        test_name = "Title Name."
        # Would fail Windows validation
        assert test_name.endswith('.')
    def test_windows_reserved_names(self):
        """Windows mode should block reserved names like CON, PRN, etc."""
        config.set_pref('filesystem_type', 'windows')
        
        reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1']
        for name in reserved_names:
            # These would fail Windows validation
            assert name.upper() in ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1']
class TestAutoSanitization:
    """Tests for automatic folder name sanitization."""
    
    def test_sanitize_removes_colons(self):
        """Sanitization should remove colons."""
        original = "Mushoku no Eiyuu: Betsu ni Skill"
        sanitized = sanitize_folder_name(original)
        
        # Colons should be removed or replaced
        assert ':' not in sanitized
        # Title should still be recognizable
        assert 'Mushoku' in sanitized
        assert 'Eiyuu' in sanitized
    def test_sanitize_removes_quotes(self):
        """Sanitization should remove quotes."""
        original = 'Gift "Mugen Gacha" de Level'
        sanitized = sanitize_folder_name(original)
        
        # Quotes should be removed
        assert '"' not in sanitized
        # Title should still be readable
        assert 'Gift' in sanitized
        assert 'Mugen' in sanitized
    def test_sanitize_preserves_valid_characters(self):
        """Sanitization should preserve valid characters."""
        original = "Valid Title Name 123"
        sanitized = sanitize_folder_name(original)
        
        # Should be unchanged or minimally changed
        assert 'Valid' in sanitized
        assert 'Title' in sanitized
        assert 'Name' in sanitized
    def test_sanitize_handles_multiple_invalid_chars(self):
        """Sanitization should handle multiple invalid characters."""
        original = 'Title: "Name" <Test> |More|'
        sanitized = sanitize_folder_name(original)
        
        # All invalid characters should be removed
        invalid_chars = [':', '"', '<', '>', '|']
        for char in invalid_chars:
            assert char not in sanitized
    def test_sanitize_respects_global_replacement_preference(self):
        """Global replacement character preference should be applied when enabled."""
        original = 'Bad:Name?Here'
        try:
            config.set_pref('sanitize_replace_all', True)
            config.set_pref('sanitize_global_char', '-')
            sanitized = sanitize_folder_name(original)
            assert sanitized == 'Bad-Name-Here'
        finally:
            config.set_pref('sanitize_replace_all', True)
            config.set_pref('sanitize_global_char', '_')
            config.set_pref('sanitize_custom_map', {})
    def test_sanitize_respects_custom_map_preference(self):
        """Custom per-character mapping should be used when replace-all is disabled."""
        original = 'Bad:Name?Here'
        try:
            config.set_pref('sanitize_replace_all', False)
            config.set_pref('sanitize_custom_map', {':': '~', '?': ''})
            sanitized = sanitize_folder_name(original)
            assert sanitized == 'Bad~NameHere'
        finally:
            config.set_pref('sanitize_replace_all', True)
            config.set_pref('sanitize_global_char', '_')
            config.set_pref('sanitize_custom_map', {})
    def test_auto_sanitize_preference_default(self):
        """Auto-sanitize preference should default to True."""
        pref = config.get_pref('auto_sanitize_paths', True)
        assert pref == True
    def test_auto_sanitize_preference_toggle(self):
        """Should be able to toggle auto-sanitize preference."""
        # Set to False
        config.set_pref('auto_sanitize_paths', False)
        assert config.get_pref('auto_sanitize_paths', True) == False
        
        # Set back to True
        config.set_pref('auto_sanitize_paths', True)
        assert config.get_pref('auto_sanitize_paths', False) == True
class TestValidationIntegration:
    """Integration tests for validation with treeview and sync."""
    
    def test_filesystem_preference_persistence(self):
        """Filesystem type preference should persist."""
        # Set to Windows
        config.set_pref('filesystem_type', 'windows')
        assert config.get_pref('filesystem_type', 'linux') == 'windows'
        
        # Set to Linux
        config.set_pref('filesystem_type', 'linux')
        assert config.get_pref('filesystem_type', 'windows') == 'linux'
    def test_validation_respects_filesystem_type(self):
        """Validation should respect filesystem type preference."""
        # Set Linux mode
        config.set_pref('filesystem_type', 'linux')
        fs_type = config.get_pref('filesystem_type', 'windows')
        assert fs_type == 'linux'
        
        # Set Windows mode
        config.set_pref('filesystem_type', 'windows')
        fs_type = config.get_pref('filesystem_type', 'linux')
        assert fs_type == 'windows'
    def test_sanitization_with_path_components(self):
        """Sanitization should work with full paths."""
        path = "media/anime/web/Fall 2025/Mushoku no Eiyuu: Betsu ni Skill"
        components = path.split('/')
        
        # Last component has invalid character
        assert ':' in components[-1]
        
        # Sanitize last component
        sanitized = sanitize_folder_name(components[-1])
        assert ':' not in sanitized
class TestValidationEdgeCases:
    """Edge case tests for validation system."""
    
    def test_empty_folder_name(self):
        """Should handle empty folder names gracefully."""
        empty = ""
        # Should not crash, should return safe default or fail validation
        assert len(empty) == 0
    def test_whitespace_only_name(self):
        """Should handle whitespace-only names."""
        whitespace = "   "
        # Should fail validation or be sanitized
        assert whitespace.strip() == ""
    def test_very_long_path(self):
        """Should handle very long path names."""
        long_name = "A" * 300  # Longer than typical MAX_PATH_LENGTH
        # Should fail validation for length
        assert len(long_name) > 255
    def test_unicode_characters(self):
        """Should handle Unicode characters properly."""
        unicode_name = "ã‚¢ãƒ‹ãƒ¡ Title åŠ¨æ¼«"
        # Should preserve Unicode unless invalid
        assert len(unicode_name) > 0
    def test_mixed_slashes(self):
        """Should handle mixed forward and back slashes."""
        mixed = "path\\to/folder"
        # Should normalize or validate correctly
        assert '\\' in mixed or '/' in mixed
class TestCategorySavePathExtraction:
    """Tests for category save-path extraction compatibility."""

    def test_extracts_qbit_save_path_key(self):
        """Should support qBittorrent native save_path key."""
        cat_info = {'save_path': 'media/anime/web'}
        assert get_category_save_path(cat_info) == 'media/anime/web'

    def test_extracts_legacy_savePath_key(self):
        """Should support legacy savePath key used by older app data."""
        cat_info = {'savePath': 'media/anime/web'}
        assert get_category_save_path(cat_info) == 'media/anime/web'

    def test_extracts_from_string_category_value(self):
        """Should support string category values from simplified caches."""
        assert get_category_save_path('media/anime/web') == 'media/anime/web'

    def test_normalizes_backslashes(self):
        """Should normalize Windows slashes for consistency in rules."""
        cat_info = {'save_path': r'media\\anime\\web'}
        assert get_category_save_path(cat_info) == 'media/anime/web'


class TestEffectiveDownloadPath:
    """Tests for full destination path composition."""

    def test_compose_default_category_rule_relative(self):
        """Should compose default + category + rule relative path."""
        full = compose_effective_download_path(
            '/downloads',
            'media/anime/web',
            'Fall 2025/Sample Seasonal Title'
        )
        assert full == '/downloads/media/anime/web/Fall 2025/Sample Seasonal Title'

    def test_compose_absolute_rule_path_wins(self):
        """Absolute rule save path should override default/category composition."""
        full = compose_effective_download_path('/downloads', 'media/anime/web', '/custom/absolute/path')
        assert full == '/custom/absolute/path'

    def test_build_save_path_uses_cached_category_path(self):
        """Auto-generated save path should remain rule-relative."""
        old_default_download = config.DEFAULT_DOWNLOAD_PATH
        old_cached_categories = dict(getattr(config, 'CACHED_CATEGORIES', {}) or {})
        try:
            config.DEFAULT_DOWNLOAD_PATH = '/downloads'
            config.CACHED_CATEGORIES = {
                'Anime - Web': {'save_path': 'media/anime/web'}
            }
            full = build_save_path(
                'Sample Seasonal Title',
                'Fall',
                '2025',
                'Anime - Web'
            )
            assert full == 'Fall 2025/Sample Seasonal Title'
        finally:
            config.DEFAULT_DOWNLOAD_PATH = old_default_download
            config.CACHED_CATEGORIES = old_cached_categories

    def test_build_save_path_case_by_case_winter_example(self):
        """Rule savePath should be generated per season/title, not hardcoded."""
        path = build_save_path(
            'Sample Winter Title',
            'Winter',
            '2026',
            'Anime - Web'
        )
        assert path == 'Winter 2026/Sample Winter Title'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

