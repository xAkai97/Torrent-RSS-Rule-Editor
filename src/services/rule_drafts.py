"""
Rule Draft Helpers — In-Memory Rule Editing State.

When the user edits rule properties in the Qt GUI (like toggling enabled/disabled),
those changes are "drafts" that live only in the GUI until the user saves them.
This module provides helpers to commit those draft edits back into the in-memory
ALL_TITLES data structure.

Key concept: No server communication happens here. These functions only modify
the local in-memory state. To push changes to qBittorrent, use rule_sync_apply.py.
"""

from __future__ import annotations

from typing import Any, Dict

from src.config import config
from src.utils import get_display_title, get_rule_name


def _to_enabled(value: Any) -> bool:
    """
    Convert various enabled/disabled representations to a Python bool.

    Handles strings like "yes", "true", "1", "enabled" and their
    negative counterparts. Anything else falls back to Python's bool().

    Args:
        value: The value to interpret (string, bool, int, etc.)

    Returns:
        True if the value represents "enabled", False otherwise.
    """
    text = str(value or '').strip().lower()
    if text in {'yes', 'true', '1', 'enabled'}:
        return True
    if text in {'no', 'false', '0', 'disabled'}:
        return False
    return bool(value)


def commit_rule_enabled_drafts_to_local_titles(
    rule_rows: list[dict[str, str]],
    all_titles: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """
    Apply enabled/disabled draft changes from the rules table into ALL_TITLES.

    The Qt rules table lets users toggle rules on/off. When they save, this
    function takes those draft states and applies them to the in-memory
    title entries.

    Matching is fuzzy — it tries multiple fields (ruleName, display title,
    mustContain, name) to find the right entry, because entries can come from
    different sources with different field naming.

    Args:
        rule_rows: List of row dicts from the Qt rules table. Each must have
                   'rule_name' (str) and 'enabled' (str/bool) keys.
        all_titles: Optional titles map to modify. Defaults to config.ALL_TITLES.

    Returns:
        A stats dictionary with:
          updated_count         — how many entries had their enabled state changed
          matched_count         — how many rule_rows were matched to entries
          requested_count       — total number of rule_rows provided
          unresolved_rule_names — rule_rows that couldn't be matched to any entry
    """
    target_titles = all_titles if isinstance(all_titles, dict) else getattr(config, 'ALL_TITLES', {})
    if not isinstance(target_titles, dict):
        return {
            'updated_count': 0,
            'matched_count': 0,
            'requested_count': 0,
            'unresolved_rule_names': [],
        }

    # Build a lookup: rule_name → desired enabled state
    desired_by_name: dict[str, bool] = {}
    for row in rule_rows or []:
        rule_name = str((row or {}).get('rule_name', '') or '').strip()
        if not rule_name:
            continue
        desired_by_name[rule_name] = _to_enabled((row or {}).get('enabled', ''))

    if not desired_by_name:
        return {
            'updated_count': 0,
            'matched_count': 0,
            'requested_count': 0,
            'unresolved_rule_names': [],
        }

    updated_count = 0
    matched_rule_names: set[str] = set()

    # Walk through all title entries and try to match them to draft rows
    for _, entries in target_titles.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            # Collect all possible names for this entry to try matching against
            candidate_names = {
                str(get_rule_name(entry, '') or '').strip(),
                str(get_display_title(entry, '') or '').strip(),
                str(entry.get('mustContain', '') or '').strip(),
                str(entry.get('ruleName', '') or '').strip(),
                str(entry.get('name', '') or '').strip(),
            }
            candidate_names = {name for name in candidate_names if name}

            # Try to find a match between this entry's names and the draft rows
            hit = None
            for candidate in candidate_names:
                if candidate in desired_by_name:
                    hit = candidate
                    break

            if not hit:
                continue

            # Apply the draft change if the enabled state actually changed
            matched_rule_names.add(hit)
            new_enabled = bool(desired_by_name[hit])
            old_enabled = bool(entry.get('enabled', True))
            if old_enabled != new_enabled:
                entry['enabled'] = new_enabled
                updated_count += 1

    # Report which draft rows couldn't be matched to any entry
    unresolved = sorted([name for name in desired_by_name.keys() if name not in matched_rule_names])
    return {
        'updated_count': updated_count,
        'matched_count': len(matched_rule_names),
        'requested_count': len(desired_by_name),
        'unresolved_rule_names': unresolved,
    }
