"""
Backup Service — Convenience re-export.

This module re-exports everything from src.backup so that other modules
can import backup functions via the services package:
  from src.services.backup import create_backup, load_backup, ...
"""

from src.backup import *
