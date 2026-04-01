# TODO: Torrent RSS Rule Editor

## Active Priorities
- [x] Backup/restore: one-click qBittorrent rules snapshot and restore

## Next Improvements
- [x] Multi-target export + main server selection (qBittorrent, Deluge, Transmission, Sonarr, Autobrr)
- [ ] Logging configuration controls in Settings
- [ ] Performance profiling for large rule sets

## New Suggestions
- [ ] Credential key import/recovery flow (pair with existing key export)
- [ ] Encrypted backup bundle option (config + cache + key metadata)
- [ ] Rule diff preview before apply/sync (show changed fields only)
- [ ] Rule conflict detector (duplicate mustContain/savePath/category combos)
- [ ] Optional startup health check panel (qBittorrent/Sonarr/encryption status)

## Deferred
- [ ] Extract sync workflow from main window callbacks (high effort, low ROI)
- [ ] Consider replacing config.ini with JSON after credential-encryption design is finalized

## Notes
- Auto-create default config.ini is now implemented for first run.
- Credential encryption phase 1+2 complete: encrypted save/load, plaintext migration, settings status indicator, and manual migrate action.
- Credential encryption phase 3 complete: key export, key rotation with backup and re-encryption, and startup plaintext fallback warning.
- Template workflow polish complete: create/apply/edit/rename/delete now handled in template dialog.
- Dark mode improvements: dropdown arrow visibility fixed for combobox, spinbox, and menubutton controls.
- Pre-import check UI upgraded from plain text to sortable table with click-to-copy cell values.
- Legacy single-file app folder removed; codebase now uses modular entrypoint only.
- Keep config.ini and seasonal_cache.json ignored in git for local secrets/state.
- Backup/restore feature complete: automated snapshots, restore options (merge/replace), backup manager, and auto-backup before sync operations.
- Multi-platform target selection complete: main server preference in Settings + config.ini, and multi-target export flow for qBittorrent/Deluge/Transmission/Sonarr/Autobrr.

**Last Updated:** 2026-03-31
