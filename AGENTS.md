# AI Agent Architecture Summary

## 1. High-Level Overview
**Torrent-RSS-Rule-Editor** is a modular Python desktop application that serves as a visual editor and synchronizer for RSS rules in the qBittorrent client. It also acts as an automation bridge, pulling data from anime release schedules (SubsPlease) and querying AniList (via GraphQL) to auto-generate complex matching rules and language-specific regex patterns.

**Primary Technologies:**
- **Language:** Python 3.10+
- **GUI Framework:** PySide6 (Qt).
- **Key Libraries:** `requests` (API comms), `cryptography` (Fernet credential encryption).

---

## 2. Architecture & File Structure
The project strictly separates its logic into three main tiers:

### 2.1 Boundary Layer (`src/api/`)
Handles all external network API calls and web scraping. Configured with timeouts, retry limits, and robust exception-handling.
- **[qbittorrent.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/api/qbittorrent.py)**: Interacts with the qBittorrent WebUI v2 client. Manages login sessions, category listing/creation, feed retrieval, and RSS rule CRUD operations.
- **[subsplease.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/api/subsplease.py)**: Fetches broadcast schedules from SubsPlease and queries AniList's GraphQL API for show synonyms, aliases, and metadata.
- **[rss_fetcher.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/api/rss_fetcher.py)**: Downloads and parses standard XML RSS feeds. Supports regex-based HTML scraping on Nyaa.si (for historical items without beautifulsoup4 dependencies) and queries the SubsPlease JSON API.

### 2.2 Business Logic Layer (`src/services/`)
Orchestrates complex backend tasks. This layer contains the core logic of the app, is fully decoupled from the GUI, and is highly unit-tested.
- **[backup.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/backup.py)** (re-exported via [services/backup.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/backup.py)): Generates safety snapshots of server state (JSON files in `backups/` containing rules, feeds, and categories) before destructively writing to the server. Keeps the 10 most recent backups.
- **[batch_downloader.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/batch_downloader.py)**: Coordinates downloading historical episodes/torrent magnet links matching specific filters.
- **[connection_status.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/connection_status.py)**: Monitors current qBittorrent server connectivity state.
- **[file_operations.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/file_operations.py)**: Manages local file exports and imports, validating structure and filtering metadata pollution.
- **[language_detection.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/language_detection.py)**: Detects subtitle types (Sub, Dub, Raw, Dual-Audio) from torrent names.
- **[rule_drafts.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/rule_drafts.py)**: Manages the active rule edits (draft state).
- **[rule_editor.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/rule_editor.py)**: Processes and constructs mustContain/mustNotContain patterns, handles template creation, and generates rules.
- **[rule_sync_apply.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/rule_sync_apply.py)**: The sync engine. Calculates rule differences (Desired vs. Actual) and runs dry-runs of additions, modifications, and deletions.
- **[server_snapshot.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/services/server_snapshot.py)**: Takes active snapshot representations of qBittorrent server states.

### 2.3 Presentation Layer (`src/gui_qt/`)
PySide6 GUI widgets, views, and worker threads.
- **[main_window.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/gui_qt/main_window.py)**: The main entry window layout. Integrates tree views, drag-and-drop rule ordering, search filtering, and draft triggers. (Complex layout module: >240KB, 4000+ lines).
- **[settings_dialog.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/gui_qt/settings_dialog.py)**: Configures server settings, multi-server connection profiles, path rules, and credential encryption (rotation/key export).
- **[workers.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/gui_qt/workers.py)**: Standardizes asynchronous tasks using QThread workers to prevent blocking the GUI event loop (e.g., checking connection, querying AniList APIs, downloading files).
- **[theme.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/gui_qt/theme.py)**: Dynamically injects the visual aesthetic stylesheet and palettes.

### 2.4 Core & Utility Modules
- **[config.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/config.py)**: Singleton manager for persistent states (`AppConfig`). Handles configurations, preferences, connection profiles, and credential encryption.
- **[constants.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/constants.py)**: Holds configuration keys (`PrefKeys`, `CacheKeys`), exceptions, and OS file limitations.
- **[cache.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/cache.py)**: Thread-safe, disk-based cache manager using TTL expiry/size caps to avoid AniList rate limits.
- **[rss_rules.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/rss_rules.py)**: Contains the immutable `RSSRule` dataclass, supporting serialization and schema validation.
- **[utils.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/utils.py)**: Pure utility functions for title processing, path composition, duplicate checking, and platform-specific sanitization.

---

## 3. Lazy-Loading Import Optimization
To optimize application start times, **[src/\_\_init\_\_.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/__init__.py)** utilizes module-level `__getattr__` and a `_LAZY_ATTRS` registry map.
Heavy modules (like `gui_qt` or API packages that import PySide6/cryptography) are only imported dynamically when their attributes are first accessed. This keeps the initial launch responsive.

---

## 4. Data Models, State Management, and Encryption

### 4.1 Data Storage Directory (`data/`)
The application stores configuration and cached data inside a dedicated `data/` subdirectory. Legacy files located in the root are migrated automatically on startup:
1. **`data/config.ini`**: Main configuration file containing server connection settings, preferences, and multi-server profiles.
2. **`data/cache.json`**: Cache database tracking feeds, categories, rules templates, and AniList variations.
3. **`data/.app_secret.key`**: Fernet symmetric encryption key for encrypting credentials.
4. **`data/qbt_editor.log`**: Log output for debugging.

### 4.2 Credentials Security & Fernet Encryption
- App passwords are encrypted symmetrically using **Fernet** (256-bit AES via `cryptography` library) and stored in `config.ini` prefixed with `enc:`.
- If the `cryptography` library is missing, the application defaults to a plaintext fallback, flags this in `AppConfig._encryption_fallback_active`, and highlights a warning banner in the Settings UI.
- The UI in **[settings_dialog.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/src/gui_qt/settings_dialog.py)** enables manual key rotation and key export for secure backups.

### 4.3 Library State (`ALL_TITLES`)
`config.ALL_TITLES` maps media types to rules list.
- **Hybrid Format**: Entries contain both standard qBittorrent rule fields (`mustContain`, `savePath`) and internal tracking fields (`node` for tree view, `ruleName` for client syncing).
- **Sanitization**: Before writing to local JSON or uploading to qBittorrent, internal tracking fields must be removed.
  - `strip_internal_fields()` deletes `node` and `ruleName`.
  - `sanitize_entry_for_export()` aggressively strips any unexpected keys that leaked from AniList queries to prevent schema pollution.

---

## 5. Testing & Verification Strategy
- **Location:** `tests/` directory.
- **Style:** `pytest` with shared fixtures configured in **[conftest.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/tests/conftest.py)**.
- **Execution:** Automated tests are run using the custom runner script **[run_tests.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/run_tests.py)**.
  - Command: `D:\PythonEnvs\torrent-rss-rule-editor\Scripts\python.exe run_tests.py`
  - Quiet mode: `python run_tests.py -q`
- **Headless GUI Testing**: Because Qt views are difficult to instantiate headlessly in CI, testing focuses on service wrappers. The shell functions in [test_qt_preview_shell.py](file:///Y:/Code/Torrent-RSS-Rule-Editor/tests/test_qt_preview_shell.py) mock GUI interactions with core services.

---

## 6. Local Development Environment
If a local override file `AGENTS.local.md` exists in the repository root, AI agents MUST read it first to obtain machine-specific virtual environment paths, PowerShell profile commands, and other developer-specific environment details.