"""
Application configuration management.
"""
# Standard library imports
import shutil
from datetime import datetime
import json
import logging
import os
from configparser import ConfigParser
from typing import Any, Dict, List, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]

# Local application imports
from .constants import CacheKeys

logger = logging.getLogger(__name__)


class AppConfig:
    """Application configuration manager with type-safe access to settings."""
    
    def __init__(self):
        # File paths and defaults
        self.CONFIG_FILE: str = 'config.ini'
        self.SECRET_KEY_FILE: str = '.app_secret.key'
        self.OUTPUT_CONFIG_FILE_NAME: str = 'qbittorrent_rules.json'
        self.CACHE_FILE: str = 'seasonal_cache.json'
        self._encryption_fallback_active: bool = False
        self._encryption_fallback_reason: str = ''
        
        self.DEFAULT_RSS_FEED: str = ""
        self.DEFAULT_SAVE_PATH: str = ""
        self.DEFAULT_DOWNLOAD_PATH: str = ""  # qBittorrent's default download path (used as base path)
        self.DEFAULT_CATEGORY: str = ""
        self.DEFAULT_AFFECTED_FEEDS: List[str] = []
        
        # Connection configuration - qBittorrent
        self.QBT_PROTOCOL: Optional[str] = None
        self.QBT_HOST: Optional[str] = None
        self.QBT_PORT: Optional[str] = None
        self.QBT_USER: Optional[str] = None
        self.QBT_PASS: Optional[str] = None
        self.QBT_VERIFY_SSL: bool = True
        self.CONNECTION_MODE: str = 'online'
        self.QBT_CA_CERT: Optional[str] = None
        
        # Connection configuration - Sonarr
        self.SONARR_URL: Optional[str] = None
        self.SONARR_API_KEY: Optional[str] = None
        self.SONARR_QUALITY_PROFILE: Optional[int] = None
        self.SONARR_ROOT_FOLDER: Optional[str] = None
        self.SONARR_MONITOR_MODE: str = 'all'  # all, future, missing, existing, none
        self.SONARR_SEARCH_ON_ADD: bool = False

        # Connection configuration - Deluge
        self.DELUGE_PROTOCOL: Optional[str] = None
        self.DELUGE_HOST: Optional[str] = None
        self.DELUGE_PORT: Optional[str] = None
        self.DELUGE_PASSWORD: Optional[str] = None
        self.DELUGE_VERIFY_SSL: bool = True

        # Platform configuration
        self.SUPPORTED_SERVERS: List[str] = ['qbittorrent', 'deluge', 'transmission', 'sonarr', 'autobrr']
        self.MAIN_SERVER: str = 'qbittorrent'
        self.EXPORT_TARGETS: List[str] = ['sonarr']
        
        # Application state
        self.RECENT_FILES: List[str] = []
        self.CACHED_CATEGORIES: Dict[str, Any] = {}
        self.CACHED_FEEDS: Dict[str, Any] = {}
        
        # ALL_TITLES uses a hybrid format where each entry contains both:
        # 1. qBittorrent RSS rule fields (mustContain, savePath, affectedFeeds, etc.)
        # 2. Internal tracking fields for display purposes:
        #    - 'node': {'title': 'Display Title'} - used for treeview display
        #    - 'ruleName': 'Title' - original rule name from qBittorrent
        #
        # Structure:
        # {
        #   'existing': [  # or 'anime', 'manga', etc.
        #     {
        #       # qBittorrent fields
        #       'mustContain': 'Title',
        #       'savePath': '/path/to/save',
        #       'assignedCategory': 'Category',
        #       'enabled': True,
        #       'affectedFeeds': ['url'],
        #       'torrentParams': {...},
        #       # Internal tracking fields (filtered out on export)
        #       'node': {'title': 'Display Title'},
        #       'ruleName': 'Title'
        #     }
        #   ]
        # }
        #
        # When exporting or previewing, internal fields ('node', 'ruleName') must be
        # filtered out to produce clean qBittorrent-compatible JSON.
        # See file_operations.py: _show_preview_dialog() for the filtering logic.
        self.ALL_TITLES: Dict[str, List[Any]] = {}
        
        # API Endpoints
        self.QBT_AUTH_LOGIN: str = "/api/v2/auth/login"
        self.QBT_TORRENTS_CATEGORIES: str = "/api/v2/torrents/categories"
        self.QBT_RSS_FEEDS: str = "/api/v2/rss/items"
        self.QBT_RSS_RULES: str = "/api/v2/rss/rules"
        self.QBT_API_BASE: str = "/api/v2"

    def _secret_key_path(self) -> str:
        """Return absolute path for the local encryption key file."""
        cfg_dir = os.path.dirname(os.path.abspath(self.CONFIG_FILE)) or os.getcwd()
        return os.path.join(cfg_dir, self.SECRET_KEY_FILE)

    def _get_cipher(self) -> Any:
        """Return a Fernet cipher instance when encryption is available."""
        if Fernet is None:
            self._encryption_fallback_active = True
            self._encryption_fallback_reason = 'cryptography dependency not installed'
            return None

        key_path = self._secret_key_path()
        try:
            if os.path.exists(key_path):
                with open(key_path, 'rb') as f:
                    key = f.read().strip()
            else:
                key = Fernet.generate_key()
                with open(key_path, 'wb') as f:
                    f.write(key)
            self._encryption_fallback_active = False
            self._encryption_fallback_reason = ''
            return Fernet(key)
        except Exception as e:
            logger.warning(f"Credential encryption unavailable (key init failed): {e}")
            self._encryption_fallback_active = True
            self._encryption_fallback_reason = str(e)
            return None

    def _encrypt_secret(self, value: str) -> str:
        """Encrypt secret value for at-rest storage when possible."""
        if not value:
            return ''
        if value.startswith('enc:'):
            return value

        cipher = self._get_cipher()
        if not cipher:
            return value

        try:
            token = cipher.encrypt(value.encode('utf-8'))
            return 'enc:' + token.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to encrypt secret, storing plaintext: {e}")
            return value

    def _decrypt_secret(self, value: str) -> str:
        """Decrypt secret value loaded from config."""
        if not value:
            return ''
        if not value.startswith('enc:'):
            return value

        cipher = self._get_cipher()
        if not cipher:
            return value

        try:
            token = value[4:].encode('utf-8')
            return cipher.decrypt(token).decode('utf-8')
        except InvalidToken:
            logger.warning("Failed to decrypt secret (invalid token); keeping raw value")
            return value
        except Exception as e:
            logger.warning(f"Failed to decrypt secret: {e}")
            return value

    def _persist_encrypted_secrets(self) -> bool:
        """Rewrite config.ini with encrypted secret fields when needed."""
        if not os.path.exists(self.CONFIG_FILE):
            return False

        if Fernet is None:
            return False

        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)

            changed = False
            if 'QBITTORRENT_API' in cfg:
                raw_pass = cfg['QBITTORRENT_API'].get('password', '')
                enc_pass = self._encrypt_secret(raw_pass)
                if enc_pass != raw_pass:
                    cfg['QBITTORRENT_API']['password'] = enc_pass
                    changed = True

            if 'SONARR' in cfg:
                raw_key = cfg['SONARR'].get('api_key', '')
                enc_key = self._encrypt_secret(raw_key)
                if enc_key != raw_key:
                    cfg['SONARR']['api_key'] = enc_key
                    changed = True

            if changed:
                with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                    cfg.write(f)
                logger.info("Migrated plaintext secrets to encrypted config entries")
            return changed
        except Exception as e:
            logger.warning(f"Failed to persist encrypted secrets migration: {e}")
            return False

    def is_secret_encryption_available(self) -> bool:
        """Whether encryption backend is available in the current environment."""
        return Fernet is not None

    def has_plaintext_secrets(self) -> bool:
        """Check whether config file still contains plaintext sensitive values."""
        try:
            if not os.path.exists(self.CONFIG_FILE):
                return False

            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)

            qbt_password = ''
            sonarr_key = ''

            if 'QBITTORRENT_API' in cfg:
                qbt_password = str(cfg['QBITTORRENT_API'].get('password', '') or '')
            if 'SONARR' in cfg:
                sonarr_key = str(cfg['SONARR'].get('api_key', '') or '')

            for value in (qbt_password, sonarr_key):
                if value and not value.startswith('enc:'):
                    return True
            return False
        except Exception:
            return False

    def migrate_plaintext_secrets(self) -> bool:
        """Force migration of plaintext secrets to encrypted values."""
        return self._persist_encrypted_secrets()

    def is_plaintext_fallback_active(self) -> bool:
        """Whether runtime fell back to plaintext secret handling."""
        return bool(self._encryption_fallback_active)

    def get_plaintext_fallback_reason(self) -> str:
        """Get reason for plaintext fallback mode."""
        return self._encryption_fallback_reason or 'Unknown encryption backend issue'

    def export_secret_key(self, destination_path: str) -> bool:
        """Export local encryption key to a user-selected destination file."""
        try:
            source = self._secret_key_path()
            if not os.path.exists(source):
                # Ensure key exists before export.
                if not self._get_cipher():
                    return False
            source = self._secret_key_path()
            shutil.copy2(source, destination_path)
            return True
        except Exception as e:
            logger.error(f"Failed to export secret key: {e}")
            return False

    def rotate_secret_key(self) -> bool:
        """Rotate local encryption key and re-encrypt stored secret values."""
        if Fernet is None:
            logger.warning("Cannot rotate secret key: cryptography unavailable")
            return False
        if not os.path.exists(self.CONFIG_FILE):
            return False

        key_path = self._secret_key_path()
        old_key = None
        if os.path.exists(key_path):
            try:
                with open(key_path, 'rb') as f:
                    old_key = f.read().strip()
            except Exception as e:
                logger.error(f"Failed reading existing key during rotation: {e}")
                return False

        old_cipher = Fernet(old_key) if old_key else None

        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)

            def _decrypt_existing(value: str) -> str:
                if not value:
                    return ''
                if not str(value).startswith('enc:'):
                    return str(value)
                token = str(value)[4:].encode('utf-8')
                if not old_cipher:
                    raise ValueError('No existing key available to decrypt current encrypted secrets')
                return old_cipher.decrypt(token).decode('utf-8')

            qbt_plain = ''
            sonarr_plain = ''
            if 'QBITTORRENT_API' in cfg:
                qbt_plain = _decrypt_existing(cfg['QBITTORRENT_API'].get('password', ''))
            if 'SONARR' in cfg:
                sonarr_plain = _decrypt_existing(cfg['SONARR'].get('api_key', ''))

            new_key = Fernet.generate_key()
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            if os.path.exists(key_path):
                shutil.copy2(key_path, f"{key_path}.{timestamp}.bak")
            with open(key_path, 'wb') as f:
                f.write(new_key)

            new_cipher = Fernet(new_key)
            if 'QBITTORRENT_API' in cfg:
                cfg['QBITTORRENT_API']['password'] = (
                    'enc:' + new_cipher.encrypt(qbt_plain.encode('utf-8')).decode('utf-8') if qbt_plain else ''
                )
            if 'SONARR' in cfg:
                cfg['SONARR']['api_key'] = (
                    'enc:' + new_cipher.encrypt(sonarr_plain.encode('utf-8')).decode('utf-8') if sonarr_plain else ''
                )

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)

            self._encryption_fallback_active = False
            self._encryption_fallback_reason = ''
            return True
        except Exception as e:
            logger.error(f"Failed rotating secret key: {e}")
            return False
    
    def get_pref(self, key: str, default: Any = None) -> Any:
        """Get a preference value with fallback."""
        cache = self._load_cache_data()
        return cache.get(CacheKeys.PREFS, {}).get(key, default)
    
    def set_pref(self, key: str, value: Any) -> bool:
        """Set a preference value."""
        try:
            cache = self._load_cache_data()
            cache.setdefault(CacheKeys.PREFS, {})[key] = value
            return self._save_cache_data(cache)
        except Exception as e:
            logger.error(f"Failed to set preference '{key}': {e}")
            return False
    
    def _load_cache_data(self) -> Dict[str, Any]:
        """Load cache data from file."""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load cache file: {e}")
        return {}
    
    def _save_cache_data(self, data: Dict[str, Any]) -> bool:
        """Save cache data to file."""
        try:
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save cache file: {e}")
            return False
    
    def load_cached_categories(self) -> None:
        """Load cached categories from file."""
        cache = self._load_cache_data()
        self.CACHED_CATEGORIES = cache.get(CacheKeys.CATEGORIES, {})
        logger.info(f"Loaded {len(self.CACHED_CATEGORIES)} cached categories")
    
    def load_cached_feeds(self) -> None:
        """Load cached feeds from file."""
        cache = self._load_cache_data()
        self.CACHED_FEEDS = cache.get(CacheKeys.FEEDS, {})
        logger.info(f"Loaded {len(self.CACHED_FEEDS)} cached feeds")
    
    def add_recent_file(self, filepath: str) -> None:
        """Add a file to the recent files list."""
        # Remove if already exists to avoid duplicates
        if filepath in self.RECENT_FILES:
            self.RECENT_FILES.remove(filepath)
        
        # Add to front and keep only last N
        self.RECENT_FILES.insert(0, filepath)
        from .constants import CacheLimits
        self.RECENT_FILES = self.RECENT_FILES[:CacheLimits.MAX_RECENT_FILES]
        
        # Save to cache
        cache = self._load_cache_data()
        cache[CacheKeys.RECENT_FILES] = self.RECENT_FILES
        self._save_cache_data(cache)
        logger.info(f"Added recent file: {filepath}")
    
    def load_config(self) -> bool:
        """
        Loads qBittorrent connection configuration from config.ini file.
        
        Reads configuration file and populates configuration variables
        for qBittorrent API connection parameters.
        
        Returns:
            bool: True if configuration loaded successfully with host and port,
                  False otherwise
        """
        try:
            if not os.path.exists(self.CONFIG_FILE):
                # First-run bootstrap: create a safe default config file.
                self.save_config(
                    protocol='http',
                    host='localhost',
                    port='8080',
                    user='',
                    password='',
                    mode='online',
                    verify_ssl=False,
                    default_save_path='',
                    default_category='',
                    default_affected_feeds=[],
                )
                logger.info(f"Created default config file: {self.CONFIG_FILE}")

            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)

            qbt_loaded = 'QBITTORRENT_API' in cfg
            migration_needed = False
            if qbt_loaded:
                qbt = cfg['QBITTORRENT_API']
                self.QBT_PROTOCOL = qbt.get('protocol', 'http')
                self.QBT_HOST = qbt.get('host', 'localhost')
                self.QBT_PORT = str(qbt.get('port', '8080')).strip() or '8080'
                self.QBT_USER = qbt.get('username', '')
                qbt_pass_raw = qbt.get('password', '')
                self.QBT_PASS = self._decrypt_secret(qbt_pass_raw)
                if qbt_pass_raw and not str(qbt_pass_raw).startswith('enc:'):
                    migration_needed = True
                self.CONNECTION_MODE = qbt.get('mode', 'online')
                self.QBT_VERIFY_SSL = qbt.get('verify_ssl', 'True').lower() == 'true'
                self.QBT_CA_CERT = qbt.get('ca_cert') or None
                self.DEFAULT_SAVE_PATH = qbt.get('default_save_path', '')
                self.DEFAULT_DOWNLOAD_PATH = qbt.get('default_download_path', '')
                self.DEFAULT_CATEGORY = qbt.get('default_category', '')
                
                # Load default affected feeds (comma-separated list)
                feeds_str = qbt.get('default_affected_feeds', '')
                self.DEFAULT_AFFECTED_FEEDS = [f.strip() for f in feeds_str.split(',') if f.strip()]
                
                logger.info(f"Loaded qBittorrent config: {self.QBT_PROTOCOL}://{self.QBT_HOST}:{self.QBT_PORT} (mode: {self.CONNECTION_MODE})")
            else:
                # Set defaults
                self.QBT_PROTOCOL, self.QBT_HOST, self.QBT_PORT = 'http', 'localhost', '8080'
                self.QBT_USER, self.QBT_PASS = '', ''
                self.QBT_VERIFY_SSL = False
                self.CONNECTION_MODE = 'online'
                logger.warning("No QBITTORRENT_API section found in config.ini, using defaults")
            
            # Load Sonarr configuration
            sonarr_loaded = 'SONARR' in cfg
            if sonarr_loaded:
                sonarr = cfg['SONARR']
                self.SONARR_URL = sonarr.get('url', '')
                sonarr_key_raw = sonarr.get('api_key', '')
                self.SONARR_API_KEY = self._decrypt_secret(sonarr_key_raw)
                if sonarr_key_raw and not str(sonarr_key_raw).startswith('enc:'):
                    migration_needed = True
                quality_profile = sonarr.get('quality_profile', '')
                self.SONARR_QUALITY_PROFILE = int(quality_profile) if quality_profile else None
                self.SONARR_ROOT_FOLDER = sonarr.get('root_folder', '')
                self.SONARR_MONITOR_MODE = sonarr.get('monitor_mode', 'all')
                self.SONARR_SEARCH_ON_ADD = sonarr.get('search_on_add', 'False').lower() == 'true'
                logger.info(f"Loaded Sonarr config: {self.SONARR_URL}")
            else:
                logger.info("No SONARR section found in config.ini")

            # Load Deluge configuration
            if 'DELUGE_API' in cfg:
                deluge = cfg['DELUGE_API']
                self.DELUGE_PROTOCOL = deluge.get('protocol', 'http')
                self.DELUGE_HOST = deluge.get('host', 'localhost')
                self.DELUGE_PORT = str(deluge.get('port', '8112')).strip() or '8112'
                self.DELUGE_PASSWORD = deluge.get('password', '')
                self.DELUGE_VERIFY_SSL = deluge.get('verify_ssl', 'True').lower() == 'true'
            else:
                self.DELUGE_PROTOCOL = 'http'
                self.DELUGE_HOST = 'localhost'
                self.DELUGE_PORT = '8112'
                self.DELUGE_PASSWORD = ''
                self.DELUGE_VERIFY_SSL = True

            # Load platform/server preferences
            if 'PLATFORM' in cfg:
                platform_cfg = cfg['PLATFORM']
                main_server = str(platform_cfg.get('main_server', 'qbittorrent')).strip().lower()
                if main_server in self.SUPPORTED_SERVERS:
                    self.MAIN_SERVER = main_server
                else:
                    self.MAIN_SERVER = 'qbittorrent'

                export_targets_raw = str(platform_cfg.get('export_targets', 'sonarr')).strip()
                parsed_targets = [t.strip().lower() for t in export_targets_raw.split(',') if t.strip()]
                parsed_targets = [t for t in parsed_targets if t in self.SUPPORTED_SERVERS]
                self.EXPORT_TARGETS = parsed_targets or ['sonarr']
            else:
                self.MAIN_SERVER = 'qbittorrent'
                self.EXPORT_TARGETS = ['sonarr']

            if migration_needed:
                self._persist_encrypted_secrets()

            return bool(self.QBT_HOST and self.QBT_PORT)
        except Exception as e:
            logger.error(f"Failed to load config from INI: {e}")
            self.QBT_PROTOCOL, self.QBT_HOST, self.QBT_PORT = 'http', 'localhost', '8080'
            self.QBT_USER, self.QBT_PASS = '', ''
            self.CONNECTION_MODE = 'online'
            return False
    
    def save_config(self, protocol: str, host: str, port: str, user: str, password: str, mode: str, verify_ssl: bool, 
                    default_save_path: str = '', default_category: str = '', default_affected_feeds: List[str] = None) -> bool:
        """
        Saves qBittorrent connection configuration to config.ini file.
        
        Args:
            protocol: HTTP protocol ('http' or 'https')
            host: qBittorrent host address (IP or hostname)
            port: qBittorrent WebUI port number
            user: WebUI username
            password: WebUI password
            mode: Connection mode ('online' or 'offline')
            verify_ssl: Whether to verify SSL certificates
            default_save_path: Default save path for new rules
            default_category: Default category for new rules
            default_affected_feeds: Default affected feeds for new rules (list of feed URLs)
        
        Returns:
            bool: True if save was successful, False otherwise
        """
        cfg = ConfigParser()
        cfg.read(self.CONFIG_FILE)
        normalized_port = str(port).strip() or '8080'
        
        # Prepare default affected feeds as comma-separated string
        feeds_str = ', '.join(default_affected_feeds) if default_affected_feeds else ''
        
        cfg['QBITTORRENT_API'] = {
                'protocol': protocol,
                'host': host,
                'port': normalized_port,
                'username': user,
            'password': self._encrypt_secret(password),
                'mode': mode,
                'verify_ssl': str(verify_ssl),
                'ca_cert': self.QBT_CA_CERT or '',
                'default_save_path': default_save_path,
                'default_download_path': self.DEFAULT_DOWNLOAD_PATH or '',
            'default_category': default_category,
            'default_affected_feeds': feeds_str,
        }
        
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                cfg.write(f)
        except Exception as e:
            logger.error(f"Failed to save config to INI: {e}")
            return False

        self.QBT_PROTOCOL, self.QBT_HOST, self.QBT_PORT, self.QBT_USER, self.QBT_PASS, self.CONNECTION_MODE, self.QBT_VERIFY_SSL = (
            protocol, host, normalized_port, user, password, mode, verify_ssl
        )
        self.DEFAULT_SAVE_PATH = default_save_path
        self.DEFAULT_CATEGORY = default_category
        self.DEFAULT_AFFECTED_FEEDS = default_affected_feeds or []
        logger.info(f"Saved qBittorrent config: {protocol}://{host}:{normalized_port} (mode: {mode})")
        return True

    def save_platform_config(self, main_server: str, export_targets: List[str]) -> bool:
        """
        Save preferred main server and export targets.

        Args:
            main_server: Preferred server identifier
            export_targets: List of enabled export targets

        Returns:
            True if saved successfully
        """
        try:
            normalized_main = str(main_server or 'qbittorrent').strip().lower()
            if normalized_main not in self.SUPPORTED_SERVERS:
                normalized_main = 'qbittorrent'

            normalized_targets: List[str] = []
            for target in export_targets or []:
                target_norm = str(target).strip().lower()
                if target_norm in self.SUPPORTED_SERVERS and target_norm not in normalized_targets:
                    normalized_targets.append(target_norm)
            if not normalized_targets:
                normalized_targets = ['sonarr']

            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)
            if 'PLATFORM' not in cfg:
                cfg.add_section('PLATFORM')

            cfg['PLATFORM'] = {
                'main_server': normalized_main,
                'export_targets': ', '.join(normalized_targets),
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)

            self.MAIN_SERVER = normalized_main
            self.EXPORT_TARGETS = normalized_targets
            return True
        except Exception as e:
            logger.error(f"Failed to save platform config: {e}")
            return False
    
    def save_sonarr_config(self, url: str, api_key: str, quality_profile: Optional[int] = None,
                          root_folder: Optional[str] = None, monitor_mode: str = 'all',
                          search_on_add: bool = False) -> bool:
        """
        Saves Sonarr connection configuration to config.ini file.
        
        Args:
            url: Sonarr URL (e.g., http://localhost:8989)
            api_key: Sonarr API key
            quality_profile: Quality profile ID
            root_folder: Root folder path
            monitor_mode: Monitor mode (all, future, missing, existing, none)
            search_on_add: Whether to search for missing episodes on add
            
        Returns:
            bool: True if saved successfully
        """
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)
            
            if 'SONARR' not in cfg:
                cfg.add_section('SONARR')
            
            cfg['SONARR'] = {
                'url': url,
                'api_key': self._encrypt_secret(api_key),
                'quality_profile': str(quality_profile) if quality_profile else '',
                'root_folder': root_folder or '',
                'monitor_mode': monitor_mode,
                'search_on_add': str(search_on_add)
            }
            
            with open(self.CONFIG_FILE, 'w') as f:
                cfg.write(f)
            
            self.SONARR_URL = url
            self.SONARR_API_KEY = api_key
            self.SONARR_QUALITY_PROFILE = quality_profile
            self.SONARR_ROOT_FOLDER = root_folder
            self.SONARR_MONITOR_MODE = monitor_mode
            self.SONARR_SEARCH_ON_ADD = search_on_add
            
            logger.info(f"Saved Sonarr config: {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to save Sonarr config: {e}")
            return False

    def save_deluge_config(
        self,
        protocol: str,
        host: str,
        port: str,
        password: str,
        verify_ssl: bool,
    ) -> bool:
        """Save Deluge API connection configuration to config.ini."""
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE)

            if 'DELUGE_API' not in cfg:
                cfg.add_section('DELUGE_API')

            cfg['DELUGE_API'] = {
                'protocol': (protocol or 'http').strip() or 'http',
                'host': (host or 'localhost').strip() or 'localhost',
                'port': str(port or '8112').strip() or '8112',
                'password': password or '',
                'verify_ssl': str(bool(verify_ssl)),
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)

            self.DELUGE_PROTOCOL = cfg['DELUGE_API']['protocol']
            self.DELUGE_HOST = cfg['DELUGE_API']['host']
            self.DELUGE_PORT = cfg['DELUGE_API']['port']
            self.DELUGE_PASSWORD = cfg['DELUGE_API']['password']
            self.DELUGE_VERIFY_SSL = bool(verify_ssl)
            return True
        except Exception as e:
            logger.error(f"Failed to save Deluge config: {e}")
            return False
    
    def save_cached_categories(self, categories: Dict[str, Any]) -> bool:
        """Save cached categories to file."""
        try:
            cache = self._load_cache_data()
            cache[CacheKeys.CATEGORIES] = categories
            self._save_cache_data(cache)
            self.CACHED_CATEGORIES = categories
            logger.info(f"Saved {len(categories)} cached categories")
            return True
        except Exception as e:
            logger.error(f"Failed to save cached categories: {e}")
            return False
    
    def save_cached_feeds(self, feeds: Dict[str, Any]) -> bool:
        """Save cached feeds to file."""
        try:
            cache = self._load_cache_data()
            cache[CacheKeys.FEEDS] = feeds
            self._save_cache_data(cache)
            self.CACHED_FEEDS = feeds
            logger.info(f"Saved {len(feeds)} cached feeds")
            return True
        except Exception as e:
            logger.error(f"Failed to save cached feeds: {e}")
            return False
    
    def load_recent_files(self) -> None:
        """Load recent files list from cache."""
        try:
            cache = self._load_cache_data()
            self.RECENT_FILES = cache.get(CacheKeys.RECENT_FILES, [])
            logger.info(f"Loaded {len(self.RECENT_FILES)} recent files")
        except Exception as e:
            logger.error(f"Failed to load recent files: {e}")
            self.RECENT_FILES = []
    
    def clear_recent_files(self) -> bool:
        """Clear the recent files list."""
        try:
            self.RECENT_FILES = []
            cache = self._load_cache_data()
            cache[CacheKeys.RECENT_FILES] = []
            self._save_cache_data(cache)
            logger.info("Cleared recent files list")
            return True
        except Exception as e:
            logger.error(f"Failed to clear recent files: {e}")
            return False


# Global config instance
config = AppConfig()
