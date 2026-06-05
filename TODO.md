# TODO: Torrent RSS Rule Editor

## Active Work

- [x] Finish Tk-to-Qt parity audit items below and verify the remaining gaps are either implemented or explicitly documented.
- [x] Confirm the Qt main window status feedback covers long-running operations with the same persistence and visibility as Tk.
- [x] Confirm the Qt sync workflow matches the Tk meaning of sync: importing existing rules into Titles, not only enabled-state qBittorrent changes.
- [x] Confirm the Qt sync workflow still provides a preview, selection fallback, and status feedback comparable to Tk during the fetch/merge path.
- [x] Confirm validation, bulk edit, template management, and rule editor flows match the Tk dialogs in scope and detail.
- [x] Confirm import/export, drag-and-drop, and library refresh behavior match the Tk workflow after every write path, including recent-file opens and dropped-file imports.
- [x] Confirm settings tabs and controls cover the same functional surface area as Tk, especially the default category/save-path browser, connection profile editor, Sonarr export flow, API rate limits, and sanitization controls.
- [x] Confirm menu organization, shortcuts, and recent-file behavior match the Tk shell where users expect it.

## UI Parity Audit Findings

### Critical Workflow Gaps
- [x] Make the Qt status feedback behave like Tk's persistent status var during import, sync, generation, refresh, and other long operations.
- [x] Replace or supplement the Qt sync action so it can fetch and merge existing qBittorrent rules into Titles the way Tk does.
- [x] Verify the Qt sync action preserves the Tk no-selection fallback, preview text, and error/status updates.
- [x] Verify the Qt validate action shows the same detailed results surface as Tk, not just a summary message.

### High Priority Feature Parity
- [x] Verify the Qt bulk edit dialog supports the same field set and cross-field syncing as Tk, especially category and torrentParams updates.
- [x] Verify the Qt template manager matches Tk's create, edit, delete, preview, and selection behavior.
- [x] Verify the Qt advanced rule editor exists and exposes the same rule fields and validation feedback as Tk.
- [x] Verify the Qt import flow shows the same sanitization and prefix preview behavior as Tk before commits are applied.
- [x] Verify the Qt tree view supports the same selection, inline edit, drag-and-drop, and refresh behavior as Tk.

### Settings and Shell Parity
- [x] Verify the Qt settings dialog includes the same functional tabs and controls as Tk, including the default category picker, qBittorrent download-path fetch, import/export, Sonarr export, API limits, sanitization, appearance, and diagnostics.
- [x] Verify the Qt settings save flow matches Tk expectations for immediate feedback, profile handling, and connection testing.
- [x] Verify the Qt Sonarr export settings are reachable from the same dialog path and preserve the same connection, search, and bulk-add flow as Tk.
- [x] Verify the Qt main menu organization and shortcut display match Tk closely enough that no core action is harder to discover.
- [x] Verify the Qt recent-files submenu matches Tk cleanup and ordering behavior.
- [x] Verify the Qt window placement and dialog geometry behavior match Tk where cached sizing or bottom placement matters.

### Workflow and Refresh Checks
- [x] Verify import, restore, bulk edit, and template actions always refresh the library tree automatically after changes.
- [x] Verify the Qt import paths show the same user-facing status text as Tk when a file is imported, dropped, or reopened from recent files.
- [x] Verify backup and restore dialogs expose the same recovery modes and metadata clarity as Tk.
- [x] Verify trash viewing and restore/delete behavior preserve the same item categorization and state transitions as Tk.
- [x] Verify drag-and-drop import accepts the same file types and rejection cases as Tk.
- [x] Verify startup loading for config, cached categories, cached feeds, recent files, and templates is complete and consistent.

### Polish and Documentation Follow-ups
- [x] Decide which Tk behaviors are intentionally replaced by Qt-native UI patterns and document those differences.
- [x] Add focused tests for any remaining parity gaps so future regressions are caught quickly.

### Intentional Divergences To Document
- [x] Qt uses a persistent native status bar plus dialog feedback instead of Tk's status_var-driven label updates.
- [x] Qt sync uses a mode chooser that includes Tk-style fetch/merge and a separate draft apply path; confirm if this split should be documented as an intentional UX divergence.
- [x] Qt settings are grouped into a more modern tabbed dialog with inline profile/default editors, while Tk spreads some of that behavior across more explicit frame-based sections.
- [x] Qt import flows rely on native Qt dialogs and refresh hooks, while Tk leans on tkinterdnd2 and status-var messaging for more of the user feedback.


## Later Work (Previously Active)

- [ ] Finalize Sonarr export mapping/validation flow in settings and export dialogs.
- [ ] Finalize Autobrr export format and profile validation behavior.
- [ ] Add settings UI controls for runtime logging level and log file actions.

## Reliability, Performance, and Testing

- [ ] Profile large title-set operations (import, tree refresh, rule generation).
- [ ] Add focused performance tests for heavy datasets.
- [ ] Review long-running API interactions for timeout/retry consistency.
- [ ] Modernize `test_integration.py`: Convert script-like integration tests into standard pytest fixtures.
- [ ] Improve Headless Qt Testing: Add better mocking or a headless Qt setup (e.g., `pytest-qt` or `xvfb`) to prevent skipped tests in CI environments without a display.

## Security and Recovery

- [ ] Add credential key import/recovery UX paired with current key export flow.
- [ ] Add optional encrypted backup bundle for config + cache metadata.

## Code Quality and Architecture

- [ ] Continue extracting large GUI callback blocks into focused modules where practical.
- [ ] Refactor `src/gui_qt/main_window.py`: The file is exceptionally large (>4000 lines). Extract UI construction and complex interaction logic into smaller, focused view components to reduce tight coupling.
- [ ] Consolidate State Management: State is currently fragmented across `config.py`, `AppState`, and local GUI variables. Unify this to simplify end-to-end state transition testing and maintainability.
- [ ] Keep documentation synchronized with behavior changes in the same change set.

**Last Updated:** 2026-06-02
