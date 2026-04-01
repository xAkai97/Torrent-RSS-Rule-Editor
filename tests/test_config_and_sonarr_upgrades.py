"""Regression tests for recent config and Sonarr API hardening changes."""

from configparser import ConfigParser
import importlib
from unittest.mock import MagicMock, patch

config_module = importlib.import_module("src.config")
from src.config import AppConfig
from src import sonarr_api


def test_save_config_normalizes_blank_port(tmp_path):
    cfg_file = tmp_path / "config.ini"
    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    saved = app_cfg.save_config(
        protocol="http",
        host="localhost",
        port="   ",
        user="admin",
        password="secret",
        mode="online",
        verify_ssl=False,
    )

    assert saved is True
    assert app_cfg.QBT_PORT == "8080"

    parser = ConfigParser()
    parser.read(str(cfg_file))
    assert parser.get("QBITTORRENT_API", "port") == "8080"


def test_load_config_normalizes_port_whitespace(tmp_path):
    cfg_file = tmp_path / "config.ini"
    parser = ConfigParser()
    parser["QBITTORRENT_API"] = {
        "protocol": "http",
        "host": "localhost",
        "port": " 8081 ",
        "username": "admin",
        "password": "secret",
        "mode": "online",
        "verify_ssl": "False",
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        parser.write(f)

    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    loaded = app_cfg.load_config()

    assert loaded is True
    assert app_cfg.QBT_PORT == "8081"


def test_load_config_creates_default_file_when_missing(tmp_path):
    cfg_file = tmp_path / "config.ini"
    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    assert cfg_file.exists() is False

    loaded = app_cfg.load_config()

    assert loaded is True
    assert cfg_file.exists() is True

    parser = ConfigParser()
    parser.read(str(cfg_file))
    assert parser.has_section("QBITTORRENT_API")
    assert parser.get("QBITTORRENT_API", "host") == "localhost"
    assert parser.get("QBITTORRENT_API", "port") == "8080"


def test_save_config_encrypts_password_when_cipher_available(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.ini"
    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    monkeypatch.setattr(app_cfg, "_encrypt_secret", lambda s: f"enc:{s}" if s else s)

    saved = app_cfg.save_config(
        protocol="http",
        host="localhost",
        port="8080",
        user="admin",
        password="secret",
        mode="online",
        verify_ssl=False,
    )

    assert saved is True

    parser = ConfigParser()
    parser.read(str(cfg_file))
    assert parser.get("QBITTORRENT_API", "password") == "enc:secret"


def test_load_config_migrates_plaintext_secrets(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.ini"
    parser = ConfigParser()
    parser["QBITTORRENT_API"] = {
        "protocol": "http",
        "host": "localhost",
        "port": "8080",
        "username": "admin",
        "password": "plain-pass",
        "mode": "online",
        "verify_ssl": "False",
    }
    parser["SONARR"] = {
        "url": "http://localhost:8989",
        "api_key": "plain-key",
        "quality_profile": "",
        "root_folder": "",
        "monitor_mode": "all",
        "search_on_add": "False",
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        parser.write(f)

    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    monkeypatch.setattr(config_module, "Fernet", object())
    monkeypatch.setattr(app_cfg, "_encrypt_secret", lambda s: f"enc:{s}" if s and not s.startswith("enc:") else s)
    monkeypatch.setattr(app_cfg, "_decrypt_secret", lambda s: s[4:] if isinstance(s, str) and s.startswith("enc:") else s)

    loaded = app_cfg.load_config()
    assert loaded is True
    assert app_cfg.QBT_PASS == "plain-pass"
    assert app_cfg.SONARR_API_KEY == "plain-key"

    reloaded = ConfigParser()
    reloaded.read(str(cfg_file))
    assert reloaded.get("QBITTORRENT_API", "password") == "enc:plain-pass"
    assert reloaded.get("SONARR", "api_key") == "enc:plain-key"


def test_has_plaintext_secrets_detects_plain_values(tmp_path):
    cfg_file = tmp_path / "config.ini"
    parser = ConfigParser()
    parser["QBITTORRENT_API"] = {
        "protocol": "http",
        "host": "localhost",
        "port": "8080",
        "username": "admin",
        "password": "plain-pass",
        "mode": "online",
        "verify_ssl": "False",
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        parser.write(f)

    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)
    assert app_cfg.has_plaintext_secrets() is True


def test_has_plaintext_secrets_false_for_encrypted_values(tmp_path):
    cfg_file = tmp_path / "config.ini"
    parser = ConfigParser()
    parser["QBITTORRENT_API"] = {
        "protocol": "http",
        "host": "localhost",
        "port": "8080",
        "username": "admin",
        "password": "enc:token",
        "mode": "online",
        "verify_ssl": "False",
    }
    parser["SONARR"] = {
        "url": "http://localhost:8989",
        "api_key": "enc:key",
        "quality_profile": "",
        "root_folder": "",
        "monitor_mode": "all",
        "search_on_add": "False",
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        parser.write(f)

    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)
    assert app_cfg.has_plaintext_secrets() is False


def test_get_cipher_sets_plaintext_fallback_when_cryptography_missing(monkeypatch):
    app_cfg = AppConfig()
    monkeypatch.setattr(config_module, "Fernet", None)

    cipher = app_cfg._get_cipher()

    assert cipher is None
    assert app_cfg.is_plaintext_fallback_active() is True
    assert "cryptography dependency not installed" in app_cfg.get_plaintext_fallback_reason()


def test_export_secret_key_copies_key_file(tmp_path):
    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(tmp_path / "config.ini")
    key_path = tmp_path / ".app_secret.key"
    key_bytes = b"unit-test-secret-key"
    key_path.write_bytes(key_bytes)

    export_path = tmp_path / "exported.key"
    exported = app_cfg.export_secret_key(str(export_path))

    assert exported is True
    assert export_path.read_bytes() == key_bytes


def test_rotate_secret_key_reencrypts_values_and_creates_backup(tmp_path, monkeypatch):
    class FakeFernet:
        def __init__(self, key: bytes):
            self.key = key

        @staticmethod
        def generate_key() -> bytes:
            return b"new-key"

        def encrypt(self, plain: bytes) -> bytes:
            return self.key + b"::" + plain

        def decrypt(self, token: bytes) -> bytes:
            prefix = self.key + b"::"
            if not token.startswith(prefix):
                raise ValueError("invalid token")
            return token[len(prefix):]

    monkeypatch.setattr(config_module, "Fernet", FakeFernet)

    cfg_file = tmp_path / "config.ini"
    key_file = tmp_path / ".app_secret.key"
    key_file.write_bytes(b"old-key")

    parser = ConfigParser()
    parser["QBITTORRENT_API"] = {
        "protocol": "http",
        "host": "localhost",
        "port": "8080",
        "username": "admin",
        "password": "enc:old-key::plain-pass",
        "mode": "online",
        "verify_ssl": "False",
    }
    parser["SONARR"] = {
        "url": "http://localhost:8989",
        "api_key": "enc:old-key::plain-key",
        "quality_profile": "",
        "root_folder": "",
        "monitor_mode": "all",
        "search_on_add": "False",
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        parser.write(f)

    app_cfg = AppConfig()
    app_cfg.CONFIG_FILE = str(cfg_file)

    rotated = app_cfg.rotate_secret_key()

    assert rotated is True
    assert key_file.read_bytes() == b"new-key"

    backup_files = list(tmp_path.glob(".app_secret.key.*.bak"))
    assert len(backup_files) == 1
    assert backup_files[0].read_bytes() == b"old-key"

    reloaded = ConfigParser()
    reloaded.read(str(cfg_file))
    assert reloaded.get("QBITTORRENT_API", "password") == "enc:new-key::plain-pass"
    assert reloaded.get("SONARR", "api_key") == "enc:new-key::plain-key"


def test_sonarr_test_connection_uses_shared_session_and_verify_flag():
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"version": "4.0.0"}
    mock_response.raise_for_status.return_value = None
    mock_session.get.return_value = mock_response

    with patch("src.sonarr_api._create_session", return_value=mock_session) as mock_factory:
        result = sonarr_api.test_connection("https://sonarr.local", "api-key", verify_ssl=False)

    assert result == {"version": "4.0.0"}
    mock_factory.assert_called_once_with(verify_ssl=False)
    assert mock_session.get.call_count == 1
    mock_session.close.assert_called_once()


def test_sonarr_add_series_uses_shared_session_and_verify_flag():
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"title": "Example"}
    mock_session.post.return_value = mock_response

    with patch("src.sonarr_api._create_session", return_value=mock_session) as mock_factory:
        result = sonarr_api.add_series(
            "https://sonarr.local",
            "api-key",
            {"title": "Example", "titleSlug": "example", "tvdbId": 12345},
            quality_profile_id=1,
            root_folder_path="/tv",
            verify_ssl=False,
        )

    assert result["title"] == "Example"
    mock_factory.assert_called_once_with(verify_ssl=False)
    assert mock_session.post.call_count == 1
    mock_session.close.assert_called_once()


def test_sonarr_add_series_duplicate_detection_handles_non_json_400():
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = "Series already exists"
    mock_response.raise_for_status.return_value = None
    mock_session.post.return_value = mock_response

    with patch("src.sonarr_api._create_session", return_value=mock_session):
        try:
            sonarr_api.add_series(
                "https://sonarr.local",
                "api-key",
                {"title": "Example", "titleSlug": "example", "tvdbId": 12345},
                quality_profile_id=1,
                root_folder_path="/tv",
            )
            assert False, "Expected SonarrError for duplicate series"
        except sonarr_api.SonarrError as e:
            assert "already exists" in str(e).lower()

    mock_session.close.assert_called_once()


def test_sonarr_bulk_add_series_forwards_verify_ssl_flag():
    with patch("src.sonarr_api.add_series") as mock_add:
        mock_add.return_value = {"title": "A"}

        result = sonarr_api.bulk_add_series(
            "https://sonarr.local",
            "api-key",
            [{"title": "A"}],
            quality_profile_id=1,
            root_folder_path="/tv",
            verify_ssl=False,
        )

    assert result["success"] == ["A"]
    assert result["failed"] == []
    assert mock_add.call_count == 1
    assert mock_add.call_args.kwargs.get("verify_ssl") is False
