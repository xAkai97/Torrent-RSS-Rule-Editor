import unittest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as ET

from src.api.rss_fetcher import (
    fetch_rss_feed,
    get_subsplease_search_url,
    get_nyaa_search_url,
    fetch_nyaa_html_search,
    fetch_subsplease_api_search
)

class TestRSSFetcher(unittest.TestCase):
    
    def test_get_subsplease_search_url(self):
        url1 = get_subsplease_search_url("One Punch Man")
        self.assertEqual(url1, "https://subsplease.org/rss/?q=One+Punch+Man")
        
        url2 = get_subsplease_search_url("One Punch Man", "1080p")
        self.assertEqual(url2, "https://subsplease.org/rss/?q=One+Punch+Man&r=1080")
        
        url3 = get_subsplease_search_url("One Punch Man S2", "Any")
        self.assertEqual(url3, "https://subsplease.org/rss/?q=One+Punch+Man+S2")

    def test_get_nyaa_search_url(self):
        url1 = get_nyaa_search_url("One Punch Man")
        self.assertEqual(url1, "https://nyaa.si/?page=rss&c=1_2&q=One+Punch+Man")
        
        url2 = get_nyaa_search_url("One Punch Man", "1080p")
        self.assertEqual(url2, "https://nyaa.si/?page=rss&c=1_2&q=One+Punch+Man+1080p")

    @patch('requests.get')
    def test_fetch_rss_feed_subsplease_format(self, mock_get):
        # Mock SubsPlease RSS response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>SubsPlease RSS</title>
                <item>
                    <title>[SubsPlease] One Punch Man - 01 (1080p) [12345678].mkv</title>
                    <link>magnet:?xt=urn:btih:MOCKHASH123&amp;dn=One+Punch+Man</link>
                    <guid>https://subsplease.org/torrents/one-punch-man-01.torrent</guid>
                    <pubDate>Mon, 15 Jun 2026 12:00:00 +0000</pubDate>
                </item>
            </channel>
        </rss>
        """
        mock_get.return_value = mock_response

        items = fetch_rss_feed("https://subsplease.org/rss/")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], "[SubsPlease] One Punch Man - 01 (1080p) [12345678].mkv")
        self.assertEqual(items[0]['magnet'], "magnet:?xt=urn:btih:MOCKHASH123&dn=One+Punch+Man")
        self.assertEqual(items[0]['torrent_url'], "https://subsplease.org/torrents/one-punch-man-01.torrent")
        self.assertEqual(items[0]['pub_date'], "Mon, 15 Jun 2026 12:00:00 +0000")
        mock_response.raise_for_status.assert_called_once()

    @patch('requests.get')
    def test_fetch_rss_feed_nyaa_format(self, mock_get):
        # Mock Nyaa RSS response with namespaces
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:nyaa="https://nyaa.si/xmlns/nyaa">
            <channel>
                <title>Nyaa - Anime</title>
                <item>
                    <title>[SubsPlease] One Punch Man - 02 (1080p) [87654321].mkv</title>
                    <link>https://nyaa.si/download/12345.torrent</link>
                    <guid isPermaLink="true">https://nyaa.si/view/12345</guid>
                    <pubDate>Tue, 16 Jun 2026 14:00:00 +0000</pubDate>
                    <nyaa:infoHash>AABBCCDDEEFF00112233445566778899AABBCCDD</nyaa:infoHash>
                </item>
            </channel>
        </rss>
        """
        mock_get.return_value = mock_response

        items = fetch_rss_feed("https://nyaa.si/?page=rss")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], "[SubsPlease] One Punch Man - 02 (1080p) [87654321].mkv")
        self.assertEqual(items[0]['torrent_url'], "https://nyaa.si/download/12345.torrent")
        self.assertEqual(items[0]['pub_date'], "Tue, 16 Jun 2026 14:00:00 +0000")
        self.assertTrue(items[0]['magnet'].startswith("magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD"))
        mock_response.raise_for_status.assert_called_once()

    @patch('requests.get')
    def test_fetch_rss_feed_failure(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        items = fetch_rss_feed("https://invalid-url.com/rss")
        self.assertEqual(items, [])

    @patch('requests.get')
    def test_fetch_nyaa_html_search(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = """
        <html>
        <body>
        <table>
            <tbody>
                <tr class="success">
                    <td class="text-center">
                        <a href="/view/123456" title="[SubsPlease] Test Anime - 01 (1080p) [12345678].mkv">[SubsPlease] Test Anime - 01 (1080p) [12345678].mkv</a>
                    </td>
                    <td class="text-center">
                        <a href="/download/123456.torrent"><i class="fa fa-download"></i></a>
                        <a href="magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD&dn=%5BSubsPlease%5D+Test+Anime+-+01+%281080p%29"><i class="fa fa-magnet"></i></a>
                    </td>
                    <td class="text-center" data-timestamp="1623456000">2021-06-12 00:00</td>
                </tr>
            </tbody>
        </table>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        items = fetch_nyaa_html_search("Test Anime", "1080p")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], "[SubsPlease] Test Anime - 01 (1080p) [12345678].mkv")
        self.assertEqual(items[0]['torrent_url'], "https://nyaa.si/download/123456.torrent")
        self.assertEqual(items[0]['magnet'], "magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD&dn=%5BSubsPlease%5D+Test+Anime+-+01+%281080p%29")
        self.assertEqual(items[0]['pub_date'], "2021-06-12 00:00")

    @patch('requests.get')
    def test_fetch_subsplease_api_search(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "123": {
                "show": "Test Show",
                "episode": "01",
                "release_date": "2026-06-12",
                "downloads": [
                    {
                        "res": "1080",
                        "magnet": "magnet:?xt=urn:btih:MOCK1"
                    },
                    {
                        "res": "720",
                        "magnet": "magnet:?xt=urn:btih:MOCK2"
                    }
                ]
            }
        }
        mock_get.return_value = mock_response

        # 1. Fetch with specific resolution 1080p
        items = fetch_subsplease_api_search("Test Show", "1080p")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], "[SubsPlease] Test Show - 01 (1080p)")
        self.assertEqual(items[0]['magnet'], "magnet:?xt=urn:btih:MOCK1")
        self.assertIsNone(items[0]['torrent_url'])
        self.assertEqual(items[0]['pub_date'], "2026-06-12")

        # 2. Fetch with resolution Any
        items_any = fetch_subsplease_api_search("Test Show", "Any")
        self.assertEqual(len(items_any), 2)
        self.assertEqual(items_any[0]['title'], "[SubsPlease] Test Show - 01 (1080p)")
        self.assertEqual(items_any[1]['title'], "[SubsPlease] Test Show - 01 (720p)")

