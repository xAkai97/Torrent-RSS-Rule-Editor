"""PySide6 GUI with clean tabbed interface matching Tkinter design principles.

This module provides a professional PySide6 shell that mirrors the Tkinter
visual hierarchy and layout structure using modern Qt conventions.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import os
import sys

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
from src.constants import AniListCacheRetentionMode, AniListRefreshScope, FileSystem, PrefKeys
from src.config import config
from src.gui.app_state import AppState
from src.services.connection_status import get_connection_status_text
from src.gui.file_operations import _import_titles_core, _snapshot_import_entries, collect_invalid_folder_titles, import_titles_from_text
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
from src.utils import get_display_title, get_rule_name
from src.utils import validate_folder_name_by_filesystem

logger = logging.getLogger(__name__)


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


def run_qt_get_runtime_settings() -> dict[str, object]:
    """Return current runtime/UI preferences for Qt settings controls."""
    theme = str(config.get_pref('theme', 'light') or 'light').strip().lower()
    if theme not in {'light', 'dark'}:
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
    if theme not in {'light', 'dark'}:
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
    supported = list(getattr(config, 'SUPPORTED_SERVERS', ['qbittorrent', 'autobrr']) or [])
    supported = [str(v).strip().lower() for v in supported if str(v).strip()]
    if not supported:
        supported = ['qbittorrent', 'autobrr']
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
    supported = list(getattr(config, 'SUPPORTED_SERVERS', ['qbittorrent', 'autobrr']) or [])
    supported = [str(v).strip().lower() for v in supported if str(v).strip()]
    if not supported:
        supported = ['qbittorrent', 'autobrr']
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


def run_qt_load_log_tail(log_file_path: str = 'qbt_editor.log', max_lines: int = 300) -> dict[str, object]:
    """Load latest log lines for Qt log viewer panel."""
    path = str(log_file_path or 'qbt_editor.log').strip() or 'qbt_editor.log'
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


def run_qt_clear_log_file(log_file_path: str = 'qbt_editor.log') -> dict[str, object]:
    """Truncate application log file used by log viewer actions."""
    path = str(log_file_path or 'qbt_editor.log').strip() or 'qbt_editor.log'
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


def run_qt_clear_all_titles() -> dict[str, object]:
    """Clear all locally loaded titles in config state."""
    all_titles = getattr(config, 'ALL_TITLES', None) or {}
    existing_count = sum(len(v) for v in all_titles.values() if isinstance(v, list)) if isinstance(all_titles, dict) else 0
    config.ALL_TITLES = {}
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
    return commit_rule_enabled_drafts_to_local_titles(rule_rows)


def run_qt_rule_sync_dry_run(rule_rows: list[dict[str, str]], selected_rule_names: list[str]) -> dict[str, object]:
    """Build phase 4 dry-run summary for selected draft rows."""
    return build_rule_sync_dry_run(rule_rows=rule_rows, selected_rule_names=selected_rule_names)


def run_qt_apply_rule_sync(changes: list[dict[str, object]]) -> dict[str, object]:
    """Apply confirmed sync plan to qBittorrent."""
    return apply_rule_sync_plan(changes)


def setup_gui_qt() -> None:
    """Start a PySide6 main window shaped to match Tk app structure."""
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
        QAbstractItemView = getattr(widgets, 'QAbstractItemView')
        QTextEdit = getattr(widgets, 'QTextEdit')
        QListWidget = getattr(widgets, 'QListWidget')
        QLineEdit = getattr(widgets, 'QLineEdit')
        QComboBox = getattr(widgets, 'QComboBox')
        QMessageBox = getattr(widgets, 'QMessageBox')
        QDialog = getattr(widgets, 'QDialog')
        QFileDialog = getattr(widgets, 'QFileDialog')
        QInputDialog = getattr(widgets, 'QInputDialog')
        QStackedWidget = getattr(widgets, 'QStackedWidget')
        QShortcut = getattr(gui, 'QShortcut')
        QKeySequence = getattr(gui, 'QKeySequence')
    except Exception as exc:
        raise ImportError(
            'PySide6 is required for Qt preview mode. Install dependencies from requirements.txt.'
        ) from exc

    app = QApplication.instance() or QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle('Torrent RSS Rules Editor')
    window.resize(1420, 820)
    
    try:
        geometry = config.get_pref('qt_window_geometry', None)
        if geometry and isinstance(geometry, list) and len(geometry) == 4:
            window.setGeometry(int(geometry[0]), int(geometry[1]), int(geometry[2]), int(geometry[3]))
    except Exception:
        pass
        
    def _on_close_event(event) -> None:
        try:
            rect = window.geometry()
            config.set_pref('qt_window_geometry', [rect.x(), rect.y(), rect.width(), rect.height()])
        except Exception:
            pass
        event.accept()

    window.closeEvent = _on_close_event

    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'
    is_dark_mode = theme_pref == 'dark'

    if is_dark_mode:
        bg_color = '#0f172a'
        text_color = '#f8fafc'
        border_color = '#334155'
        button_bg = '#334155'
        button_hover = '#475569'
        button_press = '#1e293b'
        group_border = '#475569'
        chip_bg = '#1e293b'
    else:
        bg_color = '#f1f5f9'
        text_color = '#0f172a'
        border_color = '#cbd5e1'
        button_bg = '#e2e8f0'
        button_hover = '#cbd5e1'
        button_press = '#94a3b8'
        group_border = '#94a3b8'
        chip_bg = '#ffffff'

    stylesheet = f"""
        QMainWindow, QWidget, QDialog {{
            background-color: {bg_color};
            color: {text_color};
        }}
        QMenuBar {{
            background-color: {bg_color};
            color: {text_color};
            border-bottom: 1px solid {border_color};
        }}
        QMenuBar::item:selected {{
            background-color: {button_hover};
        }}
        QMenu {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
        }}
        QMenu::item:selected {{
            background-color: {button_hover};
        }}
        QGroupBox {{
            color: {text_color};
            border: 1px solid {group_border};
            border-radius: 3px;
            margin-top: 8px;
            padding-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 3px;
            font-size: 12px;
        }}
        QPushButton {{
            background-color: {button_bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 2px;
            padding: 5px 10px;
        }}
        QPushButton:hover {{
            background-color: {button_hover};
        }}
        QPushButton:pressed {{
            background-color: {button_press};
        }}
        QLineEdit, QComboBox, QTreeWidget {{
            border: 1px solid {border_color};
            border-radius: 1px;
            padding: 3px;
        }}
        QStatusBar {{
            border-top: 1px solid {border_color};
        }}
        QSplitter::handle {{
            background-color: {border_color};
        }}
    """

    app.setStyle('Fusion')
    app.setStyleSheet(stylesheet)

    central = QWidget(window)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)

    def _add_menu_action(menu, label, callback, shortcut: str = ''):
        action = menu.addAction(label)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        return action

    qt_log_viewer_ref = {'dialog': None}

    def _open_qt_log_viewer() -> None:
        existing = qt_log_viewer_ref.get('dialog')
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
        except Exception:
            pass

        dialog = QDialog(window)
        dialog.setWindowTitle('Application Log Viewer')
        dialog.resize(980, 620)
        qt_log_viewer_ref['dialog'] = dialog
        dialog_layout = QVBoxLayout(dialog)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('Filter:'))
        filter_combo = QComboBox(dialog)
        filter_combo.addItems(['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'])
        toolbar.addWidget(filter_combo)
        refresh_btn = QPushButton('Refresh')
        clear_btn = QPushButton('Clear Log')
        open_btn = QPushButton('Open File')
        close_btn = QPushButton('Close')
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(open_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(close_btn)
        dialog_layout.addLayout(toolbar)

        log_view = QTextEdit(dialog)
        log_view.setReadOnly(True)
        log_view.setLineWrapMode(QTextEdit.NoWrap)
        dialog_layout.addWidget(log_view, 1)

        status_label = QLabel('')
        dialog_layout.addWidget(status_label)

        def _load_log() -> None:
            result = run_qt_load_log_tail(max_lines=1000)
            content = str(result.get('content', '') or '')
            level = filter_combo.currentText()
            if level != 'ALL':
                filtered = []
                for line in content.splitlines():
                    if f' - {level} - ' in line:
                        filtered.append(line)
                content = '\n'.join(filtered)
            log_view.setPlainText(content or 'No log entries for current filter.')
            status_label.setText(str(result.get('message', 'Ready')))
            # Keep view pinned to bottom without relying on QTextCursor enum access.
            scrollbar = log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _clear_log() -> None:
            if QMessageBox.question(dialog, 'Clear Log', 'Clear qbt_editor.log?') != QMessageBox.Yes:
                return
            result = run_qt_clear_log_file()
            QMessageBox.information(dialog, 'Logs', str(result.get('message', 'Done')))
            _load_log()

        def _open_log_file() -> None:
            path = os.path.abspath('qbt_editor.log')
            if not os.path.exists(path):
                QMessageBox.information(dialog, 'Logs', f'Log file not found: {path}')
                return
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    QMessageBox.information(dialog, 'Logs', f'Open this file manually:\n{path}')
            except Exception as exc:
                QMessageBox.warning(dialog, 'Logs', f'Failed opening log file: {exc}')

        refresh_btn.clicked.connect(_load_log)
        filter_combo.currentTextChanged.connect(lambda _=None: _load_log())
        clear_btn.clicked.connect(_clear_log)
        open_btn.clicked.connect(_open_log_file)
        close_btn.clicked.connect(dialog.accept)
        _load_log()
        dialog.exec()

        try:
            qt_log_viewer_ref['dialog'] = None
        except Exception:
            pass

    def _open_setup_wizard_dialog() -> None:
        """Launch a modern first-run style wizard for core app setup."""
        conn_settings = run_qt_get_connection_settings()
        platform_settings = run_qt_get_platform_settings()
        runtime = run_qt_get_runtime_settings()

        wizard = QDialog(window)
        wizard.setWindowTitle('Setup Wizard')
        wizard.resize(760, 560)
        wizard_layout = QVBoxLayout(wizard)

        title_label = QLabel('Setup Wizard')
        title_label.setStyleSheet('font-weight: 600; font-size: 18px;')
        subtitle_label = QLabel('Configure connection, platform targets, and defaults in three quick steps.')
        subtitle_label.setWordWrap(True)
        wizard_layout.addWidget(title_label)
        wizard_layout.addWidget(subtitle_label)

        stack = QStackedWidget(wizard)
        wizard_layout.addWidget(stack, 1)

        # Step 1: Welcome and UI basics
        step1 = QWidget()
        step1_layout = QVBoxLayout(step1)
        step1_layout.addWidget(QLabel('Step 1 of 3 - Basics'))
        intro = QLabel(
            'This wizard sets up the essential defaults for a modern Qt workflow. '
            'You can fine-tune everything later in Settings.'
        )
        intro.setWordWrap(True)
        step1_layout.addWidget(intro)
        step1_group = QGroupBox('Quick UI Defaults')
        step1_form = QFormLayout(step1_group)
        theme_combo = QComboBox()
        theme_combo.addItems(['light', 'dark'])
        theme_combo.setCurrentText(str(runtime.get('theme', 'light')))
        log_level_combo = QComboBox()
        log_level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
        log_level_combo.setCurrentText(str(runtime.get('log_level', 'INFO')))
        step1_form.addRow('Theme:', theme_combo)
        step1_form.addRow('Log level:', log_level_combo)
        step1_layout.addWidget(step1_group)
        step1_layout.addStretch()
        stack.addWidget(step1)

        # Step 2: qBittorrent connection
        step2 = QWidget()
        step2_layout = QVBoxLayout(step2)
        step2_layout.addWidget(QLabel('Step 2 of 3 - qBittorrent Connection'))
        step2_group = QGroupBox('Connection Profile')
        step2_form = QFormLayout(step2_group)
        protocol_combo = QComboBox()
        protocol_combo.addItems(['http', 'https'])
        protocol_combo.setCurrentText(str(conn_settings.get('protocol', 'http')))
        host_edit = QLineEdit(str(conn_settings.get('host', '')))
        port_edit = QLineEdit(str(conn_settings.get('port', '8080')))
        user_edit = QLineEdit(str(conn_settings.get('username', '')))
        pass_edit = QLineEdit(str(conn_settings.get('password', '')))
        verify_ssl_box = QCheckBox('Verify SSL Certificate')
        verify_ssl_box.setChecked(bool(conn_settings.get('verify_ssl', True)))
        online_radio = QRadioButton('Online mode')
        offline_radio = QRadioButton('Offline mode')
        online_radio.setChecked(str(conn_settings.get('mode', 'online')) == 'online')
        offline_radio.setChecked(not online_radio.isChecked())
        mode_row = QHBoxLayout()
        mode_row.addWidget(online_radio)
        mode_row.addWidget(offline_radio)
        mode_row.addStretch(1)
        test_conn_btn = QPushButton('Test Connection')
        step2_form.addRow('Protocol:', protocol_combo)
        step2_form.addRow('Host:', host_edit)
        step2_form.addRow('Port:', port_edit)
        step2_form.addRow('Username:', user_edit)
        step2_form.addRow('Password:', pass_edit)
        step2_form.addRow('', verify_ssl_box)
        step2_form.addRow('Mode:', mode_row)
        step2_form.addRow('', test_conn_btn)
        step2_layout.addWidget(step2_group)
        step2_status = QLabel('')
        step2_status.setWordWrap(True)
        step2_layout.addWidget(step2_status)
        step2_layout.addStretch()
        stack.addWidget(step2)

        # Step 3: Platform and export defaults
        step3 = QWidget()
        step3_layout = QVBoxLayout(step3)
        step3_layout.addWidget(QLabel('Step 3 of 3 - Platform and Export'))
        step3_group = QGroupBox('Platform Defaults')
        step3_form = QFormLayout(step3_group)
        main_server_combo = QComboBox()
        supported_servers = platform_settings.get('supported_servers', ['qbittorrent', 'autobrr'])
        for server_name in supported_servers if isinstance(supported_servers, list) else ['qbittorrent', 'autobrr']:
            main_server_combo.addItem(str(server_name))
        main_server_combo.setCurrentText(str(platform_settings.get('main_server', 'qbittorrent')))
        export_targets = set(platform_settings.get('export_targets', ['qbittorrent']) or ['qbittorrent'])
        target_qbt = QCheckBox('qBittorrent')
        target_autobrr = QCheckBox('Autobrr')
        target_qbt.setChecked('qbittorrent' in export_targets)
        target_autobrr.setChecked('autobrr' in export_targets)
        targets_row = QVBoxLayout()
        targets_row.addWidget(target_qbt)
        targets_row.addWidget(target_autobrr)
        defaults_save_path = QLineEdit(str(getattr(config, 'DEFAULT_SAVE_PATH', '') or ''))
        defaults_download_path = QLineEdit(str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or ''))
        defaults_category = QLineEdit(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
        step3_form.addRow('Main server:', main_server_combo)
        step3_form.addRow('Export targets:', targets_row)
        step3_form.addRow('Default save path:', defaults_save_path)
        step3_form.addRow('Default download path:', defaults_download_path)
        step3_form.addRow('Default category:', defaults_category)
        step3_layout.addWidget(step3_group)
        finish_note = QLabel('Click Finish to apply and persist these settings.')
        finish_note.setWordWrap(True)
        step3_layout.addWidget(finish_note)
        step3_layout.addStretch()
        stack.addWidget(step3)

        # Wizard footer controls
        footer = QHBoxLayout()
        step_indicator = QLabel('Step 1 of 3')
        footer.addWidget(step_indicator)
        footer.addStretch(1)
        back_btn = QPushButton('Back')
        next_btn = QPushButton('Next')
        finish_btn = QPushButton('Finish')
        cancel_btn = QPushButton('Cancel')
        footer.addWidget(back_btn)
        footer.addWidget(next_btn)
        footer.addWidget(finish_btn)
        footer.addWidget(cancel_btn)
        wizard_layout.addLayout(footer)

        def _update_nav() -> None:
            index = int(stack.currentIndex())
            total = int(stack.count())
            step_indicator.setText(f'Step {index + 1} of {total}')
            back_btn.setEnabled(index > 0)
            next_btn.setEnabled(index < total - 1)
            finish_btn.setEnabled(index == total - 1)

        def _test_connection() -> None:
            protocol = protocol_combo.currentText().strip() or 'http'
            host = host_edit.text().strip()
            port = port_edit.text().strip() or '8080'
            username = user_edit.text().strip()
            password = pass_edit.text()
            verify_ssl = bool(verify_ssl_box.isChecked())
            if not host:
                QMessageBox.warning(wizard, 'Connection Test', 'Host is required for connection test.')
                return
            ok, message = ping_qbittorrent(protocol, host, port, username, password, verify_ssl, getattr(config, 'QBT_CA_CERT', None))
            step2_status.setText(str(message or ('Connection successful.' if ok else 'Connection failed.')))
            if ok:
                QMessageBox.information(wizard, 'Connection Test', str(message or 'Connection successful.'))
            else:
                QMessageBox.warning(wizard, 'Connection Test', str(message or 'Connection failed.'))

        def _next_step() -> None:
            index = int(stack.currentIndex())
            if index < stack.count() - 1:
                stack.setCurrentIndex(index + 1)
            _update_nav()

        def _back_step() -> None:
            index = int(stack.currentIndex())
            if index > 0:
                stack.setCurrentIndex(index - 1)
            _update_nav()

        def _finish_setup() -> None:
            selected_targets: list[str] = []
            if target_qbt.isChecked():
                selected_targets.append('qbittorrent')
            if target_autobrr.isChecked():
                selected_targets.append('autobrr')
            if not selected_targets:
                selected_targets = ['qbittorrent']

            connection_payload = {
                'protocol': protocol_combo.currentText(),
                'host': host_edit.text(),
                'port': port_edit.text(),
                'username': user_edit.text(),
                'password': pass_edit.text(),
                'verify_ssl': verify_ssl_box.isChecked(),
                'mode': 'online' if online_radio.isChecked() else 'offline',
                'default_save_path': defaults_save_path.text().strip(),
                'default_download_path': defaults_download_path.text().strip(),
                'default_category': defaults_category.text().strip(),
                'default_affected_feeds': ', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or []),
            }
            conn_result = run_qt_save_connection_settings(connection_payload)
            platform_result = run_qt_save_platform_settings(
                {
                    'main_server': main_server_combo.currentText().strip() or 'qbittorrent',
                    'export_targets': selected_targets,
                }
            )
            old_theme = config.get_pref("theme", "light")
            new_theme = theme_combo.currentText().strip() or "light"
            needs_restart = (str(old_theme).strip().lower() != str(new_theme).strip().lower())
            runtime_result = run_qt_save_runtime_settings(
                {
                    'theme': theme_combo.currentText().strip() or 'light',
                    'log_level': log_level_combo.currentText().strip() or 'INFO',
                    'ui_style_theme': str(config.get_pref(PrefKeys.UI_STYLE_THEME, 'clam') or 'clam'),
                }
            )

            ok_all = bool(conn_result.get('success')) and bool(platform_result.get('success')) and bool(runtime_result.get('success'))
            _refresh_chips()
            if ok_all:
                QMessageBox.information(wizard, 'Setup Wizard', 'Setup completed successfully.')
                wizard.accept()
                if needs_restart:
                    resp = QMessageBox.question(wizard, "Restart Required", "Theme has been changed. Do you want to restart the application now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if resp == QMessageBox.StandardButton.Yes:
                        from src.utils import restart_application
                        restart_application()

            else:
                QMessageBox.warning(
                    wizard,
                    'Setup Wizard',
                    'Setup completed with some issues. Review Settings for details.',
                )
                wizard.accept()

        test_conn_btn.clicked.connect(_test_connection)
        back_btn.clicked.connect(_back_step)
        next_btn.clicked.connect(_next_step)
        finish_btn.clicked.connect(_finish_setup)
        cancel_btn.clicked.connect(wizard.reject)
        _update_nav()
        wizard.exec()

    def _open_settings_dialog() -> None:
        settings = run_qt_get_connection_settings()
        runtime = run_qt_get_runtime_settings()
        platform_settings = run_qt_get_platform_settings()
        export_targets = set(platform_settings.get('export_targets', []))
        dialog = QDialog(window)
        dialog.setWindowTitle('Settings - Configuration (UI v2)')
        dialog.resize(980, 760)
        dialog_layout = QVBoxLayout(dialog)

        tabs = QTabWidget(dialog)
        dialog_layout.addWidget(tabs, 1)

        tab_connection = QWidget()
        tab_connection_layout = QVBoxLayout(tab_connection)
        mode_group = QGroupBox('Connection Mode')
        mode_layout = QHBoxLayout(mode_group)
        online_radio = QRadioButton('Online - Direct API connection')
        offline_radio = QRadioButton('Offline - Generate JSON file only')
        mode_layout.addWidget(online_radio)
        mode_layout.addWidget(offline_radio)
        mode_layout.addStretch()
        online_radio.setChecked(str(settings.get('mode', 'online')) == 'online')
        offline_radio.setChecked(not online_radio.isChecked())
        tab_connection_layout.addWidget(mode_group)

        server_group = QGroupBox('Server Platform')
        server_form = QFormLayout(server_group)
        main_server_combo = QComboBox()
        supported_servers = [str(v).strip().lower() for v in (platform_settings.get('supported_servers', []) or []) if str(v).strip()]
        if not supported_servers:
            supported_servers = ['qbittorrent', 'autobrr']
        main_server_combo.addItems(supported_servers)
        main_server_combo.setCurrentText(str(platform_settings.get('main_server', 'qbittorrent') or 'qbittorrent'))
        server_form.addRow('Main Server:', main_server_combo)
        tab_connection_layout.addWidget(server_group)

        profile_group = QGroupBox('Unified Connection Profile Editor')
        profile_form = QFormLayout(profile_group)
        protocol_combo = QComboBox()
        protocol_combo.addItems(['http', 'https'])
        protocol_combo.setCurrentText(str(settings.get('protocol', 'http')))
        host_edit = QLineEdit(str(settings.get('host', '')))
        port_edit = QLineEdit(str(settings.get('port', '8080')))
        user_edit = QLineEdit(str(settings.get('username', '')))
        pass_edit = QLineEdit(str(settings.get('password', '')))
        ca_cert_edit = QLineEdit(str(settings.get('ca_cert', '') or ''))
        ca_cert_row = QWidget()
        ca_cert_layout = QHBoxLayout(ca_cert_row)
        ca_cert_layout.setContentsMargins(0, 0, 0, 0)
        ca_cert_layout.addWidget(ca_cert_edit, 1)
        ca_browse_btn = QPushButton('Browse...')

        def _browse_ca_cert() -> None:
            path, _ = QFileDialog.getOpenFileName(dialog, 'Select CA certificate', '', 'PEM/CRT/CER files (*.pem *.crt *.cer);;All files (*.*)')
            if path:
                ca_cert_edit.setText(path)

        ca_browse_btn.clicked.connect(_browse_ca_cert)
        ca_cert_layout.addWidget(ca_browse_btn)
        verify_ssl_box = QCheckBox('Verify SSL Certificate')
        verify_ssl_box.setChecked(bool(settings.get('verify_ssl', True)))
        test_conn_btn = QPushButton('Test Connection')
        profile_form.addRow('Protocol:', protocol_combo)
        profile_form.addRow('Host:', host_edit)
        profile_form.addRow('Port:', port_edit)
        profile_form.addRow('Username:', user_edit)
        profile_form.addRow('Password:', pass_edit)
        profile_form.addRow('CA Certificate:', ca_cert_row)
        profile_form.addRow('', verify_ssl_box)
        profile_form.addRow('', test_conn_btn)
        tab_connection_layout.addWidget(profile_group)

        profiles_group = QGroupBox('Saved Connection Profiles')
        profiles_layout = QVBoxLayout(profiles_group)
        profile_name_edit = QLineEdit('')
        profiles_layout.addWidget(QLabel('Profile Name:'))
        profiles_layout.addWidget(profile_name_edit)
        profiles_list = QListWidget()
        profiles_list.setSelectionMode(QAbstractItemView.SingleSelection)
        profiles_layout.addWidget(profiles_list)
        profiles_buttons = QHBoxLayout()
        profile_new_btn = QPushButton('New')
        profile_save_btn = QPushButton('Save Profile')
        profile_load_btn = QPushButton('Load Selected')
        profile_delete_btn = QPushButton('Delete Selected')
        profiles_buttons.addWidget(profile_new_btn)
        profiles_buttons.addWidget(profile_save_btn)
        profiles_buttons.addWidget(profile_load_btn)
        profiles_buttons.addWidget(profile_delete_btn)
        profiles_layout.addLayout(profiles_buttons)

        def _load_profiles_cache() -> list[dict[str, object]]:
            try:
                profiles = config.load_connection_profiles()
            except Exception:
                profiles = []
            if not isinstance(profiles, list):
                return []
            result: list[dict[str, object]] = []
            for profile in profiles:
                if isinstance(profile, dict):
                    result.append(dict(profile))
            return result

        def _refresh_profiles_list() -> None:
            profiles_list.clear()
            for profile in _load_profiles_cache():
                name = str(profile.get('name', '') or '').strip() or 'Unnamed'
                server = str(profile.get('server', 'qbittorrent') or 'qbittorrent').strip().lower()
                profiles_list.addItem(f'{name} - {server}')

        def _new_profile() -> None:
            profile_name_edit.setText('')
            protocol_combo.setCurrentText('http')
            host_edit.setText('localhost')
            port_edit.setText('8080')
            user_edit.setText('')
            pass_edit.setText('')
            ca_cert_edit.setText('')
            verify_ssl_box.setChecked(True)

        def _save_profile() -> None:
            profile_name = profile_name_edit.text().strip()
            if not profile_name:
                QMessageBox.warning(dialog, 'Profile Name Required', 'Please enter a profile name before saving.')
                return
            new_profile = {
                'name': profile_name,
                'server': main_server_combo.currentText().strip().lower() or 'qbittorrent',
                'protocol': protocol_combo.currentText().strip().lower() or 'http',
                'host': host_edit.text().strip() or 'localhost',
                'port': port_edit.text().strip() or '8080',
                'username': user_edit.text().strip(),
                'password': pass_edit.text(),
                'verify_ssl': bool(verify_ssl_box.isChecked()),
                'ca_cert': ca_cert_edit.text().strip(),
            }
            profiles = _load_profiles_cache()
            replaced = False
            for idx, profile in enumerate(profiles):
                if str(profile.get('name', '') or '').strip().lower() == profile_name.lower():
                    profiles[idx] = new_profile
                    replaced = True
                    break
            if not replaced:
                profiles.append(new_profile)
            if config.save_connection_profiles(profiles):
                _refresh_profiles_list()
                QMessageBox.information(dialog, 'Profile Saved', f'Saved profile: {profile_name}')
            else:
                QMessageBox.warning(dialog, 'Profile Save Failed', 'Could not save connection profile.')

        def _load_selected_profile() -> None:
            row = profiles_list.currentRow()
            if row < 0:
                return
            profiles = _load_profiles_cache()
            if row >= len(profiles):
                return
            profile = profiles[row]
            profile_name_edit.setText(str(profile.get('name', '') or ''))
            main_server_combo.setCurrentText(str(profile.get('server', 'qbittorrent') or 'qbittorrent'))
            protocol_combo.setCurrentText(str(profile.get('protocol', 'http') or 'http'))
            host_edit.setText(str(profile.get('host', 'localhost') or 'localhost'))
            port_edit.setText(str(profile.get('port', '8080') or '8080'))
            user_edit.setText(str(profile.get('username', '') or ''))
            pass_edit.setText(str(profile.get('password', '') or ''))
            ca_cert_edit.setText(str(profile.get('ca_cert', '') or ''))
            verify_ssl_box.setChecked(bool(profile.get('verify_ssl', True)))

        def _delete_selected_profile() -> None:
            row = profiles_list.currentRow()
            if row < 0:
                return
            profiles = _load_profiles_cache()
            if row >= len(profiles):
                return
            profile_name = str(profiles[row].get('name', 'Unnamed') or 'Unnamed')
            if QMessageBox.question(dialog, 'Delete Profile', f"Delete connection profile '{profile_name}'?") != QMessageBox.Yes:
                return
            del profiles[row]
            config.save_connection_profiles(profiles)
            _refresh_profiles_list()

        def _test_connection() -> None:
            protocol = protocol_combo.currentText().strip() or 'http'
            host = host_edit.text().strip()
            port = port_edit.text().strip() or '8080'
            username = user_edit.text().strip()
            password = pass_edit.text()
            verify_ssl = bool(verify_ssl_box.isChecked())
            ca_cert = ca_cert_edit.text().strip() or None
            if not host:
                QMessageBox.warning(dialog, 'Connection Test', 'Host is required for connection test.')
                return
            ok, message = ping_qbittorrent(protocol, host, port, username, password, verify_ssl, ca_cert)
            if ok:
                QMessageBox.information(dialog, 'Connection Test', str(message or 'Connection successful.'))
            else:
                QMessageBox.warning(dialog, 'Connection Test', str(message or 'Connection failed.'))

        profile_new_btn.clicked.connect(_new_profile)
        profile_save_btn.clicked.connect(_save_profile)
        profile_load_btn.clicked.connect(_load_selected_profile)
        profile_delete_btn.clicked.connect(_delete_selected_profile)
        test_conn_btn.clicked.connect(_test_connection)
        _refresh_profiles_list()

        tab_connection_layout.addWidget(profiles_group)
        tab_connection_layout.addStretch()
        tabs.addTab(tab_connection, 'Connection')

        defaults_save_path_edit = None
        defaults_download_path_edit = None
        defaults_category_edit = None
        defaults_category_combo = None
        categories_tree = None
        defaults_feeds_edit = None
        ask_delete_confirm_box = None
        prefix_imports_box = None
        auto_sanitize_box = None
        pre_import_check_box = None
        auto_import_sanitize_box = None
        show_import_check_box = None
        export_qbt_box = None
        export_autobrr_box = None
        filesystem_combo = None
        sanitize_replace_all_box = None
        sanitize_global_char_edit = None
        sanitize_char_edits = {}
        sanitize_preview_labels = {}
        theme_combo = None
        time_format_combo = None
        view_mode_combo = None
        font_family_edit = None
        font_size_spin = None
        ui_style_combo = None
        level_combo = None
        anilist_interval_spin = None
        subsplease_interval_spin = None
        retention_mode_combo = None
        cache_ttl_spin = None
        cache_max_mb_spin = None
        refresh_scope_combo = None
        lang_romaji_box = None
        lang_english_box = None
        lang_native_box = None
        lang_synonym_box = None
        lang_synonym_other_box = None
        sonarr_host_edit = None
        sonarr_port_edit = None
        sonarr_apikey_edit = None
        defaults_tab_index = None

        for tab_name in ['Defaults', 'Import/Export', 'Sanitization', 'Appearance', 'Font & Style', 'Diagnostics', 'API Rate Limits', 'Sonarr']:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            section = QGroupBox(tab_name)
            section_layout = QVBoxLayout(section)
            if tab_name == 'Defaults':
                defaults_tab_index = tabs.count()
            if tab_name == 'Defaults':
                defaults_save_path_edit = QLineEdit(str(getattr(config, 'DEFAULT_SAVE_PATH', '') or ''))
                defaults_download_path_edit = QLineEdit(str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or ''))
                defaults_download_path_edit.setReadOnly(True)
                defaults_category_edit = QLineEdit(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                defaults_category_edit.hide()
                defaults_category_combo = QComboBox()
                defaults_category_combo.setEditable(True)
                defaults_category_combo.setCurrentText(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                defaults_feeds_edit = QLineEdit(', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or []))
                ask_delete_confirm_box = QCheckBox('Ask for confirmation before deleting titles')
                ask_delete_confirm_box.setChecked(bool(config.get_pref('confirm_delete_titles', True)))
                section_layout.addWidget(QLabel('Default Save Path:'))
                section_layout.addWidget(defaults_save_path_edit)
                section_layout.addWidget(QLabel('qBittorrent Download Path (profile):'))
                section_layout.addWidget(defaults_download_path_edit)
                fetch_download_btn = QPushButton('Fetch Download Path from qBittorrent')

                def _fetch_download_path(silent: bool = False) -> None:
                    try:
                        from src.api.qbittorrent import QBittorrentClient
                        api = QBittorrentClient(
                            protocol=protocol_combo.currentText().strip().lower() or 'http',
                            host=host_edit.text().strip(),
                            port=port_edit.text().strip() or '8080',
                            username=user_edit.text().strip(),
                            password=pass_edit.text(),
                            verify_ssl=bool(verify_ssl_box.isChecked()),
                            ca_cert=ca_cert_edit.text().strip() or None,
                        )
                        if not api.connect():
                            if not silent:
                                QMessageBox.warning(dialog, 'Download Path', 'Could not connect to qBittorrent.')
                            return
                        prefs = api.get_preferences() or {}
                        api.close()
                        save_path = str(prefs.get('save_path', '') or '').strip()
                        if save_path:
                            defaults_download_path_edit.setText(save_path)
                            if not silent:
                                QMessageBox.information(dialog, 'Download Path', f'Fetched: {save_path}')
                        elif not silent:
                            QMessageBox.warning(dialog, 'Download Path', 'No save_path found in qBittorrent preferences.')
                    except Exception as exc:
                        if not silent:
                            QMessageBox.warning(dialog, 'Download Path', f'Failed to fetch download path: {exc}')

                fetch_download_btn.clicked.connect(_fetch_download_path)
                section_layout.addWidget(fetch_download_btn)
                section_layout.addWidget(QLabel('Default Category:'))
                section_layout.addWidget(defaults_category_combo)

                categories_tree = QTreeWidget()
                categories_tree.setHeaderLabels(['Category', 'Save Path'])
                categories_tree.setRootIsDecorated(False)
                categories_tree.setUniformRowHeights(True)
                categories_tree.setMinimumHeight(140)

                def _category_save_path(category_def: object) -> str:
                    if isinstance(category_def, dict):
                        for key in ('save_path', 'savePath', 'savePath', 'download_path', 'path'):
                            value = str(category_def.get(key, '') or '').strip()
                            if value:
                                return value
                    return ''

                def _load_categories_list() -> None:
                    try:
                        config.load_cached_categories()
                    except Exception:
                        pass
                    categories_tree.clear()
                    existing = {defaults_category_combo.itemText(i) for i in range(defaults_category_combo.count())}
                    cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
                    if isinstance(cats, dict):
                        for category_name in sorted(cats.keys()):
                            item = QTreeWidgetItem([
                                str(category_name),
                                _category_save_path(cats.get(category_name, {})),
                            ])
                            categories_tree.addTopLevelItem(item)
                            if str(category_name) not in existing:
                                defaults_category_combo.addItem(str(category_name))

                def _on_category_pick() -> None:
                    item = categories_tree.currentItem()
                    if not item:
                        return
                    defaults_category_combo.setCurrentText(item.text(0))

                categories_tree.itemSelectionChanged.connect(_on_category_pick)
                refresh_categories_btn = QPushButton('Refresh Cached Categories')
                refresh_categories_btn.clicked.connect(_load_categories_list)
                section_layout.addWidget(QLabel('Categories & Save Paths:'))
                section_layout.addWidget(categories_tree)
                section_layout.addWidget(refresh_categories_btn)
                _load_categories_list()

                section_layout.addWidget(QLabel('Default Affected Feeds (comma-separated):'))
                section_layout.addWidget(defaults_feeds_edit)
                section_layout.addWidget(ask_delete_confirm_box)
            elif tab_name == 'Import/Export':
                prefix_imports_box = QCheckBox('Enable Season/Year prefix logic')
                prefix_imports_box.setChecked(bool(config.get_pref('prefix_imports', True)))
                auto_sanitize_box = QCheckBox('Automatically sanitize invalid folder names')
                auto_sanitize_box.setChecked(bool(config.get_pref('auto_sanitize_paths', True)))
                pre_import_check_box = QCheckBox('Show pre-import sanitize check')
                pre_import_check_box.setChecked(bool(config.get_pref('pre_import_sanitize_check', True)))
                auto_import_sanitize_box = QCheckBox('Apply automatic sanitization during import')
                auto_import_sanitize_box.setChecked(bool(config.get_pref(PrefKeys.AUTO_SANITIZE, True)))
                show_import_check_box = QCheckBox('Always show sanitize review dialog before import')
                show_import_check_box.setChecked(bool(config.get_pref('show_import_sanitize_check', True)))
                export_qbt_box = QCheckBox('qBittorrent')
                export_autobrr_box = QCheckBox('Autobrr')
                export_qbt_box.setChecked('qbittorrent' in export_targets)
                export_autobrr_box.setChecked('autobrr' in export_targets)
                section_layout.addWidget(prefix_imports_box)
                section_layout.addWidget(auto_sanitize_box)
                section_layout.addWidget(pre_import_check_box)
                section_layout.addWidget(auto_import_sanitize_box)
                section_layout.addWidget(show_import_check_box)
                section_layout.addWidget(QLabel('Export Targets:'))
                section_layout.addWidget(export_qbt_box)
                section_layout.addWidget(export_autobrr_box)
            elif tab_name == 'Sanitization':
                filesystem_combo = QComboBox()
                filesystem_combo.addItems(['linux', 'windows'])
                filesystem_combo.setCurrentText(str(config.get_pref('filesystem_type', 'linux') or 'linux'))
                sanitize_replace_all_box = QCheckBox('Replace all invalid chars with a single replacement character')
                sanitize_replace_all_box.setChecked(bool(config.get_pref(PrefKeys.SANITIZE_REPLACE_ALL, True)))
                sanitize_global_char_edit = QLineEdit(str(config.get_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, '_') or '_')[:1])
                custom_map = config.get_pref(PrefKeys.SANITIZE_CUSTOM_MAP, {}) or {}
                if not isinstance(custom_map, dict):
                    custom_map = {}
                section_layout.addWidget(QLabel('Target Filesystem Type:'))
                section_layout.addWidget(filesystem_combo)
                section_layout.addWidget(sanitize_replace_all_box)
                section_layout.addWidget(QLabel('Global replacement character:'))
                section_layout.addWidget(sanitize_global_char_edit)
                section_layout.addWidget(QLabel('Custom per-character replacements (space/remove/text):'))

                def _set_preview_text(preview_label, value: str) -> None:
                    token = str(value or '').strip().lower()
                    if token == 'space':
                        preview_label.setText('(space)')
                    elif token == 'remove':
                        preview_label.setText('(remove)')
                    elif str(value or '') == '':
                        preview_label.setText('(empty)')
                    else:
                        preview_label.setText(str(value))

                def _on_sanitize_value_changed(ch: str, value: str) -> None:
                    preview_label = sanitize_preview_labels.get(ch)
                    if preview_label is None:
                        return
                    _set_preview_text(preview_label, value)

                for ch in FileSystem.INVALID_CHARS:
                    raw_val = str(custom_map.get(ch, '') or '')
                    token = raw_val.strip().lower()
                    if token == '__remove__':
                        display_val = 'remove'
                    elif token == '__space__':
                        display_val = 'space'
                    else:
                        display_val = raw_val
                    edit = QLineEdit(display_val)
                    sanitize_char_edits[ch] = edit
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(QLabel(f'{ch} ->'))
                    row_layout.addWidget(edit, 1)
                    preview_label = QLabel('(empty)')
                    sanitize_preview_labels[ch] = preview_label
                    row_layout.addWidget(QLabel('Preview:'))
                    row_layout.addWidget(preview_label)
                    edit.textChanged.connect(lambda text, c=ch: _on_sanitize_value_changed(c, text))
                    _set_preview_text(preview_label, display_val)
                    section_layout.addWidget(row)
            elif tab_name == 'Appearance':
                theme_combo = QComboBox()
                theme_combo.addItems(['light', 'dark'])
                theme_combo.setCurrentText(str(runtime.get('theme', 'light')))
                time_format_combo = QComboBox()
                time_format_combo.addItems(['24h', '12h'])
                time_format_combo.setCurrentText(str(config.get_pref('time_format', '24h') or '24h'))
                view_mode_combo = QComboBox()
                view_mode_combo.addItems(['expanded', 'compact'])
                view_mode_combo.setCurrentText(str(config.get_pref('view_mode', 'expanded') or 'expanded'))
                section_layout.addWidget(QLabel('Theme:'))
                section_layout.addWidget(theme_combo)
                section_layout.addWidget(QLabel('Time Format:'))
                section_layout.addWidget(time_format_combo)
                section_layout.addWidget(QLabel('View Mode:'))
                section_layout.addWidget(view_mode_combo)
            elif tab_name == 'Font & Style':
                font_size_spin = QSpinBox()
                font_size_spin.setRange(8, 14)
                font_size_spin.setValue(int(config.get_pref('font_size', 10) or 10))
                font_family_edit = QLineEdit(str(config.get_pref('font_family', 'Segoe UI') or 'Segoe UI'))
                ui_style_combo = QComboBox()
                ui_style_combo.addItems(['clam', 'vista', 'default'])
                ui_style_combo.setCurrentText(str(runtime.get('ui_style_theme', 'clam')))
                section_layout.addWidget(QLabel('Font Family:'))
                section_layout.addWidget(font_family_edit)
                section_layout.addWidget(QLabel('Font Size:'))
                section_layout.addWidget(font_size_spin)
                section_layout.addWidget(QLabel('Widget Style:'))
                section_layout.addWidget(ui_style_combo)
            elif tab_name == 'Diagnostics':
                level_combo = QComboBox()
                level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
                level_combo.setCurrentText(str(runtime.get('log_level', 'INFO')))
                section_layout.addWidget(QLabel('Log level:'))
                section_layout.addWidget(level_combo)
                test_btn = QPushButton('Test Connection Now')
                test_btn.clicked.connect(lambda: QMessageBox.information(dialog, 'Connection Test', str(run_qt_connection_test().get('message', 'Test completed.'))))
                section_layout.addWidget(test_btn)
                logs_btn = QPushButton('View Logs')
                logs_btn.clicked.connect(_open_qt_log_viewer)
                clear_logs_btn = QPushButton('Clear Log File')
                clear_logs_btn.clicked.connect(lambda: QMessageBox.information(dialog, 'Logs', str(run_qt_clear_log_file().get('message', 'Done'))))
                section_layout.addWidget(logs_btn)
                section_layout.addWidget(clear_logs_btn)
            elif tab_name == 'API Rate Limits':
                anilist_interval_spin = QSpinBox()
                anilist_interval_spin.setRange(1, 1440)
                anilist_interval_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, config.get_pref('anilist_manual_refresh_interval_minutes', 15)) or 15))
                subsplease_interval_spin = QSpinBox()
                subsplease_interval_spin.setRange(1, 1440)
                subsplease_interval_spin.setValue(int(config.get_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, config.get_pref('subsplease_manual_refresh_interval_minutes', 15)) or 15))
                retention_mode_combo = QComboBox()
                retention_mode_combo.addItems([
                    AniListCacheRetentionMode.AGE,
                    AniListCacheRetentionMode.SIZE,
                    AniListCacheRetentionMode.ROTATE,
                ])
                retention_mode_combo.setCurrentText(str(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, AniListCacheRetentionMode.AGE) or AniListCacheRetentionMode.AGE).strip().lower())
                cache_ttl_spin = QSpinBox()
                cache_ttl_spin.setRange(0, 3650)
                cache_ttl_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, 30) or 30))
                cache_max_mb_spin = QSpinBox()
                cache_max_mb_spin.setRange(1, 1024)
                cache_max_mb_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, 10) or 10))
                refresh_scope_combo = QComboBox()
                refresh_scope_combo.addItems([AniListRefreshScope.TITLE_ONLY, AniListRefreshScope.TITLE_AND_SEASON])
                refresh_scope_combo.setCurrentText(str(config.get_pref(PrefKeys.ANILIST_REFRESH_SCOPE, AniListRefreshScope.TITLE_ONLY) or AniListRefreshScope.TITLE_ONLY).strip().lower())
                langs = config.get_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, ['romaji', 'english', 'native', 'synonym', 'synonym_other']) or []
                if not isinstance(langs, list):
                    langs = ['romaji', 'english', 'native', 'synonym', 'synonym_other']
                lang_romaji_box = QCheckBox('Romaji')
                lang_romaji_box.setChecked('romaji' in langs)
                lang_english_box = QCheckBox('English')
                lang_english_box.setChecked('english' in langs)
                lang_native_box = QCheckBox('Native')
                lang_native_box.setChecked('native' in langs)
                lang_synonym_box = QCheckBox('Synonyms')
                lang_synonym_box.setChecked('synonym' in langs)
                lang_synonym_other_box = QCheckBox('Other-Lang Synonyms')
                lang_synonym_other_box.setChecked('synonym_other' in langs)
                section_layout.addWidget(QLabel('AniList minimum interval (minutes):'))
                section_layout.addWidget(anilist_interval_spin)
                section_layout.addWidget(QLabel('SubsPlease minimum interval (minutes):'))
                section_layout.addWidget(subsplease_interval_spin)
                section_layout.addWidget(QLabel('AniList cache retention mode:'))
                section_layout.addWidget(retention_mode_combo)
                section_layout.addWidget(QLabel('AniList cache max age (days):'))
                section_layout.addWidget(cache_ttl_spin)
                section_layout.addWidget(QLabel('AniList cache max size (MB):'))
                section_layout.addWidget(cache_max_mb_spin)
                section_layout.addWidget(QLabel('AniList manual refresh scope:'))
                section_layout.addWidget(refresh_scope_combo)
                section_layout.addWidget(QLabel('AniList title variation languages:'))
                section_layout.addWidget(lang_romaji_box)
                section_layout.addWidget(lang_english_box)
                section_layout.addWidget(lang_native_box)
                section_layout.addWidget(lang_synonym_box)
                section_layout.addWidget(lang_synonym_other_box)
            elif tab_name == 'Sonarr':
                sonarr_host_edit = QLineEdit(str(config.get_pref('sonarr_host', 'localhost') or 'localhost'))
                sonarr_port_edit = QLineEdit(str(config.get_pref('sonarr_port', '8989') or '8989'))
                sonarr_apikey_edit = QLineEdit(str(config.get_pref('sonarr_api_key', '') or ''))
                sonarr_apikey_edit.setEchoMode(QLineEdit.Password)
                section_layout.addWidget(QLabel('Sonarr Host:'))
                section_layout.addWidget(sonarr_host_edit)
                section_layout.addWidget(QLabel('Sonarr Port:'))
                section_layout.addWidget(sonarr_port_edit)
                section_layout.addWidget(QLabel('Sonarr API Key:'))
                section_layout.addWidget(sonarr_apikey_edit)
                
                test_sonarr_btn = QPushButton('Test Connection')
                def _test_sonarr() -> None:
                    QMessageBox.information(dialog, 'Sonarr Test', 'Testing Sonarr connection is currently mocked in the Qt preview shell.')
                test_sonarr_btn.clicked.connect(_test_sonarr)
                section_layout.addWidget(test_sonarr_btn)
            else:
                section_layout.addWidget(QLabel(f'{tab_name} settings are available in this preview tab.'))
            tab_layout.addWidget(section)
            tab_layout.addStretch()
            tabs.addTab(tab, tab_name)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QPushButton('Save && Close')

        def _on_settings_tab_changed(index: int) -> None:
            if defaults_tab_index is None or index != defaults_tab_index:
                return
            try:
                _load_categories_list()
            except Exception:
                pass
            try:
                _fetch_download_path(silent=True)
            except Exception:
                pass

        tabs.currentChanged.connect(_on_settings_tab_changed)
        if defaults_tab_index is not None:
            _on_settings_tab_changed(defaults_tab_index)

        def _save_settings_preview() -> None:
            needs_restart = False
            payload = {
                'protocol': protocol_combo.currentText(),
                'host': host_edit.text(),
                'port': port_edit.text(),
                'username': user_edit.text(),
                'password': pass_edit.text(),
                'ca_cert': ca_cert_edit.text().strip(),
                'verify_ssl': verify_ssl_box.isChecked(),
                'mode': 'online' if online_radio.isChecked() else 'offline',
                'default_save_path': (defaults_save_path_edit.text().strip() if defaults_save_path_edit is not None else str(getattr(config, 'DEFAULT_SAVE_PATH', '') or '')),
                'default_download_path': (defaults_download_path_edit.text().strip() if defaults_download_path_edit is not None else str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or '')),
                'default_category': (
                    defaults_category_combo.currentText().strip()
                    if defaults_category_combo is not None
                    else (defaults_category_edit.text().strip() if defaults_category_edit is not None else str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                ),
                'default_affected_feeds': (defaults_feeds_edit.text().strip() if defaults_feeds_edit is not None else ', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or [])),
            }
            connection_result = run_qt_save_connection_settings(payload)

            if defaults_category_edit is not None:
                config.DEFAULT_SAVE_PATH = defaults_save_path_edit.text().strip() if defaults_save_path_edit is not None else config.DEFAULT_SAVE_PATH
                config.DEFAULT_DOWNLOAD_PATH = defaults_download_path_edit.text().strip() if defaults_download_path_edit is not None else config.DEFAULT_DOWNLOAD_PATH
                config.DEFAULT_CATEGORY = (
                    defaults_category_combo.currentText().strip()
                    if defaults_category_combo is not None
                    else defaults_category_edit.text().strip()
                )
                config.set_pref('default_affected_feeds_manual', (defaults_feeds_edit.text().strip() if defaults_feeds_edit is not None else ''))
                if ask_delete_confirm_box is not None:
                    config.set_pref('confirm_delete_titles', bool(ask_delete_confirm_box.isChecked()))

            if prefix_imports_box is not None:
                config.set_pref('prefix_imports', bool(prefix_imports_box.isChecked()))
            if auto_sanitize_box is not None:
                config.set_pref('auto_sanitize_paths', bool(auto_sanitize_box.isChecked()))
            if pre_import_check_box is not None:
                config.set_pref('pre_import_sanitize_check', bool(pre_import_check_box.isChecked()))
            if auto_import_sanitize_box is not None:
                config.set_pref(PrefKeys.AUTO_SANITIZE, bool(auto_import_sanitize_box.isChecked()))
            if show_import_check_box is not None:
                value = bool(show_import_check_box.isChecked())
                config.set_pref('show_import_sanitize_check', value)
                config.set_pref('pre_import_sanitize_check', value)
            if filesystem_combo is not None:
                config.set_pref('filesystem_type', filesystem_combo.currentText())
            if sanitize_replace_all_box is not None:
                config.set_pref(PrefKeys.SANITIZE_REPLACE_ALL, bool(sanitize_replace_all_box.isChecked()))
            if sanitize_global_char_edit is not None:
                char_val = str(sanitize_global_char_edit.text() or '_')[:1]
                config.set_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, char_val or '_')
            if sanitize_char_edits:
                custom_map = {}
                for ch, edit in sanitize_char_edits.items():
                    val = str(edit.text() or '').strip()
                    if not val:
                        continue
                    token = val.lower()
                    if token == 'remove':
                        custom_map[ch] = '__REMOVE__'
                    elif token == 'space':
                        custom_map[ch] = '__SPACE__'
                    else:
                        custom_map[ch] = val
                config.set_pref(PrefKeys.SANITIZE_CUSTOM_MAP, custom_map)
            if theme_combo is not None:
                old_theme = config.get_pref("theme", "light")
                new_theme = theme_combo.currentText().strip() or "light"
                if str(old_theme).strip().lower() != str(new_theme).strip().lower():
                    needs_restart = True
                config.set_pref("theme", new_theme)
            if time_format_combo is not None:
                config.set_pref('time_format', time_format_combo.currentText())
            if view_mode_combo is not None:
                config.set_pref('view_mode', view_mode_combo.currentText())
            if font_family_edit is not None:
                config.set_pref('font_family', font_family_edit.text().strip() or 'Segoe UI')
            if font_size_spin is not None:
                config.set_pref('font_size', int(font_size_spin.value()))
            if ui_style_combo is not None:
                config.set_pref(PrefKeys.UI_STYLE_THEME, ui_style_combo.currentText())
            if level_combo is not None:
                config.set_pref('log_level', level_combo.currentText())
            if anilist_interval_spin is not None:
                interval = int(anilist_interval_spin.value())
                config.set_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, interval)
                config.set_pref('anilist_manual_refresh_interval_minutes', interval)
            if subsplease_interval_spin is not None:
                interval = int(subsplease_interval_spin.value())
                config.set_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, interval)
                config.set_pref('subsplease_manual_refresh_interval_minutes', interval)
            if retention_mode_combo is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, retention_mode_combo.currentText().strip().lower() or AniListCacheRetentionMode.AGE)
            if cache_ttl_spin is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, int(cache_ttl_spin.value()))
            if cache_max_mb_spin is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, int(cache_max_mb_spin.value()))
            if refresh_scope_combo is not None:
                config.set_pref(PrefKeys.ANILIST_REFRESH_SCOPE, refresh_scope_combo.currentText().strip().lower() or AniListRefreshScope.TITLE_ONLY)
            if all(v is not None for v in [lang_romaji_box, lang_english_box, lang_native_box, lang_synonym_box, lang_synonym_other_box]):
                selected_langs = []
                if lang_romaji_box.isChecked():
                    selected_langs.append('romaji')
                if lang_english_box.isChecked():
                    selected_langs.append('english')
                if lang_native_box.isChecked():
                    selected_langs.append('native')
                if lang_synonym_box.isChecked():
                    selected_langs.append('synonym')
                if lang_synonym_other_box.isChecked():
                    selected_langs.append('synonym_other')
                if not selected_langs:
                    selected_langs = ['romaji']
                config.set_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, selected_langs)

            if sonarr_host_edit is not None:
                config.set_pref('sonarr_host', sonarr_host_edit.text().strip())
            if sonarr_port_edit is not None:
                config.set_pref('sonarr_port', sonarr_port_edit.text().strip())
            if sonarr_apikey_edit is not None:
                config.set_pref('sonarr_api_key', sonarr_apikey_edit.text().strip())

            selected_targets = []
            if export_qbt_box is not None and export_qbt_box.isChecked():
                selected_targets.append('qbittorrent')
            if export_autobrr_box is not None and export_autobrr_box.isChecked():
                selected_targets.append('autobrr')
            if not selected_targets:
                selected_targets = ['qbittorrent']
            run_qt_save_platform_settings({'main_server': main_server_combo.currentText().strip() or 'qbittorrent', 'export_targets': selected_targets})

            if needs_restart:
                resp = QMessageBox.question(dialog, "Restart Required", "Theme has been changed. Do you want to restart the application now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if resp == QMessageBox.StandardButton.Yes:
                    from src.utils import restart_application
                    restart_application()

        save_btn.clicked.connect(_save_settings_preview)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        dialog_layout.addLayout(footer)
        dialog.exec()

    menubar = window.menuBar()

    file_menu = menubar.addMenu('File')

    recent_menu = QMenu('Recent Files', file_menu)

    def _open_recent_file(path: str) -> None:
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
    _add_menu_action(file_menu, 'Export to Targets...', lambda: _action_export_all(), 'Ctrl+Shift+S')
    _add_menu_action(file_menu, 'Export to Sonarr...', lambda: QMessageBox.information(window, 'Sonarr Export', 'Sonarr bulk-add/export flow is currently simulated in the Qt preview shell.'))
    file_menu.addSeparator()
    _add_menu_action(file_menu, 'Backup qBittorrent Rules...', lambda: _action_create_backup())
    _add_menu_action(file_menu, 'Restore from Backup...', lambda: _action_restore_backup())
    _add_menu_action(file_menu, 'Manage Backups...', lambda: _action_manage_backups())
    file_menu.addSeparator()
    _add_menu_action(file_menu, 'Exit', window.close)

    def _show_shortcuts_help() -> None:
        QMessageBox.information(
            window,
            'Keyboard Shortcuts',
            '\n'.join(
                [
                    'Ctrl+O: Import File',
                    'Ctrl+Shift+S: Export to Targets',
                    'Space: Toggle Enable/Disable',
                    'Ctrl+Z: Undo',
                    'Ctrl+B: Bulk Edit Selected',
                    'Ctrl+E: Export Selected Titles',
                    'Ctrl+Shift+E: Export All Titles',
                    'F5: Refresh Treeview',
                    'Ctrl+Shift+T: Apply Template',
                    'Ctrl+T: Save as Template',
                    'Ctrl+,: Settings',
                    'Ctrl+F: Focus Filter Search',
                    'Delete: Delete Selected',
                    'Enter: Open Advanced Editor',
                ]
            ),
        )

    edit_menu = menubar.addMenu('Edit')
    _add_menu_action(edit_menu, 'Toggle Enable/Disable', lambda: _action_toggle_selected(), 'Space')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Undo', lambda: _action_undo(), 'Ctrl+Z')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Bulk Edit Selected...', lambda: _action_bulk_toggle(), 'Ctrl+B')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Clear All Titles', lambda: _action_clear_all_titles(), 'Ctrl+Shift+C')
    _add_menu_action(edit_menu, 'Export Selected Titles...', lambda: _action_export_selected(), 'Ctrl+E')
    _add_menu_action(edit_menu, 'Export All Titles...', lambda: _action_export_all(), 'Ctrl+Shift+E')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'Refresh Treeview', lambda: _refresh_library_tree(), 'F5')
    edit_menu.addSeparator()
    _add_menu_action(edit_menu, 'View Trash...', lambda: _action_view_trash())

    templates_menu = menubar.addMenu('Templates')
    _add_menu_action(templates_menu, 'Apply Template...', lambda: _action_apply_template(), 'Ctrl+Shift+T')
    _add_menu_action(templates_menu, 'Save as Template...', lambda: _action_save_template(), 'Ctrl+T')
    _add_menu_action(templates_menu, 'Manage Templates...', lambda: _action_manage_templates())

    validate_menu = menubar.addMenu('Validate')
    _add_menu_action(validate_menu, 'Validate All Titles', lambda: _action_validate_all())

    settings_menu = menubar.addMenu('Settings')
    _add_menu_action(settings_menu, 'Setup Wizard...', _open_setup_wizard_dialog)
    _add_menu_action(settings_menu, 'Settings...', _open_settings_dialog, 'Ctrl+,')

    info_menu = menubar.addMenu('Info')
    _add_menu_action(info_menu, 'View Logs...', _open_qt_log_viewer)
    _add_menu_action(info_menu, 'Keyboard Shortcuts...', _show_shortcuts_help, 'F1')
    _add_menu_action(info_menu, 'About', lambda: QMessageBox.about(window, 'About', 'Torrent RSS Rule Editor\nQt preview shell'))

    season_group = QGroupBox('Season Configuration')
    season_layout = QHBoxLayout(season_group)
    season_layout.addStretch()
    season_layout.addWidget(QLabel('Season:'))
    season_combo = QComboBox()
    season_combo.addItems(['Winter', 'Spring', 'Summer', 'Fall'])
    season_combo.setCurrentText('Spring')
    season_layout.addWidget(season_combo)
    season_layout.addWidget(QLabel('Year:'))
    year_spin = QSpinBox()
    year_spin.setRange(2000, 2100)
    year_spin.setValue(2026)
    season_layout.addWidget(year_spin)
    layout.addWidget(season_group)

    actions_group = QGroupBox('Quick Actions')
    actions_layout = QHBoxLayout(actions_group)
    generate_btn = QPushButton('Generate')
    sync_btn = QPushButton('Sync')
    quick_subs_btn = QPushButton('Refresh SubsPlease')
    quick_ani_btn = QPushButton('Refresh AniList')
    actions_layout.addWidget(generate_btn)
    actions_layout.addWidget(sync_btn)
    actions_layout.addWidget(quick_subs_btn)
    actions_layout.addWidget(quick_ani_btn)
    actions_layout.addStretch()
    settings_btn = QPushButton('Settings')
    settings_btn.clicked.connect(_open_settings_dialog)
    actions_layout.addWidget(settings_btn)
    layout.addWidget(actions_group)

    chips_layout = QHBoxLayout()
    chip_style = f'background-color: {chip_bg}; border: 1px solid {border_color}; border-radius: 2px; padding: 4px 8px; font-size: 11px;'
    connection_chip = QLabel('Connection: ' + get_connection_status_text(config))
    titles_count = sum(len(v) for v in (getattr(config, 'ALL_TITLES', {}) or {}).values() if isinstance(v, list))
    titles_chip = QLabel(f'Titles: {titles_count}')
    connection_chip.setStyleSheet(chip_style)
    titles_chip.setStyleSheet(chip_style)
    chips_layout.addWidget(connection_chip)
    chips_layout.addWidget(titles_chip)
    chips_layout.addStretch()
    layout.addLayout(chips_layout)

    content_group = QGroupBox('Title Rules Library')
    content_layout = QVBoxLayout(content_group)

    search_layout = QHBoxLayout()
    search_layout.addWidget(QLabel('Filter:'))
    search_entry = QLineEdit()
    filter_combo = QComboBox()
    filter_combo.addItems(['Title', 'Category', 'Save Path'])
    clear_btn = QPushButton('Clear')
    search_layout.addWidget(search_entry, 1)
    search_layout.addWidget(filter_combo)
    search_layout.addWidget(clear_btn)
    content_layout.addLayout(search_layout)

    splitter = QSplitter()
    library_tree = QTreeWidget()
    library_tree.setColumnCount(5)
    library_tree.setHeaderLabels(['', '#', 'Title', 'Category', 'Save Path'])
    library_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    library_tree.setColumnWidth(0, 28)
    library_tree.setColumnWidth(1, 40)
    library_tree.setColumnWidth(2, 320)
    library_tree.setColumnWidth(3, 120)
    library_tree.setColumnWidth(4, 360)

    current_titles = getattr(config, 'ALL_TITLES', {}) or {}
    if not isinstance(current_titles, dict):
        current_titles = {}
        config.ALL_TITLES = current_titles

    row_num = 1
    for category, titles_list in current_titles.items():
        if not isinstance(titles_list, list):
            continue
        for rule in titles_list:
            if not isinstance(rule, dict):
                continue
            item = QTreeWidgetItem(library_tree)
            item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
            item.setText(1, str(row_num))
            item.setText(2, str(rule.get('node', {}).get('title') or rule.get('ruleName', '(Untitled)')))
            item.setText(3, str(category))
            item.setText(4, str(rule.get('savePath', '')))
            item.setData(0, core.Qt.UserRole, rule)
            row_num += 1

    splitter.addWidget(library_tree)

    editor_group = QGroupBox('Rule Editor')
    editor_layout = QVBoxLayout(editor_group)

    editor_top = QHBoxLayout()
    editor_top.addStretch()
    enabled_box = QCheckBox('Enabled')
    enabled_box.setChecked(True)
    undo_btn = QPushButton('Undo')
    undo_btn.setEnabled(False)
    editor_top.addWidget(enabled_box)
    editor_top.addWidget(undo_btn)
    editor_layout.addLayout(editor_top)

    editor_layout.addWidget(QLabel('Title:'))
    title_row = QHBoxLayout()
    title_edit = QLineEdit()
    prefix_btn = QPushButton('Prefix')
    title_row.addWidget(title_edit, 1)
    title_row.addWidget(prefix_btn)
    editor_layout.addLayout(title_row)

    editor_layout.addWidget(QLabel('Match Pattern:'))
    must_edit = QLineEdit()
    editor_layout.addWidget(must_edit)

    variations_group = QGroupBox('Title Variations')
    variations_layout = QVBoxLayout(variations_group)
    apply_row = QHBoxLayout()
    apply_row.addWidget(QCheckBox('Match Pattern'))
    apply_row.addWidget(QCheckBox('Title'))
    apply_row.addWidget(QCheckBox('Save Path'))
    apply_row.addStretch()
    variations_layout.addLayout(apply_row)
    variations_layout.addWidget(QLabel('AniList:'))
    variations_layout.addWidget(QLabel('SubsPlease:'))
    refresh_row = QHBoxLayout()
    refresh_subs_btn = QPushButton('Refresh SubsPlease Cache')
    refresh_ani_btn = QPushButton('Refresh AniList Cache')
    refresh_row.addWidget(refresh_subs_btn)
    refresh_row.addWidget(refresh_ani_btn)
    variations_layout.addLayout(refresh_row)
    editor_layout.addWidget(variations_group)

    editor_layout.addWidget(QLabel('Last Match:'))
    last_match_edit = QLineEdit()
    editor_layout.addWidget(last_match_edit)
    editor_layout.addWidget(QLabel('Save Path:'))
    save_path_edit = QLineEdit()
    editor_layout.addWidget(save_path_edit)
    editor_layout.addWidget(QLabel('Category:'))
    category_combo = QComboBox()
    category_combo.setEditable(True)
    editor_layout.addWidget(category_combo)

    advanced_btn = QPushButton('Advanced Settings...')
    editor_layout.addWidget(advanced_btn)
    editor_layout.addStretch()
    splitter.addWidget(editor_group)

    edit_undo_stack: list[dict[str, object]] = []
    qt_trash_items: list[dict[str, object]] = []

    def _iter_tree_items() -> list[object]:
        return [library_tree.topLevelItem(i) for i in range(library_tree.topLevelItemCount())]

    def _selected_items() -> list[object]:
        return list(library_tree.selectedItems() or [])

    def _collect_rule_rows() -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for item in _iter_tree_items():
            rule = item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            rule_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or item.text(2) or '').strip()
            rows.append({'rule_name': rule_name, 'enabled': 'enabled' if bool(rule.get('enabled', False)) else 'disabled'})
        return rows

    def _refresh_chips() -> None:
        current = getattr(config, 'ALL_TITLES', {}) or {}
        if not isinstance(current, dict):
            current = {}
            config.ALL_TITLES = current
        total = sum(len(v) for v in current.values() if isinstance(v, list))
        titles_chip.setText(f'Titles: {total}')
        connection_chip.setText('Connection: ' + get_connection_status_text(config))

    def _refresh_library_tree(select_rule_name: str | None = None) -> None:
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
        library_tree.clear()
        row_num = 1
        selected_item = None
        current = getattr(config, 'ALL_TITLES', {}) or {}
        if not isinstance(current, dict):
            current = {}
            config.ALL_TITLES = current
        for category, titles_list in current.items():
            if not isinstance(titles_list, list):
                continue
            for rule in titles_list:
                if not isinstance(rule, dict):
                    continue
                item = QTreeWidgetItem(library_tree)
                rule_name = str(rule.get('ruleName') or rule.get('node', {}).get('title') or '(Untitled)')
                item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
                item.setText(1, str(row_num))
                item.setText(2, str(rule.get('node', {}).get('title') or rule_name))
                item.setText(3, str(category))
                item.setText(4, str(rule.get('savePath', '')))
                item.setData(0, core.Qt.UserRole, rule)
                if select_rule_name and rule_name == select_rule_name:
                    selected_item = item
                row_num += 1
        if selected_item is not None:
            library_tree.setCurrentItem(selected_item)
        _refresh_chips()
        _apply_filter()

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
        edit_undo_stack.append({'item': item, 'before': copy.deepcopy(rule_before)})
        if len(edit_undo_stack) > 100:
            edit_undo_stack.pop(0)
        undo_btn.setEnabled(True)

    def _action_undo() -> None:
        if not edit_undo_stack:
            QMessageBox.information(window, 'Undo', 'Nothing to undo.')
            return
        snapshot = edit_undo_stack.pop()
        item = snapshot.get('item')
        before = snapshot.get('before')
        if item is None or not isinstance(before, dict):
            return
        rule = item.data(0, core.Qt.UserRole)
        if not isinstance(rule, dict):
            return
        rule.clear()
        rule.update(copy.deepcopy(before))
        item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
        item.setText(2, str(rule.get('node', {}).get('title') or rule.get('ruleName', '(Untitled)')))
        item.setText(4, str(rule.get('savePath', '')))
        _populate_editor_from_selection()
        undo_btn.setEnabled(bool(edit_undo_stack))

    def _save_current_rule_from_editor() -> None:
        selected = _selected_items()
        if not selected:
            return
        item = selected[0]
        rule = item.data(0, core.Qt.UserRole)
        if not isinstance(rule, dict):
            return
        before = copy.deepcopy(rule)
        _push_undo(item, before)
        node = dict(rule.get('node') or {})
        node['title'] = title_edit.text().strip()
        rule['node'] = node
        rule['ruleName'] = title_edit.text().strip() or str(rule.get('ruleName', ''))
        rule['mustContain'] = must_edit.text().strip()
        rule['savePath'] = save_path_edit.text().strip()
        rule['assignedCategory'] = category_combo.currentText().strip()
        rule['enabled'] = bool(enabled_box.isChecked())
        item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
        item.setText(2, str(node.get('title') or rule.get('ruleName', '(Untitled)')))
        item.setText(3, str(rule.get('assignedCategory', '')))
        item.setText(4, str(rule.get('savePath', '')))

    def _action_toggle_selected() -> None:
        selected = _selected_items()
        if not selected:
            return
        for item in selected:
            rule = item.data(0, core.Qt.UserRole)
            if not isinstance(rule, dict):
                continue
            _push_undo(item, copy.deepcopy(rule))
            rule['enabled'] = not bool(rule.get('enabled', False))
            item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
        _populate_editor_from_selection()

    def _action_bulk_toggle() -> None:
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
            for item in selected:
                rule = item.data(0, core.Qt.UserRole)
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
                    item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
                changed_count += 1
            _populate_editor_from_selection()
            dialog.accept()
            if changed_count > 0:
                _set_status(f'Bulk edit applied to {changed_count} rules')
                QMessageBox.information(window, 'Bulk Edit', f'Updated {changed_count} rule(s).')
            else:
                _set_status('Bulk edit made no changes', 4000)
                QMessageBox.warning(window, 'Bulk Edit', 'No rules were updated.')

        _update_summary()
        apply_btn.clicked.connect(_apply_bulk)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _selected_rule_names() -> list[str]:
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
        dlg_layout.addWidget(auto_sanitize_box)

        controls_row = QHBoxLayout()
        displayed_label = QLabel('Displayed: 0  |  OK: 0  |  WARN: 0  |  CRITICAL: 0')
        controls_row.addWidget(displayed_label, 1)
        toggle_changed_btn = QPushButton('Hide Non-Changed Titles')
        controls_row.addWidget(toggle_changed_btn)
        dlg_layout.addLayout(controls_row)

        table = QTreeWidget(dialog)
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
            rows = changed if show_changed_only['value'] else snapshots
            table.clear()
            ok_count = 0
            warn_count = 0
            crit_count = 0

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
                    if sev == 'critical':
                        for c in range(4):
                            row.setBackground(c, QColor('#4a1f1f'))
                            row.setForeground(c, QColor('#ffb3b3'))
                    elif sev == 'warn':
                        for c in range(4):
                            row.setBackground(c, QColor('#4a3f1f'))
                            row.setForeground(c, QColor('#ffd98a'))
                table.addTopLevelItem(row)

            displayed_label.setText(
                f'Displayed: {len(rows)}  |  OK: {ok_count}  |  WARN: {warn_count}  |  CRITICAL: {crit_count}'
            )
            if show_changed_only['value']:
                toggle_changed_btn.setText('Show All Titles')
            else:
                toggle_changed_btn.setText('Hide Non-Changed Titles')

        def _toggle_changed_only() -> None:
            show_changed_only['value'] = not show_changed_only['value']
            _populate_snapshot_table()

        toggle_changed_btn.clicked.connect(_toggle_changed_only)

        def _copy_row_to_clipboard(item, _column) -> None:
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
        continue_btn = QPushButton('Continue Import')
        button_row.addWidget(cancel_btn)
        button_row.addWidget(continue_btn)
        dlg_layout.addLayout(button_row)

        cancel_btn.clicked.connect(dialog.reject)
        continue_btn.clicked.connect(dialog.accept)

        if dialog.exec() != QDialog.Accepted:
            return False, None
        return True, bool(auto_sanitize_box.isChecked())

    def _run_qt_import_parsed(parsed: object, source_name: str) -> dict[str, object]:
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
        year = str(year_spin.value())

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
        path, _ = QFileDialog.getOpenFileName(window, 'Import Titles', '', 'Data Files (*.json *.csv *.txt);;All Files (*)')
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
        all_titles = getattr(config, 'ALL_TITLES', None) or {}
        if not isinstance(all_titles, dict) or not all_titles:
            QMessageBox.information(window, 'Export', 'No titles available to export.')
            return

        rules_dict = build_rules_from_titles(all_titles)
        if not isinstance(rules_dict, dict) or not rules_dict:
            QMessageBox.information(window, 'Export', 'No rules available to export.')
            return

        dialog = QDialog(window)
        dialog.setWindowTitle('Export to Targets')
        dialog.resize(560, 360)
        dialog_layout = QVBoxLayout(dialog)

        title_label = QLabel('Export Targets')
        title_label.setStyleSheet('font-weight: 600; font-size: 15px;')
        dialog_layout.addWidget(title_label)

        subtitle = QLabel('Choose one or more destinations for this export action.')
        subtitle.setWordWrap(True)
        dialog_layout.addWidget(subtitle)

        settings = run_qt_get_platform_settings()
        default_targets = [
            str(v).strip().lower() for v in (settings.get('export_targets', ['qbittorrent']) or ['qbittorrent']) if str(v).strip()
        ]

        qbt_box = QCheckBox('qBittorrent (rules JSON)')
        autobrr_box = QCheckBox('Autobrr (portable JSON)')
        qbt_box.setChecked('qbittorrent' in default_targets)
        autobrr_box.setChecked('autobrr' in default_targets)
        dialog_layout.addWidget(qbt_box)
        dialog_layout.addWidget(autobrr_box)

        total_titles = sum(len(v) for v in all_titles.values() if isinstance(v, list))
        status_label = QLabel(f'Ready to export {total_titles} title(s).')
        dialog_layout.addWidget(status_label)

        button_row = QHBoxLayout()
        export_btn = QPushButton('Export')
        cancel_btn = QPushButton('Cancel')
        button_row.addWidget(export_btn)
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        dialog_layout.addLayout(button_row)

        def _do_export() -> None:
            selected_targets: list[str] = []
            if qbt_box.isChecked():
                selected_targets.append('qbittorrent')
            if autobrr_box.isChecked():
                selected_targets.append('autobrr')

            if not selected_targets:
                selected_targets = ['qbittorrent']

            try:
                run_qt_save_platform_settings(
                    {
                        'main_server': getattr(config, 'MAIN_SERVER', 'qbittorrent'),
                        'export_targets': selected_targets,
                    }
                )
            except Exception:
                pass

            exported_paths: list[str] = []
            for target in selected_targets:
                payload = build_qt_target_export_payload(target, rules_dict)
                default_name = f'{target}_rules_export.json'
                path, _ = QFileDialog.getSaveFileName(
                    dialog,
                    f'Export for {target}',
                    default_name,
                    'JSON Files (*.json);;All Files (*)',
                )
                if not path:
                    continue
                try:
                    with open(path, 'w', encoding='utf-8') as fh:
                        json.dump(payload, fh, indent=2, ensure_ascii=False)
                    exported_paths.append(path)
                except Exception as exc:
                    QMessageBox.warning(dialog, 'Export', f'Failed exporting {target}: {exc}')

            if not exported_paths:
                QMessageBox.information(dialog, 'Export', 'No files were exported.')
                return

            if exported_paths:
                QMessageBox.information(dialog, 'Export Complete', f'Exported {len(exported_paths)} file(s).')
            dialog.accept()

        export_btn.clicked.connect(_do_export)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _action_export_selected() -> None:
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

        try:
            app_state = AppState.get_instance()
            for it in qt_trash_items[-len(_selected_items()):]:
                app_state.add_to_trash(copy.deepcopy(it))
        except Exception:
            pass

        result = run_qt_remove_titles_by_rule_names(selected)
        QMessageBox.information(window, 'Delete', str(result.get('message', 'Done')))
        _refresh_library_tree()

    def _action_view_trash() -> None:
        dialog = QDialog(window)
        dialog.setWindowTitle('Trash')
        dialog.resize(700, 420)
        dialog_layout = QVBoxLayout(dialog)

        trash_list = QListWidget(dialog)
        dialog_layout.addWidget(trash_list, 1)

        def _reload_trash() -> None:
            trash_list.clear()
            for it in qt_trash_items:
                trash_list.addItem(f"{it.get('src', 'titles')} - {it.get('title', '(untitled)')}")

        def _restore_selected() -> None:
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
            if not qt_trash_items:
                return
            if QMessageBox.question(dialog, 'Trash', 'Empty the trash permanently?') != QMessageBox.Yes:
                return
            qt_trash_items.clear()
            _reload_trash()

        button_row = QHBoxLayout()
        restore_btn = QPushButton('Restore Selected')
        delete_btn = QPushButton('Delete Permanently')
        empty_btn = QPushButton('Empty Trash')
        close_btn = QPushButton('Close')
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
        should_confirm = bool(config.get_pref('confirm_delete_titles', True))
        if should_confirm:
            if QMessageBox.question(window, 'Confirm', 'Clear all loaded titles?') != QMessageBox.Yes:
                return
        result = run_qt_clear_all_titles()
        QMessageBox.information(window, 'Clear All', str(result.get('message', 'Cleared')))
        _refresh_library_tree()

    def _action_validate_all() -> None:
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
        dialog = QDialog(window)
        dialog.setWindowTitle('Manage Backups')
        dialog.resize(760, 460)
        dialog_layout = QVBoxLayout(dialog)

        list_widget = QListWidget(dialog)
        dialog_layout.addWidget(list_widget, 1)
        backup_map: dict[int, tuple[str, str, object]] = {}

        def _reload_backups() -> None:
            list_widget.clear()
            backup_map.clear()
            backups = list_backups()
            for idx, entry in enumerate(backups):
                name, path, dt = entry
                backup_map[idx] = entry
                list_widget.addItem(f"{name}  ({dt.strftime('%Y-%m-%d %H:%M:%S')})")

        def _create_backup_now() -> None:
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
        templates = load_templates() or {}
        if not isinstance(templates, dict) or not templates:
            templates = get_default_templates()
            try:
                save_templates(templates)
            except Exception:
                pass
        return {str(k): v for k, v in templates.items() if isinstance(v, dict)}

    def _selected_rule_entry() -> tuple[object | None, dict[str, object] | None]:
        selected = _selected_items()
        if not selected:
            return None, None
        item = selected[0]
        rule = item.data(0, core.Qt.UserRole)
        if not isinstance(rule, dict):
            return item, None
        return item, rule

    def _apply_template_to_rule(item, rule: dict[str, object], template: dict[str, object]) -> None:
        _push_undo(item, copy.deepcopy(rule))
        apply_template_data_to_rule(rule, template)
        item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
        item.setText(3, str(rule.get('assignedCategory', '')))
        item.setText(4, str(rule.get('savePath', '')))
        _populate_editor_from_selection()

    def _action_apply_template() -> None:
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
        dialog = QDialog(window)
        dialog.setWindowTitle('Manage Templates')
        dialog.resize(920, 620)
        dialog_layout = QVBoxLayout(dialog)

        split = QSplitter(dialog)
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_widget = QListWidget(list_panel)
        list_layout.addWidget(list_widget, 1)
        split.addWidget(list_panel)

        edit_panel = QWidget()
        edit_layout = QFormLayout(edit_panel)
        tpl_desc = QLineEdit('')
        tpl_must = QLineEdit('')
        tpl_must_not = QLineEdit('')
        tpl_category = QLineEdit('')
        tpl_save = QLineEdit('')
        tpl_episode = QLineEdit('')
        tpl_enabled = QCheckBox('Enabled')
        tpl_regex = QCheckBox('Use regex')
        preview = QTextEdit(edit_panel)
        preview.setReadOnly(True)
        preview.setMinimumHeight(160)
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
        save_btn = QPushButton('Save Changes')
        apply_btn = QPushButton('Apply to Selected Rule')
        delete_btn = QPushButton('Delete')
        reset_btn = QPushButton('Reset Defaults')
        close_btn = QPushButton('Close')
        button_row.addWidget(new_btn)
        button_row.addWidget(save_btn)
        button_row.addWidget(apply_btn)
        button_row.addWidget(delete_btn)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        dialog_layout.addLayout(button_row)

        def _new_template() -> None:
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
        item, rule = _selected_rule_entry()
        if item is None or rule is None:
            QMessageBox.information(window, 'Advanced Rule Editor', 'Select a rule first.')
            return

        dialog = QDialog(window)
        dialog.setWindowTitle('Advanced Rule Editor')
        dialog.resize(920, 720)
        dialog_layout = QVBoxLayout(dialog)

        form = QFormLayout()
        adv_title = QLineEdit(str(rule.get('node', {}).get('title') or rule.get('ruleName', '')))
        adv_must = QLineEdit(str(rule.get('mustContain', '')))
        adv_must_not = QLineEdit(str(rule.get('mustNotContain', '')))
        adv_save = QLineEdit(str(rule.get('savePath', '')))
        adv_category = QLineEdit(str(rule.get('assignedCategory', '')))
        adv_episode = QLineEdit(str(rule.get('episodeFilter', '')))
        adv_lastmatch = QTextEdit(str(rule.get('lastMatch', '') or ''))
        adv_lastmatch.setMaximumHeight(90)
        adv_lastmatch_status = QLabel('')
        adv_ignore_days = QSpinBox()
        adv_ignore_days.setRange(0, 3650)
        adv_ignore_days.setValue(int(rule.get('ignoreDays', 0) or 0))
        adv_add_paused = QComboBox()
        adv_add_paused.addItems(['None', 'False', 'True'])
        current_add_paused = rule.get('addPaused', None)
        if current_add_paused is None:
            adv_add_paused.setCurrentText('None')
        elif bool(current_add_paused):
            adv_add_paused.setCurrentText('True')
        else:
            adv_add_paused.setCurrentText('False')
        adv_smart_filter = QCheckBox('Enable smart filter')
        adv_smart_filter.setChecked(bool(rule.get('smartFilter', False)))
        adv_content_layout = QLineEdit(str(rule.get('torrentContentLayout', '') or ''))
        adv_prev_matches = QTextEdit('\n'.join(str(v) for v in (rule.get('previouslyMatchedEpisodes', []) or [])))
        adv_prev_matches.setMaximumHeight(90)
        adv_priority = QSpinBox()
        adv_priority.setRange(-99999, 99999)
        adv_priority.setValue(int(rule.get('priority', 0) or 0))
        adv_enabled = QCheckBox('Enabled')
        adv_enabled.setChecked(bool(rule.get('enabled', True)))
        adv_regex = QCheckBox('Use Regex')
        adv_regex.setChecked(bool(rule.get('useRegex', False)))

        form.addRow('Rule Title:', adv_title)
        form.addRow('Must Contain:', adv_must)
        form.addRow('Must Not Contain:', adv_must_not)
        form.addRow('Save Path:', adv_save)
        form.addRow('Assigned Category:', adv_category)
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
        dialog_layout.addLayout(form)

        dialog_layout.addWidget(QLabel('Torrent Params (JSON):'))
        torrent_params_edit = QTextEdit(dialog)
        try:
            torrent_params_edit.setPlainText(json.dumps(rule.get('torrentParams', {}), indent=2, ensure_ascii=False))
        except Exception:
            torrent_params_edit.setPlainText('{}')
        dialog_layout.addWidget(torrent_params_edit, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton('Cancel')
        apply_btn = QPushButton('Apply')
        footer.addWidget(cancel_btn)
        footer.addWidget(apply_btn)
        dialog_layout.addLayout(footer)

        def _validate_lastmatch_text(show_dialog: bool = False) -> tuple[bool, object]:
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
            rule['assignedCategory'] = adv_category.text().strip()
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

            item.setText(0, '✓' if bool(rule.get('enabled', False)) else '')
            item.setText(2, title_value)
            item.setText(3, str(rule.get('assignedCategory', '')))
            item.setText(4, str(rule.get('savePath', '')))
            _populate_editor_from_selection()
            _set_status('Advanced rule settings applied.', 4000)
            dialog.accept()

        cancel_btn.clicked.connect(dialog.reject)
        apply_btn.clicked.connect(_apply_advanced)
        dialog.exec()

    def _populate_editor_from_selection() -> None:
        selected = library_tree.selectedItems()
        if not selected:
            title_edit.clear()
            must_edit.clear()
            save_path_edit.clear()
            category_combo.setCurrentText('')
            enabled_box.setChecked(False)
            return
        rule = selected[0].data(0, core.Qt.UserRole)
        if not isinstance(rule, dict):
            return
        title_edit.setText(str(rule.get('node', {}).get('title') or rule.get('ruleName', '')))
        must_edit.setText(str(rule.get('mustContain', '')))
        save_path_edit.setText(str(rule.get('savePath', '')))
        category_combo.setCurrentText(str(rule.get('assignedCategory', '')))
        enabled_box.setChecked(bool(rule.get('enabled', False)))

    def _apply_filter() -> None:
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
        _add_menu_action(menu, 'Bulk Edit Selected...', lambda: _action_bulk_toggle())
        menu.addSeparator()
        _add_menu_action(menu, 'Export Selected Titles...', lambda: _action_export_selected())
        _add_menu_action(menu, 'Delete', lambda: _action_delete_selected())
        menu.exec(library_tree.mapToGlobal(pos))

    def _on_tree_space() -> None:
        if _selected_items():
            _action_toggle_selected()

    def _on_tree_delete() -> None:
        if _selected_items():
            _action_delete_selected()

    def _on_tree_enter() -> None:
        if _selected_items():
            _open_advanced_editor()

    def _on_search_escape() -> None:
        if search_entry.text().strip():
            search_entry.clear()
        else:
            library_tree.setFocus()

    clear_btn.clicked.connect(search_entry.clear)
    search_entry.textChanged.connect(_apply_filter)
    filter_combo.currentTextChanged.connect(lambda _=None: _apply_filter())
    library_tree.itemSelectionChanged.connect(_populate_editor_from_selection)
    library_tree.itemDoubleClicked.connect(lambda _item=None, _col=0: _on_tree_enter())
    library_tree.setContextMenuPolicy(core.Qt.CustomContextMenu)
    library_tree.customContextMenuRequested.connect(_on_tree_context_menu)
    tree_shortcuts: list[object] = []
    tree_shortcuts.append(QShortcut(QKeySequence('Space'), library_tree, activated=_on_tree_space))
    tree_shortcuts.append(QShortcut(QKeySequence('Delete'), library_tree, activated=_on_tree_delete))
    tree_shortcuts.append(QShortcut(QKeySequence('Return'), library_tree, activated=_on_tree_enter))
    tree_shortcuts.append(QShortcut(QKeySequence('Enter'), library_tree, activated=_on_tree_enter))
    tree_shortcuts.append(QShortcut(QKeySequence('Ctrl+F'), library_tree, activated=lambda: search_entry.setFocus()))
    tree_shortcuts.append(QShortcut(QKeySequence('Escape'), search_entry, activated=_on_search_escape))

    undo_btn.clicked.connect(_action_undo)
    enabled_box.stateChanged.connect(lambda _=None: _save_current_rule_from_editor())
    title_edit.editingFinished.connect(_save_current_rule_from_editor)
    must_edit.editingFinished.connect(_save_current_rule_from_editor)
    save_path_edit.editingFinished.connect(_save_current_rule_from_editor)
    category_combo.lineEdit().editingFinished.connect(_save_current_rule_from_editor)

    def _add_prefix_to_selected() -> None:
        selected = _selected_items()
        if not selected:
            return
        current = title_edit.text().strip()
        if not current:
            return
        prefix = f"{season_combo.currentText()} {year_spin.value()} - "
        if current.startswith(prefix):
            return
        title_edit.setText(prefix + current)
        _save_current_rule_from_editor()

    prefix_btn.clicked.connect(_add_prefix_to_selected)

    def _action_refresh_subsplease() -> None:
        _set_status('Refreshing SubsPlease cache...')
        result = run_qt_subsplease_refresh()
        _set_status(str(result.get('fetch_status', '') or 'SubsPlease refresh completed.'), 4000)
        QMessageBox.information(window, 'Refresh', format_refresh_result_text('SubsPlease', result))

    refresh_subs_btn.clicked.connect(_action_refresh_subsplease)
    def _action_refresh_anilist() -> None:
        _set_status('Refreshing AniList cache...')
        result = run_qt_anilist_refresh(
            current_title=title_edit.text(),
            current_must=must_edit.text(),
            selected_season=season_combo.currentText(),
            selected_year=str(year_spin.value()),
            refresh_scope_override=str(AniListRefreshScope.CURRENT_ONLY.value),
        )
        _set_status(str(result.get('fetch_status', '') or 'AniList refresh completed.'), 4000)
        QMessageBox.information(window, 'Refresh', format_refresh_result_text('AniList', result))

    refresh_ani_btn.clicked.connect(_action_refresh_anilist)
    advanced_btn.clicked.connect(_open_advanced_editor)

    quick_subs_btn.clicked.connect(_action_refresh_subsplease)
    quick_ani_btn.clicked.connect(_action_refresh_anilist)

    def _action_generate() -> None:
        rule_count = len(build_rules_from_titles(getattr(config, 'ALL_TITLES', {}) or {}))
        _set_status(f'Generated {rule_count} rule(s) in memory.', 4000)
        QMessageBox.information(window, 'Generate', f'Generated {rule_count} rules in memory.')

    generate_btn.clicked.connect(_action_generate)

    def _action_sync_fetch_existing() -> None:
        _set_status('Sync: fetching existing rules from qBittorrent...')
        snapshot = run_qt_qbittorrent_snapshot()
        rules = snapshot.get('rules', {}) if isinstance(snapshot, dict) else {}
        if not isinstance(rules, dict):
            rules = {}

        if not rules:
            _set_status('Sync complete: no existing rules available to add.', 5000)
            QMessageBox.information(window, 'Sync', 'No existing rules available to add.')
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

        _set_status(f'Sync complete: {msg}', 6000)
        QMessageBox.information(window, 'Sync', msg)

    def _action_sync() -> None:
        chooser = QMessageBox(window)
        chooser.setIcon(QMessageBox.Question)
        chooser.setWindowTitle('Sync')
        chooser.setText('Choose a sync mode.')
        chooser.setInformativeText(
            'Fetch Existing Rules to Titles mirrors Tk sync behavior.\n'
            'Apply Enabled-State Drafts sends current enabled toggles to qBittorrent.'
        )
        fetch_btn = chooser.addButton('Fetch Existing Rules to Titles', QMessageBox.ActionRole)
        apply_btn = chooser.addButton('Apply Enabled-State Drafts to qBittorrent', QMessageBox.ActionRole)
        chooser.addButton(QMessageBox.Cancel)
        chooser.setDefaultButton(fetch_btn)
        chooser.exec()

        clicked = chooser.clickedButton()
        if clicked is fetch_btn:
            _action_sync_fetch_existing()
            return
        if clicked is not apply_btn:
            _set_status('Sync cancelled by user.', 3000)
            return

        _set_status('Preparing sync dry run...')
        rule_rows = _collect_rule_rows()
        selected_names = _selected_rule_names()
        if not selected_names:
            selected_names = [str(row.get('rule_name', '') or '').strip() for row in rule_rows if str(row.get('rule_name', '') or '').strip()]
        dry_run = run_qt_rule_sync_dry_run(rule_rows, selected_names)
        summary_text = format_rule_sync_dry_run_text(dry_run)
        if int(dry_run.get('selected_count', 0) or 0) == 0:
            _set_status('Sync skipped: no rules selected.', 4000)
            QMessageBox.information(window, 'Sync', 'No rules are selected and no rule rows are available to sync.')
            return
        if QMessageBox.question(window, 'Sync Preview', summary_text + '\n\nApply these changes to qBittorrent?') != QMessageBox.Yes:
            _set_status('Sync cancelled by user.', 3000)
            return
        _set_status('Applying sync changes to qBittorrent...')
        apply_result = run_qt_apply_rule_sync(dry_run.get('changes', []) if isinstance(dry_run, dict) else [])
        _set_status(
            f"Sync result: applied {apply_result.get('applied_count', 0)}, failed {apply_result.get('failed_count', 0)}.",
            6000,
        )
        QMessageBox.information(window, 'Sync Result', f"Applied: {apply_result.get('applied_count', 0)}\nFailed: {apply_result.get('failed_count', 0)}\n{apply_result.get('rollback_guidance', '')}")

    sync_btn.clicked.connect(_action_sync)

    def _window_drag_enter_event(event) -> None:
        try:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:
            event.ignore()

    def _window_drop_event(event) -> None:
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
                year=str(year_spin.value()),
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

    splitter.setSizes([760, 380])
    content_layout.addWidget(splitter, 1)
    layout.addWidget(content_group, 1)

    window.setCentralWidget(central)

    status = QStatusBar(window)
    status_bar_ref['bar'] = status
    window.setStatusBar(status)
    _set_status('Connected: ' + get_connection_status_text(config))

    window.show()
    app.exec()
