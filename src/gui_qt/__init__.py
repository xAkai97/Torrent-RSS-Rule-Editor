"""
Qt GUI Package — PySide6 Application Entry Point.

This package contains the primary Qt-based GUI for the application.
The main entry point is setup_gui_qt(), which creates and shows
the main window with all panels, toolbars, and dialogs.

Submodules:
  - main_window             → Main application window (5000+ lines)
  - settings_dialog         → Settings/preferences dialog
  - setup_wizard_dialog     → First-run setup wizard
  - batch_downloader_dialog → Bulk episode download dialog
  - cache_viewer_dialog     → SubsPlease/AniList cache inspector
  - log_viewer_dialog       → Application log viewer
  - theme                   → Material 3 color palettes and stylesheet generation
  - workers                 → QThread background workers for non-blocking operations
"""

from .main_window import setup_gui_qt

__all__ = ["setup_gui_qt"]
