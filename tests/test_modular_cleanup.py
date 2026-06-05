"""Regression tests for modular cleanup guarantees."""

from pathlib import Path


def test_legacy_root_api_modules_removed():
    """Legacy root API modules should stay removed after refactors."""
    src_dir = Path(__file__).resolve().parents[1] / 'src'
    legacy_files = [
        src_dir / 'qbittorrent_api.py',
        src_dir / 'sonarr_api.py',
        src_dir / 'subsplease_api.py',
    ]

    missing = [str(path.name) for path in legacy_files if not path.exists()]
    assert len(missing) == len(legacy_files), (
        'Legacy root API files were reintroduced: '
        f"{', '.join(path.name for path in legacy_files if path.exists())}"
    )


def test_canonical_api_modules_importable():
    """Canonical API modules must be importable from src.api."""
    from src.api import qbittorrent, subsplease

    assert hasattr(qbittorrent, 'QBittorrentClient')
    assert hasattr(subsplease, 'fetch_subsplease_schedule')


def test_constants_modules_have_clear_ownership():
    """App constants and GUI helper constants should both remain accessible."""
    from src.constants import UIConfig, NetworkConfig
    from src.gui.helpers.constants import UIConstants

    assert hasattr(UIConfig, 'DEFAULT_WINDOW_WIDTH')
    assert hasattr(NetworkConfig, 'DEFAULT_TIMEOUT')
    assert hasattr(UIConstants, 'EDITOR_AUTO_APPLY_DEBOUNCE_MS')
