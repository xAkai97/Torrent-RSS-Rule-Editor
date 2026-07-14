"""
Torrent RSS Rule Editor — Main Package.

This is the top-level package for the Torrent RSS Rule Editor application.
It provides a desktop GUI for creating, editing, and syncing qBittorrent
RSS download rules, with anime schedule integration from SubsPlease and
title variation lookups from AniList.

Package structure:
  src/
  ├── api/          → External API communication (qBittorrent, SubsPlease, AniList)
  ├── services/     → Business logic (rule syncing, drafts, file operations)
  ├── gui_qt/       → PySide6 GUI (main window, dialogs)
  ├── config.py     → App configuration and persistent state
  ├── cache.py      → Disk-based caching with TTL/size retention
  ├── constants.py  → Shared constants, enums, and custom exceptions
  ├── rss_rules.py  → RSSRule dataclass (core data model)
  ├── backup.py     → Backup/restore functionality
  └── utils.py      → Shared utility functions
"""

from __future__ import annotations

import importlib

from .config import config

__version__ = "0.9.0-dev"  
__author__ = "Maintainer"

# Lazy-loading map: allows `from src import rss_rules` etc. without importing
# everything upfront at startup. This improves app launch time by deferring
# heavy imports (like the GUI and API modules) until they're actually needed.
#
# Format: { attribute_name: (module_path_relative_to_src, attribute_within_module_or_None) }
# If the attribute name is None, the entire module is returned.
_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
	'qbittorrent_api': ('api.qbittorrent', None),
	'rss_rules': ('rss_rules', None),
	'backup': ('backup', None),
}


def __getattr__(name: str):
	"""
	Python module-level __getattr__ for lazy imports.

	When someone accesses an attribute on the `src` package that isn't already
	loaded (e.g. `src.rss_rules`), this function checks the _LAZY_ATTRS map,
	imports the target module on demand, and caches it in globals() so the
	import only happens once.
	"""
	target = _LAZY_ATTRS.get(name)
	if target is None:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

	module_name, attr_name = target
	module = importlib.import_module(f"{__name__}.{module_name}")
	# If attr_name is None, return the whole module; otherwise return a specific attribute
	value = module if attr_name is None else getattr(module, attr_name)
	globals()[name] = value  # Cache it so __getattr__ isn't called again for this name
	return value


# Public API of this package
__all__ = ["config", "qbittorrent_api", "rss_rules", "backup"]
