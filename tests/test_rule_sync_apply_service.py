"""Tests for controlled rule sync dry-run/apply services."""

from src.services import rule_sync_apply


def test_build_rule_sync_dry_run_detects_changes_and_missing():
    all_titles = {
        'existing': [
            {'ruleName': 'Rule A', 'enabled': False, 'mustContain': 'Rule A', 'node': {'title': 'Rule A'}},
        ]
    }
    rows = [
        {'rule_name': 'Rule A', 'enabled': 'Yes'},
        {'rule_name': 'Rule Missing', 'enabled': 'No'},
    ]

    summary = rule_sync_apply.build_rule_sync_dry_run(rows, ['Rule A', 'Rule Missing'], all_titles=all_titles)

    assert summary['change_count'] == 1
    assert summary['missing_count'] == 1
    assert summary['missing_rule_names'] == ['Rule Missing']


def test_format_rule_sync_dry_run_text_contains_sections():
    text = rule_sync_apply.format_rule_sync_dry_run_text(
        {
            'selected_count': 2,
            'matched_count': 1,
            'change_count': 1,
            'unchanged_count': 0,
            'missing_count': 1,
            'missing_rule_names': ['Rule Missing'],
            'changes': [{'rule_name': 'Rule A', 'from_enabled': False, 'to_enabled': True}],
        }
    )

    assert 'Rule Sync Dry Run' in text
    assert 'Missing Rules:' in text
    assert 'Planned Changes:' in text


class _FakeClient:
    def __init__(self, **_kwargs):
        self.closed = False

    def connect(self):
        return True

    def set_rule(self, rule_name, _rule_def):
        return rule_name != 'Rule Fail'

    def close(self):
        self.closed = True


def test_apply_rule_sync_plan_partial_failure(monkeypatch):
    monkeypatch.setattr(rule_sync_apply, 'QBittorrentClient', _FakeClient)
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_PROTOCOL', 'http')
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_HOST', 'localhost')
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_PORT', '8080')
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_USER', 'user')
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_PASS', 'pass')
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_VERIFY_SSL', True)
    monkeypatch.setattr(rule_sync_apply.config, 'QBT_CA_CERT', None)

    result = rule_sync_apply.apply_rule_sync_plan(
        [
            {'rule_name': 'Rule OK', 'rule_def': {'enabled': True}},
            {'rule_name': 'Rule Fail', 'rule_def': {'enabled': False}},
        ]
    )

    assert result['applied_count'] == 1
    assert result['failed_count'] == 1
    assert result['success'] is False
    assert 'Partial apply failure' in result['rollback_guidance']
