"""Tests for connection status service helpers extracted from Tk callbacks."""

from types import SimpleNamespace

from src.services.connection_status import (
    build_qbittorrent_ping_args,
    evaluate_setup_wizard_trigger,
    get_connection_status_text,
    has_online_host_port,
)


def _cfg(**overrides):
    base = {
        'CONNECTION_MODE': 'auto',
        'QBT_PROTOCOL': 'http',
        'QBT_HOST': 'localhost',
        'QBT_PORT': '8080',
        'QBT_USER': 'user',
        'QBT_PASS': 'pass',
        'QBT_VERIFY_SSL': True,
        'QBT_CA_CERT': None,
        'BOOTSTRAPPED_CONFIG': False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_get_connection_status_text_modes():
    assert get_connection_status_text(_cfg(CONNECTION_MODE='offline')) == 'Offline'
    assert get_connection_status_text(_cfg(CONNECTION_MODE='auto')) == 'Auto (will try online if available)'
    assert get_connection_status_text(_cfg(CONNECTION_MODE='online')) == 'Online: http://localhost:8080'


def test_evaluate_setup_wizard_trigger_first_bootstrap():
    should_open, text = evaluate_setup_wizard_trigger(
        config_set=True,
        config_obj=_cfg(BOOTSTRAPPED_CONFIG=True),
        config_file_exists=True,
    )
    assert should_open is True
    assert 'First launch' in text


def test_evaluate_setup_wizard_trigger_missing_config():
    should_open, text = evaluate_setup_wizard_trigger(
        config_set=False,
        config_obj=_cfg(BOOTSTRAPPED_CONFIG=False),
        config_file_exists=False,
    )
    assert should_open is True
    assert 'CRITICAL' in text


def test_build_qbittorrent_ping_args_order_and_values():
    args = build_qbittorrent_ping_args(_cfg())
    assert args == ('http', 'localhost', '8080', 'user', 'pass', True, None)


def test_has_online_host_port_checks_normalized_values():
    assert has_online_host_port(_cfg(QBT_HOST=' localhost ', QBT_PORT=' 8080 ')) is True
    assert has_online_host_port(_cfg(QBT_HOST=' ', QBT_PORT='8080')) is False
    assert has_online_host_port(_cfg(QBT_HOST='localhost', QBT_PORT='')) is False
