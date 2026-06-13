"""
Server Snapshot — Read-Only qBittorrent State Capture.

This module provides a safe, read-only way to capture the current state of
a qBittorrent server. It fetches categories, RSS feeds, and RSS rules in
one go and packages them into a structured snapshot payload.

Used by the GUI's diagnostic/debug panel to show the user what's currently
on their qBittorrent server without making any changes.

The snapshot includes:
  - Counts for each data type
  - Sample keys (first 5) for quick preview
  - Error messages for any failed fetches
  - A pre-formatted text block for display
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.api.qbittorrent import fetch_categories, fetch_feeds, fetch_rules
from src.config import config


def _as_dict(value: Any) -> Dict[str, Any]:
    """Safely cast a value to dict, returning empty dict if it's not one."""
    return value if isinstance(value, dict) else {}


def _sample_keys(data: Dict[str, Any], limit: int = 5) -> list[str]:
    """
    Get the first N sorted keys from a dictionary for preview purposes.

    Used to show a quick sample of what's in each section (e.g. first 5
    category names) without dumping the entire data set.
    """
    keys = [str(k) for k in data.keys()]
    return sorted(keys)[: max(0, int(limit))]


def load_qbittorrent_snapshot(
    fetch_categories_fn: Callable[..., tuple[bool, Any]] = fetch_categories,
    fetch_feeds_fn: Callable[..., tuple[bool, Any]] = fetch_feeds,
    fetch_rules_fn: Callable[..., tuple[bool, Any]] = fetch_rules,
) -> Dict[str, Any]:
    """
    Fetch a read-only snapshot of the qBittorrent server's current state.

    Makes three API calls (categories, feeds, rules) and packages the
    results into a normalized payload. All fetches are independent — if
    one fails, the others still succeed (partial snapshot).

    The fetch functions are passed as parameters to allow test mocking.

    Args:
        fetch_categories_fn: Function to fetch categories (default: API function).
        fetch_feeds_fn: Function to fetch RSS feeds.
        fetch_rules_fn: Function to fetch RSS rules.

    Returns:
        A snapshot dictionary containing:
          success             — True if ALL three fetches succeeded
          message             — Human-readable status summary
          categories/feeds/rules — The fetched data (empty dict on failure)
          *_error             — Error message for each failed section
          *_count             — Item count for each section
          *_sample            — First 5 sorted keys for quick preview
    """
    # Extract connection parameters from the global config
    protocol = str(getattr(config, 'QBT_PROTOCOL', '') or '').strip()
    host = str(getattr(config, 'QBT_HOST', '') or '').strip()
    port = str(getattr(config, 'QBT_PORT', '') or '').strip()
    username = str(getattr(config, 'QBT_USER', '') or '').strip()
    password = str(getattr(config, 'QBT_PASS', '') or '').strip()
    verify_ssl = bool(getattr(config, 'QBT_VERIFY_SSL', True))
    ca_cert = getattr(config, 'QBT_CA_CERT', None)

    # Early exit if no server is configured
    if not host or not port:
        return {
            'success': False,
            'message': 'qBittorrent host/port is not configured.',
            'categories': {},
            'feeds': {},
            'rules': {},
        }

    # Fetch all three sections independently
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

    # Normalize results (use empty dict on failure)
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
    """
    Render a snapshot payload as a human-readable text block.

    Used by the GUI to display the snapshot in a read-only text area.
    Shows counts, errors (if any), and sample keys for each section.

    Args:
        snapshot: The snapshot dictionary from load_qbittorrent_snapshot().

    Returns:
        A formatted multi-line string ready for display.
    """
    lines = [
        'qBittorrent Read-Only Snapshot',
        f"Status: {str(snapshot.get('message', '') or '')}",
        f"Overall Success: {bool(snapshot.get('success', False))}",
        '',
        f"Categories: {int(snapshot.get('categories_count', 0) or 0)}",
        f"Feeds: {int(snapshot.get('feeds_count', 0) or 0)}",
        f"Rules: {int(snapshot.get('rules_count', 0) or 0)}",
    ]

    # Show errors if any section failed
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

    # Show sample keys for each section
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
