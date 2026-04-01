"""
Application state management for GUI.

This module manages global state that was previously stored in module-level variables.
Provides a clean interface for accessing and updating application state.
"""
# Standard library imports
import logging
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AppState:
    """
    Centralized application state manager.
    
    Replaces module-level global variables with a clean singleton pattern.
    """
    
    _instance: Optional['AppState'] = None
    
    def __init__(self):
        # Main window reference
        self._root: Optional[tk.Tk] = None
        self._status_var: Optional[tk.StringVar] = None
        
        # Treeview widget (the main title list)
        self._treeview_widget: Optional[tk.Widget] = None
        self._tree_adapter: Optional[Any] = None
        
        # Search/Filter entry widget
        self._search_entry: Optional[tk.Widget] = None
        self._search_var: Optional[tk.StringVar] = None
        
        # Listbox items: List of (title_text, entry_dict) tuples
        self._listbox_items: List[Tuple[str, Dict[str, Any]]] = []
        
        # Trash for undo functionality: List of deleted items
        self._trash_items: List[Dict[str, Any]] = []
    
    @classmethod
    def get_instance(cls) -> 'AppState':
        """
        Get the singleton instance of AppState.
        
        Returns:
            AppState: The global application state manager
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # Root window properties
    @property
    def root(self) -> Optional[tk.Tk]:
        """Get the main application window."""
        return self._root
    
    @root.setter
    def root(self, value: tk.Tk) -> None:
        """Set the main application window."""
        self._root = value
    
    @property
    def status_var(self) -> Optional[tk.StringVar]:
        """Get the status bar variable."""
        return self._status_var
    
    @status_var.setter
    def status_var(self, value: tk.StringVar) -> None:
        """Set the status bar variable."""
        self._status_var = value
    
    def set_status(self, message: str) -> None:
        """
        Set status bar message.
        
        Args:
            message: Status message to display
        """
        if self._status_var:
            self._status_var.set(message)
    
    # Treeview widget properties
    @property
    def treeview(self) -> Optional[tk.Widget]:
        """Get the main treeview widget."""
        return self._treeview_widget
    
    @property
    def treeview_widget(self) -> Optional[tk.Widget]:
        """Alias for treeview property for backward compatibility."""
        return self._treeview_widget
    
    @treeview.setter
    def treeview(self, value: tk.Widget) -> None:
        """Set the main treeview widget."""
        self._treeview_widget = value
    
    @treeview_widget.setter
    def treeview_widget(self, value: tk.Widget) -> None:
        """Alias for treeview setter for backward compatibility."""
        self._treeview_widget = value

    @property
    def tree_adapter(self) -> Optional[Any]:
        """Get the centralized tree adapter instance."""
        return self._tree_adapter

    @tree_adapter.setter
    def tree_adapter(self, value: Any) -> None:
        """Set the centralized tree adapter instance."""
        self._tree_adapter = value
    
    # Search entry properties
    @property
    def search_entry(self) -> Optional[tk.Widget]:
        """Get the search/filter entry widget."""
        return self._search_entry
    
    @search_entry.setter
    def search_entry(self, value: tk.Widget) -> None:
        """Set the search/filter entry widget."""
        self._search_entry = value
    
    @property
    def search_var(self) -> Optional[tk.StringVar]:
        """Get the search/filter StringVar."""
        return self._search_var
    
    @search_var.setter
    def search_var(self, value: tk.StringVar) -> None:
        """Set the search/filter StringVar."""
        self._search_var = value
    
    def focus_search(self) -> None:
        """Focus the search entry and select all text."""
        if self._search_entry:
            self._search_entry.focus_set()
            self._search_entry.select_range(0, 'end')
    
    def clear_search(self) -> None:
        """Clear the search filter."""
        if self._search_var:
            self._search_var.set("")

    # Listbox items properties
    @property
    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Get the list of title items."""
        return self._listbox_items
    
    @property
    def listbox_items(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Alias for items property for backward compatibility."""
        return self._listbox_items
    
    @items.setter
    def items(self, value: List[Tuple[str, Dict[str, Any]]]) -> None:
        """Set the list of title items."""
        self._listbox_items = value
    
    @listbox_items.setter
    def listbox_items(self, value: List[Tuple[str, Dict[str, Any]]]) -> None:
        """Alias for items setter for backward compatibility."""
        self._listbox_items = value
    
    def add_item(self, title: str, entry: Dict[str, Any]) -> None:
        """
        Add a title item to the list.
        
        Args:
            title: Title text
            entry: Entry dictionary with rule configuration
        """
        self._listbox_items.append((title, entry))
    
    def remove_item(self, index: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Remove a title item by index.
        
        Args:
            index: Index of item to remove
            
        Returns:
            Removed item tuple or None if index invalid
        """
        if 0 <= index < len(self._listbox_items):
            return self._listbox_items.pop(index)
        return None
    
    def get_item(self, index: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Get a title item by index.
        
        Args:
            index: Index of item to get
            
        Returns:
            Item tuple or None if index invalid
        """
        if 0 <= index < len(self._listbox_items):
            return self._listbox_items[index]
        return None
    
    def clear_items(self) -> None:
        """Clear all title items."""
        self._listbox_items.clear()
    
    def item_count(self) -> int:
        """Get the number of title items."""
        return len(self._listbox_items)
    
    # Trash properties
    @property
    def trash(self) -> List[Dict[str, Any]]:
        """Get the trash items list."""
        return self._trash_items
    
    @property
    def trash_items(self) -> List[Dict[str, Any]]:
        """Alias for trash property for backward compatibility."""
        return self._trash_items
    
    def add_to_trash(self, item: Dict[str, Any]) -> None:
        """
        Add an item to trash for undo functionality.
        
        Args:
            item: Dictionary containing deleted item info
        """
        self._trash_items.append(item)
    
    def pop_from_trash(self) -> Optional[Dict[str, Any]]:
        """
        Remove and return the most recent trash item.
        
        Returns:
            Most recent trash item or None if trash is empty
        """
        if self._trash_items:
            return self._trash_items.pop()
        return None
    
    def clear_trash(self) -> None:
        """Clear all items from trash."""
        self._trash_items.clear()
    
    def trash_count(self) -> int:
        """Get the number of items in trash."""
        return len(self._trash_items)


# Global singleton instance
_app_state = None


def get_app_state() -> AppState:
    """
    Get the global application state instance.
    
    Returns:
        AppState: The global application state manager
    """
    global _app_state
    if _app_state is None:
        _app_state = AppState.get_instance()
    return _app_state


# Convenience functions for backward compatibility
def get_root() -> Optional[tk.Tk]:
    """Get the main application window."""
    if _app_state is None:
        return None
    return _app_state.root


def get_status_var() -> Optional[tk.StringVar]:
    """Get the status bar variable."""
    if _app_state is None:
        return None
    return _app_state.status_var


def get_treeview() -> Optional[tk.Widget]:
    """Get the main treeview widget."""
    if _app_state is None:
        return None
    return _app_state.treeview


def get_items() -> List[Tuple[str, Dict[str, Any]]]:
    """Get the list of title items."""
    if _app_state is None:
        return []
    return _app_state.items


def get_trash() -> List[Dict[str, Any]]:
    """Get the trash items list."""
    if _app_state is None:
        return []
    return _app_state.trash


__all__ = [
    'AppState',
    'get_app_state',
    'get_root',
    'get_status_var',
    'get_treeview',
    'get_items',
    'get_trash',
]
