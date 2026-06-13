# AI Agent Architecture Summary

## 1. High-Level Overview
**Torrent-RSS-Rule-Editor** is a modular Python desktop application that serves as a visual editor and synchronizer for RSS rules in the qBittorrent client. It also acts as an automation bridge, pulling data from anime release schedules (SubsPlease) and querying AniList (via GraphQL) to auto-generate complex matching rules and language-specific regex patterns.

**Primary Technologies:**
- **Language:** Python 3.10+
- **GUI Framework:** PySide6 (Qt).
- **Key Libraries:** `requests` (API comms), `cryptography` (secret storage).

## 2. Architecture & File Structure
The project strictly separates its logic into three tiers:
*   **`src/api/`**: Boundary layer. External communication with qBittorrent (`qbittorrent.py`) and Anime sites (`subsplease.py`). Handled with retry limits and robust error catching.
*   **`src/services/`**: Business logic. Orchestrates complex tasks like rule syncing (`rule_sync_apply.py`), editor drafts (`rule_drafts.py`), and system backups. These modules contain the "smarts" but have no GUI dependencies.
*   **`src/gui_qt/`**: Presentation layer. The PySide6 entry is `src/gui_qt/main_window.py`. Because the logic is decoupled into services, the Qt window acts mostly as a view that calls "service wrappers" (e.g., `run_qt_...` functions) to fetch/mutate data. Note that `main_window.py` is exceptionally large (>4000 lines) and complex.

## 3. Key Components & Services
*   **qBittorrent API Integration:** Provides robust communication using standard `requests` with a fallback to `qbittorrent-api`. Supports auth, SSL verification, and rule fetching/updating.
*   **SubsPlease/AniList Scrapers:** Uses AniList GraphQL endpoints to resolve complex title variations (Romaji, Native, Synonyms). Handles local caching to prevent rate-limiting.
*   **Rule Syncing:** The `rule_sync_apply.py` module computes a diff between the "desired state" (local GUI data) and "actual state" (qBittorrent server). It generates a "dry run" plan before executing updates to prevent catastrophic wipes.
*   **RSSRule Dataclass:** Found in `src/rss_rules.py`. This is the immutable core representation of an RSS rule, enforcing strict validation before serialization to JSON for qBittorrent.

## 4. Data Models & State Management
*   **`config.py` (`AppConfig`)**: The central nervous system for state. It persists UI preferences, server credentials (encrypted using Fernet via `.app_secret.key`), and the `ALL_TITLES` dictionary (the user's library).
*   **Cache (`cache.json`)**: Stores expensive AniList variation graphs and schedules. Managed with a size/age TTL retention policy.
*   **GUI State**: Handled locally via Qt component properties, with `config.py` serving as the persistent truth.

## 5. Testing Strategy
*   **Location:** `tests/` directory.
*   **Style:** Predominantly `pytest`.
*   **Strengths:** Excellent coverage of data models, serialization edge cases (`test_import_export_edge_cases.py`), and API error handling (`test_qbittorrent_api_errors.py`).
*   **Weaknesses/Patterns to Watch:** 
    - The PySide6 UI is notoriously hard to test headlessly. We rely on testing the **Service Wrappers** (`run_qt_...` functions located in `test_qt_preview_shell.py`) to ensure the GUI can talk to the services correctly without instantiating QWidgets. 
    - `test_integration.py` runs high-level pipeline assertions.
    - Be mindful of time-sensitive tests (e.g. cache TTL logic in `test_anilist_language_filters.py`) when mocking dates.

## 6. Local Development Environment
If a local override file `AGENTS.local.md` exists in the repository root, AI agents MUST read it first to obtain machine-specific virtual environment paths, PowerShell profile commands, and other developer-specific environment details.