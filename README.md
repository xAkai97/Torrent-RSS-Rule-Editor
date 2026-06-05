# Torrent RSS Rule Editor

Desktop application for building and managing qBittorrent RSS download rules with Autobrr export support and SubsPlease title integration.

The app now uses PySide6 as the default UI and keeps Tkinter available as a legacy fallback path, organized as a modular Python package under src.

## What It Does

- Create and edit qBittorrent RSS rule payloads.
- Import title/rule data from JSON, CSV, TXT, clipboard text, and drag-and-drop.
- Export selected or full rule sets to JSON.
- Export to multi-target workflows (qBittorrent/Autobrr) from Qt.
- Sync rules to qBittorrent in online mode.
- Fetch and cache SubsPlease titles and AniList alias variations.
- Expand manual AniList refreshes to the selected season/year for broader cache pulls.
- Retain AniList alias cache by age, by size, or by dated archive rotation.
- Apply Title Variations to match pattern, title, and/or save path targets in the editor.
- Control season/year prefix behavior for imports and generated save paths from Settings.
- First launch opens a Setup Wizard when config.ini is missing, and Setup Wizard can be reopened from Settings menu.
- Validate and sanitize folder names using filesystem-aware rules.
- Manage backups and restores of qBittorrent rule state.
- Use modern Qt setup/configuration dialogs including Setup Wizard, log viewer, bulk edit, and template manager.

## Quick Start

1. Create/activate your virtual environment. If using the default local setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

*Note: For mapped development environments (e.g., custom virtual environment paths mapped via PowerShell profile), activate them using your custom profile helpers. See AGENTS.local.md (if present) for local paths and agent command execution details.*

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Run the app.

```powershell
python main.py
```

Run Tk fallback UI:

```powershell
python main.py --ui=tk
```

You can also set environment variable `TRRE_UI` to `qt` or `tk`.

## Runtime Files

- config.ini: application settings, connection profiles, and UI/tool preferences.
- cache.json: app cache storage.
- qbt_editor.log: runtime logs.
- .app_secret.key: local key for encrypted credential storage.

## Current Module Layout

```text
main.py
src/
    __init__.py
    constants.py
    config.py
    cache.py
    utils.py
    rss_rules.py
    backup.py
    api/
        __init__.py
        qbittorrent.py
        subsplease.py
    services/
        __init__.py
        backup.py
        rules.py
    gui/
        __init__.py
        app_state.py
        backup_restore.py
        dialogs.py
        file_operations.py
        main_window.py
        treeview_adapter.py
        widgets.py
        helpers/
            __init__.py
            constants.py
            debounce.py
            parsers.py
            theme.py
            variables.py
        components/
            __init__.py
            editor_apply.py
            editor_persistence.py
            feed_lookup.py
            lastmatch.py
    gui_qt/
        __init__.py
        main_window.py
```

## Server/Target Support in Current Code

- qBittorrent: API client, rule sync, backup/restore integration.
- Autobrr: target option is present in settings/export flow paths where configured.

## Testing

Run all tests:

```powershell
python -m pytest -q
```

Run specific groups:

```powershell
python -m pytest tests/test_qbittorrent_api.py -q
python -m pytest tests/test_qbittorrent_api_errors.py -q
python -m pytest tests/test_rss_rules.py -q
python -m pytest tests/test_integration.py -q
python -m pytest tests/test_modular_cleanup.py -q
```

## Security and Policy Docs

- Security reporting and handling: see SECURITY.md.
- AI-assisted workflow expectations: see AI_USAGE.md.
- Agent-oriented repository rules: see AGENTS.md.

## License

MIT. See LICENSE.

See [AI_USAGE.md](AI_USAGE.md) for the full policy.

## Documentation

- **[README.md](README.md)** - Setup, usage, and feature overview
- **[AI_USAGE.md](AI_USAGE.md)** - AI-assisted coding policy and review standards
- **[AGENTS.md](AGENTS.md)** - AI agent operating and audit guidance
- **[TODO.md](TODO.md)** - Roadmap and pending improvements

## Author

**xAkai97**

Developed with AI assistance from GitHub Copilot.
