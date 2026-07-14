# TODO: Torrent RSS Rule Editor

## Active Work

### UI / UX Enhancements
- [ ] Add support for custom theme loading via external JSON color maps (allowing users to import and apply custom themes beyond light/dark presets).

### Testing & Infrastructure
- [ ] Modernize `test_integration.py` to convert script-like integration tests into standard pytest fixtures.

### Security, Recovery & Architecture
- [ ] Add credential key import/recovery UI paired with current key export flow.
- [ ] Add optional encrypted backup bundle for config + cache metadata.
- [ ] Refactor `src/gui_qt/main_window.py` (>4000 lines) by extracting UI components (wizard, settings dialog, tree-view helpers) into dedicated submodules.

---

### 🏗️ Architecture Improvements

- [x] **`QBittorrentClient` lacks context manager support**: The client requires manual `connect()` + `close()` pairing. High-level convenience functions (`fetch_categories`, `fetch_feeds`, `fetch_rules`, `ping_qbittorrent`) all duplicate the same connect/try/close pattern across ~100 lines of nearly identical code. Add `__enter__`/`__exit__` to `QBittorrentClient` and factor out a `_with_temp_client()` helper.
- [ ] **Duplicated connection-param extraction pattern**: At least 4 locations (`rule_sync_apply.py:apply_rule_sync_plan()`, `server_snapshot.py:load_qbittorrent_snapshot()`, and the convenience functions in `qbittorrent.py`) manually extract `protocol/host/port/user/pass/verify_ssl/ca_cert` from `config`. Centralize this into `connection_status.build_qbittorrent_ping_args()` and use it everywhere.
- [ ] **Dual cache API creates confusion**: Both `src/cache.py` (module-level functions) and `config.AppConfig` (instance methods) expose `load_cached_categories()`, `save_cached_categories()`, etc. with slightly different signatures. Callers need to know which to use. Consolidate to one canonical API.
- [ ] **`backup.py` path resolution is fragile**: `DEFAULT_BACKUP_DIR` uses `os.path.dirname(__file__)` + `'..'` which resolves relative to wherever `src/backup.py` lives. If the module is imported from a different working directory or bundled with PyInstaller, this may not point to the project root. Consider anchoring to a well-known location from config.
- [ ] **`settings_dialog.py` is 111KB / ~3200 lines**: Like `main_window.py`, this is a large monolith. Consider extracting tab panels (connection, encryption, theming, profile management) into separate widget classes.

### 🚀 Enhancement Suggestions

- [ ] **Add structured logging with `logging.handlers.RotatingFileHandler`**: Currently using `basicConfig` with a single log file. Log files will grow unbounded. Switch to `RotatingFileHandler` with a configurable max size (e.g., 5MB) and backup count.
- [ ] **Add a `--dry-run` CLI flag**: Allow running sync operations from the command line without the GUI for scripting/automation use cases.
- [ ] **Add connection retry with exponential backoff**: `qbittorrent.py` sets `max_retries: 0`. For transient network issues (especially on remote/NAS servers), a retry with backoff (e.g., 1-2-4 seconds, max 3 attempts) would improve robustness.
- [ ] **Add schema versioning to `cache.json`**: There's no version field in the cache file, making it hard to detect and migrate incompatible cache formats after upgrades. Add a `"cache_version": "1.0"` field and check it on load.
- [ ] **Guard `restart_application()` with `atexit` cleanup**: `utils.py:restart_application()` calls `os._exit(0)` which skips all cleanup (pending cache writes, file handles, Qt event loop teardown). Call `config.flush_cache()` before exiting and consider using `sys.exit()` with proper Qt shutdown instead of the hard `os._exit()`.
---

### MY Idea/Plans
- [x] **Startup Prompt**: Prompt the user to fetch rules, load local cache, or start with a clean workspace on startup.
- [x] **Default Match Settings**: Set the default title variation checkbox behaviors (Match Pattern: ON, Title: OFF, Save Path: OFF) and save them per-rule.
- [x] **Reset Settings**: Add options to reset each settings tab individually and a global "Reset All Settings" button in the footer.
- [x] **Color-Coded Variations**: Color title variation buttons green when matched, and yellow/amber when unmatched.
- [x] **Responsive Rule Editor**: Wrap the Rule Editor layout in a scroll area to prevent elements from getting squished/mushed on small window sizes.
- [x] **Feeds Dropdown Selector**: Convert the "Affected Feeds" input field to an editable dropdown selector supporting all cached feeds and custom URLs.
- [x] **Visual Validation Highlights**: Highlight library tree rows in red for validation errors and yellow for configuration warnings (e.g. wrong directory path slashes).
- [x] **Nyaa.si Custom RSS Search**: Implement a custom Nyaa search dialog allowing queries filtered by uploader, resolution, and custom keywords (e.g. "1080", "HEVC").
- [x] **Multi-Select Season/Year Prefix**: Add a right-click context menu action to apply season/year prefixes to multiple selected rules, and resolve the rule sync prefix-stripping bug.

---
