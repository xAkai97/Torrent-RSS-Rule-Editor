"""
Unit tests for treeview display operations.

Tests cover the refactored treeview update functions including:
- update_treeview_with_titles()
- refresh_treeview_display_safe()
- clear_all_titles()
- Proper handling of empty data
- Display refresh consistency
"""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch, MagicMock
import logging
import sys
import os

# Try to initialize Tk, skip tests if display is unavailable
try:
    root = tk.Tk()
    tk_available = True
    root.destroy()
except tk.TclError:
    tk_available = False

from src.gui.file_operations import (
    update_treeview_with_titles,
    refresh_treeview_display_safe,
    clear_all_titles,
)
from src.gui.app_state import AppState, get_app_state
from src.config import config

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@unittest.skipIf(not tk_available, "Tk display not available")
class TestUpdateTreeviewWithTitles(unittest.TestCase):
    """Test the update_treeview_with_titles function."""
    
    def setUp(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
            self.treeview = ttk.Treeview(
                self.root,
                columns=('enabled', 'index', 'title', 'category', 'savepath'),
                show='headings'
            )
            self.treeview.pack()
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
        
        # Mock app_state
        self.app_state = AppState()
        self.app_state.treeview = self.treeview
        
    def tearDown(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except Exception:
            pass
    
    def test_update_empty_titles(self):
        """Test updating treeview with empty titles dict."""
        result = update_treeview_with_titles({}, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 0)
    
    def test_update_none_titles(self):
        """Test updating treeview with None titles."""
        result = update_treeview_with_titles(None, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 0)
    
    def test_update_with_single_title(self):
        """Test updating treeview with a single title."""
        titles = {
            'anime': [
                {
                    'node': {'title': 'Test Anime'},
                    'category': 'anime',
                    'enabled': True,
                    'savePath': '/path/to/save'
                }
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        children = self.treeview.get_children()
        self.assertEqual(len(children), 1)
        
        # Verify item values
        values = self.treeview.item(children[0], 'values')
        self.assertIn('Test Anime', values)
    
    def test_update_with_multiple_titles(self):
        """Test updating treeview with multiple titles."""
        titles = {
            'anime': [
                {'node': {'title': 'Anime 1'}, 'enabled': True, 'savePath': '/path1'},
                {'node': {'title': 'Anime 2'}, 'enabled': True, 'savePath': '/path2'},
                {'node': {'title': 'Anime 3'}, 'enabled': False, 'savePath': '/path3'},
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 3)
    
    def test_update_clears_previous_items(self):
        """Test that updating treeview clears previous items."""
        # Insert initial items
        self.treeview.insert('', 'end', values=('✓', '1', 'Old Item', 'cat', '/path'))
        self.assertEqual(len(self.treeview.get_children()), 1)
        
        # Update with new titles
        titles = {
            'anime': [
                {'node': {'title': 'New Anime'}, 'enabled': True, 'savePath': '/path'}
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        children = self.treeview.get_children()
        self.assertEqual(len(children), 1)
        values = self.treeview.item(children[0], 'values')
        self.assertIn('New Anime', values)

    def test_update_clears_when_delete_is_monkey_patched(self):
        """Tree clearing should still work if widget delete is overridden."""
        self.treeview.insert('', 'end', values=('✓', '1', 'Old Item', 'cat', '/path'))
        self.assertEqual(len(self.treeview.get_children()), 1)

        # Simulate listbox-compat monkey patch that doesn't handle item IDs.
        self.treeview.delete = lambda *args, **kwargs: None

        titles = {
            'anime': [
                {'node': {'title': 'New Item'}, 'enabled': True, 'savePath': '/new'}
            ]
        }

        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)

        self.assertTrue(result)
        children = self.treeview.get_children()
        self.assertEqual(len(children), 1)
        values = self.treeview.item(children[0], 'values')
        self.assertIn('New Item', values)
    
    def test_update_with_invalid_folder_name(self):
        """Test handling of titles with invalid folder names."""
        titles = {
            'anime': [
                {
                    'node': {'title': 'Anime: With: Colons'},
                    'enabled': True,
                    'savePath': '/path/to/save'
                }
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        children = self.treeview.get_children()
        self.assertEqual(len(children), 1)
    
    def test_update_with_no_treeview(self):
        """Test update_treeview_with_titles when no treeview is provided."""
        result = update_treeview_with_titles({}, treeview_widget=None)
        
        # Should return False when no treeview
        self.assertFalse(result)
    
    def test_update_with_enabled_disabled_items(self):
        """Test that enabled/disabled state is properly displayed."""
        titles = {
            'anime': [
                {'node': {'title': 'Enabled'}, 'enabled': True},
                {'node': {'title': 'Disabled'}, 'enabled': False},
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        children = self.treeview.get_children()
        self.assertEqual(len(children), 2)
        
        # Check enabled mark
        values1 = self.treeview.item(children[0], 'values')
        self.assertEqual(values1[0], '✓')  # Enabled mark
        
        values2 = self.treeview.item(children[1], 'values')
        self.assertEqual(values2[0], '')  # No mark for disabled
    
    def test_update_with_string_entries(self):
        """Test update with simple string entries."""
        titles = {
            'anime': [
                'Simple String Entry',
                'Another String',
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 2)
    
    def test_update_with_mixed_dict_and_string(self):
        """Test update with mixed dict and string entries."""
        titles = {
            'anime': [
                {'node': {'title': 'Dict Entry'}, 'enabled': True},
                'String Entry',
            ]
        }
        
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 2)
    
    def test_update_preserves_app_state_items(self):
        """Test that update properly populates app_state items."""
        with patch('src.gui.file_operations.get_app_state') as mock_get_state:
            mock_state = Mock()
            mock_state.items = []
            mock_state.add_item = Mock()
            mock_state.treeview = self.treeview
            mock_get_state.return_value = mock_state
            
            titles = {
                'anime': [
                    {'node': {'title': 'Test'}, 'enabled': True}
                ]
            }
            
            result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
            
            self.assertTrue(result)
            mock_state.add_item.assert_called_once()


@unittest.skipIf(not tk_available, "Tk display not available")
class TestClearAllTitles(unittest.TestCase):
    """Test the clear_all_titles function."""
    
    def setUp(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
            self.treeview = ttk.Treeview(
                self.root,
                columns=('enabled', 'index', 'title', 'category', 'savepath'),
                show='headings'
            )
            self.treeview.pack()
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
        
        # Mock app_state
        self.app_state = AppState()
        self.app_state.treeview = self.treeview
        
        # Add initial items
        self.treeview.insert('', 'end', values=('✓', '1', 'Item 1', 'cat', '/path'))
        self.treeview.insert('', 'end', values=('✓', '2', 'Item 2', 'cat', '/path'))
    
    def tearDown(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except:
            pass
    
    def test_clear_with_confirmation(self):
        """Test clearing titles with user confirmation."""
        config.ALL_TITLES = {'anime': [{'node': {'title': 'Test'}}]}
        status_var = tk.StringVar()
        
        with patch('src.gui.file_operations.messagebox.askyesno', return_value=True):
            with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
                result = clear_all_titles(self.root, status_var)
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 0)
        self.assertEqual(config.ALL_TITLES, {})
    
    def test_clear_with_rejection(self):
        """Test clearing is cancelled when user rejects."""
        config.ALL_TITLES = {'anime': [{'node': {'title': 'Test'}}]}
        status_var = tk.StringVar()
        
        with patch('src.gui.file_operations.messagebox.askyesno', return_value=False):
            with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
                result = clear_all_titles(self.root, status_var)
        
        self.assertFalse(result)
        # Data should not be cleared
        self.assertNotEqual(config.ALL_TITLES, {})
    
    def test_clear_empty_titles(self):
        """Test clearing when no titles are loaded."""
        config.ALL_TITLES = {}
        status_var = tk.StringVar()
        
        with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
            result = clear_all_titles(self.root, status_var)
        
        self.assertFalse(result)
        self.assertIn('No titles to clear', status_var.get())


class TestRefreshTreeviewDisplaySafe(unittest.TestCase):
    """Test the refresh_treeview_display_safe function."""
    
    def setUp(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
        self.treeview = ttk.Treeview(
            self.root,
            columns=('enabled', 'index', 'title', 'category', 'savepath'),
            show='headings'
        )
        self.treeview.pack()
        
        self.app_state = AppState()
        self.app_state.treeview = self.treeview
    
    def tearDown(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except:
            pass
    
    def test_refresh_with_titles(self):
        """Test refresh with loaded titles."""
        config.ALL_TITLES = {
            'anime': [
                {'node': {'title': 'Anime 1'}, 'enabled': True}
            ]
        }
        
        with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
            refresh_treeview_display_safe()
        
        self.assertEqual(len(self.treeview.get_children()), 1)
    
    def test_refresh_empty_titles(self):
        """Test refresh with empty titles."""
        config.ALL_TITLES = {}
        
        with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
            refresh_treeview_display_safe()
        
        self.assertEqual(len(self.treeview.get_children()), 0)
    
    def test_refresh_no_app_state(self):
        """Test refresh when app_state is not available."""
        with patch('src.gui.file_operations.get_app_state', return_value=None):
            # Should not raise exception
            refresh_treeview_display_safe()


class TestTreeviewConsistency(unittest.TestCase):
    """Test consistency of treeview operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.root = tk.Tk()
        self.treeview = ttk.Treeview(
            self.root,
            columns=('enabled', 'index', 'title', 'category', 'savepath'),
            show='headings'
        )
        self.treeview.pack()
        
        self.app_state = AppState()
        self.app_state.treeview = self.treeview
    
    def tearDown(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except:
            pass
    
    def test_update_clear_cycle(self):
        """Test updating and clearing titles in sequence."""
        # Add titles
        titles = {
            'anime': [
                {'node': {'title': 'Anime 1'}, 'enabled': True},
                {'node': {'title': 'Anime 2'}, 'enabled': True},
            ]
        }
        
        result1 = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        self.assertTrue(result1)
        self.assertEqual(len(self.treeview.get_children()), 2)
        
        # Clear titles
        result2 = update_treeview_with_titles({}, treeview_widget=self.treeview)
        self.assertTrue(result2)
        self.assertEqual(len(self.treeview.get_children()), 0)
        
        # Add different titles
        titles2 = {
            'anime': [
                {'node': {'title': 'New Anime'}, 'enabled': True},
            ]
        }
        
        result3 = update_treeview_with_titles(titles2, treeview_widget=self.treeview)
        self.assertTrue(result3)
        self.assertEqual(len(self.treeview.get_children()), 1)
    
    def test_refresh_maintains_data_consistency(self):
        """Test that refresh maintains data consistency."""
        config.ALL_TITLES = {
            'anime': [
                {'node': {'title': 'Test'}, 'enabled': True}
            ]
        }
        
        with patch('src.gui.file_operations.get_app_state', return_value=self.app_state):
            refresh_treeview_display_safe()
            self.assertEqual(len(self.treeview.get_children()), 1)
            
            # Call refresh again
            refresh_treeview_display_safe()
            self.assertEqual(len(self.treeview.get_children()), 1)


@unittest.skipIf(not tk_available, "Tk display not available")
class TestTreeviewPerformance(unittest.TestCase):
    """Performance tests for treeview operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
            self.treeview = ttk.Treeview(
                self.root,
                columns=('enabled', 'index', 'title', 'category', 'savepath'),
                show='headings'
            )
            self.treeview.pack()
            
            # Mock app_state
            self.app_state = AppState()
            self.app_state.treeview = self.treeview
        except tk.TclError as e:
            self.skipTest(f"Tk initialization failed: {e}")
    
    def tearDown(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except Exception:
            pass
    
    def _create_large_titles_dict(self, count: int) -> dict:
        """Create a large titles dictionary for performance testing."""
        anime_list = []
        for i in range(count):
            anime_list.append({
                'node': {'title': f'Test Anime {i}'},
                'enabled': True,
                'savePath': f'/path{i}'
            })
        return {'anime': anime_list}
    
    def test_performance_100_items(self):
        """Test update performance with 100 items (should be <100ms)."""
        import time
        
        titles = self._create_large_titles_dict(100)
        
        start = time.time()
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 100)
        
        # Performance assertion (warning, not strict)
        if elapsed > 0.1:
            logger.warning(f"100 items took {elapsed*1000:.2f}ms (target: <100ms)")
    
    def test_performance_500_items(self):
        """Test update performance with 500 items (should be <300ms)."""
        import time
        
        titles = self._create_large_titles_dict(500)
        
        start = time.time()
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 500)
        
        # Performance assertion (warning, not strict)
        if elapsed > 0.3:
            logger.warning(f"500 items took {elapsed*1000:.2f}ms (target: <300ms)")
    
    def test_performance_1000_items(self):
        """Test update performance with 1000 items (should be <500ms)."""
        import time
        
        titles = self._create_large_titles_dict(1000)
        
        start = time.time()
        result = update_treeview_with_titles(titles, treeview_widget=self.treeview)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 1000)
        
        # Performance assertion (warning, not strict)
        if elapsed > 0.5:
            logger.warning(f"1000 items took {elapsed*1000:.2f}ms (target: <500ms)")
    
    def test_performance_clear_large_dataset(self):
        """Test clearing performance with 1000 items."""
        import time
        
        # First populate
        titles = self._create_large_titles_dict(1000)
        update_treeview_with_titles(titles, treeview_widget=self.treeview)
        
        # Measure clear time
        start = time.time()
        result = update_treeview_with_titles({}, treeview_widget=self.treeview)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        self.assertEqual(len(self.treeview.get_children()), 0)
        
        # Performance assertion (warning, not strict)
        if elapsed > 0.2:
            logger.warning(f"Clearing 1000 items took {elapsed*1000:.2f}ms (target: <200ms)")


if __name__ == '__main__':
    unittest.main()
