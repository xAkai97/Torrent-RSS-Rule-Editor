"""
UI Constants and Configuration

Centralized storage for magic numbers, timing constants, and UI strings.
"""


class UIConstants:
    """UI-related constants and magic numbers."""
    # Window sizing
    DEFAULT_WINDOW_WIDTH = 1400
    DEFAULT_WINDOW_HEIGHT = 900
    MIN_WINDOW_WIDTH = 900
    MIN_WINDOW_HEIGHT = 600
    
    # Editor panel
    EDITOR_AUTO_APPLY_DEBOUNCE_MS = 300
    EDITOR_LASTMATCH_TIMEOUT_MIN = 10
    
    # Status chips and display
    STATUS_CHIP_REFRESH_MS = 700
    PANED_SASH_SAVE_DELAY_MS = 100
    FILTER_SUMMARY_REFRESH_MS = 500
    
    # Treeview
    TREEVIEW_ROWHEIGHT_FACTOR = 2
    TREEVIEW_ROWHEIGHT_PADDING = 6
    COLUMN_CHAR_WIDTH_PX = 7
    COLUMN_PADDING_PX = 20
    MAX_COLUMN_WIDTH_PX = 600
    COLUMN_AUTO_FIT_MIN_WIDTH = 80
    
    # Sync and API
    SYNC_COOLDOWN_CHECK_INTERVAL = 60
    SUBSPLEASE_CACHE_REFRESH_DEBOUNCE_MS = 500
    
    # Undo stack
    MAX_UNDO_STACK_SIZE = 10
    
    # UI Strings
    NO_RECENT_FILES = '(No recent files)'
    ALREADY_APPLIED = '(Already in Match Pattern)'
    NO_SUBSPLEASE_MATCH = '(No matching SubsPlease title in cache)'
    
    # Enabled state markers
    ENABLED_MARK = '✓'
    DISABLED_MARK = ''
