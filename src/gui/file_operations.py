"""
File operations for import/export functionality.

Handles importing titles from files/clipboard and exporting rules to JSON.

Internal Format Filtering:
    When entries are stored in config.ALL_TITLES, they use a hybrid format containing
    both qBittorrent fields and internal tracking fields:
    - 'node': {'title': 'Display Title'} - for GUI display
    - 'ruleName': 'Title' - original rule name from qBittorrent
    
    These internal fields MUST be filtered out before:
    - Exporting to JSON files (see: export_titles_to_file)
    - Previewing rules (see: _show_preview_dialog)
    - Syncing to qBittorrent API
    
    The filtering is done using utils.strip_internal_fields() and
    utils.strip_internal_fields_from_titles() helper functions.
"""
# Standard library imports
import csv
import json
import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

# Local application imports
from src.config import config
from src.gui.app_state import get_app_state
from src.gui.helpers import center_window
from src.gui.treeview_adapter import TreeviewAdapter
from src.rss_rules import RSSRule
from src import backup
from src.qbittorrent_api import fetch_rules, fetch_categories, fetch_feeds
from src.utils import (
    get_display_title,
    get_rule_name,
    sanitize_folder_name,
    strip_internal_fields,
    strip_internal_fields_from_titles,
    validate_folder_name,
    get_server_display_name,
    get_validation_profile_label,
)

logger = logging.getLogger(__name__)

def normalize_titles_structure(data: Any) -> Optional[Dict[str, List]]:
    """
    Normalize various title input formats into standard structure.
    
    Args:
        data: Input data (dict, list, or other format)
        
    Returns:
        Dictionary with 'anime' key containing list of titles, or None if invalid
    """
    try:
        if isinstance(data, dict):
            # If already has media types, return as-is
            if any(k in data for k in ['anime', 'manga', 'novel']):
                return data
            # If it's a qBittorrent rules export, extract rules
            if 'rules' in data or all(isinstance(v, dict) for v in data.values()):
                rules = data.get('rules', data)
                return {'anime': list(rules.values()) if isinstance(rules, dict) else rules}
            # Single level dict, wrap it
            return {'anime': [data]}
        elif isinstance(data, list):
            return {'anime': data}
        elif isinstance(data, str):
            return {'anime': [{'node': {'title': data}, 'mustContain': data}]}
        return None
    except Exception as e:
        logger.error(f"Error normalizing titles structure: {e}")
        return None


def import_titles_from_text(text: str) -> Optional[Dict[str, List]]:
    """
    Import and normalize titles from text (JSON or line-delimited).
    
    Args:
        text: Text content containing titles
        
    Returns:
        Normalized titles structure, or None if parsing fails
    """
    try:
        parsed = json.loads(text)
    except Exception:
        csv_parsed = _import_titles_from_csv_text(text, force=False)
        if csv_parsed:
            return csv_parsed
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        parsed = lines if lines else None
        if not parsed:
            return None
    
    return normalize_titles_structure(parsed)


def _import_titles_from_csv_text(text: str, force: bool = False) -> Optional[Dict[str, List]]:
    """Parse CSV-like text into normalized titles structure.

    When force=False, this parser only activates for clear multi-line CSV input
    to avoid misclassifying plain one-line title text.
    """
    try:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        has_csv_delimiter = (',' in first_line) or (';' in first_line)
        if not force and (len(lines) < 2 or not has_csv_delimiter):
            return None

        delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
        reader = csv.reader(lines, delimiter=delimiter)
        rows = [row for row in reader if row and any(str(cell).strip() for cell in row)]
        if not rows:
            return None

        header_key = str(rows[0][0]).strip().lower() if rows[0] else ''
        has_header = header_key in {'title', 'name', 'rule', 'rule_name', 'mustcontain', 'must_contain'}
        start_idx = 1 if has_header else 0

        titles: List[str] = []
        for row in rows[start_idx:]:
            if not row:
                continue
            candidate = str(row[0]).strip()
            if candidate:
                titles.append(candidate)

        if not titles:
            return None

        return {
            'anime': [
                {
                    'node': {'title': title},
                    'mustContain': title,
                    'ruleName': title,
                }
                for title in titles
            ]
        }
    except Exception:
        return None


def _snapshot_import_entries(all_titles: Dict[str, List]) -> List[Dict[str, str]]:
    """Build import entry snapshots with before/after sanitization data."""
    snapshots: List[Dict[str, str]] = []

    if not isinstance(all_titles, dict):
        return snapshots

    for items in all_titles.values():
        if not isinstance(items, list):
            continue
        for entry in items:
            try:
                if isinstance(entry, dict):
                    node = entry.get('node') or {}
                    display = str(node.get('title') or entry.get('title') or entry.get('name') or '').strip()
                    raw = str(entry.get('mustContain') or entry.get('title') or entry.get('name') or '').strip()
                    if not raw and display:
                        raw = display.split(' - ', 1)[-1].strip()
                else:
                    display = str(entry).strip()
                    raw = display

                if not raw:
                    continue

                sanitized = sanitize_folder_name(raw)
                valid, reason = validate_folder_name(sanitized)

                severity = 'ok'
                if sanitized != raw:
                    severity = 'warn'

                if (not valid) or (not sanitized.strip()):
                    severity = 'critical'
                elif raw:
                    try:
                        retention = len(sanitized) / max(1, len(raw))
                    except Exception:
                        retention = 1.0
                    if retention < 0.6:
                        severity = 'critical'

                snapshots.append(
                    {
                        'display': display or raw,
                        'before': raw,
                        'after': sanitized,
                        'severity': severity,
                        'reason': reason or ('Sanitized for folder safety' if sanitized != raw else 'No change needed'),
                    }
                )
            except Exception:
                continue

    return snapshots


def _show_import_sanitize_check(
    root: tk.Tk,
    parsed_data: Dict[str, List],
    source_name: str,
) -> Tuple[bool, bool]:
    """Show a pre-import sanitization preview and return (proceed, auto_sanitize)."""
    try:
        default_auto_sanitize = bool(config.get_pref('auto_sanitize_imports', True))
    except Exception:
        default_auto_sanitize = True

    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'

    if theme_pref == 'dark':
        bg = '#1d222b'
        fg = '#e6edf3'
        text_bg = '#171b24'
        warn_bg = '#4a3f1f'
        warn_fg = '#ffd27f'
        crit_bg = '#4a1f1f'
        crit_fg = '#ff9b9b'
        ok_fg = '#9ecbff'
    else:
        bg = '#f5f5f5'
        fg = '#1f2328'
        text_bg = '#ffffff'
        warn_bg = '#fff7d6'
        warn_fg = '#7a5600'
        crit_bg = '#ffe8e8'
        crit_fg = '#8f1f1f'
        ok_fg = '#2f6f44'

    snapshots = _snapshot_import_entries(parsed_data)
    changed = [s for s in snapshots if s['before'] != s['after']]
    critical = [s for s in snapshots if s['severity'] == 'critical']

    dlg = tk.Toplevel(root)
    dlg.title(f"Import Check - {source_name}")
    dlg.geometry('980x620')
    dlg.minsize(760, 460)
    dlg.transient(root)
    dlg.grab_set()
    dlg.configure(bg=bg)
    center_window(dlg, width=980, height=620, parent=root)

    result = {'proceed': False, 'auto_sanitize': default_auto_sanitize}
    auto_sanitize_var = tk.BooleanVar(value=default_auto_sanitize)

    header = tk.Frame(dlg, bg=bg)
    header.pack(fill='x', padx=12, pady=(12, 8))

    tk.Label(
        header,
        text='Pre-import Sanitization Check',
        bg=bg,
        fg=fg,
        font=('Segoe UI', 11, 'bold'),
    ).pack(anchor='w')

    summary = (
        f"Items scanned: {len(snapshots)}    "
        f"Will be sanitized: {len(changed)}    "
        f"Needs manual review: {len(critical)}"
    )
    tk.Label(header, text=summary, bg=bg, fg=fg, anchor='w').pack(anchor='w', pady=(4, 0))

    try:
        auto_check = ttk.Checkbutton(
            header,
            text='Apply automatic sanitization during this import',
            variable=auto_sanitize_var,
        )
        auto_check.pack(anchor='w', pady=(8, 0))
    except Exception:
        pass

    body = tk.Frame(dlg, bg=bg)
    body.pack(fill='both', expand=True, padx=12, pady=(0, 8))

    controls = tk.Frame(body, bg=bg)
    controls.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 6))
    controls.grid_columnconfigure(0, weight=1)

    show_changed_only_var = tk.BooleanVar(value=True)

    severity_summary = tk.Label(
        controls,
        text='',
        bg=bg,
        fg=fg,
        anchor='w',
        font=('Segoe UI', 9),
    )
    severity_summary.pack(side='left', fill='x', expand=True)

    toggle_btn = ttk.Button(controls, text='Show All Titles')
    toggle_btn.pack(side='right')

    table_wrap = tk.Frame(body, bg=bg)
    table_wrap.grid(row=1, column=0, sticky='nsew')

    columns = ('severity', 'before', 'after', 'display', 'reason')
    table = ttk.Treeview(table_wrap, columns=columns, show='headings', selectmode='browse', height=14)
    table.heading('severity', text='Severity')
    table.heading('before', text='Before')
    table.heading('after', text='After')
    table.heading('display', text='Display Name')
    table.heading('reason', text='Note')

    table.column('severity', width=90, minwidth=80, anchor='center', stretch=False)
    table.column('before', width=220, minwidth=160, anchor='w', stretch=True)
    table.column('after', width=220, minwidth=160, anchor='w', stretch=True)
    table.column('display', width=200, minwidth=140, anchor='w', stretch=True)
    table.column('reason', width=260, minwidth=180, anchor='w', stretch=True)

    if theme_pref == 'dark':
        table.tag_configure('warn', foreground=warn_fg, background=warn_bg)
        table.tag_configure('critical', foreground=crit_fg, background=crit_bg)
        table.tag_configure('ok', foreground=ok_fg, background=text_bg)
    else:
        table.tag_configure('warn', foreground=warn_fg, background=warn_bg)
        table.tag_configure('critical', foreground=crit_fg, background=crit_bg)
        table.tag_configure('ok', foreground=ok_fg)

    y_scroll = ttk.Scrollbar(body, orient='vertical', command=table.yview)
    x_scroll = ttk.Scrollbar(body, orient='horizontal', command=table.xview)
    table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    table.grid(row=0, column=0, sticky='nsew')
    table_wrap.grid_rowconfigure(0, weight=1)
    table_wrap.grid_columnconfigure(0, weight=1)

    y_scroll.grid(row=1, column=1, sticky='ns')
    x_scroll.grid(row=2, column=0, sticky='ew')
    body.grid_rowconfigure(1, weight=1)
    body.grid_columnconfigure(0, weight=1)

    def _on_table_click(event):
        """Handle click events: sort by column header or copy cell to clipboard."""
        item = table.identify_row(event.y)
        col = table.identify_column(event.x)
        region = table.identify_region(event.x, event.y)

        if region == 'heading' and col:
            col_index = int(col[1:]) - 1
            col_name = columns[col_index] if col_index < len(columns) else None
            if col_name:
                _sort_table_by_column(col_name)
        elif region == 'cell' and item and col:
            col_index = int(col[1:]) - 1
            if col_index < len(columns):
                try:
                    values = table.item(item, 'values')
                    if col_index < len(values):
                        cell_text = str(values[col_index])
                        root.clipboard_clear()
                        root.clipboard_append(cell_text)
                        root.update()
                except Exception:
                    pass

    _sort_state = {'column': None, 'reverse': False}

    def _sort_table_by_column(col_name: str) -> None:
        """Sort table by column, toggle reverse on repeated clicks."""
        if _sort_state['column'] == col_name:
            _sort_state['reverse'] = not _sort_state['reverse']
        else:
            _sort_state['column'] = col_name
            _sort_state['reverse'] = False

        current_items = list(table.get_children())
        item_data = [
            (table.item(item, 'values'), item) for item in current_items
        ]

        col_index = columns.index(col_name) if col_name in columns else 0
        try:
            item_data.sort(
                key=lambda x: str(x[0][col_index]).lower() if col_index < len(x[0]) else '',
                reverse=_sort_state['reverse']
            )
        except Exception:
            pass

        for i, (values, item) in enumerate(item_data):
            table.move(item, '', i)

    table.bind('<Button-1>', _on_table_click)

    help_text = tk.Label(
        body,
        text='💡 Tip: Click column headers to sort, click cells to copy to clipboard',
        bg=bg,
        fg=fg,
        font=('Segoe UI', 8),
        anchor='w'
    )
    help_text.grid(row=3, column=0, sticky='ew', pady=(4, 0), padx=(0, 1))

    def _render_rows() -> None:
        table.delete(*table.get_children())

        if show_changed_only_var.get():
            display_rows = [s for s in snapshots if s['before'] != s['after']]
        else:
            display_rows = list(snapshots)

        warn_count = sum(1 for s in display_rows if s['severity'] == 'warn')
        critical_count = sum(1 for s in display_rows if s['severity'] == 'critical')
        ok_count = sum(1 for s in display_rows if s['severity'] == 'ok')
        hidden_count = max(0, len(snapshots) - len(display_rows))

        summary_parts = [
            f"Displayed: {len(display_rows)}",
            f"OK: {ok_count}",
            f"WARN: {warn_count}",
            f"CRITICAL: {critical_count}",
        ]
        if hidden_count:
            summary_parts.append(f"Hidden unchanged: {hidden_count}")
        severity_summary.configure(text='   |   '.join(summary_parts))

        for item in display_rows:
            severity = item['severity']
            sev_label = {'ok': 'OK', 'warn': 'WARN', 'critical': 'CRITICAL'}.get(severity, 'OK')
            table.insert(
                '',
                'end',
                values=(sev_label, item['before'], item['after'], item['display'], item['reason']),
                tags=(severity,),
            )

    def _toggle_changed_filter() -> None:
        is_changed_only = bool(show_changed_only_var.get())
        show_changed_only_var.set(not is_changed_only)

    toggle_btn.configure(command=_toggle_changed_filter)

    def _on_filter_mode_change(*_args: object) -> None:
        if show_changed_only_var.get():
            toggle_btn.configure(text='Show All Titles')
        else:
            toggle_btn.configure(text='Hide Non-Changed Titles')
        _render_rows()

    show_changed_only_var.trace_add('write', _on_filter_mode_change)
    _render_rows()

    btns = tk.Frame(dlg, bg=bg)
    btns.pack(fill='x', padx=12, pady=(0, 12))

    def _cancel() -> None:
        result['proceed'] = False
        try:
            dlg.destroy()
        except Exception:
            pass

    def _continue() -> None:
        result['proceed'] = True
        result['auto_sanitize'] = bool(auto_sanitize_var.get())
        try:
            dlg.destroy()
        except Exception:
            pass

    ttk.Button(btns, text='Cancel', command=_cancel).pack(side='right')
    ttk.Button(btns, text='Continue Import', command=_continue, style='Accent.TButton').pack(side='right', padx=(0, 8))

    dlg.wait_window()
    return bool(result['proceed']), bool(result['auto_sanitize'])


def prefix_titles_with_season_year(
    all_titles: Dict[str, List],
    season: str,
    year: str
) -> None:
    """
    Prefix all titles with season and year (e.g., "Fall 2025 - Title").
    Also adds season/year folder to save paths.
    
    Example:
    - Display title: "Fall 2025 - Anime Title"
    - Save path: "/downloads/anime/Fall 2025/Anime Title/"
    
    Modifies titles in-place.
    
    Args:
        all_titles: Dictionary of titles organized by media type
        season: Season name
        year: Year string
    """
    try:
        if not season or not year:
            return
        
        prefix = f"{season} {year} - "
        season_year_folder = f"{season} {year}"
        
        if not isinstance(all_titles, dict):
            return
        
        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue
            
            for i, entry in enumerate(items):
                try:
                    if isinstance(entry, dict):
                        node = entry.get('node', {})
                        title = node.get('title') or entry.get('title') or ''
                        orig_title = str(title) if title else ''
                        
                        if orig_title and not orig_title.startswith(prefix):
                            # Add prefix to display title
                            node['title'] = prefix + orig_title
                            entry['node'] = node
                            if not entry.get('mustContain'):
                                entry['mustContain'] = orig_title
                            
                            # Add season/year folder to save path
                            current_save_path = entry.get('savePath', '') or ''
                            if current_save_path:
                                import os.path
                                # Sanitize the title for use as folder name
                                sanitized_title = sanitize_folder_name(orig_title)
                                # Add season/year folder and title folder
                                # Example: "/downloads/anime" -> "/downloads/anime/Fall 2025/Anime Title"
                                new_save_path = os.path.join(current_save_path, season_year_folder, sanitized_title).replace('\\', '/')
                                entry['savePath'] = new_save_path
                                
                                # Also update torrentParams if it exists
                                if 'torrentParams' not in entry:
                                    entry['torrentParams'] = {}
                                entry['torrentParams']['save_path'] = new_save_path
                                
                                logger.debug(f"Updated save path: '{current_save_path}' -> '{new_save_path}'")
                    else:
                        # String entry
                        title = str(entry)
                        if title and not title.startswith(prefix):
                            items[i] = {
                                'node': {'title': prefix + title},
                                'mustContain': title
                            }
                except Exception as e:
                    logger.error(f"Error prefixing title {i}: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in prefix_titles_with_season_year: {e}")


def collect_invalid_folder_titles(all_titles: Dict[str, List]) -> List[Tuple[str, str, str]]:
    """
    Collect all titles with invalid folder names.
    
    Args:
        all_titles: Dictionary of titles organized by media type
        
    Returns:
        List of tuples (display_name, raw_name, error_message) for invalid titles
    """
    invalid = []
    
    try:
        if not isinstance(all_titles, dict):
            return invalid
        
        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue
            
            for entry in items:
                try:
                    raw = ''
                    display = ''
                    
                    if isinstance(entry, dict):
                        node = entry.get('node', {})
                        display = node.get('title') or entry.get('title') or ''
                        raw = entry.get('mustContain') or entry.get('title') or entry.get('name') or ''
                        
                        # Try to extract raw from display if needed
                        if display and isinstance(display, str) and ' - ' in display:
                            parts = display.split(' - ', 1)
                            if len(parts) == 2:
                                maybe_raw = parts[1]
                                if maybe_raw and not raw:
                                    raw = maybe_raw
                    else:
                        display = str(entry)
                        raw = display
                    
                    if not raw:
                        continue
                    
                    # Validate the SANITIZED version, not the original
                    sanitized_raw = sanitize_folder_name(raw)
                    is_valid, reason = validate_folder_name(sanitized_raw)
                    if not is_valid:
                        invalid.append((display or raw, raw, reason))
                        
                except Exception as e:
                    logger.error(f"Error checking folder name: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in collect_invalid_folder_titles: {e}")
    
    return invalid


def auto_sanitize_titles(all_titles: Dict[str, List]) -> None:
    """
    Automatically sanitize folder names in titles.
    
    Modifies titles in-place.
    
    Args:
        all_titles: Dictionary of titles organized by media type
    """
    try:
        if not isinstance(all_titles, dict):
            return
        
        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue
            
            for entry in items:
                try:
                    if isinstance(entry, dict):
                        # Sanitize mustContain field
                        must_contain = entry.get('mustContain', '')
                        if must_contain:
                            entry['mustContain'] = sanitize_folder_name(must_contain)
                        
                        # Sanitize node title if it contains raw folder name
                        node = entry.get('node', {})
                        node_title = node.get('title', '')
                        if node_title and ' - ' in node_title:
                            parts = node_title.split(' - ', 1)
                            if len(parts) == 2:
                                prefix, raw = parts
                                node['title'] = f"{prefix} - {sanitize_folder_name(raw)}"
                                entry['node'] = node
                except Exception as e:
                    logger.error(f"Error sanitizing title: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in auto_sanitize_titles: {e}")


def populate_missing_rule_fields(
    all_titles: Dict[str, List],
    season: str,
    year: str
) -> None:
    """
    Populate missing fields in rule entries with defaults.
    
    Applies default category and save path from config to imported rules
    that don't already have them set.
    
    Modifies titles in-place.
    
    Args:
        all_titles: Dictionary of titles
        season: Season name
        year: Year string
    """
    logger.debug(f"populate_missing_rule_fields called with {sum(len(v) for v in all_titles.values() if isinstance(v, list))} total titles")
    try:
        from src.utils import get_current_anime_season
        from src.config import config
        
        # Use provided season/year or current if not specified
        if not season or not year:
            year_val, season_val = get_current_anime_season()
            season = season or season_val
            year = year or str(year_val)
        
        # Get defaults from config
        default_save_path = getattr(config, 'DEFAULT_SAVE_PATH', '') or ''
        default_category = getattr(config, 'DEFAULT_CATEGORY', '') or ''
        default_affected_feeds = getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or []
        
        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue
            
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                
                try:
                    # Ensure basic fields exist
                    if 'node' not in entry:
                        entry['node'] = {}
                    
                    if 'enabled' not in entry:
                        entry['enabled'] = True
                    
                    # Populate mustContain from node title if missing
                    if not entry.get('mustContain'):
                        node = entry.get('node', {})
                        title = node.get('title') or entry.get('title', '')
                        if title:
                            entry['mustContain'] = title
                    
                    # Apply default category if missing
                    if not entry.get('assignedCategory') and default_category:
                        entry['assignedCategory'] = default_category
                        logger.debug(f"Applied default category '{default_category}' to {entry.get('mustContain', 'unknown')}")
                    
                    # Apply default save path if missing
                    if not entry.get('savePath') and default_save_path:
                        entry['savePath'] = default_save_path
                        logger.debug(f"Applied default save path '{default_save_path}' to {entry.get('mustContain', 'unknown')}")
                    
                    # Apply default affected feeds if missing or empty
                    if not entry.get('affectedFeeds') and default_affected_feeds:
                        entry['affectedFeeds'] = default_affected_feeds.copy()
                        logger.debug(f"Applied default affected feeds to {entry.get('mustContain', 'unknown')}")
                    
                    # Ensure torrentParams exist and sync category/save_path
                    if 'torrentParams' not in entry:
                        entry['torrentParams'] = {}
                    
                    # Sync category and save_path to torrentParams
                    if entry.get('assignedCategory'):
                        entry['torrentParams']['category'] = entry['assignedCategory']
                    if entry.get('savePath'):
                        entry['torrentParams']['save_path'] = entry['savePath']
                            
                except Exception as e:
                    logger.error(f"Error populating fields: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in populate_missing_rule_fields: {e}")


def update_treeview_with_titles(all_titles: Dict[str, List], treeview_widget=None) -> bool:
    """
    Update the main treeview widget with anime titles.
    
    Comprehensive update with proper error handling, validation, and display refresh.
    
    Args:
        all_titles: Dictionary of titles organized by media type
        treeview_widget: Optional treeview widget reference. If None, retrieves from app_state
        
    Returns:
        True if update succeeded, False otherwise
    """
    from src.utils import validate_folder_name_by_filesystem
    
    # Get treeview widget
    if treeview_widget is None:
        app_state = get_app_state()
        treeview = app_state.treeview if app_state else None
    else:
        treeview = treeview_widget
        app_state = get_app_state()
    
    if not treeview:
        logger.warning("No treeview widget available")
        return False
    
    if not all_titles:
        all_titles = {}
    
    try:
        adapter = TreeviewAdapter(treeview)

        # Step 1: Clear existing display
        adapter.clear_all()
        
        # Step 2: Clear app_state items cache
        if app_state:
            app_state.items.clear()
        
        # Step 3: Configure display tags
        try:
            treeview.tag_configure('error', foreground='#d32f2f', background='#ffebee')
            treeview.tag_configure('warning', foreground='#f57f17', background='#fff3e0')
        except tk.TclError:
            logger.debug("Treeview tag configuration failed", exc_info=True)
        
        # Step 4: Prepare items for insertion
        auto_sanitize = config.get_pref('auto_sanitize_paths', True)
        items_to_add = []
        index = 0
        
        # Iterate through all titles
        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue
                
            for entry in items:
                try:
                    # Extract title information
                    if isinstance(entry, dict):
                        node = entry.get('node') or {}
                        title_text = node.get('title') or entry.get('title') or entry.get('name') or str(entry)
                        category = entry.get('assignedCategory') or entry.get('category') or ''
                        save_path = entry.get('savePath') or entry.get('save_path') or ''
                        
                        if not save_path:
                            tp = entry.get('torrentParams') or entry.get('torrent_params') or {}
                            save_path = tp.get('save_path') or tp.get('savePath') or ''
                        
                        if save_path:
                            save_path = str(save_path).replace('\\', '/')
                        
                        enabled = entry.get('enabled', True)
                        enabled_mark = '✓' if enabled else ''
                    else:
                        title_text = str(entry)
                        category = ''
                        save_path = ''
                        enabled_mark = '✓'
                    
                    # Validate and prepare display
                    display_title = title_text
                    validation_tag = None
                    
                    if not title_text or not title_text.strip():
                        display_title = "⚠️ [Empty Title]"
                        validation_tag = 'warning'
                    
                    # Validate folder names if save path exists
                    if save_path and not validation_tag:
                        folders = [f.strip() for f in save_path.split('/') if f.strip()]
                        for folder in folders:
                            valid, _ = validate_folder_name_by_filesystem(folder)
                            if not valid:
                                if not auto_sanitize:
                                    display_title = f"❌ {title_text}"
                                    validation_tag = 'error'
                                break
                    
                    index += 1
                    values = (enabled_mark, str(index), display_title, category, save_path)
                    items_to_add.append((title_text, entry, values, validation_tag))
                    
                except Exception as e:
                    logger.error(f"Error processing entry: {e}")
                    continue
        
        # Step 5: Insert all items into treeview
        rows_to_insert: List[Tuple[Tuple[str, ...], Optional[Tuple[str, ...]]]] = []
        for title_text, entry, values, tag in items_to_add:
            try:
                rows_to_insert.append((values, (tag,) if tag else None))
                
                # Add to app_state cache
                if app_state:
                    app_state.add_item(title_text, entry)
                    
            except Exception as e:
                logger.error(f"Error inserting item '{title_text}': {e}")

        try:
            adapter.insert_rows(rows_to_insert)
        except Exception as e:
            logger.error(f"Error inserting rows into treeview: {e}")

        # Keep adapter-owned filter cache in sync with external data refreshes.
        try:
            state_adapter = getattr(app_state, 'tree_adapter', None)
            if state_adapter and getattr(state_adapter, 'treeview', None) is treeview:
                state_adapter.on_data_changed()
            else:
                adapter.on_data_changed()
        except Exception:
            logger.debug("Unable to notify tree adapter of data change", exc_info=True)
        
        # Step 6: Refresh layout safely without forcing nested event loops.
        treeview.update_idletasks()
        
        # Verify insertion
        final_count = len(treeview.get_children())
        logger.debug(f"Treeview updated: {final_count} items displayed")
        
        return True
        
    except Exception as e:
        logger.error(f"Error in update_treeview_with_titles: {e}", exc_info=True)
        return False


def refresh_treeview_display_safe() -> None:
    """
    Safely refresh the treeview with current config data.
    """
    try:
        all_titles = getattr(config, 'ALL_TITLES', None) or {}
        app_state = get_app_state()
        
        if app_state and app_state.treeview:
            if update_treeview_with_titles(all_titles, treeview_widget=app_state.treeview):
                logger.debug("Treeview refresh completed successfully")
            else:
                logger.warning("Treeview refresh failed")
    except Exception as e:
        logger.error(f"Error in refresh_treeview_display_safe: {e}")


def _import_titles_core(
    parsed_data: Dict[str, List],
    season: str,
    year: str,
    prefix_imports: bool,
    source_name: str = "import",
    auto_sanitize_override: Optional[bool] = None,
    skip_validation: bool = False,
) -> Tuple[bool, str, int, int]:
    """
    Core import logic shared by file, clipboard, and recent file imports.
    
    Args:
        parsed_data: Parsed titles dictionary
        season: Season value for prefixing
        year: Year value for prefixing
        prefix_imports: Whether to prefix titles with season/year
        source_name: Name of import source for status messages ("file", "clipboard", etc.)
        
    Returns:
        Tuple of (success, status_message, new_count, duplicate_count)
    """
    try:
        # Check for invalid folder names
        if auto_sanitize_override is None:
            try:
                auto_sanitize = bool(config.get_pref('auto_sanitize_imports', True))
            except Exception:
                auto_sanitize = True
        else:
            auto_sanitize = bool(auto_sanitize_override)

        if not skip_validation:
            invalid_titles = collect_invalid_folder_titles(parsed_data)

            if invalid_titles:
                if auto_sanitize:
                    auto_sanitize_titles(parsed_data)
                    invalid_titles = collect_invalid_folder_titles(parsed_data)

                if invalid_titles:
                    # Validation failed even after auto-sanitize
                    # Caller should handle this by showing dialog
                    return False, "validation_failed", 0, 0
        
        # Merge with existing titles
        current = getattr(config, 'ALL_TITLES', {}) or {}
        if not isinstance(current, dict):
            current = {}
        
        logger.debug(f"Import check: current ALL_TITLES has {sum(len(v) if isinstance(v, list) else 0 for v in current.values())} items")
        
        # Get existing title names, mustContain, and ruleNames to avoid duplicates
        existing_titles = set()
        existing_must_contain = set()
        existing_rule_names = set()
        
        for k, lst in current.items():
            if not isinstance(lst, list):
                continue
            for it in lst:
                try:
                    if isinstance(it, dict):
                        t = (it.get('node') or {}).get('title') or it.get('ruleName') or it.get('name')
                        if t:
                            existing_titles.add(str(t))
                        must = it.get('mustContain')
                        if must:
                            existing_must_contain.add(str(must))
                        rule_name = it.get('ruleName') or it.get('name')
                        if rule_name:
                            existing_rule_names.add(str(rule_name))
                    else:
                        t = str(it)
                        existing_titles.add(t)
                except Exception:
                    pass
        
        # Merge new titles, skipping duplicates
        # Track newly added items for prefix application
        new_items = {media_type: [] for media_type in parsed_data.keys() if isinstance(parsed_data.get(media_type), list)}
        new_count = 0
        
        for media_type, items in parsed_data.items():
            if not isinstance(items, list):
                continue
            if media_type not in current:
                current[media_type] = []
            
            for item in items:
                try:
                    if isinstance(item, dict):
                        title = (item.get('node') or {}).get('title') or item.get('ruleName') or item.get('name')
                        must = item.get('mustContain')
                        rule_name = item.get('ruleName') or item.get('name')
                    else:
                        # Convert string items to proper dict format
                        title = str(item)
                        must = title
                        rule_name = title
                        # Convert to dict format
                        item = {'node': {'title': title}, 'mustContain': must, 'ruleName': rule_name}
                    
                    key = str(title) if title else None
                except (AttributeError, TypeError, ValueError):
                    logger.debug("Failed to parse imported item; skipping", exc_info=True)
                    key = None
                    must = None
                    rule_name = None
                
                # Check if it's a duplicate by title, mustContain, or ruleName
                is_duplicate = False
                if key and key in existing_titles:
                    is_duplicate = True
                elif must and str(must) in existing_must_contain:
                    is_duplicate = True
                elif rule_name and str(rule_name) in existing_rule_names:
                    is_duplicate = True
                
                if not is_duplicate:
                    current[media_type].append(item)
                    new_items[media_type].append(item)  # Track new items
                    if key:
                        existing_titles.add(key)
                    if must:
                        existing_must_contain.add(str(must))
                    if rule_name:
                        existing_rule_names.add(str(rule_name))
                    new_count += 1
        
        config.ALL_TITLES = current
        total_imported = sum(len(v) for v in parsed_data.values() if isinstance(v, list))
        duplicates = total_imported - new_count
        
        # Debug logging
        total_in_all_titles = sum(len(v) for v in current.values() if isinstance(v, list))
        logger.info(f"Import merge complete: {new_count} new, {duplicates} duplicates, total in ALL_TITLES: {total_in_all_titles}")
        
        # Populate missing fields ONLY for newly imported items
        if new_items:
            logger.debug(f"Populating fields for {sum(len(v) for v in new_items.values())} new items only")
            populate_missing_rule_fields(new_items, season, year)
            
            # Apply prefix ONLY to newly imported items
            if prefix_imports:
                logger.debug(f"Applying prefix to {sum(len(v) for v in new_items.values())} new items only")
                prefix_titles_with_season_year(new_items, season, year)
        
        # Build status message
        status_msg = f'Imported {new_count} new titles from {source_name}.'
        if duplicates > 0:
            status_msg += f' ({duplicates} duplicates skipped)'
        
        return True, status_msg, new_count, duplicates
        
    except Exception as e:
        logger.error(f"Error in core import logic: {e}")
        # Fallback to replace
        config.ALL_TITLES = parsed_data
        status_msg = f'Imported {sum(len(v) for v in parsed_data.values())} titles from {source_name}.'
        return True, status_msg, sum(len(v) for v in parsed_data.values()), 0


def import_titles_from_file(
    root: tk.Tk,
    status_var: tk.StringVar,
    season_var: tk.StringVar,
    year_var: tk.StringVar,
    prefix_imports: bool = False,
    path: Optional[str] = None
) -> bool:
    """
    Import titles from a JSON file and update application state.
    
    Args:
        root: Parent window
        status_var: Status bar variable
        season_var: Season selection variable
        year_var: Year selection variable
        prefix_imports: Whether to prefix titles with season/year
        path: Optional file path (opens dialog if None)
        
    Returns:
        True if import succeeded, False otherwise
    """
    if not path:
        path = filedialog.askopenfilename(
            title='Open titles file (JSON/CSV)',
            filetypes=[('JSON/CSV', '*.json *.csv'), ('JSON', '*.json'), ('CSV', '*.csv'), ('All files', '*.*')]
        )
    
    if not path:
        return False
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        ext = os.path.splitext(path)[1].lower()
        if ext == '.csv':
            parsed = _import_titles_from_csv_text(text, force=True)
        else:
            parsed = import_titles_from_text(text)
        if not parsed:
            messagebox.showerror(
                'Import Error', 
                'Failed to parse import data from selected file.\n\n'
                'Action: Ensure the file contains valid JSON or CSV format and try again.'
            )
            return False

        try:
            show_check = bool(config.get_pref('show_import_sanitize_check', True))
        except Exception:
            show_check = True

        auto_sanitize_choice: Optional[bool] = None
        if show_check:
            proceed, auto_sanitize_choice = _show_import_sanitize_check(root, parsed, 'file import')
            if not proceed:
                status_var.set('Import cancelled.')
                return False
        
        # Use core import logic
        season = season_var.get()
        year = year_var.get()
        success, status_msg, new_count, duplicates = _import_titles_core(
            parsed, season, year, prefix_imports, "file", auto_sanitize_override=auto_sanitize_choice
        )
        
        # Handle validation failure
        if not success and status_msg == "validation_failed":
            invalid_titles = collect_invalid_folder_titles(parsed)
            validation_profile = get_validation_profile_label(
                main_server=getattr(config, 'MAIN_SERVER', 'qbittorrent')
            )
            # Create a more readable display with better formatting
            lines = []
            for display, raw, reason in invalid_titles:
                display_short = display if len(display) <= 60 else display[:57] + "..."
                lines.append(f"• {display_short}\n  → {reason}")
            
            message_parts = [
                f'Validation profile: {validation_profile}\n',
                'The following imported titles contain characters or names\n'
                'invalid for folder names:\n'
            ]
            
            display_count = min(8, len(lines))
            message_parts.append('\n'.join(lines[:display_count]))
            
            if len(lines) > display_count:
                message_parts.append(f'\n... and {len(lines) - display_count} more titles with issues')
            
            message_parts.append('\n\nContinue import anyway?')
            
            if not messagebox.askyesno(
                'Invalid folder names',
                '\n'.join(message_parts),
                icon='warning'
            ):
                return False
            
            # Retry import without validation
            success, status_msg, new_count, duplicates = _import_titles_core(
                parsed,
                season,
                year,
                prefix_imports,
                "file",
                auto_sanitize_override=False,
                skip_validation=True,
            )
        
        if not success:
            return False
        
        # Update display
        refresh_treeview_display_safe()
        status_var.set(status_msg)
        
        # Add to recent files
        try:
            from src.cache import save_recent_files
            recent = getattr(config, 'RECENT_FILES', []) or []
            if path not in recent:
                recent.insert(0, path)
                recent = recent[:10]  # Keep last 10
                config.RECENT_FILES = recent
                save_recent_files(recent)
        except Exception as e:
            logger.error(f"Error saving recent file: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error importing from file: {e}")
        messagebox.showerror('File Error', f'Error reading file: {e}')
        return False


def import_titles_from_clipboard(
    root: tk.Tk,
    status_var: tk.StringVar,
    season_var: tk.StringVar,
    year_var: tk.StringVar,
    prefix_imports: bool = False
) -> bool:
    """
    Import titles from clipboard text and update application state.
    
    Args:
        root: Parent window
        status_var: Status bar variable
        season_var: Season selection variable
        year_var: Year selection variable
        prefix_imports: Whether to prefix titles with season/year
        
    Returns:
        True if import succeeded, False otherwise
    """
    try:
        text = root.clipboard_get()
    except Exception:
        messagebox.showwarning('Clipboard', 'No text found in clipboard.')
        return False
    
    parsed = import_titles_from_text(text)
    if not parsed:
        messagebox.showerror(
            'Import Error', 
            'Failed to parse JSON, CSV, or titles from clipboard text.\n\n'
            'Action: Ensure the clipboard contains valid JSON/CSV data or anime titles, one per line.'
        )
        return False

    try:
        show_check = bool(config.get_pref('show_import_sanitize_check', True))
    except Exception:
        show_check = True

    auto_sanitize_choice: Optional[bool] = None
    if show_check:
        proceed, auto_sanitize_choice = _show_import_sanitize_check(root, parsed, 'clipboard import')
        if not proceed:
            status_var.set('Import cancelled.')
            return False
    
    # Use core import logic
    season = season_var.get()
    year = year_var.get()
    success, status_msg, new_count, duplicates = _import_titles_core(
        parsed, season, year, prefix_imports, "clipboard", auto_sanitize_override=auto_sanitize_choice
    )
    
    # Handle validation failure
    if not success and status_msg == "validation_failed":
        invalid_titles = collect_invalid_folder_titles(parsed)
        validation_profile = get_validation_profile_label(
            main_server=getattr(config, 'MAIN_SERVER', 'qbittorrent')
        )
        # Create a more readable display with better formatting
        lines = []
        for display, raw, reason in invalid_titles:
            display_short = display if len(display) <= 60 else display[:57] + "..."
            lines.append(f"• {display_short}\n  → {reason}")
        
        message_parts = [
            f'Validation profile: {validation_profile}\n',
            'The following imported titles contain characters or names\n'
            'invalid for folder names:\n'
        ]
        
        display_count = min(8, len(lines))
        message_parts.append('\n'.join(lines[:display_count]))
        
        if len(lines) > display_count:
            message_parts.append(f'\n... and {len(lines) - display_count} more titles with issues')
        
        message_parts.append('\n\nContinue import anyway?')
        
        if not messagebox.askyesno(
            'Invalid folder names',
            '\n'.join(message_parts),
            icon='warning'
        ):
            return False
        
        # Retry import without validation
        success, status_msg, new_count, duplicates = _import_titles_core(
            parsed,
            season,
            year,
            prefix_imports,
            "clipboard",
            auto_sanitize_override=False,
            skip_validation=True,
        )
    
    if not success:
        return False
    
    # Update display
    refresh_treeview_display_safe()
    status_var.set(status_msg)
    
    return True


def export_selected_titles() -> None:
    """Export selected titles from the listbox to a JSON file."""
    app_state = get_app_state()
    treeview = app_state.treeview
    
    if not treeview:
        return
    
    try:
        adapter = TreeviewAdapter(treeview)
        indices = adapter.get_selected_indices()
        if not indices:
            messagebox.showwarning('Export', 'No title selected to export.')
            return

        selected_entries = [app_state.items[i][1] for i in indices]
        
        # Build rules dict
        from src.rss_rules import build_rules_from_titles
        export_map = build_rules_from_titles({'anime': selected_entries})
        
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON', '*.json')]
        )
        
        if not path:
            return
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(export_map, f, indent=4)
        
        messagebox.showinfo('Export', f'Exported {len(export_map)} rule(s) to {path}')
        
    except Exception as e:
        logger.error(f"Error exporting selected titles: {e}")
        messagebox.showerror('Export Error', f'Failed to export: {e}')


def export_all_titles() -> None:
    """Export all titles to a JSON file."""
    try:
        data = getattr(config, 'ALL_TITLES', None) or {}
        if not data:
            messagebox.showwarning('Export All', 'No titles available to export.')
            return
        
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON', '*.json')]
        )
        
        if not path:
            return
        
        # Build rules dict
        try:
            from src.rss_rules import build_rules_from_titles
            export_map = build_rules_from_titles(data)
        except Exception:
            export_map = data
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(export_map, f, indent=4)
        
        messagebox.showinfo('Export All', f'Exported all titles to {path}')
        
    except Exception as e:
        logger.error(f"Error exporting all titles: {e}")
        messagebox.showerror('Export Error', f'Failed to export: {e}')


def clear_all_titles(root: tk.Tk, status_var: tk.StringVar) -> bool:
    """
    Clear all loaded titles after user confirmation.
    
    Args:
        root: Parent window
        status_var: Status bar variable
        
    Returns:
        True if titles were cleared, False otherwise
    """
    app_state = get_app_state()
    
    try:
        has_titles = bool(getattr(config, 'ALL_TITLES', None)) and any(
            (getattr(config, 'ALL_TITLES') or {}).values()
        )
    except (AttributeError, TypeError):
        has_titles = bool(getattr(config, 'ALL_TITLES', None))
    
    if not has_titles:
        status_var.set('No titles to clear.')
        if app_state.treeview:
            try:
                children = list(app_state.treeview.get_children())
                if children:
                    TreeviewAdapter(app_state.treeview).clear_all()
            except tk.TclError:
                logger.debug("Treeview clear skipped due to widget state", exc_info=True)
        return False
    
    if not messagebox.askyesno(
        'Clear All Titles',
        'Are you sure you want to clear all loaded titles? This cannot be undone.'
    ):
        return False
    
    # Clear the data structure
    try:
        logger.info(f"Clearing ALL_TITLES. Current count: {sum(len(v) if isinstance(v, list) else 0 for v in (getattr(config, 'ALL_TITLES', {}) or {}).values())}")
        config.ALL_TITLES = {}
        # Verify clear was successful
        verify_count = sum(len(v) if isinstance(v, list) else 0 for v in (getattr(config, 'ALL_TITLES', {}) or {}).values())
        logger.info(f"ALL_TITLES cleared. Verification count: {verify_count}")
        if verify_count > 0:
            logger.error(f"WARNING: ALL_TITLES still contains items after clear! Count: {verify_count}")
    except Exception as e:
        logger.error(f"Error clearing ALL_TITLES: {e}")
        return False
    
    # Clear app state items  
    try:
        if app_state:
            app_state.clear_items()
            logger.info(f"Cleared app_state items cache")
    except Exception as e:
        logger.error(f"Error clearing app_state items: {e}")
    
    # Clear the treeview display
    if app_state and app_state.treeview:
        try:
            # Delete all items
            children = list(app_state.treeview.get_children())
            if children:
                TreeviewAdapter(app_state.treeview).clear_all()
            
            # Refresh layout safely without re-entering event loop.
            app_state.treeview.update_idletasks()
            root.update_idletasks()
            try:
                root.after_idle(app_state.treeview.update_idletasks)
            except Exception:
                pass
            
            logger.info("Treeview display cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing treeview: {e}")
    
    status_var.set('Cleared all loaded titles.')
    logger.info("Clear operation completed successfully")
    return True


def dispatch_generation(
    root: tk.Tk,
    season_var: tk.StringVar,
    year_var: tk.StringVar,
    status_var: tk.StringVar
) -> None:
    """
    Handles generation and synchronization of RSS rules to the selected main server.
    
    Shows preview dialog with validation, allows user to review and confirm
    before syncing rules to the selected main server model.
    
    Args:
        root: Parent Tkinter window
        season_var: Tkinter variable containing season selection
        year_var: Tkinter variable containing year value
        status_var: Status bar variable for displaying progress
    """
    from src.constants import FileSystem
    from src.qbittorrent_api import QBittorrentClient
    from src.gui.app_state import get_app_state
    from src.rss_rules import build_rules_from_titles
    
    try:
        season = season_var.get()
        year = year_var.get()
        main_server_key = str(getattr(config, 'MAIN_SERVER', 'qbittorrent')).strip().lower()
        main_server_name = get_server_display_name(main_server_key)
        validation_profile = get_validation_profile_label(main_server=main_server_key)

        if not season or not year:
            messagebox.showwarning("Input Error", "Season and Year must be specified.")
            return

        app_state = get_app_state()
        listbox_items = app_state.listbox_items
        treeview = app_state.treeview

        # Get selected items or all items
        items = []
        try:
            if treeview:
                sel = treeview.selection()
                if sel:
                    # Match by index column (second column, index 1)
                    indices = []
                    for item_id in sel:
                        try:
                            values = treeview.item(item_id, 'values')
                            if values and len(values) >= 2:
                                idx_str = values[1]  # index column
                                idx = int(idx_str) - 1  # Convert to 0-based
                                if 0 <= idx < len(listbox_items):
                                    indices.append(idx)
                        except (tk.TclError, ValueError, TypeError, IndexError):
                            logger.debug("Skipping invalid selected treeview row", exc_info=True)
                else:
                    indices = list(range(len(listbox_items)))
            else:
                indices = list(range(len(listbox_items)))
        except (tk.TclError, AttributeError, TypeError):
            indices = list(range(len(listbox_items)))

        for i in indices:
            try:
                if i < len(listbox_items):
                    t, entry = listbox_items[i]
                    items.append((t, entry))
            except (TypeError, ValueError, IndexError):
                continue

        if not items:
            messagebox.showwarning('No Items', 'No titles to generate rules for.')
            return

        # Validation helper
        def _is_valid_folder_name(name):
            """Validates if a string is a valid folder name.
            
            Checks are based on the target filesystem type selected in preferences:
            - 'windows': Strict Windows filesystem validation
            - 'linux': Linux/Unix/Unraid validation (only forbids forward slash)
            """
            try:
                if not name or not isinstance(name, str):
                    return False, 'Empty name'
                
                s = str(name)
                
                # Check for empty after stripping
                if not s.strip():
                    return False, 'Empty name'
                
                # Get filesystem type preference (default to 'linux' for Unraid)
                fs_type = config.get_pref('filesystem_type', 'linux').lower()
                
                if fs_type == 'windows':
                    # Windows validation: strict checks
                    if s.endswith(' ') or s.endswith('.'):
                        return False, 'Ends with a space or dot (invalid on Windows)'
                    
                    found_invalid = [c for c in s if c in FileSystem.INVALID_CHARS]
                    if found_invalid:
                        return False, f'Contains invalid characters: {"".join(sorted(set(found_invalid)))}'
                    
                    base = s.split('.')[0].upper()
                    if base in FileSystem.RESERVED_NAMES:
                        return False, f'Reserved name: {base}'
                else:
                    # Linux/Unix/Unraid validation: only forward slash is truly invalid
                    if '/' in s:
                        return False, 'Contains forward slash (invalid in folder names)'
                
                # Check length (applies to all systems)
                if len(s) > FileSystem.MAX_PATH_LENGTH:
                    return False, f'Name too long (>{FileSystem.MAX_PATH_LENGTH} chars)'
                
                return True, None
            except Exception:
                return False, 'Validation error'

        # Use centralized validation function (comment kept for compatibility)
        from src.utils import validate_folder_name_by_filesystem
        _is_valid_folder_name = validate_folder_name_by_filesystem

        # Validate all items
        problems = []
        preview_list = []
        
        for title_text, entry in items:
            e = entry if isinstance(entry, dict) else {'node': {'title': str(entry)}}
            
            try:
                node = e.get('node') or {}
                node_title = node.get('title') or e.get('mustContain') or title_text
            except (AttributeError, TypeError):
                node_title = title_text
                
            if not node_title or not str(node_title).strip():
                problems.append(f'[{validation_profile}] Missing title for item: {title_text}')

            # Validate lastMatch JSON
            try:
                lm = e.get('lastMatch', '')
                if isinstance(lm, str):
                    s = lm.strip()
                    if s and (s.startswith('{') or s.startswith('[') or s.startswith('"')):
                        try:
                            json.loads(s)
                        except (ValueError, TypeError) as ex:
                            problems.append(f'[{validation_profile}] Invalid JSON lastMatch for "{title_text}": {ex}')
            except (AttributeError, TypeError):
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
                            problems.append(f'[{validation_profile}] Invalid folder in path for "{title_text}": "{folder}" - {reason}')
                            break
            except (AttributeError, TypeError, ValueError):
                pass

            preview_list.append(e)

        # Show preview dialog
        dlg = tk.Toplevel(root)
        dlg.title(f'Preview Generation & Sync - {main_server_name}')
        dlg.geometry('800x700')
        dlg.transient(root)
        dlg.grab_set()
        dlg.configure(bg='#f5f5f5')
        
        # Header
        header_frame = ttk.Frame(dlg, padding=10)
        header_frame.pack(fill='x')
        ttk.Label(header_frame, text=f'Generate {len(preview_list)} rule(s) for {season} {year}',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(header_frame, text=f'Target model: {main_server_name} | Validation profile: {validation_profile}',
             font=('Segoe UI', 8), foreground='#666').pack(anchor='w', pady=(3, 0))

        # Validation issues section
        prob_frame = ttk.LabelFrame(dlg, text=f'Validation ({validation_profile})', padding=10)
        prob_frame.pack(fill='both', padx=10, pady=(0, 10), expand=False)
        
        if problems:
            ttk.Label(prob_frame, text=f'⚠️ Validation issues detected for {validation_profile}:', 
                     foreground='#d32f2f', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 5))
            prob_box = tk.Text(prob_frame, height=min(10, max(3, len(problems))), width=90,
                              font=('Consolas', 9), wrap='word', bg='#fff3cd', fg='#856404')
            prob_box.pack(fill='both', expand=True)
            prob_scroll = ttk.Scrollbar(prob_frame, orient='vertical', command=prob_box.yview)
            prob_scroll.pack(side='right', fill='y')
            prob_box.configure(yscrollcommand=prob_scroll.set)
            
            for p in problems:
                prob_box.insert('end', f'• {p}\n')
            prob_box.config(state='disabled')
        else:
            ttk.Label(prob_frame, text=f'✅ No validation issues detected for {validation_profile}.',
                     foreground='#2e7d32', font=('Segoe UI', 9, 'bold')).pack(anchor='w')

        # Preview JSON section
        preview_frame = ttk.LabelFrame(dlg, text='Rules Preview (JSON)', padding=10)
        preview_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        preview_text = tk.Text(preview_frame, height=20, width=90, font=('Consolas', 9),
                               wrap='none', bg='#fafafa', fg='#333333')
        preview_text.pack(side='left', fill='both', expand=True)
        
        preview_scroll_y = ttk.Scrollbar(preview_frame, orient='vertical', command=preview_text.yview)
        preview_scroll_y.pack(side='right', fill='y')
        preview_scroll_x = ttk.Scrollbar(preview_frame, orient='horizontal', command=preview_text.xview)
        preview_scroll_x.pack(side='bottom', fill='x')
        
        preview_text.configure(yscrollcommand=preview_scroll_y.set, xscrollcommand=preview_scroll_x.set)
        
        try:
            # Build actual qBittorrent rules format for preview
            from src.rss_rules import build_rules_from_titles
            
            # Strip internal tracking fields before building rules for preview
            # Uses centralized helper from utils.py
            clean_titles = strip_internal_fields_from_titles(config.ALL_TITLES)
            
            # Build rules dict - this returns {"Rule Name": {rule_data}, ...}
            rules_dict = build_rules_from_titles(clean_titles)
            
            # Display as proper qBittorrent dictionary format (not a list)
            preview_text.insert('1.0', json.dumps(rules_dict, indent=2, ensure_ascii=False))
        except Exception as e:
            # Fallback to original format if build fails
            try:
                preview_data = {
                    'season': season,
                    'year': year,
                    'rule_count': len(preview_list),
                    'rules': preview_list
                }
                preview_text.insert('1.0', json.dumps(preview_data, indent=2, ensure_ascii=False))
            except Exception:
                preview_text.insert('1.0', str(preview_list))
        preview_text.config(state='disabled')

        # Sync mode selection frame
        mode_frame = ttk.LabelFrame(dlg, text='Sync Mode', padding=10)
        mode_frame.pack(fill='x', padx=10, pady=(0, 10))
        
        sync_mode = tk.StringVar(value='replace')
        
        ttk.Radiobutton(mode_frame, text='🔄 Replace All Rules (remove old rules, then add new ones)', 
                       variable=sync_mode, value='replace').pack(anchor='w', pady=2)
        ttk.Radiobutton(mode_frame, text='➕ Add/Update Only (keep existing rules, add or update new ones)', 
                       variable=sync_mode, value='add').pack(anchor='w', pady=2)

        # Button frame
        btns = ttk.Frame(dlg, padding=10)
        btns.pack(fill='x', side='bottom')

        def _do_proceed():
            """Proceed with sync after validation."""
            try:
                if problems:
                    if not messagebox.askyesno('Proceed with Warnings', 
                        f'{len(problems)} validation issue(s) detected.\n\nProceed anyway?'):
                        return
                
                # Get selected sync mode
                selected_mode = sync_mode.get()
                
                # Auto-backup before sync (especially important for replace mode)
                if selected_mode == 'replace':
                    # For replace mode, backup is critical
                    backup_status_text = 'Creating backup before replace...'
                else:
                    # For add mode, backup is still good practice
                    backup_status_text = 'Creating backup before sync...'
                
                status_var.set(f"💾 {backup_status_text}")
                root.update()
                
                # Perform auto-backup
                try:
                    if main_server_key == 'deluge':
                        from src.deluge_api import DelugeClient
                        deluge_client = DelugeClient(
                            protocol=getattr(config, 'DELUGE_PROTOCOL', 'http'),
                            host=getattr(config, 'DELUGE_HOST', 'localhost'),
                            port=getattr(config, 'DELUGE_PORT', '8112'),
                            password=getattr(config, 'DELUGE_PASSWORD', ''),
                            verify_ssl=bool(getattr(config, 'DELUGE_VERIFY_SSL', True)),
                        )
                        deluge_client.connect()
                        existing_rules = deluge_client.get_synced_rules()
                        existing_categories = {}
                        existing_feeds = []
                    else:
                        existing_rules = fetch_rules(config.QBT_PROTOCOL, config.QBT_HOST, 
                                                      config.QBT_PORT, config.QBT_USER, 
                                                      config.QBT_PASS)
                        existing_categories = fetch_categories(config.QBT_PROTOCOL, config.QBT_HOST, 
                                                               config.QBT_PORT, config.QBT_USER, 
                                                               config.QBT_PASS)
                        existing_feeds = fetch_feeds(config.QBT_PROTOCOL, config.QBT_HOST, 
                                                      config.QBT_PORT, config.QBT_USER, 
                                                      config.QBT_PASS)
                    
                    metadata = {
                        'sync_mode': selected_mode,
                        'auto_backup': True,
                        'main_server': main_server_key,
                    }
                    
                    backup_success, backup_msg = backup.create_backup(
                        rules=existing_rules or {},
                        categories=existing_categories or {},
                        feeds=existing_feeds or [],
                        metadata=metadata
                    )
                    
                    if backup_success:
                        logger.info(f"Auto-backup created before {selected_mode} sync")
                    else:
                        logger.warning(f"Auto-backup failed: {backup_msg}")
                        # Don't fail the sync if backup fails, just warn the user
                        if selected_mode == 'replace':
                            confirm = messagebox.askyesno(
                                'Backup Warning',
                                f'Could not create backup before replace mode.\n\nBackup error: {backup_msg}\n\nContinue with sync anyway?'
                            )
                            if not confirm:
                                status_var.set('Sync cancelled')
                                return
                
                except Exception as e:
                    logger.warning(f"Failed to create auto-backup: {e}")
                    if selected_mode == 'replace':
                        confirm = messagebox.askyesno(
                            'Backup Warning',
                            f'Could not create backup before replace mode.\n\nError: {e}\n\nContinue with sync anyway?'
                        )
                        if not confirm:
                            status_var.set('Sync cancelled')
                            return
                
                dlg.destroy()
                status_var.set(f"⏳ Syncing {len(preview_list)} rules to {main_server_name}...")
                root.update()
                
                # Check connection mode
                mode = config.CONNECTION_MODE or 'online'
                if mode == 'offline':
                    messagebox.showinfo('Offline Mode', 
                        'In offline mode. Rules would be generated to JSON file only.\n\n'
                        'Use File > Export to save rules.')
                    status_var.set('Offline mode - use Export to save rules')
                    return
                
                # Build rules from the validated preview list
                try:
                    rules_dict = build_rules_from_titles(config.ALL_TITLES)
                    if not rules_dict:
                        messagebox.showwarning('Sync', 'No valid rules to sync.')
                        status_var.set('No rules generated')
                        return
                except Exception as e:
                    messagebox.showerror('Build Error', f'Failed to build rules: {e}')
                    status_var.set('❌ Failed to build rules')
                    return

                if main_server_key == 'deluge':
                    try:
                        from src.deluge_api import DelugeClient
                        deluge_client = DelugeClient(
                            protocol=getattr(config, 'DELUGE_PROTOCOL', 'http'),
                            host=getattr(config, 'DELUGE_HOST', 'localhost'),
                            port=getattr(config, 'DELUGE_PORT', '8112'),
                            password=getattr(config, 'DELUGE_PASSWORD', ''),
                            verify_ssl=bool(getattr(config, 'DELUGE_VERIFY_SSL', True)),
                        )

                        if not deluge_client.connect():
                            status_var.set(f'❌ Failed to connect to {main_server_name}')
                            messagebox.showerror('Connection Failed', f'Could not connect to {main_server_name}.')
                            return

                        success_count, failed_count = deluge_client.sync_rules(rules_dict, selected_mode)

                        status_var.set(f'✅ Synced {success_count} rule(s) for {season} {year}')
                        if failed_count > 0:
                            messagebox.showwarning(
                                'Sync Complete',
                                f'Synced {success_count} rule(s) to {main_server_name}.\n\n'
                                f'{failed_count} rule(s) failed to sync.'
                            )
                        else:
                            messagebox.showinfo(
                                'Sync Complete',
                                f'Successfully synced {success_count} rule(s) to {main_server_name}.\n\n'
                                f'Season: {season} {year}'
                            )
                        return
                    except Exception as e:
                        status_var.set(f'❌ Sync error')
                        messagebox.showerror('Sync Error', f'Failed to sync to {main_server_name}:\n\n{e}')
                        return

                if main_server_key != 'qbittorrent':
                    messagebox.showinfo(
                        'Model Not Yet Supported for Direct Sync',
                        f'Direct sync is currently implemented for qBittorrent and Deluge only.\n\n'
                        f'Current model: {main_server_name}\n'
                        'Use Export to Targets to generate payloads for this model.'
                    )
                    status_var.set(f'ℹ️ Direct sync unavailable for {main_server_name}. Use Export to Targets.')
                    return
                
                # Connect and sync to qBittorrent
                try:
                    api = QBittorrentClient(
                        protocol=config.QBT_PROTOCOL,
                        host=config.QBT_HOST,
                        port=config.QBT_PORT,
                        username=config.QBT_USER,
                        password=config.QBT_PASS,
                        verify_ssl=config.QBT_VERIFY_SSL,
                        ca_cert=getattr(config, 'QBT_CA_CERT', None)
                    )
                    
                    # Connect to qBittorrent
                    if not api.connect():
                        status_var.set(f'❌ Failed to connect to {main_server_name}')
                        messagebox.showerror('Connection Failed', f'Could not connect to {main_server_name}.')
                        return
                    
                    removed_count = 0
                    
                    # If replace mode, remove all existing rules first
                    if selected_mode == 'replace':
                        # Get existing rules
                        existing_rules = api.get_rules()
                        
                        # Remove all existing rules first (to replace them)
                        if existing_rules:
                            for old_rule_name in list(existing_rules.keys()):
                                try:
                                    if api.remove_rule(old_rule_name):
                                        removed_count += 1
                                        status_var.set(f"🗑️ Removing old rules... ({removed_count}/{len(existing_rules)})")
                                        root.update()
                                except Exception as e:
                                    logger.error(f"Failed to remove rule '{old_rule_name}': {e}")
                    
                    # Now add/update the new rules
                    success_count = 0
                    failed_count = 0
                    
                    for rule_name, rule_def in rules_dict.items():
                        try:
                            if api.set_rule(rule_name, rule_def):
                                success_count += 1
                                status_var.set(f"⏳ Synced {success_count}/{len(rules_dict)} rules...")
                                root.update()
                            else:
                                failed_count += 1
                        except Exception as e:
                            logger.error(f"Failed to set rule '{rule_name}': {e}")
                            failed_count += 1
                    
                    # Show results
                    if success_count > 0:
                        if selected_mode == 'replace':
                            msg = f'✅ Successfully replaced {removed_count} old rule(s) with {success_count} new rule(s)!'
                        else:
                            msg = f'✅ Successfully added/updated {success_count} rule(s)!'
                        
                        status_var.set(f'✅ Synced {success_count} rule(s) for {season} {year}')
                        if failed_count > 0:
                            messagebox.showwarning('Sync Complete', 
                                f'{msg}\n\n'
                                f'{failed_count} rule(s) failed to sync.')
                        else:
                            messagebox.showinfo('Sync Complete', 
                                f'{msg}\n\n'
                                f'Season: {season} {year}')
                    else:
                        status_var.set('❌ Sync failed')
                        messagebox.showerror('Sync Failed', f'Failed to sync any rules to {main_server_name}.')
                        
                except Exception as e:
                    status_var.set(f'❌ Sync error')
                    messagebox.showerror('Sync Error', f'Failed to connect to {main_server_name}:\n\n{e}')
                    
            except Exception as e:
                logger.error(f"Error in _do_proceed: {e}")
                messagebox.showerror('Generation Error', f'An error occurred: {e}')

        def _do_cancel():
            """Cancel the operation."""
            try:
                dlg.destroy()
                status_var.set('Sync cancelled')
            except tk.TclError:
                logger.debug("Preview dialog already closed", exc_info=True)

        ttk.Button(btns, text='✓ Proceed & Sync', command=_do_proceed, 
                  style='Accent.TButton').pack(side='right', padx=(5, 0))
        ttk.Button(btns, text='✕ Cancel', command=_do_cancel).pack(side='right')

        dlg.wait_window()

    except Exception as e:
        logger.error(f"Error in dispatch_generation: {e}")
        messagebox.showerror("Generation Error", f"An error occurred: {e}")


__all__ = [
    'normalize_titles_structure',
    'import_titles_from_text',
    'prefix_titles_with_season_year',
    'collect_invalid_folder_titles',
    'auto_sanitize_titles',
    'populate_missing_rule_fields',
    'update_treeview_with_titles',
    'import_titles_from_file',
    'import_titles_from_clipboard',
    'export_selected_titles',
    'export_all_titles',
    'build_rules_from_titles',
    'clear_all_titles',
    'dispatch_generation',
]
