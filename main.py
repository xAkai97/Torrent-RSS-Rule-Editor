#!/usr/bin/env python
"""
Torrent RSS Rule Editor - Main Entry Point

A desktop GUI for generating and synchronizing qBittorrent RSS rules.
Built with PySide6 (Qt).

Usage:
    python main.py
"""
import logging
import sys

logger = logging.getLogger(__name__)


def main():
    """Main entry point for the application."""
    log_level_str = 'INFO'
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
            filename=getattr(config, 'LOG_FILE', 'data/qbt_editor.log'),
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            encoding='utf-8'
        )

        logger.info("Starting Torrent RSS Rule Editor")
        logger.info(f"Log level: {log_level_str}")

        from src.gui_qt import setup_gui_qt
        setup_gui_qt()
        
    except ImportError as e:
        err_text = str(e)
        is_qt_import_error = ('PySide6' in err_text) or ('src.gui_qt' in err_text)
        print("=" * 60)
        if is_qt_import_error:
            print("ERROR: PySide6 is required but not installed")
            print("=" * 60)
            print(f"\nDetails: {e}")
            print("\nSolution:")
            print("  pip install PySide6")
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

