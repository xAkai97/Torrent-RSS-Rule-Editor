"""
GUI Package for Torrent RSS Rule Editor

This package contains all GUI-related modules organized by responsibility:
- app_state: Centralized application state management
- helpers: GUI utility functions
- widgets: Reusable widget components (ToolTip, ScrollableFrame)
- dialogs: Dialog windows (settings, log viewer, trash, advanced editor)
- file_operations: Import/export functionality with merge logic
- main_window: Main application window setup and all GUI components

Phase 3: GUI Modularization - ✅ COMPLETE (100%)
=================================================
✅ app_state.py - Complete (Singleton pattern, global state)
✅ helpers.py - Complete (Utility functions, datetime parsing, JSON validation)
✅ widgets.py - Complete (ToolTip, ScrollableFrame, helpers)
✅ dialogs.py - Complete (Settings, Log Viewer, Trash, Advanced Editor)
✅ file_operations.py - Complete (Import/Export with merge logic)
✅ main_window.py - Complete (Fully modular GUI setup)

Modularization Achievement:
- Extracted 2,350+ lines from monolithic setup_gui()
- 6 specialized modules with clear responsibilities
- Zero dependencies on legacy code
- All functionality tested and validated
"""

# Main window setup - Primary GUI entry point
from .main_window import setup_gui, exit_handler

# Dialogs - All dialog windows
from .dialogs import (
    open_settings_window,
    open_log_viewer,
    view_trash_dialog,
    open_full_rule_editor
)

# File operations - Import/Export functionality
from .file_operations import (
    import_titles_from_file,
    import_titles_from_clipboard,
    import_titles_from_text,
    export_selected_titles,
    export_all_titles,
    clear_all_titles,
    update_treeview_with_titles
)

# App state - Centralized state management
from .app_state import AppState

# Helpers - Utility functions
from .helpers import (
    parse_datetime_from_string,
    validate_json_string,
    center_window
)

# Widgets - Reusable components
from .widgets import (
    ToolTip,
    ScrollableFrame,
    create_labeled_entry,
    create_labeled_text
)

__all__ = [
    # Main window
    'setup_gui',
    'exit_handler',
    
    # Dialogs
    'open_settings_window',
    'open_log_viewer',
    'view_trash_dialog',
    'open_full_rule_editor',
    
    # File operations
    'import_titles_from_file',
    'import_titles_from_clipboard',
    'import_titles_from_text',
    'export_selected_titles',
    'export_all_titles',
    'clear_all_titles',
    'update_treeview_with_titles',
    
    # State management
    'AppState',
    
    # Helpers
    'parse_datetime_from_string',
    'validate_json_string',
    'center_window',
    
    # Widgets
    'ToolTip',
    'ScrollableFrame',
    'create_labeled_entry',
    'create_labeled_text',
]

__version__ = "1.0.0"  # Phase 3 Complete - Fully Modular!
