"""
Batch Downloader Service — Bulk Episode Download Manager.

This module provides the backend logic for the Batch Downloader dialog. It lets
users search for episodes across multiple sources (SubsPlease, Nyaa, RSS feeds),
filter by resolution, and then download them via one of three methods:

  1. **Local file download** — Save .torrent files to disk
  2. **Magnet link copy** — Copy magnet URIs to clipboard
  3. **Push to qBittorrent** — Add torrents directly to the running qBittorrent server

The workflow is:
  1. get_imported_shows_list() — Get the user's anime list from ALL_TITLES
  2. fetch_and_filter_episodes() — Search a source for episodes, filter by resolution
  3. download_torrent_file() / push_to_qbittorrent() — Execute the download action
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

from src.api.qbittorrent import QBittorrentClient
from src.api.rss_fetcher import (
    fetch_rss_feed,
    get_nyaa_search_url,
    get_subsplease_search_url,
    fetch_nyaa_html_search,
    fetch_subsplease_api_search,
)
from src.config import config
from src.constants import NetworkConfig
from src.utils import get_display_title

logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for matching resolution tags in episode titles.
# These are used to filter search results by video quality.
RESOLUTION_REGEXES = {
    '1080p': re.compile(r'\b1080p?\b', re.IGNORECASE),  # Matches "1080p" or "1080"
    '720p': re.compile(r'\b720p?\b', re.IGNORECASE),
    '480p': re.compile(r'\b480p?\b', re.IGNORECASE),
}


def get_imported_shows_list() -> List[Dict[str, Any]]:
    """
    Build a flat, sorted list of all shows from the user's title library.

    Walks through ALL_TITLES (which is organized by media type) and flattens
    it into a simple list that the Batch Downloader dialog can display.

    Returns:
        A list of show dictionaries sorted alphabetically, each containing:
          display_name  — the show's display title
          rule_name     — the qBittorrent rule name
          must_contain  — the RSS match pattern
          save_path     — where downloads should be saved
          feeds         — list of RSS feed URLs
          category      — qBittorrent category
    """
    shows: List[Dict[str, Any]] = []
    all_titles = getattr(config, 'ALL_TITLES', {}) or {}

    if not isinstance(all_titles, dict):
        return shows

    for media_type, items in all_titles.items():
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue

            rule_name = entry.get('ruleName', '')
            display_name = get_display_title(entry, rule_name)

            shows.append({
                'display_name': display_name,
                'rule_name': rule_name,
                'must_contain': entry.get('mustContain', ''),
                'save_path': entry.get('savePath', ''),
                'feeds': entry.get('affectedFeeds', []) or [],
                'category': entry.get('assignedCategory', '')
            })

    # Sort alphabetically by display name for consistent UI presentation
    shows.sort(key=lambda s: s['display_name'].lower())
    return shows


def fetch_and_filter_episodes(
    source: str,
    query: str,
    feed_url: Optional[str] = None,
    resolution: str = 'Any',
    timeout: int = NetworkConfig.DEFAULT_TIMEOUT
) -> List[Dict[str, Any]]:
    """
    Search for episodes from a source and optionally filter by resolution.

    This is the main search function for the Batch Downloader. It supports
    multiple search backends with automatic fallback:

    Sources:
      - 'feeds'      — Fetch from the show's configured RSS feed URL
      - 'subsplease' — Search SubsPlease API (falls back to RSS feed search)
      - 'nyaa'       — Search Nyaa HTML (falls back to RSS feed search)
      - 'custom'     — Fetch from a user-provided URL

    For 'feeds' and 'custom' sources, results are additionally filtered by
    the search query (title substring match).

    Resolution filtering is applied as a post-processing step for any source.

    Args:
        source: The search backend to use ('feeds', 'subsplease', 'nyaa', 'custom').
        query: The search text (anime title or keywords).
        feed_url: Direct feed URL (required for 'feeds' and 'custom' sources).
        resolution: Video quality filter ('1080p', '720p', '480p', or 'Any').
        timeout: Network request timeout in seconds.

    Returns:
        A list of episode dictionaries, each with at least a 'title' key.
    """
    items: List[Dict[str, Any]] = []

    # --- Step 1: Fetch raw items from the selected source ---
    if source == 'feeds' and feed_url:
        items = fetch_rss_feed(feed_url, timeout=timeout)
    elif source == 'subsplease':
        # Try the SubsPlease API first, fall back to RSS feed search
        items = fetch_subsplease_api_search(query, resolution, timeout=timeout)
        if not items:
            logger.info("SubsPlease API search returned no items, falling back to RSS feed search.")
            url = get_subsplease_search_url(query, resolution)
            items = fetch_rss_feed(url, timeout=timeout)
    elif source == 'nyaa':
        # Try Nyaa HTML scraping first, fall back to RSS feed search
        items = fetch_nyaa_html_search(query, resolution, timeout=timeout)
        if not items:
            logger.info("Nyaa HTML search returned no items, falling back to RSS feed search.")
            url = get_nyaa_search_url(query, resolution)
            items = fetch_rss_feed(url, timeout=timeout)
    elif source == 'custom' and feed_url:
        items = fetch_rss_feed(feed_url, timeout=timeout)
    else:
        logger.warning(f"Unknown source '{source}' or missing URL for batch downloader")
        return []

    # --- Step 2: Filter by search query (for sources that return all items) ---
    # 'feeds' and 'custom' return all items from the feed, so we need to
    # filter by the search query to show only relevant results
    if source in ('feeds', 'custom') and query:
        query_clean = query.strip().lower()
        if query_clean:
            items = [item for item in items if query_clean in item.get('title', '').lower()]

    # --- Step 3: Filter by resolution ---
    if resolution != 'Any' and resolution in RESOLUTION_REGEXES:
        pattern = RESOLUTION_REGEXES[resolution]
        filtered: List[Dict[str, Any]] = []
        for item in items:
            title = item.get('title', '')
            if pattern.search(title):
                filtered.append(item)
        return filtered

    return items


def download_torrent_file(url: str, dest_path: str, timeout: int = NetworkConfig.DEFAULT_TIMEOUT) -> bool:
    """
    Download a .torrent file from a URL and save it to disk.

    Args:
        url: The torrent file download URL.
        dest_path: Where to save the file (absolute path, including filename).
        timeout: Network request timeout in seconds.

    Returns:
        True if the download succeeded, False on any error.
    """
    logger.info(f"Downloading torrent file: {url} -> {dest_path}")
    headers = {'User-Agent': NetworkConfig.USER_AGENT}

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        # Create the target directory if it doesn't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(dest_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        logger.error(f"Failed to download torrent file from {url}: {e}")
        return False


def push_to_qbittorrent(
    urls: List[str],
    save_path: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Add torrent/magnet links directly to the running qBittorrent server.

    Connects to qBittorrent using the app's saved credentials, pushes the
    provided URLs, and starts them downloading immediately.

    Args:
        urls: List of magnet links or .torrent file URLs to add.
        save_path: Optional download directory on the qBittorrent host.
        category: Optional category to assign to the added torrents.
        tags: Optional comma-separated tags to assign.

    Returns:
        A tuple of (success: bool, status_message: str).
    """
    if not urls:
        return False, "No torrent URLs selected to push."

    # Get connection parameters from the global config
    protocol = config.QBT_PROTOCOL or 'http'
    host = config.QBT_HOST or 'localhost'
    port = config.QBT_PORT or '8080'
    username = config.QBT_USER or ''
    password = config.QBT_PASS or ''
    verify_ssl = config.QBT_VERIFY_SSL
    ca_cert = config.QBT_CA_CERT

    # Can't push to server in offline mode
    if config.CONNECTION_MODE == 'offline':
        return False, "Application is in offline mode. Cannot push to qBittorrent."

    try:
        # Create a temporary client connection
        client = QBittorrentClient(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert
        )

        if not client.connect():
            return False, "Could not establish connection to qBittorrent. Check credentials."

        try:
            # Push all selected episodes, starting them immediately (not paused)
            success = client.add_torrents(
                urls=urls,
                save_path=save_path,
                category=category,
                tags=tags,
                is_paused=False
            )
        finally:
            # Always close the connection, even on error
            client.close()

        if success:
            return True, f"Successfully pushed {len(urls)} torrent(s) to qBittorrent."
        else:
            return False, "qBittorrent client failed to add torrents."

    except Exception as e:
        error_msg = f"Error pushing to qBittorrent: {e}"
        logger.error(error_msg)
        return False, error_msg
