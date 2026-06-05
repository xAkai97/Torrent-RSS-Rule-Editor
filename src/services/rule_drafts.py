"""Local draft rule write helpers.

These helpers apply Qt draft edits to in-memory application data only.
No remote API synchronization is performed here.
"""

from __future__ import annotations

from typing import Any, Dict

from src.config import config
from src.utils import get_display_title, get_rule_name


def _to_enabled(value: Any) -> bool:
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
    """Commit rule enabled-state drafts into local ALL_TITLES.

    Args:
        rule_rows: Qt rules-table rows containing ``rule_name`` and ``enabled``.
        all_titles: Optional titles map; defaults to ``config.ALL_TITLES``.

    Returns:
        Dict with counts and unresolved rule names.
    """
    target_titles = all_titles if isinstance(all_titles, dict) else getattr(config, 'ALL_TITLES', {})
    if not isinstance(target_titles, dict):
        return {
            'updated_count': 0,
            'matched_count': 0,
            'requested_count': 0,
            'unresolved_rule_names': [],
        }

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

    for _, entries in target_titles.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            candidate_names = {
                str(get_rule_name(entry, '') or '').strip(),
                str(get_display_title(entry, '') or '').strip(),
                str(entry.get('mustContain', '') or '').strip(),
                str(entry.get('ruleName', '') or '').strip(),
                str(entry.get('name', '') or '').strip(),
            }
            candidate_names = {name for name in candidate_names if name}

            hit = None
            for candidate in candidate_names:
                if candidate in desired_by_name:
                    hit = candidate
                    break

            if not hit:
                continue

            matched_rule_names.add(hit)
            new_enabled = bool(desired_by_name[hit])
            old_enabled = bool(entry.get('enabled', True))
            if old_enabled != new_enabled:
                entry['enabled'] = new_enabled
                updated_count += 1

    unresolved = sorted([name for name in desired_by_name.keys() if name not in matched_rule_names])
    return {
        'updated_count': updated_count,
        'matched_count': len(matched_rule_names),
        'requested_count': len(desired_by_name),
        'unresolved_rule_names': unresolved,
    }
