"""Read-only server snapshot helpers.

This service collects lightweight qBittorrent state (categories, feeds, rules)
using existing API wrappers so UI layers can display diagnostics safely.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.api.qbittorrent import fetch_categories, fetch_feeds, fetch_rules
from src.config import config


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sample_keys(data: Dict[str, Any], limit: int = 5) -> list[str]:
    keys = [str(k) for k in data.keys()]
    return sorted(keys)[: max(0, int(limit))]


def load_qbittorrent_snapshot(
    fetch_categories_fn: Callable[..., tuple[bool, Any]] = fetch_categories,
    fetch_feeds_fn: Callable[..., tuple[bool, Any]] = fetch_feeds,
    fetch_rules_fn: Callable[..., tuple[bool, Any]] = fetch_rules,
) -> Dict[str, Any]:
    """Fetch read-only qBittorrent snapshot and return normalized status payload."""
    protocol = str(getattr(config, 'QBT_PROTOCOL', '') or '').strip()
    host = str(getattr(config, 'QBT_HOST', '') or '').strip()
    port = str(getattr(config, 'QBT_PORT', '') or '').strip()
    username = str(getattr(config, 'QBT_USER', '') or '').strip()
    password = str(getattr(config, 'QBT_PASS', '') or '').strip()
    verify_ssl = bool(getattr(config, 'QBT_VERIFY_SSL', True))
    ca_cert = getattr(config, 'QBT_CA_CERT', None)

    if not host or not port:
        return {
            'success': False,
            'message': 'qBittorrent host/port is not configured.',
            'categories': {},
            'feeds': {},
            'rules': {},
        }

    cat_ok, cat_data = fetch_categories_fn(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        ca_cert=ca_cert,
    )
    feed_ok, feed_data = fetch_feeds_fn(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        ca_cert=ca_cert,
    )
    rules_ok, rules_data = fetch_rules_fn(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        ca_cert=ca_cert,
    )

    categories = _as_dict(cat_data) if cat_ok else {}
    feeds = _as_dict(feed_data) if feed_ok else {}
    rules = _as_dict(rules_data) if rules_ok else {}

    success = bool(cat_ok and feed_ok and rules_ok)
    message = 'Snapshot loaded.' if success else 'Snapshot partially loaded (see section errors).'

    return {
        'success': success,
        'message': message,
        'categories': categories,
        'feeds': feeds,
        'rules': rules,
        'categories_error': '' if cat_ok else str(cat_data),
        'feeds_error': '' if feed_ok else str(feed_data),
        'rules_error': '' if rules_ok else str(rules_data),
        'categories_count': len(categories),
        'feeds_count': len(feeds),
        'rules_count': len(rules),
        'categories_sample': _sample_keys(categories),
        'feeds_sample': _sample_keys(feeds),
        'rules_sample': _sample_keys(rules),
    }


def format_qbittorrent_snapshot_text(snapshot: Dict[str, Any]) -> str:
    """Render a readable text block from snapshot payload."""
    lines = [
        'qBittorrent Read-Only Snapshot',
        f"Status: {str(snapshot.get('message', '') or '')}",
        f"Overall Success: {bool(snapshot.get('success', False))}",
        '',
        f"Categories: {int(snapshot.get('categories_count', 0) or 0)}",
        f"Feeds: {int(snapshot.get('feeds_count', 0) or 0)}",
        f"Rules: {int(snapshot.get('rules_count', 0) or 0)}",
    ]

    cat_error = str(snapshot.get('categories_error', '') or '')
    feeds_error = str(snapshot.get('feeds_error', '') or '')
    rules_error = str(snapshot.get('rules_error', '') or '')
    if cat_error or feeds_error or rules_error:
        lines.extend([
            '',
            f"Category Error: {cat_error or '-'}",
            f"Feeds Error: {feeds_error or '-'}",
            f"Rules Error: {rules_error or '-'}",
        ])

    for label, sample_key in (
        ('Category Sample', 'categories_sample'),
        ('Feed Sample', 'feeds_sample'),
        ('Rule Sample', 'rules_sample'),
    ):
        sample = snapshot.get(sample_key) or []
        if sample:
            lines.append('')
            lines.append(f'{label}:')
            lines.extend([f'- {str(item)}' for item in sample])

    return '\n'.join(lines)
