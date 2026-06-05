"""Tests for rule sync merge service extracted from Tk callback flow."""

from src.services.rule_sync import merge_existing_rule_entries


def _display_title(entry):
    if isinstance(entry, dict):
        node = entry.get('node') or {}
        return str(node.get('title') or entry.get('mustContain') or entry.get('ruleName') or '')
    return str(entry)


def _rule_name(entry):
    if isinstance(entry, dict):
        return str(entry.get('ruleName') or entry.get('name') or _display_title(entry))
    return str(entry)


def test_merge_existing_rule_entries_adds_new_and_skips_duplicates():
    current = {
        'existing': [
            {'ruleName': 'Rule A', 'mustContain': 'Rule A', 'node': {'title': 'Rule A'}},
        ]
    }
    incoming = [
        {'ruleName': 'Rule A', 'mustContain': 'Rule A', 'node': {'title': 'Rule A'}},
        {'ruleName': 'Rule B', 'mustContain': 'Rule B', 'node': {'title': 'Rule B'}},
    ]

    result = merge_existing_rule_entries(
        current_titles=current,
        incoming_entries=incoming,
        get_display_title_fn=_display_title,
        get_rule_name_fn=_rule_name,
    )

    assert result['new_entries_count'] == 1
    assert result['removed_duplicates_count'] == 0
    merged_existing = result['updated_titles']['existing']
    assert len(merged_existing) == 2


def test_merge_existing_rule_entries_final_dedup_removes_conflicts():
    current = {
        'existing': [
            {'ruleName': 'Rule A', 'mustContain': 'Rule A', 'node': {'title': 'Rule A'}},
            {'ruleName': 'Rule A', 'mustContain': 'Rule A', 'node': {'title': 'Rule A duplicate'}},
        ]
    }

    result = merge_existing_rule_entries(
        current_titles=current,
        incoming_entries=[],
        get_display_title_fn=_display_title,
        get_rule_name_fn=_rule_name,
    )

    assert result['new_entries_count'] == 0
    assert result['removed_duplicates_count'] == 1
    assert len(result['updated_titles']['existing']) == 1
