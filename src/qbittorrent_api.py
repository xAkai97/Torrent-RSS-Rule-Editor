"""
qBittorrent API Integration Module

This module provides a clean interface to qBittorrent's WebUI API.
It handles authentication, connection management, and all API operations
needed for RSS rule management.

Phase 4: qBittorrent Integration
"""
# Standard library imports
import logging
import sys
import typing
import warnings
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple, Union

# Third-party imports
import requests
import urllib3
from requests.auth import HTTPBasicAuth

# Local application imports
from src.config import config
from src.constants import QBittorrentError

# Suppress SSL warnings when verify_ssl is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Try to import qbittorrentapi, fall back to requests if not available
try:
    from qbittorrentapi import APIConnectionError, Client, Conflict409Error
    HAS_QBT_API = True
except ImportError as e:
    HAS_QBT_API = False
    logger.warning(
        "qbittorrentapi not available, using requests fallback. "
        "Import error: %s | interpreter: %s",
        e,
        sys.executable,
    )
    
    # Define fallback exceptions
    class APIConnectionError(Exception):
        """Raised when connection to qBittorrent API fails."""
        pass
    
    class Conflict409Error(Exception):
        """Raised when a 409 Conflict occurs (e.g., duplicate RSS feed)."""
        pass


# API Endpoints
QBT_API_BASE = "/api/v2"
QBT_AUTH_LOGIN = f"{QBT_API_BASE}/auth/login"
QBT_APP_VERSION = f"{QBT_API_BASE}/app/version"
QBT_APP_PREFERENCES = f"{QBT_API_BASE}/app/preferences"
QBT_TORRENTS_CATEGORIES = f"{QBT_API_BASE}/torrents/categories"
QBT_RSS_FEEDS = f"{QBT_API_BASE}/rss/items"
QBT_RSS_ADD_FEED = f"{QBT_API_BASE}/rss/addFeed"
QBT_RSS_SET_RULE = f"{QBT_API_BASE}/rss/setRule"
QBT_RSS_REMOVE_RULE = f"{QBT_API_BASE}/rss/removeRule"
QBT_RSS_RULES = f"{QBT_API_BASE}/rss/rules"


def _normalize_connection_parts(protocol: str, host: str, port: str) -> Tuple[str, str, str]:
    """Normalize connection fields and support full URL input in host field."""
    proto = (protocol or 'http').strip().lower()
    raw_host = (host or '').strip()
    raw_port = str(port or '').strip()

    # Accept protocol values like "https://" and normalize to "https"
    if proto.endswith('://'):
        proto = proto[:-3]
    if proto not in ('http', 'https'):
        proto = 'http'

    normalized_host = raw_host
    normalized_port = raw_port

    # Support host entered as full URL, e.g. "http://192.168.1.10:8080/"
    if raw_host and '://' in raw_host:
        parsed = urlparse(raw_host)
        parsed_scheme = (parsed.scheme or '').lower()
        parsed_host = parsed.hostname or ''
        parsed_port = parsed.port

        if parsed_scheme in ('http', 'https'):
            proto = parsed_scheme
        if parsed_host:
            normalized_host = parsed_host
        if parsed_port and not normalized_port:
            normalized_port = str(parsed_port)

    # Support host entered as "hostname:port" without scheme
    elif raw_host and ':' in raw_host and raw_host.count(':') == 1:
        host_part, port_part = raw_host.split(':', 1)
        host_part = host_part.strip().rstrip('/')
        port_part = port_part.strip()
        if host_part:
            normalized_host = host_part
        if port_part and not normalized_port:
            normalized_port = port_part

    normalized_host = normalized_host.rstrip('/').strip()

    return proto, normalized_host, normalized_port


class QBittorrentClient:
    """
    Wrapper for qBittorrent API client with connection management.
    
    Provides a unified interface whether using qbittorrentapi library
    or falling back to raw requests.
    """
    
    def __init__(self, protocol: str, host: str, port: str, 
                 username: str, password: str, verify_ssl: bool = True,
                 ca_cert: Optional[str] = None, timeout: Optional[int] = None):
        """
        Initialize qBittorrent client.
        
        Args:
            protocol: 'http' or 'https'
            host: qBittorrent host address
            port: qBittorrent WebUI port
            username: WebUI username
            password: WebUI password
            verify_ssl: Whether to verify SSL certificates
            ca_cert: Optional path to CA certificate file
            timeout: Request timeout in seconds (defaults to NetworkConfig.DEFAULT_TIMEOUT)
        """
        from src.constants import NetworkConfig
        self.protocol, self.host, self.port = _normalize_connection_parts(protocol, host, port)
        self.username = username.strip()
        self.password = password.strip()
        self.verify_ssl = verify_ssl
        self.ca_cert = ca_cert
        self.timeout = timeout if timeout is not None else NetworkConfig.DEFAULT_TIMEOUT
        
        self.base_url = f"{self.protocol}://{self.host}:{self.port}"
        
        # SSL verification parameter
        self.verify_param = False if not verify_ssl else (ca_cert if ca_cert else verify_ssl)
        
        logger.debug(f"QBittorrentClient initialized: verify_ssl={verify_ssl}, ca_cert={ca_cert}, verify_param={self.verify_param}")
        
        self._client = None
        self._session = None

    @staticmethod
    def _normalize_connection_parts(protocol: str, host: str, port: str) -> Tuple[str, str, str]:
        return _normalize_connection_parts(protocol, host, port)
        
    def _get_verify_param(self) -> Union[bool, str]:
        """Get SSL verification parameter."""
        return self.verify_param
    
    def connect(self) -> bool:
        """
        Establish connection to qBittorrent.
        
        Returns:
            bool: True if connection successful
            
        Raises:
            APIConnectionError: If connection fails
            QBittorrentError: If authentication fails
        """
        if HAS_QBT_API:
            return self._connect_with_library()
        else:
            return self._connect_with_requests()
    
    def _connect_with_library(self) -> bool:
        """Connect using qbittorrentapi library."""
        try:
            self._client = Client(
                host=self.base_url,
                username=self.username,
                password=self.password,
                VERIFY_WEBUI_CERTIFICATE=self.verify_param
            )
            self._client.auth_log_in()
            logger.info(f"Connected to qBittorrent at {self.base_url}")
            return True
        except TypeError:
            # Fallback: try without certificate parameter, then set session verify manually
            self._client = Client(
                host=self.base_url,
                username=self.username,
                password=self.password
            )
            # Manually disable SSL verification if needed
            if not self.verify_ssl:
                for attr in ('_http_session', '_session', 'http_session', 'session'):
                    sess = getattr(self._client, attr, None)
                    if sess and hasattr(sess, 'verify'):
                        sess.verify = False
                        logger.debug(f"Disabled SSL verification via {attr}")
                        break
            self._client.auth_log_in()
            logger.info(f"Connected to qBittorrent at {self.base_url} (fallback mode)")
            return True
    
    def _connect_with_requests(self) -> bool:
        """Connect using raw requests."""
        self._session = requests.Session()
        login_url = f"{self.base_url}{QBT_AUTH_LOGIN}"
        
        logger.debug(f"Connecting to {login_url} with verify={self.verify_param}")
        
        response = self._session.post(
            login_url,
            data={'username': self.username, 'password': self.password},
            timeout=self.timeout,
            verify=self.verify_param
        )
        
        if response.status_code == 200 and response.text.strip().lower() == 'ok':
            logger.info(f"Connected to qBittorrent at {self.base_url} (requests)")
            return True
        
        raise QBittorrentError(f"Authentication failed: {response.text}")
    
    def get_version(self) -> str:
        """
        Get qBittorrent version.
        
        Returns:
            str: Version string
        """
        if self._client:
            return self._client.app_version()
        
        if self._session:
            url = f"{self.base_url}{QBT_APP_VERSION}"
            response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
            if response.status_code == 200:
                return response.text.strip()
        
        return "unknown"
    
    def get_preferences(self) -> Dict[str, Any]:
        """
        Get qBittorrent application preferences/settings.
        
        Returns:
            dict: Preferences dictionary containing settings like save_path
        """
        if self._client:
            if hasattr(self._client, 'app_preferences'):
                return self._client.app_preferences() or {}
            elif hasattr(self._client, 'preferences'):
                return self._client.preferences() or {}
        
        if self._session:
            url = f"{self.base_url}{QBT_APP_PREFERENCES}"
            try:
                response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
                if response.status_code == 200:
                    return response.json() or {}
            except:
                pass
        
        return {}
    
    def get_categories(self) -> Dict[str, Any]:
        """
        Fetch all categories from qBittorrent.
        
        Returns:
            dict: Categories dictionary
        """
        if self._client:
            for attr in ('torrents_categories', 'categories', 'torrents_categories_map'):
                if hasattr(self._client, attr):
                    return getattr(self._client, attr)() or {}
        
        if self._session:
            url = f"{self.base_url}{QBT_TORRENTS_CATEGORIES}"
            response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
            if response.status_code == 200:
                return response.json() or {}
        
        return {}
    
    def get_feeds(self) -> Dict[str, Any]:
        """
        Fetch all RSS feeds from qBittorrent.
        
        Returns:
            dict: Feeds dictionary
        """
        if self._client:
            for attr in ('rss_feeds', 'rss_feed', 'rss_items'):
                if hasattr(self._client, attr):
                    return getattr(self._client, attr)() or {}
        
        if self._session:
            endpoints = [QBT_RSS_FEEDS, f"{QBT_API_BASE}/rss/rootItems", f"{QBT_API_BASE}/rss/tree"]
            for endpoint in endpoints:
                try:
                    url = f"{self.base_url}{endpoint}"
                    response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
                    if response.status_code == 200:
                        return response.json() or {}
                except:
                    continue
        
        return {}
    
    def get_rules(self) -> Dict[str, Any]:
        """
        Fetch all RSS download rules from qBittorrent.
        
        Returns:
            dict: Rules dictionary
        """
        if self._client:
            for attr in ('rss_rules', 'rss_rule', 'rss_download_rules'):
                if hasattr(self._client, attr):
                    return getattr(self._client, attr)() or {}
        
        if self._session:
            url = f"{self.base_url}{QBT_RSS_RULES}"
            response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
            if response.status_code == 200:
                return response.json() or {}
        
        return {}
    
    def add_feed(self, feed_url: str, feed_name: Optional[str] = None) -> bool:
        """
        Add an RSS feed to qBittorrent.
        
        Args:
            feed_url: URL of the RSS feed
            feed_name: Optional custom name for the feed
            
        Returns:
            bool: True if successful
        """
        if self._client:
            try:
                self._client.rss_add_feed(url=feed_url)
                logger.info(f"Added RSS feed: {feed_url}")
                return True
            except Conflict409Error:
                logger.info(f"RSS feed already exists: {feed_url}")
                return True
            except Exception as e:
                logger.error(f"Failed to add RSS feed: {e}")
                return False
        
        if self._session:
            url = f"{self.base_url}{QBT_RSS_ADD_FEED}"
            data = {'url': feed_url}
            if feed_name:
                data['path'] = feed_name
            
            try:
                response = self._session.post(
                    url,
                    data=data,
                    timeout=self.timeout,
                    verify=self.verify_param
                )
                if response.status_code in (200, 409):  # 409 = already exists
                    logger.info(f"Added RSS feed: {feed_url}")
                    return True
                logger.error(f"Failed to add RSS feed: HTTP {response.status_code}")
                return False
            except Exception as e:
                logger.error(f"Failed to add RSS feed: {e}")
                return False
        
        return False
    
    def set_rule(self, rule_name: str, rule_def: Dict[str, Any]) -> bool:
        """
        Create or update an RSS download rule.
        
        Args:
            rule_name: Name of the rule
            rule_def: Rule definition dictionary
            
        Returns:
            bool: True if successful
        """
        if self._client:
            self._client.rss_set_rule(rule_name=rule_name, rule_def=rule_def)
            logger.info(f"Set RSS rule: {rule_name}")
            return True
        
        if self._session:
            url = f"{self.base_url}{QBT_RSS_SET_RULE}"
            import json
            data = {'ruleName': rule_name, 'ruleDef': json.dumps(rule_def)}
            
            response = self._session.post(url, data=data, timeout=self.timeout, verify=self.verify_param)
            if response.status_code == 200:
                logger.info(f"Set RSS rule: {rule_name}")
                return True
            logger.error(f"Failed to set RSS rule: HTTP {response.status_code}")
            return False
        
        return False
    
    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove an RSS download rule.
        
        Args:
            rule_name: Name of the rule to remove
            
        Returns:
            bool: True if successful
        """
        if self._client:
            self._client.rss_remove_rule(rule_name=rule_name)
            logger.info(f"Removed RSS rule: {rule_name}")
            return True
        
        if self._session:
            url = f"{self.base_url}{QBT_RSS_REMOVE_RULE}"
            data = {'ruleName': rule_name}
            
            response = self._session.post(url, data=data, timeout=self.timeout, verify=self.verify_param)
            if response.status_code == 200:
                logger.info(f"Removed RSS rule: {rule_name}")
                return True
            logger.error(f"Failed to remove RSS rule: HTTP {response.status_code}")
            return False
        
        return False
    
    def close(self):
        """Close the connection."""
        if self._client:
            try:
                self._client.auth_log_out()
            except:
                pass
            self._client = None
        
        if self._session:
            try:
                self._session.close()
            except:
                pass
            self._session = None


# High-level API functions

def ping_qbittorrent(protocol: str, host: str, port: str, 
                    username: str, password: str, verify_ssl: bool = True,
                    ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, str]:
    """
    Test connection to qBittorrent.
    
    Args:
        protocol: 'http' or 'https'
        host: qBittorrent host
        port: WebUI port
        username: Username
        password: Password
        verify_ssl: Verify SSL certificates
        ca_cert: Optional CA certificate path
        timeout: Connection timeout
        
    Returns:
        Tuple[bool, str]: (success, message)
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"
    
    try:
        client = QBittorrentClient(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert,
            timeout=timeout
        )
        
        client.connect()
        version = client.get_version()
        client.close()
        
        return True, f"Connected - version {version}"
        
    except APIConnectionError as e:
        return False, f"Connection failed: {e}"
    except QBittorrentError as e:
        return False, f"Authentication failed: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def fetch_categories(protocol: str, host: str, port: str,
                    username: str, password: str, verify_ssl: bool = True,
                    ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Fetch categories from qBittorrent.
    
    Args:
        protocol: 'http' or 'https'
        host: qBittorrent host
        port: WebUI port
        username: Username
        password: Password
        verify_ssl: Verify SSL certificates
        ca_cert: Optional CA certificate path
        timeout: Request timeout
        
    Returns:
        Tuple[bool, Union[str, dict]]: (success, categories or error_message)
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"
    
    try:
        client = QBittorrentClient(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert,
            timeout=timeout
        )
        
        client.connect()
        categories = client.get_categories()
        client.close()
        
        return True, categories
        
    except Exception as e:
        return False, str(e)


def fetch_feeds(protocol: str, host: str, port: str,
               username: str, password: str, verify_ssl: bool = True,
               ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Fetch RSS feeds from qBittorrent.
    
    Args:
        protocol: 'http' or 'https'
        host: qBittorrent host
        port: WebUI port
        username: Username
        password: Password
        verify_ssl: Verify SSL certificates
        ca_cert: Optional CA certificate path
        timeout: Request timeout
        
    Returns:
        Tuple[bool, Union[str, dict]]: (success, feeds or error_message)
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"
    
    try:
        client = QBittorrentClient(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert,
            timeout=timeout
        )
        
        client.connect()
        feeds = client.get_feeds()
        client.close()
        
        return True, feeds
        
    except Exception as e:
        return False, str(e)


def fetch_rules(protocol: str, host: str, port: str,
               username: str, password: str, verify_ssl: bool = True,
               ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Fetch RSS download rules from qBittorrent.
    
    Args:
        protocol: 'http' or 'https'
        host: qBittorrent host
        port: WebUI port
        username: Username
        password: Password
        verify_ssl: Verify SSL certificates
        ca_cert: Optional CA certificate path
        timeout: Request timeout
        
    Returns:
        Tuple[bool, Union[str, dict]]: (success, rules or error_message)
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"
    
    try:
        client = QBittorrentClient(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert,
            timeout=timeout
        )
        
        client.connect()
        rules = client.get_rules()
        client.close()
        
        return True, rules
        
    except Exception as e:
        return False, str(e)


__all__ = [
    'QBittorrentClient',
    'ping_qbittorrent',
    'fetch_categories',
    'fetch_feeds',
    'fetch_rules',
    'APIConnectionError',
    'Conflict409Error',
]
