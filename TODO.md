# TODO: Torrent RSS Rule Editor

## Active Work

### UI / UX Enhancements
- [ ] Add support for custom theme loading via external JSON color maps (allowing users to import and apply custom themes beyond light/dark presets).

### Testing & Infrastructure
- [ ] Set up headless Qt testing (e.g., using `pytest-qt` or mock QWidgets) so GUI tests don't have to be skipped in CI environments without a display.
- [ ] Modernize `test_integration.py` to convert script-like integration tests into standard pytest fixtures.

### Security, Recovery & Architecture
- [ ] Add credential key import/recovery UI paired with current key export flow.
- [ ] Add optional encrypted backup bundle for config + cache metadata.
- [ ] Refactor `src/gui_qt/main_window.py` (>4000 lines) by extracting UI components (wizard, settings dialog, tree-view helpers) into dedicated submodules.

### My Fixes
- [x] fix tree view display column number sorting as single digits number like 1 and 2 are not correct, its doing 1, 10 , 11, 12, 13, 14, 15, 16, 17, 18, 19, 2, 20, 21 , ... instead of 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12...
- [x] fix affected feeds list not showing in rule editor and advanced rule editor.
- [x] improve batch downloader to use more source not just from feeds but also from search result cause rss feeds only contain recent rss feeds so some older episodes might be missing. possible sources suplease website, nyaa.si and others.
- [x] apply rules is doing all rules it for some reason is applying only selected rule not all rules.
- [x] improve the title variations match logic as sometimes it doesn't match the correct title variations like Saikyou no Ousama, Nidome no Jinsei wa Nani wo Suru? = AniList English was The Beginning After the End but logic did not detect it or similar cases.
- [x] Refresh cached categories are not working, probbly same for default feeds? and i cant seem to find the cache for categories or default feeds.


