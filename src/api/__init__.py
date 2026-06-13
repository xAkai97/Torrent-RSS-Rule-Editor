"""
API Package — External service communication layer.

This package contains all modules that talk to external services:
  - qbittorrent.py  → Connects to the qBittorrent WebUI API for managing
                       RSS feeds, download rules, and torrent operations.
  - subsplease.py   → Scrapes SubsPlease and AniList for anime schedule data,
                       title variations, and language-specific metadata.
  - rss_fetcher.py  → Generic RSS feed fetching/parsing for SubsPlease, Nyaa, etc.

Re-exports from qbittorrent and subsplease are made available here so other
parts of the app can do `from src.api import QBittorrentClient` directly.
"""

from .qbittorrent import *
from .subsplease import *

__all__ = []
