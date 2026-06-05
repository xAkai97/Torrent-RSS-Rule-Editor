"""Controlled server sync helpers for Qt Phase 4.

This module provides:
- Dry-run summaries for rule enabled-state changes.
- Explicit apply flow to qBittorrent with partial-failure reporting.
"""

from __future__ import annotations

from typing import Any, Dict

from src.api.qbittorrent import QBittorrentClient
from src.config import config
from src.utils import get_display_title, get_rule_name, sanitize_entry_for_export


def _to_enabled(value: Any) -> bool:
    text = str(value or '').strip().lower()
    if text in {'yes', 'true', '1', 'enabled'}:
        return True
    if text in {'no', 'false', '0', 'disabled'}:
        return False
    return bool(value)


def _desired_enabled_by_rule_name(rule_rows: list[dict[str, str]], selected_rule_names: list[str]) -> dict[str, bool]:
    selected = {str(name or '').strip() for name in selected_rule_names if str(name or '').strip()}
    desired: dict[str, bool] = {}
    for row in rule_rows or []:
        name = str((row or {}).get('rule_name', '') or '').strip()
        if not name:
            continue
        if selected and name not in selected:
            continue
        desired[name] = _to_enabled((row or {}).get('enabled', ''))
    return desired


def build_rule_sync_dry_run(
    rule_rows: list[dict[str, str]],
    selected_rule_names: list[str],
    all_titles: dict[str, list[Any]] | None = None,
) -> Dict[str, Any]:
    """Build dry-run summary for enabled-state sync changes."""
    desired = _desired_enabled_by_rule_name(rule_rows, selected_rule_names)
    titles = all_titles if isinstance(all_titles, dict) else getattr(config, 'ALL_TITLES', {})

    changes: list[dict[str, Any]] = []
    unchanged_count = 0
    matched_rule_names: set[str] = set()

    if not isinstance(titles, dict):
        titles = {}

    for media_type, entries in titles.items():
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue

            candidate_names = {
                str(get_rule_name(entry, '') or '').strip(),
                str(get_display_title(entry, '') or '').strip(),
                str(entry.get('ruleName', '') or '').strip(),
                str(entry.get('name', '') or '').strip(),
                str(entry.get('mustContain', '') or '').strip(),
            }
            candidate_names = {name for name in candidate_names if name}

            hit = None
            for candidate in candidate_names:
                if candidate in desired:
                    hit = candidate
                    break
            if not hit:
                continue

            matched_rule_names.add(hit)
            current_enabled = bool(entry.get('enabled', True))
            next_enabled = bool(desired[hit])
            if current_enabled == next_enabled:
                unchanged_count += 1
                continue

            rule_def = sanitize_entry_for_export(dict(entry))
            rule_def['enabled'] = next_enabled
            if isinstance(rule_def.get('torrentParams'), dict):
                rule_def['torrentParams'] = dict(rule_def.get('torrentParams') or {})

            changes.append(
                {
                    'rule_name': hit,
                    'media_type': str(media_type),
                    'index': int(idx),
                    'from_enabled': current_enabled,
                    'to_enabled': next_enabled,
                    'rule_def': rule_def,
                }
            )

    missing = sorted([name for name in desired.keys() if name not in matched_rule_names])
    return {
        'selected_count': len(desired),
        'matched_count': len(matched_rule_names),
        'unchanged_count': unchanged_count,
        'change_count': len(changes),
        'missing_count': len(missing),
        'missing_rule_names': missing,
        'changes': changes,
    }


def format_rule_sync_dry_run_text(summary: Dict[str, Any]) -> str:
    """Render a readable dry-run summary."""
    lines = [
        'Rule Sync Dry Run',
        f"Selected: {int(summary.get('selected_count', 0) or 0)}",
        f"Matched: {int(summary.get('matched_count', 0) or 0)}",
        f"Changes: {int(summary.get('change_count', 0) or 0)}",
        f"Unchanged: {int(summary.get('unchanged_count', 0) or 0)}",
        f"Missing: {int(summary.get('missing_count', 0) or 0)}",
    ]

    missing = summary.get('missing_rule_names', []) or []
    if missing:
        lines.append('')
        lines.append('Missing Rules:')
        lines.extend([f"- {str(name)}" for name in missing[:8]])
        if len(missing) > 8:
            lines.append('- ...')

    changes = summary.get('changes', []) or []
    if changes:
        lines.append('')
        lines.append('Planned Changes:')
        for item in changes[:12]:
            lines.append(
                f"- {item.get('rule_name')}: {bool(item.get('from_enabled'))} -> {bool(item.get('to_enabled'))}"
            )
        if len(changes) > 12:
            lines.append('- ...')

    return '\n'.join(lines)


def apply_rule_sync_plan(changes: list[dict[str, Any]]) -> Dict[str, Any]:
    """Apply dry-run changes to qBittorrent with partial-failure reporting."""
    if not changes:
        return {
            'applied_count': 0,
            'failed_count': 0,
            'failed_rules': [],
            'rollback_guidance': 'No changes to apply.',
            'success': True,
        }

    protocol = str(getattr(config, 'QBT_PROTOCOL', '') or '').strip()
    host = str(getattr(config, 'QBT_HOST', '') or '').strip()
    port = str(getattr(config, 'QBT_PORT', '') or '').strip()
    username = str(getattr(config, 'QBT_USER', '') or '').strip()
    password = str(getattr(config, 'QBT_PASS', '') or '').strip()
    verify_ssl = bool(getattr(config, 'QBT_VERIFY_SSL', True))
    ca_cert = getattr(config, 'QBT_CA_CERT', None)

    if not host or not port:
        return {
            'applied_count': 0,
            'failed_count': len(changes),
            'failed_rules': [str(c.get('rule_name', '')) for c in changes],
            'rollback_guidance': 'qBittorrent host/port missing. Configure connection, rerun dry run, then apply again.',
            'success': False,
        }

    client = QBittorrentClient(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        ca_cert=ca_cert,
    )

    applied: list[str] = []
    failed: list[str] = []
    try:
        client.connect()
        for change in changes:
            rule_name = str(change.get('rule_name', '') or '').strip()
            rule_def = change.get('rule_def', {})
            if not rule_name or not isinstance(rule_def, dict):
                failed.append(rule_name or '<invalid-rule>')
                continue
            ok = bool(client.set_rule(rule_name, rule_def))
            if ok:
                applied.append(rule_name)
            else:
                failed.append(rule_name)
    except Exception:
        failed.extend([str(c.get('rule_name', '')) for c in changes if str(c.get('rule_name', '') or '').strip()])
    finally:
        try:
            client.close()
        except Exception:
            pass

    success = len(failed) == 0
    if success:
        guidance = 'Apply completed. Reload snapshot to verify server state.'
    elif applied:
        guidance = (
            'Partial apply failure. Reload snapshot, compare applied rules, then re-run dry run. '
            'If needed, restore previous values by reapplying with prior enabled states.'
        )
    else:
        guidance = 'No rules applied. Fix connectivity/validation issues, rerun dry run, then apply.'

    return {
        'applied_count': len(applied),
        'failed_count': len(failed),
        'failed_rules': sorted([name for name in failed if name]),
        'rollback_guidance': guidance,
        'success': success,
    }
