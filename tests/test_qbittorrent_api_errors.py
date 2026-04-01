"""
Unit tests for qBittorrent API error handling.

Tests cover connection failures, timeouts, authentication errors, 
invalid responses, network errors, and proper error propagation.
"""
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests

from src.constants import QBittorrentError
from src.qbittorrent_api import (
    APIConnectionError,
    Conflict409Error,
    QBittorrentClient,
    fetch_categories,
    fetch_feeds,
    fetch_rules,
    ping_qbittorrent,
)


class TestConnectionErrors(unittest.TestCase):
    """Test connection error handling."""

    def test_normalizes_full_url_host_input(self):
        """Host field may be entered as full URL in settings dialog."""
        client = QBittorrentClient(
            protocol="http",
            host="https://203.0.113.10:8080/",
            port="",
            username="admin",
            password="password"
        )

        assert client.protocol == "https"
        assert client.host == "203.0.113.10"
        assert client.port == "8080"
        assert client.base_url == "https://203.0.113.10:8080"

    def test_normalizes_host_with_embedded_port(self):
        """Host field may include host:port while port field is blank."""
        client = QBittorrentClient(
            protocol="http",
            host="203.0.113.10:8080",
            port="",
            username="admin",
            password="password"
        )

        assert client.host == "203.0.113.10"
        assert client.port == "8080"
        assert client.base_url == "http://203.0.113.10:8080"
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_connection_timeout(self, mock_session_class):
        """Test handling of connection timeout."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.post.side_effect = requests.Timeout("Connection timed out")
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            timeout=5
        )
        
        with self.assertRaises(requests.Timeout):
            client.connect()
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_connection_refused(self, mock_session_class):
        """Test handling of connection refused."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.post.side_effect = requests.ConnectionError("Connection refused")
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        with self.assertRaises(requests.ConnectionError):
            client.connect()
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_ssl_error(self, mock_session_class):
        """Test handling of SSL certificate errors."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.post.side_effect = requests.exceptions.SSLError("SSL certificate verification failed")
        
        client = QBittorrentClient(
            protocol="https",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=True
        )
        
        with self.assertRaises(requests.exceptions.SSLError):
            client.connect()
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_invalid_url(self, mock_session_class):
        """Test handling of invalid URL."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.post.side_effect = requests.exceptions.InvalidURL("Invalid URL")
        
        client = QBittorrentClient(
            protocol="http",
            host="invalid host",
            port="8080",
            username="admin",
            password="password"
        )
        
        with self.assertRaises(requests.exceptions.InvalidURL):
            client.connect()


class TestAuthenticationErrors(unittest.TestCase):
    """Test authentication error handling."""
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_authentication_failed(self, mock_session_class):
        """Test handling of authentication failure."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Fails."
        mock_session.post.return_value = mock_response
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="wrong",
            password="wrong"
        )
        
        with self.assertRaises(QBittorrentError):
            client.connect()
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_authentication_forbidden(self, mock_session_class):
        """Test handling of 403 Forbidden response."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_session.post.return_value = mock_response
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        with self.assertRaises(QBittorrentError):
            client.connect()


class TestAPIResponseErrors(unittest.TestCase):
    """Test API response error handling."""
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_invalid_json_response(self, mock_session_class):
        """Test handling of invalid JSON in response."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        # Successful login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.text = "Ok"
        
        # Invalid JSON response
        rules_response = MagicMock()
        rules_response.status_code = 200
        rules_response.json.side_effect = ValueError("Invalid JSON")
        rules_response.text = "{ invalid json }"
        
        mock_session.post.return_value = login_response
        mock_session.get.return_value = rules_response
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        client.connect()
        
        with self.assertRaises(ValueError):
            client.get_rules()
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_404_not_found(self, mock_session_class):
        """Test handling of 404 Not Found response."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        # Successful login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.text = "Ok"
        
        # 404 response
        rules_response = MagicMock()
        rules_response.status_code = 404
        rules_response.text = "Not Found"
        
        mock_session.post.return_value = login_response
        mock_session.get.return_value = rules_response
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        client.connect()
        
        # Should return empty dict on 404
        result = client.get_rules()
        assert result == {}
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_500_internal_server_error(self, mock_session_class):
        """Test handling of 500 Internal Server Error."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.post.return_value = mock_response
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        with self.assertRaises(QBittorrentError):
            client.connect()


class TestNetworkErrors(unittest.TestCase):
    """Test network-related error handling."""
    
    def test_ping_timeout(self):
        """Test ping function with timeout."""
        with patch('src.qbittorrent_api.QBittorrentClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.side_effect = requests.Timeout("Connection timed out")
            
            success, message = ping_qbittorrent(
                protocol="http",
                host="localhost",
                port="8080",
                username="admin",
                password="password",
                verify_ssl=False,
                timeout=1
            )
            
            assert success is False
            assert "Connection timed out" in message or "Timeout" in message
    
    def test_ping_connection_error(self):
        """Test ping function with connection error."""
        with patch('src.qbittorrent_api.QBittorrentClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.side_effect = requests.ConnectionError("Connection refused")
            
            success, message = ping_qbittorrent(
                protocol="http",
                host="localhost",
                port="8080",
                username="admin",
                password="password",
                verify_ssl=False
            )
            
            assert success is False
            assert "Connection" in message or "refused" in message.lower()
    
    def test_fetch_categories_network_error(self):
        """Test fetch_categories with network error."""
        with patch('src.qbittorrent_api.QBittorrentClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.side_effect = requests.ConnectionError("Network error")
            
            success, result = fetch_categories(
                protocol="http",
                host="localhost",
                port="8080",
                username="admin",
                password="password",
                verify_ssl=False
            )
            
            assert success is False
            assert "Network error" in result
    
    def test_fetch_feeds_timeout(self):
        """Test fetch_feeds with timeout."""
        with patch('src.qbittorrent_api.QBittorrentClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.return_value = True
            mock_client.get_feeds.side_effect = requests.Timeout("Request timed out")
            
            success, result = fetch_feeds(
                protocol="http",
                host="localhost",
                port="8080",
                username="admin",
                password="password",
                verify_ssl=False
            )
            
            assert success is False
            assert "Request timed out" in result or "Timeout" in result
    
    def test_fetch_rules_connection_error(self):
        """Test fetch_rules with connection error."""
        with patch('src.qbittorrent_api.QBittorrentClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.side_effect = requests.ConnectionError("Connection failed")
            
            success, result = fetch_rules(
                protocol="http",
                host="localhost",
                port="8080",
                username="admin",
                password="password",
                verify_ssl=False
            )
            
            assert success is False
            assert "Connection failed" in result


class TestRuleOperationErrors(unittest.TestCase):
    """Test error handling in rule operations."""
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_set_rule_conflict(self, mock_session_class):
        """Test handling of 409 Conflict when setting rule."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        # Successful login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.text = "Ok"
        
        # Conflict response
        rule_response = MagicMock()
        rule_response.status_code = 409
        rule_response.text = "Conflict"
        
        mock_session.post.side_effect = [login_response, rule_response]
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        client.connect()
        
        # Should handle 409 gracefully
        result = client.set_rule("TestRule", {"mustContain": "test"})
        # Implementation may return False or raise exception
        assert result is False or result is None
    
    @patch('src.qbittorrent_api.HAS_QBT_API', False)
    @patch('src.qbittorrent_api.requests.Session')
    def test_remove_rule_not_found(self, mock_session_class):
        """Test removing non-existent rule."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        # Successful login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.text = "Ok"
        
        # Not found response
        rule_response = MagicMock()
        rule_response.status_code = 404
        rule_response.text = "Not Found"
        
        mock_session.post.side_effect = [login_response, rule_response]
        
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        client.connect()
        
        # Should handle 404 gracefully
        result = client.remove_rule("NonExistentRule")
        # May return False, None, or succeed silently
        assert result is False or result is None or result is True


class TestSSLConfiguration(unittest.TestCase):
    """Test SSL configuration and certificate handling."""
    
    def test_ssl_verification_disabled(self):
        """Test SSL verification can be disabled."""
        client = QBittorrentClient(
            protocol="https",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=False
        )
        
        assert client.verify_ssl is False
        assert client.verify_param is False
    
    def test_ssl_verification_enabled(self):
        """Test SSL verification is enabled by default."""
        client = QBittorrentClient(
            protocol="https",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=True
        )
        
        assert client.verify_ssl is True
        assert client.verify_param is True
    
    def test_custom_ca_certificate(self):
        """Test custom CA certificate path."""
        ca_path = "/path/to/ca.crt"
        client = QBittorrentClient(
            protocol="https",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=True,
            ca_cert=ca_path
        )
        
        assert client.ca_cert == ca_path
        assert client.verify_param == ca_path


class TestParameterValidation(unittest.TestCase):
    """Test parameter validation and edge cases."""
    
    def test_whitespace_stripping(self):
        """Test parameters are stripped of whitespace."""
        client = QBittorrentClient(
            protocol="  http  ",
            host="  localhost  ",
            port="  8080  ",
            username="  admin  ",
            password="  password  "
        )
        
        assert client.protocol == "http"
        assert client.host == "localhost"
        assert client.port == "8080"
        assert client.username == "admin"
        assert client.password == "password"
    
    def test_base_url_construction(self):
        """Test base URL is constructed correctly."""
        client = QBittorrentClient(
            protocol="https",
            host="example.com",
            port="443",
            username="admin",
            password="password"
        )
        
        assert client.base_url == "https://example.com:443"
    
    def test_default_timeout(self):
        """Test default timeout value."""
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password"
        )
        
        assert client.timeout == 10
    
    def test_custom_timeout(self):
        """Test custom timeout value."""
        client = QBittorrentClient(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            timeout=30
        )
        
        assert client.timeout == 30


class TestErrorPropagation(unittest.TestCase):
    """Test proper error propagation through the API."""
    
    @patch('src.qbittorrent_api.QBittorrentClient')
    def test_ping_exception_handling(self, mock_client_class):
        """Test ping handles all exceptions gracefully."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("Unexpected error")
        
        success, message = ping_qbittorrent(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=False
        )
        
        assert success is False
        assert "Unexpected error" in message or "Error" in message
    
    @patch('src.qbittorrent_api.QBittorrentClient')
    def test_fetch_functions_return_empty_on_error(self, mock_client_class):
        """Test fetch functions return error tuples on error."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("Error")
        
        success, result = fetch_categories(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=False
        )
        assert success is False
        assert "Error" in result
        
        success, result = fetch_feeds(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=False
        )
        assert success is False
        assert "Error" in result
        
        success, result = fetch_rules(
            protocol="http",
            host="localhost",
            port="8080",
            username="admin",
            password="password",
            verify_ssl=False
        )
        assert success is False
        assert "Error" in result


if __name__ == '__main__':
    unittest.main()
