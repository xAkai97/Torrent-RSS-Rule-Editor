"""
Parsing and Conversion Utilities

Helpers for parsing various data formats.
"""

from datetime import datetime, timezone
from typing import Any, Optional


def parse_datetime_from_string(s: str) -> Optional[datetime]:
    """
    Parses a datetime string in various formats into a datetime object.
    
    Args:
        s: String containing date/time information
    
    Returns:
        datetime or None: Parsed datetime object with timezone info, or None if parsing fails
    """
    if not s or not isinstance(s, str):
        return None
    
    for fmt in ('%d %b %Y %H:%M:%S %z', '%d %b %Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S'):
        try:
            ds = s.strip()
            if ds.endswith('Z'):
                ds = ds[:-1] + ' +0000'
            if '+' in ds or '-' in ds:
                parts = ds.rsplit(' ', 1)
                if len(parts) == 2 and (':' in parts[1]):
                    tz = parts[1].replace(':', '')
                    ds = parts[0] + ' ' + tz
            dt = datetime.strptime(ds, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    
    try:
        ds = s.strip()
        if ds.endswith('Z'):
            ds = ds[:-1] + '+00:00'
        dt = datetime.fromisoformat(ds)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
