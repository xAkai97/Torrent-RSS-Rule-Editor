"""
Deluge Web API integration.

Provides a minimal JSON-RPC client for Deluge WebUI and a rule-sync storage
layer used by this application.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class DelugeClient:
    """Minimal Deluge Web JSON-RPC client wrapper."""

    def __init__(
        self,
        protocol: str,
        host: str,
        port: str,
        password: str,
        verify_ssl: bool = True,
        timeout: int = 12,
    ):
        self.protocol = (protocol or 'http').strip().lower() or 'http'
        self.host = (host or 'localhost').strip() or 'localhost'
        self.port = str(port or '8112').strip() or '8112'
        self.password = (password or '').strip()
        self.verify_ssl = bool(verify_ssl)
        self.timeout = int(timeout)

        self.base_url = f"{self.protocol}://{self.host}:{self.port}"
        self.rpc_url = f"{self.base_url}/json"
        self.session = requests.Session()
        self._request_id = 0

    def _rpc(self, method: str, params: Optional[list] = None) -> Any:
        """Execute a Deluge JSON-RPC call and return the result."""
        self._request_id += 1
        payload = {
            'method': method,
            'params': params or [],
            'id': self._request_id,
        }
        response = self.session.post(
            self.rpc_url,
            json=payload,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        if data.get('error'):
            raise RuntimeError(str(data.get('error')))
        return data.get('result')

    def connect(self) -> bool:
        """Authenticate to Deluge Web and connect to daemon if needed."""
        auth_ok = self._rpc('auth.login', [self.password])
        if not auth_ok:
            raise RuntimeError('Deluge authentication failed')

        try:
            is_connected = self._rpc('web.connected', [])
            if not is_connected:
                hosts = self._rpc('web.get_hosts', []) or []
                if hosts:
                    host_id = hosts[0][0]
                    self._rpc('web.connect', [host_id])
        except Exception as e:
            logger.warning('Deluge daemon connect check failed: %s', e)

        return True

    def get_version(self) -> str:
        """Return Deluge daemon version if available."""
        try:
            version = self._rpc('daemon.info', [])
            return str(version or 'unknown')
        except Exception:
            return 'unknown'

    def get_synced_rules(self) -> Dict[str, Any]:
        """
        Retrieve previously synced rules from Deluge config storage.

        Rules are stored under core config key: qbrss_rules_store.
        """
        cfg = self._rpc('core.get_config', []) or {}
        raw = cfg.get('qbrss_rules_store', '')
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    def sync_rules(self, rules_dict: Dict[str, Any], mode: str = 'replace') -> Tuple[int, int]:
        """
        Sync rules into Deluge config-backed store.

        Args:
            rules_dict: Generated rules payload
            mode: 'replace' or 'add'

        Returns:
            Tuple of (success_count, failed_count)
        """
        existing = self.get_synced_rules()

        if mode == 'add':
            merged = dict(existing)
            merged.update(rules_dict or {})
            to_store = merged
        else:
            to_store = dict(rules_dict or {})

        # Store as JSON text for robust Deluge serialization compatibility.
        self._rpc('core.set_config', [{'qbrss_rules_store': json.dumps(to_store)}])

        success_count = len(to_store)
        failed_count = 0
        return success_count, failed_count


def ping_deluge(protocol: str, host: str, port: str, password: str, verify_ssl: bool = True) -> Tuple[bool, str]:
    """Test Deluge connection and return status."""
    try:
        client = DelugeClient(protocol, host, port, password, verify_ssl)
        client.connect()
        version = client.get_version()
        return True, f'Deluge connected ({version})'
    except Exception as e:
        return False, str(e)
