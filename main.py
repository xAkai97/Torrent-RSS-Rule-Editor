#!/usr/bin/env python
"""
Torrent RSS Rule Editor - Main Entry Point (Modular Version)

A desktop GUI for generating and synchronizing qBittorrent RSS rules.
This is the new modular entry point that imports from the src package.

Usage:
    python main.py
"""
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _resolve_ui_mode(argv: list[str] | None = None) -> str:
    """Resolve UI mode from CLI or environment.

    Priority: CLI flag (--ui=...) then env var TRRE_UI, defaulting to qt.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    cli_mode = ''
    for idx, arg in enumerate(args):
        if arg.startswith('--ui='):
            cli_mode = arg.split('=', 1)[1].strip().lower()
            break
        if arg == '--ui' and idx + 1 < len(args):
            cli_mode = str(args[idx + 1]).strip().lower()
            break

    env_mode = str(os.getenv('TRRE_UI', '')).strip().lower()
    mode = cli_mode or env_mode or 'qt'
    if mode not in {'tk', 'qt'}:
        return 'qt'
    return mode


def _run_tk_gui() -> None:
    """Launch the legacy Tkinter fallback UI path."""
    logger.warning("Launching legacy Tk fallback UI (--ui=tk).")
    from src.gui import setup_gui, exit_handler

    exit_handler()
    setup_gui()


def _run_qt_gui() -> None:
    """Launch the default PySide6 UI path."""
    from src.gui_qt import setup_gui_qt

    setup_gui_qt()


def main(argv: list[str] | None = None):
    """Main entry point for the application."""
    log_level_str = 'INFO'
    ui_mode = 'qt'
    try:
        # Import config first to get log level preference
        from src.config import config
        
        # Get log level from preferences, default to INFO
        try:
            log_level_str = config.get_pref('log_level', 'INFO').upper()
            if log_level_str not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                log_level_str = 'INFO'
            log_level = getattr(logging, log_level_str)
        except Exception:
            log_level = logging.INFO
        
        # Configure logging with preference
        logging.basicConfig(
            filename='qbt_editor.log',
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            encoding='utf-8'
        )

        logger.info("Starting Torrent RSS Rule Editor (Modular Version)")
        logger.info(f"Log level: {log_level_str}")
        logger.info("GUI Modularization: COMPLETE - 100% modular architecture")

        ui_mode = _resolve_ui_mode(argv)
        logger.info(f"UI mode: {ui_mode}")
        if ui_mode == 'qt':
            _run_qt_gui()
        else:
            _run_tk_gui()
        
    except ImportError as e:
        err_text = str(e)
        is_qt_import_error = ('PySide6' in err_text) or ('src.gui_qt' in err_text)
        print("=" * 60)
        if is_qt_import_error:
            print("ERROR: Qt mode is unavailable")
            print("=" * 60)
            print(f"\nDetails: {e}")
            print("\nPossible solutions:")
            print("  1. Install optional Qt dependency: pip install PySide6")
            print("  2. Or run the Tk fallback UI: python main.py --ui=tk")
            print()
        else:
            print("ERROR: Failed to import required modules")
            print("=" * 60)
            print(f"\nDetails: {e}")
            print("\nPossible solutions:")
            print("  1. Make sure you're running from the project root directory")
            print("  2. Install required dependencies: pip install -r requirements.txt")
            print()
        logger.error(f"Import error: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        print("=" * 60)
        print("ERROR: An unexpected error occurred")
        print("=" * 60)
        print(f"\nDetails: {e}")
        print("\nPlease check 'qbt_editor.log' for more information.")
        print()
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
