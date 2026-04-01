"""
Unit tests for GUI components using unittest.mock.

Tests cover main_window.py, dialogs.py, and file_operations.py functionality
including user interactions, button clicks, menu selections, and error handling.
"""
import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import MagicMock, Mock, call, mock_open, patch

# Check if Tk is available
try:
    root = tk.Tk()
    tk_available = True
    root.destroy()
except tk.TclError:
    tk_available = False

from src.gui.app_state import AppState
from src.gui.dialogs import (
    open_full_rule_editor,
    open_log_viewer,
    open_settings_window,
    view_trash_dialog,
)
from src.gui.file_operations import (
    clear_all_titles,
    import_titles_from_clipboard,
    import_titles_from_file,
    import_titles_from_text,
    normalize_titles_structure,
    update_treeview_with_titles,
)
from src.gui.main_window import (
    create_tooltip,
    refresh_treeview_display,
    setup_status_and_autoconnect,
    setup_window_and_styles,
)
from src.config import config


@unittest.skipIf(not tk_available, "Tk display not available")
class TestTooltip(unittest.TestCase):
    """Test tooltip creation and behavior."""
    
    def setUp(self):
        """Create root window for tests."""
        try:
            self.root = tk.Tk()
            self.widget = tk.Button(self.root, text="Test")
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
        
    def tearDown(self):
        """Destroy root window after tests."""
        try:
            self.root.destroy()
        except Exception:
            pass
    
    def test_create_tooltip(self):
        """Test tooltip is created without errors."""
        create_tooltip(self.widget, "Test tooltip")
        # Verify bindings are set
        bindings = self.widget.bind()
        assert '<Enter>' in bindings
        assert '<Leave>' in bindings


class TestWindowSetup(unittest.TestCase):
    """Test window initialization and styling."""
    
    def test_window_setup_smoke_test(self):
        """Basic smoke test for window setup function."""
        # Just verify the function exists and is callable
        assert callable(setup_window_and_styles)

    @unittest.skipIf(not tk_available, "Tk display not available")
    def test_window_setup_dark_mode_palette(self):
        """Dark theme should apply configured palette to key ttk widgets."""
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
        try:
            with patch('src.gui.main_window.config.get_pref') as mock_get_pref:
                def _pref_side_effect(key, default=None):
                    if key == 'theme':
                        return 'dark'
                    if key == 'font_size':
                        return 10
                    return default

                mock_get_pref.side_effect = _pref_side_effect
                style, _, _ = setup_window_and_styles(root)

            tree_cfg = style.configure('Treeview')
            entry_cfg = style.configure('TEntry')
            tab_cfg = style.configure('TNotebook.Tab')

            assert tree_cfg.get('background') == '#171b24'
            assert entry_cfg.get('fieldbackground') == '#171b24'
            assert tab_cfg.get('background') == '#1d222b'
        finally:
            root.destroy()


class TestAutoConnectSetup(unittest.TestCase):
    """Test setup_status_and_autoconnect safety behavior."""

    @patch('src.gui.main_window.os.path.exists', return_value=True)
    @patch('src.gui.main_window.threading.Thread', side_effect=RuntimeError('thread error'))
    def test_autoconnect_thread_failure_is_handled(self, _mock_thread, _mock_exists):
        """Auto mode should handle thread start failure without raising."""
        root = MagicMock()
        status_var = MagicMock()

        with patch.object(config, 'CONNECTION_MODE', 'auto'):
            setup_status_and_autoconnect(root, status_var, config_set=True)

        status_var.set.assert_any_call('Auto (will try online if available)')

    @patch('src.gui.main_window.os.path.exists', return_value=True)
    def test_online_mode_schedules_autotest(self, _mock_exists):
        """Online mode should schedule delayed auto test via root.after."""
        root = MagicMock()
        status_var = MagicMock()

        with patch.object(config, 'CONNECTION_MODE', 'online'):
            setup_status_and_autoconnect(root, status_var, config_set=True)

        root.after.assert_any_call(500, unittest.mock.ANY)


class TestTreeviewRefresh(unittest.TestCase):
    """Test treeview refresh functionality."""
    
    def test_refresh_treeview_display_no_treeview(self):
        """Test refresh when no treeview is available."""
        # Should not raise exception
        refresh_treeview_display()


class TestDialogWindows(unittest.TestCase):
    """Test dialog window functionality."""
    
    def test_dialog_imports(self):
        """Test that dialog functions can be imported."""
        # Simple test to verify the module structure
        assert callable(open_settings_window)
        assert callable(open_log_viewer)
        assert callable(view_trash_dialog)
        assert callable(open_full_rule_editor)


class TestFileOperations(unittest.TestCase):
    """Test file import/export operations."""
    
    def test_normalize_titles_structure_list(self):
        """Test normalizing title structure from list format."""
        data = ["Anime 1", "Anime 2"]
        result = normalize_titles_structure(data)
        assert isinstance(result, dict)
    
    def test_import_titles_from_text(self):
        """Test importing titles from text."""
        text = "Anime 1\nAnime 2\nAnime 3"
        result = import_titles_from_text(text)
        assert result is not None
        assert isinstance(result, dict)

    def test_import_titles_from_text_csv(self):
        """CSV input should parse into normalized title entries."""
        text = "title,category\nSolo Leveling,anime\nOne Piece,anime"
        result = import_titles_from_text(text)
        assert result is not None
        assert 'anime' in result
        assert len(result['anime']) == 2

    @patch('src.gui.file_operations._show_import_sanitize_check')
    @patch('src.gui.file_operations.config.get_pref')
    def test_import_clipboard_cancelled_by_sanitize_check(self, mock_get_pref, mock_show_check):
        """Clipboard import should stop when user cancels pre-import sanitize check."""
        root = MagicMock()
        root.clipboard_get.return_value = "Anime 1\nAnime 2"
        status_var = MagicMock()
        season_var = MagicMock()
        year_var = MagicMock()
        season_var.get.return_value = "Winter"
        year_var.get.return_value = "2026"

        def _pref_side_effect(key, default=None):
            if key == 'show_import_sanitize_check':
                return True
            return default

        mock_get_pref.side_effect = _pref_side_effect
        mock_show_check.return_value = (False, True)

        result = import_titles_from_clipboard(root, status_var, season_var, year_var, prefix_imports=False)

        assert result is False
        status_var.set.assert_called_with('Import cancelled.')
    
    @patch('src.gui.file_operations.messagebox.askyesno')
    def test_clear_all_titles_cancelled(self, mock_confirm):
        """Test clearing all titles when cancelled."""
        mock_confirm.return_value = False
        mock_root = MagicMock()
        mock_status = MagicMock()
        
        result = clear_all_titles(mock_root, mock_status)
        
        assert result is False


class TestAppState(unittest.TestCase):
    """Test AppState singleton functionality."""
    
    def test_app_state_singleton(self):
        """Test AppState get_instance returns instance."""
        state1 = AppState.get_instance()
        state2 = AppState.get_instance()
        assert state1 is state2
    
    def test_app_state_treeview(self):
        """Test treeview getter/setter."""
        state = AppState.get_instance()
        mock_tree = MagicMock()
        
        state.treeview = mock_tree
        assert state.treeview is mock_tree
    
    def test_app_state_root(self):
        """Test root getter/setter."""
        state = AppState.get_instance()
        mock_root = MagicMock()
        
        state.root = mock_root
        assert state.root is mock_root
    
    def test_app_state_status_var(self):
        """Test status_var getter/setter."""
        state = AppState.get_instance()
        mock_var = MagicMock()
        
        state.status_var = mock_var
        assert state.status_var is mock_var
    
    def test_app_state_set_status(self):
        """Test set_status updates status_var."""
        state = AppState.get_instance()
        mock_var = MagicMock()
        state.status_var = mock_var
        
        state.set_status("Test message")
        mock_var.set.assert_called_once_with("Test message")


class TestErrorHandling(unittest.TestCase):
    """Test error handling in GUI operations."""
    
    def test_normalize_titles_handles_none(self):
        """Test normalize_titles_structure handles None input."""
        result = normalize_titles_structure(None)
        # Should handle gracefully - either None or empty/default dict
        assert result is None or isinstance(result, dict)
    
    def test_normalize_titles_handles_invalid_type(self):
        """Test normalize_titles_structure handles invalid types."""
        result = normalize_titles_structure(12345)
        # Should handle gracefully
        assert isinstance(result, dict) or result is None
    
    def test_import_titles_from_text_empty(self):
        """Test import_titles_from_text handles empty string."""
        result = import_titles_from_text("")
        # Should handle gracefully - either None or empty dict
        assert result is None or result == {} or isinstance(result, dict)


if __name__ == '__main__':
    unittest.main()
