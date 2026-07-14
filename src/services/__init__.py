"""
Services Package — Business Logic Layer.

This package contains all the application's business logic, separated from
both the GUI (presentation) and the API (external communication) layers.
It orchestrates complex operations like rule syncing, file import/export,
backup management, and batch downloads.

Submodules:
  - backup              → Re-exports from src.backup (convenience alias)
  - batch_downloader    → Bulk torrent download queue management
  - connection_status   → Connection mode display and setup wizard triggers
  - file_operations     → Import/export of rules, titles, and JSON files
  - gui_bindings        → Keyboard shortcut and drag-drop wiring
  - language_detection  → Heuristic language classification for AniList synonyms
  - rule_drafts         → In-progress rule editing state management
  - rule_editor         → Rule creation, modification, and template application
  - rule_sync           → High-level sync orchestration (fetch → diff → plan)
  - rule_sync_apply     → Low-level sync execution (apply changes to qBittorrent)
  - rules               → Re-exports from src.rss_rules (convenience alias)
  - server_snapshot     → Capture and compare qBittorrent server state

Imports are explicit rather than wildcard to keep the public API clear
and avoid unintentional symbol leakage between submodules.
"""
