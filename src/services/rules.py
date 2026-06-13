"""
RSS Rules Service — Convenience re-export.

This module re-exports everything from src.rss_rules so that other modules
can import rule functions via the services package:
  from src.services.rules import RSSRule, create_rule, build_save_path, ...
"""

from src.rss_rules import *
