"""
Dialog windows for the application.

Contains settings dialog, import/export dialogs, and other modal windows.
"""
# Standard library imports
import json
import logging
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

# Local application imports
import src.api.qbittorrent as qbt_api
from src.config import config
from src.constants import AniListCacheRetentionMode, AniListRefreshScope, FileSystem, PrefKeys
from src.gui.app_state import AppState
from src.gui.file_operations import import_titles_from_file, update_treeview_with_titles
from src.gui.helpers import center_window, get_ui_font, get_ui_mono_font
from src.gui.treeview_adapter import TreeviewAdapter
from src.utils import get_category_save_path, get_current_anime_season, get_server_display_name, get_validation_profile_label

logger = logging.getLogger(__name__)


def open_setup_wizard(root: tk.Tk, status_var: tk.StringVar) -> None:
    """Open first-run setup wizard flow using the settings window."""
    try:
        status_var.set('🧭 Setup Wizard: configure connection and defaults, then click Save')
    except Exception:
        pass

    open_settings_window(root, status_var)

    try:
        messagebox.showinfo(
            'Setup Wizard',
            'Welcome to Torrent RSS Rule Editor.\n\n'
            'Use Settings to configure connection details and defaults, then click Save.'
        )
    except Exception:
        pass


def open_settings_window(root: tk.Tk, status_var: tk.StringVar) -> None:
    """
    Opens the settings dialog window for qBittorrent connection configuration.
    
    Creates a settings dialog allowing users to configure qBittorrent WebUI connection
    parameters including host, port, credentials, and SSL settings.
    
    Args:
        root: Parent Tkinter window
        status_var: Status bar variable for displaying connection status
    """
    existing_settings = getattr(root, '_settings_window', None)
    if existing_settings is not None:
        try:
            if existing_settings.winfo_exists():
                existing_settings.lift()
                existing_settings.focus_force()
                return
        except tk.TclError:
            logger.debug("Existing settings window reference is stale", exc_info=True)
        try:
            setattr(root, '_settings_window', None)
        except AttributeError:
            logger.debug("Could not clear settings window reference on root", exc_info=True)

    settings_win = tk.Toplevel(root)
    setattr(root, '_settings_window', settings_win)
    settings_win.title("⚙️ Settings - Configuration (UI v2)")
    
    # Try to fit full settings on screen
    from src.constants import UIConfig
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    optimal_width = min(UIConfig.SETTINGS_WINDOW_WIDTH, max(640, screen_width - 40))
    optimal_height = min(900, max(500, screen_height - 100))  # Leave space for taskbar
    min_width = min(UIConfig.SETTINGS_WINDOW_WIDTH, max(560, screen_width - 80))
    min_height = min(UIConfig.SETTINGS_WINDOW_MIN_HEIGHT, max(420, screen_height - 160))
    settings_win.geometry(f"{optimal_width}x{optimal_height}")
    settings_win.minsize(min_width, min_height)
    settings_win.transient(root)
    settings_win.focus_set()

    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'

    if theme_pref == 'dark':
        settings_bg = '#14181f'
        listbox_bg = '#1a2028'
        listbox_fg = '#e6edf3'
        listbox_select_bg = '#1f6feb'
        listbox_select_fg = '#ffffff'
        subtle_fg = '#9aa7b2'
    else:
        settings_bg = '#f5f5f5'
        listbox_bg = '#ffffff'
        listbox_fg = '#333333'
        listbox_select_bg = '#0078D4'
        listbox_select_fg = '#ffffff'
        subtle_fg = '#666'

    settings_win.configure(bg=settings_bg)
    # Always place Settings on the same display as the main window.
    center_window(settings_win, width=optimal_width, height=optimal_height, parent=root)
    try:
        # Re-apply once after layout settles to avoid platform-specific placement drift.
        settings_win.after_idle(
            lambda: center_window(settings_win, width=optimal_width, height=optimal_height, parent=root)
        )
    except Exception:
        pass

    def _close_settings_window() -> None:
        """Close settings and clear root window reference."""
        try:
            setattr(root, '_settings_window', None)
        except AttributeError:
            logger.debug("Could not clear settings window reference on close", exc_info=True)
        try:
            settings_win.destroy()
        except tk.TclError:
            logger.debug("Settings window already destroyed", exc_info=True)

    # Initialize StringVars with config values
    qbt_protocol_temp = tk.StringVar(value=config.QBT_PROTOCOL or 'http')
    qbt_host_temp = tk.StringVar(value=config.QBT_HOST or 'localhost')
    qbt_port_temp = tk.StringVar(value=config.QBT_PORT or '8080')
    qbt_user_temp = tk.StringVar(value=config.QBT_USER or '')
    qbt_pass_temp = tk.StringVar(value=config.QBT_PASS or '')
    mode_temp = tk.StringVar(value=config.CONNECTION_MODE or 'online')
    main_server_temp = tk.StringVar(value=getattr(config, 'MAIN_SERVER', 'qbittorrent') or 'qbittorrent')
    verify_ssl_temp = tk.BooleanVar(value=bool(config.QBT_VERIFY_SSL))
    ca_cert_temp = tk.StringVar(value=config.QBT_CA_CERT or '')
    default_save_path_temp = tk.StringVar(value=config.DEFAULT_SAVE_PATH or '')
    default_category_temp = tk.StringVar(value=config.DEFAULT_CATEGORY or '')
    default_affected_feeds_temp = tk.StringVar(value=', '.join(config.DEFAULT_AFFECTED_FEEDS) if config.DEFAULT_AFFECTED_FEEDS else '')
    export_target_vars: Dict[str, tk.BooleanVar] = {
        'qbittorrent': tk.BooleanVar(value='qbittorrent' in (getattr(config, 'EXPORT_TARGETS', ['qbittorrent']) or ['qbittorrent'])),
        'autobrr': tk.BooleanVar(value='autobrr' in (getattr(config, 'EXPORT_TARGETS', ['qbittorrent']) or ['qbittorrent'])),
    }

    # Sanitization preference state
    try:
        pref_replace_all = config.get_pref(PrefKeys.SANITIZE_REPLACE_ALL, True)
    except (AttributeError, TypeError, ValueError):
        pref_replace_all = True
    sanitize_replace_all_var = tk.BooleanVar(value=bool(pref_replace_all))

    try:
        pref_global_char = config.get_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, '_') or '_'
    except (AttributeError, TypeError, ValueError):
        pref_global_char = '_'
    sanitize_global_char_var = tk.StringVar(value=str(pref_global_char)[:1])

    try:
        pref_custom_map = config.get_pref(PrefKeys.SANITIZE_CUSTOM_MAP, {}) or {}
        if not isinstance(pref_custom_map, dict):
            pref_custom_map = {}
    except (AttributeError, TypeError, ValueError):
        pref_custom_map = {}

    # Per-character replacement variables keyed by invalid char.
    # Supports special action tokens in prefs:
    # - __REMOVE__: remove this character
    # - __SPACE__: replace with a space
    sanitize_char_vars: Dict[str, tk.StringVar] = {}
    for ch in FileSystem.INVALID_CHARS:
        raw_val = pref_custom_map.get(ch, '')
        raw_text = str(raw_val) if raw_val is not None else ''
        token = raw_text.strip().lower()
        if token == '__remove__':
            display_val = 'remove'
        elif token == '__space__':
            display_val = 'space'
        else:
            display_val = raw_text
        sanitize_char_vars[ch] = tk.StringVar(value=display_val)

    def save_and_close():
        """Saves connection settings and closes the settings dialog."""
        try:
            _apply_editor_to_runtime_vars()
        except Exception:
            pass
        # Get and validate inputs
        new_qbt_host = qbt_host_temp.get().strip()
        new_qbt_port = qbt_port_temp.get().strip()
        selected_main_server = str(main_server_temp.get() or 'qbittorrent').strip().lower()
        
        if selected_main_server == 'qbittorrent' and (not new_qbt_host or not new_qbt_port):
            messagebox.showwarning("Warning", "Host and Port are required when main server is qBittorrent.")
            return

        # Keep qBittorrent profile valid even when another model is selected.
        new_qbt_host = new_qbt_host or (config.QBT_HOST or 'localhost')
        new_qbt_port = new_qbt_port or (config.QBT_PORT or '8080')

        # Parse feeds
        feeds_str = default_affected_feeds_temp.get().strip()
        new_default_affected_feeds = [f.strip() for f in feeds_str.split(',') if f.strip()] if feeds_str else []

        # Update config
        config.QBT_CA_CERT = ca_cert_temp.get().strip() or None
        config.DEFAULT_DOWNLOAD_PATH = default_download_path_temp.get().strip()

        try:
            custom_map: Dict[str, str] = {}
            for ch, var in sanitize_char_vars.items():
                val = var.get()
                if val is None:
                    continue
                val_str = str(val)
                if val_str == '':
                    continue
                action = val_str.strip().lower()
                if action == 'remove':
                    custom_map[ch] = '__REMOVE__'
                elif action == 'space':
                    custom_map[ch] = '__SPACE__'
                else:
                    custom_map[ch] = val_str

            config.set_pref(PrefKeys.SANITIZE_REPLACE_ALL, bool(sanitize_replace_all_var.get()))
            config.set_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, sanitize_global_char_var.get() or '_')
            config.set_pref(PrefKeys.SANITIZE_CUSTOM_MAP, custom_map)
        except Exception as e:
            messagebox.showwarning("Warning", f"Could not save sanitization settings: {e}")
            return
        
        # Save to file
        config.save_config(
            qbt_protocol_temp.get().strip(),
            new_qbt_host,
            new_qbt_port,
            qbt_user_temp.get().strip(),
            qbt_pass_temp.get().strip(),
            mode_temp.get(),
            verify_ssl_temp.get(),
            default_save_path_temp.get().strip(),
            default_category_temp.get().strip(),
            new_default_affected_feeds
        )

        selected_export_targets = [
            name for name, enabled_var in export_target_vars.items() if bool(enabled_var.get())
        ]
        if not selected_export_targets:
            selected_export_targets = ['qbittorrent']
        config.save_platform_config(main_server_temp.get(), selected_export_targets)

        _close_settings_window()

    # Tabbed layout for grouped settings (tabs fixed at top)
    settings_notebook = ttk.Notebook(settings_win)
    settings_notebook.pack(fill='both', expand=True, padx=0, pady=0)

    def _create_scrollable_tab(title: str) -> ttk.Frame:
        """Create one notebook tab with its own scrollable content frame."""
        tab_shell = ttk.Frame(settings_notebook)
        settings_notebook.add(tab_shell, text=title)

        tab_canvas = tk.Canvas(tab_shell, bg=settings_bg, highlightthickness=0)
        tab_scrollbar = ttk.Scrollbar(tab_shell, orient='vertical', command=tab_canvas.yview)
        tab_content = ttk.Frame(tab_canvas)

        tab_window = tab_canvas.create_window((0, 0), window=tab_content, anchor='nw')
        tab_canvas.configure(yscrollcommand=tab_scrollbar.set)

        def _update_tab_scrollregion(_event=None):
            try:
                tab_canvas.configure(scrollregion=tab_canvas.bbox('all'))
            except Exception:
                pass

        def _on_tab_canvas_configure(event):
            try:
                tab_canvas.itemconfig(tab_window, width=event.width - 5)
            except Exception:
                pass

        tab_content.bind('<Configure>', _update_tab_scrollregion)
        tab_canvas.bind('<Configure>', _on_tab_canvas_configure)

        tab_canvas.pack(side='left', fill='both', expand=True)
        tab_scrollbar.pack(side='right', fill='y')

        return tab_content

    tab_connection = _create_scrollable_tab('Connection')
    tab_defaults = _create_scrollable_tab('Defaults')
    tab_import = _create_scrollable_tab('Import/Export')
    tab_sanitization = _create_scrollable_tab('Sanitization')
    tab_appearance = _create_scrollable_tab('Appearance')
    tab_font_style = _create_scrollable_tab('Font & Style')
    tab_diagnostics = _create_scrollable_tab('Diagnostics')
    tab_api_rate = _create_scrollable_tab('API Rate Limits')

    settings_win.protocol("WM_DELETE_WINDOW", _close_settings_window)

    # Dedicated top-level Font & Style tab (always visible)
    try:
        fs_frame = ttk.LabelFrame(tab_font_style, text='🔤 Font And Style', padding=10)
        fs_frame.pack(fill='x', pady=(10, 10), padx=10)

        ttk.Label(
            fs_frame,
            text='Adjust UI font family, style theme, and font size (applies after restart):',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 8))

        try:
            fs_family_pref = str(config.get_pref(PrefKeys.FONT_FAMILY, 'Segoe UI') or 'Segoe UI').strip()
        except Exception:
            fs_family_pref = 'Segoe UI'
        fs_family_var = tk.StringVar(value=fs_family_pref)

        fs_family_choices = ['Segoe UI', 'Calibri', 'Arial', 'Tahoma', 'Verdana', 'Trebuchet MS', 'Cambria', 'Consolas']
        if fs_family_pref not in fs_family_choices:
            fs_family_choices.insert(0, fs_family_pref)

        fs_family_row = ttk.Frame(fs_frame)
        fs_family_row.pack(fill='x', pady=(0, 8))
        ttk.Label(fs_family_row, text='Font Family:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        fs_family_combo = ttk.Combobox(fs_family_row, textvariable=fs_family_var, values=fs_family_choices, state='readonly', width=24)
        fs_family_combo.pack(side='left')
        fs_family_combo.bind('<<ComboboxSelected>>', lambda _e: config.set_pref(PrefKeys.FONT_FAMILY, fs_family_var.get().strip() or 'Segoe UI'))

        try:
            fs_style_pref = str(config.get_pref(PrefKeys.UI_STYLE_THEME, 'clam') or 'clam').strip()
        except Exception:
            fs_style_pref = 'clam'
        try:
            fs_style_choices = list(ttk.Style().theme_names())
        except Exception:
            fs_style_choices = ['clam', 'default']
        if fs_style_pref not in fs_style_choices:
            fs_style_choices.insert(0, fs_style_pref)
        fs_style_var = tk.StringVar(value=fs_style_pref)

        fs_style_row = ttk.Frame(fs_frame)
        fs_style_row.pack(fill='x', pady=(0, 8))
        ttk.Label(fs_style_row, text='Widget Style:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        fs_style_combo = ttk.Combobox(fs_style_row, textvariable=fs_style_var, values=fs_style_choices, state='readonly', width=18)
        fs_style_combo.pack(side='left')
        fs_style_combo.bind('<<ComboboxSelected>>', lambda _e: config.set_pref(PrefKeys.UI_STYLE_THEME, fs_style_var.get()))

        try:
            fs_size_pref = int(config.get_pref('font_size', 9))
        except Exception:
            fs_size_pref = 9
        fs_size_var = tk.IntVar(value=max(8, min(14, fs_size_pref)))

        def _save_fs_size(*_args):
            try:
                v = int(fs_size_var.get())
            except Exception:
                v = 9
            v = max(8, min(14, v))
            if v != fs_size_var.get():
                fs_size_var.set(v)
            config.set_pref('font_size', v)

        fs_size_row = ttk.Frame(fs_frame)
        fs_size_row.pack(fill='x', pady=(0, 2))
        ttk.Label(fs_size_row, text='Font Size:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        fs_size_spin = ttk.Spinbox(fs_size_row, from_=8, to=14, textvariable=fs_size_var, width=6, command=_save_fs_size)
        fs_size_spin.pack(side='left')
        fs_size_spin.bind('<FocusOut>', _save_fs_size)
        fs_size_spin.bind('<Return>', _save_fs_size)
        ttk.Label(fs_size_row, text='pt (range: 8-14)', font=('Segoe UI', 8), foreground='#666').pack(side='left', padx=(8, 0))
    except Exception as e:
        logger.error('Failed to build top-level Font & Style tab: %s', e, exc_info=True)

    # Dedicated top-level API Rate Limits tab (always visible)
    try:
        api_frame = ttk.LabelFrame(tab_api_rate, text='⏱️ Manual Refresh Cooldowns', padding=10)
        api_frame.pack(fill='x', pady=(10, 10), padx=10)

        ttk.Label(
            api_frame,
            text='These limits control manual refresh buttons in the Rule Editor.',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 8))

        try:
            api_ani_pref = int(config.get_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, 15))
        except Exception:
            api_ani_pref = 15
        api_ani_var = tk.IntVar(value=max(1, min(1440, api_ani_pref)))

        try:
            api_sp_pref = int(config.get_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, 15))
        except Exception:
            api_sp_pref = 15
        api_sp_var = tk.IntVar(value=max(1, min(1440, api_sp_pref)))

        def _save_api_ani(*_args):
            try:
                v = int(api_ani_var.get())
            except Exception:
                v = 15
            v = max(1, min(1440, v))
            if v != api_ani_var.get():
                api_ani_var.set(v)
            config.set_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, v)

        def _save_api_sp(*_args):
            try:
                v = int(api_sp_var.get())
            except Exception:
                v = 15
            v = max(1, min(1440, v))
            if v != api_sp_var.get():
                api_sp_var.set(v)
            config.set_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, v)

        api_ani_row = ttk.Frame(api_frame)
        api_ani_row.pack(fill='x', pady=(0, 6))
        ttk.Label(api_ani_row, text='AniList minimum interval:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        api_ani_spin = ttk.Spinbox(api_ani_row, from_=1, to=1440, textvariable=api_ani_var, width=8, command=_save_api_ani)
        api_ani_spin.pack(side='left')
        api_ani_spin.bind('<FocusOut>', _save_api_ani)
        api_ani_spin.bind('<Return>', _save_api_ani)
        ttk.Label(api_ani_row, text='minutes', font=('Segoe UI', 9)).pack(side='left', padx=(8, 0))

        api_sp_row = ttk.Frame(api_frame)
        api_sp_row.pack(fill='x', pady=(0, 2))
        ttk.Label(api_sp_row, text='SubsPlease minimum interval:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        api_sp_spin = ttk.Spinbox(api_sp_row, from_=1, to=1440, textvariable=api_sp_var, width=8, command=_save_api_sp)
        api_sp_spin.pack(side='left')
        api_sp_spin.bind('<FocusOut>', _save_api_sp)
        api_sp_spin.bind('<Return>', _save_api_sp)
        ttk.Label(api_sp_row, text='minutes', font=('Segoe UI', 9)).pack(side='left', padx=(8, 0))

        ttl_frame = ttk.LabelFrame(tab_api_rate, text='🗂️ AniList Alias Cache Retention', padding=10)
        ttl_frame.pack(fill='x', pady=(0, 10), padx=10)
        ttk.Label(
            ttl_frame,
            text='Choose how AniList title variations are retained before the cache is trimmed or archived.',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 8))

        try:
            retention_mode_pref = str(
                config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, AniListCacheRetentionMode.AGE)
                or AniListCacheRetentionMode.AGE
            ).strip().lower()
        except Exception:
            retention_mode_pref = AniListCacheRetentionMode.AGE
        if retention_mode_pref not in (AniListCacheRetentionMode.AGE, AniListCacheRetentionMode.SIZE, AniListCacheRetentionMode.ROTATE):
            retention_mode_pref = AniListCacheRetentionMode.AGE
        retention_mode_var = tk.StringVar(value=retention_mode_pref)

        def _save_anilist_retention_mode(*_args):
            selected_mode = str(retention_mode_var.get() or AniListCacheRetentionMode.AGE).strip().lower()
            if selected_mode not in (AniListCacheRetentionMode.AGE, AniListCacheRetentionMode.SIZE, AniListCacheRetentionMode.ROTATE):
                selected_mode = AniListCacheRetentionMode.AGE
                retention_mode_var.set(selected_mode)
            config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, selected_mode)

        mode_row = ttk.Frame(ttl_frame)
        mode_row.pack(fill='x', pady=(0, 8))
        ttk.Label(mode_row, text='Retention mode:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=retention_mode_var,
            values=[AniListCacheRetentionMode.AGE, AniListCacheRetentionMode.SIZE, AniListCacheRetentionMode.ROTATE],
            state='readonly',
            width=12,
        )
        mode_combo.pack(side='left')
        mode_combo.bind('<<ComboboxSelected>>', _save_anilist_retention_mode)

        try:
            ttl_pref = int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, 30))
        except Exception:
            ttl_pref = 30
        ttl_var = tk.IntVar(value=max(0, min(3650, ttl_pref)))

        def _save_anilist_ttl(*_args):
            try:
                v = int(ttl_var.get())
            except Exception:
                v = 30
            v = max(0, min(3650, v))
            if v != ttl_var.get():
                ttl_var.set(v)
            config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, v)

        try:
            max_mb_pref = int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, 10))
        except Exception:
            max_mb_pref = 10
        max_mb_var = tk.IntVar(value=max(1, min(1024, max_mb_pref)))

        def _save_anilist_max_mb(*_args):
            try:
                v = int(max_mb_var.get())
            except Exception:
                v = 10
            v = max(1, min(1024, v))
            if v != max_mb_var.get():
                max_mb_var.set(v)
            config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, v)

        ttl_row = ttk.Frame(ttl_frame)
        ttl_row.pack(fill='x')
        ttk.Label(ttl_row, text='Retain cached aliases for:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        ttl_spin = ttk.Spinbox(ttl_row, from_=0, to=3650, textvariable=ttl_var, width=8, command=_save_anilist_ttl)
        ttl_spin.pack(side='left')
        ttl_spin.bind('<FocusOut>', _save_anilist_ttl)
        ttl_spin.bind('<Return>', _save_anilist_ttl)
        ttk.Label(ttl_row, text='days (used in age mode; 0 = keep forever)', font=('Segoe UI', 9)).pack(side='left', padx=(8, 0))

        size_row = ttk.Frame(ttl_frame)
        size_row.pack(fill='x', pady=(6, 0))
        ttk.Label(size_row, text='Max cache size:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        size_spin = ttk.Spinbox(size_row, from_=1, to=1024, textvariable=max_mb_var, width=8, command=_save_anilist_max_mb)
        size_spin.pack(side='left')
        size_spin.bind('<FocusOut>', _save_anilist_max_mb)
        size_spin.bind('<Return>', _save_anilist_max_mb)
        ttk.Label(size_row, text='MB (used in size mode)', font=('Segoe UI', 9)).pack(side='left', padx=(8, 0))

        ttk.Label(
            ttl_frame,
            text='Rotate mode archives the current AniList cache to a dated file before saving a fresh snapshot.',
            font=('Segoe UI', 8),
            foreground='#666',
        ).pack(anchor='w', pady=(6, 0))

        # AniList title variation language filters
        lang_frame = ttk.LabelFrame(tab_api_rate, text='🌐 AniList Variation Languages', padding=10)
        lang_frame.pack(fill='x', pady=(0, 10), padx=10)
        ttk.Label(
            lang_frame,
            text='Choose which AniList language fields are shown in Title Variations.',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 8))

        default_langs = ['romaji', 'english', 'native', 'synonym', 'synonym_other']
        try:
            stored_langs = config.get_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, default_langs)
            if not isinstance(stored_langs, list):
                stored_langs = list(default_langs)
        except Exception:
            stored_langs = list(default_langs)

        lang_vars: Dict[str, tk.BooleanVar] = {
            'romaji': tk.BooleanVar(value='romaji' in stored_langs),
            'english': tk.BooleanVar(value='english' in stored_langs),
            'native': tk.BooleanVar(value='native' in stored_langs),
            'synonym': tk.BooleanVar(value='synonym' in stored_langs),
            'synonym_other': tk.BooleanVar(value='synonym_other' in stored_langs),
        }

        def _save_anilist_langs(*_args):
            selected = [k for k, v in lang_vars.items() if bool(v.get())]
            if not selected:
                # Keep at least one language active to avoid empty variation UI.
                selected = ['romaji']
                lang_vars['romaji'].set(True)
            config.set_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, selected)

        lang_checks_row = ttk.Frame(lang_frame)
        lang_checks_row.pack(fill='x', pady=(0, 4))
        ttk.Checkbutton(lang_checks_row, text='Romaji', variable=lang_vars['romaji'], command=_save_anilist_langs).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(lang_checks_row, text='English', variable=lang_vars['english'], command=_save_anilist_langs).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(lang_checks_row, text='Native', variable=lang_vars['native'], command=_save_anilist_langs).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(lang_checks_row, text='Synonyms', variable=lang_vars['synonym'], command=_save_anilist_langs).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(lang_checks_row, text='Other-Lang Synonyms', variable=lang_vars['synonym_other'], command=_save_anilist_langs).pack(side='left', padx=(0, 0))

        ttk.Label(
            lang_frame,
            text='Changes apply immediately to the Rule Editor Title Variations section.',
            font=('Segoe UI', 8),
            foreground='#666',
        ).pack(anchor='w')

        scope_frame = ttk.LabelFrame(tab_api_rate, text='🧠 AniList Refresh Scope', padding=10)
        scope_frame.pack(fill='x', pady=(0, 10), padx=10)
        ttk.Label(
            scope_frame,
            text='Choose whether manual AniList refresh stays on the current title or expands to the selected season/year.',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 8))

        try:
            scope_pref = str(config.get_pref(PrefKeys.ANILIST_REFRESH_SCOPE, AniListRefreshScope.TITLE_ONLY) or AniListRefreshScope.TITLE_ONLY).strip().lower()
        except Exception:
            scope_pref = AniListRefreshScope.TITLE_ONLY
        if scope_pref not in (AniListRefreshScope.TITLE_ONLY, AniListRefreshScope.TITLE_AND_SEASON):
            scope_pref = AniListRefreshScope.TITLE_ONLY
        scope_var = tk.StringVar(value=scope_pref)

        def _save_anilist_scope(*_args):
            selected_scope = str(scope_var.get() or AniListRefreshScope.TITLE_ONLY).strip().lower()
            if selected_scope not in (AniListRefreshScope.TITLE_ONLY, AniListRefreshScope.TITLE_AND_SEASON):
                selected_scope = AniListRefreshScope.TITLE_ONLY
                scope_var.set(selected_scope)
            config.set_pref(PrefKeys.ANILIST_REFRESH_SCOPE, selected_scope)

        ttk.Radiobutton(
            scope_frame,
            text='Current title only',
            variable=scope_var,
            value=AniListRefreshScope.TITLE_ONLY,
            command=_save_anilist_scope,
        ).pack(anchor='w', pady=(0, 4))
        ttk.Radiobutton(
            scope_frame,
            text='Current title plus selected season/year',
            variable=scope_var,
            value=AniListRefreshScope.TITLE_AND_SEASON,
            command=_save_anilist_scope,
        ).pack(anchor='w', pady=(0, 4))
        ttk.Label(
            scope_frame,
            text='The season/year selectors at the top of the app are used when the expanded mode is active.',
            font=('Segoe UI', 8),
            foreground='#666',
        ).pack(anchor='w', pady=(2, 0))
    except Exception as e:
        logger.error('Failed to build top-level API Rate Limits tab: %s', e, exc_info=True)

    mode_frame = ttk.LabelFrame(tab_connection, text="🔌 Connection Mode", padding=12)
    mode_frame.pack(fill='x', pady=(0, 10), padx=10)
    
    ttk.Label(mode_frame, text="Select how the application should run sync operations:", 
              font=('Segoe UI', 9)).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
    ttk.Radiobutton(mode_frame, text="🌐 Online - Direct API connection", 
                    variable=mode_temp, value='online').grid(row=1, column=0, sticky='w', padx=5, pady=3)
    ttk.Radiobutton(mode_frame, text="📁 Offline - Generate JSON file only", 
                    variable=mode_temp, value='offline').grid(row=1, column=1, sticky='w', padx=5, pady=3)

    server_frame = ttk.LabelFrame(tab_connection, text="🧭 Server Platform", padding=12)
    server_frame.pack(fill='x', pady=(0, 10), padx=10)
    ttk.Label(server_frame, text="Main torrent/automation server:",
              font=('Segoe UI', 9)).grid(row=0, column=0, sticky='w', pady=(0, 8))

    server_display = {
        'qbittorrent': 'qBittorrent',
        'autobrr': 'Autobrr',
    }
    server_combo = ttk.Combobox(
        server_frame,
        textvariable=main_server_temp,
        values=list(server_display.keys()),
        state='readonly',
        width=20,
    )
    server_combo.grid(row=0, column=1, sticky='w', padx=(8, 0), pady=(0, 8))
    server_hint_var = tk.StringVar(
        value=f"Primary model: {get_server_display_name(main_server_temp.get())}. "
              "This preference is stored in config.ini and used as the default integration target."
    )
    ttk.Label(server_frame, textvariable=server_hint_var,
              font=('Segoe UI', 8), foreground='#666').grid(row=1, column=0, columnspan=2, sticky='w')

    def _update_server_hint(*_args):
        server_hint_var.set(
            f"Primary model: {get_server_display_name(main_server_temp.get())}. "
            "This preference is stored in config.ini and used as the default integration target."
        )

    main_server_temp.trace_add('write', _update_server_hint)

    qbt_frame = ttk.LabelFrame(tab_connection, text="🔧 Unified Connection Profile Editor", padding=15)
    qbt_frame.pack(fill='x', pady=(0, 10), padx=10)

    profile_server_options = ['qbittorrent']
    profile_name_var = tk.StringVar(value='')
    profile_server_type_var = tk.StringVar(value=str(main_server_temp.get() or 'qbittorrent'))

    def _normalize_server_type(value: str) -> str:
        normalized = str(value or 'qbittorrent').strip().lower()
        if normalized in profile_server_options:
            return normalized
        return 'qbittorrent'

    conn_protocol_temp = tk.StringVar(value=qbt_protocol_temp.get() or 'http')
    conn_host_temp = tk.StringVar(value=qbt_host_temp.get() or 'localhost')
    conn_port_temp = tk.StringVar(value=qbt_port_temp.get() or '8080')
    conn_user_temp = tk.StringVar(value=qbt_user_temp.get() or '')
    conn_pass_temp = tk.StringVar(value=qbt_pass_temp.get() or '')
    conn_verify_ssl_temp = tk.BooleanVar(value=bool(verify_ssl_temp.get()))
    conn_ca_cert_temp = tk.StringVar(value=ca_cert_temp.get() or '')

    def _load_profiles_cache() -> list:
        try:
            profiles = config.load_connection_profiles()
            if isinstance(profiles, list):
                filtered = []
                for p in profiles:
                    if not isinstance(p, dict):
                        continue
                    server_key = _normalize_server_type(p.get('server', 'qbittorrent'))
                    if server_key in profile_server_options:
                        p_copy = dict(p)
                        p_copy['server'] = server_key
                        filtered.append(p_copy)
                return filtered
        except Exception:
            pass
        return []

    def _save_profiles_cache(profiles: list) -> None:
        try:
            config.save_connection_profiles(profiles)
        except Exception as e:
            logger.error(f"Failed saving connection profiles: {e}")

    profiles_listbox = tk.Listbox(
        qbt_frame,
        height=5,
        font=('Segoe UI', 9),
        bg=listbox_bg,
        fg=listbox_fg,
        selectbackground=listbox_select_bg,
        selectforeground=listbox_select_fg,
        highlightthickness=0,
        bd=0,
        relief='flat',
    )

    profile_index_map = []

    def _profile_label(profile: dict) -> str:
        p_name = str(profile.get('name', '') or '').strip() or 'Unnamed'
        p_server = _normalize_server_type(profile.get('server', 'qbittorrent'))
        return f"{p_name} - {get_server_display_name(p_server)}"

    def _refresh_profiles_listbox() -> None:
        nonlocal profile_index_map
        profiles = _load_profiles_cache()
        profiles_listbox.delete(0, 'end')
        profile_index_map = []
        for idx, profile in enumerate(profiles):
            profiles_listbox.insert('end', _profile_label(profile))
            profile_index_map.append(idx)

    def _load_editor_from_profile(profile: dict) -> None:
        profile_name_var.set(str(profile.get('name', '') or ''))
        p_server = _normalize_server_type(profile.get('server', 'qbittorrent'))
        profile_server_type_var.set(p_server)
        conn_protocol_temp.set(str(profile.get('protocol', 'http') or 'http'))
        conn_host_temp.set(str(profile.get('host', 'localhost') or 'localhost'))
        conn_port_temp.set(str(profile.get('port', '8080') or '8080'))
        conn_user_temp.set(str(profile.get('username', '') or ''))
        conn_pass_temp.set(str(profile.get('password', '') or ''))
        conn_verify_ssl_temp.set(bool(profile.get('verify_ssl', True)))
        conn_ca_cert_temp.set(str(profile.get('ca_cert', '') or ''))

    def _apply_editor_to_runtime_vars() -> None:
        active_server = _normalize_server_type(profile_server_type_var.get())
        main_server_temp.set(active_server)
        protocol_val = conn_protocol_temp.get().strip() or 'http'
        host_val = conn_host_temp.get().strip() or 'localhost'
        port_val = conn_port_temp.get().strip() or '8080'
        user_val = conn_user_temp.get().strip()
        pass_val = conn_pass_temp.get()
        verify_val = bool(conn_verify_ssl_temp.get())
        ca_cert_val = conn_ca_cert_temp.get().strip()

        qbt_protocol_temp.set(protocol_val)
        qbt_host_temp.set(host_val)
        qbt_port_temp.set(port_val)
        qbt_user_temp.set(user_val)
        qbt_pass_temp.set(pass_val)
        verify_ssl_temp.set(verify_val)
        ca_cert_temp.set(ca_cert_val)

    def _new_profile() -> None:
        profile_name_var.set('')
        conn_protocol_temp.set('http')
        conn_host_temp.set('localhost')
        conn_port_temp.set('8080')
        conn_user_temp.set('')
        conn_pass_temp.set('')
        conn_verify_ssl_temp.set(True)
        conn_ca_cert_temp.set('')

    def _save_current_profile() -> None:
        p_name = profile_name_var.get().strip()
        if not p_name:
            messagebox.showwarning('Profile Name Required', 'Please enter a profile name before saving.')
            return
        new_profile = {
            'name': p_name,
            'server': _normalize_server_type(profile_server_type_var.get()),
            'protocol': conn_protocol_temp.get().strip() or 'http',
            'host': conn_host_temp.get().strip() or 'localhost',
            'port': conn_port_temp.get().strip() or '8080',
            'username': conn_user_temp.get().strip(),
            'password': conn_pass_temp.get(),
            'verify_ssl': bool(conn_verify_ssl_temp.get()),
            'ca_cert': conn_ca_cert_temp.get().strip(),
        }
        profiles = _load_profiles_cache()
        replaced = False
        for idx, profile in enumerate(profiles):
            if str(profile.get('name', '')).strip().lower() == p_name.lower():
                profiles[idx] = new_profile
                replaced = True
                break
        if not replaced:
            profiles.append(new_profile)
        _save_profiles_cache(profiles)
        _refresh_profiles_listbox()
        _apply_editor_to_runtime_vars()
        messagebox.showinfo('Profile Saved', f"Saved profile: {p_name}")

    def _load_selected_profile() -> None:
        selection = profiles_listbox.curselection()
        if not selection:
            return
        profiles = _load_profiles_cache()
        idx = selection[0]
        if idx < 0 or idx >= len(profile_index_map):
            return
        profile_idx = profile_index_map[idx]
        if profile_idx < 0 or profile_idx >= len(profiles):
            return
        _load_editor_from_profile(profiles[profile_idx])
        _apply_editor_to_runtime_vars()

    def _delete_selected_profile() -> None:
        selection = profiles_listbox.curselection()
        if not selection:
            return
        profiles = _load_profiles_cache()
        idx = selection[0]
        if idx < 0 or idx >= len(profile_index_map):
            return
        profile_idx = profile_index_map[idx]
        if profile_idx < 0 or profile_idx >= len(profiles):
            return
        profile_name = str(profiles[profile_idx].get('name', 'Unnamed'))
        if not messagebox.askyesno('Delete Profile', f"Delete connection profile '{profile_name}'?"):
            return
        del profiles[profile_idx]
        _save_profiles_cache(profiles)
        _refresh_profiles_listbox()
    
    ttk.Label(qbt_frame, text="Profile Name:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky='w', padx=5, pady=8)
    ttk.Entry(qbt_frame, textvariable=profile_name_var, width=24).grid(row=0, column=1, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Server Type:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=2, sticky='w', padx=(20, 5), pady=8)
    ttk.Combobox(
        qbt_frame,
        textvariable=profile_server_type_var,
        values=profile_server_options,
        state='readonly',
        width=20,
    ).grid(row=0, column=3, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Protocol:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, sticky='w', padx=5, pady=8)
    protocol_dropdown = ttk.Combobox(qbt_frame, textvariable=conn_protocol_temp, values=['http', 'https'], state='readonly', width=10)
    protocol_dropdown.grid(row=1, column=1, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Host:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=2, sticky='w', padx=(20, 5), pady=8)
    ttk.Entry(qbt_frame, textvariable=conn_host_temp, width=20).grid(row=1, column=3, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Port:", font=('Segoe UI', 9, 'bold')).grid(row=2, column=0, sticky='w', padx=5, pady=8)
    ttk.Entry(qbt_frame, textvariable=conn_port_temp, width=10).grid(row=2, column=1, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Username:", font=('Segoe UI', 9, 'bold')).grid(row=2, column=2, sticky='w', padx=(20, 5), pady=8)
    ttk.Entry(qbt_frame, textvariable=conn_user_temp, width=20).grid(row=2, column=3, sticky='w', padx=5, pady=8)

    ttk.Label(qbt_frame, text="Password:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, sticky='w', padx=5, pady=8)
    ttk.Entry(qbt_frame, textvariable=conn_pass_temp, show='●', width=20).grid(row=3, column=1, columnspan=3, sticky='w', padx=5, pady=8)

    ttk.Checkbutton(qbt_frame, text="🔒 Verify SSL Certificate (uncheck for self-signed)",
                    variable=conn_verify_ssl_temp).grid(row=4, column=0, columnspan=4, sticky='w', padx=5, pady=10)

    ttk.Label(qbt_frame, text="CA Certificate (optional):", font=('Segoe UI', 9, 'bold')).grid(row=5, column=0, columnspan=4, sticky='w', padx=5, pady=(10, 5))
    
    def browse_ca():
        """
        Opens file dialog to browse for CA certificate file.
        """
        path = filedialog.askopenfilename(title='Select CA certificate (PEM)', filetypes=[('PEM files','*.pem;*.crt;*.cer'), ('All files','*.*')])
        if path:
            conn_ca_cert_temp.set(path)
    
    ca_entry = ttk.Entry(qbt_frame, textvariable=conn_ca_cert_temp, width=50)
    ca_entry.grid(row=6, column=0, columnspan=3, sticky='ew', padx=5, pady=5)
    ttk.Button(qbt_frame, text='📁 Browse...', command=browse_ca).grid(row=6, column=3, sticky='w', padx=5, pady=5)
    
    qbt_frame.grid_columnconfigure(3, weight=1)
    
    # Status and test section - use grid for better control
    test_btn_frame = ttk.Frame(qbt_frame)
    test_btn_frame.grid(row=7, column=0, columnspan=4, sticky='ew', padx=5, pady=(15, 5))

    ttk.Button(test_btn_frame, text='💾 Save Profile', command=_save_current_profile).pack(side='left', padx=5)
    ttk.Button(test_btn_frame, text='📥 Load Selected', command=_load_selected_profile).pack(side='left', padx=5)
    ttk.Button(test_btn_frame, text='➕ New', command=_new_profile).pack(side='left', padx=5)
    ttk.Button(test_btn_frame, text='🗑️ Delete Selected', command=_delete_selected_profile).pack(side='left', padx=5)
    
    test_btn = ttk.Button(test_btn_frame, text="🔍 Test Connection", style='Accent.TButton')
    test_btn.pack(side='left', padx=5)
    
    # Status label with wrapping - separate row for full width
    status_frame = ttk.Frame(qbt_frame)
    status_frame.grid(row=8, column=0, columnspan=4, sticky='ew', padx=5, pady=(5, 5))
    
    settings_conn_status = tk.StringVar(value='⚪ Not tested')
    status_label = tk.Label(status_frame, textvariable=settings_conn_status, 
                           font=('Segoe UI', 9), anchor='w', justify='left',
                           wraplength=max(420, optimal_width - 80), bg='#f5f5f5')
    status_label.pack(side='left', fill='both', expand=True, padx=5)

    def _update_status_wrap(event=None):
        try:
            status_label.configure(wraplength=max(320, status_frame.winfo_width() - 20))
        except Exception:
            pass

    status_frame.bind('<Configure>', _update_status_wrap)
    
    ttk.Label(qbt_frame, text="Saved Profiles:", font=('Segoe UI', 9, 'bold')).grid(row=9, column=0, sticky='nw', padx=5, pady=(5, 0))
    profiles_listbox.grid(row=9, column=1, columnspan=3, sticky='ew', padx=5, pady=(5, 0))

    ttk.Label(qbt_frame, text="💡 RSS rule profiles are limited to qBittorrent. Non-RSS profile types were removed.",
              font=('Segoe UI', 8), foreground='#666').grid(row=10, column=0, columnspan=4, sticky='w', padx=5, pady=(5, 0))

    _refresh_profiles_listbox()

    def _on_profile_server_type_changed(*_args):
        active_server = _normalize_server_type(profile_server_type_var.get())
        main_server_temp.set(active_server)

    profile_server_type_var.trace_add('write', _on_profile_server_type_changed)

    qbt_frame.grid_columnconfigure(3, weight=1)

    # Default Rule Settings Frame
    defaults_frame = ttk.LabelFrame(tab_defaults, text="📝 Default Rule Settings", padding=15)
    defaults_frame.pack(fill='x', pady=(0, 10), padx=10)
    
    ttk.Label(defaults_frame, text="These defaults will be used when creating new rules:", 
              font=('Segoe UI', 9)).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 10))

    ttk.Label(defaults_frame, text="Default Category:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, sticky='w', padx=5, pady=8)
    default_category_combo = ttk.Combobox(defaults_frame, textvariable=default_category_temp, width=48)
    default_category_combo.grid(row=1, column=1, columnspan=3, sticky='ew', padx=5, pady=8)
    ttk.Label(defaults_frame, text="💡 Select a category from the list below or type one manually.",
              font=('Segoe UI', 8), foreground='#666').grid(row=2, column=0, columnspan=4, sticky='w', padx=5, pady=(0, 8))
    
    # Categories and Save Paths (list view)
    ttk.Label(defaults_frame, text="📂 Categories & Save Paths:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, sticky='w', padx=5, pady=8)
    
    # Create frame for treeview and scrollbar
    cat_list_frame = ttk.Frame(defaults_frame)
    cat_list_frame.grid(row=3, column=1, columnspan=3, sticky='nsew', padx=5, pady=8)
    
    # Treeview showing all categories and their save paths
    cat_tree = ttk.Treeview(cat_list_frame, columns=('category', 'save_path'), height=6, show='headings')
    cat_tree.heading('category', text='Category')
    cat_tree.heading('save_path', text='Save Path')
    cat_tree.column('category', width=120)
    cat_tree.column('save_path', width=280)
    
    cat_scroll = ttk.Scrollbar(cat_list_frame, orient='vertical', command=cat_tree.yview)
    cat_tree.configure(yscrollcommand=cat_scroll.set)
    
    cat_tree.pack(side='left', fill='both', expand=True)
    cat_scroll.pack(side='right', fill='y')
    
    # Load categories into treeview
    def _load_categories_list():
        try:
            config.load_cached_categories()
            cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
            cat_tree.delete(*cat_tree.get_children())
            
            if isinstance(cats, dict):
                default_category_combo['values'] = sorted(cats.keys())
                for cat_name in sorted(cats.keys()):
                    cat_data = cats[cat_name]
                    save_path = get_category_save_path(cat_data)
                    cat_tree.insert('', 'end', values=(cat_name, save_path))
        except Exception as e:
            logger.error(f"Error loading categories list: {e}")
    
    _load_categories_list()
    
    # When clicking a category, select it and set it as default
    def _on_cat_select(event):
        try:
            selection = cat_tree.selection()
            if selection:
                item = selection[0]
                values = cat_tree.item(item, 'values')
                if values:
                    default_category_temp.set(values[0])
        except Exception as e:
            logger.error(f"Error selecting category: {e}")
    
    cat_tree.bind('<<TreeviewSelect>>', _on_cat_select)
    
    # Let row expand
    defaults_frame.grid_rowconfigure(3, weight=1)
    
    
    # Default Download Path from qBittorrent
    default_download_path_temp = tk.StringVar(value=getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or "")
    
    ttk.Label(defaults_frame, text="qBittorrent Download Path (profile):", font=('Segoe UI', 9, 'bold')).grid(row=4, column=0, sticky='w', padx=5, pady=8)
    default_download_path_entry = ttk.Entry(defaults_frame, textvariable=default_download_path_temp, width=50, state='readonly')
    default_download_path_entry.grid(row=4, column=1, columnspan=3, sticky='ew', padx=5, pady=8)
    ttk.Label(defaults_frame, text="💡 Auto-fetched from qBittorrent profile on tab access. Used as base path for auto-generated save paths (Season/Title structure)",
              font=('Segoe UI', 8), foreground='#666').grid(row=5, column=0, columnspan=4, sticky='w', padx=5, pady=(0, 8))
    
    def fetch_download_path(silent=False):
        """Fetch default download path from qBittorrent (silent by default)."""
        try:
            # Use current settings to connect
            from src.api.qbittorrent import QBittorrentClient
            api = QBittorrentClient(
                protocol=qbt_protocol_temp.get(),
                host=qbt_host_temp.get(),
                port=qbt_port_temp.get(),
                username=qbt_user_temp.get(),
                password=qbt_pass_temp.get(),
                verify_ssl=verify_ssl_temp.get(),
                ca_cert=ca_cert_temp.get().strip() or None
            )
            
            if api.connect():
                prefs = api.get_preferences()
                save_path = prefs.get('save_path', '')
                if save_path:
                    default_download_path_temp.set(save_path)
                    if not silent:
                        messagebox.showinfo('Success', f'Fetched default download path:\n{save_path}')
                api.close()
        except Exception as e:
            if not silent:
                logger.error(f"Failed to auto-fetch download path: {e}")

    # Delete behavior preference
    try:
        pref_confirm_delete = config.get_pref('confirm_delete', False)
    except Exception:
        pref_confirm_delete = False
    confirm_delete_var = tk.BooleanVar(value=bool(pref_confirm_delete))

    ttk.Checkbutton(
        defaults_frame,
        text='Ask for confirmation before deleting titles',
        variable=confirm_delete_var,
        command=lambda: config.set_pref('confirm_delete', bool(confirm_delete_var.get())),
    ).grid(row=6, column=0, columnspan=4, sticky='w', padx=5, pady=(4, 8))
    
    # Default Affected Feeds - with listbox for cached feeds
    ttk.Label(defaults_frame, text="Default Affected Feeds:", font=('Segoe UI', 9, 'bold')).grid(row=7, column=0, sticky='nw', padx=5, pady=8)
    
    # Create frame for feeds listbox and buttons
    feeds_container = ttk.Frame(defaults_frame)
    feeds_container.grid(row=7, column=1, columnspan=3, sticky='ew', padx=5, pady=8)
    
    # Manual entry field
    manual_feed_entry_frame = ttk.Frame(feeds_container)
    manual_feed_entry_frame.pack(fill='x', pady=(0, 5))
    
    ttk.Label(manual_feed_entry_frame, text="Manual Entry:", font=('Segoe UI', 8)).pack(side='left', padx=(0, 5))
    default_feeds_entry = ttk.Entry(manual_feed_entry_frame, textvariable=default_affected_feeds_temp, width=45)
    default_feeds_entry.pack(side='left', fill='x', expand=True)
    
    # Listbox for cached feeds
    feeds_list_frame = ttk.LabelFrame(feeds_container, text="Cached Feeds (click to add)", padding=5)
    feeds_list_frame.pack(fill='both', expand=True)
    
    # Create inner frame for listbox and scrollbar
    feeds_inner_frame = ttk.Frame(feeds_list_frame)
    feeds_inner_frame.pack(fill='both', expand=True)
    
    feeds_listbox = tk.Listbox(feeds_inner_frame, height=4, font=('Segoe UI', 9),
                               bg=listbox_bg, fg=listbox_fg,
                               selectbackground=listbox_select_bg, selectforeground=listbox_select_fg,
                               highlightthickness=0, bd=0, relief='flat')
    feeds_listbox.pack(side='left', fill='both', expand=True)
    
    feeds_scroll = ttk.Scrollbar(feeds_inner_frame, orient='vertical', command=feeds_listbox.yview)
    feeds_scroll.pack(side='right', fill='y')
    feeds_listbox.configure(yscrollcommand=feeds_scroll.set)
    
    # Prevent feeds listbox scroll from affecting main canvas
    def _on_feeds_mousewheel(event):
        try:
            feeds_listbox.yview_scroll(int(-1*(event.delta/120)), "units")
            return "break"
        except Exception:
            pass
    
    feeds_listbox.bind("<MouseWheel>", _on_feeds_mousewheel)
    
    # Load cached feeds into listbox
    def _load_cached_feeds_into_listbox():
        """Load cached RSS feeds from config and populate listbox."""
        try:
            config.load_cached_feeds()
            feeds = getattr(config, 'CACHED_FEEDS', {}) or {}
            feeds_listbox.delete(0, 'end')
            
            # Extract feed URLs from the feeds structure
            feed_urls = set()  # Use set to automatically handle duplicates
            
            def extract_urls(obj):
                """Recursively extract URLs from nested feed structure."""
                if isinstance(obj, dict):
                    # Check for 'url' key
                    if 'url' in obj and obj['url'] and isinstance(obj['url'], str):
                        feed_urls.add(obj['url'].strip())
                    # Recurse into all values
                    for value in obj.values():
                        extract_urls(value)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_urls(item)
            
            extract_urls(feeds)
            
            # Add sorted URLs to listbox
            for url in sorted(feed_urls):
                feeds_listbox.insert('end', url)
                
            logger.debug(f"Loaded {len(feed_urls)} cached feed(s) into listbox")
        except Exception as e:
            logger.error(f"Error loading cached feeds into listbox: {e}")
    
    def _on_feed_select(event):
        """Add selected feed from listbox to manual entry field."""
        try:
            selection = feeds_listbox.curselection()
            if not selection:
                return
                
            selected_url = feeds_listbox.get(selection[0]).strip()
            current = default_affected_feeds_temp.get().strip()
            
            # Parse current feeds
            current_feeds = [f.strip() for f in current.split(',') if f.strip()] if current else []
            
            # Add if not already present
            if selected_url not in current_feeds:
                current_feeds.append(selected_url)
                default_affected_feeds_temp.set(', '.join(current_feeds))
                logger.debug(f"Added feed to defaults: {selected_url}")
        except Exception as e:
            logger.error(f"Error adding selected feed: {e}")
    
    feeds_listbox.bind('<<ListboxSelect>>', _on_feed_select)
    
    # Refresh button for feeds
    refresh_feeds_btn = ttk.Button(feeds_list_frame, text='🔄 Refresh', command=_load_cached_feeds_into_listbox)
    refresh_feeds_btn.pack(pady=(5, 0))
    
    # Initial load of cached feeds
    _load_cached_feeds_into_listbox()
    
    ttk.Label(defaults_frame, text="💡 Click feeds from cache to add them, or manually enter comma-separated URLs.",
              font=('Segoe UI', 8), foreground=subtle_fg).grid(row=8, column=0, columnspan=4, sticky='w', padx=5, pady=(5, 0))
    
    defaults_frame.grid_columnconfigure(1, weight=1)

    # Auto-fetch and refresh Defaults tab data when accessed
    def _on_defaults_tab_select():
        try:
            if settings_notebook.index(settings_notebook.select()) == 1:  # Defaults tab is at index 1
                # Auto-fetch download path silently
                fetch_download_path(silent=True)
                # Auto-load categories
                try:
                    _load_categories_list()
                except Exception:
                    pass
                # Auto-load feeds
                try:
                    _load_cached_feeds_into_listbox()
                except Exception:
                    pass
        except Exception:
            pass
    
    settings_notebook.bind('<<NotebookTabChanged>>', lambda e: _on_defaults_tab_select())
    
    # Trigger auto-fetch on initial Defaults tab access
    try:
        _on_defaults_tab_select()
    except Exception:
        pass

    def _run_test_and_update():
        """Runs connection test in background thread and updates status."""
        def _worker():
            settings_conn_status.set('⏳ Testing connection...')
            try:
                active_server = str(main_server_temp.get() or 'qbittorrent').strip().lower()
                if active_server == 'autobrr':
                    settings_conn_status.set(
                        f"ℹ️ Connection test is not yet implemented for {get_server_display_name(active_server)} profiles."
                    )
                    return
                else:
                    ca_cert = ca_cert_temp.get().strip() or None
                    ok, msg = qbt_api.ping_qbittorrent(
                        qbt_protocol_temp.get(),
                        qbt_host_temp.get(),
                        qbt_port_temp.get(),
                        qbt_user_temp.get(),
                        qbt_pass_temp.get(),
                        verify_ssl_temp.get(),
                        ca_cert
                    )
                status_icon = '✅ Connected: ' if ok else '❌ Failed: '
                settings_conn_status.set(status_icon + msg)
            except Exception as e:
                settings_conn_status.set(f'❌ Error: {e}')
        
        threading.Thread(target=_worker, daemon=True).start()

    test_btn.configure(command=_run_test_and_update)

    try:
        cat_frame = ttk.LabelFrame(tab_connection, text='📂 Cached Categories', padding=10)
        cat_frame.pack(fill='both', expand=True, pady=(0, 10), padx=10)
        
        cat_listbox = tk.Listbox(cat_frame, height=5, font=('Segoe UI', 9),
                                 bg=listbox_bg, fg=listbox_fg,
                                 selectbackground=listbox_select_bg, selectforeground=listbox_select_fg,
                                 highlightthickness=0, bd=0, relief='flat')
        cat_listbox.pack(side='left', fill='both', expand=True, padx=(0, 5), pady=5)
        cat_scroll = ttk.Scrollbar(cat_frame, orient='vertical', command=cat_listbox.yview)
        cat_scroll.pack(side='left', fill='y', pady=5)
        cat_listbox.configure(yscrollcommand=cat_scroll.set)
        
        # Prevent category listbox scroll from affecting main canvas
        def _on_cat_mousewheel(event):
            """Handle mousewheel for category listbox."""
            cat_listbox.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"  # Prevent event propagation
        
        cat_listbox.bind("<MouseWheel>", _on_cat_mousewheel)

        def _load_cached_categories_into_listbox():
            """Load categories from cache into listbox and combobox."""
            config.load_cached_categories()
            cats = config.CACHED_CATEGORIES or {}
            cat_listbox.delete(0, 'end')
            
            # Extract category names
            if isinstance(cats, dict):
                keys = list(cats.keys())
            elif isinstance(cats, list):
                keys = cats
            else:
                keys = []
            
            # Populate listbox
            for k in keys:
                cat_listbox.insert('end', str(k))

        def _clear_cached_categories():
            """Clear all cached categories after confirmation."""
            if messagebox.askyesno('Confirm', 'Clear cached categories? This cannot be undone.'):
                config.save_cached_categories({})
                _load_cached_categories_into_listbox()
                status_var.set('Cached categories cleared.')

        def _refresh_categories_from_server():
            """Refresh categories from qBittorrent server."""
            def _worker():
                settings_conn_status.set('⏳ Refreshing categories...')
                try:
                    ca_cert = ca_cert_temp.get().strip() or None
                    ok, data = qbt_api.fetch_categories(
                        qbt_protocol_temp.get(),
                        qbt_host_temp.get(),
                        qbt_port_temp.get(),
                        qbt_user_temp.get(),
                        qbt_pass_temp.get(),
                        verify_ssl_temp.get(),
                        ca_cert
                    )
                    
                    if ok:
                        config.save_cached_categories(data)
                        _load_cached_categories_into_listbox()
                        settings_conn_status.set('✅ Categories refreshed.')
                        status_var.set('Categories updated from server.')
                    else:
                        settings_conn_status.set(f'❌ Refresh failed: {data}')
                        status_var.set('Failed to refresh categories.')
                except Exception as e:
                    settings_conn_status.set(f'❌ Refresh error: {e}')
            
            threading.Thread(target=_worker, daemon=True).start()

        btns_frame = ttk.Frame(cat_frame)
        btns_frame.pack(side='left', fill='y', padx=(10, 0), pady=5)
        ttk.Button(btns_frame, text='🔄 Refresh', command=_refresh_categories_from_server, width=15).pack(fill='x', pady=(0, 5))
        ttk.Button(btns_frame, text='🗑️ Clear', command=_clear_cached_categories, width=15).pack(fill='x')
        _load_cached_categories_into_listbox()
    except Exception:
        pass

    try:
        feeds_frame = ttk.LabelFrame(tab_connection, text='📡 Cached RSS Feeds', padding=10)
        feeds_frame.pack(fill='both', expand=True, pady=(0, 10), padx=10)
        
        feeds_listbox = tk.Listbox(feeds_frame, height=5, font=('Segoe UI', 9),
                                   bg=listbox_bg, fg=listbox_fg,
                                   selectbackground=listbox_select_bg, selectforeground=listbox_select_fg,
                                   highlightthickness=0, bd=0, relief='flat')
        feeds_listbox.pack(side='left', fill='both', expand=True, padx=(0, 5), pady=5)
        feeds_scroll = ttk.Scrollbar(feeds_frame, orient='vertical', command=feeds_listbox.yview)
        feeds_scroll.pack(side='left', fill='y', pady=5)
        feeds_listbox.configure(yscrollcommand=feeds_scroll.set)
        
        # Prevent feeds listbox scroll from affecting main canvas
        def _on_feeds_mousewheel(event):
            try:
                feeds_listbox.yview_scroll(int(-1*(event.delta/120)), "units")
                return "break"  # Prevent event propagation
            except Exception:
                pass
        
        feeds_listbox.bind("<MouseWheel>", _on_feeds_mousewheel)

        def _load_cached_feeds_into_listbox():
            try:
                config.load_cached_feeds()
                f = getattr(config, 'CACHED_FEEDS', {}) or {}
                feeds_listbox.delete(0, 'end')
                if isinstance(f, dict):
                    if not f:
                        feeds_listbox.insert('end', '(No cached feeds - click Refresh to load)')
                    else:
                        for k, v in f.items():
                            if isinstance(v, dict) and v.get('url'):
                                feeds_listbox.insert('end', f"{k} -> {v.get('url')}")
                            else:
                                feeds_listbox.insert('end', str(k))
                elif isinstance(f, list):
                    if not f:
                        feeds_listbox.insert('end', '(No cached feeds - click Refresh to load)')
                    else:
                        for item in f:
                            if isinstance(item, dict) and item.get('url'):
                                feeds_listbox.insert('end', item.get('url'))
                            else:
                                feeds_listbox.insert('end', str(item))
                else:
                    feeds_listbox.insert('end', '(No cached feeds - click Refresh to load)')
            except Exception as e:
                feeds_listbox.delete(0, 'end')
                feeds_listbox.insert('end', f'(Error loading feeds: {e})')

        def _clear_cached_feeds():
            try:
                if not messagebox.askyesno('Confirm', 'Clear cached feeds? This cannot be undone.'):
                    return
                config.save_cached_feeds({})
                _load_cached_feeds_into_listbox()
                status_var.set('Cached feeds cleared.')
            except Exception:
                status_var.set('Failed to clear cached feeds.')

        def _refresh_feeds_from_server():
            def _worker():
                try:
                    settings_conn_status.set('Refreshing feeds...')
                    ok, data = qbt_api.fetch_feeds(qbt_protocol_temp.get(), qbt_host_temp.get(), qbt_port_temp.get(), qbt_user_temp.get(), qbt_pass_temp.get(), bool(verify_ssl_temp.get()), ca_cert_temp.get() if ca_cert_temp.get().strip() else None)
                    if ok:
                        try:
                            config.save_cached_feeds(data)
                        except Exception:
                            pass
                        settings_conn_status.set('Feeds refreshed.')
                        status_var.set('Feeds updated from server.')
                        _load_cached_feeds_into_listbox()
                    else:
                        settings_conn_status.set('Refresh failed: ' + str(data))
                        status_var.set('Failed to refresh feeds.')
                except Exception as e:
                    settings_conn_status.set('Refresh error: ' + str(e))
            try:
                threading.Thread(target=_worker, daemon=True).start()
            except Exception:
                settings_conn_status.set('Failed to start refresh thread')

        fbtns_frame = ttk.Frame(feeds_frame)
        fbtns_frame.pack(side='left', fill='y', padx=(10, 0), pady=5)
        ttk.Button(fbtns_frame, text='🔄 Refresh', command=_refresh_feeds_from_server, width=15).pack(fill='x', pady=(0, 5))
        ttk.Button(fbtns_frame, text='🗑️ Clear', command=_clear_cached_feeds, width=15).pack(fill='x')
        _load_cached_feeds_into_listbox()
    except Exception:
        pass

    # Import/Export Settings
    try:
        import_frame = ttk.LabelFrame(tab_import, text='📥 Import/Export Settings', padding=10)
        import_frame.pack(fill='x', pady=(0, 10), padx=10)
        
        try:
            pref_prefix = config.get_pref('prefix_imports', True)
        except Exception:
            pref_prefix = True
        prefix_imports_setting_var = tk.BooleanVar(value=bool(pref_prefix))
        
        ttk.Checkbutton(import_frame, text='✓ Enable Season/Year prefix logic (imports + generated save paths)', 
                       variable=prefix_imports_setting_var,
                       command=lambda: config.set_pref('prefix_imports', bool(prefix_imports_setting_var.get()))).pack(anchor='w', pady=5)
        
        try:
            pref_auto_sanitize = config.get_pref('auto_sanitize_imports', True)
        except Exception:
            pref_auto_sanitize = True
        auto_sanitize_var = tk.BooleanVar(value=bool(pref_auto_sanitize))
        
        ttk.Checkbutton(import_frame, text='✓ Automatically sanitize titles with invalid folder names',
                       variable=auto_sanitize_var,
                       command=lambda: config.set_pref('auto_sanitize_imports', bool(auto_sanitize_var.get()))).pack(anchor='w', pady=5)

        try:
            pref_show_check = config.get_pref('show_import_sanitize_check', True)
        except Exception:
            pref_show_check = True
        show_import_check_var = tk.BooleanVar(value=bool(pref_show_check))

        ttk.Checkbutton(import_frame, text='✓ Show pre-import sanitize check (JSON/CSV/Clipboard)',
                       variable=show_import_check_var,
                       command=lambda: config.set_pref('show_import_sanitize_check', bool(show_import_check_var.get()))).pack(anchor='w', pady=5)

        target_frame = ttk.LabelFrame(tab_import, text='🎯 Export Targets', padding=10)
        target_frame.pack(fill='x', pady=(0, 10), padx=10)
        ttk.Label(target_frame, text='Choose default export targets for multi-target export:',
              font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        ttk.Checkbutton(target_frame, text='qBittorrent', variable=export_target_vars['qbittorrent']).pack(anchor='w', pady=2)
        ttk.Checkbutton(target_frame, text='Autobrr', variable=export_target_vars['autobrr']).pack(anchor='w', pady=2)

        ttk.Label(target_frame, text='At least one target is required. If none are selected, qBittorrent is used as fallback.',
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(6, 0))

        security_frame = ttk.LabelFrame(tab_import, text='🔐 Credential Security', padding=10)
        security_frame.pack(fill='x', pady=(0, 10), padx=10)

        security_status_var = tk.StringVar(value='Checking credential encryption status...')
        security_status_label = ttk.Label(security_frame, textvariable=security_status_var, font=('Segoe UI', 9, 'bold'))
        security_status_label.pack(anchor='w', pady=(0, 6))

        security_hint_var = tk.StringVar(value='')
        ttk.Label(security_frame, textvariable=security_hint_var, font=('Segoe UI', 8), foreground=subtle_fg).pack(anchor='w')

        def _refresh_security_status() -> None:
            try:
                if not config.is_secret_encryption_available():
                    security_status_var.set('⚠️ Encryption backend unavailable (plaintext fallback)')
                    security_status_label.configure(foreground='#d32f2f')
                    security_hint_var.set('Install dependency: cryptography')
                    return

                if config.has_plaintext_secrets():
                    security_status_var.set('⚠️ Plaintext credentials detected')
                    security_status_label.configure(foreground='#f57f17')
                    security_hint_var.set('Use "Migrate Secrets Now" to encrypt existing credentials in config.ini')
                else:
                    security_status_var.set('✅ Credentials stored in encrypted format')
                    security_status_label.configure(foreground='#2e7d32')
                    security_hint_var.set('qBittorrent password is encrypted at rest')
            except Exception:
                security_status_var.set('⚠️ Unable to determine credential security status')
                security_status_label.configure(foreground='#f57f17')
                security_hint_var.set('Try reopening Settings after saving connection values')

        def _migrate_secrets_now() -> None:
            try:
                if not config.is_secret_encryption_available():
                    messagebox.showwarning(
                        'Encryption Unavailable',
                        'Credential encryption backend is not available.\n\nInstall the cryptography package and try again.'
                    )
                    return

                changed = config.migrate_plaintext_secrets()
                if changed:
                    messagebox.showinfo('Migration Complete', 'Plaintext credentials were migrated to encrypted format.')
                else:
                    messagebox.showinfo('No Changes', 'No plaintext credentials were found to migrate.')
                _refresh_security_status()
            except Exception as e:
                messagebox.showerror('Migration Error', f'Failed to migrate credentials: {e}')

        def _export_secret_key() -> None:
            try:
                path = filedialog.asksaveasfilename(
                    title='Export Secret Key',
                    defaultextension='.key',
                    filetypes=[('Key files', '*.key'), ('All files', '*.*')]
                )
                if not path:
                    return
                if config.export_secret_key(path):
                    messagebox.showinfo('Export Complete', f'Secret key exported to:\n{path}')
                else:
                    messagebox.showerror('Export Failed', 'Could not export secret key.')
            except Exception as e:
                messagebox.showerror('Export Error', f'Failed to export key: {e}')

        def _rotate_secret_key() -> None:
            try:
                if not messagebox.askyesno(
                    'Rotate Secret Key',
                    'Rotate encryption key now?\n\nA backup of the previous key will be created locally.'
                ):
                    return
                if config.rotate_secret_key():
                    messagebox.showinfo('Rotation Complete', 'Secret key rotated and credentials re-encrypted.')
                    _refresh_security_status()
                else:
                    messagebox.showerror('Rotation Failed', 'Could not rotate secret key.')
            except Exception as e:
                messagebox.showerror('Rotation Error', f'Failed to rotate key: {e}')

        btn_row = ttk.Frame(security_frame)
        btn_row.pack(anchor='w', pady=(8, 0))
        ttk.Button(btn_row, text='🔄 Refresh Status', command=_refresh_security_status).pack(side='left', padx=(0, 8))
        ttk.Button(btn_row, text='🔐 Migrate Secrets Now', command=_migrate_secrets_now, style='Accent.TButton').pack(side='left')

        key_btn_row = ttk.Frame(security_frame)
        key_btn_row.pack(anchor='w', pady=(8, 0))
        ttk.Button(key_btn_row, text='🗝️ Export Key...', command=_export_secret_key).pack(side='left', padx=(0, 8))
        ttk.Button(key_btn_row, text='♻️ Rotate Key', command=_rotate_secret_key).pack(side='left')

        _refresh_security_status()
    except Exception:
        pass

    # Appearance tab only contains general display options.
    # Font controls are in the dedicated "Font & Style" tab.
    appearance_general_tab = tab_appearance

    # Appearance Tab - Theme
    try:
        theme_frame = ttk.LabelFrame(appearance_general_tab, text='🎨 Theme', padding=10)
        theme_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(theme_frame, text='Select the application color theme:',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        try:
            pref_theme = config.get_pref('theme', 'light')
        except Exception:
            pref_theme = 'light'
        theme_var = tk.StringVar(value=pref_theme)
        def _on_theme_change(new_theme):
            old_theme = config.get_pref('theme', 'light')
            if str(old_theme).strip().lower() != str(new_theme).strip().lower():
                config.set_pref('theme', new_theme)
                from tkinter import messagebox
                if messagebox.askyesno('Restart Required', 'Theme has been changed. Do you want to restart the application now?'):
                    from src.utils import restart_application
                    restart_application()
            else:
                config.set_pref('theme', new_theme)

        ttk.Radiobutton(theme_frame, text='☀️ Light (default)',
                       variable=theme_var, value='light',
                       command=lambda: _on_theme_change('light')).pack(anchor='w', pady=2)
        ttk.Radiobutton(theme_frame, text='🌙 Dark',
                       variable=theme_var, value='dark',
                       command=lambda: _on_theme_change('dark')).pack(anchor='w', pady=2)


        ttk.Label(theme_frame, text='💡 Theme change takes effect on next restart.',
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(8, 0))
    except Exception:
        pass

    # Appearance Tab - Time Format
    try:
        time_frame = ttk.LabelFrame(appearance_general_tab, text='🕐 Time Format', padding=10)
        time_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(time_frame, text='Select how times are displayed:',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        try:
            pref_time_24 = config.get_pref('time_24', True)
        except Exception:
            pref_time_24 = True
        time_format_var = tk.BooleanVar(value=bool(pref_time_24))

        ttk.Radiobutton(time_frame, text='24-hour format (default)',
                       variable=time_format_var, value=True,
                       command=lambda: config.set_pref('time_24', True)).pack(anchor='w', pady=2)
        ttk.Radiobutton(time_frame, text='12-hour format (AM/PM)',
                       variable=time_format_var, value=False,
                       command=lambda: config.set_pref('time_24', False)).pack(anchor='w', pady=2)
    except Exception:
        pass

    # Appearance Tab - View Mode
    try:
        view_frame = ttk.LabelFrame(appearance_general_tab, text='📊 View Mode', padding=10)
        view_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(view_frame, text='Choose how titles are displayed in the list:',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        try:
            pref_view_mode = config.get_pref('view_mode', 'expanded')
        except Exception:
            pref_view_mode = 'expanded'
        view_mode_var = tk.StringVar(value=pref_view_mode)

        ttk.Radiobutton(view_frame, text='📋 Expanded - Show all details (default)',
                       variable=view_mode_var, value='expanded',
                       command=lambda: config.set_pref('view_mode', 'expanded')).pack(anchor='w', pady=2)
        ttk.Radiobutton(view_frame, text='📄 Compact - Show titles only',
                       variable=view_mode_var, value='compact',
                       command=lambda: config.set_pref('view_mode', 'compact')).pack(anchor='w', pady=2)

        ttk.Label(view_frame, text='💡 View mode change takes effect on next restart.',
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(8, 0))
    except Exception:
        pass

    # Filesystem Type Settings (moved from Validation tab)
    try:
        fs_frame = ttk.LabelFrame(tab_sanitization, text='💾 Target Filesystem Type', padding=10)
        fs_frame.pack(fill='x', pady=(0, 10), padx=10)
        
        ttk.Label(fs_frame, text='Select the target filesystem for folder validation:', 
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))
        
        try:
            pref_fs_type = config.get_pref('filesystem_type', 'linux')
        except Exception:
            pref_fs_type = 'linux'
        fs_type_var = tk.StringVar(value=pref_fs_type)
        
        ttk.Radiobutton(fs_frame, text='🐧 Linux/Unix/Unraid (default) - Only blocks forward slashes (/)', 
                       variable=fs_type_var, value='linux',
                       command=lambda: config.set_pref('filesystem_type', 'linux')).pack(anchor='w', pady=2)
        ttk.Radiobutton(fs_frame, text='🪟 Windows - Strict validation (colons, quotes, etc. not allowed)', 
                       variable=fs_type_var, value='windows',
                       command=lambda: config.set_pref('filesystem_type', 'windows')).pack(anchor='w', pady=2)
        
        ttk.Label(fs_frame, text='💡 This affects validation for the selected main server model.', 
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(8, 2))
        validation_profile_var = tk.StringVar(
            value=f"Validation profile: {get_validation_profile_label(main_server=main_server_temp.get())}"
        )
        ttk.Label(fs_frame, textvariable=validation_profile_var,
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(0, 2))

        def _update_validation_profile(*_args):
            validation_profile_var.set(
                f"Validation profile: {get_validation_profile_label(main_server=main_server_temp.get())}"
            )

        fs_type_var.trace_add('write', _update_validation_profile)
        main_server_temp.trace_add('write', _update_validation_profile)
        ttk.Label(fs_frame, text='⚠️ Note: Linux folders with colons (:) will appear without colons', 
                  font=('Segoe UI', 8), foreground='#d32f2f').pack(anchor='w', pady=(0, 0))
        ttk.Label(fs_frame, text='    when accessed from Windows via SMB shares', 
                  font=('Segoe UI', 8), foreground='#d32f2f').pack(anchor='w', pady=(0, 0))
        
        # Auto-sanitize option
        ttk.Separator(fs_frame, orient='horizontal').pack(fill='x', pady=(10, 10))
        
        try:
            pref_auto_sanitize = config.get_pref('auto_sanitize_paths', True)
        except Exception:
            pref_auto_sanitize = True
        auto_sanitize_var = tk.BooleanVar(value=bool(pref_auto_sanitize))
        
        ttk.Checkbutton(fs_frame, text='✨ Auto-sanitize invalid folder names when syncing', 
                       variable=auto_sanitize_var,
                       command=lambda: config.set_pref('auto_sanitize_paths', auto_sanitize_var.get())).pack(anchor='w', pady=2)
        ttk.Label(fs_frame, text='💡 Auto-sanitization follows selected filesystem mode: Linux only sanitizes "/", Windows sanitizes < > : " \\ | ? * and /.', 
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(2, 0))
    except Exception:
        pass

    # Special Character Sanitization Settings
    try:
        sanitize_frame = ttk.LabelFrame(tab_sanitization, text='✂️ Special Character Sanitization', padding=10)
        sanitize_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(sanitize_frame, text='Control how invalid characters are replaced when sanitizing titles.',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        # Show which characters are invalid on Windows/Linux
        info_frame = ttk.LabelFrame(sanitize_frame, text='📋 Invalid Characters by Platform', padding=10)
        info_frame.pack(fill='x', pady=(0, 10), anchor='w')

        ttk.Label(info_frame, text='Windows only:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 3))
        ttk.Label(info_frame, text='< > : " \\ | ? *', font=('Segoe UI', 9), foreground='#0078D4').pack(anchor='w', padx=(20, 0), pady=(0, 6))

        ttk.Label(info_frame, text='Both Windows & Linux:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 3))
        ttk.Label(info_frame, text='/ (forward slash)', font=('Segoe UI', 9), foreground='#107C10').pack(anchor='w', padx=(20, 0), pady=(0, 0))

        sanitize_scope_var = tk.StringVar(value='Active sanitization scope: Linux mode -> only / is sanitized.')

        def _update_sanitization_scope_label(*_args):
            try:
                current_fs = str(config.get_pref('filesystem_type', 'linux') or 'linux').strip().lower()
            except Exception:
                current_fs = 'linux'
            if current_fs == 'windows':
                sanitize_scope_var.set('Active sanitization scope: Windows mode -> < > : " \\ | ? * and / are sanitized.')
            else:
                sanitize_scope_var.set('Active sanitization scope: Linux mode -> only / is sanitized.')

        _update_sanitization_scope_label()
        try:
            fs_type_var.trace_add('write', _update_sanitization_scope_label)
        except Exception:
            pass

        ttk.Label(sanitize_frame, textvariable=sanitize_scope_var,
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(0, 8))

        def _get_active_filesystem_for_sanitize() -> str:
            try:
                return str(fs_type_var.get() or 'linux').strip().lower()
            except Exception:
                try:
                    return str(config.get_pref('filesystem_type', 'linux') or 'linux').strip().lower()
                except Exception:
                    return 'linux'

        def _update_sanitize_inputs():
            state = 'disabled' if sanitize_replace_all_var.get() else 'normal'
            active_fs = _get_active_filesystem_for_sanitize()

            for ch in FileSystem.INVALID_CHARS:
                entry_widget = sanitize_entries.get(ch)
                char_label = sanitize_char_labels.get(ch)
                preview_label = sanitize_preview_labels.get(ch)
                if entry_widget is None:
                    continue

                active_for_fs = (active_fs == 'windows') or (ch == '/')
                effective_state = state if active_for_fs else 'disabled'

                try:
                    entry_widget.configure(state=effective_state)
                except Exception:
                    pass

                try:
                    if char_label is not None:
                        char_label.configure(foreground='#333' if active_for_fs else '#999')
                except Exception:
                    pass

                try:
                    if preview_label is not None and not active_for_fs:
                        preview_label.configure(foreground='#999')
                except Exception:
                    pass

        def _on_replace_all_toggle():
            _update_sanitize_inputs()
            try:
                config.set_pref(PrefKeys.SANITIZE_REPLACE_ALL, bool(sanitize_replace_all_var.get()))
            except Exception:
                pass

        ttk.Checkbutton(
            sanitize_frame,
            text='Replace all special characters with a single character',
            variable=sanitize_replace_all_var,
            command=_on_replace_all_toggle
        ).pack(anchor='w', pady=2)

        replacement_row = ttk.Frame(sanitize_frame)
        replacement_row.pack(fill='x', pady=(6, 4))
        ttk.Label(replacement_row, text='Replacement character:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 6))

        def _clamp_global_char(*_):
            val = sanitize_global_char_var.get()
            if len(val) > 1:
                sanitize_global_char_var.set(val[0])
        sanitize_global_char_var.trace_add('write', _clamp_global_char)

        ttk.Entry(replacement_row, textvariable=sanitize_global_char_var, width=6).pack(side='left')
        ttk.Label(replacement_row, text='Used when "replace all" is enabled; defaults to _ if blank.',
                  font=('Segoe UI', 8), foreground='#666').pack(side='left', padx=8)

        ttk.Label(sanitize_frame, text='Custom replacements (only used when "replace all" is OFF):',
                  font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(8, 6))

        # Style for disabled custom map entries so they appear gray
        sanitize_entry_style = ttk.Style(sanitize_frame)
        sanitize_entry_style.configure('SanitizeEntry.TEntry', padding=4)
        sanitize_entry_style.map(
            'SanitizeEntry.TEntry',
            foreground=[('disabled', '#777')],
            fieldbackground=[('disabled', '#f0f0f0')]
        )

        table = ttk.Frame(sanitize_frame)
        table.pack(fill='x', pady=(0, 4))
        ttk.Label(table, text='Character', font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky='w', padx=4, pady=2)
        ttk.Label(table, text='Replacement', font=('Segoe UI', 9, 'bold')).grid(row=0, column=1, sticky='w', padx=4, pady=2)
        ttk.Label(table, text='Preview', font=('Segoe UI', 9, 'bold')).grid(row=0, column=2, sticky='w', padx=4, pady=2)

        sanitize_entries: Dict[str, ttk.Entry] = {}
        sanitize_char_labels: Dict[str, ttk.Label] = {}
        sanitize_preview_labels = {}
        
        def _update_preview_for_char(ch):
            """Update preview label to show visible representation of replacement."""
            val = sanitize_char_vars[ch].get()
            preview_label = sanitize_preview_labels.get(ch)
            if preview_label:
                token = val.strip().lower()
                if val == ' ' or token == 'space':
                    preview_label.config(text='(space)', foreground='#0078D4')
                elif token == 'remove':
                    preview_label.config(text='(remove)', foreground='#d32f2f')
                elif val == '':
                    preview_label.config(text='(empty)', foreground='#999')
                else:
                    preview_label.config(text=val, foreground='#333')
        
        for idx, ch in enumerate(FileSystem.INVALID_CHARS, start=1):
            char_label = ttk.Label(table, text=ch, width=4)
            char_label.grid(row=idx, column=0, sticky='w', padx=4, pady=2)
            sanitize_char_labels[ch] = char_label

            entry = ttk.Entry(table, textvariable=sanitize_char_vars[ch], width=10, style='SanitizeEntry.TEntry')
            entry.grid(row=idx, column=1, sticky='w', padx=4, pady=2)
            sanitize_entries[ch] = entry
            
            # Preview label to show space visibly
            preview_label = ttk.Label(table, text='(empty)', foreground='#999', width=10)
            preview_label.grid(row=idx, column=2, sticky='w', padx=4, pady=2)
            sanitize_preview_labels[ch] = preview_label
            
            # Update preview on change
            sanitize_char_vars[ch].trace_add('write', lambda *args, c=ch: _update_preview_for_char(c))
            _update_preview_for_char(ch)

        ttk.Label(
            sanitize_frame,
            text='Leave blank to fall back to default. Use "space" for a space or "remove" to delete that character.',
            font=('Segoe UI', 8), foreground='#666'
        ).pack(anchor='w', pady=(2, 4))

        ttk.Label(
            sanitize_frame,
            text='Note: In Linux mode, non-slash character mappings (like : or *) are stored but not applied until Windows mode is selected.',
            font=('Segoe UI', 8), foreground='#666'
        ).pack(anchor='w', pady=(0, 4))

        try:
            fs_type_var.trace_add('write', lambda *_args: _update_sanitize_inputs())
        except Exception:
            pass

        _update_sanitize_inputs()
    except Exception:
        pass

    # Diagnostics Tab - Settings Location Note
    try:
        api_note_frame = ttk.LabelFrame(tab_diagnostics, text='⏱️ API Rate Limits', padding=10)
        api_note_frame.pack(fill='x', pady=(0, 10), padx=10)
        ttk.Label(
            api_note_frame,
            text='Rate-limit controls were moved to the dedicated "API Rate Limits" tab.',
            font=('Segoe UI', 9),
        ).pack(anchor='w', pady=(0, 4))
        ttk.Label(
            api_note_frame,
            text='Use that tab to configure AniList and SubsPlease manual refresh cooldowns.',
            font=('Segoe UI', 8),
            foreground='#666',
        ).pack(anchor='w')
    except Exception:
        pass

    # Diagnostics Tab - Logging
    try:
        log_frame = ttk.LabelFrame(tab_diagnostics, text='📊 Logging', padding=10)
        log_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(log_frame, text='Log level controls the verbosity of application logs.',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        try:
            pref_log_level = config.get_pref('log_level', 'INFO')
        except Exception:
            pref_log_level = 'INFO'
        log_level_var = tk.StringVar(value=pref_log_level)

        def _on_log_level_change():
            try:
                config.set_pref('log_level', log_level_var.get())
            except Exception:
                pass

        level_frame = ttk.Frame(log_frame)
        level_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(level_frame, text='Level:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        log_combo = ttk.Combobox(level_frame, textvariable=log_level_var,
                                 values=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                                 state='readonly', width=12)
        log_combo.pack(side='left')
        log_combo.bind('<<ComboboxSelected>>', lambda e: _on_log_level_change())

        ttk.Label(log_frame, text='💡 Change takes effect on next application restart.',
                  font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(0, 8))

        ttk.Button(log_frame, text='📄 View Logs',
                   command=lambda: open_log_viewer(root)).pack(anchor='w', pady=(4, 0))
    except Exception:
        pass

    # Diagnostics Tab - Connection Test
    try:
        test_frame = ttk.LabelFrame(tab_diagnostics, text='🔌 Connection Test', padding=10)
        test_frame.pack(fill='x', pady=(0, 10), padx=10)

        ttk.Label(test_frame, text='Test qBittorrent profile connection (used when main model is qBittorrent).',
                  font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 8))

        test_status_var = tk.StringVar(value='Not tested')
        test_status_label = ttk.Label(test_frame, textvariable=test_status_var,
                                      font=('Segoe UI', 9), foreground='#666')
        test_status_label.pack(anchor='w', pady=(0, 8))

        def _run_diag_test():
            def _worker():
                test_status_var.set('⏳ Testing...')
                try:
                    ca_cert = ca_cert_temp.get().strip() or None
                    ok, msg = qbt_api.ping_qbittorrent(
                        qbt_protocol_temp.get(),
                        qbt_host_temp.get(),
                        qbt_port_temp.get(),
                        qbt_user_temp.get(),
                        qbt_pass_temp.get(),
                        verify_ssl_temp.get(),
                        ca_cert
                    )
                    if ok:
                        test_status_var.set(f'✅ Connected: {msg}')
                    else:
                        test_status_var.set(f'❌ Failed: {msg}')
                except Exception as e:
                    test_status_var.set(f'❌ Error: {e}')
            threading.Thread(target=_worker, daemon=True).start()

        ttk.Button(test_frame, text='🔍 Test Connection Now',
                   command=_run_diag_test, style='Accent.TButton').pack(anchor='w')
    except Exception:
        pass

    # Footer with buttons - outside scrollable area
    footer_frame = ttk.Frame(settings_win, padding=10)
    footer_frame.pack(fill='x', side='bottom')
    
    save_btn = ttk.Button(footer_frame, text="💾 Save & Close", command=save_and_close, style='Accent.TButton', width=20)
    save_btn.pack(side='right', padx=5)
    
    cancel_btn = ttk.Button(footer_frame, text="✕ Cancel", command=_close_settings_window, width=15)
    cancel_btn.pack(side='right')


def open_log_viewer(root: tk.Tk) -> None:
    """
    Opens a window displaying the application log file.
    
    Shows the last 500 lines of the log file with auto-refresh capability
    and buttons to clear or open the full log file.
    
    Args:
        root: Parent Tkinter window
    """
    existing_log = getattr(root, '_log_window', None)
    if existing_log is not None:
        try:
            if existing_log.winfo_exists():
                existing_log.lift()
                existing_log.focus_force()
                return
        except Exception:
            pass
        try:
            setattr(root, '_log_window', None)
        except Exception:
            pass

    log_window = tk.Toplevel(root)
    setattr(root, '_log_window', log_window)
    log_window.title('Application Log Viewer')
    log_window.geometry('900x600')
    log_window.transient(root)

    def _close_log_window() -> None:
        """Close log viewer and clear root window reference."""
        try:
            setattr(root, '_log_window', None)
        except Exception:
            pass
        try:
            log_window.destroy()
        except Exception:
            pass

    log_window.protocol("WM_DELETE_WINDOW", _close_log_window)
    
    # Create toolbar
    toolbar = ttk.Frame(log_window)
    toolbar.pack(side='top', fill='x', padx=5, pady=5)
    
    # Log level filter
    ttk.Label(toolbar, text='Filter:').pack(side='left', padx=5)
    filter_var = tk.StringVar(value='ALL')
    filter_combo = ttk.Combobox(toolbar, textvariable=filter_var, 
                                 values=['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
                                 state='readonly', width=10)
    filter_combo.pack(side='left', padx=5)
    
    # Create text widget with scrollbar
    text_frame = ttk.Frame(log_window)
    text_frame.pack(fill='both', expand=True, padx=5, pady=5)
    
    log_text = tk.Text(text_frame, wrap='word', height=30, width=100)
    log_text.pack(side='left', fill='both', expand=True)
    
    scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=log_text.yview)
    scrollbar.pack(side='right', fill='y')
    log_text.configure(yscrollcommand=scrollbar.set)
    
    # Configure text tags for color coding
    log_text.tag_configure('ERROR', foreground='red')
    log_text.tag_configure('WARNING', foreground='orange')
    log_text.tag_configure('INFO', foreground='blue')
    log_text.tag_configure('DEBUG', foreground='gray')
    
    def load_log_content():
        """Load and display log file content with filtering."""
        try:
            log_text.configure(state='normal')
            log_text.delete('1.0', 'end')
            
            if not os.path.exists('qbt_editor.log'):
                log_text.insert('1.0', 'No log file found. Start using the application to generate logs.')
                log_text.configure(state='disabled')
                return
            
            # Read last 500 lines
            with open('qbt_editor.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                lines = lines[-500:] if len(lines) > 500 else lines
            
            filter_level = filter_var.get()
            
            for line in lines:
                # Apply filter
                if filter_level != 'ALL':
                    if f' - {filter_level} - ' not in line:
                        continue
                
                # Color code by log level
                if ' - ERROR - ' in line:
                    log_text.insert('end', line, 'ERROR')
                elif ' - WARNING - ' in line:
                    log_text.insert('end', line, 'WARNING')
                elif ' - INFO - ' in line:
                    log_text.insert('end', line, 'INFO')
                elif ' - DEBUG - ' in line:
                    log_text.insert('end', line, 'DEBUG')
                else:
                    log_text.insert('end', line)
            
            # Scroll to bottom
            log_text.see('end')
            log_text.configure(state='disabled')
            
        except Exception as e:
            log_text.insert('1.0', f'Error loading log file: {e}')
            log_text.configure(state='disabled')
    
    def refresh_log():
        """Refresh the log display."""
        load_log_content()
    
    def clear_log():
        """Clear the log file after confirmation."""
        if messagebox.askyesno('Clear Log', 'Are you sure you want to clear the log file?'):
            try:
                with open('qbt_editor.log', 'w', encoding='utf-8') as f:
                    f.write('')
                logger.info('Log file cleared by user')
                load_log_content()
                messagebox.showinfo('Success', 'Log file cleared successfully')
            except Exception as e:
                messagebox.showerror('Error', f'Failed to clear log: {e}')
    
    def open_log_file():
        """Open the log file in the default text editor."""
        try:
            if os.path.exists('qbt_editor.log'):
                if sys.platform == 'win32':
                    os.startfile('qbt_editor.log')
                elif sys.platform == 'darwin':
                    os.system('open qbt_editor.log')
                else:
                    os.system('xdg-open qbt_editor.log')
            else:
                messagebox.showwarning('Not Found', 'Log file does not exist yet.')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open log file: {e}')
    
    def copy_log_to_clipboard():
        """Copy the visible log content to clipboard."""
        try:
            log_content = log_text.get('1.0', 'end-1c')
            log_window.clipboard_clear()
            log_window.clipboard_append(log_content)
            messagebox.showinfo('Copied', 'Log content copied to clipboard')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to copy log: {e}')
    
    # Buttons
    button_frame = ttk.Frame(log_window)
    button_frame.pack(side='bottom', fill='x', padx=5, pady=5)
    
    ttk.Button(button_frame, text='📋 Copy', command=copy_log_to_clipboard).pack(side='left', padx=5)
    ttk.Button(button_frame, text='Refresh', command=refresh_log).pack(side='left', padx=5)
    ttk.Button(button_frame, text='Clear Log', command=clear_log).pack(side='left', padx=5)
    ttk.Button(button_frame, text='Open in Editor', command=open_log_file).pack(side='left', padx=5)
    ttk.Button(button_frame, text='Close', command=_close_log_window).pack(side='right', padx=5)
    
    # Bind filter change
    filter_combo.bind('<<ComboboxSelected>>', lambda e: load_log_content())
    
    # Initial load
    load_log_content()


def view_trash_dialog(parent: tk.Tk) -> None:
    """
    Opens a dialog showing all deleted items in the trash.
    
    Args:
        parent: Parent Tkinter window
    """
    app_state = AppState.get_instance()
    trash_items = app_state.trash_items
    
    try:
        dlg = tk.Toplevel(parent)
        dlg.title('Trash')
        dlg.transient(parent)
        dlg.grab_set()

        lb = tk.Listbox(dlg, height=12, width=80)
        lb.pack(fill='both', expand=True, padx=10, pady=10)

        def refresh():
            try:
                lb.delete(0, 'end')
            except Exception:
                pass
            for it in trash_items:
                try:
                    lb.insert('end', f"{it.get('src')} - {it.get('title')}")
                except Exception:
                    pass

        def _restore_selected():
            try:
                sel = lb.curselection()
                if not sel:
                    messagebox.showwarning('Restore', 'No trash item selected.')
                    return
                restored_count = 0
                for i in sorted([int(x) for x in sel], reverse=True):
                    try:
                        item = trash_items.pop(i)
                    except Exception:
                        continue
                    if item.get('src') == 'titles':
                        title_text = item.get('title')
                        entry = item.get('entry')
                        try:
                            # Add back to listbox_items
                            app_state.listbox_items.append((title_text, entry))
                            
                            # Add back to config.ALL_TITLES
                            import src.config as config
                            if not hasattr(config, 'ALL_TITLES') or not isinstance(config.ALL_TITLES, dict):
                                config.ALL_TITLES = {}
                            if 'existing' not in config.ALL_TITLES:
                                config.ALL_TITLES['existing'] = []
                            config.ALL_TITLES['existing'].append(entry)
                            
                            restored_count += 1
                        except Exception:
                            pass
                
                # Refresh treeview to show restored items
                if restored_count > 0:
                    update_treeview_with_titles(config.ALL_TITLES)
                
                refresh()
                messagebox.showinfo('Restore', f'Restored {restored_count} item(s) to Titles.')
            except Exception as e:
                messagebox.showerror('Restore Error', f'Failed to restore: {e}')

        def _delete_permanent():
            try:
                sel = lb.curselection()
                if not sel:
                    messagebox.showwarning('Delete', 'No trash item selected.')
                    return
                if not messagebox.askyesno('Permanently Delete', f'Delete {len(sel)} item(s) permanently?'):
                    return
                for i in sorted([int(x) for x in sel], reverse=True):
                    try:
                        trash_items.pop(i)
                    except Exception:
                        pass
                refresh()
            except Exception as e:
                messagebox.showerror('Delete Error', f'Failed to permanently delete: {e}')

        def _empty_trash():
            try:
                if not trash_items:
                    return
                if not messagebox.askyesno('Empty Trash', 'Empty the trash permanently?'):
                    return
                trash_items.clear()
                refresh()
            except Exception as e:
                messagebox.showerror('Trash Error', f'Failed to empty trash: {e}')

        btns = ttk.Frame(dlg)
        btns.pack(fill='x', padx=10, pady=(0,10))
        ttk.Button(btns, text='Restore Selected', command=_restore_selected).pack(side='left')
        ttk.Button(btns, text='Delete Permanently', command=_delete_permanent).pack(side='left', padx=6)
        ttk.Button(btns, text='Empty Trash', command=_empty_trash).pack(side='right')

        refresh()
    except Exception:
        pass


def open_full_rule_editor(root: tk.Tk, title_text: str, entry: Dict[str, Any], idx: int, 
                          populate_editor_callback: Optional[callable] = None) -> None:
    """
    Opens a comprehensive editor dialog for all rule settings.
    
    Args:
        root: Parent Tkinter window
        title_text: Display name of the title being edited
        entry: Rule entry dictionary containing all configuration
        idx: Index of the item in listbox_items
        populate_editor_callback: Optional callback to refresh main editor after save
    """
    app_state = AppState.get_instance()
    listbox_items = app_state.listbox_items
    treeview_widget = app_state.treeview_widget
    
    dlg = tk.Toplevel(root)
    dlg.title(f'🔧 Advanced Rule Editor - {title_text}')
    
    # Auto-size to monitor height (use 85% of screen height), increased width to 1000px
    try:
        screen_height = dlg.winfo_screenheight()
        dialog_height = int(screen_height * 0.85)
        dialog_height = max(600, min(dialog_height, screen_height - 100))
        dlg.geometry(f'1000x{dialog_height}')
    except Exception:
        dlg.geometry('1000x700')
    
    dlg.transient(root)
    dlg.grab_set()
    dlg.configure(bg='#f5f5f5')

    def safe_get(d, *keys, default=''):
        try:
            v = d
            for k in keys:
                v = v.get(k) if isinstance(v, dict) else None
            return v if v is not None else default
        except Exception:
            return default

    def _get_field(k, default=''):
        try:
            if not isinstance(entry, dict):
                return default
            v = entry.get(k)
            return default if v is None else v
        except Exception:
            return default

    def _strip_season_year_prefix(text: str) -> str:
        """Remove a leading Season Year prefix if present."""
        try:
            return re.sub(r'^(Winter|Spring|Summer|Fall)\s+\d{4}\s*-\s*', '', str(text or '').strip(), count=1)
        except Exception:
            return str(text or '').strip()

    addPaused_val = _get_field('addPaused', None)
    if addPaused_val is None:
        addPaused_str = 'None'
    else:
        addPaused_str = 'True' if addPaused_val else 'False'
    addPaused_var = tk.StringVar(value=addPaused_str)
    assigned_var = tk.StringVar(value=_get_field('assignedCategory', ''))
    enabled_var = tk.BooleanVar(value=bool(_get_field('enabled', True)))
    episode_var = tk.StringVar(value=_get_field('episodeFilter', ''))
    ignore_var = tk.StringVar(value=str(_get_field('ignoreDays', 0)))
    lastmatch_var = tk.StringVar(value=_get_field('lastMatch', ''))
    must_var = tk.StringVar(value=_get_field('mustContain', title_text))
    mustnot_var = tk.StringVar(value=_get_field('mustNotContain', ''))
    priority_var = tk.StringVar(value=str(_get_field('priority', 0)))
    rule_title_var = tk.StringVar(value=title_text)

    smart_var = tk.BooleanVar(value=bool(_get_field('smartFilter', False)))
    tcl_val = _get_field('torrentContentLayout', '')
    tcl_var = tk.StringVar(value='' if tcl_val is None else tcl_val)
    useregex_var = tk.BooleanVar(value=bool(_get_field('useRegex', False)))

    tp = entry.get('torrentParams') if (isinstance(entry, dict) and entry.get('torrentParams') is not None) else {}
    try:
        sp_val = _get_field('savePath', '') or _get_field('save_path', '')
        if not sp_val and isinstance(tp, dict):
            sp_val = tp.get('save_path') or tp.get('download_path') or ''
        sp_disp = '' if sp_val is None else str(sp_val).replace('/', '\\')
    except Exception:
        sp_disp = ''

    savepath_var = tk.StringVar(value=sp_disp)
    tp_category = tk.StringVar(value=tp.get('category', ''))
    tp_download_limit = tk.StringVar(value=str(tp.get('download_limit', -1)))
    tp_download_path = tk.StringVar(value=tp.get('download_path', ''))
    tp_inactive_limit = tk.StringVar(value=str(tp.get('inactive_seeding_time_limit', -2)))
    tp_operating_mode = tk.StringVar(value=tp.get('operating_mode', 'AutoManaged'))
    tp_ratio_limit = tk.StringVar(value=str(tp.get('ratio_limit', -2)))
    tp_save_path = tk.StringVar(value=tp.get('save_path', '').replace('/', '\\'))
    tp_seeding_time = tk.StringVar(value=str(tp.get('seeding_time_limit', -2)))
    tp_skip = tk.BooleanVar(value=bool(tp.get('skip_checking', False)))
    tp_tags = tk.StringVar(value=(','.join(tp.get('tags')) if isinstance(tp.get('tags'), list) else ''))
    tp_upload_limit = tk.StringVar(value=str(tp.get('upload_limit', -1)))
    tp_auto_tmm = tk.BooleanVar(value=bool(tp.get('use_auto_tmm', False)))

    # Create scrollable frame
    canvas = tk.Canvas(dlg, bg='#f5f5f5', highlightthickness=0)
    scrollbar = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas, padding=20)
    
    def _update_scrollregion(event=None):
        try:
            if canvas.winfo_exists():
                canvas.configure(scrollregion=canvas.bbox("all"))
                # Show/hide scrollbar based on content size
                try:
                    bbox = canvas.bbox("all")
                    if bbox:
                        content_height = bbox[3] - bbox[1]
                        canvas_height = canvas.winfo_height()
                        if content_height > canvas_height:
                            scrollbar.pack(side="right", fill="y")
                        else:
                            scrollbar.pack_forget()
                except Exception:
                    pass
        except Exception:
            pass
    
    scrollable_frame.bind("<Configure>", _update_scrollregion)
    
    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Update canvas window width when canvas resizes to eliminate right space
    def _on_canvas_resize(event):
        try:
            canvas.itemconfig(canvas_window, width=event.width)
        except Exception:
            pass
    canvas.bind('<Configure>', _on_canvas_resize)
    
    # Enable mousewheel scrolling when hovering - use widget-specific binding
    def _on_mousewheel(event):
        try:
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        except Exception:
            pass
    
    def _bind_mousewheel(event):
        try:
            canvas.bind("<MouseWheel>", _on_mousewheel)
        except Exception:
            pass
    
    def _unbind_mousewheel(event):
        try:
            canvas.unbind("<MouseWheel>")
        except Exception:
            pass
    
    canvas.bind("<Enter>", _bind_mousewheel)
    canvas.bind("<Leave>", _unbind_mousewheel)
    scrollable_frame.bind("<Enter>", _bind_mousewheel)
    scrollable_frame.bind("<Leave>", _unbind_mousewheel)
    
    # Create footer frame FIRST (pack at bottom before canvas)
    footer = ttk.Frame(dlg, padding=10)
    footer.pack(side='bottom', fill='x', pady=(0, 0), padx=10)
    
    # Add separator above footer for visual distinction
    footer_separator = ttk.Separator(dlg, orient='horizontal')
    footer_separator.pack(side='bottom', fill='x', pady=(0, 0))
    
    # Pack canvas and scrollbar - using pack for main layout
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Cleanup on dialog close
    def _on_close():
        try:
            canvas.unbind("<Enter>")
            canvas.unbind("<Leave>")
            canvas.unbind("<MouseWheel>")
            scrollable_frame.unbind("<Enter>")
            scrollable_frame.unbind("<Leave>")
        except Exception:
            pass
        dlg.destroy()
    
    dlg.protocol("WM_DELETE_WINDOW", _on_close)
    
    row = 0
    frm = scrollable_frame
    
    # Configure column 1 to expand with window resize
    frm.columnconfigure(1, weight=1)

    def grid_label(r, text=''):
        ttk.Label(frm, text=text, font=('Segoe UI', 9, 'bold')).grid(row=r, column=0, sticky='w', padx=5, pady=4)

    affected_frame = ttk.Frame(frm)
    affected_listbox_frame = ttk.Frame(affected_frame)
    affected_listbox = tk.Listbox(affected_listbox_frame, height=5, font=('Consolas', 9),
                                   bg='#fafafa', relief='flat', bd=1, selectmode='extended',
                                   highlightthickness=1, highlightbackground='#e0e0e0')
    affected_scrollbar = ttk.Scrollbar(affected_listbox_frame, orient='vertical', command=affected_listbox.yview)
    affected_listbox.configure(yscrollcommand=affected_scrollbar.set)

    prevmatches_frame = ttk.Frame(frm)
    prevmatches_text = tk.Text(prevmatches_frame, height=3, width=50, font=('Consolas', 9),
                               bg='#fafafa', relief='flat', bd=1,
                               highlightthickness=1, highlightbackground='#e0e0e0')
    
    # Title section
    ttk.Label(frm, text='📌 Basic Information', font=('Segoe UI', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
    row += 1

    grid_label(row, 'Rule Title:')
    title_frame = ttk.Frame(frm)
    title_frame.grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    title_frame.columnconfigure(0, weight=1)
    title_entry = ttk.Entry(title_frame, textvariable=rule_title_var, font=('Segoe UI', 9))
    title_entry.grid(row=0, column=0, sticky='ew', padx=(0, 6))

    def _open_prefix_dialog():
        current_title = rule_title_var.get().strip()
        base_title = _strip_season_year_prefix(current_title)
        current_season, current_year = get_current_anime_season()

        prefix_win = tk.Toplevel(dlg)
        prefix_win.title('Set Prefix')
        prefix_win.geometry('460x320')
        prefix_win.resizable(False, False)
        prefix_win.transient(dlg)
        prefix_win.grab_set()
        center_window(prefix_win, dlg)

        prefix_frame = ttk.Frame(prefix_win, padding=16)
        prefix_frame.pack(fill='both', expand=True)

        ttk.Label(prefix_frame, text='Set Prefix', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(prefix_frame, text='Choose a Season/Year prefix or provide your own custom prefix.', font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 10))

        mode_var = tk.StringVar(value='season_year')
        season_var = tk.StringVar(value=current_season)
        year_var = tk.StringVar(value=current_year)
        custom_prefix_var = tk.StringVar(value='')
        preview_var = tk.StringVar(value='')

        season_row = ttk.Frame(prefix_frame)
        season_row.pack(fill='x', pady=4)
        ttk.Radiobutton(season_row, text='Season/Year Prefix', variable=mode_var, value='season_year').pack(anchor='w')

        season_fields = ttk.Frame(prefix_frame)
        season_fields.pack(fill='x', pady=(0, 10))
        ttk.Label(season_fields, text='Season:').grid(row=0, column=0, sticky='w', padx=(0, 6))
        season_combo = ttk.Combobox(season_fields, textvariable=season_var, values=['Winter', 'Spring', 'Summer', 'Fall'], state='readonly', width=12)
        season_combo.grid(row=0, column=1, sticky='w', padx=(0, 12))
        ttk.Label(season_fields, text='Year:').grid(row=0, column=2, sticky='w', padx=(0, 6))
        year_entry = ttk.Entry(season_fields, textvariable=year_var, width=8)
        year_entry.grid(row=0, column=3, sticky='w')

        custom_row = ttk.Frame(prefix_frame)
        custom_row.pack(fill='x', pady=4)
        ttk.Radiobutton(custom_row, text='Custom Prefix', variable=mode_var, value='custom').pack(anchor='w')
        custom_entry = ttk.Entry(prefix_frame, textvariable=custom_prefix_var)
        custom_entry.pack(fill='x', pady=(0, 10))

        preview_label = ttk.Label(prefix_frame, textvariable=preview_var, font=('Segoe UI', 9, 'italic'), foreground='#666')
        preview_label.pack(anchor='w', pady=(0, 12))

        def _update_preview(*_args):
            if mode_var.get() == 'custom':
                prefix = custom_prefix_var.get().strip()
            else:
                prefix = f"{season_var.get().strip()} {year_var.get().strip()}"
            prefix = prefix.strip()
            if prefix:
                preview_var.set(f"Preview: {prefix} - {base_title}")
            else:
                preview_var.set(f"Preview: {base_title}")

        mode_var.trace_add('write', _update_preview)
        season_var.trace_add('write', _update_preview)
        year_var.trace_add('write', _update_preview)
        custom_prefix_var.trace_add('write', _update_preview)
        _update_preview()

        def _apply_prefix():
            try:
                if mode_var.get() == 'custom':
                    prefix_text = custom_prefix_var.get().strip()
                else:
                    prefix_text = f"{season_var.get().strip()} {year_var.get().strip()}".strip()

                if not prefix_text:
                    messagebox.showwarning('Prefix', 'Please enter a prefix or choose a season/year.', parent=prefix_win)
                    return

                rule_title_var.set(f"{prefix_text} - {base_title}".strip())
                prefix_win.destroy()
            except Exception as e:
                messagebox.showerror('Prefix Error', f'Failed to apply prefix:\n{e}', parent=prefix_win)

        btn_row = ttk.Frame(prefix_frame)
        btn_row.pack(fill='x', pady=(8, 0))
        ttk.Button(btn_row, text='Apply', command=_apply_prefix, style='Accent.TButton').pack(side='right', padx=(6, 0))
        ttk.Button(btn_row, text='Cancel', command=prefix_win.destroy).pack(side='right')

    ttk.Button(title_frame, text='Prefix', command=_open_prefix_dialog, width=8).grid(row=0, column=1, sticky='e')
    row += 1
    
    ttk.Separator(frm, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=15)
    row += 1
    
    ttk.Label(frm, text='⚙️ Rule Configuration', font=('Segoe UI', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
    row += 1

    grid_label(row, 'Add Paused:')
    ttk.Combobox(frm, textvariable=addPaused_var, values=['None', 'False', 'True'], 
                 state='readonly', width=15, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    def _validate_full_lastmatch(*a):
        try:
            txt = lastmatch_var.get().strip()
            if lastmatch_full_status_label is None:
                return True
            try:
                lastmatch_full_status_label.config(text='', fg='green')
            except Exception:
                pass
            if not txt:
                return True
            if not (txt.startswith('{') or txt.startswith('[') or txt.startswith('"')):
                return True
            try:
                json.loads(txt)
                try:
                    lastmatch_full_status_label.config(text='Valid JSON', fg='green')
                except Exception:
                    pass
                return True
            except Exception as e:
                try:
                    msg = f'Invalid JSON: {str(e)}'
                    short = msg if len(msg) < 120 else msg[:116] + '...'
                    lastmatch_full_status_label.config(text=short, fg='red')
                except Exception:
                    pass
                return False
        except Exception:
            try:
                if lastmatch_full_status_label is not None:
                    lastmatch_full_status_label.config(text='Invalid JSON', fg='red')
            except Exception:
                pass
            return False

    try:
        lastmatch_var.trace_add('write', lambda *a: _validate_full_lastmatch())
    except Exception:
        try:
            lastmatch_var.trace('w', lambda *a: _validate_full_lastmatch())
        except Exception:
            pass

    grid_label(row, 'Affected Feeds:')
    row += 1
    
    # Place listbox and controls below the label in column 0-1 span
    affected_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=5, pady=4)
    affected_frame.columnconfigure(0, weight=1)  # Make frame expand
    
    # Listbox frame with better height
    affected_listbox_frame.pack(side='top', fill='both', expand=False, pady=(0, 8))
    affected_listbox.pack(side='left', fill='both', expand=True)
    affected_scrollbar.pack(side='right', fill='y')
    
    # Set a reasonable height for the listbox
    affected_listbox.configure(height=6)
    
    try:
        af = entry.get('affectedFeeds') if isinstance(entry, dict) else []
        if isinstance(af, list):
            affected_listbox.delete(0, 'end')
            for feed in af:
                affected_listbox.insert('end', feed)
    except Exception:
        pass
    try:
        config.load_cached_feeds()
        cached_feeds = getattr(config, 'CACHED_FEEDS', {}) or {}
    except Exception:
        cached_feeds = {}
    try:
        feeds_choices = []
        if isinstance(cached_feeds, dict):
            for k, v in cached_feeds.items():
                if isinstance(v, dict) and v.get('url'):
                    feeds_choices.append(f"{k} -> {v.get('url')}")
                else:
                    feeds_choices.append(str(k))
        elif isinstance(cached_feeds, list):
            for it in cached_feeds:
                if isinstance(it, dict) and it.get('url'):
                    feeds_choices.append(it.get('url'))
                else:
                    feeds_choices.append(str(it))
        else:
            feeds_choices = []
    except Exception:
        feeds_choices = []
    try:
        # Control frame for add/delete buttons
        feeds_select_frame = ttk.Frame(affected_frame)
        feeds_select_frame.pack(side='top', fill='x', pady=(0, 8))
        
        ttk.Label(feeds_select_frame, text='Add from cached feeds:', font=('Segoe UI', 9)).pack(side='left', padx=(0, 5))
        
        feeds_combo = ttk.Combobox(feeds_select_frame, values=feeds_choices, state='readonly', width=50)
        feeds_combo.pack(side='left', padx=(0, 5))
        
        def _add_selected_feed():
            try:
                val = feeds_combo.get().strip()
                if not val:
                    return
                if '->' in val:
                    val = val.split('->',1)[1].strip()
                current_items = affected_listbox.get(0, 'end')
                if val not in current_items:
                    affected_listbox.insert('end', val)
                    feeds_combo.set('')  # Clear selection after adding
            except Exception:
                pass
        
        def _delete_selected_feeds():
            try:
                selected = affected_listbox.curselection()
                if not selected:
                    messagebox.showwarning('Remove Feed', 'Please select one or more feeds to remove from the list above.')
                    return
                for idx in reversed(selected):
                    affected_listbox.delete(idx)
            except Exception as e:
                messagebox.showerror('Remove Error', f'Failed to remove feeds: {e}')
        
        ttk.Button(feeds_select_frame, text='➕ Add', command=_add_selected_feed, width=10).pack(side='left', padx=2)
        ttk.Button(feeds_select_frame, text='🗑️ Remove', command=_delete_selected_feeds, width=14).pack(side='left', padx=2)
    except Exception:
        pass
    row += 1

    grid_label(row, 'Assigned Category:')
    # Use Combobox with cached categories and allow manual editing
    try:
        config.load_cached_categories()
        cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
    except Exception:
        cached_cats = {}
    try:
        if isinstance(cached_cats, dict):
            cat_choices = list(cached_cats.keys())
        elif isinstance(cached_cats, list):
            cat_choices = cached_cats
        else:
            cat_choices = []
    except Exception:
        cat_choices = []
    
    # Add categories from current listbox items
    try:
        for title_text_item, entry_item in listbox_items:
            if isinstance(entry_item, dict):
                cat = entry_item.get('assignedCategory') or entry_item.get('assigned_category') or entry_item.get('category') or ''
                if cat and cat not in cat_choices:
                    cat_choices.append(str(cat))
    except Exception:
        pass
    
    assigned_combo = ttk.Combobox(frm, textvariable=assigned_var, values=sorted(cat_choices), width=48, font=('Segoe UI', 9))
    assigned_combo.grid(row=row, column=1, sticky='w', padx=5, pady=4)
    
    # Sync assigned_var with tp_category when either changes
    def _sync_assigned_to_tp(*args):
        try:
            tp_category.set(assigned_var.get())
        except Exception:
            pass
    
    def _sync_tp_to_assigned(*args):
        try:
            assigned_var.set(tp_category.get())
        except Exception:
            pass
    
    try:
        assigned_var.trace_add('write', _sync_assigned_to_tp)
        tp_category.trace_add('write', _sync_tp_to_assigned)
    except Exception:
        try:
            assigned_var.trace('w', _sync_assigned_to_tp)
            tp_category.trace('w', _sync_tp_to_assigned)
        except Exception:
            pass
    
    row += 1

    grid_label(row, 'Enabled:')
    ttk.Checkbutton(frm, variable=enabled_var, text='Enable this rule').grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    grid_label(row, 'Episode Filter:')
    ttk.Entry(frm, textvariable=episode_var, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    row += 1

    grid_label(row, 'Ignore Days:')
    ttk.Entry(frm, textvariable=ignore_var, width=10, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    grid_label(row, 'Last Match:')
    lastmatch_frame = ttk.Frame(frm)
    lastmatch_frame.grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    lastmatch_frame.columnconfigure(0, weight=1)
    ttk.Entry(lastmatch_frame, textvariable=lastmatch_var, font=('Segoe UI', 9)).grid(row=0, column=0, sticky='ew')
    try:
        lastmatch_full_status_label = tk.Label(lastmatch_frame, text='', fg='green')
        lastmatch_full_status_label.grid(row=0, column=1, sticky='w', padx=(8, 0))
    except Exception:
        lastmatch_full_status_label = None
    row += 1

    grid_label(row, 'Must Contain:')
    ttk.Entry(frm, textvariable=must_var, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    row += 1

    grid_label(row, 'Must Not Contain:')
    ttk.Entry(frm, textvariable=mustnot_var, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    row += 1

    grid_label(row, 'Previously Matched (one per line):')
    prevmatches_frame.grid(row=row, column=1, sticky='w')
    prevmatches_text.grid(row=0, column=0, sticky='w', padx=2, pady=6)
    try:
        pm = entry.get('previouslyMatchedEpisodes') if isinstance(entry, dict) else []
        if isinstance(pm, list):
            prevmatches_text.delete('1.0', 'end')
            prevmatches_text.insert('1.0', '\n'.join([str(x) for x in pm]))
    except Exception:
        pass
    row += 1

    grid_label(row, 'Priority:')
    ttk.Entry(frm, textvariable=priority_var, width=10, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    grid_label(row, 'Save Path:')
    savepath_entry = ttk.Entry(frm, textvariable=savepath_var, font=('Segoe UI', 9))
    savepath_entry.grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    
    row += 1

    grid_label(row, 'Smart Filter:')
    ttk.Checkbutton(frm, variable=smart_var, text='Enable smart filtering').grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    grid_label(row, 'Torrent Content Layout:')
    ttk.Entry(frm, textvariable=tcl_var, font=('Segoe UI', 9)).grid(row=row, column=1, sticky='ew', padx=5, pady=4)
    row += 1

    ttk.Separator(frm, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=15)
    row += 1

    # torrentParams section with better styling
    ttk.Label(frm, text='🔧 Torrent Parameters', font=('Segoe UI', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
    
    tp_frame = ttk.LabelFrame(frm, text='', padding=10)
    tp_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=4)
    tp_frame.columnconfigure(1, weight=1)
    tp_row = 0
    
    ttk.Label(tp_frame, text='category:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    tp_category_combo = ttk.Combobox(tp_frame, textvariable=tp_category, values=sorted(cat_choices), font=('Segoe UI', 9))
    tp_category_combo.grid(row=tp_row, column=1, sticky='ew', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='download_limit:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_download_limit, width=10, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='download_path:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_download_path, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='ew', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='inactive_seeding_time_limit:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_inactive_limit, width=10, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='operating_mode:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_operating_mode, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='ew', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='ratio_limit:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_ratio_limit, width=10, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='save_path:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    tp_save_path_entry = ttk.Entry(tp_frame, textvariable=tp_save_path, font=('Segoe UI', 9))
    tp_save_path_entry.grid(row=tp_row, column=1, sticky='ew', padx=5, pady=4)
    
    tp_row += 1

    ttk.Label(tp_frame, text='seeding_time_limit:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_seeding_time, width=10, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='skip_checking:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Checkbutton(tp_frame, variable=tp_skip, text='Skip hash checking').grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='tags (comma separated):', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_tags, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='ew', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='upload_limit:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Entry(tp_frame, textvariable=tp_upload_limit, width=10, font=('Segoe UI', 9)).grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    ttk.Label(tp_frame, text='use_auto_tmm:', font=('Segoe UI', 9, 'bold')).grid(row=tp_row, column=0, sticky='w', padx=5, pady=4)
    ttk.Checkbutton(tp_frame, variable=tp_auto_tmm, text='Use automatic torrent management').grid(row=tp_row, column=1, sticky='w', padx=5, pady=4)
    tp_row += 1

    row += 1

    ttk.Separator(frm, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=15)
    row += 1

    grid_label(row, 'Use Regex:')
    ttk.Checkbutton(frm, variable=useregex_var, text='Enable regex matching').grid(row=row, column=1, sticky='w', padx=5, pady=4)
    row += 1

    # Footer buttons are defined at the end after _apply_full function

    def _apply_full():
        try:
            new_rule = {}
            ap = addPaused_var.get()
            if ap == 'None':
                new_rule['addPaused'] = None
            elif ap == 'True':
                new_rule['addPaused'] = True
            else:
                new_rule['addPaused'] = False

            feeds_raw = affected_listbox.get(0, 'end')
            new_rule['affectedFeeds'] = [f.strip() for f in feeds_raw if f.strip()]
            new_rule['assignedCategory'] = assigned_var.get().strip()
            new_rule['enabled'] = bool(enabled_var.get())
            new_rule['episodeFilter'] = episode_var.get().strip()
            try:
                new_rule['ignoreDays'] = int(ignore_var.get())
            except Exception:
                new_rule['ignoreDays'] = 0
            try:
                lm_txt = lastmatch_var.get().strip()
                if lm_txt:
                    if lm_txt.startswith('{') or lm_txt.startswith('[') or lm_txt.startswith('"'):
                        try:
                            new_rule['lastMatch'] = json.loads(lm_txt)
                        except Exception as e:
                            try:
                                if not messagebox.askyesno('Invalid JSON', f'Last Match appears to be JSON but is invalid:\n{e}\n\nApply as raw text anyway?'):
                                    return
                            except Exception:
                                return
                            new_rule['lastMatch'] = lm_txt
                    else:
                        new_rule['lastMatch'] = lm_txt
                else:
                    new_rule['lastMatch'] = ''
            except Exception:
                try:
                    new_rule['lastMatch'] = lastmatch_var.get().strip()
                except Exception:
                    new_rule['lastMatch'] = ''
            new_rule['mustContain'] = must_var.get().strip()
            new_rule['mustNotContain'] = mustnot_var.get().strip()
            pm_raw = prevmatches_text.get('1.0', 'end').strip()
            new_rule['previouslyMatchedEpisodes'] = [l.strip() for l in pm_raw.splitlines() if l.strip()]
            try:
                new_rule['priority'] = int(priority_var.get())
            except Exception:
                new_rule['priority'] = 0

            sp = savepath_var.get().strip()
            if not sp:
                if not messagebox.askyesno('Validation', 'Save Path is empty. Do you want to continue without a save path?'):
                    return
            else:
                try:
                    if len(sp) > 260 and not messagebox.askyesno('Validation Warning', 'Save Path is unusually long. Continue?'):
                        return
                except Exception:
                    pass
            new_rule['savePath'] = sp.replace('/', '\\')
            new_rule['smartFilter'] = bool(smart_var.get())
            new_rule['torrentContentLayout'] = None if not tcl_var.get().strip() else tcl_var.get().strip()
            new_rule['useRegex'] = bool(useregex_var.get())

            tp_new = {}
            tp_new['category'] = tp_category.get().strip()
            try:
                tp_new['download_limit'] = int(tp_download_limit.get())
            except Exception:
                tp_new['download_limit'] = -1
            tp_new['download_path'] = tp_download_path.get().strip()
            try:
                tp_new['inactive_seeding_time_limit'] = int(tp_inactive_limit.get())
            except Exception:
                tp_new['inactive_seeding_time_limit'] = -2
            tp_new['operating_mode'] = tp_operating_mode.get().strip() or 'AutoManaged'
            try:
                tp_new['ratio_limit'] = int(tp_ratio_limit.get())
            except Exception:
                tp_new['ratio_limit'] = -2
            tp_new['save_path'] = tp_save_path.get().strip().replace('\\', '/')
            try:
                tp_new['seeding_time_limit'] = int(tp_seeding_time.get())
            except Exception:
                tp_new['seeding_time_limit'] = -2
            tp_new['skip_checking'] = bool(tp_skip.get())
            tags_val = [t.strip() for t in tp_tags.get().split(',') if t.strip()]
            tp_new['tags'] = tags_val
            try:
                tp_new['upload_limit'] = int(tp_upload_limit.get())
            except Exception:
                tp_new['upload_limit'] = -1
            tp_new['use_auto_tmm'] = bool(tp_auto_tmm.get())
            new_rule['torrentParams'] = tp_new

            # Get the new rule title
            new_title = rule_title_var.get().strip()
            if not new_title:
                messagebox.showerror('Validation Error', 'Rule Title cannot be empty.')
                return
            
            # Preserve or create node structure with the title
            node = entry.get('node') if isinstance(entry, dict) else {}
            if not isinstance(node, dict):
                node = {}
            node['title'] = new_title
            new_rule['node'] = node

            listbox_items[idx] = (new_title, new_rule)
            try:
                if getattr(config, 'ALL_TITLES', None):
                    for k, lst in (config.ALL_TITLES.items() if isinstance(config.ALL_TITLES, dict) else []):
                        for i, it in enumerate(lst):
                            try:
                                candidate_title = (it.get('node') or {}).get('title') if isinstance(it, dict) else str(it)
                            except Exception:
                                candidate_title = str(it)
                            if candidate_title == title_text:
                                config.ALL_TITLES[k][i] = new_rule
                                raise StopIteration
            except StopIteration:
                pass

            try:
                adapter = TreeviewAdapter(treeview_widget)
                adapter.update_title_at_index(idx, new_title)
                adapter.set_selection_indices([idx])
                adapter.see_index(idx)
            except Exception:
                pass

            dlg.destroy()
            # Auto-refresh the editor to show updated values
            if populate_editor_callback:
                try:
                    populate_editor_callback()
                except Exception:
                    pass
            messagebox.showinfo('Edit', 'Full settings applied.')
        except Exception as e:
            messagebox.showerror('Apply Error', f'Failed to apply full settings: {e}')

    ttk.Button(footer, text='✓ Apply', command=_apply_full, style='Accent.TButton', width=12).pack(side='right', padx=5)
    ttk.Button(footer, text='✕ Cancel', command=dlg.destroy, width=12).pack(side='right')


def open_bulk_edit_dialog(root: tk.Tk, selected_items: List[tuple], 
                          apply_callback: callable, status_var: tk.StringVar) -> None:
    """
    Opens a bulk edit dialog for editing multiple selected rules at once.
    
    Args:
        root: Parent Tkinter window
        selected_items: List of (title, entry) tuples for selected items
        apply_callback: Callback function to apply changes
        status_var: Status bar variable for feedback
    """
    if not selected_items:
        messagebox.showwarning('Bulk Edit', 'No items selected.')
        return
    
    dlg = tk.Toplevel(root)
    dlg.title(f"📝 Bulk Edit - {len(selected_items)} items selected")
    dlg.geometry("600x400")
    dlg.minsize(500, 350)
    dlg.transient(root)
    dlg.grab_set()
    dlg.configure(bg='#f5f5f5')
    
    center_window(dlg)
    
    # Main frame
    main_frame = ttk.Frame(dlg, padding=20)
    main_frame.pack(fill='both', expand=True)
    
    # Info label
    ttk.Label(main_frame, text=f"Editing {len(selected_items)} selected rules", 
              font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 15))
    
    ttk.Label(main_frame, text="Check the fields you want to update for all selected items:",
              font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 10))
    
    # Fields frame
    fields_frame = ttk.Frame(main_frame)
    fields_frame.pack(fill='both', expand=True, pady=10)
    
    # Category field
    category_enabled = tk.BooleanVar(value=False)
    category_var = tk.StringVar(value='')
    
    category_frame = ttk.Frame(fields_frame)
    category_frame.pack(fill='x', pady=8)
    
    ttk.Checkbutton(category_frame, text="Category:", variable=category_enabled,
                   width=12).pack(side='left')
    category_combo = ttk.Combobox(category_frame, textvariable=category_var, 
                                 font=('Segoe UI', 9), state='normal')
    category_combo.pack(side='left', fill='x', expand=True, padx=(5, 0))
    
    # Populate category dropdown from cached categories
    try:
        cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
        if isinstance(cached_cats, dict):
            category_combo['values'] = sorted(cached_cats.keys())
    except Exception:
        pass
    
    # Save Path field
    savepath_enabled = tk.BooleanVar(value=False)
    savepath_var = tk.StringVar(value='')
    
    savepath_frame = ttk.Frame(fields_frame)
    savepath_frame.pack(fill='x', pady=8)
    
    ttk.Checkbutton(savepath_frame, text="Save Path:", variable=savepath_enabled,
                   width=12).pack(side='left')
    savepath_entry = ttk.Entry(savepath_frame, textvariable=savepath_var,
                              font=('Segoe UI', 9))
    savepath_entry.pack(side='left', fill='x', expand=True, padx=(5, 0))
    
    # Keep save path independent from category selection
    def _on_category_change(*args):
        return
    
    category_var.trace_add('write', _on_category_change)
    
    # Enabled field
    enabled_enabled = tk.BooleanVar(value=False)
    enabled_var = tk.BooleanVar(value=True)
    
    enabled_frame = ttk.Frame(fields_frame)
    enabled_frame.pack(fill='x', pady=8)
    
    ttk.Checkbutton(enabled_frame, text="Enabled:", variable=enabled_enabled,
                   width=12).pack(side='left')
    ttk.Checkbutton(enabled_frame, text="Enable rules", variable=enabled_var).pack(side='left', padx=(5, 0))
    
    # Separator
    ttk.Separator(fields_frame, orient='horizontal').pack(fill='x', pady=15)
    
    # Summary frame
    summary_frame = ttk.Frame(fields_frame)
    summary_frame.pack(fill='x', pady=5)
    
    summary_label = ttk.Label(summary_frame, text="", 
                             font=('Segoe UI', 9), foreground='#666')
    summary_label.pack(anchor='w')
    
    def _update_summary(*args):
        changes = []
        if category_enabled.get():
            changes.append(f"Category → '{category_var.get()}'")
        if savepath_enabled.get():
            changes.append(f"Save Path → '{savepath_var.get()}'")
        if enabled_enabled.get():
            changes.append(f"Enabled → {'Yes' if enabled_var.get() else 'No'}")
        
        if changes:
            summary_label.config(text="Will update: " + ", ".join(changes))
        else:
            summary_label.config(text="No changes selected")
    
    category_enabled.trace_add('write', _update_summary)
    savepath_enabled.trace_add('write', _update_summary)
    enabled_enabled.trace_add('write', _update_summary)
    category_var.trace_add('write', _update_summary)
    savepath_var.trace_add('write', _update_summary)
    enabled_var.trace_add('write', _update_summary)
    
    _update_summary()
    
    # Footer with buttons
    footer = ttk.Frame(dlg, padding=(20, 10))
    footer.pack(fill='x', side='bottom')
    
    def _apply_bulk_changes():
        """Apply bulk changes to all selected items."""
        try:
            # Check if any fields are enabled
            if not (category_enabled.get() or savepath_enabled.get() or enabled_enabled.get()):
                messagebox.showwarning('Bulk Edit', 'No fields selected to update.')
                return
            
            # Confirm with user
            changes_text = []
            if category_enabled.get():
                changes_text.append(f"• Category: '{category_var.get()}'")
            if savepath_enabled.get():
                changes_text.append(f"• Save Path: '{savepath_var.get()}'")
            if enabled_enabled.get():
                changes_text.append(f"• Enabled: {'Yes' if enabled_var.get() else 'No'}")
            
            confirm_msg = f"Update {len(selected_items)} selected rules with:\n\n" + "\n".join(changes_text)
            
            if not messagebox.askyesno('Confirm Bulk Edit', confirm_msg):
                return
            
            # Prepare changes dict
            changes = {}
            if category_enabled.get():
                changes['category'] = category_var.get().strip()
            if savepath_enabled.get():
                changes['save_path'] = savepath_var.get().strip()
            if enabled_enabled.get():
                changes['enabled'] = enabled_var.get()
            
            # Apply changes via callback
            success_count = apply_callback(selected_items, changes)
            
            dlg.destroy()
            
            if success_count > 0:
                status_var.set(f'Bulk edit applied to {success_count} rules')
                messagebox.showinfo('Bulk Edit', f'Successfully updated {success_count} rules.')
            else:
                messagebox.showwarning('Bulk Edit', 'No rules were updated.')
                
        except Exception as e:
            logger.error(f"Bulk edit error: {e}", exc_info=True)
            messagebox.showerror('Bulk Edit Error', f'Failed to apply bulk changes: {e}')
    
    ttk.Button(footer, text='✓ Apply to All', command=_apply_bulk_changes, 
              style='Accent.TButton', width=15).pack(side='right', padx=5)
    ttk.Button(footer, text='✕ Cancel', command=dlg.destroy, width=12).pack(side='right')


def open_template_dialog(root: tk.Tk, apply_callback=None, current_rule_data: Dict[str, Any] = None) -> None:
    """
    Opens the template management dialog.
    
    Allows users to view, apply, create, edit, and delete rule templates.
    
    Args:
        root: Parent Tkinter window
        apply_callback: Function to call when applying a template, signature: callback(template_data) -> bool
        current_rule_data: Optional dict with current rule data for creating new templates
    """
    from src.cache import load_templates, save_templates, add_template, delete_template, initialize_default_templates
    
    # Initialize default templates if none exist
    initialize_default_templates()
    
    dlg = tk.Toplevel(root)
    dlg.title("📋 Rule Templates")
    dlg.geometry("900x650")
    dlg.minsize(700, 500)
    dlg.transient(root)
    dlg.grab_set()
    dlg.configure(bg='#f5f5f5')
    center_window(dlg, root)
    
    # Main container
    main_frame = ttk.Frame(dlg, padding=20)
    main_frame.pack(fill='both', expand=True)
    
    # Title
    title_label = ttk.Label(main_frame, text="Rule Templates", 
                           font=get_ui_font(size_delta=7, weight='bold'))
    title_label.pack(pady=(0, 15))
    
    # Content area (list + preview)
    content_frame = ttk.Frame(main_frame)
    content_frame.pack(fill='both', expand=True, pady=(0, 15))
    
    # Left side - Template list
    list_frame = ttk.LabelFrame(content_frame, text="Templates", padding=10)
    list_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
    
    # Listbox with scrollbar
    list_scroll = ttk.Scrollbar(list_frame, orient='vertical')
    template_listbox = tk.Listbox(list_frame, yscrollcommand=list_scroll.set,
                                  font=get_ui_font(size_delta=1), height=20)
    list_scroll.config(command=template_listbox.yview)
    list_scroll.pack(side='right', fill='y')
    template_listbox.pack(side='left', fill='both', expand=True)
    
    # Right side - Preview pane
    preview_frame = ttk.LabelFrame(content_frame, text="Preview", padding=10)
    preview_frame.pack(side='right', fill='both', expand=True)
    
    # Preview text widget with scrollbar
    preview_scroll = ttk.Scrollbar(preview_frame, orient='vertical')
    preview_text = tk.Text(preview_frame, yscrollcommand=preview_scroll.set,
                          font=('Consolas', 9), wrap='word', height=20, width=40)
    preview_scroll.config(command=preview_text.yview)
    preview_scroll.pack(side='right', fill='y')
    preview_text.pack(side='left', fill='both', expand=True)
    preview_text.config(state='disabled')  # Read-only
    
    # Template data storage
    templates = {}
    
    def refresh_template_list(selected_name: str = None):
        """Refresh the template list and keep selection when possible."""
        nonlocal templates
        templates = load_templates()

        template_listbox.delete(0, tk.END)
        sorted_names = sorted(templates.keys())
        for name in sorted_names:
            template_listbox.insert(tk.END, name)

        if template_listbox.size() > 0:
            if selected_name and selected_name in sorted_names:
                selected_idx = sorted_names.index(selected_name)
            else:
                selected_idx = 0
            template_listbox.selection_clear(0, tk.END)
            template_listbox.selection_set(selected_idx)
            template_listbox.see(selected_idx)
            update_preview()
    
    def update_preview(event=None):
        """Update the preview pane with selected template."""
        selection = template_listbox.curselection()
        if not selection:
            preview_text.config(state='normal')
            preview_text.delete('1.0', tk.END)
            preview_text.config(state='disabled')
            return
        
        template_name = template_listbox.get(selection[0])
        template_data = templates.get(template_name, {})
        
        # Format preview
        preview_content = f"Template: {template_name}\n"
        preview_content += "=" * 50 + "\n\n"
        
        if 'description' in template_data:
            preview_content += f"Description:\n  {template_data['description']}\n\n"
        
        preview_content += "Settings:\n"
        for key, value in template_data.items():
            if key == 'description':
                continue
            preview_content += f"  {key}: {value}\n"
        
        preview_text.config(state='normal')
        preview_text.delete('1.0', tk.END)
        preview_text.insert('1.0', preview_content)
        preview_text.config(state='disabled')
    
    template_listbox.bind('<<ListboxSelect>>', update_preview)
    
    def apply_template():
        """Apply the selected template."""
        selection = template_listbox.curselection()
        if not selection:
            messagebox.showwarning('No Selection', 'Please select a template to apply.')
            return
        
        template_name = template_listbox.get(selection[0])
        template_data = templates.get(template_name, {})
        
        if apply_callback:
            try:
                # Remove description from data passed to callback
                data_to_apply = {k: v for k, v in template_data.items() if k != 'description'}
                success = apply_callback(data_to_apply)
                if success:
                    messagebox.showinfo('Template Applied', f'Template "{template_name}" applied successfully.')
                    dlg.destroy()
                else:
                    messagebox.showerror('Apply Failed', 'Failed to apply template.')
            except Exception as e:
                logger.error(f"Error applying template: {e}", exc_info=True)
                messagebox.showerror('Error', f'Failed to apply template: {e}')
        else:
            messagebox.showinfo('Template Data', f'Template "{template_name}" selected.\n\nData:\n{template_data}')
    
    def create_new_template(edit_name: str = None, edit_data: Dict[str, Any] = None):
        """Create a new template or edit an existing one."""
        is_edit_mode = bool(edit_name)
        create_win = tk.Toplevel(dlg)
        create_win.title("Edit Template" if is_edit_mode else "Create New Template")
        create_win.geometry("500x600")
        create_win.transient(dlg)
        create_win.grab_set()
        center_window(create_win, dlg)
        
        form_frame = ttk.Frame(create_win, padding=20)
        form_frame.pack(fill='both', expand=True)
        
        ttk.Label(form_frame, text="Edit Template" if is_edit_mode else "Create New Template", 
                 font=('Segoe UI', 14, 'bold')).pack(pady=(0, 20))
        
        # Template name
        ttk.Label(form_frame, text="Template Name:").pack(anchor='w', pady=(5, 2))
        name_entry = ttk.Entry(form_frame, width=50)
        name_entry.pack(fill='x', pady=(0, 10))
        
        # Description
        ttk.Label(form_frame, text="Description:").pack(anchor='w', pady=(5, 2))
        desc_entry = ttk.Entry(form_frame, width=50)
        desc_entry.pack(fill='x', pady=(0, 10))
        
        # Category
        ttk.Label(form_frame, text="Category:").pack(anchor='w', pady=(5, 2))
        category_entry = ttk.Entry(form_frame, width=50)
        category_entry.pack(fill='x', pady=(0, 10))
        
        # Save Path
        ttk.Label(form_frame, text="Save Path:").pack(anchor='w', pady=(5, 2))
        savepath_entry = ttk.Entry(form_frame, width=50)
        savepath_entry.pack(fill='x', pady=(0, 10))
        
        # Must Contain
        ttk.Label(form_frame, text="Must Contain:").pack(anchor='w', pady=(5, 2))
        must_contain_entry = ttk.Entry(form_frame, width=50)
        must_contain_entry.pack(fill='x', pady=(0, 10))
        
        # Must Not Contain
        ttk.Label(form_frame, text="Must Not Contain:").pack(anchor='w', pady=(5, 2))
        must_not_contain_entry = ttk.Entry(form_frame, width=50)
        must_not_contain_entry.pack(fill='x', pady=(0, 10))
        
        # Episode Filter
        ttk.Label(form_frame, text="Episode Filter:").pack(anchor='w', pady=(5, 2))
        episode_filter_entry = ttk.Entry(form_frame, width=50)
        episode_filter_entry.pack(fill='x', pady=(0, 10))
        
        # Enabled checkbox
        enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form_frame, text="Enabled by default", 
                       variable=enabled_var).pack(anchor='w', pady=(5, 10))
        
        # Use Regex checkbox
        use_regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form_frame, text="Use Regular Expression", 
                       variable=use_regex_var).pack(anchor='w', pady=(0, 10))
        
        # Pre-fill fields for edit mode or save-as-template mode.
        prefill_data = edit_data if isinstance(edit_data, dict) else current_rule_data
        if is_edit_mode and edit_name:
            name_entry.insert(0, edit_name)
        if prefill_data:
            desc_entry.insert(0, prefill_data.get('description', ''))
            category_entry.insert(0, prefill_data.get('category', ''))
            savepath_entry.insert(0, prefill_data.get('save_path', ''))
            must_contain_entry.insert(0, prefill_data.get('must_contain', ''))
            must_not_contain_entry.insert(0, prefill_data.get('must_not_contain', ''))
            episode_filter_entry.insert(0, prefill_data.get('episode_filter', ''))
            enabled_var.set(prefill_data.get('enabled', True))
            use_regex_var.set(prefill_data.get('use_regex', False))
        
        def save_new_template():
            """Save the new or edited template."""
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning('Invalid Name', 'Please enter a template name.')
                return

            template_data = {
                'description': desc_entry.get().strip(),
                'category': category_entry.get().strip(),
                'save_path': savepath_entry.get().strip(),
                'must_contain': must_contain_entry.get().strip(),
                'must_not_contain': must_not_contain_entry.get().strip(),
                'episode_filter': episode_filter_entry.get().strip(),
                'enabled': enabled_var.get(),
                'use_regex': use_regex_var.get(),
            }

            if is_edit_mode:
                all_templates = load_templates()
                if name != edit_name and name in all_templates:
                    if not messagebox.askyesno('Overwrite Template',
                                               f'Template "{name}" already exists. Overwrite?'):
                        return
                if edit_name and edit_name in all_templates and name != edit_name:
                    del all_templates[edit_name]
                all_templates[name] = template_data
                if save_templates(all_templates):
                    messagebox.showinfo('Success', f'Template "{name}" updated successfully.')
                    create_win.destroy()
                    refresh_template_list(selected_name=name)
                else:
                    messagebox.showerror('Error', 'Failed to update template.')
            else:
                if name in templates:
                    if not messagebox.askyesno('Overwrite Template',
                                               f'Template "{name}" already exists. Overwrite?'):
                        return
                if add_template(name, template_data):
                    messagebox.showinfo('Success', f'Template "{name}" saved successfully.')
                    create_win.destroy()
                    refresh_template_list(selected_name=name)
                else:
                    messagebox.showerror('Error', 'Failed to save template.')
        
        # Buttons
        btn_frame = ttk.Frame(form_frame)
        btn_frame.pack(fill='x', pady=(15, 0))
        
        ttk.Button(btn_frame, text='✓ Save Template', command=save_new_template,
                  style='Accent.TButton', width=15).pack(side='right', padx=5)
        ttk.Button(btn_frame, text='✕ Cancel', command=create_win.destroy,
                  width=12).pack(side='right')
    
    def edit_template():
        """Edit the selected template."""
        selection = template_listbox.curselection()
        if not selection:
            messagebox.showwarning('No Selection', 'Please select a template to edit.')
            return
        
        template_name = template_listbox.get(selection[0])
        template_data = templates.get(template_name, {})

        create_new_template(edit_name=template_name, edit_data=template_data)
    
    def delete_selected_template():
        """Delete the selected template."""
        selection = template_listbox.curselection()
        if not selection:
            messagebox.showwarning('No Selection', 'Please select a template to delete.')
            return
        
        template_name = template_listbox.get(selection[0])
        
        if not messagebox.askyesno('Confirm Delete', 
                                   f'Delete template "{template_name}"?'):
            return
        
        if delete_template(template_name):
            messagebox.showinfo('Deleted', f'Template "{template_name}" deleted.')
            refresh_template_list()
        else:
            messagebox.showerror('Error', 'Failed to delete template.')
    
    # Button panel
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill='x', pady=(0, 0))
    
    ttk.Button(button_frame, text='✓ Apply Template', command=apply_template,
              style='Accent.TButton', width=15).pack(side='left', padx=5)
    ttk.Button(button_frame, text='+ New Template', command=create_new_template,
              width=15).pack(side='left', padx=5)
    ttk.Button(button_frame, text='✎ Edit Template', command=edit_template,
              width=15).pack(side='left', padx=5)
    ttk.Button(button_frame, text='🗑 Delete', command=delete_selected_template,
              width=12).pack(side='left', padx=5)
    ttk.Button(button_frame, text='✕ Close', command=dlg.destroy,
              width=12).pack(side='right', padx=5)
    
    # Load templates
    refresh_template_list()


def open_sonarr_export_dialog(root: tk.Tk, titles_to_export: List[str]) -> None:
    """
    Opens the Sonarr export dialog to bulk-add series.
    
    Args:
        root: Parent Tkinter window
        titles_to_export: List of anime titles to add to Sonarr
    """
    return
    """
    # Load quality profiles and root folders
    quality_profiles = []
    root_folders = []
    
    def load_settings():
        nonlocal quality_profiles, root_folders
        try:
            status_var.set("Loading Sonarr settings...")
            dlg.update()
            
            # Get quality profiles
            quality_profiles = sonarr.get_quality_profiles(url_var.get(), api_key_var.get())
            profile_names = [p['name'] for p in quality_profiles]
            quality_combo['values'] = profile_names
            if profile_names:
                quality_combo.current(0)
            
            # Get root folders
            root_folders = sonarr.get_root_folders(url_var.get(), api_key_var.get())
            folder_paths = [f['path'] for f in root_folders]
            root_folder_combo['values'] = folder_paths
            if folder_paths:
                root_folder_combo.current(0)
            
            status_var.set(f"Loaded {len(quality_profiles)} profiles, {len(root_folders)} folders")
        except Exception as e:
            status_var.set(f"Failed to load settings: {e}")
            messagebox.showerror('Settings Error', f'Failed to load Sonarr settings:\n\n{e}')
    
    load_settings_btn = ttk.Button(settings_frame, text='↻ Load Settings', command=load_settings)
    load_settings_btn.grid(row=0, column=2, padx=(10, 0))
    
    # Series matching frame
    matching_frame = ttk.LabelFrame(main_frame, text="Series Matching", padding=10)
    matching_frame.pack(fill='both', expand=True, pady=(0, 15))
    
    # Treeview for series matching
    columns = ('title', 'status', 'match')
    tree = ttk.Treeview(matching_frame, columns=columns, show='headings', height=15)
    tree.heading('title', text='Title')
    tree.heading('status', text='Status')
    tree.heading('match', text='Sonarr Match')
    tree.column('title', width=250)
    tree.column('status', width=100)
    tree.column('match', width=400)
    
    # Scrollbar
    scrollbar = ttk.Scrollbar(matching_frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)
    
    # Store series matches
    series_matches = {}  # title -> sonarr series data
    
    # Populate tree
    for title in titles_to_export:
        tree.insert('', 'end', values=(title, 'Pending', ''))
    
    # Search for series
    def search_all_series():
        status_var.set("Searching for series in Sonarr...")
        dlg.update()
        
        matches_found = 0
        for item in tree.get_children():
            title = tree.item(item, 'values')[0]
            try:
                results = sonarr.search_series(url_var.get(), api_key_var.get(), title)
                if results:
                    # Use first match
                    match = results[0]
                    series_matches[title] = match
                    match_text = f"{match.get('title')} ({match.get('year', 'N/A')})"
                    tree.item(item, values=(title, '✓ Found', match_text))
                    tree.item(item, tags=('found',))
                    matches_found += 1
                else:
                    tree.item(item, values=(title, '✗ Not Found', 'No matches'))
                    tree.item(item, tags=('not_found',))
            except Exception as e:
                tree.item(item, values=(title, '✗ Error', str(e)))
                tree.item(item, tags=('error',))
            
            dlg.update()
        
        tree.tag_configure('found', foreground='green')
        tree.tag_configure('not_found', foreground='red')
        tree.tag_configure('error', foreground='orange')
        
        status_var.set(f"Found matches for {matches_found}/{len(titles_to_export)} series")
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill='x')
    
    ttk.Button(button_frame, text='🔍 Search for Series', command=search_all_series).pack(side='left', padx=5)
    
    def add_to_sonarr():
        if not series_matches:
            messagebox.showwarning('No Matches', 'Please search for series first.')
            return
        
        # Get selected quality profile and root folder
        quality_name = quality_var.get()
        quality_id = next((p['id'] for p in quality_profiles if p['name'] == quality_name), None)
        
        root_folder = root_folder_var.get()
        
        if not quality_id or not root_folder:
            messagebox.showwarning('Settings Required', 'Please select quality profile and root folder.')
            return
        
        # Confirm
        if not messagebox.askyesno('Confirm Add', 
                                   f'Add {len(series_matches)} series to Sonarr?\n\n' +
                                   f'Quality: {quality_name}\n' +
                                   f'Folder: {root_folder}\n' +
                                   f'Monitor: {monitor_var.get()}'):
            return
        
        # Add series
        status_var.set("Adding series to Sonarr...")
        dlg.update()
        
        results = sonarr.bulk_add_series(
            url_var.get(), api_key_var.get(),
            list(series_matches.values()),
            quality_id, root_folder,
            monitor_var.get(), search_var.get()
        )
        
        # Update tree with results
        for item in tree.get_children():
            title = tree.item(item, 'values')[0]
            if title in results['success']:
                tree.item(item, values=(title, '✓ Added', tree.item(item, 'values')[2]))
                tree.item(item, tags=('added',))
            elif any(title in f for f in results['failed']):
                error = next(f for f in results['failed'] if title in f)
                tree.item(item, values=(title, '✗ Failed', error))
                tree.item(item, tags=('failed',))
        
        tree.tag_configure('added', foreground='blue')
        tree.tag_configure('failed', foreground='red')
        
        status_var.set(f"Added {len(results['success'])} series, {len(results['failed'])} failed")
        
        # Save settings
        config.save_sonarr_config(
            url_var.get(), api_key_var.get(),
            quality_id, root_folder,
            monitor_var.get(), search_var.get()
        )
        
        messagebox.showinfo('Sonarr Export Complete', 
                           f"Successfully added {len(results['success'])} series to Sonarr.\n\n" +
                           (f"Failed: {len(results['failed'])}" if results['failed'] else ""))
    
    ttk.Button(button_frame, text='✓ Add to Sonarr', command=add_to_sonarr,
              style='Accent.TButton').pack(side='left', padx=5)
    ttk.Button(button_frame, text='✕ Close', command=dlg.destroy).pack(side='right', padx=5)
"""

def _build_target_export_payload(target: str, rules_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Build an export payload for a specific target platform."""
    target_norm = str(target).strip().lower()

    if target_norm == 'qbittorrent':
        return rules_dict

    rule_items: List[Dict[str, Any]] = []
    for rule_name, rule in (rules_dict or {}).items():
        rule_items.append({
            'name': rule_name,
            'enabled': bool(rule.get('enabled', True)),
            'must_contain': rule.get('mustContain', ''),
            'must_not_contain': rule.get('mustNotContain', ''),
            'save_path': rule.get('savePath', ''),
            'category': rule.get('assignedCategory', ''),
            'affected_feeds': rule.get('affectedFeeds', []),
            'torrent_params': rule.get('torrentParams', {}),
        })

    return {
        'target': target_norm,
        'version': '1.0',
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'rule_count': len(rule_items),
        'rules': rule_items,
    }


def open_multi_target_export_dialog(
    root: tk.Tk,
    titles_to_export: List[str],
    entries_to_export: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Open a multi-target export dialog for qBittorrent and Autobrr.

    Args:
        root: Parent Tkinter window
        titles_to_export: Display titles used by export workflows
        entries_to_export: Optional selected entries for rule export payload generation
    """
    from src.services.rules import build_rules_from_titles

    supported_targets = ['qbittorrent', 'autobrr']
    default_targets = getattr(config, 'EXPORT_TARGETS', ['qbittorrent']) or ['qbittorrent']

    dlg = tk.Toplevel(root)
    dlg.title('Export to Targets')
    dlg.geometry('520x370')
    dlg.resizable(False, False)
    dlg.transient(root)
    dlg.grab_set()
    center_window(dlg, root)

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)

    ttk.Label(frame, text='Export Targets', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Choose one or more destinations for this export action.',
              font=('Segoe UI', 9)).pack(anchor='w', pady=(4, 10))

    target_vars: Dict[str, tk.BooleanVar] = {}
    label_map = {
        'qbittorrent': 'qBittorrent (rules JSON)',
        'autobrr': 'Autobrr (portable JSON)',
    }

    for target in supported_targets:
        var = tk.BooleanVar(value=(target in default_targets))
        target_vars[target] = var
        ttk.Checkbutton(frame, text=label_map[target], variable=var).pack(anchor='w', pady=3)

    status_var = tk.StringVar(value=f"Ready to export {len(titles_to_export)} title(s).")
    ttk.Label(frame, textvariable=status_var, font=('Segoe UI', 8), foreground='#555').pack(anchor='w', pady=(12, 6))

    def _selected_targets() -> List[str]:
        return [name for name, var in target_vars.items() if bool(var.get())]

    def _export_file_targets(targets: List[str]) -> None:
        export_entries = entries_to_export if entries_to_export is not None else []
        if not export_entries:
            # Fallback to all data if no explicit selection was supplied.
            data = getattr(config, 'ALL_TITLES', None) or {}
            rules_dict = build_rules_from_titles(data) if data else {}
        else:
            rules_dict = build_rules_from_titles({'anime': export_entries})

        if not rules_dict:
            messagebox.showwarning('Export', 'No rules available to export.', parent=dlg)
            return

        for target in targets:
            payload = _build_target_export_payload(target, rules_dict)
            default_name = f"{target}_rules_export.json"
            save_path = filedialog.asksaveasfilename(
                parent=dlg,
                title=f'Export for {target}',
                initialfile=default_name,
                defaultextension='.json',
                filetypes=[('JSON', '*.json')],
            )
            if not save_path:
                continue

            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

    def _do_export() -> None:
        targets = _selected_targets()
        if not targets:
            messagebox.showwarning('Export', 'Select at least one target.', parent=dlg)
            return

        # Persist user defaults for future exports.
        try:
            config.save_platform_config(getattr(config, 'MAIN_SERVER', 'qbittorrent'), targets)
        except Exception:
            pass

        try:
            status_var.set('Exporting JSON payload(s)...')
            dlg.update_idletasks()
            _export_file_targets(targets)

            dlg.destroy()
        except Exception as e:
            messagebox.showerror('Export Error', f'Failed to export target payloads: {e}', parent=dlg)

    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill='x', side='bottom', pady=(10, 0))
    ttk.Button(btn_frame, text='Export', command=_do_export, style='Accent.TButton').pack(side='left')
    ttk.Button(btn_frame, text='Cancel', command=dlg.destroy).pack(side='right')
