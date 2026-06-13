"""
RSS Feed Fetcher and Parser Module.

This module handles downloading and parsing RSS feeds from anime torrent sources
like SubsPlease and Nyaa.si. It extracts release information (titles, magnet links,
torrent file URLs, and publication dates) so the rest of the app can match them
against the user's download rules.

Supported sources:
  - SubsPlease RSS feed and JSON API
  - Nyaa.si RSS feed and HTML search page scraping
  - Any generic RSS feed with standard <item> elements
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.constants import NetworkConfig

logger = logging.getLogger(__name__)

# Pre-compiled regex to extract the numeric torrent ID from a Nyaa view URL.
# Example: "https://nyaa.si/view/1234567" → captures "1234567"
NYAA_VIEW_ID_RE = re.compile(r'nyaa\.si/view/(\d+)')


def fetch_rss_feed(url: str, timeout: int = NetworkConfig.DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """
    Download and parse a standard RSS feed from any URL.

    This is the main generic RSS parser. It handles feeds from SubsPlease, Nyaa,
    or any other source that follows the RSS XML format. For each <item> in the feed,
    it tries to extract:
      - The release title (required — items without titles are skipped)
      - A magnet link (checked in <link>, <guid>, and <enclosure> tags)
      - A .torrent file URL (same tags, with special handling for Nyaa view pages)
      - The publication date

    Args:
        url: The RSS feed URL to fetch.
        timeout: How many seconds to wait before giving up on the request.

    Returns:
        A list of dictionaries, one per release. Each dict has keys:
          'title'       — the release title (always present)
          'magnet'      — magnet link string, or None if not found
          'torrent_url' — direct .torrent download URL, or None if not found
          'pub_date'    — publication date string, or None if not found
    """
    logger.info(f"Fetching RSS feed from: {url}")

    # Set headers to identify ourselves and tell the server we accept XML
    headers = {
        'User-Agent': NetworkConfig.USER_AGENT,
        'Accept': 'application/xml, text/xml, */*'
    }

    # --- Step 1: Download the RSS feed ---
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx, 5xx)
    except Exception as e:
        logger.error(f"Failed to fetch RSS feed from {url}: {e}")
        return []

    # --- Step 2: Parse the XML content ---
    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        logger.error(f"Failed to parse RSS XML from {url}: {e}")
        return []

    # --- Step 3: Loop through each <item> and extract release info ---
    # In RSS feeds, all release entries live inside <channel> → <item> tags
    items = root.findall('.//item')
    parsed_items: List[Dict[str, Any]] = []

    for item in items:
        # Every item must have a title — skip blank ones
        title = item.findtext('title', '').strip()
        if not title:
            continue

        # Get the publication date if available
        pub_date = item.findtext('pubDate')
        if pub_date:
            pub_date = pub_date.strip()

        # Collect all the potential link sources from the item.
        # RSS feeds store links in different tags depending on the source:
        #   <link>      — usually the main URL
        #   <guid>      — sometimes contains a magnet or torrent link
        #   <enclosure> — often holds the torrent file download URL
        raw_link = item.findtext('link', '').strip()
        raw_guid = item.findtext('guid', '').strip()

        # The <enclosure> tag stores its URL as an XML attribute, not text content
        enclosure_url = ''
        enclosure = item.find('enclosure')
        if enclosure is not None:
            enclosure_url = enclosure.get('url', '').strip()

        # Some Nyaa items include an <infoHash> tag (with a namespace prefix).
        # We scan all child tags and match by suffix to handle any namespace.
        info_hash = ''
        for child in item:
            if child.tag.endswith('infoHash'):
                info_hash = (child.text or '').strip()
                break

        # --- Step 3a: Find the magnet link ---
        # Check each link source to see if any of them is a magnet link
        magnet: Optional[str] = None
        torrent_url: Optional[str] = None

        for candidate in (raw_link, raw_guid, enclosure_url):
            if candidate.lower().startswith('magnet:'):
                magnet = candidate
                break

        # If there's no direct magnet link but we found an infoHash,
        # we can build a working magnet link from the hash and title
        if not magnet and info_hash:
            encoded_title = urllib.parse.quote(title)
            magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={encoded_title}"

        # --- Step 3b: Find the .torrent file download URL ---
        # Look for any HTTP link that isn't a magnet link
        for candidate in (raw_link, raw_guid, enclosure_url):
            if candidate.lower().startswith('http') and not candidate.lower().startswith('magnet:'):
                # Special case: Nyaa "view" pages (e.g. nyaa.si/view/12345) are
                # human-readable pages, not direct downloads. Convert them to the
                # actual download URL (nyaa.si/download/12345.torrent) instead.
                if 'nyaa.si/view/' in candidate:
                    match = NYAA_VIEW_ID_RE.search(candidate)
                    if match:
                        torrent_url = f"https://nyaa.si/download/{match.group(1)}.torrent"
                    continue  # Don't use the view URL directly as a torrent URL

                torrent_url = candidate
                break

        # Add the parsed item to our results list
        parsed_items.append({
            'title': title,
            'magnet': magnet,
            'torrent_url': torrent_url,
            'pub_date': pub_date
        })

    logger.info(f"Successfully parsed {len(parsed_items)} items from feed")
    return parsed_items


def get_subsplease_search_url(query: str, resolution: Optional[str] = None) -> str:
    """
    Build a SubsPlease RSS feed URL for the given search query.

    SubsPlease's RSS endpoint accepts a search term and an optional resolution
    filter (e.g. 1080, 720, 480). If no resolution is specified or it's "Any",
    all resolutions are included.

    Args:
        query: The show name or search term to look for.
        resolution: Optional resolution like "1080p". The trailing "p" is stripped
                    automatically since SubsPlease expects just the number.

    Returns:
        The fully constructed SubsPlease RSS feed URL as a string.
    """
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://subsplease.org/rss/?q={encoded_query}"

    if resolution and resolution != 'Any':
        # SubsPlease expects just the number (e.g. "1080"), not "1080p"
        res_val = resolution.replace('p', '').strip()
        url += f"&r={res_val}"

    return url


def get_nyaa_search_url(query: str, resolution: Optional[str] = None) -> str:
    """
    Build a Nyaa.si RSS feed URL for the given search query.

    Unlike SubsPlease, Nyaa doesn't have a separate resolution parameter —
    the resolution is appended directly to the search query string
    (e.g. "One Piece 1080p").

    The category "1_2" filters results to "Anime - English-translated" only.

    Args:
        query: The show name or search term.
        resolution: Optional resolution like "1080p", appended to the query text.

    Returns:
        The fully constructed Nyaa RSS feed URL as a string.
    """
    search_query = query
    if resolution and resolution != 'Any':
        # Nyaa uses free-text search, so we just tack the resolution onto the query
        search_query = f"{query} {resolution}"

    encoded_query = urllib.parse.quote_plus(search_query)
    # c=1_2 means category "Anime - English-translated"
    return f"https://nyaa.si/?page=rss&c=1_2&q={encoded_query}"


def fetch_nyaa_html_search(
    query: str,
    resolution: Optional[str] = None,
    timeout: int = NetworkConfig.DEFAULT_TIMEOUT
) -> List[Dict[str, Any]]:
    """
    Search Nyaa.si by scraping the HTML results page directly.

    This is used instead of (or in addition to) the RSS feed because the RSS feed
    only returns recent results. The HTML search page gives access to the full
    history of uploads, which is useful for finding older releases.

    We use regex-based HTML parsing here (instead of a proper HTML parser) to avoid
    adding extra dependencies like BeautifulSoup. The Nyaa page structure is simple
    and stable enough for this approach.

    Args:
        query: The show name or search term.
        resolution: Optional resolution filter (appended to query text).
        timeout: How many seconds to wait before giving up on the request.

    Returns:
        A list of release dicts with keys: 'title', 'magnet', 'torrent_url', 'pub_date'.
    """
    # Build the search URL — same as RSS but using the HTML page (no "page=rss")
    search_query = query
    if resolution and resolution != 'Any':
        search_query = f"{query} {resolution}"
    encoded_query = urllib.parse.quote_plus(search_query)
    # f=0 means "no filter" (show all results), c=1_2 means "Anime - English-translated"
    url = f"https://nyaa.si/?f=0&c=1_2&q={encoded_query}"

    logger.info(f"Fetching Nyaa HTML search from: {url}")
    headers = {
        'User-Agent': NetworkConfig.USER_AGENT,
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch Nyaa HTML search: {e}")
        return []

    # --- Parse the HTML table of results ---
    # Nyaa displays results in a <tbody> table. We extract just that section first.
    html = response.text
    tbody_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', html, re.DOTALL)
    if not tbody_match:
        logger.warning("No tbody found in Nyaa HTML page.")
        return []
    tbody = tbody_match.group(1)

    # Split the table body into individual rows (<tr> elements)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody, re.DOTALL)
    parsed_items: List[Dict[str, Any]] = []

    for row in rows:
        # --- Extract the title and Nyaa view ID ---
        # First try: look for a link with a title attribute (most common format)
        view_match = re.search(r'<a href="/view/(\d+)"[^>]*title="([^"]+)"', row)
        if not view_match:
            # Fallback: grab the link text content directly (less common)
            view_match = re.search(r'<a href="/view/(\d+)"[^>]*>(.*?)</a>', row)
        if not view_match:
            continue  # Can't identify this row — skip it

        view_id = view_match.group(1)
        title = view_match.group(2).strip()
        # Remove any stray HTML tags that might be inside the title text
        title = re.sub(r'<[^>]*>', '', title)

        # --- Extract the .torrent download link ---
        # Look for a direct download link; fall back to constructing one from the view ID
        torrent_match = re.search(r'href="(/download/\d+\.torrent)"', row)
        torrent_url = (
            f"https://nyaa.si{torrent_match.group(1)}" if torrent_match
            else f"https://nyaa.si/download/{view_id}.torrent"
        )

        # --- Extract the magnet link ---
        magnet_match = re.search(r'href="(magnet:\?xt=[^"]+)"', row)
        magnet = magnet_match.group(1) if magnet_match else None

        # --- Extract the publication date ---
        # Nyaa stores timestamps in a data-timestamp attribute on the date cell
        date_match = re.search(r'data-timestamp="(\d+)"[^>]*>([^<]+)</td>', row)
        pub_date = date_match.group(2).strip() if date_match else None

        parsed_items.append({
            'title': title,
            'magnet': magnet,
            'torrent_url': torrent_url,
            'pub_date': pub_date
        })

    logger.info(f"Successfully scraped {len(parsed_items)} items from Nyaa HTML search")
    return parsed_items


def fetch_subsplease_api_search(
    query: str,
    resolution: Optional[str] = None,
    timeout: int = NetworkConfig.DEFAULT_TIMEOUT
) -> List[Dict[str, Any]]:
    """
    Search SubsPlease's JSON API for historical releases.

    SubsPlease provides a JSON API endpoint separate from the RSS feed. This
    gives structured data (show name, episode number, per-resolution magnet links)
    that's easier to work with and includes more historical results than the RSS feed.

    The API returns a dictionary where each key is a show entry containing nested
    download objects — one per available resolution. We flatten this into the same
    list-of-dicts format used by the other fetch functions.

    Args:
        query: The show name or search term.
        resolution: Optional resolution filter (e.g. "1080p"). If specified,
                    only releases matching that resolution are included.
        timeout: How many seconds to wait before giving up on the request.

    Returns:
        A list of release dicts with keys: 'title', 'magnet', 'torrent_url', 'pub_date'.
        The 'torrent_url' is always None for SubsPlease API results (only magnets provided).
    """
    encoded_query = urllib.parse.quote_plus(query)
    # f=search tells the API we want search results; tz=UTC normalizes timestamps
    url = f"https://subsplease.org/api/?f=search&tz=UTC&s={encoded_query}"

    logger.info(f"Fetching SubsPlease API search from: {url}")
    headers = {
        'User-Agent': NetworkConfig.USER_AGENT,
        'Accept': 'application/json'
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch SubsPlease API search: {e}")
        return []

    # The API returns an empty list or a non-dict for "no results" — handle gracefully
    if not isinstance(data, dict):
        return []

    parsed_items: List[Dict[str, Any]] = []

    # Each entry in the response dict represents one show/episode combo.
    # Inside each entry, "downloads" is a list of per-resolution download options.
    for key, val in data.items():
        if not isinstance(val, dict):
            continue

        show = val.get('show', '').strip()        # e.g. "One Piece"
        episode = val.get('episode', '').strip()   # e.g. "1120"
        pub_date = val.get('release_date', '').strip() or val.get('time', '').strip()
        downloads = val.get('downloads', [])

        if not isinstance(downloads, list):
            continue

        # Each download entry has a resolution and a magnet link
        for dl in downloads:
            if not isinstance(dl, dict):
                continue

            res = dl.get('res', '').strip()        # e.g. "1080"
            magnet = dl.get('magnet', '').strip()

            # If the user asked for a specific resolution, skip non-matching ones
            if resolution and resolution != 'Any':
                clean_res = resolution.replace('p', '').strip()
                if res != clean_res:
                    continue

            # Build a human-readable title in the SubsPlease naming convention
            # e.g. "[SubsPlease] One Piece - 1120 (1080p)"
            title = f"[SubsPlease] {show} - {episode} ({res}p)"
            parsed_items.append({
                'title': title,
                'magnet': magnet,
                'torrent_url': None,  # SubsPlease API only provides magnet links
                'pub_date': pub_date
            })

    logger.info(f"Successfully retrieved {len(parsed_items)} items from SubsPlease API search")
    return parsed_items
