"""LastMatch display and validation helpers for the editor panel."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Tuple


def format_lastmatch_value(
    value,
    use_24h: bool,
    parse_datetime_from_string: Callable[[str], object],
) -> Tuple[str, str]:
    """Return display text and age label text for a lastMatch value."""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, indent=2), 'Age: N/A'
        except Exception:
            return str(value), 'Age: N/A'

    if isinstance(value, str) and value.strip():
        parsed = parse_datetime_from_string(value.strip())
        if parsed is not None:
            try:
                local_tz = datetime.now().astimezone().tzinfo
                parsed_local = parsed.astimezone(local_tz)
            except Exception:
                parsed_local = parsed

            age_text = 'Age: N/A'
            try:
                now_local = datetime.now(parsed_local.tzinfo) if parsed_local.tzinfo is not None else datetime.now()
                delta = now_local - parsed_local
                secs = delta.total_seconds()
                if secs < 0:
                    future_secs = -int(secs)
                    if future_secs < 60:
                        age_phrase = 'In a few seconds'
                    elif future_secs < 3600:
                        age_phrase = f'In {future_secs//60} minute(s)'
                    elif future_secs < 86400:
                        age_phrase = f'In {future_secs//3600} hour(s)'
                    else:
                        age_phrase = f'In {abs(delta.days)} day(s)'
                else:
                    if secs < 60:
                        age_phrase = 'just now'
                    elif secs < 3600:
                        age_phrase = f'{int(secs//60)} minute(s) ago'
                    elif secs < 86400:
                        age_phrase = f'{int(secs//3600)} hour(s) ago'
                    else:
                        age_phrase = f'{delta.days} day(s) ago'
                age_text = f'Age: {age_phrase}'
            except Exception:
                age_text = 'Age: N/A'

            try:
                if use_24h:
                    fmt = '%Y-%m-%d %H:%M:%S %Z'
                else:
                    fmt = '%Y-%m-%d %I:%M:%S %p %Z'
                display = parsed_local.strftime(fmt)
            except Exception:
                display = value

            return display, age_text

    return '' if value is None else str(value), 'Age: N/A'


def validate_lastmatch_json_text(text: str) -> Tuple[bool, str]:
    """Validate potential JSON text and return (is_valid, status_message)."""
    try:
        txt = str(text or '').strip()
    except Exception:
        txt = ''

    if not txt:
        return True, ''

    if not _looks_like_json_candidate(txt):
        return True, ''

    try:
        json.loads(txt)
        return True, 'Valid JSON'
    except Exception as e:
        msg = f'Invalid JSON: {str(e)}'
        short = msg if len(msg) < 120 else msg[:116] + '...'
        return False, short


def _looks_like_json_candidate(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    ss = text.strip()
    return ss.startswith('{') or ss.startswith('[') or ss.startswith('"')
