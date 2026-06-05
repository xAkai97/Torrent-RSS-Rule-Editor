"""Tests for read-only server snapshot service helpers."""

from src.services.server_snapshot import (
    format_qbittorrent_snapshot_text,
    load_qbittorrent_snapshot,
)


def test_load_qbittorrent_snapshot_missing_host_returns_error(monkeypatch):
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PROTOCOL', 'http')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_HOST', '')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PORT', '8080')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_USER', 'user')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PASS', 'pass')

    result = load_qbittorrent_snapshot()

    assert result['success'] is False
    assert 'not configured' in result['message']


def test_load_qbittorrent_snapshot_success_counts_and_samples(monkeypatch):
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PROTOCOL', 'http')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_HOST', 'localhost')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PORT', '8080')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_USER', 'user')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_PASS', 'pass')
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_VERIFY_SSL', True)
    monkeypatch.setattr('src.services.server_snapshot.config.QBT_CA_CERT', None)

    def _cats(**_kwargs):
        return True, {'Anime': {}, 'Movies': {}}

    def _feeds(**_kwargs):
        return True, {'SubsPlease': {}, 'Nyaa': {}}

    def _rules(**_kwargs):
        return True, {'Rule A': {}, 'Rule B': {}, 'Rule C': {}}

    result = load_qbittorrent_snapshot(
        fetch_categories_fn=_cats,
        fetch_feeds_fn=_feeds,
        fetch_rules_fn=_rules,
    )

    assert result['success'] is True
    assert result['categories_count'] == 2
    assert result['feeds_count'] == 2
    assert result['rules_count'] == 3
    assert 'Anime' in result['categories_sample']


def test_format_qbittorrent_snapshot_text_includes_errors_and_counts():
    text = format_qbittorrent_snapshot_text(
        {
            'success': False,
            'message': 'Snapshot partially loaded (see section errors).',
            'categories_count': 1,
            'feeds_count': 0,
            'rules_count': 2,
            'categories_error': '',
            'feeds_error': 'connection timeout',
            'rules_error': '',
            'categories_sample': ['Anime'],
            'feeds_sample': [],
            'rules_sample': ['Rule A'],
        }
    )

    assert 'Overall Success: False' in text
    assert 'Feeds Error: connection timeout' in text
    assert 'Categories: 1' in text
    assert '- Anime' in text
