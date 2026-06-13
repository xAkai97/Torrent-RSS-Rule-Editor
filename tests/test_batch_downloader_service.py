import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile

from src.services.batch_downloader import (
    get_imported_shows_list,
    fetch_and_filter_episodes,
    download_torrent_file,
    push_to_qbittorrent
)
from src.config import config

class TestBatchDownloaderService(unittest.TestCase):

    def setUp(self):
        # Backup original ALL_TITLES
        self.original_all_titles = getattr(config, 'ALL_TITLES', {})
        config.ALL_TITLES = {
            'anime': [
                {
                    'ruleName': 'OPM',
                    'mustContain': 'One Punch Man',
                    'savePath': '/downloads/OPM',
                    'assignedCategory': 'anime',
                    'affectedFeeds': ['https://feed1.com', 'https://feed2.com'],
                    'node': {'title': 'One Punch Man (TV)'}
                },
                {
                    'ruleName': 'MHA',
                    'mustContain': 'My Hero Academia',
                    'savePath': '/downloads/MHA',
                    'assignedCategory': 'anime',
                    'affectedFeeds': [],
                    'node': {'title': 'My Hero Academia'}
                }
            ]
        }

    def tearDown(self):
        config.ALL_TITLES = self.original_all_titles

    def test_get_imported_shows_list(self):
        shows = get_imported_shows_list()
        self.assertEqual(len(shows), 2)
        
        # Verify ordering and display name mapping
        self.assertEqual(shows[0]['display_name'], 'My Hero Academia')
        self.assertEqual(shows[0]['rule_name'], 'MHA')
        self.assertEqual(shows[0]['save_path'], '/downloads/MHA')
        self.assertEqual(shows[0]['feeds'], [])
        
        self.assertEqual(shows[1]['display_name'], 'One Punch Man (TV)')
        self.assertEqual(shows[1]['rule_name'], 'OPM')
        self.assertEqual(shows[1]['save_path'], '/downloads/OPM')
        self.assertEqual(shows[1]['feeds'], ['https://feed1.com', 'https://feed2.com'])

    @patch('src.services.batch_downloader.fetch_nyaa_html_search')
    @patch('src.services.batch_downloader.fetch_subsplease_api_search')
    @patch('src.services.batch_downloader.fetch_rss_feed')
    def test_fetch_and_filter_episodes(self, mock_fetch, mock_subsplease, mock_nyaa):
        # Mock API searches to return empty so fallback to RSS is executed
        mock_subsplease.return_value = []
        mock_nyaa.return_value = []

        # Mock fetched episodes for fallback
        mock_fetch.return_value = [
            {'title': '[SubsPlease] Show - 01 (1080p)', 'magnet': 'mag1', 'torrent_url': 'tor1'},
            {'title': '[SubsPlease] Show - 01 (720p)', 'magnet': 'mag2', 'torrent_url': 'tor2'},
            {'title': '[SubsPlease] Show - 01 (480p)', 'magnet': 'mag3', 'torrent_url': 'tor3'},
            {'title': '[SubsPlease] Show - 02 (1080)', 'magnet': 'mag4', 'torrent_url': 'tor4'}
        ]

        # 1. Fetch all (fallback path)
        res_any = fetch_and_filter_episodes('subsplease', 'Show', resolution='Any')
        self.assertEqual(len(res_any), 4)

        # 2. Filter 1080p (fallback path)
        res_1080 = fetch_and_filter_episodes('subsplease', 'Show', resolution='1080p')
        self.assertEqual(len(res_1080), 2)
        self.assertEqual(res_1080[0]['title'], '[SubsPlease] Show - 01 (1080p)')
        self.assertEqual(res_1080[1]['title'], '[SubsPlease] Show - 02 (1080)')

        # 3. Filter 720p (fallback path)
        res_720 = fetch_and_filter_episodes('subsplease', 'Show', resolution='720p')
        self.assertEqual(len(res_720), 1)
        self.assertEqual(res_720[0]['title'], '[SubsPlease] Show - 01 (720p)')

        # 4. Filter by query for feeds (Configured Feeds)
        res_feeds = fetch_and_filter_episodes('feeds', 'Show - 01', feed_url='https://feed1.com', resolution='Any')
        self.assertEqual(len(res_feeds), 3)
        self.assertTrue(all('Show - 01' in item['title'] for item in res_feeds))

        res_feeds_none = fetch_and_filter_episodes('feeds', 'Non-existent', feed_url='https://feed1.com', resolution='Any')
        self.assertEqual(len(res_feeds_none), 0)

        # 5. Direct API results without fallback
        mock_subsplease.return_value = [
            {'title': '[SubsPlease] Show - 03 (1080p)', 'magnet': 'mag5', 'torrent_url': None}
        ]
        res_direct = fetch_and_filter_episodes('subsplease', 'Show', resolution='Any')
        self.assertEqual(len(res_direct), 1)
        self.assertEqual(res_direct[0]['title'], '[SubsPlease] Show - 03 (1080p)')

        mock_nyaa.return_value = [
            {'title': '[SubsPlease] Show - 04 (1080p)', 'magnet': 'mag6', 'torrent_url': 'tor6'}
        ]
        res_nyaa_direct = fetch_and_filter_episodes('nyaa', 'Show', resolution='Any')
        self.assertEqual(len(res_nyaa_direct), 1)
        self.assertEqual(res_nyaa_direct[0]['title'], '[SubsPlease] Show - 04 (1080p)')

    @patch('requests.get')
    def test_download_torrent_file(self, mock_get):
        # Mock file download contents
        mock_response = MagicMock()
        mock_response.content = b"TORRENT_FILE_CONTENT"
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "test.torrent")
            success = download_torrent_file("http://link.com/test.torrent", dest)
            
            self.assertTrue(success)
            self.assertTrue(os.path.exists(dest))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), b"TORRENT_FILE_CONTENT")

    @patch('src.services.batch_downloader.QBittorrentClient')
    @patch.object(config, 'load_config')
    def test_push_to_qbittorrent(self, mock_load, mock_client_cls):
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.add_torrents.return_value = True
        mock_client_cls.return_value = mock_client
        
        config.CONNECTION_MODE = 'online'
        
        urls = ['magnet:?xt=urn:btih:123']
        success, msg = push_to_qbittorrent(urls, save_path='/downloads', category='anime', tags='batch')
        
        self.assertTrue(success)
        mock_client.connect.assert_called_once()
        mock_client.add_torrents.assert_called_once_with(
            urls=urls,
            save_path='/downloads',
            category='anime',
            tags='batch',
            is_paused=False
        )
        mock_client.close.assert_called_once()
