"""
Background Worker Threads — Non-Blocking GUI Operations.

Qt requires that long-running operations (network requests, file I/O) run
in background threads to keep the GUI responsive. This module provides
QThread-based workers for each async operation the app needs.

Each worker:
  1. Runs a service function in a background thread
  2. Emits a `finished` signal with a result dict when done
  3. Catches all exceptions and includes error info in the result

The GUI connects to the `finished` signal to update the UI when
the operation completes.

Why lazy imports: The workers import their service functions inside run()
to avoid circular imports (the main window module also imports workers).
"""

import logging
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ConnectionTestWorker(QThread):
    """
    Background worker for testing qBittorrent server connectivity.

    Emits a dict with 'success' (bool) and 'message' (str) keys.
    """
    finished = Signal(dict)

    def run(self):
        try:
            from src.gui_qt.main_window import run_qt_connection_test
            res = run_qt_connection_test()
            self.finished.emit(res)
        except Exception as e:
            logger.error(f"Error in ConnectionTestWorker: {e}", exc_info=True)
            self.finished.emit({'success': False, 'message': f'Worker thread error: {e}'})


class FetchRulesWorker(QThread):
    """
    Background worker for fetching a read-only snapshot of qBittorrent state.

    Fetches categories, feeds, and rules from the server. Emits a snapshot
    dict containing the fetched data (or error messages for failed sections).
    """
    finished = Signal(dict)

    def run(self):
        try:
            from src.gui_qt.main_window import run_qt_qbittorrent_snapshot
            res = run_qt_qbittorrent_snapshot()
            self.finished.emit(res)
        except Exception as e:
            logger.error(f"Error in FetchRulesWorker: {e}", exc_info=True)
            self.finished.emit({
                'success': False,
                'message': f'Worker thread error: {e}',
                'rules': {},
                'categories': {},
                'feeds': {},
                'rules_error': str(e)
            })


class ApplyRulesWorker(QThread):
    """
    Background worker for pushing rule changes to the qBittorrent server.

    Takes a list of change dicts (from a dry-run plan) and applies them
    one by one. Supports partial failure — some rules may succeed while
    others fail.

    Emits a result dict with applied_count, failed_count, and rollback_guidance.
    """
    finished = Signal(dict)

    def __init__(self, changes):
        super().__init__()
        self.changes = changes  # List of change dicts from build_rule_sync_dry_run()

    def run(self):
        try:
            from src.gui_qt.main_window import run_qt_apply_rule_sync
            res = run_qt_apply_rule_sync(self.changes)
            self.finished.emit(res)
        except Exception as e:
            logger.error(f"Error in ApplyRulesWorker: {e}", exc_info=True)
            self.finished.emit({
                'success': False,
                'applied_count': 0,
                'failed_count': len(self.changes),
                'rollback_guidance': f'Worker thread error: {e}'
            })


class SubsPleaseRefreshWorker(QThread):
    """
    Background worker for refreshing the SubsPlease schedule cache.

    Fetches the latest anime schedule from SubsPlease and updates the
    local cache. Respects cooldown timers to prevent rate-limiting.

    Emits a status payload with fetch_status, app_status, and
    should_update_variations flag.
    """
    finished = Signal(dict)

    def run(self):
        try:
            from src.gui_qt.main_window import run_qt_subsplease_refresh
            res = run_qt_subsplease_refresh()
            self.finished.emit(res)
        except Exception as e:
            logger.error(f"Error in SubsPleaseRefreshWorker: {e}", exc_info=True)
            self.finished.emit({
                'fetch_status': f'❌ Worker thread error: {e}',
                'app_status': '',
                'should_update_variations': False
            })


class AniListRefreshWorker(QThread):
    """
    Background worker for refreshing AniList title variations cache.

    Queries AniList's GraphQL API for title synonyms (Romaji, English,
    Native, etc.) and updates the local variations cache. Supports
    two refresh scopes: title-only and title+season.

    Args (passed to constructor):
        current_title: The title being edited.
        current_must: The current mustContain pattern.
        selected_season / selected_year: For season-scoped refresh.
        refresh_scope_override: 'title_only' or 'title_and_season'.
    """
    finished = Signal(dict)

    def __init__(self, current_title: str, current_must: str, selected_season: str, selected_year: str, refresh_scope_override: str):
        super().__init__()
        self.current_title = current_title
        self.current_must = current_must
        self.selected_season = selected_season
        self.selected_year = selected_year
        self.refresh_scope_override = refresh_scope_override

    def run(self):
        try:
            from src.gui_qt.main_window import run_qt_anilist_refresh
            res = run_qt_anilist_refresh(
                current_title=self.current_title,
                current_must=self.current_must,
                selected_season=self.selected_season,
                selected_year=self.selected_year,
                refresh_scope_override=self.refresh_scope_override
            )
            self.finished.emit(res)
        except Exception as e:
            logger.error(f"Error in AniListRefreshWorker: {e}", exc_info=True)
            self.finished.emit({
                'fetch_status': f'❌ Worker thread error: {e}',
                'app_status': '',
                'should_update_variations': False
            })
