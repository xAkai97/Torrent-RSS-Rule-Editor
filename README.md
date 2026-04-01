# Torrent RSS Rule Editor

A cross-platform Tkinter GUI for generating and synchronizing qBittorrent RSS download rules for seasonal anime. Supports offline JSON export and optional online sync to qBittorrent WebUI.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-186%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **🎯 Smart Rule Generation** - Create qBittorrent RSS download rules with seasonal paths
- **📤 Dual Mode Operation** - Export JSON files or sync directly to qBittorrent WebUI
- **📺 Sonarr Integration** - Bulk-add series to Sonarr with automatic matching
- **🔄 SubsPlease Integration** - Fetch current seasonal anime titles with local caching
- **📋 MAL Import** - Import anime lists from MyAnimeList via browser extension
- **🔍 Search & Filter** - Quickly find rules by title, category, or save path
- **✏️ Bulk Edit** - Edit multiple rules simultaneously (category, save path, enabled)
- **✨ Auto-Sanitization** - Automatically fixes invalid folder names based on target filesystem
- **⚠️ Validation Indicators** - Visual warnings for titles with validation issues in treeview
- **💾 Filesystem Selection** - Choose between Windows and Linux/Unix/Unraid validation rules
- **📋 Rule Templates** - Save and apply common rule configurations (5 built-in templates)
- **↩️ Undo** - Restore deleted rules with Ctrl+Z
- **🔐 Credential Security** - Optional encrypted credential storage with key rotation and export/import
- **📊 Import Preview** - Sortable table-based pre-import check with click-to-copy cell values
- **🎨 Dark Mode** - Full dark theme support with improved control visibility
- **⌨️ Keyboard Shortcuts** - Ctrl+S, Ctrl+O, Ctrl+F, Ctrl+B, Ctrl+T, Ctrl+Shift+S, and more
- **📂 Drag & Drop** - Drop JSON files directly onto the window to import

## Quick Start

### 1. Create & Activate Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Run the Application

```powershell
python main.py
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open/Import JSON file |
| `Ctrl+S` | Generate/Sync rules |
| `Ctrl+Shift+S` | Export to Sonarr |
| `Ctrl+E` | Export selected rules |
| `Ctrl+Shift+E` | Export all rules |
| `Ctrl+B` | Bulk edit selected rules |
| `Ctrl+Z` | Undo last delete |
| `Ctrl+T` | Save rule as template |
| `Ctrl+Shift+T` | Apply template to rule |
| `Ctrl+F` | Focus search filter |
| `Ctrl+Shift+C` | Clear all titles |
| `Ctrl+Q` | Quit |
| `F5` | Refresh display |
| `Space` | Toggle enable/disable |

## Project Structure

Fully modular architecture with clean separation of concerns:

```
src/
├── constants.py       # Constants & exceptions
├── config.py          # Configuration management
├── cache.py           # Data persistence
├── utils.py           # Utility & helper functions
├── subsplease_api.py  # SubsPlease API integration
├── qbittorrent_api.py # qBittorrent API client
├── rss_rules.py       # RSS rule management
└── gui/               # GUI modules
    ├── app_state.py      - Centralized state management
    ├── helpers.py        - GUI utility functions
    ├── widgets.py        - Reusable components
    ├── dialogs.py        - Dialog windows
    ├── file_operations.py - Import/export logic
    └── main_window.py    - Main window & setup

tests/
├── test_entrypoint_and_dialog_singletons.py # Entry/log/settings window tests (3)
├── test_filtering.py             # Helper & filter tests (18)
├── test_gui_components.py        # GUI component tests (18)
├── test_import_export_edge_cases.py # Edge case tests (21)
├── test_integration.py           # Integration tests (10)
├── test_modules.py               # Foundation tests (6)
├── test_config_and_sonarr_upgrades.py # Config and Sonarr hardening tests (5)
├── test_qbittorrent_api.py       # API tests (5)
├── test_qbittorrent_api_errors.py # API error tests (27)
├── test_rss_rules.py             # RSS rules tests (9)
├── test_treeview_display.py      # Treeview behavior tests (23)
└── test_validation.py            # Validation & sanitization tests (30)
```

**Total Test Coverage:** 186 tests passing across 12 test files

## Configuration

On first run, open **Settings** (Ctrl+,) and configure your qBittorrent WebUI details.

### Connection Modes

- **Online Mode** - Sync rules directly to qBittorrent WebUI
- **Offline Mode** - Generate JSON file for manual import

### Save Path Resolution

The app keeps RSS rule `savePath` values relative (for example: `Fall 2025/Title`).
qBittorrent then resolves the final destination by appending paths as:

`qBittorrent default download path + category save_path + rule savePath`

Example:
- qBittorrent default download path: `/data`
- category save_path: `anime/web`
- rule savePath: `Fall 2025/Example Series`
- effective full path: `/data/anime/web/Fall 2025/Example Series`

These values are examples only; actual `savePath` is generated case-by-case from each rule's season/year/title.

Behavior notes:
- Rule generation does not prepend category/default paths into `savePath`.
- qBittorrent performs the final path composition during download.

### Filesystem Validation

Configure your target filesystem in Settings for proper folder name validation:

- **🐧 Linux/Unix/Unraid (Default)** - Allows colons and quotes, blocks forward slashes
- **🪟 Windows** - Strict validation: blocks colons, quotes, trailing dots, and reserved names

**⚠️ Note:** Linux folders with colons (`:`) will appear without colons when accessed from Windows via SMB shares.

### Auto-Sanitization

Enable automatic folder name sanitization in Settings (enabled by default):
- Automatically fixes invalid characters when syncing from qBittorrent
- Example: `"Title: Name"` → `"Title Name"`
- Works with both Windows and Linux validation modes

### Validation Indicators

Titles with validation issues display visual warnings in the treeview:
- **❌ Red highlight** - Critical validation errors (invalid folder names)
- **⚠️ Orange highlight** - Warnings (empty titles, etc.)

### SSL/TLS Support

For self-signed HTTPS certificates:
- Provide a CA certificate path in Settings, OR
- Uncheck "Verify SSL"

## Dependencies

### Required
```
requests
qbittorrent-api
configparser
Pillow
```

### Optional
```
tkinterdnd2  # Enables drag-and-drop file import
```

Install optional dependency:
```powershell
pip install tkinterdnd2
```

## SubsPlease API Integration

Fetches current anime titles from SubsPlease's public API for RSS feed title matching.

- **Caching:** Results cached locally for 30 days
- **Rate Limiting:** Automatic through caching mechanism
- **Optional:** The tool works fine without this feature

## MAL Multi-Select Export Integration

Import anime lists from MyAnimeList using the companion browser extension.

### Extension Repository
🔗 https://github.com/xAkai97/mal-multi-select-export

### Usage
1. Install the browser extension
2. Select anime on MyAnimeList seasonal pages
3. Export as JSON or copy to clipboard
4. Import into RSS Rule Editor via **Import > Paste from Clipboard**

## Running Tests

```powershell
# Run all tests
python -m pytest -v

# Or using test runner script
python run_tests.py

# Run individual test suites
pytest tests/test_filtering.py       # 18 tests
pytest tests/test_import_export_edge_cases.py # 21 tests
pytest tests/test_validation.py      # 30 tests
pytest tests/test_gui_components.py  # 18 tests
pytest tests/test_qbittorrent_api_errors.py # 27 tests
pytest tests/test_integration.py     # 10 tests
pytest tests/test_rss_rules.py       # 9 tests
pytest tests/test_qbittorrent_api.py # 5 tests
pytest tests/test_modules.py         # 6 tests
pytest tests/test_config_and_sonarr_upgrades.py # 5 tests
pytest tests/test_treeview_display.py # 23 tests
pytest tests/test_entrypoint_and_dialog_singletons.py # 3 tests
```

**Test Coverage Breakdown:**
- ✅ **Core Modules** (6 tests) - Module imports and structure
- ✅ **qBittorrent API** (5 tests) - Client and API operations
- ✅ **qBittorrent API Errors** (27 tests) - Error handling and edge cases
- ✅ **RSS Rules** (9 tests) - Rule management and serialization
- ✅ **Integration Tests** (10 tests) - End-to-end workflows
- ✅ **Config & Sonarr Hardening** (5 tests) - Port normalization and resilient Sonarr HTTP behavior
- ✅ **Data Filtering** (18 tests) - Utility functions and filters
- ✅ **GUI Components** (18 tests) - GUI widgets, dialogs, auto-connect setup, and style behavior
- ✅ **Import/Export Edge Cases** (21 tests) - Malformed data, Unicode, large files
- ✅ **Treeview Display** (23 tests) - Treeview refresh and render behavior
- ✅ **Validation & Sanitization** (30 tests) - Filesystem validation and auto-sanitization
- ✅ **Entrypoint & Dialog Singletons** (3 tests) - Main startup and singleton window behavior

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Security

Please report security vulnerabilities privately. See [SECURITY.md](SECURITY.md) for the disclosure policy and response expectations.

## AI-Assisted Development

AI tools may be used to help draft code, tests, documentation, and refactors.
All AI-assisted changes are treated as suggestions and require human review before merge.

Project expectations for AI-assisted coding:
- Validate behavior locally (run relevant tests and smoke checks)
- Review for correctness, maintainability, and style consistency
- Verify security-sensitive changes manually (auth, networking, file I/O, credential handling)
- Avoid committing secrets or sensitive data in prompts, logs, or generated code

See [AI_USAGE.md](AI_USAGE.md) for the full policy.

## Documentation

- **[README.md](README.md)** - Setup, usage, and feature overview
- **[AI_USAGE.md](AI_USAGE.md)** - AI-assisted coding policy and review standards
- **[AGENTS.md](AGENTS.md)** - AI agent operating and audit guidance
- **[TODO.md](TODO.md)** - Roadmap and pending improvements

## Author

**xAkai97**

Developed with AI assistance from GitHub Copilot.
