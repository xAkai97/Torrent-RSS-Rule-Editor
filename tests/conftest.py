import os
import pytest

# Configure headless Qt platform by default to allow GUI tests to run without a display
if 'QT_QPA_PLATFORM' not in os.environ:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

@pytest.fixture(autouse=True)
def temp_config_env(tmp_path):
    """Global autouse fixture to isolate AppConfig paths to a temp directory to protect user config files."""
    from src.config import config
    
    # Store original values
    orig_config_file = config.CONFIG_FILE
    orig_secret_key_file = config.SECRET_KEY_FILE
    orig_cache_file = config.CACHE_FILE
    orig_log_file = getattr(config, 'LOG_FILE', 'data/qbt_editor.log')
    orig_all_titles = config.ALL_TITLES
    orig_cached_prefs = getattr(config, '_cached_prefs', None)
    orig_cache_data = getattr(config, '_cache_data_in_memory', None)
    
    # Override with temp paths
    config.CONFIG_FILE = str(tmp_path / "config_test.ini")
    config.SECRET_KEY_FILE = ".app_secret_test.key"
    config.CACHE_FILE = str(tmp_path / "cache_test.json")
    config.LOG_FILE = str(tmp_path / "qbt_editor_test.log")
    config.ALL_TITLES = {}
    config._cached_prefs = None
    config._cache_data_in_memory = None
    
    # Ensure fresh start
    if os.path.exists(config.CONFIG_FILE):
        os.remove(config.CONFIG_FILE)
    key_path = config._secret_key_path()
    if os.path.exists(key_path):
        try:
            os.remove(key_path)
        except OSError:
            pass
    if os.path.exists(config.CACHE_FILE):
        os.remove(config.CACHE_FILE)
    if os.path.exists(config.LOG_FILE):
        os.remove(config.LOG_FILE)
        
    yield config
    
    # Cleanup any leftovers
    if os.path.exists(config.CONFIG_FILE):
        try:
            os.remove(config.CONFIG_FILE)
        except OSError:
            pass
    if os.path.exists(key_path):
        try:
            os.remove(key_path)
        except OSError:
            pass
    if os.path.exists(config.CACHE_FILE):
        try:
            os.remove(config.CACHE_FILE)
        except OSError:
            pass
    if os.path.exists(config.LOG_FILE):
        try:
            os.remove(config.LOG_FILE)
        except OSError:
            pass
        
    # Restore original values
    config.CONFIG_FILE = orig_config_file
    config.SECRET_KEY_FILE = orig_secret_key_file
    config.CACHE_FILE = orig_cache_file
    config.LOG_FILE = orig_log_file
    config.ALL_TITLES = orig_all_titles
    config._cached_prefs = orig_cached_prefs
    config._cache_data_in_memory = orig_cache_data
