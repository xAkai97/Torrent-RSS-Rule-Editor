"""
Torrent RSS Rule Editor - Modular Package

A desktop application package for generating and synchronizing qBittorrent RSS rules.

"""

from __future__ import annotations

import importlib

from .config import config

__version__ = "0.9.0-dev"  
__author__ = "Maintainer"

_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
	'setup_gui': ('gui', 'setup_gui'),
	'exit_handler': ('gui', 'exit_handler'),
	'qbittorrent_api': ('api.qbittorrent', None),
	'rss_rules': ('rss_rules', None),
	'backup': ('backup', None),
}


def __getattr__(name: str):
	target = _LAZY_ATTRS.get(name)
	if target is None:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

	module_name, attr_name = target
	module = importlib.import_module(f"{__name__}.{module_name}")
	value = module if attr_name is None else getattr(module, attr_name)
	globals()[name] = value
	return value


__all__ = ["config", "setup_gui", "exit_handler", "qbittorrent_api", "rss_rules", "backup"]
