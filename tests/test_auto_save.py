"""
Unit tests for the Auto-Save JSON on Changes (Option B) feature.
"""
import os
import json
import time
import pytest
from src.config import config
from src.gui_qt.main_window import (
    auto_save_rules,
    run_qt_clear_all_titles,
    run_qt_remove_titles_by_rule_names,
    run_qt_commit_rule_drafts,
)

@pytest.fixture
def temp_rules_file(tmp_path):
    """Fixture to set up a temporary file path for rules output and restore original settings."""
    original_output_file = getattr(config, 'OUTPUT_CONFIG_FILE_NAME', 'qbittorrent_rules.json')
    original_titles = getattr(config, 'ALL_TITLES', {})
    
    temp_file = tmp_path / "temp_rules.json"
    config.OUTPUT_CONFIG_FILE_NAME = str(temp_file)
    
    yield temp_file
    
    # Restore original setting
    config.OUTPUT_CONFIG_FILE_NAME = original_output_file
    config.ALL_TITLES = original_titles
    if temp_file.exists():
        try:
            os.remove(temp_file)
        except Exception:
            pass

def test_auto_save_writes_file(temp_rules_file):
    """Verify that auto_save_rules correctly writes clean rules JSON in a background thread."""
    config.ALL_TITLES = {
        'anime': [
            {
                'node': {'title': 'Test Show'},
                'ruleName': 'Test Show',
                'mustContain': 'Test Show',
                'enabled': True,
                'affectedFeeds': [],
                'savePath': '',
                'assignedCategory': '',
            }
        ]
    }
    
    auto_save_rules()
    
    # Wait for background thread to write
    start_time = time.time()
    while not temp_rules_file.exists() and time.time() - start_time < 2.0:
        time.sleep(0.05)
        
    assert temp_rules_file.exists(), "Auto-save file was not created"
    
    with open(temp_rules_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert 'Test Show' in data
    assert data['Test Show']['mustContain'] == 'Test Show'
    # GUI/internal fields should be stripped
    assert 'node' not in data['Test Show']

def test_clear_titles_triggers_auto_save(temp_rules_file):
    """Verify that run_qt_clear_all_titles triggers auto_save."""
    config.ALL_TITLES = {
        'anime': [
            {
                'node': {'title': 'Test Show'},
                'ruleName': 'Test Show',
                'mustContain': 'Test Show',
                'enabled': True,
                'affectedFeeds': [],
                'savePath': '',
                'assignedCategory': '',
            }
        ]
    }
    
    result = run_qt_clear_all_titles()
    assert result['success'] is True
    
    # Wait for background thread
    start_time = time.time()
    while not temp_rules_file.exists() and time.time() - start_time < 2.0:
        time.sleep(0.05)
        
    assert temp_rules_file.exists()
    
    with open(temp_rules_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert data == {}

def test_remove_titles_triggers_auto_save(temp_rules_file):
    """Verify that run_qt_remove_titles_by_rule_names triggers auto_save."""
    config.ALL_TITLES = {
        'anime': [
            {
                'node': {'title': 'Test Show 1'},
                'ruleName': 'Test Show 1',
                'mustContain': 'Show 1',
                'enabled': True,
                'affectedFeeds': [],
                'savePath': '',
                'assignedCategory': '',
            },
            {
                'node': {'title': 'Test Show 2'},
                'ruleName': 'Test Show 2',
                'mustContain': 'Show 2',
                'enabled': True,
                'affectedFeeds': [],
                'savePath': '',
                'assignedCategory': '',
            }
        ]
    }
    
    result = run_qt_remove_titles_by_rule_names(['Test Show 1'])
    assert result['success'] is True
    
    # Wait for background thread
    start_time = time.time()
    while not temp_rules_file.exists() and time.time() - start_time < 2.0:
        time.sleep(0.05)
        
    assert temp_rules_file.exists()
    
    with open(temp_rules_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert 'Test Show 2' in data
    assert 'Test Show 1' not in data


def test_action_bar_preferences_save_and_load():
    """Verify that action bar preferences (order & visibility) with custom separators/spacers save and load correctly."""
    custom_order = [
        "season_year", "separator_1", "import", "fetch_rules", "apply", 
        "spacer_1", "theme", "settings", "separator_2", "spacer_2"
    ]
    custom_visible = {
        "season_year": True, "separator_1": True, "import": True, "fetch_rules": True, "apply": True,
        "spacer_1": True, "theme": True, "settings": True, "separator_2": False, "spacer_2": False
    }
    
    assert config.set_pref('action_bar_order', custom_order) is True
    assert config.set_pref('action_bar_visible', custom_visible) is True
    
    loaded_order = config.get_pref('action_bar_order')
    loaded_visible = config.get_pref('action_bar_visible')
    
    assert loaded_order == custom_order
    assert loaded_visible == custom_visible


def test_action_bar_default_config_excludes_generate():
    """Verify that 'generate' is excluded from the action bar default config in main_window.py."""
    from src.gui_qt.main_window import DEFAULT_ACTION_BAR_ORDER
    
    assert len(DEFAULT_ACTION_BAR_ORDER) > 0, "DEFAULT_ACTION_BAR_ORDER is empty"
    assert "generate" not in DEFAULT_ACTION_BAR_ORDER, f"DEFAULT_ACTION_BAR_ORDER contains 'generate': {DEFAULT_ACTION_BAR_ORDER}"
