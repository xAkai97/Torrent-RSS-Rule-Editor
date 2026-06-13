import os
import shutil
import pytest
from src.config import AppConfig
from src.cache import (
    load_templates,
    save_templates,
    add_template,
    delete_template,
    initialize_default_templates,
    get_default_templates,
    load_recent_files,
    save_recent_files,
    add_recent_file,
    clear_recent_files,
    load_cached_categories,
    save_cached_categories,
    load_cached_feeds,
    save_cached_feeds
)


def test_config_bootstrap_and_load_save(temp_config_env):
    config = temp_config_env
    
    # 1. Test bootstrap on missing config file
    assert not os.path.exists(config.CONFIG_FILE)
    loaded = config.load_config()
    assert loaded
    assert config.BOOTSTRAPPED_CONFIG
    assert os.path.exists(config.CONFIG_FILE)
    
    # 2. Test saving and loading custom configuration
    success = config.save_config(
        protocol="https",
        host="192.168.1.50",
        port="9091",
        user="admin",
        password="supersecretpassword",
        mode="offline",
        verify_ssl=True,
        default_save_path="/downloads/anime",
        default_category="anime-seasonal",
        default_affected_feeds=["http://example.com/feed1", "http://example.com/feed2"]
    )
    assert success
    
    # Clear variables to prove load works
    config.QBT_HOST = None
    config.QBT_PORT = None
    
    loaded = config.load_config()
    assert loaded
    assert config.QBT_PROTOCOL == "https"
    assert config.QBT_HOST == "192.168.1.50"
    assert config.QBT_PORT == "9091"
    assert config.QBT_USER == "admin"
    assert config.QBT_PASS == "supersecretpassword"
    assert config.CONNECTION_MODE == "offline"
    assert config.QBT_VERIFY_SSL is True
    assert config.DEFAULT_SAVE_PATH == "/downloads/anime"
    assert config.DEFAULT_CATEGORY == "anime-seasonal"
    assert config.DEFAULT_AFFECTED_FEEDS == ["http://example.com/feed1", "http://example.com/feed2"]


def test_credential_encryption(temp_config_env):
    config = temp_config_env
    
    # 1. Test encrypt/decrypt secrets directly
    plain = "mypassword123"
    encrypted = config._encrypt_secret(plain)
    if config.is_secret_encryption_available():
        assert encrypted.startswith("enc:")
        decrypted = config._decrypt_secret(encrypted)
        assert decrypted == plain
    else:
        assert encrypted == plain

    # 2. Test connection profiles load/save with encryption
    profiles = [
        {"name": "Local Qbt", "host": "localhost", "port": "8080", "password": "pass1"},
        {"name": "Remote Qbt", "host": "remote", "port": "8081", "password": "pass2"}
    ]
    success = config.save_connection_profiles(profiles)
    assert success
    
    # Read raw file to verify it's encrypted in storage
    from configparser import ConfigParser
    cfg = ConfigParser()
    cfg.read(config.CONFIG_FILE)
    assert "CONNECTION_PROFILES" in cfg
    raw_profiles = cfg["CONNECTION_PROFILES"].get("profiles_json")
    if config.is_secret_encryption_available():
        assert "pass1" not in raw_profiles  # shouldn't be plaintext
    else:
        assert "pass1" in raw_profiles  # will be plaintext since encryption is not available
    
    # Load back using AppConfig API and check decrypted password
    loaded_profiles = config.load_connection_profiles()
    assert len(loaded_profiles) == 2
    assert loaded_profiles[0]["password"] == "pass1"
    assert loaded_profiles[1]["password"] == "pass2"


def test_key_rotation_and_export(temp_config_env, tmp_path):
    config = temp_config_env
    if not config.is_secret_encryption_available():
        pytest.skip("Cryptography library is not available for testing key rotation")
        
    # Save a config with a password
    config.save_config("http", "localhost", "8080", "admin", "secret_pass", "online", False)
    assert os.path.exists(config._secret_key_path())
    
    # 1. Test key export
    dest_path = str(tmp_path / "exported_secret.key")
    export_ok = config.export_secret_key(dest_path)
    assert export_ok
    assert os.path.exists(dest_path)
    
    # 2. Test key rotation
    rotate_ok = config.rotate_secret_key()
    assert rotate_ok
    
    # Verify we can still decrypt after rotation
    config.load_config()
    assert config.QBT_PASS == "secret_pass"


def test_recent_files(temp_config_env):
    config = temp_config_env
    
    # Check initial
    assert load_recent_files() == []
    
    # Add files
    assert add_recent_file("file1.json")
    assert add_recent_file("file2.json")
    assert add_recent_file("file1.json")  # move to front
    
    recent = load_recent_files()
    assert recent == ["file1.json", "file2.json"]
    
    # Test capping limit
    for i in range(15):
        add_recent_file(f"file_{i}.json")
    recent = load_recent_files()
    assert len(recent) <= 10  # max limit check
    assert recent[0] == "file_14.json"
    
    # Test clear
    assert clear_recent_files()
    assert load_recent_files() == []


def test_template_management(temp_config_env):
    # Templates should initially be empty
    assert load_templates() == {}
    
    # 1. Test initialize default templates
    init_ok = initialize_default_templates()
    assert init_ok
    
    templates = load_templates()
    assert len(templates) == len(get_default_templates())
    assert "1080p Seasonal" in templates
    
    # 2. Test duplicate initialization does nothing
    assert not initialize_default_templates()
    
    # 3. Test add_template
    custom_template = {
        "description": "My Custom TV Shows",
        "must_contain": "720p H.264",
        "must_not_contain": "1080p",
        "category": "tv-shows",
        "save_path": "/tv",
        "enabled": True,
        "episode_filter": "",
        "use_regex": False
    }
    assert add_template("TV 720p", custom_template)
    
    templates = load_templates()
    assert "TV 720p" in templates
    assert templates["TV 720p"]["category"] == "tv-shows"
    
    # 4. Test delete_template
    assert delete_template("TV 720p")
    templates = load_templates()
    assert "TV 720p" not in templates
    
    # Deleting non-existent template returns False
    assert not delete_template("NonExistent")


def test_cached_categories_and_feeds(temp_config_env):
    config = temp_config_env

    # Initial load
    assert load_cached_categories() == {}
    assert load_cached_feeds() == {}
    
    # 1. Test categories caching
    categories = {
        "anime": {"savePath": "/downloads/anime"},
        "tv": {"savePath": "/downloads/tv"}
    }
    assert save_cached_categories(categories)
    assert load_cached_categories() == categories
    
    # 2. Test feeds caching
    feeds = {
        "feed1": {"url": "http://feed1.com", "uid": "123"},
        "feed2": {"url": "http://feed2.com", "uid": "456"}
    }
    assert save_cached_feeds(feeds)
    assert load_cached_feeds() == feeds

    # 3. Test direct AppConfig methods
    assert config.CACHED_CATEGORIES == {}
    assert config.CACHED_FEEDS == {}

    assert config.save_cached_categories({"test-cat": {"savePath": "/cat"}})
    assert config.CACHED_CATEGORIES == {"test-cat": {"savePath": "/cat"}}

    # Clear in-memory to force reload from cache data
    config.CACHED_CATEGORIES = {}
    config.load_cached_categories()
    assert config.CACHED_CATEGORIES == {"test-cat": {"savePath": "/cat"}}

    assert config.save_cached_feeds({"test-feed": {"url": "http://test.feed"}})
    assert config.CACHED_FEEDS == {"test-feed": {"url": "http://test.feed"}}

    config.CACHED_FEEDS = {}
    config.load_cached_feeds()
    assert config.CACHED_FEEDS == {"test-feed": {"url": "http://test.feed"}}

