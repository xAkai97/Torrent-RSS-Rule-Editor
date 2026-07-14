"""
qBittorrent API Integration Module.

This module is the bridge between our app and a running qBittorrent instance.
It handles everything needed to talk to qBittorrent's WebUI API:
  - Authenticating (login/logout)
  - Managing RSS feeds (add, list)
  - Managing RSS download rules (create, update, delete, list)
  - Fetching server info (version, preferences, categories)
  - Adding torrents (via magnet links or .torrent URLs)

DUAL-BACKEND STRATEGY:
  The module tries to use the `qbittorrent-api` Python library first (faster,
  more robust, handles edge cases). If that library isn't installed, it falls
  back to making raw HTTP requests using `requests.Session`. This fallback
  ensures the app works even without the optional dependency.
"""

# Standard library imports
import json
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

# Suppress noisy SSL warnings when the user has intentionally disabled SSL
# verification (e.g. self-signed certs on a local network)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# --- Optional dependency: qbittorrent-api library ---
# We try to import the full-featured library. If it's not installed,
# we define stub exception classes so the rest of the code can still
# reference them without crashing.
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

    # Stub exception classes so code that catches these won't break
    class APIConnectionError(Exception):
        """Raised when connection to qBittorrent API fails."""
        pass

    class Conflict409Error(Exception):
        """Raised when a 409 Conflict occurs (e.g., duplicate RSS feed)."""
        pass


# ============================================================================
# qBittorrent WebUI API endpoint paths
# These are appended to the base URL (e.g. "http://192.168.1.10:8080")
# to form the full request URL for each API call.
# ============================================================================
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
    """
    Clean up and normalize the connection fields entered by the user.

    Users might enter the host in many different formats:
      - Just a hostname:          "192.168.1.10"
      - With a port:              "192.168.1.10:8080"
      - As a full URL:            "http://192.168.1.10:8080/"
      - Protocol with trailing :// "https://"

    This function handles all these cases and returns clean, separated values
    for protocol, host, and port that can be safely combined into a base URL.

    Args:
        protocol: The protocol string (e.g. "http", "https", "https://")
        host: The host string — could be a plain hostname, host:port, or full URL
        port: The port string (may be empty if included in the host)

    Returns:
        A tuple of (protocol, host, port) with all values cleaned and normalized.
    """
    proto = (protocol or 'http').strip().lower()
    raw_host = (host or '').strip()
    raw_port = str(port or '').strip()

    # Strip trailing "://" from protocol if user typed "https://" instead of "https"
    if proto.endswith('://'):
        proto = proto[:-3]
    # Default to http if the protocol is something unexpected
    if proto not in ('http', 'https'):
        proto = 'http'

    normalized_host = raw_host
    normalized_port = raw_port

    # --- Case 1: Host contains "://" → user pasted a full URL ---
    # Example: "http://192.168.1.10:8080/some/path"
    if raw_host and '://' in raw_host:
        parsed = urlparse(raw_host)
        parsed_scheme = (parsed.scheme or '').lower()
        parsed_host = parsed.hostname or ''
        parsed_port = parsed.port

        # Use the scheme from the pasted URL if it's valid
        if parsed_scheme in ('http', 'https'):
            proto = parsed_scheme
        if parsed_host:
            normalized_host = parsed_host
        # Only use the parsed port if the user didn't already provide one separately
        if parsed_port and not normalized_port:
            normalized_port = str(parsed_port)

    # --- Case 2: Host contains exactly one ":" → user typed "hostname:port" ---
    # Example: "192.168.1.10:8080"
    elif raw_host and ':' in raw_host and raw_host.count(':') == 1:
        host_part, port_part = raw_host.split(':', 1)
        host_part = host_part.strip().rstrip('/')
        port_part = port_part.strip()
        if host_part:
            normalized_host = host_part
        if port_part and not normalized_port:
            normalized_port = port_part

    # Clean up any trailing slashes or whitespace from the host
    normalized_host = normalized_host.rstrip('/').strip()

    return proto, normalized_host, normalized_port


class QBittorrentClient:
    """
    Main client for communicating with a qBittorrent instance.

    This class provides a unified API regardless of whether the optional
    `qbittorrent-api` library is installed. It automatically picks the
    best available backend:
      - If `qbittorrent-api` is installed → uses its Client class (preferred)
      - Otherwise → falls back to raw HTTP requests via `requests.Session`

    The caller doesn't need to know which backend is being used — all methods
    work the same way either way.

    Typical usage:
        client = QBittorrentClient("http", "192.168.1.10", "8080", "admin", "password")
        client.connect()
        rules = client.get_rules()
        client.close()
    """

    def __init__(self, protocol: str, host: str, port: str,
                 username: str, password: str, verify_ssl: bool = True,
                 ca_cert: Optional[str] = None, timeout: Optional[int] = None):
        """
        Set up the client with connection details.

        No actual network connection is made here — call connect() for that.

        Args:
            protocol: 'http' or 'https'
            host: qBittorrent server hostname or IP address
            port: WebUI port number (usually 8080)
            username: WebUI login username
            password: WebUI login password
            verify_ssl: Whether to verify the server's SSL certificate.
                        Set to False for self-signed certs.
            ca_cert: Optional path to a custom CA certificate file for SSL.
            timeout: Request timeout in seconds. If not specified, uses the
                     default from NetworkConfig.
        """
        from src.constants import NetworkConfig

        # Normalize the connection details (handles messy user input)
        self.protocol, self.host, self.port = _normalize_connection_parts(protocol, host, port)
        self.username = username.strip()
        self.password = password.strip()
        self.verify_ssl = verify_ssl
        self.ca_cert = ca_cert
        self.timeout = timeout if timeout is not None else NetworkConfig.DEFAULT_TIMEOUT

        # Build the base URL that all API calls will be made against
        # Example: "https://192.168.1.10:8080"
        self.base_url = f"{self.protocol}://{self.host}:{self.port}"

        # Determine what to pass as the `verify` parameter to requests:
        #   - False           → skip SSL verification entirely
        #   - path to CA cert → use a custom certificate authority
        #   - True            → use the system's default CA bundle
        self.verify_param = False if not verify_ssl else (ca_cert if ca_cert else verify_ssl)

        logger.debug(f"QBittorrentClient initialized: verify_ssl={verify_ssl}, ca_cert={ca_cert}, verify_param={self.verify_param}")

        # These get populated by connect() — one will be set, the other stays None
        self._client = None    # The qbittorrent-api Client (if using library backend)
        self._session = None   # The requests.Session (if using fallback backend)

    @staticmethod
    def _normalize_connection_parts(protocol: str, host: str, port: str) -> Tuple[str, str, str]:
        """Static method wrapper so other code can access normalization via the class."""
        return _normalize_connection_parts(protocol, host, port)

    def _get_verify_param(self) -> Union[bool, str]:
        """Get the SSL verification parameter for requests calls."""
        return self.verify_param

    def connect(self) -> bool:
        """
        Authenticate and establish a session with qBittorrent.

        Picks the best available backend automatically:
          - Library backend (qbittorrent-api) if installed
          - Raw requests fallback otherwise

        Returns:
            True if the connection and login were successful.

        Raises:
            APIConnectionError: If the server can't be reached.
            QBittorrentError: If the username/password is wrong.
        """
        if HAS_QBT_API:
            return self._connect_with_library()
        else:
            return self._connect_with_requests()

    def __enter__(self) -> QBittorrentClient:
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit point — auto-closes the connection."""
        self.close()

    def _connect_with_library(self) -> bool:
        """
        Connect using the qbittorrent-api library (preferred backend).

        This tries to create a Client with SSL verification settings.
        Some older versions of the library don't support the
        VERIFY_WEBUI_CERTIFICATE parameter, so if we get a TypeError,
        we retry without it and manually patch the session's SSL setting.
        """
        try:
            self._client = Client(
                host=self.base_url,
                username=self.username,
                password=self.password,
                VERIFY_WEBUI_CERTIFICATE=self.verify_param,
                FORCE_SCHEME_FROM_HOST=True,       # Use our protocol, don't auto-detect
                HTTPADAPTER_ARGS={'max_retries': 0},  # Don't retry failed requests
                REQUESTS_ARGS={'timeout': self.timeout}
            )
            self._client.auth_log_in()
            logger.info(f"Connected to qBittorrent at {self.base_url}")
            return True
        except TypeError:
            # Fallback for older library versions that don't accept
            # VERIFY_WEBUI_CERTIFICATE — create client without it, then
            # manually disable SSL verification on the underlying session
            self._client = Client(
                host=self.base_url,
                username=self.username,
                password=self.password,
                FORCE_SCHEME_FROM_HOST=True,
                HTTPADAPTER_ARGS={'max_retries': 0},
                REQUESTS_ARGS={'timeout': self.timeout}
            )
            # The library's internal session object has different names across
            # versions, so we try several possible attribute names
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
        """
        Connect using raw HTTP requests (fallback when qbittorrent-api isn't installed).

        Creates a requests.Session (which persists cookies across calls) and
        authenticates by POSTing username/password to the login endpoint.
        qBittorrent returns "Ok" on success, which we verify.
        """
        self._session = requests.Session()
        login_url = f"{self.base_url}{QBT_AUTH_LOGIN}"

        logger.debug(f"Connecting to {login_url} with verify={self.verify_param}")

        response = self._session.post(
            login_url,
            data={'username': self.username, 'password': self.password},
            timeout=self.timeout,
            verify=self.verify_param
        )

        # qBittorrent returns the text "Ok" (case-insensitive) on successful login
        if response.status_code == 200 and response.text.strip().lower() == 'ok':
            logger.info(f"Connected to qBittorrent at {self.base_url} (requests)")
            return True

        raise QBittorrentError(f"Authentication failed: {response.text}")

    def get_version(self) -> str:
        """
        Get the qBittorrent application version string (e.g. "v4.6.2").

        Returns:
            The version string, or "unknown" if it can't be retrieved.
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
        Get qBittorrent's application preferences/settings.

        This returns things like the default save path, max active downloads,
        speed limits, etc. Useful for pre-filling save path fields in the UI.

        Returns:
            A dictionary of all qBittorrent preferences, or empty dict on failure.
        """
        if self._client:
            # Different library versions expose preferences under different method names
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
            except Exception:
                pass

        return {}

    def get_categories(self) -> Dict[str, Any]:
        """
        Fetch all torrent categories configured in qBittorrent.

        Categories are user-defined labels (e.g. "Anime", "Movies") that can
        have their own default save paths. The rule editor uses these to populate
        category dropdown menus.

        Returns:
            A dictionary mapping category names to their settings, or empty dict.
        """
        if self._client:
            # Try multiple method names for cross-version compatibility
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
        Fetch all RSS feeds currently configured in qBittorrent.

        Each feed has a URL, a name, and (potentially) cached articles.
        The rule editor needs this list to let users pick which feeds
        their download rules should apply to.

        Returns:
            A dictionary of feed data, or empty dict on failure.
        """
        if self._client:
            # Try multiple method names for cross-version compatibility
            for attr in ('rss_feeds', 'rss_feed', 'rss_items'):
                if hasattr(self._client, attr):
                    return getattr(self._client, attr)() or {}

        if self._session:
            # qBittorrent has changed the feed list endpoint name across versions,
            # so we try multiple endpoints until one works
            endpoints = [QBT_RSS_FEEDS, f"{QBT_API_BASE}/rss/rootItems", f"{QBT_API_BASE}/rss/tree"]
            for endpoint in endpoints:
                try:
                    url = f"{self.base_url}{endpoint}"
                    response = self._session.get(url, timeout=self.timeout, verify=self.verify_param)
                    if response.status_code == 200:
                        return response.json() or {}
                except Exception:
                    continue

        return {}

    def get_rules(self) -> Dict[str, Any]:
        """
        Fetch all RSS automatic download rules from qBittorrent.

        These are the rules that tell qBittorrent "when a new RSS item matches
        this pattern, download it automatically." This is the core data that
        our rule editor reads and writes.

        Returns:
            A dictionary mapping rule names to their definitions, or empty dict.
        """
        if self._client:
            # Try multiple method names for cross-version compatibility
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
        Add an RSS feed to qBittorrent so it starts polling for new releases.

        If the feed already exists, this is treated as a success (not an error),
        since the goal is just to make sure the feed is present.

        Args:
            feed_url: The URL of the RSS feed to add.
            feed_name: Optional custom display name for the feed in qBittorrent.

        Returns:
            True if the feed was added (or already existed), False on failure.
        """
        if self._client:
            try:
                self._client.rss_add_feed(url=feed_url)
                logger.info(f"Added RSS feed: {feed_url}")
                return True
            except Conflict409Error:
                # Feed already exists — that's fine, we just wanted to ensure it's there
                logger.info(f"RSS feed already exists: {feed_url}")
                return True
            except Exception as e:
                logger.error(f"Failed to add RSS feed: {e}")
                return False

        if self._session:
            url = f"{self.base_url}{QBT_RSS_ADD_FEED}"
            data = {'url': feed_url}
            if feed_name:
                data['path'] = feed_name  # qBittorrent uses 'path' as the feed name param

            try:
                response = self._session.post(
                    url,
                    data=data,
                    timeout=self.timeout,
                    verify=self.verify_param
                )
                # HTTP 409 means the feed already exists — still a success for our purposes
                if response.status_code in (200, 409):
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
        Create or update an RSS automatic download rule on the server.

        This is the main write operation for rules. The rule definition dict
        contains fields like 'mustContain', 'mustNotContain', 'savePath',
        'assignedCategory', 'affectedFeeds', etc.

        Args:
            rule_name: The name/identifier for the rule.
            rule_def: The full rule definition as a dictionary.

        Returns:
            True if the rule was created/updated successfully, False on failure.
        """
        if self._client:
            self._client.rss_set_rule(rule_name=rule_name, rule_def=rule_def)
            logger.info(f"Set RSS rule: {rule_name}")
            return True

        if self._session:
            url = f"{self.base_url}{QBT_RSS_SET_RULE}"
            # The WebUI API expects the rule definition as a JSON string, not a dict
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
        Delete an RSS download rule from qBittorrent.

        Args:
            rule_name: The name of the rule to remove.

        Returns:
            True if the rule was removed successfully, False on failure.
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

    def add_torrents(self, urls: Union[str, List[str]], save_path: Optional[str] = None,
                     category: Optional[str] = None, tags: Optional[Union[str, List[str]]] = None,
                     is_paused: bool = False) -> bool:
        """
        Send torrent URLs or magnet links to qBittorrent for downloading.

        This is used by the batch downloader feature to queue up multiple
        torrents at once. It supports magnet links, .torrent file URLs,
        and any mix of both.

        Args:
            urls: A single URL/magnet string, or a list of them.
            save_path: Optional target download directory on the server.
            category: Optional category to assign to the torrent(s).
            tags: Optional tag(s) — either a comma-separated string or list of strings.
            is_paused: If True, add the torrent(s) in a paused state (won't start downloading).

        Returns:
            True if the torrents were queued successfully, False on failure.
        """
        # Normalize input: ensure we always have a list for counting/logging
        urls_list = [urls] if isinstance(urls, str) else list(urls)
        # The WebUI API also accepts newline-separated URLs as a single string
        urls_str = "\n".join(urls_list)

        if self._client:
            try:
                self._client.torrents_add(
                    urls=urls_list,
                    save_path=save_path,
                    category=category,
                    tags=tags,
                    is_paused=is_paused
                )
                logger.info(f"Successfully added {len(urls_list)} torrent(s) via qbittorrent-api")
                return True
            except Exception as e:
                logger.error(f"Failed to add torrents via qbittorrent-api: {e}")
                return False

        if self._session:
            url = f"{self.base_url}/api/v2/torrents/add"
            data = {
                'urls': urls_str,
                'paused': 'true' if is_paused else 'false'
            }
            if save_path:
                data['savepath'] = save_path
            if category:
                data['category'] = category
            if tags:
                # The WebUI API expects tags as a single comma-separated string
                if isinstance(tags, list):
                    data['tags'] = ",".join(tags)
                else:
                    data['tags'] = tags

            try:
                response = self._session.post(
                    url,
                    data=data,
                    timeout=self.timeout,
                    verify=self.verify_param
                )
                if response.status_code == 200:
                    logger.info(f"Successfully added {len(urls_list)} torrent(s) via requests fallback")
                    return True
                logger.error(f"Failed to add torrents via requests fallback: HTTP {response.status_code} {response.text}")
                return False
            except Exception as e:
                logger.error(f"Failed to add torrents via requests fallback: {e}")
                return False

        return False

    def close(self):
        """
        Cleanly shut down the connection to qBittorrent.

        Logs out the session and releases any held resources. Safe to call
        even if the connection was never established (does nothing in that case).
        """
        if self._client:
            try:
                self._client.auth_log_out()
            except Exception:
                pass  # Best-effort logout — if it fails, we're closing anyway
            self._client = None

        if self._session:
            try:
                self._session.close()
            except Exception:
                pass  # Best-effort close
            self._session = None


# ============================================================================
# High-level convenience functions
#
# These are standalone functions that create a temporary QBittorrentClient,
# perform one operation, and then close the connection. They're used by the
# GUI and services layer for quick one-off operations without having to
# manage the client lifecycle manually.
# ============================================================================

def ping_qbittorrent(protocol: str, host: str, port: str,
                    username: str, password: str, verify_ssl: bool = True,
                    ca_cert: Optional[str] = None, timeout: int = 3) -> Tuple[bool, str]:
    """
    Test whether we can connect and authenticate to qBittorrent.

    Used by the "Test Connection" button in the settings UI. Creates a
    temporary client, tries to log in and fetch the version, then disconnects.

    Args:
        protocol: 'http' or 'https'
        host: qBittorrent server hostname or IP
        port: WebUI port number
        username: WebUI login username
        password: WebUI login password
        verify_ssl: Whether to verify SSL certificates
        ca_cert: Optional path to a custom CA certificate file
        timeout: Connection timeout in seconds (short default for quick feedback)

    Returns:
        A tuple of (success: bool, message: str).
        On success: (True, "Connected - version v4.6.2")
        On failure: (False, "Connection failed: <error details>")
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"

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
    try:
        client.connect()
        version = client.get_version()
        return True, f"Connected - version {version}"
    except APIConnectionError as e:
        return False, f"Connection failed: {e}"
    except QBittorrentError as e:
        return False, f"Authentication failed: {e}"
    except Exception as e:
        return False, f"Error: {e}"
    finally:
        client.close()


def fetch_categories(protocol: str, host: str, port: str,
                     username: str, password: str, verify_ssl: bool = True,
                     ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Connect to qBittorrent and retrieve all configured torrent categories.

    Used to populate category dropdowns in the rule editor UI.

    Args:
        protocol: 'http' or 'https'
        host: qBittorrent server hostname or IP
        port: WebUI port number
        username: WebUI login username
        password: WebUI login password
        verify_ssl: Whether to verify SSL certificates
        ca_cert: Optional path to a custom CA certificate file
        timeout: Request timeout in seconds

    Returns:
        A tuple of (success: bool, result).
        On success: (True, {category_name: {savePath: "...", ...}, ...})
        On failure: (False, "error message string")
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"

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
    try:
        client.connect()
        categories = client.get_categories()
        return True, categories
    except Exception as e:
        return False, str(e)
    finally:
        client.close()


def fetch_feeds(protocol: str, host: str, port: str,
               username: str, password: str, verify_ssl: bool = True,
               ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Connect to qBittorrent and retrieve all configured RSS feeds.

    Used by the rule editor to show which feeds are available and to let
    users assign feeds to their download rules.

    Args:
        protocol: 'http' or 'https'
        host: qBittorrent server hostname or IP
        port: WebUI port number
        username: WebUI login username
        password: WebUI login password
        verify_ssl: Whether to verify SSL certificates
        ca_cert: Optional path to a custom CA certificate file
        timeout: Request timeout in seconds

    Returns:
        A tuple of (success: bool, result).
        On success: (True, {feed_name: {url: "...", ...}, ...})
        On failure: (False, "error message string")
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"

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
    try:
        client.connect()
        feeds = client.get_feeds()
        return True, feeds
    except Exception as e:
        return False, str(e)
    finally:
        client.close()


def fetch_rules(protocol: str, host: str, port: str,
               username: str, password: str, verify_ssl: bool = True,
               ca_cert: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Union[str, Dict]]:
    """
    Connect to qBittorrent and retrieve all RSS automatic download rules.

    This is the primary function used by the rule sync system to get the
    current state of rules on the server, so it can compare them against
    the desired state in the local editor.

    Args:
        protocol: 'http' or 'https'
        host: qBittorrent server hostname or IP
        port: WebUI port number
        username: WebUI login username
        password: WebUI login password
        verify_ssl: Whether to verify SSL certificates
        ca_cert: Optional path to a custom CA certificate file
        timeout: Request timeout in seconds

    Returns:
        A tuple of (success: bool, result).
        On success: (True, {rule_name: {mustContain: "...", ...}, ...})
        On failure: (False, "error message string")
    """
    protocol, host, port = _normalize_connection_parts(protocol, host, port)

    if not host or not port:
        return False, "Host or port is empty"

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
    try:
        client.connect()
        rules = client.get_rules()
        return True, rules
    except Exception as e:
        return False, str(e)
    finally:
        client.close()




# Public API — these are the symbols available when doing `from src.api.qbittorrent import *`
__all__ = [
    'QBittorrentClient',
    'ping_qbittorrent',
    'fetch_categories',
    'fetch_feeds',
    'fetch_rules',
    'APIConnectionError',
    'Conflict409Error',
]
