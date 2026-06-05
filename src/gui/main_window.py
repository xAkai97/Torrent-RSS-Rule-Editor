"""
Main window setup and GUI initialization.

This module contains functions for setting up the main application window,
including window geometry, styling, menu bar, and event handlers.

"""

# Standard library imports
import logging
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, Tuple

# Local application imports
import src.api.qbittorrent as qbt_api
from src.config import config
from src.constants import AniListRefreshScope, PrefKeys
from src.gui.app_state import AppState
from src.gui.dialogs import open_settings_window, open_setup_wizard
from src.gui.file_operations import (
    clear_all_titles,
    import_titles_from_clipboard,
    import_titles_from_file,
    import_titles_from_text,
    update_treeview_with_titles,
)
from src.gui.helpers import enable_global_mousewheel_scrolling, get_ui_font, get_ui_font_size, get_ui_mono_font
from src.gui.helpers.constants import UIConstants
from src.gui.helpers.parsers import parse_datetime_from_string
from src.gui.helpers.theme import get_editor_theme_colors, get_ui_theme_colors
from src.gui.helpers.variables import create_editor_variables
from src.gui.components.feed_lookup import (
    render_anilist_variations,
)
from src.services.rule_editor import (
    build_rule_editor_feed_state,
    run_anilist_refresh,
    run_subsplease_refresh,
)
from src.services.connection_status import (
    build_qbittorrent_ping_args,
    evaluate_setup_wizard_trigger,
    get_connection_status_text,
    has_online_host_port,
)
from src.services.gui_bindings import (
    bind_all_shortcuts,
    build_keyboard_shortcut_actions,
    first_json_path,
    parse_dropped_paths,
)
from src.services.rule_sync import merge_existing_rule_entries
from src.gui.components.editor_apply import (
    apply_editor_values_to_entry,
    editor_has_changes,
    parse_lastmatch_input,
)
from src.gui.components.editor_persistence import (
    persist_editor_entry_and_refresh_view,
)
from src.gui.components.lastmatch import format_lastmatch_value, validate_lastmatch_json_text
from src.gui.treeview_adapter import TreeviewAdapter
from src.utils import (
    get_category_save_path,
    get_current_anime_season,
    get_display_title,
    get_rule_name,
    sanitize_folder_name,
    get_server_display_name,
)

logger = logging.getLogger(__name__)


def create_tooltip(widget: tk.Widget, text: str) -> None:
    """
    Creates a tooltip for a widget that appears on hover.
    
    Args:
        widget: The tkinter widget to attach the tooltip to
        text: The tooltip text to display
    """
    tooltip_window = None

    colors = get_editor_theme_colors()
    tooltip_bg = colors['tooltip_bg']
    tooltip_fg = colors['tooltip_fg']
    
    def on_enter(event):
        nonlocal tooltip_window
        tooltip_window = tk.Toplevel(widget)
        tooltip_window.wm_overrideredirect(True)

        label = tk.Label(
            tooltip_window,
            text=text,
            justify='left',
            background=tooltip_bg,
            foreground=tooltip_fg,
            relief='solid',
            borderwidth=1,
            font=get_ui_font(size_delta=0),
            wraplength=420,
            padx=6,
            pady=4,
        )
        label.pack()

        # Keep tooltip fully visible inside the app window on multi-monitor setups.
        try:
            tooltip_window.update_idletasks()
            tip_w = int(tooltip_window.winfo_reqwidth())
            tip_h = int(tooltip_window.winfo_reqheight())
        except Exception:
            tip_w = 200
            tip_h = 40

        try:
            host = widget.winfo_toplevel()
            host_left = int(host.winfo_rootx())
            host_top = int(host.winfo_rooty())
            host_right = host_left + int(host.winfo_width())
            host_bottom = host_top + int(host.winfo_height())
        except Exception:
            host_left = 0
            host_top = 0
            host_right = host_left + int(widget.winfo_screenwidth())
            host_bottom = host_top + int(widget.winfo_screenheight())

        margin = 8
        x = int(widget.winfo_rootx()) + 18
        y = int(widget.winfo_rooty()) + int(widget.winfo_height()) + 8

        if x + tip_w > host_right - margin:
            x = host_right - tip_w - margin
        if x < host_left + margin:
            x = host_left + margin

        if y + tip_h > host_bottom - margin:
            y = int(widget.winfo_rooty()) - tip_h - 8
        if y < host_top + margin:
            y = host_top + margin

        tooltip_window.wm_geometry(f"+{x}+{y}")
    
    def on_leave(event):
        nonlocal tooltip_window
        if tooltip_window:
            try:
                tooltip_window.destroy()
            except tk.TclError:
                logger.debug("Tooltip already destroyed", exc_info=True)
            tooltip_window = None
    
    widget.bind('<Enter>', on_enter)
    widget.bind('<Leave>', on_leave)
    widget.bind('<ButtonPress>', on_leave)


def setup_window_and_styles(root: tk.Tk) -> Tuple[ttk.Style, tk.StringVar, tk.StringVar]:
    """
    Configures the main window geometry, theme, and styles.
    
    Sets up window size, position, minimum size, background color,
    and configures all ttk widget styles with a modern look.
    
    Args:
        root: Tkinter root window
        
    Returns:
        Tuple of (style, season_var, year_var):
            - style: Configured ttk.Style object
            - season_var: StringVar for season selection
            - year_var: StringVar for year selection
    """
    root.title("Torrent RSS Rules Editor")

    try:
        saved_geometry = config.get_pref('main_window_geometry', '')
    except Exception:
        saved_geometry = ''
    
    # Position window away from taskbar
    from src.constants import UIConfig
    try:
        if saved_geometry and isinstance(saved_geometry, str) and 'x' in saved_geometry and '+' in saved_geometry:
            root.geometry(saved_geometry)
        else:
            # Open on the monitor under the cursor instead of always using primary display.
            cursor_x = root.winfo_pointerx()
            cursor_y = root.winfo_pointery()

            monitor_left = 0
            monitor_top = 0
            monitor_width = root.winfo_screenwidth()
            monitor_height = root.winfo_screenheight()

            try:
                if sys.platform == 'win32':
                    import ctypes

                    class _POINT(ctypes.Structure):
                        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

                    class _RECT(ctypes.Structure):
                        _fields_ = [
                            ('left', ctypes.c_long),
                            ('top', ctypes.c_long),
                            ('right', ctypes.c_long),
                            ('bottom', ctypes.c_long),
                        ]

                    class _MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ('cbSize', ctypes.c_ulong),
                            ('rcMonitor', _RECT),
                            ('rcWork', _RECT),
                            ('dwFlags', ctypes.c_ulong),
                        ]

                    user32 = ctypes.windll.user32
                    pt = _POINT(int(cursor_x), int(cursor_y))
                    monitor = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
                    if monitor:
                        mi = _MONITORINFO()
                        mi.cbSize = ctypes.sizeof(_MONITORINFO)
                        if user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
                            monitor_left = int(mi.rcWork.left)
                            monitor_top = int(mi.rcWork.top)
                            monitor_width = int(mi.rcWork.right - mi.rcWork.left)
                            monitor_height = int(mi.rcWork.bottom - mi.rcWork.top)
            except Exception:
                logger.debug("Could not resolve active monitor geometry", exc_info=True)

            # Clamp initial size to visible work area of active monitor.
            window_width = min(UIConfig.DEFAULT_WINDOW_WIDTH, max(960, monitor_width - 40))
            window_height = min(UIConfig.DEFAULT_WINDOW_HEIGHT, max(640, monitor_height - 90))
            x = monitor_left + max((monitor_width - window_width) // 2, 0)
            y = monitor_top + max(min(UIConfig.WINDOW_TOP_MARGIN, monitor_height - window_height), 0)
            root.geometry(f"{window_width}x{window_height}+{x}+{y}")
    except Exception:
        root.geometry(f"{UIConfig.DEFAULT_WINDOW_WIDTH}x{UIConfig.DEFAULT_WINDOW_HEIGHT}")

    try:
        min_width = min(UIConfig.MIN_WINDOW_WIDTH, max(900, root.winfo_screenwidth() - 80))
        min_height = min(UIConfig.MIN_WINDOW_HEIGHT, max(600, root.winfo_screenheight() - 140))
        root.minsize(min_width, min_height)
    except Exception:
        root.minsize(UIConfig.MIN_WINDOW_WIDTH, UIConfig.MIN_WINDOW_HEIGHT)

    _geometry_save_job = {'id': None}

    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    # Get font size preference for row height calculation
    try:
        font_size_pref = int(config.get_pref('font_size', 10))
    except (TypeError, ValueError):
        font_size_pref = 10

    # Get theme-aware colors for all UI components
    theme_colors = get_ui_theme_colors(font_size_pref)
    theme_pref = theme_colors.pop('theme_pref')
    bg_color = theme_colors['bg_color']
    frame_bg = theme_colors['frame_bg']
    text_color = theme_colors['text_color']
    button_bg = theme_colors['button_bg']
    button_text = theme_colors['button_text']
    button_hover = theme_colors['button_hover']
    button_pressed = theme_colors['button_pressed']
    button_disabled_bg = theme_colors['button_disabled_bg']
    button_disabled_text = theme_colors['button_disabled_text']
    accent_color = theme_colors['accent_color']
    accent_hover = theme_colors['accent_hover']
    accent_pressed = theme_colors['accent_pressed']
    border_color = theme_colors['border_color']
    tree_field_bg = theme_colors['tree_field_bg']
    tree_select_bg = theme_colors['tree_select_bg']
    tree_select_fg = theme_colors['tree_select_fg']
    danger_bg = theme_colors['danger_bg']
    danger_border = theme_colors['danger_border']
    danger_hover = theme_colors['danger_hover']
    danger_pressed = theme_colors['danger_pressed']
    tree_bg = theme_colors['tree_bg']
    tree_fg = theme_colors['tree_fg']
    tree_heading_bg = theme_colors['tree_heading_bg']
    tree_heading_fg = theme_colors['tree_heading_fg']
    
    root.configure(bg=bg_color)

    # Keep classic Tk widgets in sync with ttk style font settings.
    root.option_add('*Font', get_ui_font())
    root.option_add('*Menu*Font', get_ui_font())
    root.option_add('*Text.Font', get_ui_mono_font())
    
    # Configure styles with theme colors and font size
    # Note: '.' is not a valid ttk style name, skip it
    style.configure('TFrame', background=frame_bg)
    style.configure('TLabelFrame', background=frame_bg, bordercolor=border_color, relief='flat')
    style.configure('TLabelFrame.Label', background=frame_bg, foreground=text_color, font=get_ui_font(weight='bold'))
    style.configure('TLabel', background=frame_bg, foreground=text_color, font=get_ui_font())
    style.configure('TCheckbutton', background=frame_bg, foreground=text_color, focuscolor=accent_color)
    style.configure(
        'TButton',
        padding=6,
        relief='raised',
        borderwidth=1,
        background=button_bg,
        foreground=button_text,
        bordercolor=border_color,
        lightcolor=button_hover,
        darkcolor=button_pressed,
        font=get_ui_font(),
    )
    style.map(
        'TButton',
        background=[('pressed', button_pressed), ('active', button_hover), ('disabled', button_disabled_bg)],
        foreground=[('disabled', button_disabled_text)],
        bordercolor=[('active', accent_color), ('pressed', accent_color)],
    )
    style.configure(
        'Accent.TButton',
        foreground='white',
        background=accent_color,
        bordercolor=accent_color,
        lightcolor=accent_hover,
        darkcolor=accent_pressed,
        borderwidth=1,
        font=get_ui_font(weight='bold'),
    )
    style.map(
        'Accent.TButton',
        background=[('pressed', accent_pressed), ('active', accent_hover), ('disabled', button_disabled_bg)],
        foreground=[('disabled', button_disabled_text)],
        bordercolor=[('active', accent_hover), ('pressed', accent_pressed)],
    )
    style.configure('RefreshButton.TButton', font=get_ui_font(size_delta=9), padding=0)
    style.configure('TCombobox',
                    padding=5,
                    fieldbackground=tree_field_bg,
                    background=frame_bg,
                    foreground=text_color,
                    selectbackground=tree_select_bg,
                    selectforeground=tree_select_fg)
    style.map('TCombobox',
              fieldbackground=[('readonly', tree_field_bg)],
              foreground=[('readonly', text_color)])
    style.configure('TSpinbox',
                    fieldbackground=tree_field_bg,
                    background=frame_bg,
                    foreground=text_color)
    style.configure('TMenubutton',
                    background=frame_bg,
                    foreground=text_color)
    style.configure('TEntry', padding=5, fieldbackground=tree_field_bg, foreground=text_color)
    style.configure('TNotebook', background=bg_color, borderwidth=0)
    style.configure('TNotebook.Tab',
                    background=frame_bg,
                    foreground=text_color,
                    padding=(10, 6),
                    borderwidth=0)
    style.map('TNotebook.Tab',
              background=[('selected', accent_color), ('active', accent_hover)],
              foreground=[('selected', '#ffffff')])
    
    # Secondary button style
    style.configure('Secondary.TButton', foreground='white', background='#5c636a', font=get_ui_font())
    style.map('Secondary.TButton', background=[('active', '#4a5056')])
    style.configure(
        'Danger.TButton',
        foreground='white',
        background=danger_bg,
        bordercolor=danger_border,
        lightcolor=danger_hover,
        darkcolor=danger_pressed,
        borderwidth=1,
        font=get_ui_font(weight='bold'),
    )
    style.map(
        'Danger.TButton',
        background=[('pressed', danger_pressed), ('active', danger_hover), ('disabled', button_disabled_bg)],
        foreground=[('disabled', button_disabled_text)],
        bordercolor=[('active', danger_hover), ('pressed', danger_pressed)],
    )
    
    # Configure scrollbar colors
    style.configure('TScrollbar', background=frame_bg, troughcolor=bg_color)
    
    # Configure treeview styles with theme colors and font size
    style.configure('Treeview', 
                   background=tree_bg,
                   foreground=tree_fg,
                   fieldbackground=tree_field_bg,
                   rowheight=max(24, font_size_pref * 2 + 6),
                   font=get_ui_font())
    style.configure('Treeview.Heading',
                   background=tree_heading_bg,
                   foreground=tree_heading_fg,
                   font=get_ui_font(weight='bold'))
    style.map('Treeview.Heading', background=[('active', accent_hover)])
    style.map('Treeview', 
             background=[('selected', tree_select_bg)],
             foreground=[('selected', tree_select_fg)])

    if theme_pref == 'dark':
        # Keep drop arrows and indicator glyphs visible on dark backgrounds.
        style.configure('TCombobox', arrowcolor=text_color)
        style.configure('TSpinbox', arrowcolor=text_color)
        style.configure('TMenubutton', arrowcolor=text_color)

        # Improve readability for classic Tk widgets mixed into ttk layouts.
        root.option_add('*Text.Background', '#1a2028')
        root.option_add('*Text.Foreground', text_color)
        root.option_add('*Text.InsertBackground', text_color)
        root.option_add('*Listbox.Background', '#1a2028')
        root.option_add('*Listbox.Foreground', text_color)
        root.option_add('*Listbox.selectBackground', tree_select_bg)
        root.option_add('*Listbox.selectForeground', tree_select_fg)
        root.option_add('*TCombobox*Listbox.background', '#1a2028')
        root.option_add('*TCombobox*Listbox.foreground', text_color)
        root.option_add('*TCombobox*Listbox.selectBackground', tree_select_bg)
        root.option_add('*TCombobox*Listbox.selectForeground', tree_select_fg)

    # Get current anime season
    current_season, current_year = get_current_anime_season()
    season_var = tk.StringVar(value=current_season)
    year_var = tk.StringVar(value=current_year)

    return style, season_var, year_var


def setup_status_and_autoconnect(root: tk.Tk, status_var: tk.StringVar, config_set: bool) -> None:
    """
    Initializes status variable and handles auto-connection to qBittorrent.
    
    Sets up initial connection status message, checks if config exists,
    and optionally auto-connects to qBittorrent based on connection mode.
    
    Args:
        root: Tkinter root window
        status_var: StringVar for status bar
        config_set: Whether configuration was successfully loaded
    """
    status_var.set(get_connection_status_text(config))

    # First-run bootstrap trigger: load_config may have created config.ini with defaults.
    config_file_missing = not os.path.exists(getattr(config, 'CONFIG_FILE', 'config.ini'))
    should_open_wizard, wizard_status = evaluate_setup_wizard_trigger(
        config_set=config_set,
        config_obj=config,
        config_file_exists=(not config_file_missing),
    )

    if should_open_wizard:
        status_var.set(wizard_status)
        root.after(100, lambda: open_setup_wizard(root, status_var))

    def _start_auto_connect_thread():
        """Starts a background thread to automatically connect to qBittorrent."""
        def worker():
            attempts = 0
            while attempts < 3:
                attempts += 1
                try:
                    status_var.set('Auto: attempting qBittorrent connection...')
                    ok, msg = qbt_api.ping_qbittorrent(*build_qbittorrent_ping_args(config))
                    if ok:
                        status_var.set(f'Connected to qBittorrent ({msg})')
                        return
                    else:
                        status_var.set(f'Auto: not connected ({msg})')
                except (qbt_api.APIConnectionError, ConnectionError, TimeoutError, OSError, RuntimeError, ValueError, TypeError):
                    status_var.set('Auto: connection attempt failed')
                time.sleep(2)
        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
        except (RuntimeError, OSError):
            logger.debug("Unable to start auto-connect thread", exc_info=True)

    # Handle auto-connection based on mode
    try:
        if (getattr(config, 'CONNECTION_MODE', '') or '').lower() == 'auto':
            _start_auto_connect_thread()
        elif (getattr(config, 'CONNECTION_MODE', '') or '').lower() == 'online':
            # Auto-test connection for online mode if settings are filled
            def _auto_test_online():
                def worker():
                    try:
                        # Check if required settings are filled
                        if has_online_host_port(config):
                            status_var.set('Testing connection to qBittorrent...')
                            ok, msg = qbt_api.ping_qbittorrent(*build_qbittorrent_ping_args(config))
                            if ok:
                                status_var.set(f'✅ Connected: {msg}')
                            else:
                                status_var.set(f'❌ Connection failed: {msg}')
                        else:
                            status_var.set('Online mode: Connection not tested (missing host/port)')
                    except (qbt_api.APIConnectionError, ConnectionError, TimeoutError, OSError, RuntimeError, ValueError, TypeError) as e:
                        status_var.set(f'Connection test failed: {e}')
                try:
                    t = threading.Thread(target=worker, daemon=True)
                    t.start()
                except (RuntimeError, OSError):
                    logger.debug("Unable to start online auto-test thread", exc_info=True)
            # Delay test slightly to let UI load
            root.after(500, _auto_test_online)
    except (tk.TclError, AttributeError, TypeError):
        logger.debug("Auto-connect scheduling skipped", exc_info=True)


def refresh_treeview_display() -> None:
    """
    Refresh the treeview display with current data from config.ALL_TITLES.
    Useful to fix display issues or synchronize the view with data.
    """
    from src.gui.file_operations import refresh_treeview_display_safe
    refresh_treeview_display_safe()


def setup_menu_bar(
    root: tk.Tk, 
    status_var: tk.StringVar, 
    season_var: tk.StringVar, 
    year_var: tk.StringVar
) -> Tuple[tk.Menu, tk.Menu, tk.Menu, tk.Menu, tk.Menu]:
    """
    Creates and configures the main menu bar.
    
    Sets up File, Edit, Settings, and Info menus with all commands,
    keyboard shortcuts, and recent files menu.
    
    Args:
        root: Tkinter root window
        status_var: StringVar for status bar updates
        season_var: StringVar for current season selection
        year_var: StringVar for current year selection
        
    Returns:
        Tuple of (menubar, recent_menu, edit_menu) for external updates
    """
    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)
    edit_menu = tk.Menu(menubar, tearoff=0)
    
    # File menu
    def _import_file_and_refresh():
        """Import from file and refresh recent menu."""
        result = import_titles_from_file(
            root, status_var, season_var, year_var,
            prefix_imports=config.get_pref('prefix_imports', True)
        )
        if result:
            refresh_recent_menu()
    
    file_menu.add_command(
        label='Import File...',
        accelerator='Ctrl+O', 
        command=_import_file_and_refresh
    )
    file_menu.add_command(
        label='Paste from Clipboard', 
        command=lambda: import_titles_from_clipboard(
            root, status_var, season_var, year_var,
            prefix_imports=config.get_pref('prefix_imports', True)
        )
    )
    recent_menu = tk.Menu(file_menu, tearoff=0)
    file_menu.add_cascade(label='Recent Files', menu=recent_menu)
    file_menu.add_separator()
    file_menu.add_command(
        label='Export to Targets...', 
        accelerator='Ctrl+Shift+S',
        command=lambda: None  # Will be set up later in setup_library_panel
    )
    file_menu.add_separator()
    
    # Backup/Restore commands
    from src.gui.backup_restore import (
        backup_qbittorrent_rules,
        restore_from_backup,
        open_backup_manager
    )
    
    file_menu.add_command(
        label='💾 Backup qBittorrent Rules...',
        command=lambda: backup_qbittorrent_rules(root, status_var)
    )
    file_menu.add_command(
        label='↩️ Restore from Backup...',
        command=lambda: restore_from_backup(root, status_var)
    )
    file_menu.add_command(
        label='📂 Manage Backups...',
        command=lambda: open_backup_manager(root, status_var)
    )
    file_menu.add_separator()
    
    file_menu.add_command(label='Exit', command=root.quit)
    menubar.add_cascade(label='📁 File', menu=file_menu)
    
    # Edit menu
    from src.gui.file_operations import (export_selected_titles, export_all_titles,
                                         clear_all_titles)
    from src.gui.dialogs import view_trash_dialog
    
    # Note: Toggle command will be set up after treeview is created
    # It is a placeholder here and will be configured in setup_library_panel
    edit_menu.add_command(label='🔄 Toggle Enable/Disable', accelerator='Space')
    edit_menu.add_separator()
    edit_menu.add_command(
        label='↶ Undo', 
        accelerator='Ctrl+Z', 
        command=lambda: None  # Will be configured after setup
    )
    edit_menu.add_separator()
    edit_menu.add_command(
        label='📝 Bulk Edit Selected...', 
        accelerator='Ctrl+B', 
        command=lambda: None  # Will be configured after setup
    )
    edit_menu.add_separator()
    edit_menu.add_command(
        label='Clear All Titles', 
        accelerator='Ctrl+Shift+C', 
        command=lambda: clear_all_titles(root, status_var)
    )
    edit_menu.add_command(
        label='Export Selected Titles...', 
        accelerator='Ctrl+E', 
        command=export_selected_titles
    )
    edit_menu.add_command(
        label='Export All Titles...', 
        accelerator='Ctrl+Shift+E', 
        command=lambda: export_all_titles()
    )
    edit_menu.add_separator()
    edit_menu.add_command(
        label='Refresh Treeview', 
        accelerator='F5', 
        command=lambda: refresh_treeview_display()
    )
    edit_menu.add_separator()
    edit_menu.add_command(
        label='View Trash...', 
        command=lambda: view_trash_dialog(root)
    )
    menubar.add_cascade(label='✏️ Edit', menu=edit_menu)

    # Templates menu
    templates_menu = tk.Menu(menubar, tearoff=0)
    templates_menu.add_command(
        label='📋 Apply Template...', 
        accelerator='Ctrl+Shift+T',
        command=lambda: None  # Will be configured after setup
    )
    templates_menu.add_command(
        label='💾 Save as Template...', 
        accelerator='Ctrl+T',
        command=lambda: None  # Will be configured after setup
    )
    templates_menu.add_separator()
    templates_menu.add_command(
        label='📚 Manage Templates...', 
        command=lambda: None  # Will be configured after setup
    )
    menubar.add_cascade(label='📋 Templates', menu=templates_menu)

    def refresh_recent_menu():
        """Refreshes the Recent Files menu with current file history."""
        try:
            recent_menu.delete(0, 'end')
        except Exception:
            pass
        try:
            config.load_recent_files()
            recent_files = getattr(config, 'RECENT_FILES', []) or []
            
            # Filter out non-existent files
            valid_files = [p for p in recent_files if os.path.isfile(p)]
            
            # Update config if files were removed
            if len(valid_files) != len(recent_files):
                config.RECENT_FILES = valid_files
                from src.cache import save_recent_files
                save_recent_files(valid_files)
            
            for path in valid_files:
                def _open_path(p=path):
                    try:
                        # Use import_titles_from_file to get proper merge behavior
                        result = import_titles_from_file(
                            root, status_var, season_var, year_var,
                            prefix_imports=config.get_pref('prefix_imports', True),
                            path=p
                        )
                        if result:
                            from src.gui.file_operations import refresh_treeview_display_safe
                            refresh_treeview_display_safe()
                    except Exception as e:
                        messagebox.showerror(
                            'Open Recent', 
                            f'Failed to open {os.path.basename(p)}: {e}\n\n'
                            'Action: Check if the file still exists and is not corrupted.'
                        )
                
                # Show filename with full path as tooltip-like info
                display_name = os.path.basename(path)
                if len(display_name) > 40:
                    display_name = display_name[:37] + '...'
                label = f"{display_name} ({os.path.dirname(path)})" if len(os.path.dirname(path)) < 50 else display_name
                
                recent_menu.add_command(label=label, command=_open_path)
            
            if valid_files:
                recent_menu.add_separator()
                recent_menu.add_command(
                    label='Clear Recent Files', 
                    command=lambda: (config.clear_recent_files(), refresh_recent_menu())
                )
            else:
                recent_menu.add_command(label='(No recent files)', state='disabled')
        except Exception:
            pass

    refresh_recent_menu()

    # Validate menu
    validate_menu = tk.Menu(menubar, tearoff=0)
    
    def _validate_all_titles():
        """Validates all titles and shows issues in a dialog."""
        try:
            import json
            from src.constants import FileSystem
            from src.gui.app_state import get_app_state
            
            app_state = get_app_state()
            listbox_items = app_state.listbox_items
            
            if not listbox_items:
                messagebox.showinfo('Validation', 'No titles to validate.')
                return
            
            # Use centralized validation function
            from src.utils import validate_folder_name_by_filesystem
            _is_valid_folder_name = validate_folder_name_by_filesystem
            
            # Validate all items
            problems = []
            
            for title_text, entry in listbox_items:
                e = entry if isinstance(entry, dict) else {'node': {'title': str(entry)}}
                
                try:
                    node = e.get('node') or {}
                    node_title = node.get('title') or e.get('mustContain') or title_text
                except Exception:
                    node_title = title_text
                    
                if not node_title or not str(node_title).strip():
                    problems.append(f'❌ Missing title for item: {title_text}')
                
                # Validate lastMatch JSON
                try:
                    lm = e.get('lastMatch', '')
                    if isinstance(lm, str):
                        s = lm.strip()
                        if s and (s.startswith('{') or s.startswith('[') or s.startswith('"')):
                            try:
                                json.loads(s)
                            except Exception as ex:
                                problems.append(f'❌ Invalid JSON lastMatch for "{title_text}": {ex}')
                except Exception:
                    pass
                
                # Validate folder names in save path
                try:
                    # Get the save path
                    save_path = e.get('savePath') or e.get('save_path') or ''
                    if not save_path:
                        tp = e.get('torrentParams') or e.get('torrent_params') or {}
                        save_path = tp.get('save_path') or tp.get('savePath') or ''
                    
                    if save_path:
                        # Validate each folder component in the path
                        path_str = str(save_path).replace('\\', '/')
                        folders = [f for f in path_str.split('/') if f.strip()]
                        
                        for folder in folders:
                            valid, reason = _is_valid_folder_name(folder)
                            if not valid:
                                problems.append(f'❌ Invalid folder in path for "{title_text}": "{folder}" - {reason}')
                                break
                except Exception:
                    pass
            
            # Show results dialog
            result_dlg = tk.Toplevel(root)
            result_dlg.title('Validation Results')
            result_dlg.geometry('700x500')
            result_dlg.transient(root)
            result_dlg.grab_set()
            
            # Header
            header_frame = ttk.Frame(result_dlg, padding=15)
            header_frame.pack(fill='x')
            
            if problems:
                ttk.Label(header_frame, 
                         text=f'⚠️ Found {len(problems)} validation issue(s) in {len(listbox_items)} title(s)',
                         font=('Segoe UI', 11, 'bold'), foreground='#d32f2f').pack(anchor='w')
            else:
                ttk.Label(header_frame, 
                         text=f'✅ All {len(listbox_items)} title(s) validated successfully',
                         font=('Segoe UI', 11, 'bold'), foreground='#2e7d32').pack(anchor='w')
            
            # Issues list
            if problems:
                issues_frame = ttk.LabelFrame(result_dlg, text='Validation Issues', padding=10)
                issues_frame.pack(fill='both', expand=True, padx=15, pady=(0, 15))
                
                issues_text = tk.Text(issues_frame, height=20, font=('Consolas', 9),
                                     wrap='word', bg='#fff3cd', fg='#856404')
                issues_text.pack(side='left', fill='both', expand=True)
                
                issues_scroll = ttk.Scrollbar(issues_frame, orient='vertical', command=issues_text.yview)
                issues_scroll.pack(side='right', fill='y')
                issues_text.configure(yscrollcommand=issues_scroll.set)
                
                for p in problems:
                    issues_text.insert('end', f'{p}\n\n')
                issues_text.config(state='disabled')
            
            # Close button
            btn_frame = ttk.Frame(result_dlg, padding=15)
            btn_frame.pack(fill='x', side='bottom')

            ttk.Button(btn_frame, text='Close', command=result_dlg.destroy,
                      style='Accent.TButton').pack(side='right')
            
            result_dlg.wait_window()
            
        except Exception as e:
            logger.error(f"Error in validation: {e}")
            messagebox.showerror(
                'Validation Error', 
                f'An error occurred: {e}\n\n'
                'Action: Check that all required fields are filled correctly.'
            )
    
    validate_menu.add_command(label='🔍 Validate All Titles', command=_validate_all_titles)
    menubar.add_cascade(label='✓ Validate', menu=validate_menu)

    # Settings menu (placed after Validate)
    settings_menu = tk.Menu(menubar, tearoff=0)
    settings_menu.add_command(
        label='Setup Wizard...',
        command=lambda: open_setup_wizard(root, status_var)
    )
    settings_menu.add_separator()
    settings_menu.add_command(
        label='Settings...', 
        accelerator='Ctrl+,', 
        command=lambda: open_settings_window(root, status_var)
    )
    menubar.add_cascade(label='⚙️ Settings', menu=settings_menu)

    # Info menu with log viewer
    from src.gui.dialogs import open_log_viewer as dialog_open_log_viewer
    
    info_menu = tk.Menu(menubar, tearoff=0)
    
    def show_about():
        """Displays the About dialog with application information."""
        messagebox.showinfo(
            'About Torrent RSS Rule Editor', 
            'Torrent RSS Rule Editor\n\n'
            'Generate and sync torrent RSS rules for seasonal anime.\n'
            'Run: python -m qbt_editor'
        )
    
    info_menu.add_command(label='View Logs...', command=lambda: dialog_open_log_viewer(root))
    info_menu.add_separator()
    info_menu.add_command(label='About', command=show_about)
    menubar.add_cascade(label='ℹ️ Info', menu=info_menu)

    # Attach menu to window
    try:
        root.config(menu=menubar)
    except Exception:
        try:
            root['menu'] = menubar
        except Exception:
            pass

    return menubar, recent_menu, edit_menu, file_menu, templates_menu


def setup_keyboard_shortcuts(root: tk.Tk, season_var: tk.StringVar, year_var: tk.StringVar, 
                            status_var: tk.StringVar) -> None:
    """
    Binds keyboard shortcuts for common operations.
    
    Sets up Ctrl+O (open), Ctrl+S (generate), Ctrl+E (export), etc.
    
    Args:
        root: Tkinter root window
        season_var: StringVar for season selection
        year_var: StringVar for year selection
        status_var: StringVar for status updates
    """
    # Import functions that will be called by shortcuts
    from src.gui.file_operations import (
        export_selected_titles, clear_all_titles, 
        export_all_titles, dispatch_generation
    )
    
    try:
        from src.gui.app_state import get_app_state

        actions = build_keyboard_shortcut_actions(
            root=root,
            season_var=season_var,
            year_var=year_var,
            status_var=status_var,
            import_titles_from_file_fn=import_titles_from_file,
            dispatch_generation_fn=dispatch_generation,
            export_selected_titles_fn=export_selected_titles,
            export_all_titles_fn=export_all_titles,
            clear_all_titles_fn=clear_all_titles,
            refresh_treeview_display_fn=refresh_treeview_display,
            focus_search_fn=get_app_state().focus_search,
        )
        bind_all_shortcuts(root, actions)
    except Exception:
        pass


def setup_drag_and_drop(root: tk.Tk, status_var: tk.StringVar, 
                        season_var: tk.StringVar = None, year_var: tk.StringVar = None) -> None:
    """
    Setup drag-and-drop support for JSON file import.
    
    Attempts to use tkinterdnd2 for native drag-and-drop. If not available,
    logs a warning but continues without DnD support.
    
    Args:
        root: Tkinter root window
        status_var: Status bar variable for feedback
        season_var: Season selection variable (optional)
        year_var: Year selection variable (optional)
    """
    try:
        # Try to import tkinterdnd2
        from tkinterdnd2 import DND_FILES
        
        # Check if root is a TkinterDnD.Tk instance
        if not hasattr(root, 'drop_target_register'):
            logger.info("Drag-and-drop: root window not DnD-enabled, skipping")
            return
        
        def _handle_drop(event):
            """Handle dropped files."""
            try:
                # Parse dropped file paths (may be wrapped in braces on Windows)
                files = parse_dropped_paths(event.data, root.tk.splitlist)
                file_path = first_json_path(files)

                if not file_path:
                    status_var.set("Drop a .json file to import")
                    return
                
                # Use existing import function
                from src.gui.file_operations import import_titles_from_file
                
                # Get season/year vars - use empty StringVars as fallback
                sv = season_var if season_var else tk.StringVar(value="")
                yv = year_var if year_var else tk.StringVar(value="")
                
                success = import_titles_from_file(root, status_var, sv, yv, path=file_path)
                
                if success:
                    status_var.set(f"Imported: {os.path.basename(file_path)}")
                
            except Exception as e:
                logger.error(f"Drag-and-drop import failed: {e}")
                status_var.set(f"Drop failed: {e}")
        
        # Register the root window as a drop target
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<Drop>>', _handle_drop)
        
        logger.info("Drag-and-drop enabled for JSON file import")
        
    except ImportError:
        logger.info("tkinterdnd2 not installed - drag-and-drop disabled. Install with: pip install tkinterdnd2")
    except Exception as e:
        logger.warning(f"Could not setup drag-and-drop: {e}")


def exit_handler() -> None:
    """
    Setup custom exception handler for clean shutdown.
    
    Filters out non-critical exceptions during application shutdown.
    """
    def _custom_excepthook(exc_type, exc_value, exc_traceback):
        """
        Custom exception handler to suppress specific non-critical exceptions.
        
        Filters out AttributeErrors related to _http_session which can occur
        during shutdown without affecting functionality.
        
        Args:
            exc_type: Exception class
            exc_value: Exception instance
            exc_traceback: Traceback object
        """
        try:
            if exc_type is AttributeError and '_http_session' in str(exc_value):
                return
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _custom_excepthook


def setup_gui() -> tk.Tk:
    """
    Main GUI setup function.
    
    Initializes the complete application interface by calling all extracted
    setup functions in the proper sequence.
    
    Returns:
        tk.Tk: The root window instance
    """
    import json
    from src.services.rules import build_rules_from_titles
    
    # Initialize app state singleton
    app_state = AppState.get_instance()
    
    # Load configuration
    try:
        config_set = config.load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}", exc_info=True)
        config_set = False
    
    # Create root window - try TkinterDnD for drag-and-drop support
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        logger.info("Using TkinterDnD for drag-and-drop support")
    except ImportError:
        root = tk.Tk()
        logger.info("TkinterDnD not available - using standard Tk")
    
    app_state.root = root
    enable_global_mousewheel_scrolling(root)

    try:
        if config.is_plaintext_fallback_active():
            fallback_reason = config.get_plaintext_fallback_reason() or 'Unknown reason'

            def _show_encryption_fallback_warning() -> None:
                messagebox.showwarning(
                    'Credential Security Notice',
                    'Encrypted credential storage is currently unavailable.\n\n'
                    f'Reason: {fallback_reason}\n\n'
                    'Credentials may be handled in plaintext until this is resolved. '
                    'Open Settings > Credential Security to review status and actions.'
                )

            root.after(350, _show_encryption_fallback_warning)
    except Exception:
        logger.debug('Unable to evaluate encryption fallback state', exc_info=True)
    
    # Setup exception handler
    exit_handler()
    
    # Initialize default templates if none exist
    try:
        from src.cache import initialize_default_templates
        initialize_default_templates()
        logger.info("Default templates initialized")
    except Exception as e:
        logger.error(f"Failed to initialize default templates: {e}")
    
    # Initialize window and styles (returns style, season_var, year_var)
    style, season_var, year_var = setup_window_and_styles(root)
    
    # Create main container frame
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill='both', expand=True)
    
    # Create status variable
    status_var = tk.StringVar(value='Initializing...')
    app_state.status_var = status_var

    def _notify_status(message: str, attention: bool = False) -> None:
        """Update status bar text (silent)."""
        app_state.set_status(message)
    
    # Setup menu bar (now that season_var and year_var are available)
    menubar, recent_menu, edit_menu, file_menu, templates_menu = setup_menu_bar(root, status_var, season_var, year_var)
    
    # Setup status bar and auto-connect
    setup_status_and_autoconnect(root, status_var, config_set)
    
    # Setup season controls
    top_config_frame = setup_season_controls(root, main_frame, season_var, year_var, status_var, style)

    # Quick actions strip (top-level productivity shortcuts)
    quick_actions_frame = ttk.LabelFrame(main_frame, text='Quick Actions', padding='8')
    quick_actions_frame.pack(fill='x', pady=(0, 6))

    def _invoke_quick_action(action_name: str, unavailable_message: str) -> None:
        try:
            action = getattr(app_state, action_name, None)
            if callable(action):
                action()
            else:
                _notify_status(unavailable_message)
        except Exception as e:
            _notify_status(f'Quick action failed: {e}')

    def _quick_generate() -> None:
        try:
            from src.gui.file_operations import dispatch_generation
            dispatch_generation(root, season_var, year_var, status_var)
        except Exception as e:
            _notify_status(f'Generate failed: {e}')

    ttk.Button(
        quick_actions_frame,
        text='⚡ Generate',
        style='Accent.TButton',
        command=_quick_generate,
    ).pack(side='left', padx=(0, 6))
    ttk.Button(
        quick_actions_frame,
        text='🔄 Sync',
        command=lambda: _invoke_quick_action('quick_sync_action', 'Sync action is not ready yet.'),
    ).pack(side='left', padx=6)
    ttk.Button(
        quick_actions_frame,
        text='📡 Refresh SubsPlease',
        command=lambda: _invoke_quick_action('quick_refresh_subsplease_action', 'SubsPlease refresh is not ready yet.'),
    ).pack(side='left', padx=6)
    ttk.Button(
        quick_actions_frame,
        text='🧠 Refresh AniList',
        command=lambda: _invoke_quick_action('quick_refresh_anilist_action', 'AniList refresh is not ready yet.'),
    ).pack(side='left', padx=6)
    ttk.Button(
        quick_actions_frame,
        text='⚙️ Settings',
        command=lambda: open_settings_window(root, status_var),
    ).pack(side='right', padx=(6, 0))

    # Persistent status chips (quick context separate from transient status bar messages)
    chips_frame = ttk.Frame(main_frame)
    chips_frame.pack(fill='x', pady=(0, 6))

    style.configure('Chip.TLabel', padding=(8, 3), borderwidth=1, relief='solid')
    style.configure('ChipOnline.TLabel', padding=(8, 3), borderwidth=1, relief='solid', foreground='#0f7b0f')
    style.configure('ChipAuto.TLabel', padding=(8, 3), borderwidth=1, relief='solid', foreground='#8a6a00')
    style.configure('ChipOffline.TLabel', padding=(8, 3), borderwidth=1, relief='solid', foreground='#7f1d1d')
    connection_chip_var = tk.StringVar(value='Connection: ...')
    titles_chip_var = tk.StringVar(value='Titles: 0')

    connection_chip_label = ttk.Label(chips_frame, textvariable=connection_chip_var, style='Chip.TLabel')
    connection_chip_label.pack(side='left', padx=(0, 6))
    titles_chip_label = ttk.Label(chips_frame, textvariable=titles_chip_var, style='Chip.TLabel')
    titles_chip_label.pack(side='left')
    
    # Setup library panel (treeview)
    paned, treeview = setup_library_panel(root, main_frame, style, edit_menu)
    app_state.treeview_widget = treeview

    def _refresh_status_chips() -> None:
        """Refresh connection and title-count chips periodically."""
        try:
            mode = str(getattr(config, 'CONNECTION_MODE', '') or 'unknown').strip().lower()
            server_name = get_server_display_name(getattr(config, 'MAIN_SERVER', 'qbittorrent'))
            connection_chip_var.set(f"Connection: {mode.title()} ({server_name})")
            if mode == 'online':
                connection_chip_label.configure(style='ChipOnline.TLabel')
            elif mode == 'auto':
                connection_chip_label.configure(style='ChipAuto.TLabel')
            elif mode == 'offline':
                connection_chip_label.configure(style='ChipOffline.TLabel')
            else:
                connection_chip_label.configure(style='Chip.TLabel')

            total = len(app_state.listbox_items)
            visible = len(treeview.get_children())
            search_text = ''
            try:
                if app_state.search_var is not None:
                    search_text = str(app_state.search_var.get() or '').strip()
            except Exception:
                search_text = ''

            if search_text:
                titles_chip_var.set(f"Titles: {visible}/{total} shown")
            else:
                titles_chip_var.set(f"Titles: {total}")
            titles_chip_label.configure(style='Chip.TLabel')
        except Exception:
            pass
        finally:
            try:
                root.after(UIConstants.STATUS_CHIP_REFRESH_MS, _refresh_status_chips)
            except Exception:
                pass

    _refresh_status_chips()
    
    # Setup editor panel
    (editor_rule_name, editor_must, editor_savepath, editor_category, 
     editor_enabled, editor_lastmatch_text) = setup_editor_panel(
        root, paned, treeview, season_var, year_var, status_var, style
    )
    
    # Setup keyboard shortcuts
    setup_keyboard_shortcuts(root, season_var, year_var, status_var)
    
    # Setup drag-and-drop for JSON file import
    setup_drag_and_drop(root, status_var, season_var, year_var)
    
    # ==================== Context Menu Setup ====================
    # Context menu handlers for right-click operations
    tree_adapter = TreeviewAdapter(treeview)
    
    def _ctx_edit_selected():
        """Opens advanced editor for selected item."""
        try:
            from src.gui.dialogs import open_full_rule_editor
            
            sel = tree_adapter.get_selected_indices()
            if not sel:
                messagebox.showwarning('Edit', 'No title selected.')
                return
            idx = int(sel[0])
            title_text, entry = app_state.listbox_items[idx]
            
            # Callback to refresh editor after save
            def _populate_callback(event=None):
                try:
                    new_sel = tree_adapter.get_selected_indices()
                    if new_sel:
                        treeview.event_generate('<<TreeviewSelect>>')
                except Exception:
                    pass
            
            open_full_rule_editor(root, title_text, entry, idx, _populate_callback)
        except Exception as e:
            messagebox.showerror(
                'Edit Error', 
                f'Failed to open editor: {e}\n\n'
                'Action: Try closing and reopening the application.'
            )
    
    def _ctx_delete_selected():
        """Moves selected items to trash with undo support."""
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                messagebox.showwarning(
                    'Delete', 
                    'No title selected.\n\n'
                    'Action: Select one or more titles from the list, then try again.'
                )
                return
            
            # Confirmation is optional and defaults to disabled.
            if bool(config.get_pref('confirm_delete', False)):
                shown_once = config.get_pref('delete_dialog_shown_once', False)
                if not shown_once:
                    # First confirmed delete: show informative dialog with trash and undo info.
                    message = (
                        f'Delete {len(sel)} selected title(s)?\n\n'
                        '💡 Info:\n'
                        '• Items are moved to Trash\n'
                        '• Use Ctrl+Z to undo\n'
                        '• Each undo operation restores one deletion\n'
                        '• This message will not appear again'
                    )
                    if not messagebox.askyesno('Confirm Delete', message):
                        return
                    config.set_pref('delete_dialog_shown_once', True)
                else:
                    if not messagebox.askyesno('Confirm Delete', f'Delete {len(sel)} selected title(s)?'):
                        return
            
            removed = 0
            for s in sorted([int(i) for i in sel], reverse=True):
                try:
                    title_text, entry = app_state.listbox_items[s]
                except Exception:
                    continue
                
                # Add to trash
                try:
                    app_state.trash_items.append({
                        'title': title_text, 
                        'entry': entry, 
                        'src': 'titles', 
                        'index': s
                    })
                except Exception:
                    pass
                
                # Remove from treeview
                try:
                    tree_adapter.delete_indices([s])
                except Exception:
                    pass
                
                # Remove from listbox_items
                try:
                    app_state.listbox_items.pop(s)
                except Exception:
                    pass
                
                # Remove from config.ALL_TITLES
                try:
                    if getattr(config, 'ALL_TITLES', None):
                        for k, lst in (config.ALL_TITLES.items() if isinstance(config.ALL_TITLES, dict) else []):
                            for i in range(len(config.ALL_TITLES.get(k, [])) - 1, -1, -1):
                                it = config.ALL_TITLES[k][i]
                                try:
                                    candidate = get_display_title(it) if isinstance(it, dict) else str(it)
                                except Exception:
                                    candidate = str(it)
                                if candidate == title_text:
                                    try:
                                        del config.ALL_TITLES[k][i]
                                    except Exception:
                                        pass
                except Exception:
                    pass
                
                removed += 1
            
            # Refresh treeview
            from src.gui.file_operations import refresh_treeview_display_safe
            refresh_treeview_display_safe()
            
            undo_count = len(app_state.trash_items)
            _notify_status(
                f'Deleted {removed} title(s) - press Ctrl+Z to undo ({undo_count} available)',
                attention=True,
            )
        except Exception as e:
            messagebox.showerror(
                'Delete Error', 
                f'Failed to delete selected titles: {e}\n\n'
                'Action: Try refreshing the list and attempting again.'
            )
    
    def _ctx_copy_selected():
        """Copies selected items as JSON to clipboard."""
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                messagebox.showwarning(
                    'Copy', 
                    'No title selected to copy.\n\n'
                    'Action: Select one or more titles from the list to copy as JSON.'
                )
                return
            
            export_map = {}
            try:
                sel_indices = [int(i) for i in sel]
            except Exception:
                sel_indices = []
            
            try:
                # Build proper qBittorrent rules format
                all_map = build_rules_from_titles({
                    'anime': [app_state.listbox_items[i][1] for i in sel_indices]
                })
                export_map = all_map
            except Exception:
                # Fallback: simple dictionary export
                for s in sel_indices:
                    try:
                        title_text, entry = app_state.listbox_items[s]
                    except Exception:
                        continue
                    if isinstance(entry, dict):
                        export_map[title_text] = entry
                    else:
                        export_map[title_text] = {'title': str(entry)}
            
            try:
                text = json.dumps(export_map, indent=4)
            except Exception as e:
                messagebox.showerror(
                    'Copy Error', 
                    f'Failed to serialize selection to JSON: {e}\n\n'
                    'Action: The selected data may be corrupted. Try selecting different items.'
                )
                return
            
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
                messagebox.showinfo('Copy', f'Copied {len(export_map)} item(s) to clipboard as JSON.')
                status_var.set(f'Copied {len(export_map)} item(s) to clipboard')
            except Exception as e:
                messagebox.showerror('Copy Error', f'Failed to copy to clipboard: {e}')
        except Exception as e:
            messagebox.showerror('Copy Error', f'Failed to copy selected titles: {e}')
    
    def _ctx_set_enabled_action(mode: str = 'toggle') -> None:
        """
        Set enabled/disabled state for selected rules.
        
        Args:
            mode: 'toggle' = toggle state, 'enable' = set to True, 'disable' = set to False
        """
        try:
            sel = treeview.selection()
            if not sel:
                msg_type = mode.capitalize()
                messagebox.showwarning(msg_type, 'No title selected.')
                return
            
            action_count = 0
            for item_id in sel:
                try:
                    values = treeview.item(item_id, 'values')
                    if not values or len(values) < 3:
                        continue
                    
                    title_text = values[2]
                    
                    # Find entry in listbox_items
                    entry = None
                    for t, e in app_state.listbox_items:
                        if t == title_text:
                            entry = e
                            break
                    
                    if not entry:
                        continue
                    
                    # Determine new enabled state
                    is_currently_enabled = values[0] == UIConstants.ENABLED_MARK
                    if mode == 'toggle':
                        new_enabled = not is_currently_enabled
                    elif mode == 'enable':
                        new_enabled = True
                    else:  # mode == 'disable'
                        new_enabled = False
                    
                    # Update entry enabled state
                    if isinstance(entry, dict):
                        entry['enabled'] = new_enabled
                    
                    # Update in config.ALL_TITLES
                    for k, lst in (config.ALL_TITLES.items() if isinstance(config.ALL_TITLES, dict) else []):
                        for i, it in enumerate(lst):
                            try:
                                candidate_title = get_display_title(it) if isinstance(it, dict) else str(it)
                            except Exception:
                                candidate_title = str(it)
                            if candidate_title == title_text:
                                if isinstance(config.ALL_TITLES[k][i], dict):
                                    config.ALL_TITLES[k][i]['enabled'] = new_enabled
                    
                    # Update treeview display
                    enabled_mark = UIConstants.ENABLED_MARK if new_enabled else UIConstants.DISABLED_MARK
                    new_values = (enabled_mark,) + values[1:]
                    treeview.item(item_id, values=new_values)
                    
                    action_count += 1
                except Exception as e:
                    logger.error(f"Error updating item enabled state: {e}")
                    continue
            
            if action_count > 0:
                mode_name = 'Toggled' if mode == 'toggle' else mode.capitalize() + 'ed'
                status_msg = f'{mode_name} {action_count} rule(s)'
                status_var.set(status_msg)
                # Refresh editor if any item is currently selected
                try:
                    treeview.event_generate('<<TreeviewSelect>>')
                except Exception:
                    pass
                
                # Show info messages for enable/disable
                if mode in ('enable', 'disable'):
                    messagebox.showinfo(mode.capitalize(), f'{mode_name} {action_count} rule(s).')
        except Exception as e:
            mode_name = mode.capitalize()
            messagebox.showerror(f'{mode_name} Error', f'Failed to {mode} rules: {e}')
    
    def _ctx_toggle_enabled():
        """Toggles enabled/disabled state for selected rules."""
        _ctx_set_enabled_action('toggle')
    
    def _ctx_enable_selected():
        """Enables selected rules."""
        _ctx_set_enabled_action('enable')
    
    def _ctx_disable_selected():
        """Disables selected rules."""
        _ctx_set_enabled_action('disable')
    
    def _on_listbox_right_click(event):
        """Handles right-click on treeview to show context menu."""
        try:
            idx = tree_adapter.get_index_at_y(event.y)
            if idx is None:
                return
            cur = tree_adapter.get_selected_indices()
            if not cur or (idx not in cur):
                try:
                    tree_adapter.clear_selection()
                except Exception:
                    pass
                try:
                    tree_adapter.set_selection_indices([idx])
                except Exception:
                    pass
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()
        except Exception:
            pass
    
    # Create context menu
    try:
        context_menu = tk.Menu(treeview, tearoff=0)
        context_menu.add_command(label='🔄 Toggle Enable/Disable', command=_ctx_toggle_enabled)
        context_menu.add_separator()
        context_menu.add_command(label='Copy', command=_ctx_copy_selected)
        context_menu.add_command(label='Edit', command=_ctx_edit_selected)
        context_menu.add_command(label='Delete', command=_ctx_delete_selected)
        treeview.bind('<Button-3>', _on_listbox_right_click, add='+')
        
        # Bind Space key to toggle enable/disable
        def _on_space_key(event):
            """Toggle enable/disable on Space key press."""
            try:
                _ctx_toggle_enabled()
                return "break"  # Prevent default space behavior
            except Exception as e:
                logger.error(f"Error in Space key handler: {e}")
        
        treeview.bind('<KeyPress-space>', _on_space_key)
        
        # Bind Delete key to delete selected items
        def _on_delete_key(event):
            """Delete selected items on Delete key press."""
            try:
                _ctx_delete_selected()
                return "break"  # Prevent default delete behavior
            except Exception as e:
                logger.error(f"Error in Delete key handler: {e}")
        
        treeview.bind('<Delete>', _on_delete_key)
    except Exception as e:
        logger.error(f"Failed to setup context menu: {e}")
    
    # Update Edit menu commands now that functions are defined
    if edit_menu:
        try:
            edit_menu.entryconfig(0, command=_ctx_toggle_enabled)
            # Undo is at index 2 (after separator)
            edit_menu.entryconfig(2, command=lambda: _undo_last_action())
            # Bulk edit is at index 4 (after another separator)
            edit_menu.entryconfig(4, command=lambda: _open_bulk_edit())
        except Exception as e:
            logger.error(f"Failed to update edit menu: {e}")
    
    # ==================== Bulk Edit Handler ====================
    def _open_bulk_edit():
        """Opens bulk edit dialog for multiple selected items."""
        try:
            from src.gui.dialogs import open_bulk_edit_dialog
            
            sel = tree_adapter.get_selected_indices()
            if not sel or len(sel) < 2:
                messagebox.showinfo(
                    'Bulk Edit', 
                    'Please select 2 or more items to use bulk edit.\n\n'
                    'Tip: Hold Ctrl and click to select multiple items.'
                )
                return
            
            # Collect selected items
            selected_items = []
            for idx in sel:
                try:
                    idx_int = int(idx)
                    title_text, entry = app_state.listbox_items[idx_int]
                    selected_items.append((title_text, entry))
                except Exception as e:
                    logger.error(f"Failed to get item {idx}: {e}")
                    continue
            
            if not selected_items:
                messagebox.showwarning('Bulk Edit', 'No valid items selected.')
                return
            
            # Callback to apply changes
            def _apply_bulk_changes(items, changes):
                """Apply bulk changes to selected items."""
                try:
                    # Save undo state
                    _save_undo_state()
                    
                    success_count = 0
                    for title_text, entry in items:
                        try:
                            # Find the item in listbox_items
                            item_idx = None
                            for i, (t, e) in enumerate(app_state.listbox_items):
                                if t == title_text and e is entry:
                                    item_idx = i
                                    break
                            
                            if item_idx is None:
                                continue
                            
                            # Apply changes
                            if 'category' in changes:
                                entry['assignedCategory'] = changes['category']
                                if 'torrentParams' not in entry:
                                    entry['torrentParams'] = {}
                                entry['torrentParams']['category'] = changes['category']
                            
                            if 'save_path' in changes:
                                entry['savePath'] = changes['save_path']
                                if 'torrentParams' not in entry:
                                    entry['torrentParams'] = {}
                                entry['torrentParams']['save_path'] = changes['save_path']
                            
                            if 'enabled' in changes:
                                entry['enabled'] = changes['enabled']
                            
                            # Update in ALL_TITLES
                            if hasattr(config, 'ALL_TITLES') and isinstance(config.ALL_TITLES, dict):
                                for season_key, titles_list in config.ALL_TITLES.items():
                                    if isinstance(titles_list, list):
                                        for item in titles_list:
                                            if isinstance(item, dict) and item.get('title') == title_text:
                                                if 'category' in changes:
                                                    item['assignedCategory'] = changes['category']
                                                    if 'torrentParams' not in item:
                                                        item['torrentParams'] = {}
                                                    item['torrentParams']['category'] = changes['category']
                                                if 'save_path' in changes:
                                                    item['savePath'] = changes['save_path']
                                                    if 'torrentParams' not in item:
                                                        item['torrentParams'] = {}
                                                    item['torrentParams']['save_path'] = changes['save_path']
                                                if 'enabled' in changes:
                                                    item['enabled'] = changes['enabled']
                            
                            success_count += 1
                        except Exception as e:
                            logger.error(f"Failed to update item {title_text}: {e}")
                            continue
                    
                    # Refresh treeview display
                    if success_count > 0:
                        refresh_treeview_display()
                        
                        # Re-select the items
                        treeview.selection_clear()
                        for idx in sel:
                            try:
                                treeview.selection_add(int(idx))
                            except Exception:
                                pass
                    
                    return success_count
                except Exception as e:
                    logger.error(f"Bulk edit apply error: {e}", exc_info=True)
                    messagebox.showerror('Bulk Edit Error', f'Failed to apply changes: {e}')
                    return 0
            
            open_bulk_edit_dialog(root, selected_items, _apply_bulk_changes, status_var)
        except Exception as e:
            logger.error(f"Bulk edit error: {e}", exc_info=True)
            messagebox.showerror(
                'Bulk Edit Error', 
                f'Failed to open bulk editor: {e}\n\n'
                'Action: Try selecting items again.'
            )

    def _save_undo_state() -> None:
        """Capture a lightweight undo snapshot placeholder for edit operations."""
        try:
            logger.debug("Undo snapshot requested for edit operation")
        except Exception:
            pass
    
    # Update keyboard shortcuts now that bulk edit function is defined
    try:
        root.bind_all('<Control-b>', lambda e: _open_bulk_edit())
        root.bind_all('<Control-B>', lambda e: _open_bulk_edit())
    except Exception as e:
        logger.error(f"Failed to bind bulk edit shortcut: {e}")
    
    # ==================== Unified Undo Handler ====================
    def _undo_last_action():
        """Unified undo handler for both delete and edit operations."""
        try:
            # Check if we have trash items (deleted items take priority)
            if app_state.trash_items:
                # Restore the most recent trash item
                try:
                    item = app_state.trash_items.pop()
                    if item.get('src') == 'titles':
                        title_text = item.get('title')
                        entry = item.get('entry')
                        original_idx = item.get('index', None)
                        
                        # Add back to listbox_items at original position if possible
                        if original_idx is not None and 0 <= original_idx <= len(app_state.listbox_items):
                            app_state.listbox_items.insert(original_idx, (title_text, entry))
                        else:
                            app_state.listbox_items.append((title_text, entry))
                        
                        # Add back to config.ALL_TITLES
                        if hasattr(config, 'ALL_TITLES') and isinstance(config.ALL_TITLES, dict):
                            if 'existing' not in config.ALL_TITLES:
                                config.ALL_TITLES['existing'] = []
                            config.ALL_TITLES['existing'].append(entry)
                        
                        # Refresh display
                        refresh_treeview_display()
                        
                        # Select the restored item
                        if original_idx is not None:
                            try:
                                tree_adapter.set_selection_indices([original_idx])
                                tree_adapter.see_index(original_idx)
                            except Exception:
                                pass

                        # Update status and attract attention to the status bar.
                        remaining = len(app_state.trash_items)
                        _notify_status(
                            f'Restored: {title_text} ({remaining} undo operation(s) remaining)',
                            attention=True,
                        )
                        return
                except Exception as e:
                    logger.error(f"Failed to restore trash item: {e}")
                    messagebox.showerror('Undo Error', f'Failed to undo delete: {e}')
                    return
            
            # If no trash items, use status bar + attention instead of popup.
            _notify_status('No operations to undo. Tip: Undo works for delete operations.', attention=True)
        except Exception as e:
            logger.error(f"Undo error: {e}", exc_info=True)
            messagebox.showerror('Undo Error', f'Failed to undo: {e}')
    
    # Update Ctrl+Z keyboard shortcuts
    try:
        root.bind_all('<Control-z>', lambda e: _undo_last_action())
        root.bind_all('<Control-Z>', lambda e: _undo_last_action())
    except Exception as e:
        logger.error(f"Failed to bind undo shortcut: {e}")
    
    # ==================== Template Functions ====================
    def _apply_template_to_rule(template_data: Dict[str, Any]) -> bool:
        """
        Apply a template to the selected rule(s).
        
        Args:
            template_data: Template configuration to apply
            
        Returns:
            bool: True if successful
        """
        try:
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning('No Selection', 'Please select a rule to apply the template to.')
                return False
            
            # Apply template to each selected item
            for item in selected:
                values = treeview.item(item, 'values')
                if not values:
                    continue
                
                title_text = values[0]
                
                # Find the entry in listbox_items
                for idx, (t, entry) in enumerate(app_state.listbox_items):
                    if t == title_text:
                        # Update entry with template data
                        for key, value in template_data.items():
                            if key in entry:
                                entry[key] = value
                        
                        # Update treeview
                        enabled_text = '✓ Yes' if entry.get('enabled', True) else '✗ No'
                        treeview.item(item, values=(
                            title_text,
                            entry.get('category', ''),
                            entry.get('save_path', ''),
                            entry.get('must_contain', ''),
                            enabled_text
                        ))
                        break
            
            status_var.set(f'Template applied to {len(selected)} rule(s)')
            return True
        except Exception as e:
            logger.error(f"Error applying template: {e}", exc_info=True)
            messagebox.showerror('Template Error', f'Failed to apply template: {e}')
            return False
    
    def _open_template_dialog():
        """Open the template dialog to apply a template."""
        try:
            from src.gui.dialogs import open_template_dialog
            open_template_dialog(root, apply_callback=_apply_template_to_rule)
        except Exception as e:
            logger.error(f"Error opening template dialog: {e}", exc_info=True)
            messagebox.showerror('Template Error', f'Failed to open template dialog: {e}')
    
    def _save_as_template():
        """Save the selected rule as a template."""
        try:
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning('No Selection', 'Please select a rule to save as a template.')
                return
            
            if len(selected) > 1:
                messagebox.showwarning('Multiple Selection', 'Please select only one rule to save as a template.')
                return
            
            # Get the selected item data
            item = selected[0]
            values = treeview.item(item, 'values')
            if not values:
                return
            
            title_text = values[0]
            
            # Find the entry in listbox_items
            current_rule = None
            for t, entry in app_state.listbox_items:
                if t == title_text:
                    current_rule = entry.copy()
                    break
            
            if not current_rule:
                messagebox.showerror('Error', 'Could not find rule data.')
                return
            
            # Open template dialog with current rule data
            from src.gui.dialogs import open_template_dialog
            open_template_dialog(root, current_rule_data=current_rule)
        except Exception as e:
            logger.error(f"Error saving template: {e}", exc_info=True)
            messagebox.showerror('Template Error', f'Failed to save template: {e}')
    
    def _manage_templates():
        """Open template management dialog."""
        try:
            from src.gui.dialogs import open_template_dialog
            open_template_dialog(root, apply_callback=_apply_template_to_rule)
        except Exception as e:
            logger.error(f"Error managing templates: {e}", exc_info=True)
            messagebox.showerror('Template Error', f'Failed to open template manager: {e}')

    # Update Templates menu commands now that handlers are defined
    try:
        templates_menu.entryconfig(0, command=_open_template_dialog)
        templates_menu.entryconfig(1, command=_save_as_template)
        templates_menu.entryconfig(3, command=_manage_templates)
    except Exception as e:
        logger.error(f"Failed to update templates menu: {e}")
    
    # Update template keyboard shortcuts
    try:
        root.bind_all('<Control-t>', lambda e: _save_as_template())
        root.bind_all('<Control-T>', lambda e: _save_as_template())
        root.bind_all('<Control-Shift-t>', lambda e: _open_template_dialog())
        root.bind_all('<Control-Shift-T>', lambda e: _open_template_dialog())
    except Exception as e:
        logger.error(f"Failed to bind template shortcuts: {e}")
    
    # ==================== Multi-Target Export Function ====================
    def _export_to_targets():
        """Export selected or all titles to configured targets."""
        try:
            # Get all titles from listbox_items
            all_titles = [title for title, entry in app_state.listbox_items]
            
            if not all_titles:
                messagebox.showwarning('No Titles', 'No titles to export. Please add some anime first.')
                return
            
            # Ask if exporting selected or all
            selected = treeview.selection()
            selected_title_set = set()
            if selected:
                export_selected = messagebox.askyesno(
                    'Export to Targets',
                    f'Export {len(selected)} selected titles to target(s)?\n\n'
                    'Click No to export all titles instead.'
                )
                if export_selected:
                    titles_to_export = [treeview.item(item, 'values')[0] for item in selected]
                    selected_title_set = set(titles_to_export)
                else:
                    titles_to_export = all_titles
            else:
                titles_to_export = all_titles

            entries_to_export = []
            if selected_title_set:
                for title_value, entry_value in app_state.listbox_items:
                    if title_value in selected_title_set:
                        entries_to_export.append(entry_value)
            else:
                entries_to_export = [entry for _, entry in app_state.listbox_items]
            
            # Open multi-target export dialog
            from src.gui.dialogs import open_multi_target_export_dialog
            open_multi_target_export_dialog(root, titles_to_export, entries_to_export)
            
        except Exception as e:
            logger.error(f"Target export error: {e}", exc_info=True)
            messagebox.showerror('Target Export Error', f'Failed to export to target(s): {e}')
    
    # Update file menu with multi-target export command
    try:
        # Find the Export to Targets menu item and update it
        file_menu.entryconfig('Export to Targets...', command=_export_to_targets)
    except Exception as e:
        logger.error(f"Failed to configure export menu item: {e}")
    
    # Update keyboard shortcut
    try:
        root.bind_all('<Control-Shift-s>', lambda e: _export_to_targets())
        root.bind_all('<Control-Shift-S>', lambda e: _export_to_targets())
    except Exception as e:
        logger.error(f"Failed to bind export shortcut: {e}")
    
    # ==================== Status Bar ====================
    # Pack status_frame first (at very bottom)
    status_frame = ttk.Frame(root, padding="5")
    status_frame.pack(side='bottom', fill='x')
    status_label = ttk.Label(status_frame, textvariable=status_var, relief='sunken', anchor='w')
    status_label.pack(fill='x')
    
    # Quick Actions at the top is now the primary action surface.
    # Keep legacy action_bar unmounted to avoid duplicate controls.
    
    # ==================== Final Initialization ====================
    # Load initial data if available
    try:
        logger.debug(f"Startup: config.ALL_TITLES type: {type(getattr(config, 'ALL_TITLES', None))}")
        logger.debug(f"Startup: config.ALL_TITLES content: {getattr(config, 'ALL_TITLES', None)}")
        
        if config.ALL_TITLES:
            # Pass treeview explicitly to ensure it's used
            update_treeview_with_titles(config.ALL_TITLES, treeview_widget=treeview)
            total_count = sum(len(v) for v in config.ALL_TITLES.values() if isinstance(v, list))
            status_var.set(f'Loaded {total_count} titles from config')
        else:
            logger.warning("Startup: config.ALL_TITLES is empty or None")
    except Exception as e:
        logger.error(f"Failed to load initial titles: {e}", exc_info=True)
    
    logger.info("GUI initialized successfully")
    
    # Start the main event loop
    root.mainloop()
    
    return root


def setup_season_controls(root: tk.Tk, main_frame: ttk.Frame, season_var: tk.StringVar, 
                          year_var: tk.StringVar, status_var: tk.StringVar, 
                          style: ttk.Style) -> ttk.Frame:
    """
    Creates the season/year selection controls and sync button.
    
    Sets up the top configuration panel with season dropdown, year entry,
    and sync from qBittorrent button for fetching existing rules.
    
    Args:
        root: Tkinter root window
        main_frame: Parent frame to pack controls into
        season_var: StringVar for season selection
        year_var: StringVar for year input
        status_var: StringVar for status updates
        style: ttk.Style for button styling
        
    Returns:
        The top_config_frame containing all season controls
    """
    top_config_frame = ttk.Frame(main_frame, padding="5")
    top_config_frame.pack(fill='x', pady=(0, 5))
    
    # Add a title label
    title_label = ttk.Label(top_config_frame, text="Season Configuration", font=('Segoe UI', 11, 'bold'))
    title_label.grid(row=0, column=0, sticky='w', pady=(0, 3))

    # Keep season/year selectors on the same row, aligned to the right to save vertical space.
    ttk.Label(top_config_frame, text="Season:").grid(row=0, column=2, sticky='e', padx=(0, 5), pady=(0, 3))
    season_dropdown = ttk.Combobox(top_config_frame, textvariable=season_var, 
                                    values=["Winter", "Spring", "Summer", "Fall"], 
                                    state="readonly", width=9)
    season_dropdown.grid(row=0, column=3, sticky='e', padx=(0, 10), pady=(0, 3))
    
    ttk.Label(top_config_frame, text="Year:").grid(row=0, column=4, sticky='e', padx=(0, 5), pady=(0, 3))
    year_entry = ttk.Entry(top_config_frame, textvariable=year_var, width=5)
    year_entry.grid(row=0, column=5, sticky='e', padx=(0, 5), pady=(0, 3))
    
    top_config_frame.grid_columnconfigure(1, weight=1)

    # Sync from selected server button
    def _sync_online_worker(root_ref, status_var_ref, btn_ref=None):
        """Background worker to sync existing rules from selected server profile."""
        def worker():
            try:
                active_server = get_server_display_name(getattr(config, 'MAIN_SERVER', 'qbittorrent'))
                def _disable_btn_and_set_status():
                    try:
                        if btn_ref is not None:
                            btn_ref.config(state='disabled')
                    except Exception:
                        pass
                    status_var_ref.set(f'Sync: fetching existing rules from {active_server}...')

                root_ref.after(0, _disable_btn_and_set_status)
                
                # Fetch rules using the qbittorrent_api module
                success, rules = qbt_api.fetch_rules(
                    config.QBT_PROTOCOL,
                    config.QBT_HOST,
                    str(config.QBT_PORT),
                    config.QBT_USER or '',
                    config.QBT_PASS or '',
                    bool(config.QBT_VERIFY_SSL),
                    getattr(config, 'QBT_CA_CERT', None)
                )
                
                if not success:
                    error_msg = str(rules)
                    def _fail_and_reenable():
                        status_var_ref.set(f'Sync failed: {error_msg}')
                        try:
                            if btn_ref is not None:
                                btn_ref.config(state='normal')
                        except Exception:
                            pass
                    root_ref.after(0, _fail_and_reenable)
                    return
                
                def finish():
                    try:
                        from src.gui.app_state import get_app_state
                        
                        if not rules:
                            status_var_ref.set('No existing rules available to add.')
                        else:
                            entries = []
                            if isinstance(rules, dict):
                                for name, data in rules.items():
                                    if isinstance(data, dict):
                                        title = data.get('ruleName') or data.get('name') or name
                                        rule_entry = dict(data)
                                        if not rule_entry.get('node'):
                                            rule_entry['node'] = {'title': title}
                                        # Ensure ruleName is set for duplicate detection
                                        if not rule_entry.get('ruleName'):
                                            rule_entry['ruleName'] = title
                                        entries.append(rule_entry)
                                    else:
                                        entries.append({'node': {'title': name}, 'ruleName': name})
                            elif isinstance(rules, list):
                                for item in rules:
                                    if isinstance(item, dict) and item.get('ruleName'):
                                        name = item.get('ruleName')
                                    else:
                                        name = str(item)
                                    entries.append({'node': {'title': name}, 'ruleName': name})

                            if entries:
                                current = getattr(config, 'ALL_TITLES', {}) or {}
                                merge_result = merge_existing_rule_entries(
                                    current_titles=current,
                                    incoming_entries=entries,
                                    get_display_title_fn=get_display_title,
                                    get_rule_name_fn=get_rule_name,
                                )

                                new_count = int(merge_result.get('new_entries_count', 0) or 0)
                                removed_count = int(merge_result.get('removed_duplicates_count', 0) or 0)

                                if new_count > 0:
                                    config.ALL_TITLES = merge_result.get('updated_titles', current)
                                    try:
                                        from src.gui.file_operations import refresh_treeview_display_safe
                                        refresh_treeview_display_safe()
                                        if removed_count > 0:
                                            status_var_ref.set(
                                                f'Added {new_count} new existing rule(s) and removed {removed_count} duplicate local row(s).'
                                            )
                                        else:
                                            status_var_ref.set(f'Added {new_count} new existing rule(s) to Titles.')
                                    except Exception as e:
                                        logger.error(f"Failed to refresh treeview after sync: {e}")
                                        status_var_ref.set('Added existing rules but failed to refresh Titles UI.')
                                else:
                                    status_var_ref.set('No new existing rules to add (duplicates skipped).')
                    finally:
                        try:
                            if btn_ref is not None:
                                btn_ref.config(state='normal')
                        except Exception:
                            pass
                
                root_ref.after(0, finish)
            except Exception as e:
                error_msg = str(e)
                def _error_and_reenable():
                    status_var_ref.set(f'Sync error: {error_msg}')
                    try:
                        if btn_ref is not None:
                            btn_ref.config(state='normal')
                    except Exception:
                        pass
                root_ref.after(0, _error_and_reenable)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_sync_clicked():
        """Handles sync button click for the selected server profile or offline file import."""
        try:
            mode = (getattr(config, 'CONNECTION_MODE', '') or '').lower()
            if mode == 'online':
                _sync_online_worker(root, status_var, None)
            else:
                import_titles_from_file(root, status_var)
        except Exception as e:
            messagebox.showerror('Sync Error', f'Failed to start sync: {e}')

    try:
        from src.gui.app_state import get_app_state
        get_app_state().quick_sync_action = _on_sync_clicked
    except Exception:
        pass

    return top_config_frame


def setup_library_panel(
    root: tk.Tk,
    main_frame: ttk.Frame, 
    style: ttk.Style, 
    edit_menu: tk.Menu = None
) -> Tuple[ttk.PanedWindow, ttk.Treeview]:
    """
    Creates the title library panel with treeview and all features.
    
    Sets up the main library display with:
    - Resizable paned window for library/editor split
    - Treeview with columns (#, Enabled, Title, Category, Save Path)
    - Auto-fit columns, column width persistence
    - Scrollbars (auto-hide when not needed)
    - Listbox compatibility methods
    - Context menu (Enable, Disable, Copy, Edit, Delete)
    
    Args:
        root: Tkinter root window
        main_frame: Parent frame to pack panel into
        style: ttk.Style for treeview styling
        edit_menu: Edit menu to configure enable/disable commands (optional)
        
    Returns:
        Tuple of (paned_window, treeview) for further configuration
    """
    list_frame_container = ttk.LabelFrame(main_frame, text="📋 Title Rules Library", padding="15")
    list_frame_container.pack(fill='both', expand=True, pady=(10, 5))
    
    # Search/Filter bar
    search_frame = ttk.Frame(list_frame_container)
    search_frame.pack(fill='x', pady=(0, 8))
    
    ttk.Label(search_frame, text="🔍 Filter:").pack(side='left', padx=(0, 5))
    
    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
    search_entry.pack(side='left', fill='x', expand=True, padx=(0, 5))
    
    # Store in app_state for global access
    from src.gui.app_state import get_app_state
    app_state = get_app_state()
    app_state.search_entry = search_entry
    app_state.search_var = search_var
    
    # Filter type dropdown
    filter_type_var = tk.StringVar(value="Title")
    filter_type = ttk.Combobox(search_frame, textvariable=filter_type_var, 
                               values=["Title", "Category", "Save Path", "All"], 
                               state='readonly', width=10)
    filter_type.pack(side='left', padx=(0, 5))
    
    # Clear button
    def clear_filter():
        search_var.set("")
        try:
            tree_adapter.apply_filter_debounced(debounce_ms=0)
        except Exception:
            try:
                app_state.tree_adapter.apply_filter_debounced(debounce_ms=0)
            except Exception:
                pass
    
    clear_btn = ttk.Button(search_frame, text="Clear", width=7, command=clear_filter, style='Danger.TButton')
    clear_btn.pack(side='left')

    # Use PanedWindow to allow resizable split between library and editor
    paned = ttk.PanedWindow(list_frame_container, orient='horizontal')
    paned.pack(fill='both', expand=True)
    
    # Load saved paned window position
    try:
        saved_sash_pos = config.get_pref('paned_sash_position', None)
    except Exception:
        saved_sash_pos = None
    
    # Function to save paned window position
    def _save_sash_position(event=None):
        try:
            def _delayed_save():
                try:
                    pos = paned.sashpos(0)
                    config.set_pref('paned_sash_position', pos)
                except Exception:
                    pass
            paned.after(UIConstants.PANED_SASH_SAVE_DELAY_MS, _delayed_save)
        except Exception:
            pass
    
    # Bind to save sash position when dragged
    paned.bind('<ButtonRelease-1>', _save_sash_position)
    
    # Bind double-click to reset paned sash to default position
    def _reset_paned_sash(event):
        try:
            total_width = paned.winfo_width()
            if total_width > 100:
                default_pos = int(total_width * 0.6)
                paned.sashpos(0, default_pos)
                config.set_pref('paned_sash_position', default_pos)
        except Exception:
            pass
    
    paned.bind('<Double-Button-1>', _reset_paned_sash)

    # Restore saved position after widget is rendered
    def _restore_or_set_default_sash():
        try:
            total_width = paned.winfo_width()
            if total_width > 100:
                default_pos = int(total_width * 0.6)
                
                # Validate saved position
                if saved_sash_pos is not None and saved_sash_pos > 100 and saved_sash_pos < total_width - 100:
                    paned.sashpos(0, saved_sash_pos)
                else:
                    # Use default if saved position is invalid
                    paned.sashpos(0, default_pos)
        except Exception:
            pass
    
    # Create treeview frame
    treeview_frame = ttk.Frame(paned)
    paned.add(treeview_frame, weight=2)
    
    # Create Treeview with columns (checkmark as first column, hide tree column #0)
    treeview = ttk.Treeview(treeview_frame, selectmode='extended', 
                           columns=('enabled', 'index', 'title', 'category', 'savepath'),
                           show='headings', height=20)
    
    tree_adapter = TreeviewAdapter(treeview)

    # Define column headings (enabled first, then index, title, category, savepath)
    treeview.heading('enabled', text='✓', anchor='center', command=lambda: tree_adapter.sort_column_toggle('enabled'))
    treeview.heading('index', text='#', anchor='w', command=lambda: tree_adapter.sort_column_toggle('index'))
    treeview.heading('title', text='Title', anchor='w', command=lambda: tree_adapter.sort_column_toggle('title'))
    treeview.heading('category', text='Category', anchor='w', command=lambda: tree_adapter.sort_column_toggle('category'))
    treeview.heading('savepath', text='Save Path', anchor='w', command=lambda: tree_adapter.sort_column_toggle('savepath'))
    
    # Load saved column widths or use defaults
    try:
        saved_col_widths = config.get_pref('treeview_column_widths', {})
    except Exception:
        saved_col_widths = {}
    
    # Load saved column order
    try:
        saved_col_order = config.get_pref('treeview_column_order', None)
    except Exception:
        saved_col_order = None
    
    # Apply saved column order if available, ensuring 'enabled' is always first and 'index' always second
    # IMPORTANT: If old config doesn't have 'index', we must add it!
    if saved_col_order and isinstance(saved_col_order, list):
        try:
            logger.debug(f"Saved column order from config: {saved_col_order}")
            # Ensure 'enabled' is first in the display order
            if 'enabled' in saved_col_order:
                saved_col_order.remove('enabled')
            saved_col_order.insert(0, 'enabled')
            # Ensure 'index' is second (may not exist in old configs - MUST ADD IT!)
            if 'index' not in saved_col_order:
                logger.debug("'index' column not in saved order, adding it at position 1")
                saved_col_order.insert(1, 'index')
            else:
                # Move index to position 1 if it's elsewhere
                if saved_col_order.index('index') != 1:
                    saved_col_order.remove('index')
                    saved_col_order.insert(1, 'index')
            logger.debug(f"Final column display order: {saved_col_order}")
            treeview['displaycolumns'] = tuple(saved_col_order)
        except Exception as e:
            logger.error(f"Error setting column order: {e}", exc_info=True)
            # Fallback to default order with enabled first
            treeview['displaycolumns'] = ('enabled', 'index', 'title', 'category', 'savepath')
    else:
        logger.debug("No saved column order, using default: enabled, index, title, category, savepath")
        # Default order with enabled first
        treeview['displaycolumns'] = ('enabled', 'index', 'title', 'category', 'savepath')
    
    # Track manual column resizes
    columns_manual_resize = {
        'enabled': {'disabled': False},
        'index': {'disabled': False},
        'title': {'disabled': False},
        'category': {'disabled': False},
        'savepath': {'disabled': False}
    }
    
    # Get view mode preference (compact vs expanded)
    try:
        view_mode = config.get_pref('view_mode', 'expanded')
        if view_mode not in ['compact', 'expanded']:
            view_mode = 'expanded'
    except Exception:
        view_mode = 'expanded'
    
    # Configure column widths based on view mode
    if view_mode == 'compact':
        # Compact mode: hide category and savepath, narrow title
        treeview.column('enabled', width=saved_col_widths.get('enabled', 30), minwidth=25, stretch=False)
        treeview.column('index', width=saved_col_widths.get('index', 40), minwidth=30, stretch=False)
        treeview.column('title', width=saved_col_widths.get('title', 250), minwidth=150, stretch=True)
        treeview.column('category', width=0, minwidth=0, stretch=False)
        treeview.column('savepath', width=0, minwidth=0, stretch=False)
        # Update display columns for compact mode
        treeview['displaycolumns'] = ('enabled', 'index', 'title')
    else:  # expanded mode (default)
        treeview.column('enabled', width=saved_col_widths.get('enabled', 30), minwidth=25, stretch=False)
        treeview.column('index', width=saved_col_widths.get('index', 40), minwidth=30, stretch=False)
        treeview.column('title', width=saved_col_widths.get('title', 300), minwidth=150, stretch=True)
        treeview.column('category', width=saved_col_widths.get('category', 150), minwidth=100, stretch=False)
        treeview.column('savepath', width=saved_col_widths.get('savepath', 400), minwidth=180, stretch=True)
        # Reset display columns for expanded mode
        treeview['displaycolumns'] = ('enabled', 'index', 'title', 'category', 'savepath')
    
    # Auto-fit column function with better width calculation
    def _auto_fit_column(col_id):
        """Auto-fit column width based on content with proper text measurement."""
        try:
            # Start with minimum width
            max_width = 30
            
            # Font metrics for accurate measurement (approximate 7 pixels per char for Segoe UI 9pt)
            char_width = 7
            padding = 20
            
            # Measure header text
            header_texts = {'enabled': '✓', 'index': '#', 'title': 'Title', 'category': 'Category', 'savepath': 'Save Path'}
            header_text = header_texts.get(col_id, '')
            header_width = len(header_text) * char_width + padding + 10  # Extra padding for sort indicator
            max_width = max(max_width, header_width)
            
            # Measure all items in column
            for item in treeview.get_children():
                try:
                    values = treeview.item(item, 'values')
                    col_index = {'enabled': 0, 'index': 1, 'title': 2, 'category': 3, 'savepath': 4}.get(col_id, -1)
                    text = values[col_index] if col_index >= 0 and col_index < len(values) else ''
                    
                    if text:
                        text_width = len(str(text)) * char_width + padding
                        max_width = max(max_width, text_width)
                except Exception:
                    pass
            
            # Cap maximum width to prevent excessive columns
            max_width = min(max_width, 600)
            
            treeview.column(col_id, width=int(max_width))
            
            # Mark as manually sized to prevent auto-resize
            if col_id in columns_manual_resize:
                columns_manual_resize[col_id]['disabled'] = False
        except Exception as e:
            logger.error(f"Error in auto_fit_column: {e}")
    
    # Auto-fit all columns on data load
    def _auto_fit_all_columns():
        """Auto-fit all columns after data is loaded."""
        try:
            for col_id in ['enabled', 'index', 'title', 'category', 'savepath']:
                if col_id not in columns_manual_resize or not columns_manual_resize[col_id].get('disabled', False):
                    _auto_fit_column(col_id)
        except Exception:
            pass
    
    # Save column widths and order function
    def _save_column_widths_and_order(event=None):
        """Save column widths and display order."""
        try:
            widths = {
                'enabled': treeview.column('enabled', 'width'),
                'index': treeview.column('index', 'width'),
                'title': treeview.column('title', 'width'),
                'category': treeview.column('category', 'width'),
                'savepath': treeview.column('savepath', 'width')
            }
            config.set_pref('treeview_column_widths', widths)
            
            # Save column display order (always ensure enabled is first, index second)
            try:
                display_cols = list(treeview['displaycolumns'])
                # Ensure enabled is always first
                if 'enabled' in display_cols:
                    display_cols.remove('enabled')
                display_cols.insert(0, 'enabled')
                # Ensure index is always second
                if 'index' in display_cols:
                    display_cols.remove('index')
                display_cols.insert(1, 'index')
                config.set_pref('treeview_column_order', display_cols)
            except Exception:
                pass
            
            # Track manual resize
            if event:
                try:
                    region = treeview.identify_region(event.x, event.y)
                    if region == "separator":
                        col = treeview.identify_column(event.x)
                        col_map = {
                            '#1': 'enabled',
                            '#2': 'index',
                            '#3': 'title',
                            '#4': 'category',
                            '#5': 'savepath',
                        }
                        if col in col_map:
                            columns_manual_resize[col_map[col]]['disabled'] = True
                except Exception:
                    pass
        except Exception:
            pass
    
    treeview.bind('<ButtonRelease-1>', _save_column_widths_and_order)
    
    # Double-click separator to auto-fit column
    def _on_double_click(event):
        """Handle double-click on column separator to auto-resize."""
        try:
            region = treeview.identify_region(event.x, event.y)
            if region == "separator":
                # Get the column to the LEFT of the separator
                x_pos = event.x
                col = None
                cumulative_width = 0
                    
                # Check each displayed column
                for col_name in ['enabled', 'index', 'title', 'category', 'savepath']:
                    col_width = treeview.column(col_name, 'width')
                    cumulative_width += col_width
                    if abs(x_pos - cumulative_width) <= 5:  # Separator threshold
                        col = col_name
                        break
                
                if col:
                    _auto_fit_column(col)
                    _save_column_widths_and_order()
                return "break"
        except Exception as e:
            logger.error(f"Error in double-click handler: {e}")
    
    treeview.bind('<Double-Button-1>', _on_double_click)
    
    # Create scrollbars
    vsb = ttk.Scrollbar(treeview_frame, orient='vertical', command=treeview.yview)
    hsb = ttk.Scrollbar(treeview_frame, orient='horizontal', command=treeview.xview)
    
    # Auto-hide scrollbars
    def _vsb_set(*args):
        try:
            vsb.set(*args)
            if float(args[0]) <= 0.0 and float(args[1]) >= 1.0:
                vsb.grid_remove()
            else:
                vsb.grid()
        except Exception:
            vsb.set(*args)
    
    def _hsb_set(*args):
        try:
            hsb.set(*args)
            if float(args[0]) <= 0.0 and float(args[1]) >= 1.0:
                hsb.grid_remove()
            else:
                hsb.grid()
        except Exception:
            hsb.set(*args)
    
    treeview.configure(yscrollcommand=_vsb_set, xscrollcommand=_hsb_set)
    
    # Grid layout
    treeview.grid(row=0, column=0, sticky='nsew')
    vsb.grid(row=0, column=1, sticky='ns')
    hsb.grid(row=1, column=0, sticky='ew')
    
    treeview_frame.grid_rowconfigure(0, weight=1)
    treeview_frame.grid_columnconfigure(0, weight=1)
    
    # Attach manual resize tracker
    treeview._columns_manual_resize = columns_manual_resize
    
    # Bind centralized filter handling through adapter state.
    tree_adapter.bind_filter_controls(search_var, filter_type_var, debounce_ms=150)
    app_state.tree_adapter = tree_adapter


    
    # Bind Ctrl+F to focus search
    def _focus_search(event=None):
        search_entry.focus_set()
        search_entry.select_range(0, 'end')
        return 'break'
    
    treeview.bind('<Control-f>', _focus_search)
    treeview.bind('<Control-F>', _focus_search)
    
    # Bind Escape to clear filter when in search entry
    def _escape_search(event=None):
        if search_var.get():
            clear_filter()
        else:
            treeview.focus_set()
        return 'break'
    
    search_entry.bind('<Escape>', _escape_search)
    
    # Restore sash position after widget is fully rendered
    paned.after_idle(_restore_or_set_default_sash)
    
    return paned, treeview


def setup_editor_panel(root: tk.Tk, paned: tk.PanedWindow, treeview: ttk.Treeview,
                       season_var: tk.StringVar, year_var: tk.StringVar,
                       status_var: tk.StringVar, style: ttk.Style) -> Tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.StringVar, tk.BooleanVar, tk.Text]:
    """
    Creates the rule editor panel with all editor fields and SubsPlease integration.
    
    Sets up a scrollable editor panel containing:
    - Title and match pattern fields
    - Feed title lookup with SubsPlease API integration
    - Last match display with age calculation
    - Save path and category fields
    - Enabled checkbox
    - Season/year prefix button
    - Apply and Advanced Settings buttons
    
    Args:
        root: Tkinter root window
        paned: PanedWindow widget containing library and editor panels
        treeview: Treeview widget for displaying titles
        season_var: StringVar for season selection
        year_var: StringVar for year selection
        status_var: StringVar for status bar updates
        style: ttk.Style object for styling
        
    Returns:
        Tuple of (editor_rule_name, editor_must, editor_savepath, editor_category, 
                  editor_enabled, editor_lastmatch_text):
            - editor_rule_name: StringVar for rule title
            - editor_must: StringVar for match pattern
            - editor_savepath: StringVar for save path
            - editor_category: StringVar for category
            - editor_enabled: BooleanVar for enabled state
            - editor_lastmatch_text: Text widget for last match display
    """
    from src.api.subsplease import (
        can_pull_anilist_cache,
        can_pull_subsplease_cache,
        fetch_subsplease_schedule,
        find_subsplease_title_match,
        load_subsplease_cache,
        load_title_variations_cache,
        refresh_anilist_cache_with_limit,
    )
    from src.gui.dialogs import open_full_rule_editor
    import json
    from datetime import datetime, timezone
    
    app_state = AppState.get_instance()
    listbox_items = app_state.listbox_items
    tree_adapter = TreeviewAdapter(treeview)

    # Get theme-aware colors
    colors = get_editor_theme_colors()
    editor_bg = colors['bg']
    editor_input_bg = colors['input_bg']
    editor_input_fg = colors['input_fg']
    editor_border = colors['border']
    link_color = colors['link']
    success_color = colors['success']
    tooltip_bg = colors['tooltip_bg']
    tooltip_fg = colors['tooltip_fg']
    
    # Create editor container for PanedWindow (increased weight for more space)
    editor_container = ttk.Frame(paned)
    paned.add(editor_container, weight=5)
    
    # Create editor scrollable container
    editor_scrollable_container = ttk.Frame(editor_container)
    editor_scrollable_container.pack(fill='both', expand=True)
    
    editor_canvas = tk.Canvas(editor_scrollable_container, bg=editor_bg, highlightthickness=0)
    editor_scrollbar = ttk.Scrollbar(editor_scrollable_container, orient='vertical', command=editor_canvas.yview)
    editor_frame = ttk.Frame(editor_canvas, padding=15)
    
    try:
        editor_scrollbar.pack(side='right', fill='y')
        editor_canvas.pack(side='left', fill='both', expand=True)
    except Exception:
        pass
    
    try:
        editor_canvas_window = editor_canvas.create_window((0, 0), window=editor_frame, anchor='nw')
        editor_canvas.configure(yscrollcommand=editor_scrollbar.set)
        
        # Update canvas window width when canvas resizes
        def _on_canvas_resize(event):
            try:
                canvas_width = event.width
                editor_canvas.itemconfig(editor_canvas_window, width=canvas_width)
            except Exception:
                pass
        editor_canvas.bind('<Configure>', _on_canvas_resize)
        
        # Enable mousewheel scrolling for editor canvas
        def _wheel_units(event):
            """Normalize wheel delta across Windows/macOS/Linux."""
            if hasattr(event, 'num') and event.num in (4, 5):
                return -1 if event.num == 4 else 1
            delta = getattr(event, 'delta', 0)
            if delta == 0:
                return 0
            return int(-1 * (delta / 120))

        def _on_editor_mousewheel(event):
            try:
                units = _wheel_units(event)
                if units:
                    editor_canvas.yview_scroll(units, "units")
            except Exception:
                pass
        
        def _bind_editor_mousewheel(event):
            try:
                editor_canvas.bind("<MouseWheel>", _on_editor_mousewheel)
                editor_canvas.bind("<Button-4>", _on_editor_mousewheel)
                editor_canvas.bind("<Button-5>", _on_editor_mousewheel)
            except Exception:
                pass
        
        def _unbind_editor_mousewheel(event):
            try:
                editor_canvas.unbind("<MouseWheel>")
                editor_canvas.unbind("<Button-4>")
                editor_canvas.unbind("<Button-5>")
            except Exception:
                pass
        
        editor_canvas.bind("<Enter>", _bind_editor_mousewheel)
        editor_canvas.bind("<Leave>", _unbind_editor_mousewheel)
        editor_frame.bind("<Enter>", _bind_editor_mousewheel)
        editor_frame.bind("<Leave>", _unbind_editor_mousewheel)
    except Exception:
        pass
    
    def _configure_editor_scroll(event=None):
        try:
            editor_canvas.configure(scrollregion=editor_canvas.bbox('all'))
            # Show/hide scrollbar based on content
            try:
                bbox = editor_canvas.bbox("all")
                if bbox:
                    content_height = bbox[3] - bbox[1]
                    canvas_height = editor_canvas.winfo_height()
                    if content_height > canvas_height:
                        editor_scrollbar.pack(side='right', fill='y')
                    else:
                        editor_scrollbar.pack_forget()
                        editor_canvas.pack(side='left', fill='both', expand=True)
            except Exception:
                pass
        except Exception:
            pass
    
    try:
        editor_frame.bind('<Configure>', _configure_editor_scroll)
    except Exception:
        pass

    # Create editor variables
    editor_vars = create_editor_variables()
    editor_rule_name = editor_vars['rule_name']
    editor_must = editor_vars['must']
    editor_savepath = editor_vars['savepath']
    editor_category = editor_vars['category']
    editor_enabled = editor_vars['enabled']
    
    # Undo stack for editor changes (stores previous state)
    editor_undo_stack = editor_vars['undo_stack']
    
    def _save_undo_state():
        """Saves current editor state to undo stack."""
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                return
            idx = int(sel[0])
            title_text, entry = listbox_items[idx]
            
            # Create a deep copy of the current state
            state = {
                'idx': idx,
                'title': title_text,
                'entry': json.loads(json.dumps(entry)),  # Deep copy via JSON
                'editor_values': {
                    'rule_name': editor_rule_name.get(),
                    'must': editor_must.get(),
                    'savepath': editor_savepath.get(),
                    'category': editor_category.get(),
                    'enabled': editor_enabled.get()
                }
            }
            editor_undo_stack.append(state)
            # Keep only last N undo states
            if len(editor_undo_stack) > UIConstants.MAX_UNDO_STACK_SIZE:
                editor_undo_stack.pop(0)
            
            # Update undo button state
            try:
                undo_btn.config(state='normal')
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error saving undo state: {e}")
    
    def _undo_editor_changes():
        """Undoes the last editor change."""
        try:
            if not editor_undo_stack:
                messagebox.showinfo('Undo', 'No changes to undo.')
                return
            
            # Pop the last state
            state = editor_undo_stack.pop()
            
            # Restore the entry
            idx = state['idx']
            entry = state['entry']
            title = state['title']
            
            # Update listbox_items
            listbox_items[idx] = (title, entry)
            
            # Update config.ALL_TITLES
            try:
                if getattr(config, 'ALL_TITLES', None):
                    for k, lst in (config.ALL_TITLES.items() if isinstance(config.ALL_TITLES, dict) else []):
                        for i, it in enumerate(lst):
                            try:
                                candidate_title = get_display_title(it) if isinstance(it, dict) else str(it)
                            except Exception:
                                candidate_title = str(it)
                            if candidate_title == state['editor_values']['rule_name']:
                                config.ALL_TITLES[k][i] = entry
                                break
            except Exception as e:
                logger.error(f"Error updating ALL_TITLES during undo: {e}")
            
            # Refresh treeview
            try:
                update_treeview_with_titles(config.ALL_TITLES)
                tree_adapter.set_selection_indices([idx])
                tree_adapter.see_index(idx)
            except Exception:
                pass
            
            # Refresh editor to show restored values
            try:
                _populate_editor_from_selection()
            except Exception:
                pass
            
            # Update undo button state
            try:
                if not editor_undo_stack:
                    undo_btn.config(state='disabled')
            except Exception:
                pass
            
            status_var.set('Undone last change')
        except Exception as e:
            messagebox.showerror('Undo Error', f'Failed to undo: {e}')
    
    # Improved text widget styling
    editor_lastmatch_text = tk.Text(editor_frame, height=2, width=40, state='disabled',
                                     font=('Consolas', 9), bg=editor_input_bg, fg=editor_input_fg,
                                     relief='flat', bd=1, highlightthickness=1,
                                     highlightbackground=editor_border, highlightcolor='#0078D4')

    # Create header with title and undo button
    editor_header = ttk.Frame(editor_frame)
    editor_header.pack(fill='x', pady=(0, 10))
    ttk.Label(editor_header, text='📝 Rule Editor', font=('Segoe UI', 11, 'bold')).pack(side='left')

    enabled_toggle_text = tk.StringVar(value='✅ Enabled')

    def _refresh_enabled_toggle_button() -> None:
        try:
            if bool(editor_enabled.get()):
                enabled_toggle_text.set('✅ Enabled')
                enabled_toggle_btn.configure(style='Accent.TButton')
            else:
                enabled_toggle_text.set('⛔ Disabled')
                enabled_toggle_btn.configure(style='Danger.TButton')
        except Exception:
            pass

    def _toggle_enabled_from_header() -> None:
        try:
            editor_enabled.set(not bool(editor_enabled.get()))
            _refresh_enabled_toggle_button()
        except Exception:
            pass
    
    undo_btn = ttk.Button(editor_header, text='↶ Undo', command=_undo_editor_changes, 
                          width=8, state='disabled')
    undo_btn.pack(side='right')
    enabled_toggle_btn = ttk.Button(
        editor_header,
        textvariable=enabled_toggle_text,
        command=_toggle_enabled_from_header,
        width=12,
        style='Accent.TButton',
    )
    enabled_toggle_btn.pack(side='right', padx=(0, 8))
    _refresh_enabled_toggle_button()
    create_tooltip(undo_btn, 'Undo last auto-applied change (up to 10 changes)')
    create_tooltip(enabled_toggle_btn, 'Toggle rule enabled state')
    
    ttk.Separator(editor_frame, orient='horizontal').pack(fill='x', pady=(0, 10))

    # Add prefix button
    def _add_prefix_to_selected():
        """
        Adds season/year prefix to the selected title.
        """
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                messagebox.showwarning('Prefix', 'No title selected.')
                return
            idx = int(sel[0])
            title_text, entry = listbox_items[idx]
            
            season = season_var.get()
            year = year_var.get()
            prefix = f"[{season} {year}] "
            
            # Check if already has prefix
            if title_text.startswith(prefix):
                messagebox.showinfo('Prefix', 'Title already has this prefix.')
                return
            
            new_title = prefix + title_text
            
            # Update entry
            if isinstance(entry, dict):
                node = entry.get('node') or {}
                node['title'] = new_title
                entry['node'] = node
            
            # Update listbox and items
            listbox_items[idx] = (new_title, entry)
            tree_adapter.update_title_at_index(idx, new_title)
            tree_adapter.set_selection_indices([idx])
            tree_adapter.see_index(idx)
            
            # Update config
            try:
                if getattr(config, 'ALL_TITLES', None):
                    for k, lst in (config.ALL_TITLES.items() if isinstance(config.ALL_TITLES, dict) else []):
                        for i, it in enumerate(lst):
                            try:
                                candidate_title = get_display_title(it) if isinstance(it, dict) else str(it)
                            except Exception:
                                candidate_title = str(it)
                            if candidate_title == title_text:
                                config.ALL_TITLES[k][i] = entry
                                break
            except Exception:
                pass
            
            # Refresh treeview to show updated titles
            update_treeview_with_titles(config.ALL_TITLES)
            
            # Re-select the item after refresh
            try:
                tree_adapter.set_selection_indices([idx])
                tree_adapter.see_index(idx)
            except Exception:
                pass
            
            # Refresh editor
            _populate_editor_from_selection()
            messagebox.showinfo('Prefix', f'Added prefix "{prefix}" to title.')
        except Exception as e:
            messagebox.showerror('Prefix Error', f'Failed to add prefix: {e}')
    
    ttk.Label(editor_frame, text='Title:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    title_row = ttk.Frame(editor_frame)
    title_row.pack(anchor='w', fill='x', pady=(0, 8))
    title_row.columnconfigure(0, weight=1)
    ttk.Entry(title_row, textvariable=editor_rule_name, font=('Segoe UI', 9)).grid(row=0, column=0, sticky='ew')
    ttk.Button(title_row, text='Prefix', command=_add_prefix_to_selected, width=8).grid(row=0, column=1, sticky='e', padx=(8, 0))

    inline_validation_var = tk.StringVar(value='')
    inline_validation_label = ttk.Label(editor_frame, textvariable=inline_validation_var, foreground='#b00020')
    inline_validation_label.pack(anchor='w', pady=(0, 6))
    
    ttk.Label(editor_frame, text='Match Pattern:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    ttk.Entry(editor_frame, textvariable=editor_must, font=('Segoe UI', 9)).pack(anchor='w', fill='x', pady=(0, 8))
    
    # ==================== Feed Title Lookup Section ====================
    feed_lookup_frame = ttk.LabelFrame(editor_frame, text='📡 Title Variations', padding=12)
    feed_lookup_frame.pack(fill='x', pady=(0, 10))
    
    subsplease_title_var = tk.StringVar(value='')
    fetch_status_var = tk.StringVar(value='')
    apply_match_var = tk.BooleanVar(value=True)
    apply_title_var = tk.BooleanVar(value=False)
    apply_savepath_var = tk.BooleanVar(value=False)

    # Header row with status
    title_label_row = ttk.Frame(feed_lookup_frame)
    title_label_row.pack(fill='x', pady=(0, 6))

    apply_targets_row = ttk.Frame(title_label_row)
    apply_targets_row.pack(side='left')
    ttk.Checkbutton(apply_targets_row, text='Match Pattern', variable=apply_match_var).pack(side='left', padx=(0, 8))
    ttk.Checkbutton(apply_targets_row, text='Title', variable=apply_title_var).pack(side='left', padx=(0, 8))
    ttk.Checkbutton(apply_targets_row, text='Save Path', variable=apply_savepath_var).pack(side='left')

    fetch_status_label = ttk.Label(feed_lookup_frame, textvariable=fetch_status_var,
                                   font=('Segoe UI', 8), foreground='#0078D4')
    fetch_status_label.pack(anchor='w', pady=(0, 4))

    def _ensure_apply_target_selected(*_args) -> None:
        if not (bool(apply_match_var.get()) or bool(apply_title_var.get()) or bool(apply_savepath_var.get())):
            apply_match_var.set(True)

    apply_match_var.trace_add('write', _ensure_apply_target_selected)
    apply_title_var.trace_add('write', _ensure_apply_target_selected)
    apply_savepath_var.trace_add('write', _ensure_apply_target_selected)

    def _suggest_save_path_from_title(new_title: str) -> str:
        """Build a save path suggestion by replacing only the title portion of the leaf folder."""
        sanitized_leaf = sanitize_folder_name(str(new_title or '').strip())
        if not sanitized_leaf:
            return str(editor_savepath.get() or '')

        current_path = str(editor_savepath.get() or '').strip().replace('\\', '/')
        if not current_path:
            return sanitized_leaf

        parts = [p for p in current_path.split('/') if p]
        if not parts:
            return sanitized_leaf

        current_leaf = parts[-1]
        season_year_prefix = ''

        # Preserve existing season/year prefix when it's embedded in the leaf name,
        # e.g. "Fall 2026 - Old Title" -> "Fall 2026 - New Title".
        match = re.match(r'^((Winter|Spring|Summer|Fall)\s+(\d{4})\s*-\s*)(.+)$', current_leaf, flags=re.IGNORECASE)
        if match:
            season_year_prefix = match.group(1)

        parts[-1] = f"{season_year_prefix}{sanitized_leaf}" if season_year_prefix else sanitized_leaf
        return '/'.join(parts)

    def _apply_variation_value(value: str, source_label: str) -> None:
        targets = []
        if bool(apply_match_var.get()):
            editor_must.set(value)
            targets.append('match pattern')
        if bool(apply_title_var.get()):
            editor_rule_name.set(value)
            targets.append('title')
        if bool(apply_savepath_var.get()):
            editor_savepath.set(_suggest_save_path_from_title(value))
            targets.append('save path')

        if targets:
            status_var.set(f"Applied {source_label} to {', '.join(targets)}")

    # AniList section
    anilist_section = ttk.Frame(feed_lookup_frame)
    anilist_section.pack(fill='x', pady=(0, 6))
    ttk.Label(anilist_section, text='AniList:', font=('Segoe UI', 9, 'bold')).pack(anchor='w')
    anilist_values_frame = ttk.Frame(anilist_section)
    anilist_values_frame.pack(fill='x', expand=True, pady=(2, 0))

    def _apply_anilist_variation(value: str) -> None:
        _apply_variation_value(value, 'AniList variation')

    # SubsPlease section
    subsplease_row = ttk.Frame(feed_lookup_frame)
    subsplease_row.pack(fill='x', pady=(0, 8))
    ttk.Label(subsplease_row, text='SubsPlease:', font=('Segoe UI', 9, 'bold')).pack(anchor='w')

    subsplease_label = ttk.Label(subsplease_row, textvariable=subsplease_title_var,
                                 font=('Segoe UI', 8), foreground='#0078D4',
                                 cursor='hand2', padding=(4, 4))
    subsplease_label.pack(fill='x', expand=True)

    create_tooltip(subsplease_label, 'Click to apply this SubsPlease title to selected targets')

    def _use_subsplease_title():
        """Apply SubsPlease title to selected targets."""
        sp_title = subsplease_title_var.get().strip()
        if sp_title and not sp_title.startswith('('):
            _apply_variation_value(sp_title, 'SubsPlease title')

    subsplease_label.bind('<Button-1>', lambda e: _use_subsplease_title())
        
    # Fetch button frame
    fetch_btn_frame = ttk.Frame(feed_lookup_frame)
    fetch_btn_frame.pack(fill='x', pady=(0, 0))
    
    def _fetch_subsplease_titles(force_refresh: bool = False):
        """Fetches SubsPlease schedule in background thread."""
        def _worker():
            try:
                fetch_status_var.set(
                    '⏳ Fetching fresh data from SubsPlease API...'
                    if force_refresh else '⏳ Loading cache...'
                )

                result = run_subsplease_refresh(
                    force_refresh=force_refresh,
                    can_pull_subsplease_cache=can_pull_subsplease_cache,
                    fetch_subsplease_schedule=fetch_subsplease_schedule,
                )
                fetch_status_var.set(str(result.get('fetch_status', '')))
                app_status = str(result.get('app_status', '') or '')
                if app_status:
                    status_var.set(app_status)

                if bool(result.get('should_update_variations', False)):
                    _update_feed_variations()
            except Exception as e:
                fetch_status_var.set(f'❌ Error: {str(e)}')
                logger.error(f"Error fetching SubsPlease titles: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _update_feed_variations():
        """Updates feed title variations when title selection changes."""
        try:
            current_title = editor_rule_name.get()
            current_must = editor_must.get()
            state = build_rule_editor_feed_state(
                current_title=current_title,
                current_must=current_must,
                find_subsplease_title_match=find_subsplease_title_match,
                load_title_variations_cache=load_title_variations_cache,
            )

            render_anilist_variations(
                container=anilist_values_frame,
                aliases=state.get('aliases', []),
                link_color=link_color,
                on_apply=_apply_anilist_variation,
                alias_display_map=state.get('alias_display_map', {}),
                empty_text=str(state.get('alias_empty_text', '(No AniList variations cached yet)')),
            )

            subsplease_title_var.set(str(state.get('subsplease_title', '')))
            fetch_status_var.set(str(state.get('status', '')))
        except Exception as e:
            subsplease_title_var.set('(Error)')
            render_anilist_variations(
                container=anilist_values_frame,
                aliases=[],
                link_color=link_color,
                on_apply=_apply_anilist_variation,
                alias_display_map={},
                empty_text='(No AniList variations cached yet)',
            )
            logger.error(f"Error updating feed variations: {e}")

    def _manual_refresh_anilist_cache(refresh_scope_override: str | None = None):
        """Pull AniList aliases for current Match Pattern/Title plus cache with cooldown protection."""
        def _worker():
            try:
                fetch_status_var.set('⏳ Refreshing AniList alias cache...')

                result = run_anilist_refresh(
                    can_pull_anilist_cache=can_pull_anilist_cache,
                    load_subsplease_cache=load_subsplease_cache,
                    refresh_anilist_cache_with_limit=refresh_anilist_cache_with_limit,
                    current_title=editor_rule_name.get(),
                    current_must=editor_must.get(),
                    selected_season=season_var.get(),
                    selected_year=year_var.get(),
                    refresh_scope_override=refresh_scope_override,
                )
                fetch_status_var.set(str(result.get('fetch_status', '')))
                app_status = str(result.get('app_status', '') or '')
                if app_status:
                    status_var.set(app_status)

                if bool(result.get('should_update_variations', False)):
                    _update_feed_variations()
            except Exception as e:
                fetch_status_var.set(f'❌ AniList refresh failed: {e}')
                status_var.set('AniList cache refresh failed')

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception as e:
            fetch_status_var.set(f'❌ Failed to start: {str(e)}')

    def _set_refresh_scope_and_refresh(scope: str) -> None:
        """Trigger AniList refresh using an explicit scope from the dropdown."""
        _manual_refresh_anilist_cache(refresh_scope_override=scope)

    try:
        app_state.quick_refresh_subsplease_action = lambda: _fetch_subsplease_titles(force_refresh=True)
        app_state.quick_refresh_anilist_action = _manual_refresh_anilist_cache
    except Exception:
        pass
    
    # Fetch buttons
    try:
        fetch_font_size_pref = int(config.get_pref('font_size', 10))
    except Exception:
        fetch_font_size_pref = 10
    fetch_ui_colors = get_ui_theme_colors(fetch_font_size_pref)
    split_button_bg = fetch_ui_colors['button_bg']
    split_button_fg = fetch_ui_colors['button_text']
    split_button_border = fetch_ui_colors['border_color']
    split_button_hover = fetch_ui_colors['button_hover']
    split_button_pressed = fetch_ui_colors['button_pressed']
    split_button_split = fetch_ui_colors['button_disabled_bg']

    fetch_fresh_btn = ttk.Button(
        fetch_btn_frame,
        text='🔄 Refresh SubsPlease Cache',
        command=lambda: _fetch_subsplease_titles(force_refresh=True),
    )
    fetch_fresh_btn.pack(side='left', fill='x', expand=True, padx=(0, 4))
    create_tooltip(fetch_fresh_btn, 'Fetches the latest schedule from SubsPlease API (rate-limited by Settings)')

    anilist_refresh_shell = tk.Frame(fetch_btn_frame, bg=editor_bg, highlightthickness=0)
    anilist_refresh_shell.pack(side='left', fill='x', expand=True, padx=(4, 0))

    anilist_refresh_canvas = tk.Canvas(
        anilist_refresh_shell,
        height=30,
        bg=editor_bg,
        highlightthickness=0,
        bd=0,
        cursor='hand2',
    )
    anilist_refresh_canvas.pack(fill='x', expand=True)

    anilist_refresh_menu = tk.Menu(anilist_refresh_canvas, tearoff=0)
    anilist_refresh_menu.add_command(
        label='Current title only',
        command=lambda: _set_refresh_scope_and_refresh(AniListRefreshScope.TITLE_ONLY),
    )
    anilist_refresh_menu.add_command(
        label='Current title + selected season/year',
        command=lambda: _set_refresh_scope_and_refresh(AniListRefreshScope.TITLE_AND_SEASON),
    )

    def _show_anilist_menu_from_arrow(widget: tk.Widget) -> None:
        try:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height()
            anilist_refresh_menu.tk_popup(x, y)
        finally:
            try:
                anilist_refresh_menu.grab_release()
            except Exception:
                pass

    button_state = {'hover': False, 'pressed': False}
    
    def _draw_anilist_split_button(_event=None) -> None:
        try:
            anilist_refresh_canvas.delete('all')
            width = max(1, int(anilist_refresh_canvas.winfo_width() or 1))
            height = max(1, int(anilist_refresh_canvas.winfo_height() or 30))
            arrow_width = 30
            split_x = max(0, width - arrow_width)
    
            fill_color = split_button_bg
            if button_state['pressed']:
                fill_color = split_button_pressed
            elif button_state['hover']:
                fill_color = split_button_hover
    
            anilist_refresh_canvas.create_rectangle(
                1,
                1,
                width - 1,
                height - 1,
                outline=split_button_border,
                width=1,
                fill=fill_color,
            )
            anilist_refresh_canvas.create_line(split_x, 2, split_x, height - 2, fill=split_button_border, width=1)
            anilist_refresh_canvas.create_rectangle(
                split_x,
                1,
                width - 1,
                height - 1,
                outline='',
                fill=split_button_split,
            )
            anilist_refresh_canvas.create_line(split_x, 2, split_x, height - 2, fill=split_button_border, width=1)
            anilist_refresh_canvas.create_text(
                10,
                height // 2,
                text='🧠 Refresh AniList Cache',
                fill=split_button_fg,
                anchor='w',
                font=get_ui_font(weight='normal'),
            )
            anilist_refresh_canvas.create_text(
                split_x + (arrow_width // 2),
                height // 2 - 1,
                text='▾',
                fill=split_button_fg,
                anchor='center',
                font=get_ui_font(weight='bold'),
            )
        except Exception:
            pass
    
    def _anilist_refresh_press(event):
        try:
            button_state['pressed'] = True
            _draw_anilist_split_button()
        except Exception:
            pass
    
    def _anilist_refresh_release(event):
        try:
            width = max(1, int(anilist_refresh_canvas.winfo_width() or 1))
            arrow_width = 30
            split_x = max(0, width - arrow_width)
            button_state['pressed'] = False
            _draw_anilist_split_button()
            if event.x >= split_x:
                _show_anilist_menu_from_arrow(anilist_refresh_canvas)
            else:
                _manual_refresh_anilist_cache()
        except Exception:
            pass
    
    def _anilist_refresh_enter(_event=None):
        button_state['hover'] = True
        _draw_anilist_split_button()
    
    def _anilist_refresh_leave(_event=None):
        button_state['hover'] = False
        button_state['pressed'] = False
        _draw_anilist_split_button()
    
    anilist_refresh_canvas.bind('<Configure>', _draw_anilist_split_button)
    anilist_refresh_canvas.bind('<ButtonPress-1>', _anilist_refresh_press)
    anilist_refresh_canvas.bind('<ButtonRelease-1>', _anilist_refresh_release)
    anilist_refresh_canvas.bind('<Enter>', _anilist_refresh_enter)
    anilist_refresh_canvas.bind('<Leave>', _anilist_refresh_leave)
    anilist_refresh_canvas.bind('<Button-3>', lambda _event: _show_anilist_menu_from_arrow(anilist_refresh_canvas))

    create_tooltip(
        anilist_refresh_canvas,
        'Refreshes AniList title aliases for cached titles. Use the arrow for a season/year-wide pull.',
    )
    _draw_anilist_split_button()
    
    # Load initial cache status (auto-load on startup)
    try:
        cached = load_subsplease_cache()
        if cached:
            fetch_status_var.set(f'📦 {len(cached)} titles in cache')
        else:
            fetch_status_var.set('📦 Cache empty - click Refresh SubsPlease Cache')
    except Exception:
        fetch_status_var.set('📦 Cache empty')
    
    # ==================== End Feed Title Lookup Section ====================
    
    ttk.Label(editor_frame, text='Last Match:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    editor_lastmatch_text.pack(anchor='w', pady=(0, 2), fill='x', expand=True)
    editor_lastmatch_text.pack_forget()

    lastmatch_details_visible = {'flag': False}

    # Create a single row for status and age labels to eliminate blank space
    status_age_row = ttk.Frame(editor_frame)
    status_age_row.pack(fill='x', pady=(0, 8))
    
    lastmatch_status_label = tk.Label(status_age_row, text='', fg=success_color, font=('Segoe UI', 8), bg=editor_bg)
    lastmatch_status_label.pack(side='left', padx=(0, 10))
    
    age_label = ttk.Label(status_age_row, text='Age: N/A', font=('Segoe UI', 8))
    age_label.pack(side='left')

    def _toggle_lastmatch_details():
        lastmatch_details_visible['flag'] = not lastmatch_details_visible['flag']
        if lastmatch_details_visible['flag']:
            editor_lastmatch_text.pack(anchor='w', pady=(0, 2), fill='x', expand=True, before=status_age_row)
            lastmatch_toggle_btn.config(text='Hide date')
        else:
            editor_lastmatch_text.pack_forget()
            lastmatch_toggle_btn.config(text='Show date')

    lastmatch_toggle_btn = ttk.Button(status_age_row, text='Show date', width=10, command=_toggle_lastmatch_details)
    lastmatch_toggle_btn.pack(side='right')
    
    current_lastmatch_holder = {'value': None}
    try:
        pref_val = config.get_pref('time_24', True)
    except Exception:
        pref_val = True
    time_24_var = tk.BooleanVar(value=bool(pref_val))
    
    ttk.Label(editor_frame, text='Save Path:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    editor_savepath_entry = ttk.Entry(editor_frame, textvariable=editor_savepath, font=('Segoe UI', 9))
    editor_savepath_entry.pack(anchor='w', fill='x', pady=(0, 8))
    
    # Track if save path was manually edited (to prevent auto-fill overwriting user edits)
    savepath_manually_edited = {'flag': False}
    
    def _on_savepath_change(*args):
        """Mark save path as manually edited when user types in it."""
        savepath_manually_edited['flag'] = True
    
    # Bind to detect manual edits (triggered when user types)
    editor_savepath_entry.bind('<KeyRelease>', lambda e: _on_savepath_change())
    
    ttk.Label(editor_frame, text='Category:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    # Use Combobox for category with cached categories
    editor_category_combo = ttk.Combobox(editor_frame, textvariable=editor_category, font=('Segoe UI', 9))
    editor_category_combo.pack(anchor='w', fill='x', pady=(0, 8))
    
    def _on_category_change(*args):
        """Auto-fill save path from category's save path if not manually edited and no custom save path exists."""
        if savepath_manually_edited['flag']:
            return  # User has manually edited save path, don't override
        
        try:
            selected_category = editor_category.get().strip()
            if not selected_category:
                return
            
            # Get current save path
            current_save_path = editor_savepath.get().strip()
            
            # Get category info from cached categories
            cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
            if isinstance(cached_cats, dict) and selected_category in cached_cats:
                cat_info = cached_cats[selected_category]
                cat_save_path = get_category_save_path(cat_info)
                    
                # Only auto-fill if:
                # 1. There's no current save path (empty field), OR
                # 2. Current save path matches the category's default (user hasn't customized it)
                # This prevents overwriting custom save paths when loading rules
                if cat_save_path and not current_save_path:
                    # Empty field, safe to auto-fill
                    editor_savepath.set(cat_save_path)
                elif cat_save_path and current_save_path == cat_save_path:
                    # Already matches category default, no change needed
                    pass
                # else: Custom save path exists, don't override it
        except Exception:
            pass
    
    # Bind category change to auto-fill save path
    editor_category.trace_add('write', _on_category_change)

    def _update_inline_validation() -> bool:
        """Update inline validation hint for common editor field issues."""
        try:
            title_val = editor_rule_name.get().strip()
            save_val = editor_savepath.get().strip()
        except Exception:
            inline_validation_var.set('')
            return True

        if not title_val:
            inline_validation_var.set('Title cannot be empty.')
            return False

        if save_val and len(save_val) > 260:
            inline_validation_var.set('Save Path is unusually long (>260 chars). Consider shortening it.')
            return True

        inline_validation_var.set('')
        return True

    try:
        editor_rule_name.trace_add('write', lambda *_a: _update_inline_validation())
        editor_savepath.trace_add('write', lambda *_a: _update_inline_validation())
    except Exception:
        pass
    
    # Function to update category cache
    def _update_category_cache():
        try:
            categories = set()
            
            # Load cached categories from config
            try:
                config.load_cached_categories()
                cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
                if isinstance(cached_cats, dict):
                    categories.update(cached_cats.keys())
                elif isinstance(cached_cats, list):
                    categories.update(cached_cats)
            except Exception:
                pass
            
            # Add categories from current listbox items
            for title_text, entry in listbox_items:
                if isinstance(entry, dict):
                    cat = entry.get('assignedCategory') or entry.get('assigned_category') or entry.get('category') or ''
                    if cat:
                        categories.add(str(cat))
                    tp = entry.get('torrentParams') or {}
                    if isinstance(tp, dict) and tp.get('category'):
                        categories.add(str(tp['category']))
            
            editor_category_combo['values'] = sorted(list(categories))
        except Exception:
            pass
    
    # Update cache initially
    _update_category_cache()
    
    ttk.Separator(editor_frame, orient='horizontal').pack(fill='x', pady=(0, 10))

    btns = ttk.Frame(editor_frame)
    btns.pack(anchor='center', pady=(0, 0), fill='x')

    def _populate_editor_from_selection(event=None):
        """
        Populates the editor panel with data from the selected listbox item.
        
        Args:
            event: Optional Tkinter event (for event binding)
        """
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                return
            idx = int(sel[0])
            mapped = listbox_items[idx]
            title_text, entry = mapped[0], mapped[1]
        except Exception:
            return

        editor_rule_name.set(title_text)
        must = ''
        save = ''
        cat = ''
        en = True
        try:
            if isinstance(entry, dict):
                node = entry.get('node') or {}
                must = entry.get('mustContain') or entry.get('must_contain') or node.get('title') or title_text

                def _find(d, candidates):
                    try:
                        if not isinstance(d, dict):
                            return None
                        for k in candidates:
                            if k in d and d.get(k) is not None and str(d.get(k)).strip() != '':
                                return d.get(k)
                    except Exception:
                        pass
                    return None

                tp = None
                for tp_key in ('torrentParams', 'torrent_params', 'torrentparams'):
                    if isinstance(entry, dict) and tp_key in entry and isinstance(entry[tp_key], dict):
                        tp = entry[tp_key]
                        break

                save_val = _find(entry, ['savePath', 'save_path']) or (_find(tp, ['save_path', 'savePath', 'download_path']) if tp else None)
                save = '' if save_val is None else str(save_val).replace('\\', '/')

                cat_val = _find(entry, ['assignedCategory', 'assigned_category', 'category']) or (_find(tp, ['category']) if tp else None)
                cat = '' if cat_val is None else str(cat_val)

                en = bool(entry.get('enabled', True))
                try:
                    lm = entry.get('lastMatch', '')
                except Exception:
                    lm = ''
                current_lastmatch_holder['value'] = lm
                try:
                    update_lastmatch_display(lm)
                except Exception:
                    try:
                        editor_lastmatch_text.config(state='normal')
                        editor_lastmatch_text.delete('1.0', 'end')
                        editor_lastmatch_text.insert('1.0', '' if lm is None else str(lm))
                        editor_lastmatch_text.config(state='disabled')
                    except Exception:
                        pass
            else:
                must = str(entry)
        except Exception:
            must = title_text

        editor_must.set(must)
        editor_savepath.set(save)
        editor_category.set(cat)
        editor_enabled.set(en)
        _refresh_enabled_toggle_button()
        
        # Reset manual edit flag when loading from selection
        savepath_manually_edited['flag'] = False
        
        # Update category cache
        try:
            _update_category_cache()
        except Exception:
            pass
        
        # Update feed title variations
        try:
            _update_feed_variations()
        except Exception:
            pass

        try:
            _update_inline_validation()
        except Exception:
            pass

    def update_lastmatch_display(lm_value=None):
        """
        Updates the lastMatch display field with formatted datetime information.
        
        Args:
            lm_value: Optional lastMatch value to display (uses cached value if None)
        """
        try:
            val = lm_value if lm_value is not None else current_lastmatch_holder.get('value')
            try:
                editor_lastmatch_text.config(state='normal')
            except Exception:
                pass
            try:
                editor_lastmatch_text.delete('1.0', 'end')
            except Exception:
                pass
            try:
                lastmatch_status_label.config(text='', fg='green')
            except Exception:
                pass
            display_text, age_text = format_lastmatch_value(
                value=val,
                use_24h=bool(time_24_var.get()),
                parse_datetime_from_string=parse_datetime_from_string,
            )
            editor_lastmatch_text.insert('1.0', display_text)
            age_label.config(text=age_text)
        except Exception:
            try:
                editor_lastmatch_text.insert('1.0', '' if lm_value is None else str(lm_value))
            except Exception:
                pass
        finally:
            try:
                editor_lastmatch_text.config(state='disabled')
            except Exception:
                pass

    def validate_lastmatch_json(event=None):
        """
        Validates JSON in the lastMatch text field and updates status label.
        
        Args:
            event: Optional Tkinter event (for event binding)
        
        Returns:
            bool: True if JSON is valid or field is empty/non-JSON, False if invalid JSON
        """
        try:
            txt = editor_lastmatch_text.get('1.0', 'end').strip()
            lastmatch_status_label.config(text='', fg='green')
            ok, message = validate_lastmatch_json_text(txt)
            if message:
                lastmatch_status_label.config(text=message, fg='green' if ok else 'red')
            return ok
        except Exception:
            try:
                lastmatch_status_label.config(text='Invalid JSON', fg='red')
            except Exception:
                pass
            return False

    try:
        editor_lastmatch_text.bind('<KeyRelease>', lambda e: validate_lastmatch_json())
        editor_lastmatch_text.bind('<FocusOut>', lambda e: validate_lastmatch_json())
    except Exception:
        pass

    try:
        def _on_time24_changed(*a):
            try:
                config.set_pref('time_24', bool(time_24_var.get()))
                # Refresh lastmatch display with new time format
                try:
                    update_lastmatch_display()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            time_24_var.trace_add('write', lambda *a: _on_time24_changed())
        except Exception:
            try:
                time_24_var.trace('w', lambda *a: _on_time24_changed())
            except Exception:
                pass
    except Exception:
        pass

    def _apply_editor_changes(silent=False):
        """
        Applies changes from the editor panel to the selected listbox item.
        
        Updates the selected title's configuration with values from the editor
        fields and refreshes the display.
        
        Args:
            silent: If True, don't show success message or validation dialogs
        """
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                if not silent:
                    messagebox.showwarning('Edit', 'No title selected.')
                return False
            idx = int(sel[0])
            mapped = listbox_items[idx]
            title_text, entry = mapped[0], mapped[1]
        except Exception:
            if not silent:
                messagebox.showerror('Edit', 'Failed to locate selected item.')
            return False

        new_title = editor_rule_name.get().strip()
        new_must = editor_must.get().strip()
        new_save = editor_savepath.get().strip()
        new_cat = editor_category.get().strip()
        new_en = bool(editor_enabled.get())
        try:
            new_lastmatch = editor_lastmatch_text.get('1.0', 'end').strip()
        except Exception:
            new_lastmatch = ''

        if not new_title:
            inline_validation_var.set('Title cannot be empty.')
            return False

        try:
            _update_inline_validation()
        except Exception:
            pass

        # If nothing changed, don't save undo or apply.
        if not editor_has_changes(
            entry=entry,
            original_title=title_text,
            new_title=new_title,
            new_must=new_must,
            new_save=new_save,
            new_cat=new_cat,
            new_enabled=new_en,
        ):
            return True

        try:
            # Save undo state before applying changes (only if there are actual changes)
            _save_undo_state()
            
            lm_val, lm_error = parse_lastmatch_input(new_lastmatch)
            if lm_error and not silent:
                try:
                    if not messagebox.askyesno('Invalid JSON', f'Last Match appears to be JSON but is invalid:\n{lm_error}\n\nApply as raw text anyway?'):
                        return False
                except Exception:
                    return False

            entry = apply_editor_values_to_entry(
                entry=entry,
                new_title=new_title,
                new_must=new_must,
                new_save=new_save,
                new_cat=new_cat,
                new_enabled=new_en,
                lastmatch_value=lm_val,
            )
            
            # Update listbox_items with the modified entry
            listbox_items[idx] = (new_title, entry)
            logger.debug(f"Updated listbox_items[{idx}], entry id: {id(entry)}, mustContain: {entry.get('mustContain')}")
            
            # Persist updated entry and refresh tree view.
            try:
                if getattr(config, 'ALL_TITLES', None):
                    persist_result = persist_editor_entry_and_refresh_view(
                        all_titles=config.ALL_TITLES,
                        entry=entry,
                        old_title=title_text,
                        new_title=new_title,
                        idx=idx,
                        treeview=treeview,
                        tree_adapter=tree_adapter,
                        get_display_title=get_display_title,
                        update_treeview_with_titles=update_treeview_with_titles,
                    )
                    if not persist_result.get('updated_in_all_titles', False):
                        logger.warning(f"Failed to find entry to update in ALL_TITLES for title: {title_text}")
            except Exception as e:
                logger.error(f"Error updating ALL_TITLES: {e}", exc_info=True)
            
            # Don't auto-refresh during silent apply to avoid recursion
            if not silent:
                # Auto-refresh the editor to show updated values
                try:
                    _populate_editor_from_selection()
                except Exception:
                    pass
                status_var.set('Changes auto-applied')

            # Keep Title Variations synced with the latest editor values.
            try:
                _update_feed_variations()
            except Exception:
                pass
            
            return True
        except Exception as e:
            if not silent:
                messagebox.showerror('Edit Error', f'Failed to apply changes: {e}')
            return False
    
    # Auto-apply when fields change (debounced)
    auto_apply_after_id = {'id': None}
    
    def _schedule_auto_apply(*args):
        """Schedules auto-apply after a short delay (debouncing)."""
        try:
            # Cancel previous scheduled apply
            if auto_apply_after_id['id']:
                root.after_cancel(auto_apply_after_id['id'])
            
            # Schedule new apply after 300ms of no changes (fast response)
            auto_apply_after_id['id'] = root.after(UIConstants.EDITOR_AUTO_APPLY_DEBOUNCE_MS, lambda: _apply_editor_changes(silent=True))
        except Exception:
            pass
    
    # Attach auto-apply to editor fields
    try:
        editor_rule_name.trace_add('write', _schedule_auto_apply)
        editor_must.trace_add('write', _schedule_auto_apply)
        editor_savepath.trace_add('write', _schedule_auto_apply)
        editor_category.trace_add('write', _schedule_auto_apply)
        editor_enabled.trace_add('write', _schedule_auto_apply)
        editor_enabled.trace_add('write', lambda *_a: _refresh_enabled_toggle_button())
    except Exception:
        # Fallback for older Python/Tkinter versions
        try:
            editor_rule_name.trace('w', _schedule_auto_apply)
            editor_must.trace('w', _schedule_auto_apply)
            editor_savepath.trace('w', _schedule_auto_apply)
            editor_category.trace('w', _schedule_auto_apply)
            editor_enabled.trace('w', _schedule_auto_apply)
            editor_enabled.trace('w', lambda *_a: _refresh_enabled_toggle_button())
        except Exception:
            pass

    def open_full_rule_editor_for_selection():
        """
        Opens the full rule editor dialog for the selected listbox item.
        """
        try:
            sel = tree_adapter.get_selected_indices()
            if not sel:
                messagebox.showwarning('Edit', 'No title selected.')
                return
            idx = int(sel[0])
            title_text, entry = listbox_items[idx]
        except Exception:
            messagebox.showerror('Edit', 'Failed to locate selected item.')
            return
        open_full_rule_editor(root, title_text, entry, idx, _populate_editor_from_selection)

    ttk.Button(btns, text='🔧 Advanced Settings...', command=open_full_rule_editor_for_selection, style='Secondary.TButton', width=25).pack(fill='x', pady=(0, 5))

    try:
        treeview.bind('<<TreeviewSelect>>', _populate_editor_from_selection)
        try:
            def _on_item_double_click(event):
                """Open editor only if not clicking on separator"""
                try:
                    region = treeview.identify_region(event.x, event.y)
                    if region != "separator":
                        open_full_rule_editor_for_selection()
                except Exception:
                    pass
            treeview.bind('<Double-1>', _on_item_double_click)
        except Exception:
            pass
    except Exception:
        pass
    
    return (editor_rule_name, editor_must, editor_savepath, editor_category, 
            editor_enabled, editor_lastmatch_text)


# Public API
__all__ = [
    'setup_window_and_styles',
    'setup_status_and_autoconnect',
    'setup_menu_bar',
    'setup_keyboard_shortcuts',
    'setup_season_controls',
    'setup_library_panel',
    'setup_editor_panel',
    'setup_gui',
    'exit_handler',
]
