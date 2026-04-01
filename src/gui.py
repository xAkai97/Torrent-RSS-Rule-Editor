"""
GUI module - Main application interface.

GUI modularization is complete.

The GUI is organized into modules under src/gui:

Structure:
----------
src/gui/
├── __init__.py           - Package initialization
├── app_state.py          - Shared application state
├── main_window.py        - Main window setup and event flow
├── dialogs.py            - Dialog windows
├── file_operations.py    - Import/export workflows
├── helpers.py            - GUI helper utilities
├── treeview_adapter.py   - Treeview abstraction layer
└── widgets.py            - Reusable components

Usage:
------
from src.gui import setup_gui, exit_handler

root = setup_gui()
root.mainloop()
"""
from src.gui.main_window import setup_gui, exit_handler
from src.gui.dialogs import open_settings_window

__all__ = ["setup_gui", "exit_handler", "open_settings_window"]

