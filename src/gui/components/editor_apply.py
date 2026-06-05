"""Editor apply helpers for setup_editor_panel."""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple


def editor_has_changes(
    entry: Any,
    original_title: str,
    new_title: str,
    new_must: str,
    new_save: str,
    new_cat: str,
    new_enabled: bool,
) -> bool:
    """Return True when editor values differ from current entry values."""
    try:
        old_title = str(original_title or '')
        old_must = entry.get('mustContain', '') if isinstance(entry, dict) else ''
        old_save = entry.get('savePath', '') if isinstance(entry, dict) else ''
        old_cat = entry.get('assignedCategory', '') if isinstance(entry, dict) else ''
        old_enabled = entry.get('enabled', True) if isinstance(entry, dict) else True
    except Exception:
        return True

    return not (
        new_title == old_title
        and new_must == old_must
        and new_save == old_save
        and new_cat == old_cat
        and bool(new_enabled) == bool(old_enabled)
    )


def parse_lastmatch_input(raw_value: str) -> Tuple[Any, str | None]:
    """Parse editor lastMatch input and return (value, error_message_if_json_invalid)."""
    text = str(raw_value or '').strip()
    if not text:
        return '', None

    if text.startswith('{') or text.startswith('[') or text.startswith('"'):
        try:
            return json.loads(text), None
        except Exception as e:
            return text, str(e)

    return text, None


def apply_editor_values_to_entry(
    entry: Any,
    new_title: str,
    new_must: str,
    new_save: str,
    new_cat: str,
    new_enabled: bool,
    lastmatch_value: Any,
) -> Dict[str, Any]:
    """Apply editor values to entry and return normalized dict entry."""
    if not isinstance(entry, dict):
        entry = {'node': {'title': new_title}}

    entry['mustContain'] = new_must or new_title
    entry['savePath'] = new_save
    entry['assignedCategory'] = new_cat
    entry['enabled'] = bool(new_enabled)

    if 'torrentParams' not in entry or not isinstance(entry.get('torrentParams'), dict):
        entry['torrentParams'] = {}
    entry['torrentParams']['category'] = new_cat
    entry['torrentParams']['save_path'] = new_save

    entry['lastMatch'] = lastmatch_value
    node = entry.get('node') or {}
    node['title'] = new_title
    entry['node'] = node
    return entry
