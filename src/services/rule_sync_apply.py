"""
Rule Sync Apply — Controlled Server Synchronization with Safety Net.

This is the "dangerous" module — it's the one that actually pushes changes to
the qBittorrent server. To prevent accidental data loss, it implements a
two-step process:

  1. **Dry Run** — Compute exactly what would change and show it to the user
  2. **Apply** — Execute the plan, reporting partial failures

The dry run compares local ALL_TITLES against either:
  - Simple enabled-state tracking (legacy mode, no server_rules provided)
  - Full field-by-field diff against server rules (when server_rules is provided)

Each change is classified as CREATE (new rule) or UPDATE (modified rule),
and the apply step pushes each change individually so that partial failures
don't block everything.
"""

from __future__ import annotations

from typing import Any, Dict

from src.api.qbittorrent import QBittorrentClient
from src.config import config
from src.utils import get_display_title, get_rule_name, sanitize_entry_for_export


def _to_enabled(value: Any) -> bool:
    """
    Convert various enabled/disabled representations to a Python bool.

    Handles strings like "yes", "true", "1", "enabled" and their negatives.
    """
    text = str(value or '').strip().lower()
    if text in {'yes', 'true', '1', 'enabled'}:
        return True
    if text in {'no', 'false', '0', 'disabled'}:
        return False
    return bool(value)


def _desired_enabled_by_rule_name(rule_rows: list[dict[str, str]], selected_rule_names: list[str]) -> dict[str, bool]:
    """
    Build a lookup of rule_name → desired enabled state from the GUI table rows.

    Only includes rows whose rule_name appears in selected_rule_names (if
    that list is non-empty). This lets the user sync only a subset of rules.

    Args:
        rule_rows: All rows from the Qt rules table.
        selected_rule_names: Which rules the user selected to sync (empty = all).

    Returns:
        A dict mapping rule_name → desired bool enabled state.
    """
    selected = {str(name or '').strip() for name in selected_rule_names if str(name or '').strip()}
    desired: dict[str, bool] = {}
    for row in rule_rows or []:
        name = str((row or {}).get('rule_name', '') or '').strip()
        if not name:
            continue
        if selected and name not in selected:
            continue  # Skip unselected rules
        desired[name] = _to_enabled((row or {}).get('enabled', ''))
    return desired


def get_rule_diff(local_rule: dict[str, Any], server_rule: dict[str, Any]) -> list[str]:
    """
    Compare a local rule definition against the server's version field-by-field.

    Returns a list of human-readable diff strings describing what changed.
    Each string is in the format: "fieldName: 'old_value' -> 'new_value'"

    Handles type normalization:
      - Boolean fields (enabled, useRegex, smartFilter) → compared as bool
      - Integer fields (ignoreDays, priority) → compared as int
      - String fields → compared as stripped strings
      - affectedFeeds → compared as sorted lists
      - torrentParams sub-fields → compared individually

    Args:
        local_rule: The local rule definition (from ALL_TITLES, sanitized).
        server_rule: The server's current rule definition.

    Returns:
        A list of diff description strings. Empty list means rules are identical.
    """
    diffs = []

    # Compare standard top-level fields
    fields = [
        ('enabled', 'enabled'),
        ('mustContain', 'mustContain'),
        ('mustNotContain', 'mustNotContain'),
        ('savePath', 'savePath'),
        ('assignedCategory', 'assignedCategory'),
        ('useRegex', 'useRegex'),
        ('episodeFilter', 'episodeFilter'),
        ('ignoreDays', 'ignoreDays'),
        ('smartFilter', 'smartFilter'),
        ('torrentContentLayout', 'torrentContentLayout'),
        ('priority', 'priority'),
    ]

    for local_key, server_key in fields:
        l_val = local_rule.get(local_key)
        s_val = server_rule.get(server_key)
        # Normalize types so we don't get false diffs from type mismatches
        if local_key in ('enabled', 'useRegex', 'smartFilter'):
            l_val = bool(l_val)
            s_val = bool(s_val)
        elif local_key in ('ignoreDays', 'priority'):
            l_val = int(l_val or 0)
            s_val = int(s_val or 0)
        else:
            l_val = str(l_val or '').strip()
            s_val = str(s_val or '').strip()

        if l_val != s_val:
            diffs.append(f"{local_key}: '{s_val}' -> '{l_val}'")

    # Compare affectedFeeds (order-independent comparison)
    l_feeds = sorted([str(f).strip() for f in local_rule.get('affectedFeeds', []) if f])
    s_feeds = sorted([str(f).strip() for f in server_rule.get('affectedFeeds', []) if f])
    if l_feeds != s_feeds:
        diffs.append(f"affectedFeeds: {s_feeds} -> {l_feeds}")

    # Compare torrentParams sub-fields individually
    l_params = local_rule.get('torrentParams', {})
    s_params = server_rule.get('torrentParams', {})
    if isinstance(l_params, dict) and isinstance(s_params, dict):
        for k in ('download_limit', 'upload_limit', 'ratio_limit', 'seeding_time_limit', 'inactive_seeding_time_limit', 'skip_checking', 'stopped', 'use_auto_tmm'):
            lv = l_params.get(k)
            sv = s_params.get(k)
            if lv is not None and sv is not None:
                # Normalize booleans vs integers
                if k in ('skip_checking', 'stopped', 'use_auto_tmm'):
                    lv, sv = bool(lv), bool(sv)
                else:
                    lv, sv = int(lv), int(sv)
                if lv != sv:
                    diffs.append(f"torrentParams.{k}: '{sv}' -> '{lv}'")

    return diffs


def build_rule_sync_dry_run(
    rule_rows: list[dict[str, str]],
    selected_rule_names: list[str],
    all_titles: dict[str, list[Any]] | None = None,
    server_rules: dict[str, dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Build a dry-run summary showing what would change if sync is applied.

    This is the safety net — it computes all changes WITHOUT touching the server.
    The result is displayed to the user for review before they confirm.

    Two modes:
      1. **Legacy mode** (server_rules=None): Only compares enabled/disabled state.
         Used for backward compatibility with existing tests.
      2. **Full diff mode** (server_rules provided): Compares every field and
         classifies changes as CREATE (new rule) or UPDATE (modified rule).

    Args:
        rule_rows: All rows from the Qt rules table.
        selected_rule_names: Which rules the user selected to sync.
        all_titles: Local title library (defaults to config.ALL_TITLES).
        server_rules: Current rules from the qBittorrent server (None = legacy mode).

    Returns:
        A summary dictionary with:
          selected_count     — how many rules were in the selection
          matched_count      — how many matched a local title entry
          unchanged_count    — how many are already in sync
          change_count       — how many would be created/updated
          missing_count      — how many couldn't be found locally
          missing_rule_names — list of unresolvable rule names
          changes            — list of change detail dicts
    """
    desired_names = {str(name).strip() for name in selected_rule_names if str(name).strip()}
    titles = all_titles if isinstance(all_titles, dict) else getattr(config, 'ALL_TITLES', {})

    if not isinstance(titles, dict):
        titles = {}

    changes: list[dict[str, Any]] = []
    unchanged_count = 0
    matched_rule_names: set[str] = set()

    # --- Legacy mode: simple enabled-state comparison ---
    if server_rules is None:
        desired = _desired_enabled_by_rule_name(rule_rows, selected_rule_names)
        for media_type, entries in titles.items():
            if not isinstance(entries, list):
                continue
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                rule_name = str(entry.get('ruleName') or (entry.get('node') or {}).get('title') or '').strip()
                if not rule_name or rule_name not in desired:
                    continue
                matched_rule_names.add(rule_name)
                current_enabled = bool(entry.get('enabled', True))
                next_enabled = bool(desired[rule_name])
                if current_enabled == next_enabled:
                    unchanged_count += 1
                    continue
                # Build the change record with the sanitized rule definition
                rule_def = sanitize_entry_for_export(dict(entry))
                rule_def['enabled'] = next_enabled
                changes.append({
                    'rule_name': rule_name,
                    'media_type': str(media_type),
                    'index': int(idx),
                    'from_enabled': current_enabled,
                    'to_enabled': next_enabled,
                    'rule_def': rule_def,
                })
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

    # --- Full diff mode: field-by-field comparison against server rules ---
    for media_type, entries in titles.items():
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue

            rule_name = str(entry.get('ruleName') or (entry.get('node') or {}).get('title') or '').strip()
            if not rule_name or (desired_names and rule_name not in desired_names):
                continue

            matched_rule_names.add(rule_name)
            local_clean = sanitize_entry_for_export(dict(entry))

            if rule_name not in server_rules:
                # Rule doesn't exist on server yet → CREATE
                changes.append({
                    'rule_name': rule_name,
                    'media_type': str(media_type),
                    'index': int(idx),
                    'action': 'create',
                    'rule_def': local_clean,
                    'diff_details': ['New rule (does not exist on server)']
                })
            else:
                # Rule exists on server → compare fields for UPDATE
                server_rule = server_rules[rule_name]
                diffs = get_rule_diff(local_clean, server_rule)
                if diffs:
                    changes.append({
                        'rule_name': rule_name,
                        'media_type': str(media_type),
                        'index': int(idx),
                        'action': 'update',
                        'rule_def': local_clean,
                        'diff_details': diffs
                    })
                else:
                    unchanged_count += 1

    missing = sorted([name for name in desired_names if name not in matched_rule_names])
    return {
        'selected_count': len(desired_names),
        'matched_count': len(matched_rule_names),
        'unchanged_count': unchanged_count,
        'change_count': len(changes),
        'missing_count': len(missing),
        'missing_rule_names': missing,
        'changes': changes,
    }


def format_rule_sync_dry_run_text(summary: Dict[str, Any]) -> str:
    """
    Render a dry-run summary as a human-readable text block for display.

    Shows counts, missing rules (capped at 8), and planned changes (capped at 12)
    to keep the output manageable for large rule sets.

    Args:
        summary: The dry-run summary from build_rule_sync_dry_run().

    Returns:
        A formatted multi-line string.
    """
    lines = [
        'Rule Sync Dry Run',
        f"Selected: {int(summary.get('selected_count', 0) or 0)}",
        f"Matched: {int(summary.get('matched_count', 0) or 0)}",
        f"Changes: {int(summary.get('change_count', 0) or 0)}",
        f"Unchanged: {int(summary.get('unchanged_count', 0) or 0)}",
        f"Missing: {int(summary.get('missing_count', 0) or 0)}",
    ]

    # Show missing rules (rules in selection but not found in local library)
    missing = summary.get('missing_rule_names', []) or []
    if missing:
        lines.append('')
        lines.append('Missing Rules (not found in local library):')
        lines.extend([f"- {str(name)}" for name in missing[:8]])
        if len(missing) > 8:
            lines.append('- ...')

    # Show planned changes (truncated to keep output readable)
    changes = summary.get('changes', []) or []
    if changes:
        lines.append('')
        lines.append('Planned Changes:')
        for item in changes[:12]:
            rule_name = item.get('rule_name')
            action = item.get('action')
            if action:
                # Full diff mode — show action type and first 2 diffs
                diffs = item.get('diff_details', [])
                diff_text = ", ".join(diffs[:2])
                if len(diffs) > 2:
                    diff_text += ", ..."
                lines.append(f"- [{action.upper()}] {rule_name}: {diff_text}")
            else:
                # Legacy mode — show enabled state change
                lines.append(
                    f"- {rule_name}: {bool(item.get('from_enabled'))} -> {bool(item.get('to_enabled'))}"
                )
        if len(changes) > 12:
            lines.append('- ...')

    return '\n'.join(lines)


def apply_rule_sync_plan(changes: list[dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute a dry-run plan by pushing changes to the qBittorrent server.

    Each change is applied individually using QBittorrentClient.set_rule().
    If any individual rule fails, it's recorded but doesn't stop the others
    (partial-failure support).

    The result includes rollback guidance text that helps the user recover
    from partial failures.

    Args:
        changes: The 'changes' list from build_rule_sync_dry_run().

    Returns:
        A result dictionary with:
          applied_count      — how many rules were successfully pushed
          failed_count       — how many failed
          failed_rules       — list of rule names that failed
          rollback_guidance  — human-readable recovery instructions
          success            — True only if ALL rules were applied
    """
    if not changes:
        return {
            'applied_count': 0,
            'failed_count': 0,
            'failed_rules': [],
            'rollback_guidance': 'No changes to apply.',
            'success': True,
        }

    # Extract connection parameters from the global config
    protocol = str(getattr(config, 'QBT_PROTOCOL', '') or '').strip()
    host = str(getattr(config, 'QBT_HOST', '') or '').strip()
    port = str(getattr(config, 'QBT_PORT', '') or '').strip()
    username = str(getattr(config, 'QBT_USER', '') or '').strip()
    password = str(getattr(config, 'QBT_PASS', '') or '').strip()
    verify_ssl = bool(getattr(config, 'QBT_VERIFY_SSL', True))
    ca_cert = getattr(config, 'QBT_CA_CERT', None)

    # Early exit if server isn't configured
    if not host or not port:
        return {
            'applied_count': 0,
            'failed_count': len(changes),
            'failed_rules': [str(c.get('rule_name', '')) for c in changes],
            'rollback_guidance': 'qBittorrent host/port missing. Configure connection, rerun dry run, then apply again.',
            'success': False,
        }

    # Create a temporary client connection
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
        # Apply each change individually for partial-failure resilience
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
        # Connection or unexpected error — mark all remaining as failed
        failed.extend([str(c.get('rule_name', '')) for c in changes if str(c.get('rule_name', '') or '').strip()])
    finally:
        try:
            client.close()
        except Exception:
            pass  # Best-effort cleanup

    # Build context-aware rollback guidance
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
