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
        self.CACHE_FILE: str = 'cache.json'
        self.LEGACY_CACHE_FILE: str = 'seasonal_cache.json'
        self.BOOTSTRAPPED_CONFIG: bool = False
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
        
        # Platform configuration
        self.SUPPORTED_SERVERS: List[str] = ['qbittorrent', 'autobrr']
        self.MAIN_SERVER: str = 'qbittorrent'
        self.EXPORT_TARGETS: List[str] = ['qbittorrent']
        
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

            if 'QBITTORRENT_API' in cfg:
                qbt_password = str(cfg['QBITTORRENT_API'].get('password', '') or '')

            for value in (qbt_password,):
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
            if 'QBITTORRENT_API' in cfg:
                qbt_plain = _decrypt_existing(cfg['QBITTORRENT_API'].get('password', ''))

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

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)

            self._encryption_fallback_active = False
            self._encryption_fallback_reason = ''
            return True
        except Exception as e:
            logger.error(f"Failed rotating secret key: {e}")
            return False
    
    def get_pref(self, key: str, default: Any = None) -> Any:
        """Get a preference value with fallback from config.ini."""
        prefs = self._load_ini_prefs()
        return prefs.get(key, default)
    
    def set_pref(self, key: str, value: Any) -> bool:
        """Set a preference value in config.ini."""
        try:
            prefs = self._load_ini_prefs()
            prefs[key] = value
            return self._save_ini_prefs(prefs)
        except Exception as e:
            logger.error(f"Failed to set preference '{key}': {e}")
            return False

    def _load_ini_prefs(self) -> Dict[str, Any]:
        """Load serialized preferences from config.ini."""
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')
            if 'PREFERENCES' not in cfg:
                return {}

            raw = str(cfg['PREFERENCES'].get('values_json', '{}') or '{}')
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except Exception as e:
            logger.error(f"Failed to load preferences from config.ini: {e}")
            return {}

    def _save_ini_prefs(self, prefs: Dict[str, Any]) -> bool:
        """Persist serialized preferences into config.ini."""
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')
            if 'PREFERENCES' not in cfg:
                cfg.add_section('PREFERENCES')

            cfg['PREFERENCES'] = {
                'values_json': json.dumps(prefs or {}, ensure_ascii=False)
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            return True
        except Exception as e:
            logger.error(f"Failed to save preferences to config.ini: {e}")
            return False

    def _migrate_cache_prefs_to_ini(self) -> None:
        """Move legacy preferences from cache into config.ini and clear old key."""
        try:
            cache = self._load_cache_data()
            legacy_prefs = cache.get(CacheKeys.PREFS, {})
            if not isinstance(legacy_prefs, dict):
                return

            if legacy_prefs:
                current = self._load_ini_prefs()
                changed = False
                for pref_key, pref_value in legacy_prefs.items():
                    # Connection profiles have a dedicated migration path.
                    if pref_key == 'connection_profiles':
                        continue
                    if pref_key not in current:
                        current[pref_key] = pref_value
                        changed = True
                if changed:
                    self._save_ini_prefs(current)

            # Remove legacy preference payload from cache once processed.
            if CacheKeys.PREFS in cache:
                del cache[CacheKeys.PREFS]
                self._save_cache_data(cache)
        except Exception as e:
            logger.error(f"Failed migrating legacy preferences from cache: {e}")

    def load_connection_profiles(self) -> List[Dict[str, Any]]:
        """Load connection profiles from config.ini with legacy cache fallback."""
        # Preferred source: config.ini
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')
            if 'CONNECTION_PROFILES' in cfg:
                raw = str(cfg['CONNECTION_PROFILES'].get('profiles_json', '[]') or '[]')
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    profiles: List[Dict[str, Any]] = []
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        profile = dict(item)
                        profile['password'] = self._decrypt_secret(str(profile.get('password', '') or ''))
                        profiles.append(profile)
                    return profiles
        except Exception as e:
            logger.error(f"Failed reading connection profiles from config.ini: {e}")

        # Legacy source: seasonal_cache.json prefs.connection_profiles
        try:
            cache = self._load_cache_data()
            prefs = cache.get(CacheKeys.PREFS, {})
            legacy = prefs.get('connection_profiles', []) if isinstance(prefs, dict) else []
            if isinstance(legacy, list):
                if legacy:
                    # Migrate to config.ini then clear legacy cache key.
                    self.save_connection_profiles(legacy)
                if isinstance(prefs, dict) and 'connection_profiles' in prefs:
                    del prefs['connection_profiles']
                    self._save_cache_data(cache)
                return [p for p in legacy if isinstance(p, dict)]
        except Exception as e:
            logger.error(f"Failed migrating legacy connection profiles: {e}")

        return []

    def save_connection_profiles(self, profiles: List[Dict[str, Any]]) -> bool:
        """Save connection profiles to config.ini with encrypted passwords."""
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')

            encoded_profiles: List[Dict[str, Any]] = []
            for profile in profiles or []:
                if not isinstance(profile, dict):
                    continue
                p = dict(profile)
                p['password'] = self._encrypt_secret(str(p.get('password', '') or ''))
                encoded_profiles.append(p)

            if 'CONNECTION_PROFILES' not in cfg:
                cfg.add_section('CONNECTION_PROFILES')

            cfg['CONNECTION_PROFILES'] = {
                'profiles_json': json.dumps(encoded_profiles)
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            return True
        except Exception as e:
            logger.error(f"Failed saving connection profiles to config.ini: {e}")
            return False
    
    def _load_cache_data(self) -> Dict[str, Any]:
        """Load cache data from file."""
        try:
            if not os.path.exists(self.CACHE_FILE) and os.path.exists(self.LEGACY_CACHE_FILE):
                os.replace(self.LEGACY_CACHE_FILE, self.CACHE_FILE)
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
            self.BOOTSTRAPPED_CONFIG = False
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
                self.BOOTSTRAPPED_CONFIG = True
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
            
            # Load platform/server preferences
            if 'PLATFORM' in cfg:
                platform_cfg = cfg['PLATFORM']
                main_server = str(platform_cfg.get('main_server', 'qbittorrent')).strip().lower()
                if main_server in self.SUPPORTED_SERVERS:
                    self.MAIN_SERVER = main_server
                else:
                    self.MAIN_SERVER = 'qbittorrent'

                export_targets_raw = str(platform_cfg.get('export_targets', 'qbittorrent')).strip()
                parsed_targets = [t.strip().lower() for t in export_targets_raw.split(',') if t.strip()]
                parsed_targets = [t for t in parsed_targets if t in self.SUPPORTED_SERVERS]
                self.EXPORT_TARGETS = parsed_targets or ['qbittorrent']
            else:
                self.MAIN_SERVER = 'qbittorrent'
                self.EXPORT_TARGETS = ['qbittorrent']

            if migration_needed:
                self._persist_encrypted_secrets()

            # Ensure legacy cache-stored configuration is moved into config.ini.
            self.load_connection_profiles()
            self._migrate_cache_prefs_to_ini()

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
                normalized_targets = ['qbittorrent']

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
