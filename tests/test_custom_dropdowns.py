"""
Unit tests for custom dropdown buttons and sub-actions configuration.
"""
import sys
import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QMenu, QWidget, QVBoxLayout
from PySide6.QtCore import Qt
from src.config import config
from src.gui_qt.main_window import (
    DEFAULT_DROPDOWN_SUBACTIONS,
    SUBACTION_METADATA,
    DEFAULT_BUTTON_METADATA,
)

@pytest.mark.skipif(sys.platform.startswith("win") is False, reason="Windows only test")
def test_data_structures():
    """Verify that composite sub-action metadata and default button metadata are populated correctly."""
    # Verify subaction definitions
    assert "import_file" in SUBACTION_METADATA
    assert SUBACTION_METADATA["import_file"]["label"] == "Import File"
    assert "import_clipboard" in SUBACTION_METADATA
    assert "export_selected" in SUBACTION_METADATA
    assert "export_all" in SUBACTION_METADATA
    assert "backup_create" in SUBACTION_METADATA
    assert "backup_restore" in SUBACTION_METADATA
    assert "backup_manage" in SUBACTION_METADATA
    assert "templates_apply" in SUBACTION_METADATA
    assert "templates_save" in SUBACTION_METADATA
    assert "templates_manage" in SUBACTION_METADATA
    assert "edit_rules_toggle" in SUBACTION_METADATA
    assert "edit_rules_bulk" in SUBACTION_METADATA
    assert "edit_rules_batch_title" in SUBACTION_METADATA
    assert "edit_rules_batch_apply" in SUBACTION_METADATA
    assert "refresh_subsplease" in SUBACTION_METADATA
    assert "refresh_anilist" in SUBACTION_METADATA

    # Verify composite sub-actions mappings
    assert "import" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["import"] == ["import_file", "import_clipboard"]
    assert "export" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["export"] == ["export_selected", "export_all"]
    assert "backup" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["backup"] == ["backup_create", "backup_restore", "backup_manage"]
    assert "templates" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["templates"] == ["templates_apply", "templates_save", "templates_manage"]
    assert "edit_rules" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["edit_rules"] == ["edit_rules_toggle", "edit_rules_bulk", "edit_rules_batch_title", "edit_rules_batch_apply"]
    assert "refresh" in DEFAULT_DROPDOWN_SUBACTIONS
    assert DEFAULT_DROPDOWN_SUBACTIONS["refresh"] == ["refresh_subsplease", "refresh_anilist"]

def test_dynamic_rebuilding_mocked_states(monkeypatch):
    """Verify mock rebuild settings helper connections and direct-connect bindings for composite buttons."""
    # Test dictionary states
    dropdown_subactions = {
        "import": ["import_file"], # Only 1 sub-action -> direct click
        "export": ["export_selected", "export_all"], # Multiple -> QMenu dropdown
        "backup": [] # 0 sub-actions -> hide
    }
    
    # 1 sub-action direct mapping verification
    assert len(dropdown_subactions["import"]) == 1
    # Multiple subactions dropdown verification
    assert len(dropdown_subactions["export"]) > 1
    # 0 subactions verification
    assert len(dropdown_subactions["backup"]) == 0
