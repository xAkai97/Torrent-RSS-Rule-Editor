"""
Application Configuration Manager — The Central Nervous System.

This module is the single source of truth for all persistent application state.
It manages:

1. **Connection settings** — qBittorrent server address, credentials, SSL config
2. **User preferences** — UI settings, cooldown timers, display options
3. **Cached data** — categories, feeds, recent files (stored in cache.json)
4. **Title library** — the user's anime list with rule definitions (ALL_TITLES)
5. **Connection profiles** — saved server configs for switching between servers
6. **Secret encryption** — password encryption at rest using Fernet symmetric keys

Storage files:
  - data/config.ini             → Connection settings, preferences, connection profiles
  - data/cache.json             → Cached categories, feeds, recent files, templates
  - data/.app_secret.key        → Fernet encryption key for password storage
  - data/qbittorrent_rules.json → Auto-saved/exported rules config

Architecture note:
  A single global `config` instance (AppConfig) is created at module load time
  and imported throughout the app via `from src.config import config`. This acts
  as a shared state container — the GUI reads from it, services write to it,
  and changes are persisted to disk automatically.

Legacy migration:
  The app originally stored config files in the project root. On startup,
  files are automatically migrated to the data/ subdirectory.
"""

# Standard library imports
import copy
import shutil
import threading
from datetime import datetime
import json
import logging
import os
from configparser import ConfigParser
from typing import Any, Dict, List, Optional

# Optional dependency: cryptography library for password encryption at rest.
# If not installed, passwords are stored in plaintext (with a warning).
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]

# Local application imports
from .constants import CacheKeys

logger = logging.getLogger(__name__)


class AppConfig:
    """
    Central configuration manager for the entire application.

    Holds all settings, connection details, cached data, and the user's title
    library in memory. Provides methods to load from and save to disk.

    This class is instantiated once as a module-level singleton (`config`)
    and shared across all modules via import.
    """

    def __init__(self):
        # Thread-safe lock for async cache writes (prevents file corruption)
        self._cache_write_lock = threading.Lock()

        # Ensure the data/ directory exists for storing config files
        os.makedirs("data", exist_ok=True)

        # --- Legacy file migration ---
        # The app used to store config files in the project root directory.
        # On first run after update, move them into data/ for cleaner organization.
        legacy_files = ['config.ini', '.app_secret.key', 'cache.json', 'seasonal_cache.json', 'qbt_editor.log', 'qbittorrent_rules.json']
        for file in legacy_files:
            if os.path.exists(file):
                try:
                    dest = os.path.join("data", file)
                    if not os.path.exists(dest):
                        shutil.move(file, dest)
                        logger.info(f"Successfully migrated legacy file '{file}' to 'data/{file}'")
                    else:
                        os.remove(file)  # Remove duplicate if already migrated
                except Exception as e:
                    logger.warning(f"Failed to migrate legacy file '{file}' to data/ folder: {e}")

        # --- File paths ---
        self.CONFIG_FILE: str = os.path.join('data', 'config.ini')       # Main configuration file
        self.SECRET_KEY_FILE: str = '.app_secret.key'                     # Encryption key (relative to CONFIG_FILE's dir)
        self.OUTPUT_CONFIG_FILE_NAME: str = os.path.join('data', 'qbittorrent_rules.json')  # Default export filename
        self.CACHE_FILE: str = os.path.join('data', 'cache.json')         # Cache storage file
        self.LEGACY_CACHE_FILE: str = os.path.join('data', 'seasonal_cache.json')  # Old cache filename
        self.LOG_FILE: str = os.path.join('data', 'qbt_editor.log')       # Application log file

        # Whether config.ini was just created for the first time (first-run flag)
        self.BOOTSTRAPPED_CONFIG: bool = False

        # Encryption fallback state — tracks whether we had to fall back to plaintext
        self._encryption_fallback_active: bool = False
        self._encryption_fallback_reason: str = ''

        # --- Default values for new rules ---
        self.DEFAULT_RSS_FEED: str = ""           # RSS feed URL used when creating new rules
        self.DEFAULT_SAVE_PATH: str = ""           # Default download directory for new rules
        self.DEFAULT_DOWNLOAD_PATH: str = ""       # qBittorrent's base download path (used as prefix)
        self.DEFAULT_CATEGORY: str = ""            # Default category assigned to new rules
        self.DEFAULT_AFFECTED_FEEDS: List[str] = []  # List of feed URLs assigned to new rules

        # --- qBittorrent connection settings ---
        self.QBT_PROTOCOL: Optional[str] = None    # 'http' or 'https'
        self.QBT_HOST: Optional[str] = None         # Server hostname or IP
        self.QBT_PORT: Optional[str] = None          # WebUI port (usually 8080)
        self.QBT_USER: Optional[str] = None          # WebUI username
        self.QBT_PASS: Optional[str] = None          # WebUI password (decrypted in memory)
        self.QBT_VERIFY_SSL: bool = True              # Whether to verify SSL certificates
        self.CONNECTION_MODE: str = 'online'          # 'online' (connect to server) or 'offline' (local editing only)
        self.QBT_CA_CERT: Optional[str] = None       # Custom CA certificate file path

        # --- Platform configuration ---
        self.SUPPORTED_SERVERS: List[str] = ['qbittorrent']  # Available torrent client backends
        self.MAIN_SERVER: str = 'qbittorrent'                 # Currently selected backend
        self.EXPORT_TARGETS: List[str] = ['qbittorrent']     # Where to export/sync rules

        # --- In-memory application state ---
        self.RECENT_FILES: List[str] = []               # Recently opened rule file paths
        self.CACHED_CATEGORIES: Dict[str, Any] = {}     # qBittorrent categories (loaded from cache)
        self.CACHED_FEEDS: Dict[str, Any] = {}          # qBittorrent RSS feeds (loaded from cache)

        # --- ALL_TITLES: The user's anime/media library ---
        # This is the main data structure the GUI works with. It uses a hybrid format
        # where each entry contains both qBittorrent rule fields AND internal tracking
        # fields for GUI display.
        #
        # Structure:
        # {
        #   'existing': [  # or 'anime', 'manga', etc. (media type groups)
        #     {
        #       # --- qBittorrent rule fields (sent to server) ---
        #       'mustContain': 'Title',              # RSS match pattern
        #       'savePath': '/path/to/save',         # Download directory
        #       'assignedCategory': 'Category',      # Torrent category
        #       'enabled': True,                     # Rule active/inactive
        #       'affectedFeeds': ['url'],            # RSS feeds to watch
        #       'torrentParams': {...},              # Speed/ratio limits
        #
        #       # --- Internal tracking fields (filtered out on export) ---
        #       'node': {'title': 'Display Title'},  # Used for treeview display
        #       'ruleName': 'Title'                  # Original rule name from qBittorrent
        #     }
        #   ]
        # }
        #
        # IMPORTANT: When exporting or previewing, the internal fields ('node', 'ruleName')
        # must be filtered out to produce clean qBittorrent-compatible JSON.
        # See file_operations.py: _show_preview_dialog() for the filtering logic.
        self.ALL_TITLES: Dict[str, List[Any]] = {}

        # --- qBittorrent API endpoint paths (duplicated here for legacy compatibility) ---
        self.QBT_AUTH_LOGIN: str = "/api/v2/auth/login"
        self.QBT_TORRENTS_CATEGORIES: str = "/api/v2/torrents/categories"
        self.QBT_RSS_FEEDS: str = "/api/v2/rss/items"
        self.QBT_RSS_RULES: str = "/api/v2/rss/rules"
        self.QBT_API_BASE: str = "/api/v2"

        # --- In-memory caches for performance ---
        self._cached_prefs = None           # Loaded preferences dict (avoids re-reading config.ini)
        self._cache_data_in_memory = None   # Loaded cache.json dict (avoids re-reading from disk)

    # ========================================================================
    # Secret encryption — protects passwords stored in config.ini
    #
    # Uses Fernet symmetric encryption from the `cryptography` library.
    # A randomly generated key is stored in .app_secret.key alongside config.ini.
    # Encrypted values in config.ini are prefixed with "enc:" so we can tell
    # them apart from plaintext values.
    # ========================================================================

    def _secret_key_path(self) -> str:
        """Return the absolute path to the encryption key file."""
        cfg_dir = os.path.dirname(os.path.abspath(self.CONFIG_FILE)) or os.getcwd()
        return os.path.join(cfg_dir, self.SECRET_KEY_FILE)

    def _get_cipher(self) -> Any:
        """
        Get a Fernet cipher instance for encrypting/decrypting secrets.

        If the key file doesn't exist yet, a new random key is generated.
        If the cryptography library isn't installed, returns None and sets
        the fallback flag so the app knows encryption is unavailable.

        Returns:
            A Fernet cipher instance, or None if encryption is unavailable.
        """
        if Fernet is None:
            self._encryption_fallback_active = True
            self._encryption_fallback_reason = 'cryptography dependency not installed'
            return None

        key_path = self._secret_key_path()
        try:
            if os.path.exists(key_path):
                # Load existing key from file
                with open(key_path, 'rb') as f:
                    key = f.read().strip()
            else:
                # First run: generate a new random encryption key
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
        """
        Encrypt a secret value for storage in config.ini.

        Values already encrypted (starting with "enc:") are returned as-is.
        If encryption is unavailable, the plaintext value is returned.

        Args:
            value: The plaintext secret to encrypt.

        Returns:
            The encrypted string prefixed with "enc:", or the original
            plaintext if encryption failed or is unavailable.
        """
        if not value:
            return ''
        if value.startswith('enc:'):
            return value  # Already encrypted

        cipher = self._get_cipher()
        if not cipher:
            return value  # Can't encrypt — store as plaintext

        try:
            token = cipher.encrypt(value.encode('utf-8'))
            return 'enc:' + token.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to encrypt secret, storing plaintext: {e}")
            return value

    def _decrypt_secret(self, value: str) -> str:
        """
        Decrypt a secret value loaded from config.ini.

        Only processes values with the "enc:" prefix. Plaintext values
        are returned unchanged (for backward compatibility with old configs).

        Args:
            value: The value from config.ini (may or may not be encrypted).

        Returns:
            The decrypted plaintext string.
        """
        if not value:
            return ''
        if not value.startswith('enc:'):
            return value  # Not encrypted — return as-is

        cipher = self._get_cipher()
        if not cipher:
            return value  # Can't decrypt without the cipher

        try:
            token = value[4:].encode('utf-8')  # Strip the "enc:" prefix
            return cipher.decrypt(token).decode('utf-8')
        except InvalidToken:
            logger.warning("Failed to decrypt secret (invalid token); keeping raw value")
            return value
        except Exception as e:
            logger.warning(f"Failed to decrypt secret: {e}")
            return value

    def _persist_encrypted_secrets(self) -> bool:
        """
        Re-read config.ini and encrypt any plaintext secrets found.

        This is called automatically during load_config() when plaintext
        passwords are detected. It's a one-time migration step.

        Returns:
            True if any secrets were migrated, False otherwise.
        """
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



            if changed:
                with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                    cfg.write(f)
                logger.info("Migrated plaintext secrets to encrypted config entries")
            return changed
        except Exception as e:
            logger.warning(f"Failed to persist encrypted secrets migration: {e}")
            return False

    # ========================================================================
    # Encryption status inquiry methods — used by the settings UI
    # ========================================================================

    def is_secret_encryption_available(self) -> bool:
        """Check if the cryptography library is installed and encryption can be used."""
        return Fernet is not None

    def has_plaintext_secrets(self) -> bool:
        """
        Check if config.ini still has any passwords stored in plaintext.

        Used by the settings UI to show a warning banner when secrets
        aren't encrypted.
        """
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
        """Manually trigger encryption of any plaintext secrets in config.ini."""
        return self._persist_encrypted_secrets()

    def is_plaintext_fallback_active(self) -> bool:
        """Check if the app had to fall back to plaintext password storage."""
        return bool(self._encryption_fallback_active)

    def get_plaintext_fallback_reason(self) -> str:
        """Get a human-readable explanation of why encryption isn't working."""
        return self._encryption_fallback_reason or 'Unknown encryption backend issue'

    def export_secret_key(self, destination_path: str) -> bool:
        """
        Copy the encryption key file to a user-chosen location for backup.

        If the user loses this key file, they won't be able to decrypt
        passwords in their config.ini. This lets them back it up.

        Args:
            destination_path: Where to save the copy of the key file.

        Returns:
            True if the export was successful.
        """
        try:
            source = self._secret_key_path()
            if not os.path.exists(source):
                # Key doesn't exist yet — create it first
                if not self._get_cipher():
                    return False
            source = self._secret_key_path()
            shutil.copy2(source, destination_path)
            return True
        except Exception as e:
            logger.error(f"Failed to export secret key: {e}")
            return False

    def rotate_secret_key(self) -> bool:
        """
        Generate a new encryption key and re-encrypt all stored secrets.

        This is a security best practice — the old key is backed up with
        a timestamp suffix (e.g. .app_secret.key.20260612153000.bak)
        before being replaced.

        Steps:
          1. Read and decrypt all secrets using the old key
          2. Generate a new random key
          3. Back up the old key file
          4. Write the new key
          5. Re-encrypt all secrets with the new key
          6. Save the updated config.ini

        Returns:
            True if rotation was successful, False on any error.
        """
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
                """Decrypt a value using the OLD key (before rotation)."""
                if not value:
                    return ''
                if not str(value).startswith('enc:'):
                    return str(value)
                token = str(value)[4:].encode('utf-8')
                if not old_cipher:
                    raise ValueError('No existing key available to decrypt current encrypted secrets')
                return old_cipher.decrypt(token).decode('utf-8')

            # Step 1: Decrypt existing secrets with the old key
            qbt_plain = ''
            if 'QBITTORRENT_API' in cfg:
                qbt_plain = _decrypt_existing(cfg['QBITTORRENT_API'].get('password', ''))

            # Step 2-3: Generate new key and back up old one
            new_key = Fernet.generate_key()
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            if os.path.exists(key_path):
                shutil.copy2(key_path, f"{key_path}.{timestamp}.bak")
            with open(key_path, 'wb') as f:
                f.write(new_key)

            # Step 4: Re-encrypt secrets with the new key
            new_cipher = Fernet(new_key)
            if 'QBITTORRENT_API' in cfg:
                cfg['QBITTORRENT_API']['password'] = (
                    'enc:' + new_cipher.encrypt(qbt_plain.encode('utf-8')).decode('utf-8') if qbt_plain else ''
                )

            # Step 5: Save updated config.ini
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)

            self._encryption_fallback_active = False
            self._encryption_fallback_reason = ''
            return True
        except Exception as e:
            logger.error(f"Failed rotating secret key: {e}")
            return False

    # ========================================================================
    # User Preferences — stored in the [PREFERENCES] section of config.ini
    #
    # Preferences use a simple key-value format with automatic type detection:
    # booleans are stored as "true"/"false", numbers as digits, and complex
    # values (lists, dicts) as JSON strings.
    # ========================================================================

    def get_pref(self, key: str, default: Any = None) -> Any:
        """
        Read a single user preference value.

        Lazy-loads preferences from config.ini on first access, then
        serves from the in-memory cache for performance.

        Args:
            key: The preference key name.
            default: Value to return if the key doesn't exist.

        Returns:
            The preference value (auto-typed: bool, int, float, str, dict, or list).
        """
        if self._cached_prefs is None:
            self._cached_prefs = self._load_ini_prefs()
        return self._cached_prefs.get(key, default)

    def set_pref(self, key: str, value: Any) -> bool:
        """
        Write a single user preference value and persist to disk.

        Updates both the in-memory cache and config.ini on disk.

        Args:
            key: The preference key name.
            value: The value to store.

        Returns:
            True if the preference was saved successfully.
        """
        try:
            if self._cached_prefs is None:
                self._cached_prefs = self._load_ini_prefs()
            self._cached_prefs[key] = value
            return self._save_ini_prefs(self._cached_prefs)
        except Exception as e:
            logger.error(f"Failed to set preference '{key}': {e}")
            return False

    def _load_ini_prefs(self) -> Dict[str, Any]:
        """
        Load preferences from the [PREFERENCES] section of config.ini.

        Handles two formats for backward compatibility:
          - Legacy: a single 'values_json' key containing all prefs as JSON
          - Current: individual keys with auto-type detection

        Auto-type detection converts:
          - "true"/"false" → Python bool
          - Numeric strings → int or float
          - JSON strings (starting with { or [) → dict or list
          - Everything else → str

        Returns:
            A dictionary of all preferences with automatically typed values.
        """
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')
            if 'PREFERENCES' not in cfg:
                return {}

            pref_section = cfg['PREFERENCES']

            # Handle legacy format: all prefs stored as a single JSON blob
            if 'values_json' in pref_section:
                raw = str(pref_section.get('values_json', '{}') or '{}')
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    # Auto-migrate: save in the new native format immediately
                    self._cached_prefs = parsed
                    self._save_ini_prefs(parsed)
                    return parsed

            # Current format: parse each key individually with type detection
            prefs = {}
            for key, val in pref_section.items():
                val_str = str(val).strip()

                # Try parsing as JSON object or array
                if (val_str.startswith('{') and val_str.endswith('}')) or (val_str.startswith('[') and val_str.endswith(']')):
                    try:
                        prefs[key] = json.loads(val_str)
                        continue
                    except Exception:
                        pass

                # Try parsing as boolean
                if val_str.lower() == 'true':
                    prefs[key] = True
                elif val_str.lower() == 'false':
                    prefs[key] = False
                else:
                    # Try parsing as number (float if has decimal, int otherwise)
                    try:
                        if '.' in val_str:
                            prefs[key] = float(val_str)
                        else:
                            prefs[key] = int(val_str)
                    except ValueError:
                        prefs[key] = val_str  # Keep as string
            return prefs
        except Exception as e:
            logger.error(f"Failed to load preferences from config.ini: {e}")
            return {}

    def _save_ini_prefs(self, prefs: Dict[str, Any]) -> bool:
        """
        Write all preferences to the [PREFERENCES] section of config.ini.

        Each value is serialized based on its Python type:
          - dict/list → JSON string
          - bool → "true" or "false"
          - everything else → str()

        The entire PREFERENCES section is replaced (not merged) to ensure
        deleted preferences are actually removed from the file.

        Returns:
            True if the save was successful.
        """
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')
            if 'PREFERENCES' not in cfg:
                cfg.add_section('PREFERENCES')

            # Clear the entire section and repopulate with current values
            cfg['PREFERENCES'] = {}

            for key, val in (prefs or {}).items():
                if isinstance(val, (dict, list)):
                    cfg['PREFERENCES'][key] = json.dumps(val, ensure_ascii=False)
                elif isinstance(val, bool):
                    cfg['PREFERENCES'][key] = 'true' if val else 'false'
                else:
                    cfg['PREFERENCES'][key] = str(val)

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            return True
        except Exception as e:
            logger.error(f"Failed to save preferences to config.ini: {e}")
            return False

    def _migrate_cache_prefs_to_ini(self) -> None:
        """
        Move legacy preferences from cache.json into config.ini.

        Older app versions stored preferences in the cache file. This method
        migrates them to config.ini (the new location) and removes the old
        cache entry. Connection profiles are skipped here because they have
        their own dedicated migration path.
        """
        try:
            cache = self._load_cache_data()
            legacy_prefs = cache.get(CacheKeys.PREFS, {})
            if not isinstance(legacy_prefs, dict):
                return

            if legacy_prefs:
                current = self._load_ini_prefs()
                changed = False
                for pref_key, pref_value in legacy_prefs.items():
                    # Connection profiles have a separate migration path — skip them
                    if pref_key == 'connection_profiles':
                        continue
                    # Only migrate keys that don't already exist in config.ini
                    if pref_key not in current:
                        current[pref_key] = pref_value
                        changed = True
                if changed:
                    self._save_ini_prefs(current)

            # Clean up: remove the legacy prefs section from cache
            if CacheKeys.PREFS in cache:
                del cache[CacheKeys.PREFS]
                self._save_cache_data(cache)
        except Exception as e:
            logger.error(f"Failed migrating legacy preferences from cache: {e}")

    # ========================================================================
    # Connection Profiles — multiple saved server configurations
    #
    # Users can save multiple qBittorrent server configs and switch between
    # them (e.g. local server vs remote server). Passwords in profiles are
    # encrypted using the same Fernet key.
    # ========================================================================

    def load_connection_profiles(self) -> List[Dict[str, Any]]:
        """
        Load saved connection profiles from config.ini.

        Falls back to legacy storage (cache.json) if no profiles exist
        in config.ini yet, and auto-migrates them to the new location.

        Each profile is a dict with keys like:
          name, protocol, host, port, username, password, verify_ssl, etc.

        Passwords are decrypted in memory when loaded.

        Returns:
            A list of connection profile dictionaries.
        """
        # Try loading from config.ini (preferred location)
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
                        # Decrypt password for in-memory use
                        profile['password'] = self._decrypt_secret(str(profile.get('password', '') or ''))
                        profiles.append(profile)
                    return profiles
        except Exception as e:
            logger.error(f"Failed reading connection profiles from config.ini: {e}")

        # Fallback: try loading from legacy cache location
        try:
            cache = self._load_cache_data()
            prefs = cache.get(CacheKeys.PREFS, {})
            legacy = prefs.get('connection_profiles', []) if isinstance(prefs, dict) else []
            if isinstance(legacy, list):
                if legacy:
                    # Auto-migrate legacy profiles to config.ini
                    self.save_connection_profiles(legacy)
                # Clean up the legacy cache entry
                if isinstance(prefs, dict) and 'connection_profiles' in prefs:
                    del prefs['connection_profiles']
                    self._save_cache_data(cache)
                return [p for p in legacy if isinstance(p, dict)]
        except Exception as e:
            logger.error(f"Failed migrating legacy connection profiles: {e}")

        return []

    def save_connection_profiles(self, profiles: List[Dict[str, Any]]) -> bool:
        """
        Save connection profiles to config.ini with encrypted passwords.

        Passwords are encrypted before writing to disk, so the config.ini
        file never contains plaintext credentials (when encryption is available).

        Args:
            profiles: List of profile dictionaries to save.

        Returns:
            True if the save was successful.
        """
        try:
            cfg = ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding='utf-8')

            # Encrypt passwords before storing
            encoded_profiles: List[Dict[str, Any]] = []
            for profile in profiles or []:
                if not isinstance(profile, dict):
                    continue
                p = dict(profile)
                p['password'] = self._encrypt_secret(str(p.get('password', '') or ''))
                encoded_profiles.append(p)

            if 'CONNECTION_PROFILES' not in cfg:
                cfg.add_section('CONNECTION_PROFILES')

            # Store profiles as a single JSON string
            cfg['CONNECTION_PROFILES'] = {
                'profiles_json': json.dumps(encoded_profiles)
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            return True
        except Exception as e:
            logger.error(f"Failed saving connection profiles to config.ini: {e}")
            return False

    # ========================================================================
    # Cache file I/O — reading/writing cache.json
    #
    # The cache file stores non-critical data that can be regenerated:
    # categories, feeds, recent files, templates, and AniList title variations.
    #
    # Writes are done asynchronously in a background thread to avoid blocking
    # the GUI. A thread lock prevents concurrent writes from corrupting the file.
    # Atomic writes (write to .tmp then rename) prevent partial file corruption.
    # ========================================================================

    def _load_cache_data(self) -> Dict[str, Any]:
        """
        Load cache data from cache.json, with in-memory caching.

        On first call, reads from disk and caches in memory. Subsequent
        calls return the in-memory copy for performance.

        Also handles legacy migration: renames seasonal_cache.json → cache.json
        if the old file exists but the new one doesn't.

        Returns:
            The full cache dictionary, or empty dict on error.
        """
        if self._cache_data_in_memory is not None:
            return self._cache_data_in_memory
        try:
            # Legacy migration: rename old cache file
            if not os.path.exists(self.CACHE_FILE) and os.path.exists(self.LEGACY_CACHE_FILE):
                os.replace(self.LEGACY_CACHE_FILE, self.CACHE_FILE)
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self._cache_data_in_memory = json.load(f)
                    return self._cache_data_in_memory
        except Exception as e:
            logger.error(f"Failed to load cache file: {e}")
        self._cache_data_in_memory = {}
        return self._cache_data_in_memory

    def _save_cache_data(self, data: Dict[str, Any]) -> bool:
        """
        Save cache data to cache.json asynchronously in a background thread.

        The write is done atomically (write to .tmp file, then rename) to
        prevent corruption if the app crashes mid-write. A deep copy of
        the data is made so the background thread isn't affected by
        subsequent in-memory modifications.

        Args:
            data: The complete cache dictionary to write.

        Returns:
            True if the write was successfully queued (not necessarily completed).
        """
        try:
            # Deep copy for the background thread (data might change in memory while writing)
            data_copy = copy.deepcopy(data)
            # Update the in-memory cache only after deepcopy succeeds, to avoid
            # diverging in-memory vs on-disk state if deepcopy throws.
            self._cache_data_in_memory = data
            cache_file = self.CACHE_FILE  # Capture path to prevent race conditions

            def _write_thread():
                with self._cache_write_lock:
                    try:
                        # Atomic write: write to temp file first, then rename
                        temp_file = f"{cache_file}.tmp"
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(data_copy, f, indent=2)
                        os.replace(temp_file, cache_file)
                    except Exception as exc:
                        logger.error(f"Background thread failed writing cache file: {exc}")

            threading.Thread(target=_write_thread, daemon=True).start()
            return True
        except Exception as e:
            logger.error(f"Failed to save cache file: {e}")
            return False

    def flush_cache(self, timeout: float = 5.0) -> bool:
        """
        Wait for any pending background cache write to complete.

        Call this during app shutdown to make sure the last cache write
        finishes before the process exits. Since cache writes happen in
        daemon threads, they'd be killed on exit without this.

        Args:
            timeout: Maximum seconds to wait for the write to finish.

        Returns:
            True if the flush completed within the timeout, False if it timed out.
        """
        acquired = self._cache_write_lock.acquire(timeout=timeout)
        if acquired:
            self._cache_write_lock.release()
            return True
        logger.warning("flush_cache timed out waiting for pending cache write")
        return False

    # ========================================================================
    # Convenience methods for specific cache sections
    # ========================================================================

    def load_cached_categories(self) -> None:
        """Load cached qBittorrent categories from cache.json into memory."""
        cache = self._load_cache_data()
        self.CACHED_CATEGORIES = cache.get(CacheKeys.CATEGORIES, {})
        logger.info(f"Loaded {len(self.CACHED_CATEGORIES)} cached categories")

    def load_cached_feeds(self) -> None:
        """Load cached RSS feeds from cache.json into memory."""
        cache = self._load_cache_data()
        self.CACHED_FEEDS = cache.get(CacheKeys.FEEDS, {})
        logger.info(f"Loaded {len(self.CACHED_FEEDS)} cached feeds")

    def add_recent_file(self, filepath: str) -> None:
        """
        Add a file path to the recent files list and persist to cache.

        If already in the list, moves it to the top (most recently used).
        The list is capped at MAX_RECENT_FILES entries.
        """
        # Remove if already exists so it can be moved to the top
        if filepath in self.RECENT_FILES:
            self.RECENT_FILES.remove(filepath)

        # Insert at the front (most recent position) and trim
        self.RECENT_FILES.insert(0, filepath)
        from .constants import CacheLimits
        self.RECENT_FILES = self.RECENT_FILES[:CacheLimits.MAX_RECENT_FILES]

        # Persist to cache file
        cache = self._load_cache_data()
        cache[CacheKeys.RECENT_FILES] = self.RECENT_FILES
        self._save_cache_data(cache)
        logger.info(f"Added recent file: {filepath}")

    # ========================================================================
    # Main config load/save — reads/writes config.ini
    # ========================================================================

    def load_config(self) -> bool:
        """
        Load the full application configuration from config.ini.

        This is called once at app startup. It:
          1. Creates a default config.ini if one doesn't exist (first run)
          2. Reads all qBittorrent connection settings
          3. Decrypts the stored password
          4. Migrates plaintext passwords to encrypted form if needed
          5. Loads platform/server preferences
          6. Migrates any legacy data from old storage locations

        Returns:
            True if the config was loaded and has valid host + port,
            False otherwise (but defaults are still set).
        """
        try:
            # Reset in-memory caches so we load fresh from disk
            self._cached_prefs = None
            self._cache_data_in_memory = None
            self.BOOTSTRAPPED_CONFIG = False

            if not os.path.exists(self.CONFIG_FILE):
                # First-run: create a safe default config file
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

            # --- Load qBittorrent connection settings ---
            qbt_loaded = 'QBITTORRENT_API' in cfg
            migration_needed = False
            if qbt_loaded:
                qbt = cfg['QBITTORRENT_API']
                self.QBT_PROTOCOL = qbt.get('protocol', 'http')
                self.QBT_HOST = qbt.get('host', 'localhost')
                self.QBT_PORT = str(qbt.get('port', '8080')).strip() or '8080'
                self.QBT_USER = qbt.get('username', '')

                # Decrypt password; flag for migration if it's still plaintext
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

                # Default affected feeds are stored as a comma-separated string
                feeds_str = qbt.get('default_affected_feeds', '')
                self.DEFAULT_AFFECTED_FEEDS = [f.strip() for f in feeds_str.split(',') if f.strip()]

                logger.info(f"Loaded qBittorrent config: {self.QBT_PROTOCOL}://{self.QBT_HOST}:{self.QBT_PORT} (mode: {self.CONNECTION_MODE})")
            else:
                # No config section found — use safe defaults
                self.QBT_PROTOCOL, self.QBT_HOST, self.QBT_PORT = 'http', 'localhost', '8080'
                self.QBT_USER, self.QBT_PASS = '', ''
                self.QBT_VERIFY_SSL = False
                self.CONNECTION_MODE = 'online'
                logger.warning("No QBITTORRENT_API section found in config.ini, using defaults")

            # --- Load platform preferences ---
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

            # --- Post-load migrations ---
            # Encrypt plaintext passwords if found
            if migration_needed:
                self._persist_encrypted_secrets()

            # Migrate any legacy data from old storage locations
            self.load_connection_profiles()
            self._migrate_cache_prefs_to_ini()

            return bool(self.QBT_HOST and self.QBT_PORT)
        except Exception as e:
            logger.error(f"Failed to load config from INI: {e}")
            # Set safe defaults so the app can still run
            self.QBT_PROTOCOL, self.QBT_HOST, self.QBT_PORT = 'http', 'localhost', '8080'
            self.QBT_USER, self.QBT_PASS = '', ''
            self.CONNECTION_MODE = 'online'
            return False

    def save_config(self, protocol: str, host: str, port: str, user: str, password: str, mode: str, verify_ssl: bool,
                    default_save_path: str = '', default_category: str = '', default_affected_feeds: List[str] = None) -> bool:
        """
        Save qBittorrent connection configuration to config.ini.

        This writes the [QBITTORRENT_API] section with all connection parameters.
        The password is encrypted before writing if encryption is available.
        After writing to disk, the in-memory config values are also updated.

        Args:
            protocol: 'http' or 'https'
            host: qBittorrent server hostname or IP
            port: WebUI port number
            user: WebUI login username
            password: WebUI login password (will be encrypted on disk)
            mode: 'online' (connect to server) or 'offline' (local editing)
            verify_ssl: Whether to verify SSL certificates
            default_save_path: Default download directory for new rules
            default_category: Default category for new rules
            default_affected_feeds: Default feed URLs for new rules

        Returns:
            True if the save was successful.
        """
        cfg = ConfigParser()
        cfg.read(self.CONFIG_FILE)
        normalized_port = str(port).strip() or '8080'

        # Convert feed list to comma-separated string for INI storage
        feeds_str = ', '.join(default_affected_feeds) if default_affected_feeds else ''

        cfg['QBITTORRENT_API'] = {
            'protocol': protocol,
            'host': host,
            'port': normalized_port,
            'username': user,
            'password': self._encrypt_secret(password),  # Encrypt before storing
            'mode': mode,
            'verify_ssl': str(verify_ssl),
            'ca_cert': self.QBT_CA_CERT or '',
            'default_save_path': default_save_path,
            'default_download_path': self.DEFAULT_DOWNLOAD_PATH or '',
            'default_category': default_category,
            'default_affected_feeds': feeds_str,
        }

        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
        except Exception as e:
            logger.error(f"Failed to save config to INI: {e}")
            return False

        # Update in-memory values to match what was just saved
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
        Save platform preferences (main server and export targets) to config.ini.

        Args:
            main_server: The preferred torrent client backend (e.g. 'qbittorrent').
            export_targets: List of export target identifiers.

        Returns:
            True if the save was successful.
        """
        try:
            # Validate and normalize inputs
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

            # Update in-memory values
            self.MAIN_SERVER = normalized_main
            self.EXPORT_TARGETS = normalized_targets
            return True
        except Exception as e:
            logger.error(f"Failed to save platform config: {e}")
            return False

    def save_cached_categories(self, categories: Dict[str, Any]) -> bool:
        """Save qBittorrent categories to both cache file and in-memory state."""
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
        """Save RSS feeds to both cache file and in-memory state."""
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
        """Load the recent files list from cache.json into memory."""
        try:
            cache = self._load_cache_data()
            self.RECENT_FILES = cache.get(CacheKeys.RECENT_FILES, [])
            logger.info(f"Loaded {len(self.RECENT_FILES)} recent files")
        except Exception as e:
            logger.error(f"Failed to load recent files: {e}")
            self.RECENT_FILES = []

    def clear_recent_files(self) -> bool:
        """Clear the recent files list from both memory and cache file."""
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


# ============================================================================
# Global singleton instance
#
# This is created at module import time and shared across the entire app.
# All modules import it as: from src.config import config
# ============================================================================
config = AppConfig()
