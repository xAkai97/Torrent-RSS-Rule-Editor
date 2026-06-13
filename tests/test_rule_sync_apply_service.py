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
    assert 'Missing Rules (not found in local library):' in text
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


def test_build_rule_sync_dry_run_full_field_comparison():
    all_titles = {
        'anime': [
            {
                'ruleName': 'Rule Exist Unchanged',
                'enabled': True,
                'mustContain': 'Show A',
                'node': {'title': 'Rule Exist Unchanged'},
            },
            {
                'ruleName': 'Rule Exist Updated',
                'enabled': True,
                'mustContain': 'Show B Modified',
                'node': {'title': 'Rule Exist Updated'},
                'savePath': 'New Path',
            },
            {
                'ruleName': 'Rule New',
                'enabled': False,
                'mustContain': 'Show C',
                'node': {'title': 'Rule New'},
            },
        ]
    }

    server_rules = {
        'Rule Exist Unchanged': {
            'enabled': True,
            'mustContain': 'Show A',
        },
        'Rule Exist Updated': {
            'enabled': True,
            'mustContain': 'Show B',
            'savePath': 'Old Path',
        },
    }

    selected_rule_names = ['Rule Exist Unchanged', 'Rule Exist Updated', 'Rule New']
    rule_rows = [
        {'rule_name': 'Rule Exist Unchanged'},
        {'rule_name': 'Rule Exist Updated'},
        {'rule_name': 'Rule New'},
    ]

    summary = rule_sync_apply.build_rule_sync_dry_run(
        rule_rows=rule_rows,
        selected_rule_names=selected_rule_names,
        all_titles=all_titles,
        server_rules=server_rules,
    )

    assert summary['selected_count'] == 3
    assert summary['matched_count'] == 3
    assert summary['unchanged_count'] == 1
    assert summary['change_count'] == 2

    changes = {c['rule_name']: c for c in summary['changes']}

    # Rule New should be CREATE
    assert 'Rule New' in changes
    assert changes['Rule New']['action'] == 'create'
    assert 'New rule' in changes['Rule New']['diff_details'][0]

    # Rule Exist Updated should be UPDATE
    assert 'Rule Exist Updated' in changes
    assert changes['Rule Exist Updated']['action'] == 'update'
    assert len(changes['Rule Exist Updated']['diff_details']) > 0

