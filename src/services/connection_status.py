"""
Connection Status Helpers.

Provides pure functions for building connection status display text, deciding
whether to show the Setup Wizard on launch, and extracting qBittorrent ping
parameters from the config object.

These helpers are extracted from the GUI layer so the display logic can be
tested independently and reused across different GUI implementations
(Qt main window, Tk fallback, etc.).
"""

from __future__ import annotations

from typing import Any, Tuple


def get_connection_status_text(config_obj: Any) -> str:
    """
    Build a human-readable status string for the current connection mode.

    Examples:
      - "Online: http://localhost:8080"
      - "Offline"
      - "Auto (will try online if available)"

    Args:
        config_obj: The AppConfig instance (uses CONNECTION_MODE, QBT_PROTOCOL,
                    QBT_HOST, QBT_PORT attributes).

    Returns:
        A display-ready status string.
    """
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
    """
    Decide whether the Setup Wizard should open automatically on launch.

    The wizard opens in two cases:
      1. First launch ever (BOOTSTRAPPED_CONFIG flag is set) — guide the user
         through initial server setup.
      2. Config is missing AND no config file exists on disk — something is
         very wrong and the user needs to re-enter credentials.

    Args:
        config_set: Whether load_config() returned True (valid host + port).
        config_obj: The AppConfig instance.
        config_file_exists: Whether config.ini exists on disk.

    Returns:
        A tuple of (should_open_wizard: bool, status_message: str).
    """
    first_run_bootstrap = bool(getattr(config_obj, 'BOOTSTRAPPED_CONFIG', False))
    if first_run_bootstrap:
        return True, '🧭 First launch detected. Opening Setup Wizard...'

    if (not config_set) and (not config_file_exists):
        return True, '🚨 CRITICAL: Please set qBittorrent credentials in Settings.'

    return False, ''


def build_qbittorrent_ping_args(config_obj: Any) -> Tuple[str, str, str, str, str, bool, Any]:
    """
    Extract qBittorrent connection parameters from config into a tuple.

    This is used to pass connection details to the ping/test-connection
    function without passing the entire config object.

    Args:
        config_obj: The AppConfig instance.

    Returns:
        A tuple of (protocol, host, port, username, password, verify_ssl, ca_cert).
    """
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
    """
    Check if the config has non-empty host and port values.

    Used as a quick pre-check before attempting a server ping — if there's
    no host or port configured, there's no point trying to connect.

    Args:
        config_obj: The AppConfig instance.

    Returns:
        True if both host and port are non-empty strings.
    """
    host = getattr(config_obj, 'QBT_HOST', '') or ''
    port = getattr(config_obj, 'QBT_PORT', '') or ''
    host_text = str(host).strip() if isinstance(host, str) else str(host or '').strip()
    port_text = str(port).strip() if port else ''
    return bool(host_text and port_text)
