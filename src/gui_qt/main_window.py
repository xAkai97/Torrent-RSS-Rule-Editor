"""
Main Window GUI Module.

This is the primary entry point and orchestrator for the PySide6 user interface.
It implements a massive procedural setup that constructs the main application window,
all tabs (Library, Rule Editor, Configuration), and the overarching signal/slot connections.

Key Responsibilities:
  - Builds the `QMainWindow` and its central layout.
  - Generates the dynamic, customizable Action Bar based on user settings.
  - Binds GUI events to the asynchronous background workers (e.g., `FetchRSSWorker`, `ApplyRulesWorker`).
  - Maintains the UI state (e.g., current active tab, selected tree items).
  - Bridges the UI layer with the `src.services` business logic layer, using the service wrappers defined in this module.

Note: This file is intentionally monolithic by design to avoid complex circular dependencies
between the main shell and its deeply nested tabs.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import os
import sys
import threading

from src.api.qbittorrent import ping_qbittorrent
from src.api.subsplease import (
    can_pull_anilist_cache,
    can_pull_subsplease_cache,
    fetch_subsplease_schedule,
    find_subsplease_title_match,
    load_subsplease_cache,
    load_title_variations_cache,
    refresh_anilist_cache_with_limit,
)
from src.backup import create_backup, extract_backup_metadata, list_backups, load_backup
from src.cache import get_default_templates, load_templates, save_templates
from src.constants import CacheRetentionMode, AniListRefreshScope, FileSystem, PrefKeys
from src.config import config
from src.gui_qt.workers import (
    ApplyRulesWorker,
    AniListRefreshWorker,
    FetchRulesWorker,
    SubsPleaseRefreshWorker,
)
from src.gui_qt.batch_downloader_dialog import BatchDownloaderDialog
from src.gui_qt.theme import get_host_machine_theme, get_effective_theme, apply_app_theme as apply_app_theme_imported
from src.services.connection_status import get_connection_status_text
from src.services.file_operations import _import_titles_core, _snapshot_import_entries, collect_invalid_folder_titles, import_titles_from_text
from src.services.rule_editor import (
    build_rule_editor_feed_state,
    run_anilist_refresh,
    run_subsplease_refresh,
)
from src.services.rule_drafts import commit_rule_enabled_drafts_to_local_titles
from src.services.rule_sync import merge_existing_rule_entries
from src.services.rule_sync_apply import (
    apply_rule_sync_plan,
    build_rule_sync_dry_run,
    format_rule_sync_dry_run_text,
)
from src.services.rules import build_rules_from_titles
from src.services.server_snapshot import (
    format_qbittorrent_snapshot_text,
    load_qbittorrent_snapshot,
)
from src.utils import get_display_title, get_rule_name, sanitize_folder_name
from src.utils import validate_folder_name_by_filesystem

logger = logging.getLogger(__name__)

# Default action bar configuration
DEFAULT_ACTION_BAR_ORDER = [
    "spacer_1", "import", "fetch_rules", "apply", "export", "clear_all", "validate", "separator_1", 
    "batch", "separator_2", "refresh", "refresh_library", "spacer_2", "separator_3", 
    "undo", "enabled", "separator_4", "season_year", "separator_5", "theme", "settings", 
    "spacer_3"
]


SUBACTION_METADATA = {
    "import_file": {"label": "Import File", "icon": "SP_DialogOpenButton", "tooltip": "Import titles/rules from a JSON, CSV, or text file"},
    "import_clipboard": {"label": "Paste Clipboard", "icon": "SP_DialogApplyButton", "tooltip": "Paste and import rule strings directly from the clipboard"},
    "export_selected": {"label": "Export Selected", "icon": "SP_DialogSaveButton", "tooltip": "Export only the selected rule configurations to a file"},
    "export_all": {"label": "Export All", "icon": "SP_DialogSaveButton", "tooltip": "Export all rule configurations to a file"},
    "backup_create": {"label": "Create Backup", "icon": "SP_ComputerIcon", "tooltip": "Create a backup configuration copy of current rules"},
    "backup_restore": {"label": "Restore Backup", "icon": "SP_ComputerIcon", "tooltip": "Restore rules from a previously saved backup file"},
    "backup_manage": {"label": "Manage Backups", "icon": "SP_ComputerIcon", "tooltip": "Open the backup list manager dialog"},
    "templates_apply": {"label": "Apply Template", "icon": "SP_FileDialogListView", "tooltip": "Apply a rule template/preset to the selected rule"},
    "templates_save": {"label": "Save Template", "icon": "SP_FileDialogListView", "tooltip": "Save selected rule parameters as a template"},
    "templates_manage": {"label": "Manage Templates", "icon": "SP_FileDialogListView", "tooltip": "Open the template list manager dialog"},
    "edit_rules_toggle": {"label": "Toggle Selected", "icon": "SP_FileDialogContentsView", "tooltip": "Toggle enabled status of selected rules"},
    "edit_rules_bulk": {"label": "Bulk Edit", "icon": "SP_FileDialogContentsView", "tooltip": "Bulk edit parameters of selected rules"},
    "edit_rules_batch_title": {"label": "Batch Edit Title", "icon": "SP_FileDialogContentsView", "tooltip": "Batch edit title variations"},
    "edit_rules_batch_apply": {"label": "Batch Apply Matches", "icon": "SP_DialogApplyButton", "tooltip": "Batch apply matching SubsPlease titles to selected rules"},
    "refresh_subsplease": {"label": "Refresh SubsPlease", "icon": "SP_BrowserReload", "tooltip": "Refresh current SubsPlease anime release schedules cache from the API"},
    "refresh_anilist": {"label": "Refresh AniList", "icon": "SP_BrowserReload", "tooltip": "Refresh AniList title variations and language-specific alias cache for the selected title"}
}


DEFAULT_DROPDOWN_SUBACTIONS = {
    "import": ["import_file", "import_clipboard"],
    "export": ["export_selected", "export_all"],
    "backup": ["backup_create", "backup_restore", "backup_manage"],
    "templates": ["templates_apply", "templates_save", "templates_manage"],
    "edit_rules": ["edit_rules_toggle", "edit_rules_bulk", "edit_rules_batch_title", "edit_rules_batch_apply"],
    "refresh": ["refresh_subsplease", "refresh_anilist"]
}


DEFAULT_BUTTON_METADATA = {
    "import": {"label": "Import", "icon": "SP_DialogOpenButton"},
    "fetch_rules": {"label": "Fetch Rules", "icon": "SP_ArrowDown"},
    "apply": {"label": "Apply Rules", "icon": "SP_DialogSaveButton"},
    "batch": {"label": "Batch Downloader", "icon": "SP_DriveNetIcon"},
    "refresh": {"label": "Refresh API Cache", "icon": "SP_BrowserReload"},
    "undo": {"label": "Undo", "icon": "SP_ArrowLeft"},
    "enabled": {"label": "Enabled", "icon": ""},
    "clear_all": {"label": "Clear All", "icon": "SP_DialogDiscardButton"},
    "validate": {"label": "Validate", "icon": "SP_DialogApplyButton"},
    "trash": {"label": "View Trash", "icon": "SP_TrashIcon"},
    "export": {"label": "Export", "icon": "SP_DialogSaveButton"},
    "theme": {"label": "Theme", "icon": "SP_TitleBarMenuButton"},
    "settings": {"label": "Settings", "icon": "SP_DialogHelpButton"},
    "refresh_library": {"label": "Refresh", "icon": "SP_BrowserReload"},
    "backup": {"label": "Backup", "icon": "SP_ComputerIcon"},
    "templates": {"label": "Templates", "icon": "SP_FileDialogListView"},
    "edit_rules": {"label": "Edit Rules", "icon": "SP_FileDialogContentsView"},
    "view_logs": {"label": "View Logs", "icon": "SP_MessageBoxInformation"},
    "api_cache_viewer": {"label": "API Cache Viewer", "icon": "SP_FileDialogListView"},
    "setup_wizard": {"label": "Setup Wizard", "icon": "SP_ComputerIcon"},
    "shortcuts_help": {"label": "Help Shortcuts", "icon": "SP_MessageBoxQuestion"},
    "batch_apply": {"label": "Batch Apply Titles", "icon": "SP_DialogApplyButton"},
    # Sub-actions
    "import_file": {"label": "Import File", "icon": "SP_DialogOpenButton"},
    "import_clipboard": {"label": "Paste Clipboard", "icon": "SP_DialogApplyButton"},
    "export_selected": {"label": "Export Selected", "icon": "SP_DialogSaveButton"},
    "export_all": {"label": "Export All", "icon": "SP_DialogSaveButton"},
    "backup_create": {"label": "Create Backup", "icon": "SP_ComputerIcon"},
    "backup_restore": {"label": "Restore Backup", "icon": "SP_ComputerIcon"},
    "backup_manage": {"label": "Manage Backups", "icon": "SP_ComputerIcon"},
    "templates_apply": {"label": "Apply Template", "icon": "SP_FileDialogListView"},
    "templates_save": {"label": "Save Template", "icon": "SP_FileDialogListView"},
    "templates_manage": {"label": "Manage Templates", "icon": "SP_FileDialogListView"},
    "edit_rules_toggle": {"label": "Toggle Selected", "icon": "SP_FileDialogContentsView"},
    "edit_rules_bulk": {"label": "Bulk Edit", "icon": "SP_FileDialogContentsView"},
    "edit_rules_batch_title": {"label": "Batch Edit Title", "icon": "SP_FileDialogContentsView"},
    "edit_rules_batch_apply": {"label": "Batch Apply Matches", "icon": "SP_DialogApplyButton"},
    "refresh_subsplease": {"label": "Refresh SubsPlease", "icon": "SP_BrowserReload"},
    "refresh_anilist": {"label": "Refresh AniList", "icon": "SP_BrowserReload"}
}

STANDARD_ICONS = {
    'SP_DialogOpenButton': 'Open Folder/File',
    'SP_DialogSaveButton': 'Save',
    'SP_DialogDiscardButton': 'Discard/Clear',
    'SP_DialogApplyButton': 'Apply/Ok',
    'SP_DialogCancelButton': 'Cancel',
    'SP_DialogOkButton': 'Checkmark/Ok',
    'SP_ArrowLeft': 'Arrow Left',
    'SP_ArrowRight': 'Arrow Right',
    'SP_ArrowUp': 'Arrow Up',
    'SP_ArrowDown': 'Arrow Down',
    'SP_BrowserReload': 'Reload/Refresh',
    'SP_BrowserStop': 'Stop',
    'SP_TrashIcon': 'Trash/Delete',
    'SP_DriveNetIcon': 'Network Drive',
    'SP_ComputerIcon': 'Computer',
    'SP_FileIcon': 'File',
    'SP_DirOpenIcon': 'Open Directory',
    'SP_MessageBoxInformation': 'Info',
    'SP_MessageBoxQuestion': 'Question',
    'SP_MessageBoxWarning': 'Warning',
    'SP_MediaPlay': 'Play',
    'SP_MediaStop': 'Stop',
    'SP_MediaPause': 'Pause',
    'SP_FileDialogListView': 'List View',
    'SP_CommandLink': 'Command Link'
}

# ============================================================================
# SERVICE WRAPPERS (Full parity with shared services)
# ============================================================================

def build_rule_editor_preview_text(
    current_title: str,
    current_must: str,
    state_builder=build_rule_editor_feed_state,
) -> str:
    """Build a readable preview string from the shared Rule Editor feed service."""
    state = state_builder(
        current_title=current_title,
        current_must=current_must,
        find_subsplease_title_match=find_subsplease_title_match,
        load_title_variations_cache=load_title_variations_cache,
    )

    status = str(state.get('status', '') or '')
    subsplease_title = str(state.get('subsplease_title', '') or '')
    aliases = [str(a).strip() for a in (state.get('aliases', []) or []) if str(a).strip()]

    lines = [
        'Service-backed Rule Editor Feed Preview',
        f'Title: {str(current_title or "").strip()}',
        f'Match Pattern: {str(current_must or "").strip()}',
        '',
        f'Status: {status}',
        f'SubsPlease Match: {subsplease_title}',
        f'AniList Variations: {len(aliases)}',
    ]
    if aliases:
        lines.append('')
        lines.extend([f'- {alias}' for alias in aliases])
    return '\n'.join(lines)


def run_qt_subsplease_refresh() -> dict[str, object]:
    """Run SubsPlease refresh through shared Rule Editor service wrappers."""
    return run_subsplease_refresh(
        force_refresh=True,
        can_pull_subsplease_cache=can_pull_subsplease_cache,
        fetch_subsplease_schedule=fetch_subsplease_schedule,
    )


def run_qt_anilist_refresh(
    current_title: str,
    current_must: str,
    selected_season: str,
    selected_year: str,
    refresh_scope_override: str,
) -> dict[str, object]:
    """Run AniList refresh through shared Rule Editor service wrappers."""
    return run_anilist_refresh(
        can_pull_anilist_cache=can_pull_anilist_cache,
        load_subsplease_cache=load_subsplease_cache,
        refresh_anilist_cache_with_limit=refresh_anilist_cache_with_limit,
        current_title=current_title,
        current_must=current_must,
        selected_season=selected_season,
        selected_year=selected_year,
        refresh_scope_override=refresh_scope_override,
    )


def format_refresh_result_text(source: str, result: dict[str, object]) -> str:
    """Render a readable status block for refresh action results."""
    fetch_status = str(result.get('fetch_status', '') or '')
    app_status = str(result.get('app_status', '') or '')
    should_update = bool(result.get('should_update_variations', False))

    lines = [
        f'{source} refresh result',
        f'Fetch Status: {fetch_status}',
        f'App Status: {app_status}',
        f'Update Variations: {should_update}',
    ]
    return '\n'.join(lines)


def run_qt_qbittorrent_snapshot() -> dict[str, object]:
    """Load a qBittorrent snapshot through the shared server snapshot service."""
    return load_qbittorrent_snapshot()


def run_qt_connection_test() -> dict[str, object]:
    """Test the current qBittorrent connection settings."""
    settings = run_qt_get_connection_settings()
    if str(settings.get('mode', 'online')) == 'offline':
        return {'success': True, 'message': 'Offline mode selected; connection test skipped.'}
    ok, message = ping_qbittorrent(
        str(settings.get('protocol', 'http')),
        str(settings.get('host', '') or ''),
        str(settings.get('port', '8080')),
        str(settings.get('username', '') or ''),
        str(settings.get('password', '') or ''),
        bool(settings.get('verify_ssl', True)),
        str(settings.get('ca_cert', '') or '') or None,
    )
    return {
        'success': bool(ok),
        'message': str(message or ('Connection successful.' if ok else 'Connection failed.')),
        'status_text': get_connection_status_text(config),
    }


def apply_template_data_to_rule(rule: dict[str, object], template: dict[str, object]) -> dict[str, object]:
    """Apply template data to a rule dictionary in place."""
    if not isinstance(rule, dict) or not isinstance(template, dict):
        return rule
    for key in ('enabled', 'assignedCategory', 'mustContain', 'mustNotContain', 'savePath', 'affectedFeeds'):
        if key in template:
            rule[key] = copy.deepcopy(template[key])
    if isinstance(template.get('torrentParams'), dict):
        torrent_params = dict(rule.get('torrentParams', {}) or {}) if isinstance(rule.get('torrentParams', {}), dict) else {}
        torrent_params.update(copy.deepcopy(template['torrentParams']))
        rule['torrentParams'] = torrent_params
    node = rule.get('node') if isinstance(rule.get('node'), dict) else {}
    if isinstance(node, dict):
        title = template.get('title') or template.get('ruleName') or node.get('title')
        if title:
            node['title'] = title
            rule['node'] = node
    if 'ruleName' in template and template['ruleName']:
        rule['ruleName'] = template['ruleName']
    return rule


def run_qt_get_connection_settings() -> dict[str, object]:
    """Return current qBittorrent connection settings for Qt form population."""
    return {
        'protocol': str(getattr(config, 'QBT_PROTOCOL', 'http') or 'http'),
        'host': str(getattr(config, 'QBT_HOST', '') or ''),
        'port': str(getattr(config, 'QBT_PORT', '8080') or '8080'),
        'username': str(getattr(config, 'QBT_USER', '') or ''),
        'password': str(getattr(config, 'QBT_PASS', '') or ''),
        'mode': str(getattr(config, 'CONNECTION_MODE', 'online') or 'online'),
        'verify_ssl': bool(getattr(config, 'QBT_VERIFY_SSL', True)),
        'ca_cert': str(getattr(config, 'QBT_CA_CERT', '') or ''),
    }


def run_qt_save_connection_settings(
    settings: dict[str, object],
    save_config_fn=None,
) -> dict[str, object]:
    """Persist qBittorrent connection settings from Qt form values."""
    protocol = str(settings.get('protocol', 'http') or 'http').strip().lower()
    if protocol not in {'http', 'https'}:
        protocol = 'http'
    mode = str(settings.get('mode', 'online') or 'online').strip().lower()
    if mode not in {'online', 'offline', 'auto'}:
        mode = 'online'
    host = str(settings.get('host', '') or '').strip()
    port = str(settings.get('port', '8080') or '8080').strip() or '8080'
    username = str(settings.get('username', '') or '')
    password = str(settings.get('password', '') or '')
    verify_ssl = bool(settings.get('verify_ssl', True))
    ca_cert = str(settings.get('ca_cert', getattr(config, 'QBT_CA_CERT', '') or '') or '').strip()
    default_save_path = str(settings.get('default_save_path', getattr(config, 'DEFAULT_SAVE_PATH', '') or '') or '')
    default_category = str(settings.get('default_category', getattr(config, 'DEFAULT_CATEGORY', '') or '') or '')
    default_download_path = str(settings.get('default_download_path', getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or '') or '')
    default_feeds_raw = settings.get('default_affected_feeds', getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or [])
    if isinstance(default_feeds_raw, str):
        default_affected_feeds = [v.strip() for v in default_feeds_raw.split(',') if v.strip()]
    elif isinstance(default_feeds_raw, list):
        default_affected_feeds = [str(v).strip() for v in default_feeds_raw if str(v).strip()]
    else:
        default_affected_feeds = []

    # save_config reads DEFAULT_DOWNLOAD_PATH from config object
    config.DEFAULT_DOWNLOAD_PATH = default_download_path
    config.QBT_CA_CERT = ca_cert or None

    save_fn = save_config_fn or config.save_config
    ok = bool(
        save_fn(
            protocol,
            host,
            port,
            username,
            password,
            mode,
            verify_ssl,
            default_save_path=default_save_path,
            default_category=default_category,
            default_affected_feeds=default_affected_feeds,
        )
    )
    return {
        'success': ok,
        'message': 'Connection settings saved.' if ok else 'Failed to save connection settings.',
        'status_text': get_connection_status_text(config),
    }

# Themes are now loaded from src/gui_qt/theme.py


def run_qt_get_runtime_settings() -> dict[str, object]:
    """Return current runtime/UI preferences for Qt settings controls."""
    theme = str(config.get_pref('theme', 'light') or 'light').strip().lower()
    if theme not in {'light', 'dark', 'auto'}:
        theme = 'light'
    log_level = str(config.get_pref('log_level', 'INFO') or 'INFO').strip().upper()
    if log_level not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
        log_level = 'INFO'
    ui_style = str(config.get_pref(PrefKeys.UI_STYLE_THEME, 'clam') or 'clam').strip()
    if not ui_style:
        ui_style = 'clam'
    return {
        'theme': theme,
        'log_level': log_level,
        'ui_style_theme': ui_style,
    }


def run_qt_save_runtime_settings(
    settings: dict[str, object],
    set_pref_fn=None,
) -> dict[str, object]:
    """Persist runtime/UI preferences from Qt controls."""
    theme = str(settings.get('theme', 'light') or 'light').strip().lower()
    if theme not in {'light', 'dark', 'auto'}:
        theme = 'light'
    log_level = str(settings.get('log_level', 'INFO') or 'INFO').strip().upper()
    if log_level not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
        log_level = 'INFO'
    ui_style = str(settings.get('ui_style_theme', 'clam') or 'clam').strip() or 'clam'

    set_pref = set_pref_fn or config.set_pref
    ok_theme = bool(set_pref('theme', theme))
    ok_level = bool(set_pref('log_level', log_level))
    ok_style = bool(set_pref(PrefKeys.UI_STYLE_THEME, ui_style))
    success = ok_theme and ok_level and ok_style

    return {
        'success': success,
        'message': 'Runtime settings saved.' if success else 'Failed to save runtime settings.',
        'theme': theme,
        'log_level': log_level,
        'ui_style_theme': ui_style,
    }


def run_qt_get_platform_settings() -> dict[str, object]:
    """Return current platform/main-server export settings for Qt controls."""
    supported = list(getattr(config, 'SUPPORTED_SERVERS', ['qbittorrent']) or [])
    supported = [str(v).strip().lower() for v in supported if str(v).strip()]
    if not supported:
        supported = ['qbittorrent']
    main_server = str(getattr(config, 'MAIN_SERVER', 'qbittorrent') or 'qbittorrent').strip().lower()
    if main_server not in supported:
        main_server = 'qbittorrent'
    export_targets_raw = getattr(config, 'EXPORT_TARGETS', ['qbittorrent']) or ['qbittorrent']
    export_targets = [str(v).strip().lower() for v in export_targets_raw if str(v).strip().lower() in supported]
    if not export_targets:
        export_targets = ['qbittorrent']
    return {
        'main_server': main_server,
        'export_targets': export_targets,
        'supported_servers': supported,
    }


def run_qt_save_platform_settings(
    settings: dict[str, object],
    save_platform_config_fn=None,
) -> dict[str, object]:
    """Persist platform/main-server export settings from Qt controls."""
    supported = list(getattr(config, 'SUPPORTED_SERVERS', ['qbittorrent']) or [])
    supported = [str(v).strip().lower() for v in supported if str(v).strip()]
    if not supported:
        supported = ['qbittorrent']
    main_server = str(settings.get('main_server', 'qbittorrent') or 'qbittorrent').strip().lower()
    if main_server not in supported:
        main_server = 'qbittorrent'
    raw_targets = settings.get('export_targets', ['qbittorrent']) or ['qbittorrent']
    normalized_targets: list[str] = []
    for target in (raw_targets if isinstance(raw_targets, list) else [raw_targets]):
        key = str(target or '').strip().lower()
        if key in supported and key not in normalized_targets:
            normalized_targets.append(key)
    if not normalized_targets:
        normalized_targets = ['qbittorrent']
    save_fn = save_platform_config_fn or config.save_platform_config
    ok = bool(save_fn(main_server, normalized_targets))
    return {
        'success': ok,
        'message': 'Platform settings saved.' if ok else 'Failed to save platform settings.',
        'main_server': main_server,
        'export_targets': normalized_targets,
    }


def run_qt_load_log_tail(log_file_path: str = None, max_lines: int = 300) -> dict[str, object]:
    """Load latest log lines for Qt log viewer panel."""
    default_log = getattr(config, 'LOG_FILE', 'data/qbt_editor.log')
    path = str(log_file_path or default_log).strip() or default_log
    line_limit = max(1, int(max_lines or 1))
    if not os.path.exists(path):
        return {
            'success': False,
            'message': f'Log file not found: {path}',
            'content': '',
            'line_count': 0,
        }
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
    except Exception as exc:
        return {
            'success': False,
            'message': f'Failed to read log file: {exc}',
            'content': '',
            'line_count': 0,
        }
    tail = lines[-line_limit:]
    content = ''.join(tail)
    return {
        'success': True,
        'message': f'Loaded {len(tail)} line(s) from log.',
        'content': content,
        'line_count': len(tail),
    }


def run_qt_clear_log_file(log_file_path: str = None) -> dict[str, object]:
    """Truncate application log file used by log viewer actions."""
    default_log = getattr(config, 'LOG_FILE', 'data/qbt_editor.log')
    path = str(log_file_path or default_log).strip() or default_log
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('')
        return {'success': True, 'message': f'Cleared log file: {path}'}
    except Exception as exc:
        return {'success': False, 'message': f'Failed to clear log file: {exc}'}


def run_qt_import_titles_from_text(
    text: str,
    season: str = '',
    year: str = '',
    prefix_imports: bool = False,
    source_name: str = 'qt text',
) -> dict[str, object]:
    """Import titles from provided text payload (clipboard/manual)."""
    parsed = import_titles_from_text(str(text or ''))
    if not parsed:
        return {
            'success': False,
            'message': 'Failed to parse import data from text.',
            'new_count': 0,
            'duplicates': 0,
            'total_titles': sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list)),
        }
    if not isinstance(parsed, dict):
        return {
            'success': False,
            'message': 'Failed to parse import data from text.',
            'new_count': 0,
            'duplicates': 0,
            'total_titles': sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list)),
        }
    result = _import_titles_core(
        parsed,
        season=str(season or '').strip(),
        year=str(year or '').strip(),
        prefix_imports=bool(prefix_imports),
        source_name=str(source_name or 'qt text'),
        auto_sanitize_override=None,
    )
    if isinstance(result, tuple) and len(result) >= 4:
        success_t, message_t, new_count_t, dup_t = result[:4]
        return {
            'success': bool(success_t),
            'message': str(message_t or 'Import completed.'),
            'new_count': int(new_count_t or 0),
            'duplicates': int(dup_t or 0),
            'total_titles': sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list)),
        }
    return {
        'success': bool(result.get('success', False)) if isinstance(result, dict) else True,
        'message': str(result.get('message', '') or 'Import completed.') if isinstance(result, dict) else 'Import completed.',
        'new_count': int(result.get('new_count', 0) or 0) if isinstance(result, dict) else 0,
        'duplicates': int(result.get('duplicates', 0) or 0) if isinstance(result, dict) else 0,
        'total_titles': sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list)),
    }


def run_qt_import_titles_from_path(path: str, season: str = '', year: str = '', prefix_imports: bool = False) -> dict[str, object]:
    """Import titles from a JSON/CSV/TXT file path for Qt shell flows."""
    file_path = str(path or '').strip()
    if not file_path or not os.path.exists(file_path):
        return {
            'success': False,
            'message': f'Import file not found: {file_path}',
            'new_count': 0,
            'duplicates': 0,
            'total_titles': 0,
        }
    try:
        with open(file_path, 'r', encoding='utf-8') as fh:
            text = fh.read()
        return run_qt_import_titles_from_text(text, season=season, year=year, prefix_imports=prefix_imports, source_name='qt file')
    except Exception as exc:
        return {
            'success': False,
            'message': f'Failed to read import file: {exc}',
            'new_count': 0,
            'duplicates': 0,
            'total_titles': 0,
        }


def run_qt_import_dropped_paths(
    paths: list[str],
    season: str = '',
    year: str = '',
    prefix_imports: bool = False,
    import_from_path_fn=None,
) -> dict[str, object]:
    """Import dropped files and return aggregated status payload."""
    importer = import_from_path_fn or run_qt_import_titles_from_path
    allowed_exts = {'.json', '.csv', '.txt'}
    attempted = 0
    imported = 0
    failed = 0
    skipped = 0
    details: list[str] = []

    for raw_path in paths or []:
        file_path = str(raw_path or '').strip()
        if not file_path:
            skipped += 1
            continue
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in allowed_exts:
            skipped += 1
            details.append(f'Skipped unsupported file type: {file_path}')
            continue
        if not os.path.exists(file_path):
            failed += 1
            details.append(f'File not found: {file_path}')
            continue

        attempted += 1
        result = importer(file_path, season=season, year=year, prefix_imports=prefix_imports)
        ok = bool(result.get('success', False)) if isinstance(result, dict) else False
        msg = str(result.get('message', '') or '') if isinstance(result, dict) else ''
        if ok:
            imported += 1
        else:
            failed += 1
        if msg:
            details.append(f'{os.path.basename(file_path)}: {msg}')

    summary = f'Imported {imported}/{attempted} dropped file(s).'
    if skipped > 0:
        summary += f' Skipped: {skipped}.'
    if failed > 0:
        summary += f' Failed: {failed}.'

    return {
        'success': imported > 0 and failed == 0,
        'imported_count': imported,
        'attempted_count': attempted,
        'failed_count': failed,
        'skipped_count': skipped,
        'message': summary,
        'details': details,
    }


_auto_save_timer = None
_auto_save_lock = threading.Lock()

def auto_save_rules() -> None:
    """Auto-save current rules to data/qbittorrent_rules.json in a background thread."""
    global _auto_save_timer
    
    data = getattr(config, 'ALL_TITLES', None)
    if not isinstance(data, dict):
        return

    try:
        data_copy = copy.deepcopy(data)
    except Exception as e:
        logger.error(f"Auto-save: Failed to duplicate ALL_TITLES: {e}")
        return

    def save_worker(data_to_save):
        """Save worker helper function."""
        with _auto_save_lock:
            try:
                export_map = build_rules_from_titles(data_to_save)
                file_path = getattr(config, 'OUTPUT_CONFIG_FILE_NAME', os.path.join('data', 'qbittorrent_rules.json'))
                with open(file_path, 'w', encoding='utf-8') as fh:
                    json.dump(export_map, fh, indent=4, ensure_ascii=False)
                logger.debug(f"Auto-save complete: saved {len(export_map)} rules to {file_path}")
            except Exception as exc:
                logger.error(f"Auto-save thread failure: {exc}")

    with _auto_save_lock:
        if _auto_save_timer is not None:
            _auto_save_timer.cancel()
        _auto_save_timer = threading.Timer(0.5, save_worker, args=(data_copy,))
        _auto_save_timer.daemon = True
        _auto_save_timer.start()


def run_qt_clear_all_titles() -> dict[str, object]:
    """Clear all locally loaded titles in config state."""
    all_titles = getattr(config, 'ALL_TITLES', None) or {}
    existing_count = sum(len(v) for v in all_titles.values() if isinstance(v, list)) if isinstance(all_titles, dict) else 0
    config.ALL_TITLES = {}
    auto_save_rules()
    return {
        'success': True,
        'message': f'Cleared all loaded titles ({existing_count}).',
        'cleared_count': existing_count,
    }



def run_qt_export_all_titles_to_path(path: str) -> dict[str, object]:
    """Export all loaded titles to JSON file path for Qt shell flows."""
    file_path = str(path or '').strip()
    if not file_path:
        return {'success': False, 'message': 'Export path is required.', 'exported_rules': 0}
    data = getattr(config, 'ALL_TITLES', None) or {}
    if not isinstance(data, dict) or not data:
        return {'success': False, 'message': 'No titles available to export.', 'exported_rules': 0}
    try:
        export_map = build_rules_from_titles(data)
        with open(file_path, 'w', encoding='utf-8') as fh:
            json.dump(export_map, fh, indent=4, ensure_ascii=False)
        return {
            'success': True,
            'message': f'Exported {len(export_map)} rule(s) to {file_path}',
            'exported_rules': len(export_map),
        }
    except Exception as exc:
        return {
            'success': False,
            'message': f'Failed to export titles: {exc}',
            'exported_rules': 0,
        }


def build_qt_target_export_payload(target: str, rules_dict: dict[str, dict[str, object]]) -> dict[str, object]:
    """Build target-specific export payloads for qBittorrent/Autobrr."""
    target_norm = str(target or '').strip().lower()

    if target_norm == 'qbittorrent':
        return rules_dict

    rule_items: list[dict[str, object]] = []
    for rule_name, rule in (rules_dict or {}).items():
        rule_items.append(
            {
                'name': str(rule_name),
                'enabled': bool(rule.get('enabled', True)) if isinstance(rule, dict) else True,
                'must_contain': (rule.get('mustContain', '') if isinstance(rule, dict) else ''),
                'must_not_contain': (rule.get('mustNotContain', '') if isinstance(rule, dict) else ''),
                'save_path': (rule.get('savePath', '') if isinstance(rule, dict) else ''),
                'category': (rule.get('assignedCategory', '') if isinstance(rule, dict) else ''),
                'affected_feeds': (rule.get('affectedFeeds', []) if isinstance(rule, dict) else []),
                'torrent_params': (rule.get('torrentParams', {}) if isinstance(rule, dict) else {}),
            }
        )

    return {
        'target': target_norm,
        'version': '1.0',
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'rule_count': len(rule_items),
        'rules': rule_items,
    }


def build_qt_library_rows(all_titles: dict[str, list[object]] | None = None) -> list[dict[str, str]]:
    """Build flat rows from loaded ALL_TITLES for Qt library table display."""
    titles = all_titles if isinstance(all_titles, dict) else (getattr(config, 'ALL_TITLES', {}) or {})
    rows: list[dict[str, str]] = []
    for media_type, items in titles.items():
        if not isinstance(items, list):
            continue
        for entry in items:
            rows.append(
                {
                    'media_type': str(media_type),
                    'title': str(get_display_title(entry, '') or '').strip(),
                    'rule_name': str(get_rule_name(entry, '') or '').strip(),
                    'must_contain': str((entry.get('mustContain', '') if isinstance(entry, dict) else '') or '').strip(),
                }
            )
    return rows


def run_qt_remove_titles_by_rule_names(rule_names: list[str]) -> dict[str, object]:
    """Remove selected entries from ALL_TITLES by rule name/title matching."""
    targets = {str(name or '').strip() for name in (rule_names or []) if str(name or '').strip()}
    if not targets:
        return {'success': False, 'message': 'No rule names selected.', 'removed_count': 0, 'remaining_count': 0}
    all_titles = getattr(config, 'ALL_TITLES', None) or {}
    if not isinstance(all_titles, dict) or not all_titles:
        return {'success': False, 'message': 'No loaded titles available.', 'removed_count': 0, 'remaining_count': 0}
    removed_count = 0
    next_titles: dict[str, list[object]] = {}
    for media_type, items in all_titles.items():
        if not isinstance(items, list):
            continue
        kept: list[object] = []
        for entry in items:
            key_a = str(get_rule_name(entry, '') or '').strip()
            key_b = str(get_display_title(entry, '') or '').strip()
            if key_a in targets or key_b in targets:
                removed_count += 1
                continue
            kept.append(entry)
        if kept:
            next_titles[str(media_type)] = kept
    if removed_count <= 0:
        remaining_count = sum(len(v) for v in all_titles.values() if isinstance(v, list))
        return {
            'success': False,
            'message': 'No matching library entries found to remove.',
            'removed_count': 0,
            'remaining_count': remaining_count,
        }
    config.ALL_TITLES = next_titles
    auto_save_rules()
    remaining_count = sum(len(v) for v in next_titles.values() if isinstance(v, list))
    return {
        'success': True,
        'message': f'Removed {removed_count} title(s) from local library.',
        'removed_count': removed_count,
        'remaining_count': remaining_count,
    }


def run_qt_export_selected_titles_to_path(path: str, rule_names: list[str]) -> dict[str, object]:
    """Export selected titles from ALL_TITLES by rule name/title matching."""
    file_path = str(path or '').strip()
    if not file_path:
        return {'success': False, 'message': 'Export path is required.', 'exported_rules': 0}
    targets = {str(name or '').strip() for name in (rule_names or []) if str(name or '').strip()}
    if not targets:
        return {'success': False, 'message': 'No rule names selected for export.', 'exported_rules': 0}
    all_titles = getattr(config, 'ALL_TITLES', None) or {}
    if not isinstance(all_titles, dict) or not all_titles:
        return {'success': False, 'message': 'No loaded titles available.', 'exported_rules': 0}
    selected_titles: dict[str, list[object]] = {}
    for media_type, items in all_titles.items():
        if not isinstance(items, list):
            continue
        selected: list[object] = []
        for entry in items:
            key_a = str(get_rule_name(entry, '') or '').strip()
            key_b = str(get_display_title(entry, '') or '').strip()
            if key_a in targets or key_b in targets:
                selected.append(entry)
        if selected:
            selected_titles[str(media_type)] = selected
    if not selected_titles:
        return {'success': False, 'message': 'No matching titles found for selected export.', 'exported_rules': 0}
    try:
        export_map = build_rules_from_titles(selected_titles)
        with open(file_path, 'w', encoding='utf-8') as fh:
            json.dump(export_map, fh, indent=4, ensure_ascii=False)
        return {
            'success': True,
            'message': f'Exported {len(export_map)} selected rule(s) to {file_path}',
            'exported_rules': len(export_map),
        }
    except Exception as exc:
        return {
            'success': False,
            'message': f'Failed to export selected titles: {exc}',
            'exported_rules': 0,
        }


def run_qt_commit_rule_drafts(rule_rows: list[dict[str, str]]) -> dict[str, object]:
    """Commit draft rule states to in-memory local titles only."""
    res = commit_rule_enabled_drafts_to_local_titles(rule_rows)
    if isinstance(res, dict) and res.get('updated_count', 0) > 0:
        auto_save_rules()
    return res


def run_qt_rule_sync_dry_run(
    rule_rows: list[dict[str, str]],
    selected_rule_names: list[str],
    server_rules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, object]:
    """Build phase 4 dry-run summary for selected draft rows."""
    if server_rules is None:
        server_rules = getattr(config, 'SERVER_RULES_SNAPSHOT', None)
    return build_rule_sync_dry_run(
        rule_rows=rule_rows,
        selected_rule_names=selected_rule_names,
        server_rules=server_rules,
    )


def run_qt_apply_rule_sync(changes: list[dict[str, object]]) -> dict[str, object]:
    """Apply confirmed sync plan to qBittorrent."""
    return apply_rule_sync_plan(changes)


def run_qt_batch_apply_subsplease(
    rule_names: list[str],
    update_match: bool,
    update_title: bool,
    update_path: bool,
    on_before_update = None
) -> dict[str, object]:
    """
    Headless service wrapper to batch apply SubsPlease matches to the specified rules.
    """
    if not rule_names:
        return {'success': False, 'message': 'No rules selected.', 'updated_count': 0}
        
    if not (update_match or update_title or update_path):
        return {'success': False, 'message': 'No fields selected to update.', 'updated_count': 0}

    all_titles = getattr(config, 'ALL_TITLES', None)
    if not isinstance(all_titles, dict):
        return {'success': False, 'message': 'Library is empty.', 'updated_count': 0}

    changed_count = 0
    updated_rules = []
    unmatched_rules = []
    
    import re
    # Patterns to preserve prefixes
    season_prefix_pattern = re.compile(r'^(\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*)', re.IGNORECASE)
    save_path_prefix_pattern = re.compile(r'^((?:spring|summer|fall|winter)\s+\d{4}/)', re.IGNORECASE)

    rule_names_set = set(rule_names)

    for category, items in all_titles.items():
        if not isinstance(items, list):
            continue
        for rule in items:
            if not isinstance(rule, dict):
                continue
            
            rule_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or '').strip()
            if not rule_name or rule_name not in rule_names_set:
                continue

            sp_match = find_subsplease_title_match(rule_name)
            if sp_match:
                if on_before_update:
                    on_before_update(rule_name, copy.deepcopy(rule))

                # Update the rule dict
                if update_match:
                    rule['mustContain'] = sp_match
                    if not isinstance(rule.get('torrentParams'), dict):
                        rule['torrentParams'] = {}
                    rule['torrentParams']['must_contain'] = sp_match

                if update_title:
                    m = season_prefix_pattern.match(rule_name)
                    prefix = m.group(1) if m else ""
                    new_title = prefix + sp_match
                    rule['ruleName'] = new_title
                    if 'node' not in rule or not isinstance(rule['node'], dict):
                        rule['node'] = {}
                    rule['node']['title'] = new_title

                if update_path:
                    current_path = rule.get('savePath', '') or rule.get('torrentParams', {}).get('save_path', '') or ''
                    m = save_path_prefix_pattern.match(current_path)
                    prefix = m.group(1) if m else ""
                    clean_val = sanitize_folder_name(sp_match)
                    new_path = prefix + clean_val
                    rule['savePath'] = new_path
                    if not isinstance(rule.get('torrentParams'), dict):
                        rule['torrentParams'] = {}
                    rule['torrentParams']['save_path'] = new_path

                changed_count += 1
                updated_rules.append(f"• {rule_name} → {sp_match}")
            else:
                unmatched_rules.append(f"• {rule_name}")

    if changed_count > 0:
        auto_save_rules()
        return {
            'success': True,
            'message': f"Successfully matched and updated {changed_count} rule(s).",
            'updated_count': changed_count,
            'updated_rules': updated_rules,
            'unmatched_rules': unmatched_rules
        }
    else:
        return {
            'success': False,
            'message': "No matches found in the SubsPlease schedule cache.",
            'updated_count': 0,
            'unmatched_rules': unmatched_rules
        }


def setup_gui_qt() -> None:
    """
    Start a PySide6 main window shaped to match Tk app structure.

    This function is intentionally monolithic to prevent circular dependencies
    between the UI layout, the action bar, the tabs, and the event handlers.
    
    Structure Overview:
    1. Icon Generation: Creates SVG icons on the fly.
    2. Data Loading: Pre-warms cache and settings via `config`.
    3. Window Initialization: Creates the QMainWindow and central layout.
    4. Sub-Component Definitions:
       - Toolbar/Action Bar generation routines
       - Library Tree View (Left Pane)
       - Rule Editor (Right Pane)
    5. Event Handlers: Dozens of closures (e.g., `_action_import_file`)
       that act as the glue between Qt signals and the background workers.
    6. Background Workers: Connects UI signals to `ApplyRulesWorker`, `FetchRSSWorker`, etc.
    """
    import tempfile
    temp_dir = tempfile.gettempdir()
    checkmark_path = os.path.join(temp_dir, 'qbt_checkmark.svg').replace('\\', '/')
    radio_path = os.path.join(temp_dir, 'qbt_radio_dot.svg').replace('\\', '/')
    down_arrow_path = os.path.join(temp_dir, 'qbt_down_arrow.svg').replace('\\', '/')
    up_arrow_path = os.path.join(temp_dir, 'qbt_up_arrow.svg').replace('\\', '/')
    theme_light_path = os.path.join(temp_dir, 'qbt_theme_light.svg').replace('\\', '/')
    theme_dark_path = os.path.join(temp_dir, 'qbt_theme_dark.svg').replace('\\', '/')
    theme_auto_path = os.path.join(temp_dir, 'qbt_theme_auto.svg').replace('\\', '/')
    settings_path = os.path.join(temp_dir, 'qbt_settings_gear.svg').replace('\\', '/')
    export_path = os.path.join(temp_dir, 'qbt_export.svg').replace('\\', '/')
    undo_path = os.path.join(temp_dir, 'qbt_undo.svg').replace('\\', '/')
    fetch_rules_path = os.path.join(temp_dir, 'qbt_fetch_rules.svg').replace('\\', '/')
    try:
        with open(checkmark_path, 'w', encoding='utf-8') as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'/></svg>")
        with open(radio_path, 'w', encoding='utf-8') as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'><circle cx='12' cy='12' r='5'/></svg>")
        with open(down_arrow_path, 'w', encoding='utf-8') as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#64748b' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>")
        with open(up_arrow_path, 'w', encoding='utf-8') as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#64748b' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='18 15 12 9 6 15'/></svg>")
        with open(theme_light_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>')
        with open(theme_dark_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>')
        with open(theme_auto_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#a8a29e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8M12 17v4"/></svg>')
        with open(settings_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>')
        with open(export_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>')
        with open(undo_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>')
        with open(fetch_rules_path, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>')
    except Exception as exc:
        logger.error('Failed to write temporary checkmark/radio/arrow/theme/settings/export/undo/fetch_rules SVGs: %s', exc)

    last_selected_item_ref = [None]

    try:
        config.load_config()
    except Exception as exc:
        logger.error('Failed to load config for Qt UI: %s', exc, exc_info=True)

    # Keep Qt startup parity with Tk by loading cache-backed state early.
    try:
        config.load_cached_categories()
    except Exception:
        logger.debug('Failed to load cached categories for Qt UI', exc_info=True)
    try:
        config.load_cached_feeds()
    except Exception:
        logger.debug('Failed to load cached feeds for Qt UI', exc_info=True)
    try:
        config.load_recent_files()
    except Exception:
        logger.debug('Failed to load recent files cache for Qt UI', exc_info=True)
    try:
        # Ensure template cache has seeded defaults on first run.
        get_default_templates()
    except Exception:
        logger.debug('Failed to initialize default templates for Qt UI', exc_info=True)

    if not hasattr(config, 'SERVER_RULES_SNAPSHOT') or not isinstance(config.SERVER_RULES_SNAPSHOT, dict):
        config.SERVER_RULES_SNAPSHOT = {}

    rules_file = getattr(config, 'OUTPUT_CONFIG_FILE_NAME', os.path.join('data', 'qbittorrent_rules.json'))
    if rules_file and os.path.exists(rules_file):
        try:
            with open(rules_file, 'r', encoding='utf-8') as fh:
                text = fh.read()
            parsed = import_titles_from_text(text)
            if parsed:
                config.ALL_TITLES = parsed
                logger.info('Loaded %d rules from %s on startup', sum(len(v) for v in parsed.values() if isinstance(v, list)), rules_file)
        except Exception as exc:
            logger.error('Failed to load rules on startup: %s', exc, exc_info=True)

    try:
        widgets = importlib.import_module('PySide6.QtWidgets')
        core = importlib.import_module('PySide6.QtCore')
        gui = importlib.import_module('PySide6.QtGui')
        QApplication = getattr(widgets, 'QApplication')
        QMainWindow = getattr(widgets, 'QMainWindow')
        QStatusBar = getattr(widgets, 'QStatusBar')
        QLabel = getattr(widgets, 'QLabel')
        QVBoxLayout = getattr(widgets, 'QVBoxLayout')
        QHBoxLayout = getattr(widgets, 'QHBoxLayout')
        QFormLayout = getattr(widgets, 'QFormLayout')
        QWidget = getattr(widgets, 'QWidget')
        QPushButton = getattr(widgets, 'QPushButton')
        QCheckBox = getattr(widgets, 'QCheckBox')
        QSpinBox = getattr(widgets, 'QSpinBox')
        QRadioButton = getattr(widgets, 'QRadioButton')
        QGroupBox = getattr(widgets, 'QGroupBox')
        QTabWidget = getattr(widgets, 'QTabWidget')
        QSplitter = getattr(widgets, 'QSplitter')
        QMenu = getattr(widgets, 'QMenu')
        QTreeWidget = getattr(widgets, 'QTreeWidget')
        QTreeWidgetItem = getattr(widgets, 'QTreeWidgetItem')
        class NumericQTreeWidgetItem(QTreeWidgetItem):
            def __lt__(self, other):
                """Lt helper function."""
                tw = self.treeWidget()
                column = tw.sortColumn() if tw else 1
                if column == 1:
                    try:
                        return float(self.text(column)) < float(other.text(column))
                    except ValueError:
                        pass
                return super().__lt__(other)
        QHeaderView = getattr(widgets, 'QHeaderView')
        QAbstractItemView = getattr(widgets, 'QAbstractItemView')
        QTextEdit = getattr(widgets, 'QTextEdit')
        QListWidget = getattr(widgets, 'QListWidget')
        QListWidgetItem = getattr(widgets, 'QListWidgetItem')
        QLineEdit = getattr(widgets, 'QLineEdit')
        _QComboBox = getattr(widgets, 'QComboBox')
        QListView = getattr(widgets, 'QListView')
        QFrame = getattr(widgets, 'QFrame')
        QScrollArea = getattr(widgets, 'QScrollArea')
        class QComboBox(_QComboBox):
            def __init__(self, parent=None, *args, **kwargs):
                """Init helper function."""
                super().__init__(parent, *args, **kwargs)
                self.setView(QListView(self))
                self.setMaxVisibleItems(20)
        QMessageBox = getattr(widgets, 'QMessageBox')
        QDialog = getattr(widgets, 'QDialog')
        QFileDialog = getattr(widgets, 'QFileDialog')
        QInputDialog = getattr(widgets, 'QInputDialog')
        QStackedWidget = getattr(widgets, 'QStackedWidget')
        QShortcut = getattr(gui, 'QShortcut')
        QKeySequence = getattr(gui, 'QKeySequence')
        QIcon = getattr(gui, 'QIcon')
        QStyle = getattr(widgets, 'QStyle')
    except Exception as exc:
        raise ImportError(
            'PySide6 is required for Qt preview mode. Install dependencies from requirements.txt.'
        ) from exc

    def get_rule_from_item(item) -> dict | None:
        """Get rule from item helper function."""
        if item is None:
            return None
        rule = getattr(item, 'rule_ref', None)
        if isinstance(rule, dict):
            return rule
        rule = item.data(0, core.Qt.UserRole)
        if isinstance(rule, dict):
            return rule
        return None

    # Background worker threads are now loaded from src/gui_qt/workers.py

    active_workers = []

    app = QApplication.instance() or QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle('Torrent RSS Rules Editor')
    window.resize(1420, 820)
    window.setMinimumSize(900, 580)

    try:
        geometry = config.get_pref('qt_window_geometry', None)
        if geometry and isinstance(geometry, list) and len(geometry) == 4:
            window.setGeometry(int(geometry[0]), int(geometry[1]), int(geometry[2]), int(geometry[3]))
    except Exception:
        pass
        
    def save_rules_synchronously() -> None:
        """Force save current rules to data/qbittorrent_rules.json synchronously."""
        global _auto_save_timer
        with _auto_save_lock:
            if _auto_save_timer is not None:
                _auto_save_timer.cancel()
                _auto_save_timer = None
            
            data = getattr(config, 'ALL_TITLES', None)
            if not isinstance(data, dict):
                return
            
            try:
                export_map = build_rules_from_titles(data)
                file_path = getattr(config, 'OUTPUT_CONFIG_FILE_NAME', os.path.join('data', 'qbittorrent_rules.json'))
                with open(file_path, 'w', encoding='utf-8') as fh:
                    json.dump(export_map, fh, indent=4, ensure_ascii=False)
                logger.info("Synchronous save complete: saved %d rules to %s", len(export_map), file_path)
            except Exception as exc:
                logger.error("Synchronous save failure: %s", exc)

    def _on_close_event(event) -> None:
        """Handle the close event event."""
        try:
            rect = window.geometry()
            config.set_pref('qt_window_geometry', [rect.x(), rect.y(), rect.width(), rect.height()])
        except Exception:
            pass
        try:
            config.set_pref('qt_splitter_sizes', [int(s) for s in splitter.sizes()])
        except Exception:
            pass
        try:
            col_widths = [library_tree.columnWidth(i) for i in range(library_tree.columnCount())]
            config.set_pref('qt_tree_col_widths', col_widths)
        except Exception:
            pass
        try:
            save_rules_synchronously()
        except Exception as exc:
            logger.error("Failed to save rules on close: %s", exc)
        event.accept()

    window.closeEvent = _on_close_event
    from src.gui_qt.theme import apply_app_theme as apply_app_theme_imported
    apply_app_theme = lambda theme_pref: apply_app_theme_imported(window, theme_pref)

    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'

    app.setStyle('Fusion')
    apply_app_theme(theme_pref)

    central = QWidget(window)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)

    def _add_menu_action(menu, label, callback, shortcut: str = ''):
        """Add menu action helper function."""
        action = menu.addAction(label)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        return action

    def _open_batch_downloader(preselected_show_name: Optional[str] = None) -> None:
        """Open the batch downloader window or dialog."""
        try:
            dialog = BatchDownloaderDialog(parent=window, preselected_show_name=preselected_show_name)
            dialog.exec()
        except Exception as e:
            logger.error(f"Failed to open Batch Downloader: {e}", exc_info=True)
            QMessageBox.critical(window, "Error", f"Could not open Batch Downloader:\n{e}")

    qt_cache_viewer_ref = {'dialog': None}

    def _open_qt_cache_viewer() -> None:
        """Open the qt cache viewer window or dialog."""
        from src.gui_qt.cache_viewer_dialog import CacheViewerDialog
        existing = qt_cache_viewer_ref.get('dialog')
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
        except Exception:
            pass

        dialog = CacheViewerDialog(parent=window)
        qt_cache_viewer_ref['dialog'] = dialog
        dialog.show()

    qt_log_viewer_ref = {'dialog': None}

    def _open_qt_log_viewer() -> None:
        """Open the qt log viewer window or dialog."""
        from src.gui_qt.log_viewer_dialog import LogViewerDialog
        existing = qt_log_viewer_ref.get('dialog')
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
        except Exception:
            pass

        dialog = LogViewerDialog(parent=window)
        qt_log_viewer_ref['dialog'] = dialog
        dialog.exec()
        try:
            qt_log_viewer_ref['dialog'] = None
        except Exception:
            pass

    def _open_setup_wizard_dialog() -> None:
        """Launch a modern first-run style wizard for core app setup."""
        from src.gui_qt.setup_wizard_dialog import SetupWizardDialog
        wizard = SetupWizardDialog(
            parent=window,
            refresh_chips_callback=_refresh_chips,
            set_theme_pref_callback=set_theme_pref
        )
        wizard.exec()

    def _open_settings_dialog() -> None:
        """Launch a tabbed settings manager with full live styling options."""
        from src.gui_qt.settings_dialog import SettingsDialog
        dialog = SettingsDialog(
            parent=window,
            rebuild_action_bar_callback=rebuild_action_bar,
            set_theme_pref_callback=set_theme_pref,
            on_window_resize_callback=_on_window_resize,
            active_workers=active_workers
        )
        dialog.exec()


    def set_theme_pref(new_theme: str):
        """Set theme pref helper function."""
        config.set_pref('theme', new_theme)
        apply_app_theme(new_theme)
        try:
            update_theme_btn_icon()
        except Exception:
            pass
        try:
            light_action.setChecked(new_theme == 'light')
            dark_action.setChecked(new_theme == 'dark')
            auto_action.setChecked(new_theme == 'auto')
        except NameError:
            pass

    menubar = window.menuBar()

    file_menu = menubar.addMenu('File')

    recent_menu = QMenu('Recent Files', file_menu)

    def _open_recent_file(path: str) -> None:
        """Open the recent file window or dialog."""
        if not os.path.isfile(path):
            QMessageBox.warning(window, 'Recent Files', f'File not found:\n{path}')
            _refresh_recent_menu()
            return
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                text = fh.read()
        except Exception as exc:
            QMessageBox.warning(window, 'Recent Files', f'Failed to read file:\n{exc}')
            return

        parsed = import_titles_from_text(text)
        result = _run_qt_import_parsed(parsed, 'recent file import')
        try:
            config.add_recent_file(path)
        except Exception:
            logger.debug('Failed to update recent-file order for %s', path, exc_info=True)
        _refresh_recent_menu()
        QMessageBox.information(window, 'Import', str(result.get('message', 'Import done')))
        _refresh_library_tree()

    def _refresh_recent_menu() -> None:
        """Refresh the recent menu data."""
        recent_menu.clear()
        try:
            config.load_recent_files()
        except Exception:
            pass

        recent_files = [str(p).strip() for p in (getattr(config, 'RECENT_FILES', []) or []) if str(p).strip()]
        valid_files = [p for p in recent_files if os.path.isfile(p)]

        if len(valid_files) != len(recent_files):
            config.RECENT_FILES = valid_files
            try:
                from src.cache import save_recent_files
                save_recent_files(valid_files)
            except Exception:
                logger.debug('Failed to persist trimmed recent files list', exc_info=True)

        if not valid_files:
            empty_action = recent_menu.addAction('(No recent files)')
            empty_action.setEnabled(False)
            return

        for path in valid_files:
            filename = os.path.basename(path)
            folder = os.path.dirname(path)
            display_name = filename if len(filename) <= 40 else (filename[:37] + '...')
            if folder and len(folder) < 50:
                label = f'{display_name} ({folder})'
            else:
                label = display_name
            action = recent_menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: _open_recent_file(p))

        recent_menu.addSeparator()
        clear_recent_action = recent_menu.addAction('Clear Recent Files')

        def _clear_recent_files() -> None:
            """Clear recent files helper function."""
            try:
                config.clear_recent_files()
            except Exception:
                pass
            _refresh_recent_menu()

        clear_recent_action.triggered.connect(_clear_recent_files)

    _add_menu_action(file_menu, 'Import File...', lambda: _action_import_file(), 'Ctrl+O')
    _add_menu_action(file_menu, 'Paste from Clipboard', lambda: _action_import_clipboard())
    file_menu.addMenu(recent_menu)
    _refresh_recent_menu()
    file_menu.addSeparator()
    _add_menu_action(file_menu, 'Export All Rules...', lambda: _action_export_all(), 'Ctrl+Shift+S')
    file_menu.addSeparator()
    _add_menu_action(file_menu, 'Backup qBittorrent Rules...', lambda: _action_create_backup())
    _add_menu_action(file_menu, 'Restore from Backup...', lambda: _action_restore_backup())
    _add_menu_action(file_menu, 'Manage Backups...', lambda: _action_manage_backups())
    file_menu.addSeparator()
    _add_menu_action(file_menu, 'Exit', window.close)

    def _show_shortcuts_help() -> None:
        """Show shortcuts help helper function."""
        msg_box = QMessageBox(window)
        msg_box.setWindowTitle('Keyboard Shortcuts')
        msg_box.setTextFormat(core.Qt.RichText)
        msg_box.setText(
            '<table cellpadding="4" cellspacing="0">'
            '<tr><td><b>Ctrl+O</b></td><td>Import File</td></tr>'
            '<tr><td><b>Ctrl+Shift+S</b></td><td>Export All Rules</td></tr>'
            '<tr><td><b>Space</b></td><td>Toggle Enable/Disable</td></tr>'
            '<tr><td><b>Ctrl+Z</b></td><td>Undo</td></tr>'
            '<tr><td><b>Ctrl+B</b></td><td>Bulk Edit Selected</td></tr>'
            '<tr><td><b>Ctrl+E</b></td><td>Export Selected Titles</td></tr>'
            '<tr><td><b>Ctrl+Shift+E</b></td><td>Export All Titles</td></tr>'
            '<tr><td><b>F5</b></td><td>Refresh Library</td></tr>'
            '<tr><td><b>Ctrl+Shift+T</b></td><td>Apply Template</td></tr>'
            '<tr><td><b>Ctrl+T</b></td><td>Save as Template</td></tr>'
            '<tr><td><b>Ctrl+,</b></td><td>Settings</td></tr>'
            '<tr><td><b>Ctrl+F</b></td><td>Focus Filter Search</td></tr>'
            '<tr><td><b>Delete</b></td><td>Delete Selected</td></tr>'
            '<tr><td><b>Enter</b></td><td>Open Advanced Editor</td></tr>'
            '</table>'
        )
        msg_box.setIcon(QMessageBox.Information)
        msg_box.exec()

    edit_menu = menubar.addMenu('Edit')
    _add_menu_action(edit_menu, 'Toggle Enable/Disable', lambda: _action_toggle_selected(), 'Space')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Undo', lambda: _action_undo(), 'Ctrl+Z')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Bulk Edit Selected...', lambda: _action_bulk_toggle(), 'Ctrl+B')
    _add_menu_action(edit_menu, 'Batch Edit Title...', lambda: _action_batch_review_variations(), 'Ctrl+Shift+V')
    _add_menu_action(edit_menu, 'Batch Apply SubsPlease Matches...', lambda: _action_batch_apply_subsplease())
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Clear All Titles', lambda: _action_clear_all_titles(), 'Ctrl+Shift+C')
    _add_menu_action(edit_menu, 'Export Selected Titles...', lambda: _action_export_selected(), 'Ctrl+E')
    _add_menu_action(edit_menu, 'Export All Titles...', lambda: _action_export_all(), 'Ctrl+Shift+E')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Refresh', lambda: _refresh_library_tree(), 'F5')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'View Trash...', lambda: _action_view_trash())

    view_menu = menubar.addMenu('View')
    _add_menu_action(view_menu, 'API Cache Viewer...', _open_qt_cache_viewer)

    templates_menu = menubar.addMenu('Templates')
    _add_menu_action(templates_menu, 'Apply Template...', lambda: _action_apply_template(), 'Ctrl+Shift+T')
    _add_menu_action(templates_menu, 'Save as Template...', lambda: _action_save_template(), 'Ctrl+T')
    _add_menu_action(templates_menu, 'Manage Templates...', lambda: _action_manage_templates())

    tools_menu = menubar.addMenu('Tools')
    _add_menu_action(tools_menu, 'Multi Batch Downloader...', lambda: _open_batch_downloader(), 'Ctrl+M')

    validate_menu = menubar.addMenu('Validate')
    _add_menu_action(validate_menu, 'Validate All Titles', lambda: _action_validate_all())

    settings_menu = menubar.addMenu('Settings')
    _add_menu_action(settings_menu, 'Setup Wizard...', _open_setup_wizard_dialog)

    theme_menu = QMenu('Theme', settings_menu)
    settings_menu.addMenu(theme_menu)

    light_action = theme_menu.addAction('Light')
    light_action.setCheckable(True)
    light_action.triggered.connect(lambda: set_theme_pref('light'))

    dark_action = theme_menu.addAction('Dark')
    dark_action.setCheckable(True)
    dark_action.triggered.connect(lambda: set_theme_pref('dark'))

    auto_action = theme_menu.addAction('Auto (System)')
    auto_action.setCheckable(True)
    auto_action.triggered.connect(lambda: set_theme_pref('auto'))

    init_pref = str(config.get_pref('theme', 'light')).lower()
    light_action.setChecked(init_pref == 'light')
    dark_action.setChecked(init_pref == 'dark')
    auto_action.setChecked(init_pref == 'auto')

    _add_menu_action(settings_menu, 'Settings...', _open_settings_dialog, 'Ctrl+,')

    info_menu = menubar.addMenu('Info')
    _add_menu_action(info_menu, 'View Logs...', _open_qt_log_viewer)
    _add_menu_action(info_menu, 'Keyboard Shortcuts...', _show_shortcuts_help, 'F1')
    _add_menu_action(info_menu, 'About', lambda: QMessageBox.about(window, 'About', 'Torrent RSS Rule Editor\n\nA visual editor and synchronizer for RSS rules in the qBittorrent client.'))

    actions_bar = QWidget()
    actions_layout = QHBoxLayout(actions_bar)
    actions_layout.setContentsMargins(0, 4, 0, 4)

    action_scroll_area = QScrollArea()
    action_scroll_area.setWidgetResizable(True)
    action_scroll_area.setFrameShape(QFrame.NoFrame)
    action_scroll_area.setWidget(actions_bar)
    action_scroll_area.setVerticalScrollBarPolicy(core.Qt.ScrollBarAlwaysOff)
    action_scroll_area.setHorizontalScrollBarPolicy(core.Qt.ScrollBarAlwaysOff)

    # Instantiate all action bar widgets
    season_label = QLabel('Season:')
    season_combo = QComboBox()
    season_combo.setMaxVisibleItems(20)
    season_combo.addItems(['Winter', 'Spring', 'Summer', 'Fall'])
    season_combo.setCurrentText('Spring')
    season_combo.setToolTip('Select the schedule season for anime title mapping (Winter, Spring, Summer, Fall)')

    year_label = QLabel('Year:')
    year_combo = QComboBox()
    year_combo.setMaxVisibleItems(20)
    year_combo.addItems([str(y) for y in range(2000, 2101)])
    year_combo.setCurrentText('2026')
    year_combo.setToolTip('Select the schedule year for anime title mapping')

    def create_bar_separator():
        """Create bar separator helper function."""
        sep = QFrame()
        sep.setObjectName('actions_separator')
        sep.setFixedWidth(1)
        return sep

    separator_1 = create_bar_separator()
    separator_2 = create_bar_separator()
    separator_3 = create_bar_separator()

    import_btn = QPushButton('Import')
    import_btn.setToolTip('Import rules from a file or paste clipboard content')
    import_btn.setIcon(window.style().standardIcon(QStyle.SP_DialogOpenButton))
    import_menu = QMenu(import_btn)
    import_file_action = import_menu.addAction('Import File...')
    import_file_action.setToolTip('Import titles/rules from a JSON, CSV, or text file')
    import_file_action.triggered.connect(lambda: _action_import_file())
    import_clipboard_action = import_menu.addAction('Paste Clipboard')
    import_clipboard_action.setToolTip('Paste and import rule strings directly from the clipboard')
    import_clipboard_action.triggered.connect(lambda: _action_import_clipboard())
    import_btn.setMenu(import_menu)

    fetch_rules_btn = QPushButton('Fetch Rules')
    fetch_rules_btn.setToolTip('Retrieve existing RSS rules and category configurations from the qBittorrent server')
    fetch_rules_btn.setIcon(QIcon(fetch_rules_path))

    apply_rules_btn = QPushButton('Apply Rules')
    apply_rules_btn.setToolTip('Synchronize and apply current rule configurations to the qBittorrent server (runs a dry-run review first)')
    apply_rules_btn.setIcon(window.style().standardIcon(QStyle.SP_DialogSaveButton))

    batch_downloader_btn = QPushButton('Batch Downloader')
    batch_downloader_btn.setToolTip('Batch download episodes for imported shows locally or push to qBittorrent (Ctrl+M)')
    batch_downloader_btn.setIcon(window.style().standardIcon(QStyle.SP_DriveNetIcon))
    batch_downloader_btn.clicked.connect(lambda: _open_batch_downloader())

    refresh_btn = QPushButton('Refresh API Cache')
    refresh_btn.setToolTip('Refresh current SubsPlease release schedules or AniList variation data')
    refresh_btn.setIcon(window.style().standardIcon(QStyle.SP_BrowserReload))

    refresh_menu = QMenu(refresh_btn)
    refresh_subs_action = refresh_menu.addAction('SubsPlease')
    refresh_subs_action.setToolTip('Refresh current SubsPlease anime release schedules cache from the API')
    refresh_ani_action = refresh_menu.addAction('AniList')
    refresh_ani_action.setToolTip('Refresh AniList title variations and language-specific alias cache for the selected title')
    refresh_btn.setMenu(refresh_menu)

    undo_btn = QPushButton('Undo')
    undo_btn.setEnabled(False)
    undo_btn.setToolTip('Undo the last edit made to the rule parameters (Ctrl+Z)')
    undo_btn.setIcon(QIcon(undo_path))

    enabled_box = QCheckBox('Enabled')
    enabled_box.setChecked(True)
    enabled_box.setEnabled(False)
    enabled_box.setToolTip('Enable or disable this specific RSS rule on the qBittorrent server')

    clear_all_bar_btn = QPushButton('Clear All')
    clear_all_bar_btn.setToolTip('Clear all loaded titles from the application (Ctrl+Shift+C)')
    clear_all_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_DialogDiscardButton))

    validate_bar_btn = QPushButton('Validate')
    validate_bar_btn.setToolTip('Validate files/folders name compatibility with the server filesystem')
    validate_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_DialogApplyButton))

    trash_bar_btn = QPushButton('View Trash')
    trash_bar_btn.setToolTip('Open the Rule Trash Bin dialog to inspect and restore deleted rules')
    trash_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_TrashIcon))

    export_btn = QPushButton('Export')
    export_btn.setToolTip('Export selected rules or all rules to a file')
    export_btn.setIcon(QIcon(export_path))
    export_menu = QMenu(export_btn)
    export_selected_action = export_menu.addAction('Export Selected...')
    export_selected_action.setToolTip('Export only the selected rule configurations to a file (Ctrl+E)')
    export_selected_action.triggered.connect(lambda: _action_export_selected())
    export_all_action = export_menu.addAction('Export All Rules...')
    export_all_action.setToolTip('Export all rule configurations to a file (Ctrl+Shift+S)')
    export_all_action.triggered.connect(lambda: _action_export_all())
    export_btn.setMenu(export_menu)

    theme_btn = QPushButton()
    theme_btn.setToolTip("Toggle the application visual theme (Light, Dark, Auto)")
    
    def update_theme_btn_icon():
        """Update theme btn icon helper function."""
        current = str(config.get_pref('theme', 'light')).lower()
        if current == 'dark':
            theme_btn.setIcon(QIcon(theme_dark_path))
        elif current == 'auto':
            theme_btn.setIcon(QIcon(theme_auto_path))
        else:
            theme_btn.setIcon(QIcon(theme_light_path))

    def on_theme_btn_clicked():
        """On theme btn clicked helper function."""
        current = str(config.get_pref('theme', 'light')).lower()
        if current == 'light':
            next_theme = 'dark'
        elif current == 'dark':
            next_theme = 'auto'
        else:
            next_theme = 'light'
        set_theme_pref(next_theme)
    theme_btn.clicked.connect(on_theme_btn_clicked)
    window.theme_btn = theme_btn
    update_theme_btn_icon()

    settings_btn = QPushButton('Settings')
    settings_btn.setToolTip("Open the Settings dialog to configure paths, connection profile, appearances, rate limits, and more")
    settings_btn.setIcon(QIcon(settings_path))
    settings_btn.clicked.connect(_open_settings_dialog)

    refresh_library_bar_btn = QPushButton('Refresh')
    refresh_library_bar_btn.setToolTip('Refresh current library treeview structure (F5)')
    refresh_library_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_BrowserReload))
    refresh_library_bar_btn.clicked.connect(lambda: _refresh_library_tree())

    backup_btn = QPushButton('Backup')
    backup_btn.setToolTip('Backup, restore, and manage backup rules configurations')
    backup_btn.setIcon(window.style().standardIcon(QStyle.SP_ComputerIcon))
    backup_menu = QMenu(backup_btn)
    backup_create_action = backup_menu.addAction('Create Backup...')
    backup_create_action.setToolTip('Create a backup configuration copy of current rules')
    backup_create_action.triggered.connect(lambda: _action_create_backup())
    backup_restore_action = backup_menu.addAction('Restore Backup...')
    backup_restore_action.setToolTip('Restore rules from a previously saved backup file')
    backup_restore_action.triggered.connect(lambda: _action_restore_backup())
    backup_manage_action = backup_menu.addAction('Manage Backups...')
    backup_manage_action.setToolTip('Open the backup list manager dialog')
    backup_manage_action.triggered.connect(lambda: _action_manage_backups())
    backup_btn.setMenu(backup_menu)

    view_logs_bar_btn = QPushButton('View Logs')
    view_logs_bar_btn.setToolTip('Open log viewer utility')
    view_logs_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_MessageBoxInformation))
    view_logs_bar_btn.clicked.connect(lambda: _open_qt_log_viewer())

    api_cache_viewer_bar_btn = QPushButton('API Cache Viewer')
    api_cache_viewer_bar_btn.setToolTip('View or clear local anime API metadata cache structures')
    api_cache_viewer_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_FileDialogListView))
    api_cache_viewer_bar_btn.clicked.connect(lambda: _open_qt_cache_viewer())

    templates_btn = QPushButton('Templates')
    templates_btn.setToolTip('Apply, save, and manage templates for rules')
    templates_btn.setIcon(window.style().standardIcon(QStyle.SP_FileDialogListView))
    templates_menu = QMenu(templates_btn)
    templates_apply_action = templates_menu.addAction('Apply Template...')
    templates_apply_action.setToolTip('Apply a rule template/preset to the selected rule (Ctrl+Shift+T)')
    templates_apply_action.triggered.connect(lambda: _action_apply_template())
    templates_save_action = templates_menu.addAction('Save Template...')
    templates_save_action.setToolTip('Save selected rule parameters as a template (Ctrl+T)')
    templates_save_action.triggered.connect(lambda: _action_save_template())
    templates_manage_action = templates_menu.addAction('Manage Templates...')
    templates_manage_action.setToolTip('Open the template list manager dialog')
    templates_manage_action.triggered.connect(lambda: _action_manage_templates())
    templates_btn.setMenu(templates_menu)

    setup_wizard_bar_btn = QPushButton('Setup Wizard')
    setup_wizard_bar_btn.setToolTip('Open the configuration setup wizard dialog')
    setup_wizard_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_ComputerIcon))
    setup_wizard_bar_btn.clicked.connect(lambda: _open_setup_wizard_dialog())

    edit_rules_btn = QPushButton('Edit Rules')
    edit_rules_btn.setToolTip('Toggle selected rules, bulk edit parameters, batch edit titles, or batch apply matches')
    edit_rules_btn.setIcon(window.style().standardIcon(QStyle.SP_FileDialogContentsView))
    edit_rules_menu = QMenu(edit_rules_btn)
    edit_rules_toggle_action = edit_rules_menu.addAction('Toggle Selected')
    edit_rules_toggle_action.setToolTip('Toggle enabled status of selected rules (Space)')
    edit_rules_toggle_action.triggered.connect(lambda: _action_toggle_selected())
    edit_rules_bulk_action = edit_rules_menu.addAction('Bulk Edit...')
    edit_rules_bulk_action.setToolTip('Bulk edit parameters of selected rules (Ctrl+B)')
    edit_rules_bulk_action.triggered.connect(lambda: _action_bulk_toggle())
    edit_rules_batch_title_action = edit_rules_menu.addAction('Batch Edit Title...')
    edit_rules_batch_title_action.setToolTip('Batch edit title variations (Ctrl+Shift+V)')
    edit_rules_batch_title_action.triggered.connect(lambda: _action_batch_review_variations())
    edit_rules_batch_apply_action = edit_rules_menu.addAction('Batch Apply SubsPlease Matches...')
    edit_rules_batch_apply_action.setToolTip('Batch apply matching SubsPlease titles to selected rules')
    edit_rules_batch_apply_action.triggered.connect(lambda: _action_batch_apply_subsplease())
    edit_rules_btn.setMenu(edit_rules_menu)

    batch_apply_btn = QPushButton('Batch Apply Titles')
    batch_apply_btn.setToolTip('Batch apply matching SubsPlease titles to selected rules')
    batch_apply_btn.setIcon(window.style().standardIcon(QStyle.SP_DialogApplyButton))
    batch_apply_btn.clicked.connect(lambda: _action_batch_apply_subsplease())

    shortcuts_help_bar_btn = QPushButton('Help Shortcuts')
    shortcuts_help_bar_btn.setToolTip('Show keyboard shortcuts help (F1)')
    shortcuts_help_bar_btn.setIcon(window.style().standardIcon(QStyle.SP_MessageBoxQuestion))
    shortcuts_help_bar_btn.clicked.connect(lambda: _show_shortcuts_help())

    # Standalone sub-action buttons
    import_file_btn = QPushButton('Import File')
    import_file_btn.setToolTip('Import titles/rules from a JSON, CSV, or text file')
    import_file_btn.clicked.connect(lambda: _action_import_file())

    import_clipboard_btn = QPushButton('Paste Clipboard')
    import_clipboard_btn.setToolTip('Paste and import rule strings directly from the clipboard')
    import_clipboard_btn.clicked.connect(lambda: _action_import_clipboard())

    export_selected_btn = QPushButton('Export Selected')
    export_selected_btn.setToolTip('Export only the selected rule configurations to a file')
    export_selected_btn.clicked.connect(lambda: _action_export_selected())

    export_all_btn = QPushButton('Export All')
    export_all_btn.setToolTip('Export all rule configurations to a file')
    export_all_btn.clicked.connect(lambda: _action_export_all())

    backup_create_btn = QPushButton('Create Backup')
    backup_create_btn.setToolTip('Create a backup configuration copy of current rules')
    backup_create_btn.clicked.connect(lambda: _action_create_backup())

    backup_restore_btn = QPushButton('Restore Backup')
    backup_restore_btn.setToolTip('Restore rules from a previously saved backup file')
    backup_restore_btn.clicked.connect(lambda: _action_restore_backup())

    backup_manage_btn = QPushButton('Manage Backups')
    backup_manage_btn.setToolTip('Open the backup list manager dialog')
    backup_manage_btn.clicked.connect(lambda: _action_manage_backups())

    templates_apply_btn = QPushButton('Apply Template')
    templates_apply_btn.setToolTip('Apply a rule template/preset to the selected rule')
    templates_apply_btn.clicked.connect(lambda: _action_apply_template())

    templates_save_btn = QPushButton('Save Template')
    templates_save_btn.setToolTip('Save selected rule parameters as a template')
    templates_save_btn.clicked.connect(lambda: _action_save_template())

    templates_manage_btn = QPushButton('Manage Templates')
    templates_manage_btn.setToolTip('Open the template list manager dialog')
    templates_manage_btn.clicked.connect(lambda: _action_manage_templates())

    edit_rules_toggle_btn = QPushButton('Toggle Selected')
    edit_rules_toggle_btn.setToolTip('Toggle enabled status of selected rules')
    edit_rules_toggle_btn.clicked.connect(lambda: _action_toggle_selected())

    edit_rules_bulk_btn = QPushButton('Bulk Edit')
    edit_rules_bulk_btn.setToolTip('Bulk edit parameters of selected rules')
    edit_rules_bulk_btn.clicked.connect(lambda: _action_bulk_toggle())

    edit_rules_batch_title_btn = QPushButton('Batch Edit Title')
    edit_rules_batch_title_btn.setToolTip('Batch edit title variations')
    edit_rules_batch_title_btn.clicked.connect(lambda: _action_batch_review_variations())

    edit_rules_batch_apply_btn = QPushButton('Batch Apply Matches')
    edit_rules_batch_apply_btn.setToolTip('Batch apply matching SubsPlease titles to selected rules')
    edit_rules_batch_apply_btn.clicked.connect(lambda: _action_batch_apply_subsplease())

    refresh_subsplease_btn = QPushButton('Refresh SubsPlease')
    refresh_subsplease_btn.setToolTip('Refresh current SubsPlease anime release schedules cache from the API')
    refresh_subsplease_btn.clicked.connect(lambda: _action_refresh_subsplease())

    refresh_anilist_btn = QPushButton('Refresh AniList')
    refresh_anilist_btn.setToolTip('Refresh AniList title variations and language-specific alias cache for the selected title')
    refresh_anilist_btn.clicked.connect(lambda: _action_refresh_anilist())

    # Action bar widgets group mapping
    action_widgets = {
        'season_year': [season_label, season_combo, year_label, year_combo],
        'separator': [separator_1],
        'separator_1': [separator_1],
        'separator_2': [separator_2],
        'separator_3': [separator_3],
        'import': [import_btn],
        'fetch_rules': [fetch_rules_btn],
        'apply': [apply_rules_btn],
        'batch': [batch_downloader_btn],
        'refresh': [refresh_btn],
        'undo': [undo_btn],
        'enabled': [enabled_box],
        'clear_all': [clear_all_bar_btn],
        'validate': [validate_bar_btn],
        'trash': [trash_bar_btn],
        'export': [export_btn],
        'theme': [theme_btn],
        'settings': [settings_btn],
        'refresh_library': [refresh_library_bar_btn],
        'backup': [backup_btn],
        'templates': [templates_btn],
        'edit_rules': [edit_rules_btn],
        'batch_apply': [batch_apply_btn],
        'view_logs': [view_logs_bar_btn],
        'api_cache_viewer': [api_cache_viewer_bar_btn],
        'setup_wizard': [setup_wizard_bar_btn],
        'shortcuts_help': [shortcuts_help_bar_btn],
        # Standalone sub-actions mapping
        'import_file': [import_file_btn],
        'import_clipboard': [import_clipboard_btn],
        'export_selected': [export_selected_btn],
        'export_all': [export_all_btn],
        'backup_create': [backup_create_btn],
        'backup_restore': [backup_restore_btn],
        'backup_manage': [backup_manage_btn],
        'templates_apply': [templates_apply_btn],
        'templates_save': [templates_save_btn],
        'templates_manage': [templates_manage_btn],
        'edit_rules_toggle': [edit_rules_toggle_btn],
        'edit_rules_bulk': [edit_rules_bulk_btn],
        'edit_rules_batch_title': [edit_rules_batch_title_btn],
        'edit_rules_batch_apply': [edit_rules_batch_apply_btn],
        'refresh_subsplease': [refresh_subsplease_btn],
        'refresh_anilist': [refresh_anilist_btn]
    }

    # Rebuild action bar helper
    def rebuild_action_bar():
        """
        Dynamically rebuilds the Action Bar (toolbar) based on the user's settings.
        
        This handles a massive amount of customization logic:
        - It reads the user's preferred item order and visibility.
        - It creates standalone buttons, drop-down menus, and visual separators.
        - It injects custom SVGs or icons based on the active theme (Light/Dark).
        - It manages layout compactness (responsive mode vs static mode).
        
        This method is globally callable within setup_gui_qt to allow immediate 
        UI updates when settings change.
        """
        if not hasattr(window, "dynamic_dropdown_widgets"):
            window.dynamic_dropdown_widgets = {}
        for w in list(window.dynamic_dropdown_widgets.values()):
            try:
                w.deleteLater()
            except Exception:
                pass
        window.dynamic_dropdown_widgets.clear()

        # Clear existing layout items
        while actions_layout.count() > 0:
            item = actions_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                actions_layout.removeWidget(w)
                w.setVisible(False)

        # Retrieve preferences (Default order matches user request)
        default_order = DEFAULT_ACTION_BAR_ORDER.copy()
        order = config.get_pref('action_bar_order', default_order)
        if "separator" in order:
            order = [name if name != "separator" else "separator_1" for name in order]
            
        # Backward compatibility migration
        visible = config.get_pref('action_bar_visible', None)
        if visible is not None:
            order = [name for name in order if visible.get(name, True)]

        # Load global customization preferences
        mode = str(config.get_pref('action_bar_mode', 'responsive')).lower()
        btn_size_pref = str(config.get_pref('action_bar_button_size', 'standard')).lower()
        custom_labels = config.get_pref('action_bar_custom_labels', {})
        custom_icons = config.get_pref('action_bar_custom_icons', {})

        # Determine dimensions based on size preference
        if btn_size_pref == 'compact':
            btn_height = 24
            icon_sz = 14
            font_sz = 11
            padding = "padding: 2px 6px; font-size: 11px;"
        elif btn_size_pref == 'large':
            btn_height = 38
            icon_sz = 20
            font_sz = 14
            padding = "padding: 6px 14px; font-size: 14px;"
        else: # standard
            btn_height = 30
            icon_sz = 16
            font_sz = 12
            padding = "padding: 4px 10px; font-size: 12px;"

        action_scroll_area.setFixedHeight(btn_height + 10)

        # Configure scrollbar policies based on mode
        if mode in ('scrollable', 'hybrid'):
            action_scroll_area.setHorizontalScrollBarPolicy(core.Qt.ScrollBarAsNeeded)
        else:
            action_scroll_area.setHorizontalScrollBarPolicy(core.Qt.ScrollBarAlwaysOff)

        # Apply sizes & styles to all buttons, comboboxes, and labels in the bar
        for key, wl in action_widgets.items():
            for w in wl:
                # Apply custom styles
                if isinstance(w, QPushButton):
                    w.setFixedHeight(btn_height)
                    w.setIconSize(core.QSize(icon_sz, icon_sz))
                    w.setStyleSheet(padding)
                    
                    label = custom_labels.get(key, DEFAULT_BUTTON_METADATA.get(key, {}).get('label', w.text()))
                    w.setText(label)
                    w._full_text = label
                    
                    if key in custom_icons:
                        icon_name = custom_icons[key]
                        try:
                            w.setIcon(window.style().standardIcon(getattr(QStyle, icon_name)))
                        except Exception:
                            pass
                    elif key == 'theme':
                        update_theme_btn_icon()
                    elif key == 'settings':
                        w.setIcon(QIcon(settings_path))
                    elif key == 'undo':
                        w.setIcon(QIcon(undo_path))
                    elif key == 'export':
                        w.setIcon(QIcon(export_path))
                    elif key == 'fetch_rules':
                        w.setIcon(QIcon(fetch_rules_path))
                    else:
                        # Restore standard default icon
                        meta = DEFAULT_BUTTON_METADATA.get(key, {})
                        def_icon_key = meta.get("icon", "")
                        if def_icon_key:
                            try:
                                std_icon = window.style().standardIcon(getattr(QStyle, def_icon_key))
                                w.setIcon(std_icon)
                            except Exception:
                                w.setIcon(QIcon())
                        else:
                            w.setIcon(QIcon())
                elif isinstance(w, QComboBox):
                    w.setFixedHeight(btn_height)
                    w.setStyleSheet(f"font-size: {font_sz}px;")
                elif isinstance(w, QLabel):
                    w.setStyleSheet(f"font-size: {font_sz}px;")
                elif isinstance(w, QCheckBox):
                    w.setStyleSheet(f"font-size: {font_sz}px;")
                    label = custom_labels.get(key, DEFAULT_BUTTON_METADATA.get(key, {}).get('label', w.text()))
                    w.setText(label)
                    w._full_text = label

        # Load custom dropdowns configuration
        custom_dropdowns = config.get_pref('action_bar_custom_dropdowns', {})
        dropdown_subactions = config.get_pref('action_bar_dropdown_subactions', {})

        subaction_triggers = {
            "import_file": lambda: _action_import_file(),
            "import_clipboard": lambda: _action_import_clipboard(),
            "export_selected": lambda: _action_export_selected(),
            "export_all": lambda: _action_export_all(),
            "backup_create": lambda: _action_create_backup(),
            "backup_restore": lambda: _action_restore_backup(),
            "backup_manage": lambda: _action_manage_backups(),
            "templates_apply": lambda: _action_apply_template(),
            "templates_save": lambda: _action_save_template(),
            "templates_manage": lambda: _action_manage_templates(),
            "edit_rules_toggle": lambda: _action_toggle_selected(),
            "edit_rules_bulk": lambda: _action_bulk_toggle(),
            "edit_rules_batch_title": lambda: _action_batch_review_variations(),
            "edit_rules_batch_apply": lambda: _action_batch_apply_subsplease(),
            "refresh_subsplease": lambda: _action_refresh_subsplease(),
            "refresh_anilist": lambda: _action_refresh_anilist(),
        }

        # Gather nested child keys from active custom dropdowns
        nested_child_keys = set()
        for name in order:
            if name.startswith("custom_dropdown_") and name in custom_dropdowns:
                children = custom_dropdowns[name].get("children", [])
                for child in children:
                    nested_child_keys.add(child)

        has_stretch = False

        for name in order:
            if name in nested_child_keys:
                wl = action_widgets.get(name, [])
                for w in wl:
                    w.setVisible(False)
                continue

            if name.startswith("spacer"):
                actions_layout.addStretch(1)
                has_stretch = True
                continue

            if name.startswith("separator"):
                sep = QFrame()
                sep.setObjectName('actions_separator')
                sep.setFixedWidth(1)
                actions_layout.addWidget(sep)
                continue

            if name.startswith("custom_dropdown_"):
                if name not in custom_dropdowns:
                    continue
                
                conf = custom_dropdowns[name]
                label = conf.get("label", "Custom Dropdown")
                icon_name = conf.get("icon", "SP_TitleBarMenuButton")
                children = conf.get("children", [])
                
                btn = QPushButton(label)
                btn.setFixedHeight(btn_height)
                btn.setIconSize(core.QSize(icon_sz, icon_sz))
                btn.setStyleSheet(padding)
                
                try:
                    std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                    btn.setIcon(std_icon)
                except Exception:
                    pass
                    
                menu = QMenu(btn)
                for child_key in children:
                    if child_key.startswith("separator"):
                        menu.addSeparator()
                        continue
                    if child_key.startswith("spacer"):
                        continue
                        
                    child_meta = DEFAULT_BUTTON_METADATA.get(child_key, {})
                    child_sub_meta = SUBACTION_METADATA.get(child_key, {})
                    
                    c_label = custom_labels.get(child_key, child_meta.get("label", child_sub_meta.get("label", child_key)))
                    c_icon = custom_icons.get(child_key, child_meta.get("icon", child_sub_meta.get("icon", "")))
                    c_tooltip = child_meta.get("tooltip", child_sub_meta.get("tooltip", ""))
                    
                    action = menu.addAction(c_label)
                    if c_tooltip:
                        action.setToolTip(c_tooltip)
                    if c_icon:
                        try:
                            std_icon = window.style().standardIcon(getattr(QStyle, c_icon))
                            action.setIcon(std_icon)
                        except Exception:
                            pass
                            
                    def _make_child_trigger(ck=child_key):
                        """Make child trigger helper function."""
                        if ck in subaction_triggers:
                            return lambda: subaction_triggers[ck]()
                        wl = action_widgets.get(ck, [])
                        if wl:
                            primary_w = wl[0]
                            if isinstance(primary_w, QPushButton):
                                return lambda: primary_w.click()
                            elif isinstance(primary_w, QCheckBox):
                                return lambda: primary_w.toggle()
                        return lambda: None
                        
                    action.triggered.connect(_make_child_trigger())
                    
                btn.setMenu(menu)
                window.dynamic_dropdown_widgets[name] = btn
                actions_layout.addWidget(btn)
                btn.setVisible(True)
                continue

            if name in DEFAULT_DROPDOWN_SUBACTIONS:
                active_subs = dropdown_subactions.get(name, DEFAULT_DROPDOWN_SUBACTIONS[name].copy())
                wl = action_widgets.get(name, [])
                
                if not active_subs:
                    for w in wl:
                        w.setVisible(False)
                    continue
                    
                for w in wl:
                    if isinstance(w, QPushButton):
                        if len(active_subs) == 1:
                            w.setMenu(None)
                            try:
                                import warnings
                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore", RuntimeWarning)
                                    w.clicked.disconnect()
                            except Exception:
                                pass
                                
                            single_sub_key = active_subs[0]
                            trigger_func = subaction_triggers.get(single_sub_key)
                            if trigger_func:
                                w.clicked.connect(lambda: trigger_func())
                                
                            sub_meta = SUBACTION_METADATA.get(single_sub_key, {})
                            lbl = custom_labels.get(name, "")
                            if not lbl:
                                lbl = custom_labels.get(single_sub_key, sub_meta.get("label", ""))
                            if not lbl:
                                lbl = w.text()
                                
                            w.setText(lbl)
                            w._full_text = lbl
                            w.setToolTip(sub_meta.get("tooltip", w.toolTip()))
                            
                            ico_name = custom_icons.get(name, "")
                            if not ico_name:
                                ico_name = custom_icons.get(single_sub_key, sub_meta.get("icon", ""))
                                
                            if ico_name:
                                try:
                                    std_icon = window.style().standardIcon(getattr(QStyle, ico_name))
                                    w.setIcon(std_icon)
                                except Exception:
                                    pass
                            else:
                                w.setIcon(QIcon())
                        else:
                            try:
                                import warnings
                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore", RuntimeWarning)
                                    w.clicked.disconnect()
                            except Exception:
                                pass
                            
                            # Restore default behavior
                            lbl = custom_labels.get(name, DEFAULT_BUTTON_METADATA.get(name, {}).get('label', w.text()))
                            w.setText(lbl)
                            w._full_text = lbl
                            
                            ico_name = custom_icons.get(name, DEFAULT_BUTTON_METADATA.get(name, {}).get("icon", ""))
                            if ico_name:
                                try:
                                    std_icon = window.style().standardIcon(getattr(QStyle, ico_name))
                                    w.setIcon(std_icon)
                                except Exception:
                                    pass
                            else:
                                def_icon_key = DEFAULT_BUTTON_METADATA.get(name, {}).get("icon", "")
                                if def_icon_key:
                                    try:
                                        std_icon = window.style().standardIcon(getattr(QStyle, def_icon_key))
                                        w.setIcon(std_icon)
                                    except Exception:
                                        w.setIcon(QIcon())
                                else:
                                    w.setIcon(QIcon())
                                
                            menu = QMenu(w)
                            for sub_key in active_subs:
                                sub_meta = SUBACTION_METADATA.get(sub_key, {})
                                label = custom_labels.get(sub_key, sub_meta.get("label", sub_key))
                                tooltip = sub_meta.get("tooltip", "")
                                icon_name = custom_icons.get(sub_key, sub_meta.get("icon", ""))
                                
                                action = menu.addAction(label)
                                if tooltip:
                                    action.setToolTip(tooltip)
                                if icon_name:
                                    try:
                                        std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                                        action.setIcon(std_icon)
                                    except Exception:
                                        pass
                                elif sub_meta.get("icon", ""):
                                    try:
                                        std_icon = window.style().standardIcon(getattr(QStyle, sub_meta["icon"]))
                                        action.setIcon(std_icon)
                                    except Exception:
                                        pass
                                        
                                trigger_func = subaction_triggers.get(sub_key)
                                if trigger_func:
                                    def _make_trigger(tf=trigger_func):
                                        """Make trigger helper function."""
                                        return lambda: tf()
                                    action.triggered.connect(_make_trigger())
                                    
                            w.setMenu(menu)
                    w.setVisible(True)
                    actions_layout.addWidget(w)
                continue

            wl = action_widgets.get(name, [])
            for w in wl:
                w.setVisible(True)
                actions_layout.addWidget(w)

        if not has_stretch:
            actions_layout.addStretch(1)

    # Make rebuild helper globally accessible for dialog triggers
    window.rebuild_action_bar = rebuild_action_bar
    rebuild_action_bar()

    layout.addWidget(action_scroll_area)

    def _on_window_resize(event=None):
        """Handle the window resize event."""
        if event is not None:
            window._original_resize_event(event)
        mode = str(config.get_pref('action_bar_mode', 'responsive')).lower()
        btn_size_pref = str(config.get_pref('action_bar_button_size', 'standard')).lower()
        
        # Determine if we should show text based on mode and current window width
        show_text = True
        if mode == 'icons_only':
            show_text = False
        elif mode in ('responsive', 'hybrid'):
            show_text = window.width() >= 950
            
        # Determine padding, font size and style rules based on size preference and text visibility
        if btn_size_pref == 'compact':
            padding_str = "padding: 2px 6px;" if show_text else "padding: 2px 2px;"
            font_size = 11
            btn_height = 24
            spacing = 4 if show_text else 2
        elif btn_size_pref == 'large':
            padding_str = "padding: 6px 14px;" if show_text else "padding: 6px 6px;"
            font_size = 14
            btn_height = 38
            spacing = 8 if show_text else 6
        else: # standard
            padding_str = "padding: 4px 10px;" if show_text else "padding: 4px 4px;"
            font_size = 12
            btn_height = 30
            spacing = 6 if show_text else 4

        actions_layout.setSpacing(spacing)

        if not show_text:
            style_str = f"QPushButton {{ {padding_str} font-size: {font_size}px; }} QPushButton::menu-indicator {{ image: none; width: 0px; }}"
        else:
            style_str = f"QPushButton {{ {padding_str} font-size: {font_size}px; }}"
            
        for key, wl in action_widgets.items():
            for w in wl:
                if isinstance(w, QPushButton):
                    is_icon_only_btn = (key == 'theme')
                    has_text = show_text and not is_icon_only_btn
                    w.setText(getattr(w, '_full_text', w.text()) if has_text else "")
                    w.setStyleSheet(style_str)
                    if not has_text:
                        w.setFixedWidth(btn_height)
                    else:
                        w.setMinimumWidth(0)
                        w.setMaximumWidth(16777215)
                elif isinstance(w, QCheckBox):
                    w.setText(getattr(w, '_full_text', w.text()) if show_text else "")
                elif isinstance(w, QLabel):
                    w.setVisible(show_text)

    window._original_resize_event = window.resizeEvent
    window.resizeEvent = _on_window_resize
    _on_window_resize()

    connection_chip = QLabel('Connection: ' + get_connection_status_text(config))
    titles_count = sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list))
    titles_chip = QLabel(f'Titles: {titles_count}')
    connection_chip.setObjectName('connection_chip')
    titles_chip.setObjectName('titles_chip')

    content_group = QGroupBox('Library')
    content_layout = QVBoxLayout(content_group)

    search_layout = QHBoxLayout()
    search_layout.addWidget(QLabel('Filter:'))
    search_entry = QLineEdit()
    search_entry.setToolTip("Type text to dynamically filter rules by the selected field (e.g. Title, Category, Save Path)")
    filter_combo = QComboBox()
    filter_combo.setMaxVisibleItems(20)
    filter_combo.addItems(['Title', 'Category', 'Save Path'])
    filter_combo.setToolTip("Select which rule field to search against (Title, Category, or Save Path)")
    clear_btn = QPushButton('Clear')
    clear_btn.setToolTip("Clear the search filter to display all rules")
    search_layout.addWidget(search_entry, 1)
    search_layout.addWidget(filter_combo)
    search_layout.addWidget(clear_btn)
    content_layout.addLayout(search_layout)

    splitter = QSplitter(core.Qt.Horizontal)
    library_tree = QTreeWidget()
    library_tree.setToolTip("List of all title rules. Double-click a rule to edit, or use space to toggle enable/disable state")
    library_tree.setColumnCount(5)
    library_tree.setHeaderLabels(['Active', '#', 'Title', 'Category', 'Save Path'])
    library_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    library_tree.setSortingEnabled(True)
    library_tree.sortByColumn(1, core.Qt.AscendingOrder)
    library_tree.setMinimumWidth(360)

    # Restore saved column widths, fall back to sensible defaults
    _saved_col_widths = config.get_pref('qt_tree_col_widths', None)
    _default_col_widths = [50, 40, 320, 120, 360]
    _col_widths = (_saved_col_widths if isinstance(_saved_col_widths, list) and len(_saved_col_widths) == 5
                   else _default_col_widths)
    for _ci, _cw in enumerate(_col_widths):
        library_tree.setColumnWidth(_ci, int(_cw))

    # Interactive column resizing: Active and # shrink to content; Title stretches; others interactive
    _header = library_tree.header()
    _header.setSectionResizeMode(0, QHeaderView.Fixed)
    _header.setSectionResizeMode(1, QHeaderView.Fixed)
    _header.setSectionResizeMode(2, QHeaderView.Stretch)
    _header.setSectionResizeMode(3, QHeaderView.Interactive)
    _header.setSectionResizeMode(4, QHeaderView.Interactive)
    _header.setStretchLastSection(False)

    current_titles = getattr(config, 'ALL_TITLES', {}) or {}
    if not isinstance(current_titles, dict):
        current_titles = {}
        config.ALL_TITLES = current_titles

    row_num = 1
    library_tree.blockSignals(True)
    try:
        for category, titles_list in current_titles.items():
            if not isinstance(titles_list, list):
                continue
            for rule in titles_list:
                if not isinstance(rule, dict):
                    continue
                item = NumericQTreeWidgetItem(library_tree)
                item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
                item.setText(1, str(row_num))
                item.setText(2, str(rule.get('node', {}).get('title') or rule.get('ruleName', '(Untitled)')))
                item.setText(3, str(rule.get('assignedCategory', '')))
                item.setText(4, str(rule.get('savePath', '')))
                item.setData(0, core.Qt.UserRole, rule)
                item.rule_ref = rule
                row_num += 1
    finally:
        library_tree.blockSignals(False)

    splitter.addWidget(library_tree)

    editor_group = QGroupBox('Rule Editor')
    editor_layout = QVBoxLayout(editor_group)

    editor_layout.addWidget(QLabel('Title:'))
    title_row = QHBoxLayout()
    title_edit = QLineEdit()
    title_edit.setToolTip('The name of the rule and the destination folder path on the server')
    prefix_btn = QPushButton('Prefix')
    prefix_btn.setToolTip('Prepend the selected Season & Year prefix to the current title (e.g. "Spring 2026 - ")')
    title_row.addWidget(title_edit, 1)
    title_row.addWidget(prefix_btn)
    editor_layout.addLayout(title_row)

    editor_layout.addWidget(QLabel('Match Pattern:'))
    must_edit = QLineEdit()
    must_edit.setToolTip('Vibrant regex or literal matching pattern that must be contained in the torrent name to match')
    editor_layout.addWidget(must_edit)

    variations_group = QGroupBox('Title Variations')
    variations_layout = QVBoxLayout(variations_group)
    apply_row = QHBoxLayout()
    var_match_box = QCheckBox('Match Pattern')
    var_match_box.setToolTip('When checked, clicking any title variation button below will update the Match Pattern field with that variation.')
    var_match_box.setChecked(True)
    var_title_box = QCheckBox('Title')
    var_title_box.setToolTip('When checked, clicking any title variation button below will update the rule\'s Title field (preserving any season/year prefixes).')
    var_title_box.setChecked(True)
    var_path_box = QCheckBox('Save Path')
    var_path_box.setToolTip('When checked, clicking any title variation button below will update the rule\'s Save Path folder name with that variation.')
    var_path_box.setChecked(True)
    apply_row.addWidget(var_match_box)
    apply_row.addWidget(var_title_box)
    apply_row.addWidget(var_path_box)
    apply_row.addStretch()
    variations_layout.addLayout(apply_row)

    variations_layout.addWidget(QLabel('<b>AniList Variations:</b>'))
    anilist_scroll = QScrollArea()
    anilist_scroll.setWidgetResizable(True)
    anilist_scroll.setMinimumHeight(100)
    anilist_scroll.setMaximumHeight(600)
    anilist_scroll.setFrameShape(QFrame.NoFrame)
    anilist_widget = QWidget()
    anilist_content_layout = QVBoxLayout(anilist_widget)
    anilist_content_layout.setContentsMargins(0, 0, 0, 0)
    anilist_content_layout.setSpacing(4)
    anilist_scroll.setWidget(anilist_widget)
    variations_layout.addWidget(anilist_scroll)

    variations_layout.addWidget(QLabel('<b>SubsPlease Match:</b>'))
    subsplease_widget = QWidget()
    subsplease_content_layout = QVBoxLayout(subsplease_widget)
    subsplease_content_layout.setContentsMargins(0, 0, 0, 0)
    subsplease_content_layout.setSpacing(4)
    variations_layout.addWidget(subsplease_widget)

    editor_layout.addWidget(variations_group, 1)

    def _apply_variation(val: str) -> None:
        """Apply changes for variation."""
        if not var_match_box.isChecked() and not var_title_box.isChecked() and not var_path_box.isChecked():
            QMessageBox.warning(window, 'Selection Required', 'Please check at least one of Match Pattern, Title, or Save Path to apply the variation.')
            return

        if var_match_box.isChecked():
            must_edit.setText(val)
        
        if var_title_box.isChecked():
            current_t = title_edit.text().strip()
            prefix = ""
            import re
            m = re.match(r'^(\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*)', current_t, re.IGNORECASE)
            if m:
                prefix = m.group(1)
            title_edit.setText(prefix + val)

        if var_path_box.isChecked():
            import re
            current_p = save_path_edit.text().strip()
            clean_val = sanitize_folder_name(val)
            m = re.match(r'^((?:spring|summer|fall|winter)\s+\d{4}/)', current_p, re.IGNORECASE)
            if m:
                save_path_edit.setText(m.group(1) + clean_val)
            else:
                save_path_edit.setText(clean_val)

        _save_current_rule_from_editor()

    def _update_title_variations_ui() -> None:
        """Update title variations ui helper function."""
        def _clear_layout(layout):
            """Clear layout helper function."""
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()
                    else:
                        _clear_layout(item.layout())

        _clear_layout(anilist_content_layout)
        _clear_layout(subsplease_content_layout)

        title = title_edit.text().strip()
        must = must_edit.text().strip()
        if not title and not must:
            lbl_anilist = QLabel('(Select a title to see AniList variations)')
            lbl_anilist.setStyleSheet("color: gray;")
            anilist_content_layout.addWidget(lbl_anilist)
            lbl_subs = QLabel('(No title selected)')
            lbl_subs.setStyleSheet("color: gray;")
            subsplease_content_layout.addWidget(lbl_subs)
            return

        def _get_base_title(t: str) -> str:
            """Get base title helper function."""
            import re
            m = re.match(r'^\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*(.*)', t, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return t.strip()

        def _get_base_path(p: str) -> str:
            """Get base path helper function."""
            import re
            m = re.match(r'^\s*(?:spring|summer|fall|winter)\s+\d{4}/(.*)', p, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return p.strip()

        state = build_rule_editor_feed_state(
            current_title=title,
            current_must=must,
            find_subsplease_title_match=find_subsplease_title_match,
            load_title_variations_cache=load_title_variations_cache,
        )

        sp_title = state.get('subsplease_title')
        if sp_title and sp_title not in ('(No matching SubsPlease title in cache)', '(No title selected)'):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            btn = QPushButton(str(sp_title))
            btn.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: normal;")
            btn.clicked.connect(lambda _, val=sp_title: _apply_variation(val))
            row_layout.addWidget(btn, 1)

            matches = []
            if sp_title.lower() == must.lower():
                matches.append("Match Pattern")
            if sp_title.lower() == _get_base_title(title).lower():
                matches.append("Title")
            if sanitize_folder_name(sp_title).lower() == _get_base_path(save_path_edit.text()).lower():
                matches.append("Save Path")

            if matches:
                lbl_match = QLabel(f"✓ Matches: {', '.join(matches)}")
                lbl_match.setStyleSheet("color: #2e7d32; font-weight: 600; font-size: 11px;")
                row_layout.addWidget(lbl_match)

            subsplease_content_layout.addWidget(row_widget)
        else:
            lbl = QLabel(str(sp_title or '(No matching SubsPlease title in cache)'))
            lbl.setStyleSheet("color: gray;")
            subsplease_content_layout.addWidget(lbl)

        aliases = state.get('aliases') or []
        display_map = state.get('alias_display_map') or {}
        if aliases:
            for alias in aliases:
                display_text = display_map.get(alias, alias)
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)

                btn = QPushButton(str(display_text))
                btn.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: normal;")
                btn.clicked.connect(lambda _, val=alias: _apply_variation(val))
                row_layout.addWidget(btn, 1)

                matches = []
                if alias.lower() == must.lower():
                    matches.append("Match Pattern")
                if alias.lower() == _get_base_title(title).lower():
                    matches.append("Title")
                if sanitize_folder_name(alias).lower() == _get_base_path(save_path_edit.text()).lower():
                    matches.append("Save Path")

                if matches:
                    lbl_match = QLabel(f"✓ Matches: {', '.join(matches)}")
                    lbl_match.setStyleSheet("color: #2e7d32; font-weight: 600; font-size: 11px;")
                    row_layout.addWidget(lbl_match)

                anilist_content_layout.addWidget(row_widget)
        else:
            empty_text = state.get('alias_empty_text') or '(No AniList variations cached yet)'
            lbl = QLabel(str(empty_text))
            lbl.setStyleSheet("color: gray;")
            anilist_content_layout.addWidget(lbl)

    editor_layout.addWidget(QLabel('Last Match:'))
    last_match_edit = QLineEdit()
    last_match_edit.setReadOnly(True)
    last_match_edit.setToolTip('Reference field showing the last processed torrent match name (read-only)')
    editor_layout.addWidget(last_match_edit)
    editor_layout.addWidget(QLabel('Save Path:'))
    save_path_edit = QLineEdit()
    save_path_edit.setToolTip('Custom save path override on the server where matching torrents will download')
    editor_layout.addWidget(save_path_edit)
    editor_layout.addWidget(QLabel('Category:'))
    category_combo = QComboBox()
    category_combo.setMaxVisibleItems(20)
    category_combo.setEditable(True)
    category_combo.setToolTip('Assign a qBittorrent category for folder organization on the server')
    try:
        cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
        if isinstance(cached_cats, dict):
            category_combo.addItems(sorted(str(k) for k in cached_cats.keys()))
    except Exception:
        pass
    editor_layout.addWidget(category_combo)
    editor_layout.addWidget(QLabel('Affected Feeds:'))
    affected_feeds_edit = QLineEdit()
    affected_feeds_edit.setToolTip('Comma-separated list of feed URLs this rule applies to')
    editor_layout.addWidget(affected_feeds_edit)

    advanced_btn = QPushButton('Advanced Settings...')
    advanced_btn.setToolTip('Open the Advanced Settings editor for additional qBittorrent rule override parameters')
    editor_layout.addWidget(advanced_btn)
    editor_group.setMinimumWidth(300)
    splitter.addWidget(editor_group)

    edit_undo_stack: list[dict[str, object]] = []
    qt_trash_items: list[dict[str, object]] = []

    def _iter_tree_items() -> list[object]:
        """Iter tree items helper function."""
        return [library_tree.topLevelItem(i) for i in range(library_tree.topLevelItemCount())]

    def _selected_items() -> list[object]:
        """Selected items helper function."""
        return list(library_tree.selectedItems() or [])

    def _collect_rule_rows() -> list[dict[str, str]]:
        """Collect rule rows helper function."""
        rows: list[dict[str, str]] = []
        for item in _iter_tree_items():
            rule = item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            rule_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or '').strip()
            rows.append({'rule_name': rule_name, 'enabled': 'enabled' if bool(rule.get('enabled', False)) else 'disabled'})
        return rows

    def _refresh_chips() -> None:
        """Refresh the chips data."""
        current = getattr(config, 'ALL_TITLES', {}) or {}
        if not isinstance(current, dict):
            current = {}
            config.ALL_TITLES = current
        total = sum(len(v) for v in current.values() if isinstance(v, list))
        titles_chip.setText(f'Titles: {total}')
        connection_chip.setText('Connection: ' + get_connection_status_text(config))

    def _refresh_library_tree(select_rule_name: str | None = None) -> None:
        """Refresh the library tree data."""
        # Save any pending edits before clearing the item ref
        if last_selected_item_ref[0] is not None:
            try:
                _save_rule_to_item(last_selected_item_ref[0])
            except Exception:
                pass
        last_selected_item_ref[0] = None
        if not select_rule_name:
            selected = _selected_items()
            if selected:
                selected_rule = selected[0].data(0, core.Qt.UserRole)
                if isinstance(selected_rule, dict):
                    select_rule_name = str(
                        selected_rule.get('ruleName')
                        or selected_rule.get('node', {}).get('title')
                        or selected[0].text(2)
                        or ''
                    ).strip() or None
        library_tree.setUpdatesEnabled(False)
        library_tree.blockSignals(True)
        try:
            library_tree.clear()
            row_num = 1
            selected_item = None
            current = getattr(config, 'ALL_TITLES', {}) or {}
            if not isinstance(current, dict):
                current = {}
                config.ALL_TITLES = current
            items = []
            for category, titles_list in current.items():
                if not isinstance(titles_list, list):
                    continue
                for rule in titles_list:
                    if not isinstance(rule, dict):
                        continue
                    item = NumericQTreeWidgetItem()
                    rule_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or '(Untitled)')
                    item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
                    item.setText(1, str(row_num))
                    item.setText(2, str(rule.get('node', {}).get('title') or rule_name))
                    item.setText(3, str(rule.get('assignedCategory', '')))
                    item.setText(4, str(rule.get('savePath', '')))
                    item.setData(0, core.Qt.UserRole, rule)
                    item.rule_ref = rule
                    if select_rule_name and rule_name == select_rule_name:
                        selected_item = item
                    items.append(item)
                    row_num += 1
            if items:
                library_tree.addTopLevelItems(items)
            if selected_item is not None:
                library_tree.setCurrentItem(selected_item)
            _apply_filter()
        finally:
            library_tree.blockSignals(False)
            library_tree.setUpdatesEnabled(True)
        _refresh_chips()
        _populate_editor_from_selection()
        auto_save_rules()

    status_bar_ref: dict[str, object | None] = {'bar': None}

    def _set_status(message: str, timeout_ms: int = 0) -> None:
        """Update main status bar text in a single place for parity with Tk status updates."""
        bar = status_bar_ref.get('bar')
        if bar is None:
            return
        text = str(message or '').strip()
        if not text:
            return
        try:
            if int(timeout_ms or 0) > 0:
                bar.showMessage(text, int(timeout_ms))
            else:
                bar.showMessage(text)
        except Exception:
            pass

    def _push_undo(item, rule_before: dict[str, object]) -> None:
        """Push undo helper function."""
        edit_undo_stack.append({'item': item, 'before': copy.deepcopy(rule_before)})
        if len(edit_undo_stack) > 100:
            edit_undo_stack.pop(0)
        undo_btn.setEnabled(True)

    def _action_undo() -> None:
        """Handle the undo UI action."""
        if not edit_undo_stack:
            QMessageBox.information(window, 'Undo', 'Nothing to undo.')
            return
        snapshot = edit_undo_stack.pop()
        item = snapshot.get('item')
        before = snapshot.get('before')
        if item is None or not isinstance(before, dict):
            return
        rule = get_rule_from_item(item)
        if not isinstance(rule, dict):
            return
        rule.clear()
        rule.update(copy.deepcopy(before))
        library_tree.blockSignals(True)
        try:
            item.setData(0, core.Qt.UserRole, rule)
            item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
            item.setText(2, str(rule.get('node', {}).get('title') or rule.get('ruleName', '(Untitled)')))
            item.setText(4, str(rule.get('savePath', '')))
        finally:
            library_tree.blockSignals(False)
        # Keep last_selected_item_ref in sync so the next selection change
        # saves to the correct item (the one whose undo was just applied).
        last_selected_item_ref[0] = item
        _populate_editor_from_selection()
        undo_btn.setEnabled(bool(edit_undo_stack))
        auto_save_rules()

    def _save_rule_to_item(item) -> None:
        """Save rule to item."""
        if item is None:
            return
        rule = get_rule_from_item(item)
        if not isinstance(rule, dict):
            return

        # Only save if there are actual changes to prevent pushing duplicate undo states
        node = dict(rule.get('node') or {})
        current_node_title = node.get('title') or ''
        new_title = title_edit.text().strip()

        current_feeds = rule.get('affectedFeeds', []) or []
        new_feeds = [f.strip() for f in affected_feeds_edit.text().split(',') if f.strip()]

        has_changes = (
            current_node_title != new_title or
            rule.get('mustContain', '') != must_edit.text().strip() or
            rule.get('savePath', '') != save_path_edit.text().strip() or
            rule.get('assignedCategory', '') != category_combo.currentText().strip() or
            bool(rule.get('enabled', False)) != bool(enabled_box.isChecked()) or
            current_feeds != new_feeds
        )
        if not has_changes:
            return

        # Coalesce rapid consecutive edits on the same item: if the last undo entry
        # already captured the before-state for this same item, replace it instead of
        # pushing a new entry, so a single Undo reverts the entire edit session.
        before = copy.deepcopy(rule)
        if edit_undo_stack and edit_undo_stack[-1].get('item') is item:
            # Preserve the oldest 'before' state for this item
            pass
        else:
            _push_undo(item, before)
        node['title'] = new_title
        rule['node'] = node
        rule['ruleName'] = new_title or str(rule.get('ruleName', ''))
        rule['mustContain'] = must_edit.text().strip()
        rule['savePath'] = save_path_edit.text().strip()
        rule['assignedCategory'] = category_combo.currentText().strip()
        rule['affectedFeeds'] = new_feeds
        rule['enabled'] = bool(enabled_box.isChecked())
        library_tree.blockSignals(True)
        try:
            item.setData(0, core.Qt.UserRole, rule)
            item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
            item.setText(2, str(node.get('title') or rule.get('ruleName', '(Untitled)')))
            item.setText(3, str(rule.get('assignedCategory', '')))
            item.setText(4, str(rule.get('savePath', '')))
        finally:
            library_tree.blockSignals(False)
        auto_save_rules()

    def _save_current_rule_from_editor() -> None:
        """Save current rule from editor."""
        selected = _selected_items()
        if selected:
            _save_rule_to_item(selected[0])

    def _on_item_changed(item: QTreeWidgetItem, column: int) -> None:
        """Handle the item changed event."""
        if column == 0:
            rule = get_rule_from_item(item)
            if isinstance(rule, dict):
                is_checked = item.checkState(0) == core.Qt.Checked
                if bool(rule.get('enabled', False)) != is_checked:
                    _push_undo(item, copy.deepcopy(rule))
                    rule['enabled'] = is_checked
                    library_tree.blockSignals(True)
                    try:
                        item.setData(0, core.Qt.UserRole, rule)
                    finally:
                        library_tree.blockSignals(False)
                    selected = _selected_items()
                    if selected and selected[0] == item:
                        enabled_box.blockSignals(True)
                        try:
                            enabled_box.setChecked(is_checked)
                        finally:
                            enabled_box.blockSignals(False)
                    auto_save_rules()

    def _action_toggle_selected() -> None:
        """Handle the toggle selected UI action."""
        selected = _selected_items()
        if not selected:
            return
        library_tree.blockSignals(True)
        try:
            for item in selected:
                rule = get_rule_from_item(item)
                if not isinstance(rule, dict):
                    continue
                _push_undo(item, copy.deepcopy(rule))
                rule['enabled'] = not bool(rule.get('enabled', False))
                item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
                item.setData(0, core.Qt.UserRole, rule)
        finally:
            library_tree.blockSignals(False)
        _populate_editor_from_selection()
        auto_save_rules()

    def _action_bulk_toggle() -> None:
        """Handle the bulk toggle UI action."""
        selected = _selected_items()
        if not selected or len(selected) < 2:
            QMessageBox.information(
                window,
                'Bulk Edit',
                'Please select 2 or more items to use bulk edit.\n\nTip: Hold Ctrl and click to select multiple items.',
            )
            return

        dialog = QDialog(window)
        dialog.setWindowTitle(f'Bulk Edit - {len(selected)} Selected')
        dialog.resize(560, 360)
        dialog_layout = QVBoxLayout(dialog)

        intro = QLabel('Choose fields to apply across selected rules.')
        dialog_layout.addWidget(intro)

        form_group = QGroupBox('Bulk Changes')
        form_layout = QFormLayout(form_group)
        category_enable = QCheckBox('Update category')
        category_value = QComboBox()
        category_value.setMaxVisibleItems(20)
        category_value.setEditable(True)
        category_value.setInsertPolicy(QComboBox.NoInsert)
        try:
            cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
            if isinstance(cached_cats, dict):
                category_value.addItems(sorted(str(k) for k in cached_cats.keys()))
        except Exception:
            pass
        save_enable = QCheckBox('Update save path')
        save_value = QLineEdit('')
        enabled_enable = QCheckBox('Update enabled state')
        enabled_value = QCheckBox('Enabled')
        enabled_value.setChecked(True)
        form_layout.addRow(category_enable, category_value)
        form_layout.addRow(save_enable, save_value)
        form_layout.addRow(enabled_enable, enabled_value)
        dialog_layout.addWidget(form_group)

        summary = QLabel('No fields selected.')
        dialog_layout.addWidget(summary)

        footer = QHBoxLayout()
        apply_btn = QPushButton('Apply to Selected')
        cancel_btn = QPushButton('Cancel')
        footer.addWidget(apply_btn)
        footer.addStretch(1)
        footer.addWidget(cancel_btn)
        dialog_layout.addLayout(footer)

        def _update_summary() -> None:
            """Update summary helper function."""
            changes = []
            if category_enable.isChecked():
                changes.append(f"Category -> '{category_value.currentText().strip()}'")
            if save_enable.isChecked():
                changes.append(f"Save Path -> '{save_value.text().strip()}'")
            if enabled_enable.isChecked():
                changes.append(f"Enabled -> {'Yes' if enabled_value.isChecked() else 'No'}")
            summary.setText('Will update: ' + ', '.join(changes) if changes else 'No fields selected.')

        category_enable.stateChanged.connect(lambda _=None: _update_summary())
        save_enable.stateChanged.connect(lambda _=None: _update_summary())
        enabled_enable.stateChanged.connect(lambda _=None: _update_summary())
        category_value.currentTextChanged.connect(lambda _=None: _update_summary())
        save_value.textChanged.connect(lambda _=None: _update_summary())
        enabled_value.stateChanged.connect(lambda _=None: _update_summary())

        def _apply_bulk() -> None:
            """Apply changes for bulk."""
            if not (category_enable.isChecked() or save_enable.isChecked() or enabled_enable.isChecked()):
                QMessageBox.warning(dialog, 'Bulk Edit', 'Select at least one field to update.')
                return

            changes_text: list[str] = []
            if category_enable.isChecked():
                changes_text.append(f"- Category: '{category_value.currentText().strip()}'")
            if save_enable.isChecked():
                changes_text.append(f"- Save Path: '{save_value.text().strip()}'")
            if enabled_enable.isChecked():
                changes_text.append(f"- Enabled: {'Yes' if enabled_value.isChecked() else 'No'}")

            confirm_text = (
                f"Update {len(selected)} selected rules with:\n\n" + '\n'.join(changes_text)
            )
            if QMessageBox.question(dialog, 'Confirm Bulk Edit', confirm_text) != QMessageBox.Yes:
                return

            changed_count = 0
            library_tree.blockSignals(True)
            try:
                for item in selected:
                    rule = get_rule_from_item(item)
                    if not isinstance(rule, dict):
                        continue
                    _push_undo(item, copy.deepcopy(rule))
                    if category_enable.isChecked():
                        rule['assignedCategory'] = category_value.currentText().strip()
                        if not isinstance(rule.get('torrentParams'), dict):
                            rule['torrentParams'] = {}
                        rule['torrentParams']['category'] = rule['assignedCategory']
                        item.setText(3, str(rule.get('assignedCategory', '')))
                    if save_enable.isChecked():
                        rule['savePath'] = save_value.text().strip()
                        if not isinstance(rule.get('torrentParams'), dict):
                            rule['torrentParams'] = {}
                        rule['torrentParams']['save_path'] = rule['savePath']
                        item.setText(4, str(rule.get('savePath', '')))
                    if enabled_enable.isChecked():
                        rule['enabled'] = bool(enabled_value.isChecked())
                        item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
                    item.setData(0, core.Qt.UserRole, rule)
                    changed_count += 1
            finally:
                library_tree.blockSignals(False)
            _populate_editor_from_selection()
            dialog.accept()
            if changed_count > 0:
                auto_save_rules()
                _set_status(f'Bulk edit applied to {changed_count} rules')
                QMessageBox.information(window, 'Bulk Edit', f'Updated {changed_count} rule(s).')
            else:
                _set_status('Bulk edit made no changes', 4000)
                QMessageBox.warning(window, 'Bulk Edit', 'No rules were updated.')

        _update_summary()
        apply_btn.clicked.connect(_apply_bulk)
        dialog.exec()

    def _action_batch_review_variations() -> None:
        """Open a review dialog: inspect SubsPlease + AniList suggestions per rule, then apply."""
        selected = _selected_items()
        if not selected:
            QMessageBox.information(window, 'Batch Edit Title', 'Select one or more rules first.')
            return

        import re as _re
        _season_prefix_re = _re.compile(r'^(\s*(?:spring|summer|fall|winter)\s+\d{4}\s*-\s*)', _re.IGNORECASE)
        _path_prefix_re   = _re.compile(r'^((?:spring|summer|fall|winter)\s+\d{4}/)', _re.IGNORECASE)

        # ── 1. Collect candidate data for every selected rule ─────────────────
        rows_data: list[dict] = []
        for tree_item in selected:
            rule = tree_item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            title   = str(rule.get('node', {}).get('title') or rule.get('ruleName', '')).strip()
            must    = str(rule.get('mustContain', '')).strip()
            if not title:
                continue
            state   = build_rule_editor_feed_state(
                current_title=title,
                current_must=must,
                find_subsplease_title_match=find_subsplease_title_match,
                load_title_variations_cache=load_title_variations_cache,
            )
            sp_title = state.get('subsplease_title') or ''
            aliases  = [a for a in (state.get('aliases') or []) if a]
            display_map = state.get('alias_display_map') or {}
            candidates: list[tuple[str, str]] = []       # (label, value)
            if sp_title and sp_title not in ('(No matching SubsPlease title in cache)', '(No title selected)'):
                candidates.append((f'[SubsPlease] {sp_title}', sp_title))
            for alias in aliases:
                display = display_map.get(alias, alias)
                candidates.append((f'[AniList] {display}', alias))
            rows_data.append({
                'tree_item': tree_item,
                'rule':      rule,
                'title':     title,
                'must':      must,
                'candidates': candidates,
            })

        if not rows_data:
            QMessageBox.information(window, 'Batch Edit Title',
                                    'No variation data is available for the selected rules.\n'
                                    'Try refreshing SubsPlease / AniList data first.')
            return

        # ── 2. Build the review dialog ────────────────────────────────────────
        dlg = QDialog(window)
        dlg.setWindowTitle('Batch Edit Title')
        dlg.setMinimumSize(860, 520)
        dlg.resize(1060, 640)
        dlg.setSizeGripEnabled(True)
        dlg_layout = QVBoxLayout(dlg)

        # Field selection checkboxes at the top
        field_bar = QHBoxLayout()
        field_bar.addWidget(QLabel('Apply to:'))
        _f_match = QCheckBox('Match Pattern')
        _f_match.setChecked(var_match_box.isChecked())
        _f_match.setToolTip('Update the mustContain field for each rule')
        _f_title = QCheckBox('Title')
        _f_title.setChecked(var_title_box.isChecked())
        _f_title.setToolTip('Update the rule title (preserving any season/year prefix)')
        _f_path  = QCheckBox('Save Path')
        _f_path.setChecked(var_path_box.isChecked())
        _f_path.setToolTip('Update the save path folder (preserving season/year folder prefix)')
        field_bar.addWidget(_f_match)
        field_bar.addWidget(_f_title)
        field_bar.addWidget(_f_path)
        field_bar.addStretch()
        select_all_btn  = QPushButton('Select All')
        select_all_btn.setToolTip('Mark all rows for applying')
        deselect_btn    = QPushButton('Deselect All')
        deselect_btn.setToolTip('Unmark all rows')
        field_bar.addWidget(select_all_btn)
        field_bar.addWidget(deselect_btn)
        dlg_layout.addLayout(field_bar)

        # Table: Rule Name | Variation Picker | Apply?
        table = QTreeWidget()
        table.setColumnCount(4)
        table.setHeaderLabels(['Rule Name', 'Current Match', 'Variation to Apply', 'Apply?'])
        table.setRootIsDecorated(False)
        table.setUniformRowHeights(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setSortingEnabled(False)
        _hdr = table.header()
        _hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        _hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        _hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        _hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        _hdr.setStretchLastSection(False)
        table.setColumnWidth(3, 60)
        dlg_layout.addWidget(table, 1)

        # Build per-row widgets — stored for retrieval at apply time
        _row_widgets: list[dict] = []   # {combo, check, candidates, row_data}
        for row_data in rows_data:
            ti = QTreeWidgetItem(table)
            ti.setText(0, row_data['title'])
            ti.setText(1, row_data['must'] or '(none)')

            combo = QComboBox()
            combo.setMaxVisibleItems(20)
            candidates = row_data['candidates']
            if candidates:
                for label, _val in candidates:
                    combo.addItem(label)
                combo.setToolTip('Select the variation to apply to this rule')
            else:
                combo.addItem('(no variations found)')
                combo.setEnabled(False)

            table.setItemWidget(ti, 2, combo)

            # Ensure the row has enough height to avoid text clipping inside the combobox
            combo_hint = combo.sizeHint()
            ti.setSizeHint(2, core.QSize(combo_hint.width(), max(38, combo_hint.height() + 6)))

            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(8, 0, 8, 0)
            chk_layout.setAlignment(core.Qt.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(bool(candidates))
            chk.setEnabled(bool(candidates))
            chk.setToolTip('Check to include this rule in the batch apply')
            chk_layout.addWidget(chk)
            table.setItemWidget(ti, 3, chk_widget)
            table.setRowHeight = lambda *_: None  # no-op placeholder

            _row_widgets.append({
                'combo':      combo,
                'check':      chk,
                'candidates': candidates,
                'row_data':   row_data,
            })

        def _set_all_checked(state: bool) -> None:
            """Set all checked helper function."""
            for rw in _row_widgets:
                if rw['check'].isEnabled():
                    rw['check'].setChecked(state)

        select_all_btn.clicked.connect(lambda: _set_all_checked(True))
        deselect_btn.clicked.connect(lambda: _set_all_checked(False))

        # Summary label
        summary_lbl = QLabel('')
        dlg_layout.addWidget(summary_lbl)

        def _update_summary() -> None:
            """Update summary helper function."""
            n = sum(1 for rw in _row_widgets if rw['check'].isChecked())
            summary_lbl.setText(f'{n} of {len(_row_widgets)} rules will be updated.')

        for rw in _row_widgets:
            rw['check'].stateChanged.connect(lambda _=None: _update_summary())
        _update_summary()

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(dlg.reject)
        apply_btn  = QPushButton('Apply Checked')
        apply_btn.setToolTip('Apply the selected variation to each checked rule')
        apply_btn.setDefault(True)
        footer.addWidget(cancel_btn)
        footer.addWidget(apply_btn)
        dlg_layout.addLayout(footer)

        # ── 3. Apply handler ──────────────────────────────────────────────────
        def _do_apply() -> None:
            """Do apply helper function."""
            if not (_f_match.isChecked() or _f_title.isChecked() or _f_path.isChecked()):
                QMessageBox.warning(dlg, 'No Fields Selected',
                                    'Check at least one of Match Pattern, Title, or Save Path.')
                return

            applied, skipped = 0, 0
            library_tree.blockSignals(True)
            try:
                for rw in _row_widgets:
                    if not rw['check'].isChecked():
                        skipped += 1
                        continue
                    candidates = rw['candidates']
                    if not candidates:
                        skipped += 1
                        continue
                    idx   = rw['combo'].currentIndex()
                    if idx < 0 or idx >= len(candidates):
                        skipped += 1
                        continue
                    _label, val = candidates[idx]
                    rule       = rw['row_data']['rule']
                    tree_item  = rw['row_data']['tree_item']

                    _push_undo(tree_item, copy.deepcopy(rule))

                    if _f_match.isChecked():
                        rule['mustContain'] = val
                    if _f_title.isChecked():
                        current_title = str(rule.get('node', {}).get('title') or rule.get('ruleName', '')).strip()
                        m = _season_prefix_re.match(current_title)
                        prefix = m.group(1) if m else ''
                        new_title = prefix + val
                        rule['ruleName'] = new_title
                        if not isinstance(rule.get('node'), dict):
                            rule['node'] = {}
                        rule['node']['title'] = new_title
                        tree_item.setText(2, new_title)
                    if _f_path.isChecked():
                        current_path = str(rule.get('savePath', '') or '').strip()
                        m = _path_prefix_re.match(current_path)
                        prefix = m.group(1) if m else ''
                        rule['savePath'] = prefix + sanitize_folder_name(val)
                        tree_item.setText(4, rule['savePath'])

                    applied += 1
            finally:
                library_tree.blockSignals(False)

            if applied:
                _populate_editor_from_selection()
                auto_save_rules()
                _set_status(f'Applied variations to {applied} rule(s).', 4000)

            dlg.accept()
            QMessageBox.information(
                window,
                'Batch Edit Complete',
                f'Applied: {applied} rule(s)\nSkipped: {skipped} rule(s)',
            )

        apply_btn.clicked.connect(_do_apply)
        dlg.exec()

    def _action_batch_apply_subsplease() -> None:
        """Handle the batch apply subsplease UI action."""

        selected = _selected_items()
        if not selected:
            QMessageBox.information(
                window,
                'Batch Apply SubsPlease Matches',
                'Please select one or more items to apply matches.',
            )
            return

        if not var_match_box.isChecked() and not var_title_box.isChecked() and not var_path_box.isChecked():
            QMessageBox.warning(
                window,
                'Selection Required',
                'Please check at least one of Match Pattern, Title, or Save Path in the Title Variations panel to apply batch matching.'
            )
            return

        # Prepare description of changes
        checked_fields = []
        if var_match_box.isChecked():
            checked_fields.append('Match Pattern')
        if var_title_box.isChecked():
            checked_fields.append('Title')
        if var_path_box.isChecked():
            checked_fields.append('Save Path')
        fields_str = ', '.join(checked_fields)

        confirm_text = (
            f"This will attempt to match the {len(selected)} selected rules with SubsPlease titles "
            f"and apply them to the following fields: {fields_str}.\n\n"
            f"Do you want to proceed?"
        )
        if QMessageBox.question(window, 'Confirm Batch Apply', confirm_text) != QMessageBox.Yes:
            return

        # Map rule names to items to push undo states properly
        rule_to_item = {}
        rule_names = []
        for item in selected:
            rule = item.data(0, core.Qt.UserRole)
            if isinstance(rule, dict):
                rname = str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or '').strip()
                if rname:
                    rule_names.append(rname)
                    rule_to_item[rname] = item

        def _on_before_update(rname: str, before_dict: dict):
            """Handle the before update event."""
            if rname in rule_to_item:
                item = rule_to_item[rname]
                _push_undo(item, before_dict)

        result = run_qt_batch_apply_subsplease(
            rule_names=rule_names,
            update_match=var_match_box.isChecked(),
            update_title=var_title_box.isChecked(),
            update_path=var_path_box.isChecked(),
            on_before_update=_on_before_update
        )

        changed_count = result.get('updated_count', 0)

        # Update the tree item texts for all selected items, since they were updated in-place
        library_tree.blockSignals(True)
        try:
            for item in selected:
                rule = item.data(0, core.Qt.UserRole)
                if isinstance(rule, dict):
                    item.setText(2, str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or ''))
                    item.setText(4, str(rule.get('savePath', '')))
        finally:
            library_tree.blockSignals(False)

        if changed_count > 0:
            _populate_editor_from_selection()
            
            summary_msg = result.get('message', '')
            details_text = ""
            updated_rules = result.get('updated_rules', [])
            unmatched_rules = result.get('unmatched_rules', [])
            if updated_rules:
                details_text += "Successful Matches:\n" + "\n".join(updated_rules) + "\n\n"
            if unmatched_rules:
                details_text += "No Matches Found:\n" + "\n".join(unmatched_rules)

            msg_box = QMessageBox(window)
            msg_box.setWindowTitle("Batch Apply Complete")
            msg_box.setText(summary_msg)
            if details_text:
                msg_box.setDetailedText(details_text)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.exec()
            
            _set_status(f'Batch applied SubsPlease matches to {changed_count} rules')
        else:
            summary_msg = result.get('message', '')
            unmatched_rules = result.get('unmatched_rules', [])
            details_text = "Unmatched Rules:\n" + "\n".join(unmatched_rules)
            
            msg_box = QMessageBox(window)
            msg_box.setWindowTitle("Batch Apply Complete")
            msg_box.setText(summary_msg)
            if details_text:
                msg_box.setDetailedText(details_text)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.exec()
            
            _set_status('Batch apply found no matches', 4000)

    def _selected_rule_names() -> list[str]:
        """Selected rule names helper function."""
        names: list[str] = []
        for item in _selected_items():
            rule = item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or '').strip()
            if name:
                names.append(name)
        return names

    def _should_show_pre_import_check() -> bool:
        """Respect both legacy and current pref names for sanitize preview."""
        try:
            return bool(config.get_pref('show_import_sanitize_check', config.get_pref('pre_import_sanitize_check', True)))
        except Exception:
            return True

    def _show_qt_import_sanitize_check(parsed_data: dict[str, object], source_name: str) -> tuple[bool, bool | None]:
        """Show qt import sanitize check helper function."""
        try:
            default_auto = bool(config.get_pref('auto_sanitize_imports', True))
        except Exception:
            default_auto = True

        snapshots = _snapshot_import_entries(parsed_data)
        changed = [s for s in snapshots if str(s.get('before', '')) != str(s.get('after', ''))]
        critical = [s for s in snapshots if str(s.get('severity', 'ok')).lower() == 'critical']

        if not snapshots:
            return True, default_auto

        dialog = QDialog(window)
        dialog.setWindowTitle(f'Pre-import Check - {source_name}')
        dialog.resize(980, 620)
        dlg_layout = QVBoxLayout(dialog)

        title_label = QLabel('Pre-import Sanitization Check')
        title_label.setStyleSheet('font-weight: 600; font-size: 15px;')
        dlg_layout.addWidget(title_label)

        summary_label = QLabel(
            f'Items scanned: {len(snapshots)}    Will be sanitized: {len(changed)}    Needs manual review: {len(critical)}'
        )
        summary_label.setWordWrap(True)
        dlg_layout.addWidget(summary_label)

        auto_sanitize_box = QCheckBox('Apply automatic sanitization during this import')
        auto_sanitize_box.setChecked(default_auto)
        auto_sanitize_box.setToolTip('Automatically adjust folder names according to sanitization settings during this import')
        dlg_layout.addWidget(auto_sanitize_box)

        controls_row = QHBoxLayout()
        displayed_label = QLabel('Displayed: 0  |  OK: 0  |  WARN: 0  |  CRITICAL: 0')
        controls_row.addWidget(displayed_label, 1)
        toggle_changed_btn = QPushButton('Hide Non-Changed Titles')
        toggle_changed_btn.setToolTip('Toggle view between all imported entries and only those that had names changed by sanitization')
        controls_row.addWidget(toggle_changed_btn)
        dlg_layout.addLayout(controls_row)

        table = QTreeWidget(dialog)
        table.setToolTip('Comparison checklist. Shows how titles will be sanitized. Double-click a row to copy to clipboard')
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        table.setColumnCount(4)
        table.setHeaderLabels(['Severity', 'Display/Before Name', 'After', 'Note'])
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setUniformRowHeights(True)
        table.setColumnWidth(0, 90)
        table.setColumnWidth(1, 340)
        table.setColumnWidth(2, 280)
        table.setColumnWidth(3, 220)
        dlg_layout.addWidget(table, 1)

        try:
            qtgui = importlib.import_module('PySide6.QtGui')
            QColor = getattr(qtgui, 'QColor')
        except Exception:
            QColor = None

        show_changed_only = {'value': False}

        def _populate_snapshot_table() -> None:
            """Populate snapshot table helper function."""
            rows = changed if show_changed_only['value'] else snapshots
            table.setUpdatesEnabled(False)
            try:
                table.clear()
                ok_count = 0
                warn_count = 0
                crit_count = 0
                items_to_add = []

                for entry in rows:
                    sev = str(entry.get('severity', 'ok')).lower()
                    before = str(entry.get('display') or entry.get('before') or '(Untitled)')
                    after = str(entry.get('after') or '')
                    reason = str(entry.get('reason') or '')

                    if sev == 'critical':
                        crit_count += 1
                    elif sev == 'warn':
                        warn_count += 1
                    else:
                        ok_count += 1

                    row = QTreeWidgetItem([sev.upper(), before, after, reason])
                    if QColor is not None:
                        is_dark = getattr(window, '_effective_theme', 'light') == 'dark'
                        if is_dark:
                            bg_crit = QColor('#4a1f1f')
                            fg_crit = QColor('#ffb3b3')
                            bg_warn = QColor('#4a3f1f')
                            fg_warn = QColor('#ffd98a')
                        else:
                            bg_crit = QColor('#fee2e2')
                            fg_crit = QColor('#991b1b')
                            bg_warn = QColor('#fef3c7')
                            fg_warn = QColor('#b45309')

                        if sev == 'critical':
                            for c in range(4):
                                row.setBackground(c, bg_crit)
                                row.setForeground(c, fg_crit)
                        elif sev == 'warn':
                            for c in range(4):
                                row.setBackground(c, bg_warn)
                                row.setForeground(c, fg_warn)
                    items_to_add.append(row)

                if items_to_add:
                    table.addTopLevelItems(items_to_add)
            finally:
                table.setUpdatesEnabled(True)

            displayed_label.setText(
                f'Displayed: {len(rows)}  |  OK: {ok_count}  |  WARN: {warn_count}  |  CRITICAL: {crit_count}'
            )
            if show_changed_only['value']:
                toggle_changed_btn.setText('Show All Titles')
            else:
                toggle_changed_btn.setText('Hide Non-Changed Titles')

        def _toggle_changed_only() -> None:
            """Toggle changed only helper function."""
            show_changed_only['value'] = not show_changed_only['value']
            _populate_snapshot_table()

        toggle_changed_btn.clicked.connect(_toggle_changed_only)

        def _copy_row_to_clipboard(item, _column) -> None:
            """Copy row to clipboard helper function."""
            if item is None:
                return
            row_text = '\t'.join([item.text(i) for i in range(4)])
            QApplication.clipboard().setText(row_text)

        table.itemDoubleClicked.connect(_copy_row_to_clipboard)
        _populate_snapshot_table()

        note = QLabel('Cancel to stop import. Continue to proceed with current options.')
        note.setWordWrap(True)
        dlg_layout.addWidget(note)
        dlg_layout.addWidget(QLabel('Tip: Double-click a row to copy it to clipboard.'))

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setToolTip('Abort import process entirely')
        continue_btn = QPushButton('Continue Import')
        continue_btn.setToolTip('Proceed with import using the selected configuration settings')
        button_row.addWidget(cancel_btn)
        button_row.addWidget(continue_btn)
        dlg_layout.addLayout(button_row)

        cancel_btn.clicked.connect(dialog.reject)
        continue_btn.clicked.connect(dialog.accept)

        if dialog.exec() != QDialog.Accepted:
            return False, None
        return True, bool(auto_sanitize_box.isChecked())

    def _run_qt_import_parsed(parsed: object, source_name: str) -> dict[str, object]:
        """Run qt import parsed helper function."""
        current = getattr(config, 'ALL_TITLES', {}) or {}
        total_titles = sum(len(v) for v in current.values() if isinstance(v, list)) if isinstance(current, dict) else 0
        if not isinstance(parsed, dict) or not parsed:
            return {
                'success': False,
                'message': 'Failed to parse import data.',
                'new_count': 0,
                'duplicates': 0,
                'total_titles': total_titles,
            }

        auto_sanitize_choice = None
        if _should_show_pre_import_check():
            proceed, auto_sanitize_choice = _show_qt_import_sanitize_check(parsed, source_name)
            if not proceed:
                return {
                    'success': False,
                    'message': 'Import cancelled.',
                    'new_count': 0,
                    'duplicates': 0,
                    'total_titles': total_titles,
                }

        prefix_imports = bool(config.get_pref('prefix_imports', True))
        season = season_combo.currentText()
        year = year_combo.currentText()

        success, status_msg, new_count, duplicates = _import_titles_core(
            parsed,
            season,
            year,
            prefix_imports,
            source_name,
            auto_sanitize_override=auto_sanitize_choice,
        )

        if not success and status_msg == 'validation_failed':
            invalid_titles = collect_invalid_folder_titles(parsed)
            lines: list[str] = []
            for display, raw, reason in invalid_titles[:8]:
                shown = str(display or raw or '').strip() or '(Untitled)'
                lines.append(f'- {shown}: {reason}')
            if len(invalid_titles) > 8:
                lines.append(f'... and {len(invalid_titles) - 8} more')

            warning_text = 'Some imported titles are still invalid for folder names. Continue anyway?'
            if lines:
                warning_text = warning_text + '\n\n' + '\n'.join(lines)

            if QMessageBox.question(window, 'Invalid folder names', warning_text) != QMessageBox.Yes:
                return {
                    'success': False,
                    'message': 'Import cancelled.',
                    'new_count': 0,
                    'duplicates': 0,
                    'total_titles': total_titles,
                }

            success, status_msg, new_count, duplicates = _import_titles_core(
                parsed,
                season,
                year,
                prefix_imports,
                source_name,
                auto_sanitize_override=False,
                skip_validation=True,
            )

        current_after = getattr(config, 'ALL_TITLES', {}) or {}
        total_after = sum(len(v) for v in current_after.values() if isinstance(v, list)) if isinstance(current_after, dict) else total_titles
        return {
            'success': bool(success),
            'message': str(status_msg or ('Import completed.' if success else 'Import failed.')),
            'new_count': int(new_count or 0),
            'duplicates': int(duplicates or 0),
            'total_titles': total_after,
        }

    def _action_import_file() -> None:
        """
        Action Handler: Import Rules from Disk.
        
        Opens a file dialog allowing the user to select JSON, CSV, or TXT lists.
        The data is passed to the `_run_qt_import_parsed` helper which parses it,
        sanitizes invalid folder characters, and pushes it into the UI tree view.
        """
        default_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.isdir(default_dir):
            default_dir = ''
        path, _ = QFileDialog.getOpenFileName(window, 'Import Titles', default_dir, 'Data Files (*.json *.csv *.txt);;All Files (*)')
        if not path:
            _set_status('Import cancelled.', 2500)
            return
        _set_status(f'Importing file: {os.path.basename(path)}...')
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                text = fh.read()
        except Exception as exc:
            _set_status(f'Import failed: {exc}', 5000)
            QMessageBox.warning(window, 'Import', f'Failed to read import file: {exc}')
            return

        parsed = import_titles_from_text(text)
        result = _run_qt_import_parsed(parsed, 'file import')
        _set_status(str(result.get('message', 'Import done')), 5000)
        QMessageBox.information(window, 'Import', str(result.get('message', 'Import done')))
        try:
            config.add_recent_file(path)
        except Exception:
            logger.debug('Failed to add file to recent list: %s', path, exc_info=True)
        _refresh_recent_menu()
        _refresh_library_tree()

    def _action_import_clipboard() -> None:
        """Handle the import clipboard UI action."""
        text = str(QApplication.clipboard().text() or '').strip()
        if not text:
            _set_status('Import skipped: clipboard is empty.', 3000)
            QMessageBox.information(window, 'Import', 'Clipboard is empty.')
            return
        _set_status('Importing titles from clipboard...')
        parsed = import_titles_from_text(text)
        result = _run_qt_import_parsed(parsed, 'clipboard import')
        _set_status(str(result.get('message', 'Import done')), 5000)
        QMessageBox.information(window, 'Import', str(result.get('message', 'Import done')))
        _refresh_library_tree()

    def _action_export_all() -> None:
        """Handle the export all UI action."""
        path, _ = QFileDialog.getSaveFileName(
            window,
            'Export All Rules',
            'qbittorrent_rules_export.json',
            'JSON Files (*.json);;All Files (*)',
        )
        if not path:
            return

        result = run_qt_export_all_titles_to_path(path)
        if result.get('success'):
            QMessageBox.information(window, 'Export Complete', str(result.get('message', 'Export completed successfully.')))
        else:
            QMessageBox.warning(window, 'Export Failed', str(result.get('message', 'Failed to export rules.')))

    def _action_export_selected() -> None:
        """Handle the export selected UI action."""
        selected = _selected_rule_names()
        if not selected:
            QMessageBox.information(window, 'Export', 'Select one or more rules first.')
            return
        path, _ = QFileDialog.getSaveFileName(window, 'Export Selected Titles', '', 'JSON Files (*.json);;All Files (*)')
        if not path:
            return
        result = run_qt_export_selected_titles_to_path(path, selected)
        QMessageBox.information(window, 'Export', str(result.get('message', 'Export done')))

    def _action_delete_selected() -> None:
        """Handle the delete selected UI action."""
        selected = _selected_rule_names()
        if not selected:
            return
        should_confirm = bool(config.get_pref('confirm_delete_titles', True))
        if should_confirm:
            if QMessageBox.question(window, 'Delete Selected', f'Delete {len(selected)} selected rule(s) from local library?') != QMessageBox.Yes:
                return

        for item in _selected_items():
            rule = item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            qt_trash_items.append(
                {
                    'src': 'titles',
                    'title': str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or ''),
                    'entry': copy.deepcopy(rule),
                }
            )

        result = run_qt_remove_titles_by_rule_names(selected)
        QMessageBox.information(window, 'Delete', str(result.get('message', 'Done')))
        _refresh_library_tree()

    def _action_view_trash() -> None:
        """Handle the view trash UI action."""
        dialog = QDialog(window)
        dialog.setWindowTitle('Trash')
        dialog.resize(700, 420)
        dialog_layout = QVBoxLayout(dialog)

        trash_list = QListWidget(dialog)
        trash_list.setToolTip('List of rules deleted from local library in the current session. Select rules to restore or purge')
        dialog_layout.addWidget(trash_list, 1)

        def _reload_trash() -> None:
            """Reload trash helper function."""
            trash_list.clear()
            for it in qt_trash_items:
                trash_list.addItem(f"{it.get('src', 'titles')} - {it.get('title', '(untitled)')}")

        def _restore_selected() -> None:
            """Restore selected helper function."""
            rows = sorted({idx.row() for idx in trash_list.selectedIndexes()}, reverse=True)
            if not rows:
                QMessageBox.information(dialog, 'Trash', 'No trash item selected.')
                return
            restored_count = 0
            current = getattr(config, 'ALL_TITLES', {}) or {}
            if not isinstance(current, dict):
                current = {}
                config.ALL_TITLES = current
            if 'restored' not in current or not isinstance(current.get('restored'), list):
                current['restored'] = []

            for row in rows:
                if row < 0 or row >= len(qt_trash_items):
                    continue
                it = qt_trash_items.pop(row)
                entry = it.get('entry')
                if isinstance(entry, dict):
                    current['restored'].append(entry)
                    restored_count += 1
            config.ALL_TITLES = current
            _reload_trash()
            _refresh_library_tree()
            QMessageBox.information(dialog, 'Trash', f'Restored {restored_count} item(s).')

        def _delete_permanently() -> None:
            """Delete permanently."""
            rows = sorted({idx.row() for idx in trash_list.selectedIndexes()}, reverse=True)
            if not rows:
                QMessageBox.information(dialog, 'Trash', 'No trash item selected.')
                return
            if QMessageBox.question(dialog, 'Trash', f'Delete {len(rows)} selected item(s) permanently?') != QMessageBox.Yes:
                return
            for row in rows:
                if 0 <= row < len(qt_trash_items):
                    qt_trash_items.pop(row)
            _reload_trash()

        def _empty_trash() -> None:
            """Empty trash helper function."""
            if not qt_trash_items:
                return
            if QMessageBox.question(dialog, 'Trash', 'Empty the trash permanently?') != QMessageBox.Yes:
                return
            qt_trash_items.clear()
            _reload_trash()

        button_row = QHBoxLayout()
        restore_btn = QPushButton('Restore Selected')
        restore_btn.setToolTip('Restore selected rules back to your active library')
        delete_btn = QPushButton('Delete Permanently')
        delete_btn.setToolTip('Permanently delete selected items from memory (cannot be undone)')
        empty_btn = QPushButton('Empty Trash')
        empty_btn.setToolTip('Permanently clear all items in the trash')
        close_btn = QPushButton('Close')
        close_btn.setToolTip('Close the trash manager window')
        restore_btn.clicked.connect(_restore_selected)
        delete_btn.clicked.connect(_delete_permanently)
        empty_btn.clicked.connect(_empty_trash)
        close_btn.clicked.connect(dialog.accept)
        button_row.addWidget(restore_btn)
        button_row.addWidget(delete_btn)
        button_row.addWidget(empty_btn)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        dialog_layout.addLayout(button_row)

        _reload_trash()
        dialog.exec()

    def _action_clear_all_titles() -> None:
        """Handle the clear all titles UI action."""
        should_confirm = bool(config.get_pref('confirm_delete_titles', True))
        if should_confirm:
            if QMessageBox.question(window, 'Confirm', 'Clear all loaded titles?') != QMessageBox.Yes:
                return
        result = run_qt_clear_all_titles()
        QMessageBox.information(window, 'Clear All', str(result.get('message', 'Cleared')))
        _refresh_library_tree()

    def _action_validate_all() -> None:
        """Handle the validate all UI action."""
        try:
            current = getattr(config, 'ALL_TITLES', {}) or {}
            if not isinstance(current, dict):
                current = {}

            entries: list[tuple[str, dict[str, object]]] = []
            for _group, items in current.items():
                if not isinstance(items, list):
                    continue
                for entry in items:
                    if isinstance(entry, dict):
                        title_text = str(get_display_title(entry, '') or get_rule_name(entry, '') or '(Untitled)')
                        entries.append((title_text, entry))

            if not entries:
                _set_status('Validation: no titles to validate.', 4000)
                QMessageBox.information(window, 'Validation', 'No titles to validate.')
                return

            problems: list[str] = []
            for title_text, entry in entries:
                node = entry.get('node') or {}
                node_title = node.get('title') if isinstance(node, dict) else None
                effective_title = node_title or entry.get('mustContain') or title_text
                if not str(effective_title or '').strip():
                    problems.append(f'Missing title for item: {title_text}')

                lm = entry.get('lastMatch', '')
                if isinstance(lm, str):
                    s = lm.strip()
                    if s and (s.startswith('{') or s.startswith('[') or s.startswith('"')):
                        try:
                            json.loads(s)
                        except Exception as exc:
                            problems.append(f'Invalid JSON lastMatch for "{title_text}": {exc}')

                save_path = entry.get('savePath') or entry.get('save_path') or ''
                if not save_path:
                    tp = entry.get('torrentParams') or entry.get('torrent_params') or {}
                    if isinstance(tp, dict):
                        save_path = tp.get('save_path') or tp.get('savePath') or ''

                if save_path:
                    parts = [p for p in str(save_path).replace('\\', '/').split('/') if str(p).strip()]
                    for folder in parts:
                        valid, reason = validate_folder_name_by_filesystem(str(folder))
                        if not valid:
                            problems.append(f'Invalid folder in path for "{title_text}": "{folder}" - {reason}')
                            break

            result_dlg = QDialog(window)
            result_dlg.setWindowTitle('Validation Results')
            result_dlg.resize(820, 560)
            dlg_layout = QVBoxLayout(result_dlg)

            header = QLabel()
            header.setWordWrap(True)
            if problems:
                header.setText(f'Validation found {len(problems)} issue(s) in {len(entries)} title(s).')
                header.setStyleSheet('font-weight: 600; color: #d32f2f;')
                _set_status(f'Validation found {len(problems)} issue(s).', 6000)
            else:
                header.setText(f'All {len(entries)} title(s) validated successfully.')
                header.setStyleSheet('font-weight: 600; color: #2e7d32;')
                _set_status(f'Validation passed for {len(entries)} title(s).', 5000)
            dlg_layout.addWidget(header)

            if problems:
                issues = QTextEdit(result_dlg)
                issues.setReadOnly(True)
                issues.setLineWrapMode(QTextEdit.WidgetWidth)
                issues.setStyleSheet('background: #fff3cd; color: #856404; font-family: Consolas, monospace;')
                issues.setPlainText('\n\n'.join([str(p) for p in problems]))
                dlg_layout.addWidget(issues, 1)

            buttons = QHBoxLayout()
            buttons.addStretch(1)
            close_btn = QPushButton('Close')
            close_btn.clicked.connect(result_dlg.accept)
            buttons.addWidget(close_btn)
            dlg_layout.addLayout(buttons)

            result_dlg.exec()
        except Exception as exc:
            logger.error('Validation failed: %s', exc, exc_info=True)
            _set_status(f'Validation error: {exc}', 6000)
            QMessageBox.warning(window, 'Validation Error', f'An error occurred: {exc}')

    def _action_create_backup() -> None:
        """Handle the create backup UI action."""
        snapshot = run_qt_qbittorrent_snapshot()
        success, message = create_backup(
            rules=(snapshot.get('rules') if isinstance(snapshot, dict) else {}) or {},
            categories=(snapshot.get('categories') if isinstance(snapshot, dict) else {}) or {},
            feeds=(snapshot.get('feeds') if isinstance(snapshot, dict) else []) or [],
        )
        if success:
            QMessageBox.information(window, 'Backup', message)
        else:
            QMessageBox.warning(window, 'Backup', message)

    def _action_restore_backup() -> None:
        """Handle the restore backup UI action."""
        backups = list_backups()
        if not backups:
            QMessageBox.information(window, 'Restore', 'No backup files found.')
            return
        paths = [b[1] for b in backups]
        labels = [b[0] for b in backups]
        selected_label, ok = QInputDialog.getItem(window, 'Restore Backup', 'Select backup file:', labels, 0, False)
        if not ok:
            return
        idx = labels.index(selected_label)
        ok_load, backup_data, message = load_backup(paths[idx])
        if not ok_load or not isinstance(backup_data, dict):
            QMessageBox.warning(window, 'Restore', message)
            return
        rules = backup_data.get('rules', {})
        if not isinstance(rules, dict):
            QMessageBox.warning(window, 'Restore', 'Backup rules payload is invalid.')
            return

        metadata = extract_backup_metadata(backup_data)
        mode_dialog = QDialog(window)
        mode_dialog.setWindowTitle('Restore Mode')
        mode_dialog.resize(540, 320)
        mode_layout = QVBoxLayout(mode_dialog)
        info_label = QLabel(
            f"Backup Time: {metadata.get('backup_time', 'Unknown')}\n"
            f"Rules: {metadata.get('rule_count', '0')}\n"
            f"Categories: {metadata.get('category_count', '0')}\n"
            f"Feeds: {metadata.get('feed_count', '0')}"
        )
        mode_layout.addWidget(info_label)

        merge_radio = QRadioButton('Merge with existing local rules (recommended)')
        replace_radio = QRadioButton('Replace local rules with backup rules')
        merge_radio.setChecked(True)
        mode_layout.addWidget(merge_radio)
        mode_layout.addWidget(replace_radio)

        warn = QLabel('Replace mode will overwrite current local rule set.')
        warn.setStyleSheet('color: #c0392b;')
        mode_layout.addWidget(warn)

        mode_buttons = QHBoxLayout()
        apply_mode_btn = QPushButton('Apply Restore')
        cancel_mode_btn = QPushButton('Cancel')
        mode_buttons.addWidget(apply_mode_btn)
        mode_buttons.addStretch(1)
        mode_buttons.addWidget(cancel_mode_btn)
        mode_layout.addLayout(mode_buttons)

        def _apply_restore_mode() -> None:
            """Apply changes for restore mode."""
            restored_entries = [dict(v) for v in rules.values() if isinstance(v, dict)]
            if replace_radio.isChecked():
                config.ALL_TITLES = {'restored': restored_entries}
            else:
                current = getattr(config, 'ALL_TITLES', {}) or {}
                if not isinstance(current, dict):
                    current = {}
                existing_keys: set[str] = set()
                for lst in current.values():
                    if not isinstance(lst, list):
                        continue
                    for entry in lst:
                        if not isinstance(entry, dict):
                            continue
                        key = str(entry.get('ruleName') or entry.get('node', {}).get('title') or '').strip()
                        if key:
                            existing_keys.add(key)
                target = current.setdefault('restored', [])
                if not isinstance(target, list):
                    target = []
                    current['restored'] = target
                for entry in restored_entries:
                    key = str(entry.get('ruleName') or entry.get('node', {}).get('title') or '').strip()
                    if key and key in existing_keys:
                        continue
                    target.append(entry)
                    if key:
                        existing_keys.add(key)
                config.ALL_TITLES = current
            mode_dialog.accept()

        apply_mode_btn.clicked.connect(_apply_restore_mode)
        cancel_mode_btn.clicked.connect(mode_dialog.reject)
        if mode_dialog.exec() != QDialog.Accepted:
            return

        _refresh_library_tree()
        QMessageBox.information(window, 'Restore', f'Restored {len(config.ALL_TITLES.get("restored", []))} rules into local library.')

    def _action_manage_backups() -> None:
        """Handle the manage backups UI action."""
        dialog = QDialog(window)
        dialog.setWindowTitle('Manage Backups')
        dialog.resize(760, 460)
        dialog_layout = QVBoxLayout(dialog)

        list_widget = QListWidget(dialog)
        dialog_layout.addWidget(list_widget, 1)
        backup_map: dict[int, tuple[str, str, object]] = {}

        def _reload_backups() -> None:
            """Reload backups helper function."""
            list_widget.clear()
            backup_map.clear()
            backups = list_backups()
            for idx, entry in enumerate(backups):
                name, path, dt = entry
                backup_map[idx] = entry
                list_widget.addItem(f"{name}  ({dt.strftime('%Y-%m-%d %H:%M:%S')})")

        def _create_backup_now() -> None:
            """Create backup now helper function."""
            snapshot = run_qt_qbittorrent_snapshot()
            success, message = create_backup(
                rules=(snapshot.get('rules') if isinstance(snapshot, dict) else {}) or {},
                categories=(snapshot.get('categories') if isinstance(snapshot, dict) else {}) or {},
                feeds=(snapshot.get('feeds') if isinstance(snapshot, dict) else []) or [],
            )
            if success:
                QMessageBox.information(dialog, 'Backup', message)
                _reload_backups()
            else:
                QMessageBox.warning(dialog, 'Backup', message)

        def _restore_selected_backup() -> None:
            """Restore selected backup helper function."""
            idx = list_widget.currentRow()
            if idx < 0 or idx not in backup_map:
                QMessageBox.information(dialog, 'Restore', 'Select a backup first.')
                return
            _, backup_path, _ = backup_map[idx]
            ok_load, backup_data, message = load_backup(backup_path)
            if not ok_load or not isinstance(backup_data, dict):
                QMessageBox.warning(dialog, 'Restore', message)
                return
            rules = backup_data.get('rules', {})
            if not isinstance(rules, dict):
                QMessageBox.warning(dialog, 'Restore', 'Backup rules payload is invalid.')
                return
            metadata = extract_backup_metadata(backup_data)
            mode_dialog = QDialog(dialog)
            mode_dialog.setWindowTitle('Restore Mode')
            mode_dialog.resize(520, 300)
            mode_layout = QVBoxLayout(mode_dialog)
            mode_layout.addWidget(
                QLabel(
                    f"Backup Time: {metadata.get('backup_time', 'Unknown')}\n"
                    f"Rules: {metadata.get('rule_count', '0')}\n"
                    f"Categories: {metadata.get('category_count', '0')}\n"
                    f"Feeds: {metadata.get('feed_count', '0')}"
                )
            )
            merge_radio = QRadioButton('Merge with existing local rules')
            replace_radio = QRadioButton('Replace local rules with backup rules')
            merge_radio.setChecked(True)
            mode_layout.addWidget(merge_radio)
            mode_layout.addWidget(replace_radio)
            mode_layout.addWidget(QLabel('Replace mode will overwrite current local rule set.'))

            buttons = QHBoxLayout()
            apply_btn = QPushButton('Apply Restore')
            cancel_btn = QPushButton('Cancel')
            buttons.addWidget(apply_btn)
            buttons.addStretch(1)
            buttons.addWidget(cancel_btn)
            mode_layout.addLayout(buttons)

            def _apply_mode() -> None:
                """Apply changes for mode."""
                restored_entries = [dict(v) for v in rules.values() if isinstance(v, dict)]
                if replace_radio.isChecked():
                    config.ALL_TITLES = {'restored': restored_entries}
                else:
                    current = getattr(config, 'ALL_TITLES', {}) or {}
                    if not isinstance(current, dict):
                        current = {}
                    known: set[str] = set()
                    for lst in current.values():
                        if not isinstance(lst, list):
                            continue
                        for entry in lst:
                            if not isinstance(entry, dict):
                                continue
                            key = str(entry.get('ruleName') or entry.get('node', {}).get('title') or '').strip()
                            if key:
                                known.add(key)
                    target = current.setdefault('restored', [])
                    if not isinstance(target, list):
                        target = []
                        current['restored'] = target
                    for entry in restored_entries:
                        key = str(entry.get('ruleName') or entry.get('node', {}).get('title') or '').strip()
                        if key and key in known:
                            continue
                        target.append(entry)
                        if key:
                            known.add(key)
                    config.ALL_TITLES = current
                mode_dialog.accept()

            apply_btn.clicked.connect(_apply_mode)
            cancel_btn.clicked.connect(mode_dialog.reject)
            if mode_dialog.exec() != QDialog.Accepted:
                return

            _refresh_library_tree()
            QMessageBox.information(dialog, 'Restore', f'Restored {len(config.ALL_TITLES.get("restored", []))} rules into local library.')

        def _delete_selected_backup() -> None:
            """Delete selected backup."""
            idx = list_widget.currentRow()
            if idx < 0 or idx not in backup_map:
                QMessageBox.information(dialog, 'Delete Backup', 'Select a backup first.')
                return
            name, backup_path, _ = backup_map[idx]
            if QMessageBox.question(dialog, 'Delete Backup', f'Delete backup "{name}"?') != QMessageBox.Yes:
                return
            try:
                os.remove(backup_path)
                _reload_backups()
                QMessageBox.information(dialog, 'Delete Backup', f'Deleted backup "{name}".')
            except Exception as exc:
                QMessageBox.warning(dialog, 'Delete Backup', f'Failed deleting backup: {exc}')

        button_row = QHBoxLayout()
        refresh_btn = QPushButton('Refresh')
        create_btn = QPushButton('Create Backup')
        restore_btn = QPushButton('Restore Selected')
        delete_btn = QPushButton('Delete Selected')
        close_btn = QPushButton('Close')
        button_row.addWidget(refresh_btn)
        button_row.addWidget(create_btn)
        button_row.addWidget(restore_btn)
        button_row.addWidget(delete_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        dialog_layout.addLayout(button_row)

        refresh_btn.clicked.connect(_reload_backups)
        create_btn.clicked.connect(_create_backup_now)
        restore_btn.clicked.connect(_restore_selected_backup)
        delete_btn.clicked.connect(_delete_selected_backup)
        close_btn.clicked.connect(dialog.accept)
        _reload_backups()
        dialog.exec()

    def _load_template_dict() -> dict[str, dict[str, object]]:
        """Load template dict helper function."""
        templates = load_templates() or {}
        if not isinstance(templates, dict) or not templates:
            templates = get_default_templates()
            try:
                save_templates(templates)
            except Exception:
                pass
        return {str(k): v for k, v in templates.items() if isinstance(v, dict)}

    def _selected_rule_entry() -> tuple[object | None, dict[str, object] | None]:
        """Selected rule entry helper function."""
        selected = _selected_items()
        if not selected:
            return None, None
        item = selected[0]
        rule = get_rule_from_item(item)
        if not isinstance(rule, dict):
            return item, None
        return item, rule

    def _apply_template_to_rule(item, rule: dict[str, object], template: dict[str, object]) -> None:
        """Apply changes for template to rule."""
        _push_undo(item, copy.deepcopy(rule))
        apply_template_data_to_rule(rule, template)
        library_tree.blockSignals(True)
        try:
            item.setData(0, core.Qt.UserRole, rule)
            item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
            item.setText(3, str(rule.get('assignedCategory', '')))
            item.setText(4, str(rule.get('savePath', '')))
        finally:
            library_tree.blockSignals(False)
        _populate_editor_from_selection()
        auto_save_rules()

    def _action_apply_template() -> None:
        """Handle the apply template UI action."""
        item, rule = _selected_rule_entry()
        if item is None or rule is None:
            QMessageBox.information(window, 'Templates', 'Select a rule first.')
            return
        templates = _load_template_dict()
        names = sorted(templates.keys())
        if not names:
            QMessageBox.information(window, 'Templates', 'No templates available.')
            return
        selected_name, ok = QInputDialog.getItem(window, 'Apply Template', 'Template:', names, 0, False)
        if not ok or not selected_name:
            return
        _apply_template_to_rule(item, rule, templates.get(str(selected_name), {}))
        _set_status(f'Template "{selected_name}" applied to selected rule', 4000)

    def _action_save_template() -> None:
        """Handle the save template UI action."""
        _, rule = _selected_rule_entry()
        if rule is None:
            QMessageBox.information(window, 'Templates', 'Select a rule first.')
            return
        default_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or 'New Template')
        name, ok = QInputDialog.getText(window, 'Save Template', 'Template name:', text=default_name)
        if not ok:
            return
        template_name = str(name or '').strip()
        if not template_name:
            QMessageBox.warning(window, 'Templates', 'Template name is required.')
            return
        template = {
            'description': f'Saved from rule {default_name}',
            'must_contain': str(rule.get('mustContain', '') or ''),
            'must_not_contain': str(rule.get('mustNotContain', '') or ''),
            'category': str(rule.get('assignedCategory', '') or ''),
            'save_path': str(rule.get('savePath', '') or ''),
            'enabled': bool(rule.get('enabled', True)),
            'episode_filter': str(rule.get('episodeFilter', '') or ''),
            'use_regex': bool(rule.get('useRegex', False)),
        }
        templates = _load_template_dict()
        if template_name in templates:
            if QMessageBox.question(window, 'Overwrite Template', f'Template "{template_name}" already exists. Overwrite?') != QMessageBox.Yes:
                return
        templates[template_name] = template
        ok_save = save_templates(templates)
        if ok_save:
            _set_status(f'Template "{template_name}" saved', 4000)
            QMessageBox.information(window, 'Templates', f'Template "{template_name}" saved.')
        else:
            _set_status('Failed to save template', 5000)
            QMessageBox.warning(window, 'Templates', 'Failed to save template.')

    def _action_manage_templates() -> None:
        """Handle the manage templates UI action."""
        dialog = QDialog(window)
        dialog.setWindowTitle('Manage Templates')
        dialog.resize(920, 620)
        dialog_layout = QVBoxLayout(dialog)

        split = QSplitter(dialog)
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_widget = QListWidget(list_panel)
        list_widget.setToolTip('List of saved templates. Select a template to edit its fields or apply it')
        list_layout.addWidget(list_widget, 1)
        split.addWidget(list_panel)

        edit_panel = QWidget()
        edit_layout = QFormLayout(edit_panel)
        tpl_desc = QLineEdit('')
        tpl_desc.setToolTip("Optional description explaining the template's purpose")
        tpl_must = QLineEdit('')
        tpl_must.setToolTip("Matching pattern required in the torrent name")
        tpl_must_not = QLineEdit('')
        tpl_must_not.setToolTip("Matching pattern to exclude torrents from being processed")
        tpl_category = QLineEdit('')
        tpl_category.setToolTip("The category to assign to torrents matched by this template")
        tpl_save = QLineEdit('')
        tpl_save.setToolTip("Specific download folder path override for matching torrents")
        tpl_episode = QLineEdit('')
        tpl_episode.setToolTip("Episode number filters (e.g. 1-12, or empty for all)")
        tpl_enabled = QCheckBox('Enabled')
        tpl_enabled.setToolTip("Toggle active status of the template rule")
        tpl_regex = QCheckBox('Use regex')
        tpl_regex.setToolTip("Enable regular expression evaluation on the matching pattern fields")
        preview = QTextEdit(edit_panel)
        preview.setReadOnly(True)
        preview.setMinimumHeight(160)
        preview.setToolTip("Preview of the JSON configuration payload for the selected template")
        edit_layout.addRow('Description:', tpl_desc)
        edit_layout.addRow('Must contain:', tpl_must)
        edit_layout.addRow('Must not contain:', tpl_must_not)
        edit_layout.addRow('Category:', tpl_category)
        edit_layout.addRow('Save path:', tpl_save)
        edit_layout.addRow('Episode filter:', tpl_episode)
        edit_layout.addRow('', tpl_enabled)
        edit_layout.addRow('', tpl_regex)
        edit_layout.addRow('Preview:', preview)
        split.addWidget(edit_panel)
        split.setSizes([280, 620])
        dialog_layout.addWidget(split, 1)

        templates = _load_template_dict()

        def _reload_template_list(select_name: str | None = None) -> None:
            """Reload template list helper function."""
            list_widget.clear()
            names = sorted(templates.keys())
            for name in names:
                list_widget.addItem(name)
            if names:
                target = select_name if select_name in names else names[0]
                for i in range(list_widget.count()):
                    if list_widget.item(i).text() == target:
                        list_widget.setCurrentRow(i)
                        break

        def _update_preview_and_fields() -> None:
            """Update preview and fields helper function."""
            current = list_widget.currentItem()
            if current is None:
                tpl_desc.setText('')
                tpl_must.setText('')
                tpl_must_not.setText('')
                tpl_category.setText('')
                tpl_save.setText('')
                tpl_episode.setText('')
                tpl_enabled.setChecked(True)
                tpl_regex.setChecked(False)
                preview.setPlainText('')
                return
            name = str(current.text())
            tpl = templates.get(name, {})
            tpl_desc.setText(str(tpl.get('description', '') or ''))
            tpl_must.setText(str(tpl.get('must_contain', '') or ''))
            tpl_must_not.setText(str(tpl.get('must_not_contain', '') or ''))
            tpl_category.setText(str(tpl.get('category', '') or ''))
            tpl_save.setText(str(tpl.get('save_path', '') or ''))
            tpl_episode.setText(str(tpl.get('episode_filter', '') or ''))
            tpl_enabled.setChecked(bool(tpl.get('enabled', True)))
            tpl_regex.setChecked(bool(tpl.get('use_regex', False)))
            try:
                preview.setPlainText(json.dumps(tpl, indent=2, ensure_ascii=False))
            except Exception:
                preview.setPlainText(str(tpl))

        def _collect_current_template() -> dict[str, object]:
            """Collect current template helper function."""
            return {
                'description': tpl_desc.text().strip(),
                'must_contain': tpl_must.text().strip(),
                'must_not_contain': tpl_must_not.text().strip(),
                'category': tpl_category.text().strip(),
                'save_path': tpl_save.text().strip(),
                'episode_filter': tpl_episode.text().strip(),
                'enabled': bool(tpl_enabled.isChecked()),
                'use_regex': bool(tpl_regex.isChecked()),
            }

        button_row = QHBoxLayout()
        new_btn = QPushButton('New')
        new_btn.setToolTip('Create a new empty template config')
        save_btn = QPushButton('Save Changes')
        save_btn.setToolTip('Save edited fields to the current template definition')
        apply_btn = QPushButton('Apply to Selected Rule')
        apply_btn.setToolTip('Apply the selected template parameters directly to the rule currently highlighted in the library')
        delete_btn = QPushButton('Delete')
        delete_btn.setToolTip('Delete the selected template profile permanently')
        reset_btn = QPushButton('Reset Defaults')
        reset_btn.setToolTip('Reset templates list back to the default package configurations')
        close_btn = QPushButton('Close')
        close_btn.setToolTip('Close the templates manager window')
        button_row.addWidget(new_btn)
        button_row.addWidget(save_btn)
        button_row.addWidget(apply_btn)
        button_row.addWidget(delete_btn)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        dialog_layout.addLayout(button_row)

        def _new_template() -> None:
            """New template helper function."""
            name, ok = QInputDialog.getText(dialog, 'New Template', 'Template name:')
            name = str(name or '').strip()
            if not ok or not name:
                return
            if name in templates:
                if QMessageBox.question(dialog, 'Overwrite Template', f'Template "{name}" already exists. Overwrite?') != QMessageBox.Yes:
                    return
            _, selected_rule = _selected_rule_entry()
            if isinstance(selected_rule, dict):
                templates[name] = {
                    'description': f'Saved from rule {selected_rule.get("ruleName", "")}',
                    'must_contain': str(selected_rule.get('mustContain', '') or ''),
                    'must_not_contain': str(selected_rule.get('mustNotContain', '') or ''),
                    'category': str(selected_rule.get('assignedCategory', '') or ''),
                    'save_path': str(selected_rule.get('savePath', '') or ''),
                    'episode_filter': str(selected_rule.get('episodeFilter', '') or ''),
                    'enabled': bool(selected_rule.get('enabled', True)),
                    'use_regex': bool(selected_rule.get('useRegex', False)),
                }
            else:
                templates[name] = _collect_current_template()
            if save_templates(templates):
                _set_status(f'Template "{name}" saved', 4000)
                _reload_template_list(select_name=name)
            else:
                _set_status('Failed to save template', 5000)
                QMessageBox.warning(dialog, 'Templates', 'Failed to save template.')

        def _save_template_changes() -> None:
            """Save template changes."""
            current = list_widget.currentItem()
            if current is None:
                QMessageBox.information(dialog, 'Templates', 'Select a template first.')
                return
            name = str(current.text())
            templates[name] = _collect_current_template()
            if save_templates(templates):
                _update_preview_and_fields()
                _set_status(f'Template "{name}" updated', 4000)
                QMessageBox.information(dialog, 'Templates', f'Template "{name}" updated.')
            else:
                _set_status('Failed to save template changes', 5000)
                QMessageBox.warning(dialog, 'Templates', 'Failed to save template changes.')

        def _apply_template_from_manager() -> None:
            """Apply changes for template from manager."""
            item, rule = _selected_rule_entry()
            current = list_widget.currentItem()
            if item is None or rule is None:
                QMessageBox.information(dialog, 'Templates', 'Select a rule in the library first.')
                return
            if current is None:
                QMessageBox.information(dialog, 'Templates', 'Select a template first.')
                return
            name = str(current.text())
            template = templates.get(name, {})
            _apply_template_to_rule(item, rule, template)
            _set_status(f'Template "{name}" applied to selected rule', 4000)
            QMessageBox.information(dialog, 'Templates', f'Applied template "{name}" to selected rule.')

        def _delete_template() -> None:
            """Delete template."""
            current = list_widget.currentItem()
            if current is None:
                return
            name = str(current.text())
            if QMessageBox.question(dialog, 'Delete Template', f'Delete template "{name}"?') != QMessageBox.Yes:
                return
            templates.pop(name, None)
            if save_templates(templates):
                _set_status(f'Template "{name}" deleted', 4000)
                _reload_template_list()
            else:
                _set_status('Failed to delete template', 5000)
                QMessageBox.warning(dialog, 'Templates', 'Failed to delete template.')

        def _reset_defaults() -> None:
            """Reset defaults helper function."""
            if QMessageBox.question(dialog, 'Reset Templates', 'Replace all templates with defaults?') != QMessageBox.Yes:
                return
            templates.clear()
            templates.update(get_default_templates())
            if save_templates(templates):
                _set_status('Templates reset to defaults', 4000)
                _reload_template_list()
            else:
                _set_status('Failed to reset templates', 5000)
                QMessageBox.warning(dialog, 'Templates', 'Failed to reset templates.')

        list_widget.currentItemChanged.connect(lambda _a=None, _b=None: _update_preview_and_fields())
        for widget in [tpl_desc, tpl_must, tpl_must_not, tpl_category, tpl_save, tpl_episode]:
            widget.textChanged.connect(lambda _=None: preview.setPlainText(json.dumps(_collect_current_template(), indent=2, ensure_ascii=False)))
        tpl_enabled.stateChanged.connect(lambda _=None: preview.setPlainText(json.dumps(_collect_current_template(), indent=2, ensure_ascii=False)))
        tpl_regex.stateChanged.connect(lambda _=None: preview.setPlainText(json.dumps(_collect_current_template(), indent=2, ensure_ascii=False)))
        new_btn.clicked.connect(_new_template)
        save_btn.clicked.connect(_save_template_changes)
        apply_btn.clicked.connect(_apply_template_from_manager)
        delete_btn.clicked.connect(_delete_template)
        reset_btn.clicked.connect(_reset_defaults)
        close_btn.clicked.connect(dialog.accept)

        _reload_template_list()
        _update_preview_and_fields()
        dialog.exec()

    def _open_advanced_editor() -> None:
        """Open the advanced editor window or dialog."""
        item, rule = _selected_rule_entry()
        if item is None or rule is None:
            QMessageBox.information(window, 'Advanced Rule Editor', 'Select a rule first.')
            return

        dialog = QDialog(window)
        dialog.setWindowTitle('Advanced Rule Editor')
        dialog.setMinimumSize(700, 520)
        dialog.resize(920, 720)
        dialog.setSizeGripEnabled(True)
        dialog_layout = QVBoxLayout(dialog)

        # Wrap the form in a scroll area so it works at any screen size
        _adv_scroll = QScrollArea()
        _adv_scroll.setWidgetResizable(True)
        _adv_scroll.setFrameShape(QFrame.NoFrame)
        _adv_form_widget = QWidget()
        _adv_form_layout = QVBoxLayout(_adv_form_widget)
        _adv_scroll.setWidget(_adv_form_widget)
        dialog_layout.addWidget(_adv_scroll, 1)

        form = QFormLayout()
        _adv_form_layout.addLayout(form)
        adv_title = QLineEdit(str(rule.get('node', {}).get('title') or rule.get('ruleName', '')))
        adv_title.setToolTip("Name of the RSS rule in qBittorrent")
        adv_must = QLineEdit(str(rule.get('mustContain', '')))
        adv_must.setToolTip("Regex or text pattern that the torrent title must contain to match")
        adv_must_not = QLineEdit(str(rule.get('mustNotContain', '')))
        adv_must_not.setToolTip("Regex or text pattern that the torrent title must NOT contain to match")
        adv_save = QLineEdit(str(rule.get('savePath', '')))
        adv_save.setToolTip("Specific download folder location override on the server")
        adv_category = QComboBox()
        adv_category.setMaxVisibleItems(20)
        adv_category.setEditable(True)
        adv_category.setToolTip("Assigned qBittorrent category for this rule")
        try:
            cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
            if isinstance(cached_cats, dict):
                adv_category.addItems(sorted(str(k) for k in cached_cats.keys()))
        except Exception:
            pass
        adv_category.setCurrentText(str(rule.get('assignedCategory', '')))
        adv_affected_feeds = QLineEdit(', '.join(rule.get('affectedFeeds', []) or []))
        adv_affected_feeds.setToolTip("Comma-separated list of feed URLs this rule applies to")
        adv_episode = QLineEdit(str(rule.get('episodeFilter', '')))
        adv_episode.setToolTip("Filter to match specific episodes (e.g. 1-12 or empty for all)")
        adv_lastmatch = QTextEdit(str(rule.get('lastMatch', '') or ''))
        adv_lastmatch.setMinimumHeight(60)
        adv_lastmatch.setMaximumHeight(120)
        adv_lastmatch.setToolTip("Show details about the last torrent title matched by this rule")
        adv_lastmatch_status = QLabel('')
        adv_ignore_days = QSpinBox()
        adv_ignore_days.setRange(0, 3650)
        adv_ignore_days.setValue(int(rule.get('ignoreDays', 0) or 0))
        adv_ignore_days.setToolTip("Cooldown period in days to ignore new matching torrents after a successful match")
        adv_add_paused = QComboBox()
        adv_add_paused.setMaxVisibleItems(20)
        adv_add_paused.addItems(['None', 'False', 'True'])
        current_add_paused = rule.get('addPaused', None)
        if current_add_paused is None:
            adv_add_paused.setCurrentText('None')
        elif bool(current_add_paused):
            adv_add_paused.setCurrentText('True')
        else:
            adv_add_paused.setCurrentText('False')
        adv_add_paused.setToolTip("When downloading matched torrents, set download state to paused (True/False/None)")
        adv_smart_filter = QCheckBox('Enable smart filter')
        adv_smart_filter.setChecked(bool(rule.get('smartFilter', False)))
        adv_smart_filter.setToolTip("Enable smart filtering to dynamically recognize and avoid duplicate episode downloads")
        adv_content_layout = QLineEdit(str(rule.get('torrentContentLayout', '') or ''))
        adv_content_layout.setToolTip("Set torrent layout folder organization on server")
        adv_prev_matches = QTextEdit('\n'.join(str(v) for v in (rule.get('previouslyMatchedEpisodes', []) or [])))
        adv_prev_matches.setMinimumHeight(60)
        adv_prev_matches.setMaximumHeight(120)
        adv_prev_matches.setToolTip("List of previously matched episode numbers to prevent downloading duplicates")
        adv_priority = QSpinBox()
        adv_priority.setRange(-99999, 99999)
        adv_priority.setValue(int(rule.get('priority', 0) or 0))
        adv_priority.setToolTip("Rule priority index value (higher priority rules run first)")
        adv_enabled = QCheckBox('Enabled')
        adv_enabled.setChecked(bool(rule.get('enabled', True)))
        adv_enabled.setToolTip("Toggle rule active status on the qBittorrent server")
        adv_regex = QCheckBox('Use Regex')
        adv_regex.setChecked(bool(rule.get('useRegex', False)))
        adv_regex.setToolTip("Interpret mustContain/mustNotContain patterns as regular expressions")

        form.addRow('Rule Title:', adv_title)
        form.addRow('Must Contain:', adv_must)
        form.addRow('Must Not Contain:', adv_must_not)
        form.addRow('Save Path:', adv_save)
        form.addRow('Assigned Category:', adv_category)
        form.addRow('Affected Feeds:', adv_affected_feeds)
        form.addRow('Episode Filter:', adv_episode)
        form.addRow('Last Match:', adv_lastmatch)
        form.addRow('', adv_lastmatch_status)
        form.addRow('Ignore Days:', adv_ignore_days)
        form.addRow('Add Paused:', adv_add_paused)
        form.addRow('Torrent Content Layout:', adv_content_layout)
        form.addRow('Previously Matched Episodes:', adv_prev_matches)
        form.addRow('Priority:', adv_priority)
        form.addRow('', adv_smart_filter)
        form.addRow('', adv_enabled)
        form.addRow('', adv_regex)


        _adv_form_layout.addWidget(QLabel('Torrent Params (JSON):'))
        torrent_params_edit = QTextEdit(_adv_form_widget)
        torrent_params_edit.setMinimumHeight(100)
        try:
            torrent_params_edit.setPlainText(json.dumps(rule.get('torrentParams', {}), indent=2, ensure_ascii=False))
        except Exception:
            torrent_params_edit.setPlainText('{}')
        torrent_params_edit.setToolTip("Raw JSON object containing parameters passed directly to qBittorrent torrent addition API")
        _adv_form_layout.addWidget(torrent_params_edit)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setToolTip("Close editor without saving any changes")
        apply_btn = QPushButton('Apply')
        apply_btn.setToolTip("Validate and save advanced changes to this rule")
        footer.addWidget(cancel_btn)
        footer.addWidget(apply_btn)
        dialog_layout.addLayout(footer)

        def _validate_lastmatch_text(show_dialog: bool = False) -> tuple[bool, object]:
            """Validate lastmatch text helper function."""
            text = adv_lastmatch.toPlainText().strip()
            if not text:
                adv_lastmatch_status.setText('')
                return True, ''
            if not (text.startswith('{') or text.startswith('[') or text.startswith('"')):
                adv_lastmatch_status.setText('Using raw text')
                return True, text
            try:
                parsed = json.loads(text)
                adv_lastmatch_status.setText('Valid JSON')
                return True, parsed
            except Exception as exc:
                msg = f'Invalid JSON: {exc}'
                short = msg if len(msg) <= 120 else msg[:117] + '...'
                adv_lastmatch_status.setText(short)
                if show_dialog:
                    if QMessageBox.question(dialog, 'Validation', f'Last Match JSON is invalid ({exc}). Save as raw text anyway?') == QMessageBox.Yes:
                        return True, text
                    return False, None
                return False, None

        adv_lastmatch.textChanged.connect(lambda: _validate_lastmatch_text(show_dialog=False))
        _validate_lastmatch_text(show_dialog=False)

        def _apply_advanced() -> None:
            """Apply changes for advanced."""
            title_value = adv_title.text().strip()
            if not title_value:
                QMessageBox.warning(dialog, 'Validation', 'Rule Title cannot be empty.')
                return
            try:
                params = json.loads(torrent_params_edit.toPlainText().strip() or '{}')
                if not isinstance(params, dict):
                    raise ValueError('torrentParams must be a JSON object')
            except Exception as exc:
                QMessageBox.warning(dialog, 'Validation', f'Invalid torrentParams JSON: {exc}')
                return

            ok_lastmatch, last_match_value = _validate_lastmatch_text(show_dialog=True)
            if not ok_lastmatch:
                return

            save_path_value = adv_save.text().strip()
            if not save_path_value:
                if QMessageBox.question(dialog, 'Validation', 'Save Path is empty. Continue without a save path?') != QMessageBox.Yes:
                    return
            else:
                try:
                    if len(save_path_value) > 260:
                        if QMessageBox.question(dialog, 'Validation Warning', 'Save Path is unusually long. Continue?') != QMessageBox.Yes:
                            return
                except Exception:
                    pass

            prev_matches = [line.strip() for line in adv_prev_matches.toPlainText().splitlines() if line.strip()]
            add_paused_text = adv_add_paused.currentText().strip()
            if add_paused_text == 'None':
                add_paused_value = None
            else:
                add_paused_value = add_paused_text == 'True'

            _push_undo(item, copy.deepcopy(rule))
            node = dict(rule.get('node') or {})
            node['title'] = title_value
            rule['node'] = node
            rule['ruleName'] = title_value
            rule['mustContain'] = adv_must.text().strip()
            rule['mustNotContain'] = adv_must_not.text().strip()
            rule['savePath'] = save_path_value
            rule['assignedCategory'] = adv_category.currentText().strip()
            rule['affectedFeeds'] = [f.strip() for f in adv_affected_feeds.text().split(',') if f.strip()]
            rule['episodeFilter'] = adv_episode.text().strip()
            rule['lastMatch'] = last_match_value
            rule['ignoreDays'] = int(adv_ignore_days.value())
            rule['addPaused'] = add_paused_value
            rule['smartFilter'] = bool(adv_smart_filter.isChecked())
            rule['torrentContentLayout'] = adv_content_layout.text().strip() or None
            rule['previouslyMatchedEpisodes'] = prev_matches
            rule['priority'] = int(adv_priority.value())
            rule['enabled'] = bool(adv_enabled.isChecked())
            rule['useRegex'] = bool(adv_regex.isChecked())
            rule['torrentParams'] = params
            rule['torrentParams']['category'] = str(rule.get('assignedCategory', '') or '')
            rule['torrentParams']['save_path'] = str(rule.get('savePath', '') or '')
            library_tree.blockSignals(True)
            try:
                item.setData(0, core.Qt.UserRole, rule)
                item.setCheckState(0, core.Qt.Checked if bool(rule.get('enabled', False)) else core.Qt.Unchecked)
                item.setText(2, title_value)
                item.setText(3, str(rule.get('assignedCategory', '')))
                item.setText(4, str(rule.get('savePath', '')))
            finally:
                library_tree.blockSignals(False)
            _populate_editor_from_selection()
            auto_save_rules()
            _set_status('Advanced rule settings applied.', 4000)
            dialog.accept()

        cancel_btn.clicked.connect(dialog.reject)
        apply_btn.clicked.connect(_apply_advanced)
        dialog.exec()

    def _on_selection_changed() -> None:
        """Handle the selection changed event."""
        last_item = last_selected_item_ref[0]
        if last_item is not None:
            try:
                if last_item.treeWidget() is not None:
                    _save_rule_to_item(last_item)
            except Exception as e:
                logger.debug(f"Failed to auto-save previous item: {e}")
        
        selected = library_tree.selectedItems()
        last_selected_item_ref[0] = selected[0] if selected else None
        _populate_editor_from_selection()

    def _populate_editor_from_selection() -> None:
        """
        Populate the right-side Rule Editor pane based on Tree Selection.
        
        When the user clicks a rule in the library tree, this function:
        1. Blocks UI signals (to prevent infinite loops from text change events).
        2. Pulls the rule dictionary data from the config.
        3. Fills all text boxes, checkboxes, and spinboxes in the Advanced Editor tab.
        4. Triggers `_action_refresh_anilist` silently to populate the variations UI.
        5. Unblocks signals so subsequent user edits will auto-save.
        """
        selected = library_tree.selectedItems()
        
        # Block signals on widgets to prevent triggering change callbacks during selection update
        enabled_box.blockSignals(True)
        title_edit.blockSignals(True)
        must_edit.blockSignals(True)
        save_path_edit.blockSignals(True)
        category_combo.blockSignals(True)
        affected_feeds_edit.blockSignals(True)
        
        try:
            if not selected:
                title_edit.clear()
                must_edit.clear()
                save_path_edit.clear()
                category_combo.setCurrentText('')
                affected_feeds_edit.clear()
                enabled_box.setChecked(False)
                enabled_box.setEnabled(False)
                _update_title_variations_ui()
                return
            rule = selected[0].data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                return
            title_edit.setText(str(rule.get('node', {}).get('title') or rule.get('ruleName', '')))
            must_edit.setText(str(rule.get('mustContain', '')))
            save_path_edit.setText(str(rule.get('savePath', '')))
            category_combo.setCurrentText(str(rule.get('assignedCategory', '')))
            affected_feeds_edit.setText(', '.join(rule.get('affectedFeeds', []) or []))
            enabled_box.setEnabled(True)
            enabled_box.setChecked(bool(rule.get('enabled', False)))
            _update_title_variations_ui()
        finally:
            enabled_box.blockSignals(False)
            title_edit.blockSignals(False)
            must_edit.blockSignals(False)
            save_path_edit.blockSignals(False)
            category_combo.blockSignals(False)
            affected_feeds_edit.blockSignals(False)

    def _apply_filter() -> None:
        """Apply changes for filter."""
        needle = search_entry.text().strip().lower()
        field = filter_combo.currentText()
        for i in range(library_tree.topLevelItemCount()):
            item = library_tree.topLevelItem(i)
            if not needle:
                item.setHidden(False)
                continue
            if field == 'Title':
                hay = item.text(2).lower()
            elif field == 'Category':
                hay = item.text(3).lower()
            else:
                hay = item.text(4).lower()
            item.setHidden(needle not in hay)

    def _on_tree_context_menu(pos) -> None:
        """Handle the tree context menu event."""
        item = library_tree.itemAt(pos)
        if item is None:
            return
        try:
            if not item.isSelected():
                library_tree.clearSelection()
                item.setSelected(True)
                library_tree.setCurrentItem(item)
        except Exception:
            pass
        menu = QMenu(library_tree)
        _add_menu_action(menu, 'Toggle Enable/Disable', lambda: _action_toggle_selected())
        _add_menu_action(menu, 'Edit', lambda: _open_advanced_editor())
        
        # Batch Downloader context action
        rule = item.data(0, core.Qt.UserRole)
        show_name = get_display_title(rule, rule.get('ruleName', '')) if isinstance(rule, dict) else None
        _add_menu_action(menu, 'Batch Download...', lambda: _open_batch_downloader(show_name))

        _add_menu_action(menu, 'Bulk Edit Selected...', lambda: _action_bulk_toggle())
        _add_menu_action(menu, 'Batch Edit Title...', lambda: _action_batch_review_variations())
        _add_menu_action(menu, 'Batch Apply SubsPlease Matches...', lambda: _action_batch_apply_subsplease())
        menu.addSeparator()
        _add_menu_action(menu, 'Export Selected Titles...', lambda: _action_export_selected())
        _add_menu_action(menu, 'Delete', lambda: _action_delete_selected())
        menu.exec(library_tree.mapToGlobal(pos))

    def _on_tree_space() -> None:
        """Handle the tree space event."""
        if _selected_items():
            _action_toggle_selected()

    def _on_tree_delete() -> None:
        """Handle the tree delete event."""
        if _selected_items():
            _action_delete_selected()

    def _on_tree_enter() -> None:
        """Handle the tree enter event."""
        if _selected_items():
            _open_advanced_editor()

    def _on_search_escape() -> None:
        """Handle the search escape event."""
        if search_entry.text().strip():
            search_entry.clear()
        else:
            library_tree.setFocus()

    clear_btn.clicked.connect(search_entry.clear)
    search_entry.textChanged.connect(_apply_filter)
    filter_combo.currentTextChanged.connect(lambda _=None: _apply_filter())
    library_tree.itemSelectionChanged.connect(_on_selection_changed)
    library_tree.itemChanged.connect(_on_item_changed)
    library_tree.itemDoubleClicked.connect(lambda _item=None, _col=0: _on_tree_enter())
    library_tree.setContextMenuPolicy(core.Qt.CustomContextMenu)
    library_tree.customContextMenuRequested.connect(_on_tree_context_menu)
    tree_shortcuts: list[object] = []
    tree_shortcuts.append(QShortcut(QKeySequence('Delete'), library_tree, activated=_on_tree_delete))
    tree_shortcuts.append(QShortcut(QKeySequence('Return'), library_tree, activated=_on_tree_enter))
    tree_shortcuts.append(QShortcut(QKeySequence('Enter'), library_tree, activated=_on_tree_enter))
    tree_shortcuts.append(QShortcut(QKeySequence('Ctrl+F'), library_tree, activated=lambda: search_entry.setFocus()))
    tree_shortcuts.append(QShortcut(QKeySequence('Escape'), search_entry, activated=_on_search_escape))

    def _tree_key_press_event(event):
        """Tree key press event helper function."""
        if event.key() == core.Qt.Key_Space:
            _on_tree_space()
            event.accept()
            return
        library_tree._original_key_press_event(event)

    library_tree._original_key_press_event = library_tree.keyPressEvent
    library_tree.keyPressEvent = _tree_key_press_event

    undo_btn.clicked.connect(_action_undo)
    enabled_box.toggled.connect(lambda _: _save_current_rule_from_editor())
    clear_all_bar_btn.clicked.connect(lambda: _action_clear_all_titles())
    validate_bar_btn.clicked.connect(lambda: _action_validate_all())
    trash_bar_btn.clicked.connect(lambda: _action_view_trash())
    title_edit.editingFinished.connect(_save_current_rule_from_editor)
    must_edit.editingFinished.connect(_save_current_rule_from_editor)
    save_path_edit.editingFinished.connect(_save_current_rule_from_editor)
    category_combo.lineEdit().editingFinished.connect(_save_current_rule_from_editor)
    affected_feeds_edit.editingFinished.connect(_save_current_rule_from_editor)

    # Auto-save immediately on user text typing or category dropdown selection
    title_edit.textEdited.connect(lambda _: _save_current_rule_from_editor())
    must_edit.textEdited.connect(lambda _: _save_current_rule_from_editor())
    save_path_edit.textEdited.connect(lambda _: _save_current_rule_from_editor())
    category_combo.currentTextChanged.connect(lambda _: _save_current_rule_from_editor())
    affected_feeds_edit.textEdited.connect(lambda _: _save_current_rule_from_editor())

    title_edit.textChanged.connect(lambda _=None: _update_title_variations_ui())
    must_edit.textChanged.connect(lambda _=None: _update_title_variations_ui())
    save_path_edit.textChanged.connect(lambda _=None: _update_title_variations_ui())

    def _add_prefix_to_selected() -> None:
        """Add prefix to selected helper function."""
        selected = _selected_items()
        if not selected:
            return
        current = title_edit.text().strip()
        if not current:
            return
        prefix = f"{season_combo.currentText()} {year_combo.currentText()} - "
        if current.startswith(prefix):
            return
        title_edit.setText(prefix + current)
        _save_current_rule_from_editor()

    prefix_btn.clicked.connect(_add_prefix_to_selected)

    def _action_refresh_subsplease() -> None:
        """Handle the refresh subsplease UI action."""
        refresh_btn.setEnabled(False)
        _set_status('Refreshing SubsPlease cache (in background)...')

        worker = SubsPleaseRefreshWorker()

        def _on_subsplease_finished(result, w=worker):
            """Handle the subsplease finished event."""
            refresh_btn.setEnabled(True)
            if w in active_workers:
                active_workers.remove(w)
            _set_status(str(result.get('fetch_status', '') or 'SubsPlease refresh completed.'), 4000)
            QMessageBox.information(window, 'Refresh', format_refresh_result_text('SubsPlease', result))

        active_workers.append(worker)
        worker.finished.connect(_on_subsplease_finished)
        worker.start()

    def _action_refresh_anilist() -> None:
        """Handle the refresh anilist UI action."""
        refresh_btn.setEnabled(False)
        _set_status('Refreshing AniList cache (in background)...')

        worker = AniListRefreshWorker(
            current_title=title_edit.text(),
            current_must=must_edit.text(),
            selected_season=season_combo.currentText(),
            selected_year=year_combo.currentText(),
            refresh_scope_override=AniListRefreshScope.TITLE_ONLY
        )

        def _on_anilist_finished(result, w=worker):
            """Handle the anilist finished event."""
            refresh_btn.setEnabled(True)
            if w in active_workers:
                active_workers.remove(w)
            _set_status(str(result.get('fetch_status', '') or 'AniList refresh completed.'), 4000)
            _update_title_variations_ui()
            QMessageBox.information(window, 'Refresh', format_refresh_result_text('AniList', result))

        active_workers.append(worker)
        worker.finished.connect(_on_anilist_finished)
        worker.start()

    advanced_btn.clicked.connect(_open_advanced_editor)
    refresh_subs_action.triggered.connect(_action_refresh_subsplease)
    refresh_ani_action.triggered.connect(_action_refresh_anilist)

    def _action_sync_fetch_existing() -> None:
        """Handle the sync fetch existing UI action."""
        fetch_rules_btn.setEnabled(False)
        _set_status('Fetching existing rules from qBittorrent...')
        
        worker = FetchRulesWorker()

        def _on_fetch_finished(snapshot, w=worker):
            """Handle the fetch finished event."""
            fetch_rules_btn.setEnabled(True)
            if w in active_workers:
                active_workers.remove(w)

            rules = snapshot.get('rules', {}) if isinstance(snapshot, dict) else {}
            if not isinstance(rules, dict):
                rules = {}

            # Save server snapshot copy locally for diff check
            import copy
            config.SERVER_RULES_SNAPSHOT = copy.deepcopy(rules)

            # Cache retrieved categories and feeds
            categories = snapshot.get('categories', {}) if isinstance(snapshot, dict) else {}
            feeds = snapshot.get('feeds', {}) if isinstance(snapshot, dict) else {}
            if isinstance(categories, dict) and categories:
                config.save_cached_categories(categories)
            if isinstance(feeds, dict) and feeds:
                config.save_cached_feeds(feeds)

            # Re-populate category dropdowns with updated categories
            try:
                cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
                if isinstance(cached_cats, dict):
                    current_cat = category_combo.currentText()
                    category_combo.clear()
                    category_combo.addItems(sorted(str(k) for k in cached_cats.keys()))
                    category_combo.setCurrentText(current_cat)
            except Exception:
                pass

            rules_err = snapshot.get('rules_error', '') if isinstance(snapshot, dict) else ''
            if not snapshot.get('success', False) and rules_err:
                _set_status(f'Fetch failed: {rules_err}', 5000)
                QMessageBox.warning(window, 'Fetch Rules', f'Failed to fetch rules from qBittorrent:\n\n{rules_err}')
                return

            if not rules:
                _set_status('Fetch complete: no existing rules available to add.', 5000)
                QMessageBox.information(window, 'Fetch Rules', 'No existing rules available to add.')
                return

            entries: list[dict[str, object]] = []
            for name, data in rules.items():
                if isinstance(data, dict):
                    title = str(data.get('ruleName') or data.get('name') or name)
                    rule_entry = dict(data)
                    if not isinstance(rule_entry.get('node'), dict):
                        rule_entry['node'] = {'title': title}
                    if not rule_entry.get('ruleName'):
                        rule_entry['ruleName'] = title
                    entries.append(rule_entry)
                else:
                    title = str(name)
                    entries.append({'node': {'title': title}, 'ruleName': title})

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
                _refresh_library_tree()
                if removed_count > 0:
                    msg = f'Added {new_count} existing rule(s) and removed {removed_count} duplicate local row(s).'
                else:
                    msg = f'Added {new_count} existing rule(s).'
            else:
                msg = 'No new rules were added; existing titles were already up to date.'

            _set_status(f'Fetch complete: {msg}', 6000)
            QMessageBox.information(window, 'Fetch Rules', msg)

        worker.finished.connect(_on_fetch_finished)
        active_workers.append(worker)
        worker.start()

    def _action_apply_rules() -> None:
        """
        Action Handler: Sync Local Rules to qBittorrent.
        
        This is the most critical function in the app. It acts as the bridge
        between the local UI state and the qBittorrent server.
        
        Flow:
        1. Validates the local library state against the cached server snapshot.
        2. Computes a sync plan (dry-run mode).
        3. Displays the plan in a popup dialog to the user for confirmation.
        4. If approved, dispatches `ApplyRulesWorker` to physically sync the
           data via the qBittorrent API on a background thread.
        """
        _set_status('Preparing apply dry run...')
        
        server_rules = getattr(config, 'SERVER_RULES_SNAPSHOT', None)
        if not isinstance(server_rules, dict) or not server_rules:
            reply = QMessageBox.question(
                window,
                'Server Sync Warning',
                'No server rule snapshot is loaded.\n\n'
                'Please click "Fetch Rules" first if you want to compare and synchronize with the current server rules.\n\n'
                'Do you want to proceed anyway? (This will treat all rules as new on the server)',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _set_status('Apply cancelled. Fetch rules first.', 3000)
                return
            server_rules = {}

        rule_rows = _collect_rule_rows()
        # Always synchronize all rules in the library list
        selected_names = [str(row.get('rule_name', '') or '').strip() for row in rule_rows if str(row.get('rule_name', '') or '').strip()]
        
        dry_run = run_qt_rule_sync_dry_run(rule_rows, selected_names, server_rules)
        summary_text = format_rule_sync_dry_run_text(dry_run)
        if int(dry_run.get('selected_count', 0) or 0) == 0:
            _set_status('Apply skipped: no rules selected.', 4000)
            QMessageBox.information(window, 'Apply Rules', 'No rules are selected and no rule rows are available to apply.')
            return
        if QMessageBox.question(window, 'Apply Rules Preview', summary_text + '\n\nApply these changes to qBittorrent?') != QMessageBox.Yes:
            _set_status('Apply cancelled by user.', 3000)
            return
        _set_status('Applying changes to qBittorrent...')
        apply_rules_btn.setEnabled(False)
        worker = ApplyRulesWorker(dry_run.get('changes', []) if isinstance(dry_run, dict) else [])

        def _on_apply_finished(apply_result, w=worker):
            """Handle the apply finished event."""
            apply_rules_btn.setEnabled(True)
            if w in active_workers:
                active_workers.remove(w)
            
            if apply_result.get('success', False):
                # Update local SERVER_RULES_SNAPSHOT
                s_rules = getattr(config, 'SERVER_RULES_SNAPSHOT', None)
                if isinstance(s_rules, dict):
                    import copy
                    for change in dry_run.get('changes', []):
                        rule_name = change.get('rule_name')
                        rule_def = change.get('rule_def')
                        if rule_name and isinstance(rule_def, dict):
                            s_rules[rule_name] = copy.deepcopy(rule_def)
            
            _set_status(
                f"Apply result: applied {apply_result.get('applied_count', 0)}, failed {apply_result.get('failed_count', 0)}.",
                6000,
            )
            QMessageBox.information(
                window,
                'Apply Rules Result',
                f"Applied: {apply_result.get('applied_count', 0)}\n"
                f"Failed: {apply_result.get('failed_count', 0)}\n"
                f"{apply_result.get('rollback_guidance', '')}"
            )

        worker.finished.connect(_on_apply_finished)
        active_workers.append(worker)
        worker.start()

    fetch_rules_btn.clicked.connect(_action_sync_fetch_existing)
    apply_rules_btn.clicked.connect(_action_apply_rules)

    def _window_drag_enter_event(event) -> None:
        """Window drag enter event helper function."""
        try:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:
            event.ignore()

    def _window_drop_event(event) -> None:
        """Window drop event helper function."""
        try:
            _set_status('Processing dropped import files...')
            urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
            paths: list[str] = []
            for url in urls:
                try:
                    local = url.toLocalFile()
                except Exception:
                    local = ''
                if local:
                    paths.append(local)
            if not paths:
                _set_status('Drop ignored: no valid files.', 3000)
                event.ignore()
                return
            result = run_qt_import_dropped_paths(
                paths,
                season=season_combo.currentText(),
                year=year_combo.currentText(),
                prefix_imports=bool(config.get_pref('prefix_imports', True)),
            )
            if int(result.get('imported_count', 0) or 0) > 0:
                _refresh_library_tree()
                _set_status(str(result.get('message', 'Drop import completed.')), 5000)
                event.acceptProposedAction()
            else:
                _set_status(str(result.get('message', 'Drop import did not import any files.')), 5000)
                event.ignore()
            details = result.get('details', []) if isinstance(result, dict) else []
            details_text = '\n'.join([str(d) for d in details[:8]]) if isinstance(details, list) else ''
            text = str(result.get('message', 'Drop import finished.')) if isinstance(result, dict) else 'Drop import finished.'
            if details_text:
                text += '\n\n' + details_text
            QMessageBox.information(window, 'Import', text)
        except Exception:
            _set_status('Drop import failed.', 5000)
            event.ignore()

    window.setAcceptDrops(True)
    window.dragEnterEvent = _window_drag_enter_event
    window.dropEvent = _window_drop_event

    # Restore splitter sizes from prefs; fall back to proportional defaults
    _saved_split = config.get_pref('qt_splitter_sizes', None)
    if isinstance(_saved_split, list) and len(_saved_split) == 2 and all(isinstance(x, int) and x > 0 for x in _saved_split):
        splitter.setSizes(_saved_split)
    else:
        splitter.setSizes([760, 380])
    splitter.setChildrenCollapsible(False)
    content_layout.addWidget(splitter, 1)
    layout.addWidget(content_group, 1)

    window.setCentralWidget(central)

    status = QStatusBar(window)
    status_bar_ref['bar'] = status
    window.setStatusBar(status)
    status.addPermanentWidget(connection_chip)
    status.addPermanentWidget(titles_chip)
    _set_status('Connected: ' + get_connection_status_text(config))

    # Connect to color scheme changes (Qt 6.5+)
    try:
        style_hints = app.styleHints()
        if hasattr(style_hints, 'colorSchemeChanged'):
            def _on_color_scheme_changed(scheme):
                """Handle the color scheme changed event."""
                if config.get_pref('theme', 'light').lower() == 'auto':
                    apply_app_theme('auto')
            window._color_scheme_handler = _on_color_scheme_changed
            style_hints.colorSchemeChanged.connect(window._color_scheme_handler)
    except Exception:
        pass

    # Listen to ApplicationActivate event to refresh theme on focus gain
    try:
        original_event = window.event
        def _custom_event(event):
            """Custom event helper function."""
            if event.type() == core.QEvent.ApplicationActivate:
                if config.get_pref('theme', 'light').lower() == 'auto':
                    apply_app_theme('auto')
            return original_event(event)
        window.event = _custom_event
    except Exception:
        pass

    # Periodic timer check (every 2 seconds) fallback for auto theme
    try:
        QTimer = getattr(core, 'QTimer')
        theme_timer = QTimer(window)
        def _check_theme_timer():
            """Check theme timer helper function."""
            if config.get_pref('theme', 'light').lower() == 'auto':
                current_effective = getattr(window, '_effective_theme', '')
                new_effective = get_host_machine_theme()
                if new_effective != current_effective:
                    apply_app_theme('auto')
        theme_timer.timeout.connect(_check_theme_timer)
        theme_timer.start(2000)
        window._theme_timer = theme_timer
    except Exception:
        pass

    window.show()
    app.exec()
