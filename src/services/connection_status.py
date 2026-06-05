"""Connection status and qBittorrent ping helpers.

These helpers keep connection-mode and ping payload logic outside Tk callbacks
so fallback GUI code can stay thinner and easier to retire.
"""

from __future__ import annotations

from typing import Any, Tuple


def get_connection_status_text(config_obj: Any) -> str:
    """Return status text for current connection mode."""
    mode = str(getattr(config_obj, 'CONNECTION_MODE', '') or '').strip().lower()
    if mode == 'online':
        return (
            f"Online: {getattr(config_obj, 'QBT_PROTOCOL', '')}://"
            f"{getattr(config_obj, 'QBT_HOST', '')}:{getattr(config_obj, 'QBT_PORT', '')}"
        )
    if mode == 'offline':
        return 'Offline'
    if mode == 'auto':
        return 'Auto (will try online if available)'
    return f"Mode: {mode or 'unknown'}"


def evaluate_setup_wizard_trigger(config_set: bool, config_obj: Any, config_file_exists: bool) -> tuple[bool, str]:
    """Return (should_open, status_message) for setup wizard trigger."""
    first_run_bootstrap = bool(getattr(config_obj, 'BOOTSTRAPPED_CONFIG', False))
    if first_run_bootstrap:
        return True, '🧭 First launch detected. Opening Setup Wizard...'

    if (not config_set) and (not config_file_exists):
        return True, '🚨 CRITICAL: Please set qBittorrent credentials in Settings.'

    return False, ''


def build_qbittorrent_ping_args(config_obj: Any) -> Tuple[str, str, str, str, str, bool, Any]:
    """Build normalized qBittorrent ping argument tuple."""
    return (
        getattr(config_obj, 'QBT_PROTOCOL', ''),
        getattr(config_obj, 'QBT_HOST', ''),
        str(getattr(config_obj, 'QBT_PORT', '') or ''),
        getattr(config_obj, 'QBT_USER', '') or '',
        getattr(config_obj, 'QBT_PASS', '') or '',
        bool(getattr(config_obj, 'QBT_VERIFY_SSL', True)),
        getattr(config_obj, 'QBT_CA_CERT', None),
    )


def has_online_host_port(config_obj: Any) -> bool:
    """Return True if host/port are present for online ping attempts."""
    host = getattr(config_obj, 'QBT_HOST', '') or ''
    port = getattr(config_obj, 'QBT_PORT', '') or ''
    host_text = str(host).strip() if isinstance(host, str) else str(host or '').strip()
    port_text = str(port).strip() if port else ''
    return bool(host_text and port_text)
