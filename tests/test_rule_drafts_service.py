"""Tests for local rule draft commit service."""

from src.services.rule_drafts import commit_rule_enabled_drafts_to_local_titles


def test_commit_rule_enabled_drafts_updates_matching_entries_only():
    all_titles = {
        'existing': [
            {'ruleName': 'Rule A', 'enabled': False, 'node': {'title': 'Rule A'}},
            {'ruleName': 'Rule B', 'enabled': True, 'node': {'title': 'Rule B'}},
        ]
    }

    result = commit_rule_enabled_drafts_to_local_titles(
        [
            {'rule_name': 'Rule A', 'enabled': 'Yes'},
            {'rule_name': 'Rule B', 'enabled': 'No'},
        ],
        all_titles=all_titles,
    )

    assert result['updated_count'] == 2
    assert result['matched_count'] == 2
    assert result['requested_count'] == 2
    assert result['unresolved_rule_names'] == []
    assert all_titles['existing'][0]['enabled'] is True
    assert all_titles['existing'][1]['enabled'] is False


def test_commit_rule_enabled_drafts_reports_unresolved_names():
    all_titles = {
        'existing': [
            {'ruleName': 'Rule A', 'enabled': False, 'node': {'title': 'Rule A'}},
        ]
    }

    result = commit_rule_enabled_drafts_to_local_titles(
        [
            {'rule_name': 'Missing Rule', 'enabled': 'Yes'},
        ],
        all_titles=all_titles,
    )

    assert result['updated_count'] == 0
    assert result['matched_count'] == 0
    assert result['requested_count'] == 1
    assert result['unresolved_rule_names'] == ['Missing Rule']


def test_commit_rule_enabled_drafts_handles_empty_rows():
    all_titles = {'existing': [{'ruleName': 'Rule A', 'enabled': False, 'node': {'title': 'Rule A'}}]}

    result = commit_rule_enabled_drafts_to_local_titles([], all_titles=all_titles)

    assert result['updated_count'] == 0
    assert result['matched_count'] == 0
    assert result['requested_count'] == 0
    assert result['unresolved_rule_names'] == []
    assert all_titles['existing'][0]['enabled'] is False
