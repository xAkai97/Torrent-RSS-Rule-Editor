"""
GUI helper functions.

Utility functions for GUI operations that don't fit in other modules.
"""
import tkinter as tk
from datetime import datetime, timezone, timedelta
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


def parse_datetime_from_string(s: str) -> Optional[datetime]:
    """
    Parse a datetime string in various formats into a datetime object.
    
    Supports multiple common datetime formats including ISO format, RFC format,
    and formats with/without timezone information.
    
    Args:
        s: String containing date/time information
    
    Returns:
        datetime or None: Parsed datetime object with timezone info, or None if parsing fails
    """
    if not s or not isinstance(s, str):
        return None
    
    # Try common datetime formats
    formats = [
        '%d %b %Y %H:%M:%S %z',
        '%d %b %Y %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    
    # Try ISO format with Z suffix
    try:
        ds = s.strip()
        if ds.endswith('Z'):
            ds = ds[:-1] + '+00:00'
        dt = datetime.fromisoformat(ds)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def format_timedelta(td: timedelta) -> str:
    """
    Format a timedelta into a human-readable string.
    
    Args:
        td: Time delta to format
        
    Returns:
        Formatted string like "2 days, 3 hours" or "5 minutes"
    """
    total_seconds = int(td.total_seconds())
    
    if total_seconds < 60:
        return f"{total_seconds} seconds"
    
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        hour_str = f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{hour_str}, {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}" if remaining_minutes > 0 else hour_str
    
    days = hours // 24
    remaining_hours = hours % 24
    day_str = f"{days} day{'s' if days != 1 else ''}"
    return f"{day_str}, {remaining_hours} hour{'s' if remaining_hours != 1 else ''}" if remaining_hours > 0 else day_str


def looks_like_json_candidate(s: str) -> bool:
    """
    Quick check if a string might be JSON (starts with {, [, or ").
    
    Args:
        s: String to check
    
    Returns:
        bool: True if string looks like it could be JSON
    """
    if not s or not isinstance(s, str):
        return False
    ss = s.strip()
    return ss.startswith(('{', '[', '"'))


def validate_json_string(s: str) -> tuple[bool, Optional[str]]:
    """
    Validate if a string is valid JSON.
    
    Args:
        s: String to validate
        
    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not s or not isinstance(s, str):
        return (True, None)
    
    s = s.strip()
    if not looks_like_json_candidate(s):
        return (True, None)
    
    try:
        json.loads(s)
        return (True, None)
    except json.JSONDecodeError as e:
        return (False, str(e))
    except Exception as e:
        return (False, f"Validation error: {e}")


def validate_lastmatch_json(text_widget: tk.Text, status_label: tk.Label) -> bool:
    """
    Validate JSON in a text widget and update a status label.
    
    Args:
        text_widget: Tkinter Text widget containing JSON
        status_label: Label widget to update with validation status
        
    Returns:
        bool: True if JSON is valid or not JSON-like, False if invalid JSON
    """
    try:
        txt = text_widget.get('1.0', 'end').strip()
        status_label.config(text='', fg='green')
        
        if not txt:
            return True
        
        is_valid, error_msg = validate_json_string(txt)
        
        if not is_valid:
            status_label.config(text=f'❌ Invalid JSON: {error_msg}', fg='red')
            return False
        else:
            status_label.config(text='✓ Valid', fg='green')
            return True
            
    except Exception:
        return True


def update_lastmatch_display(
    text_widget: tk.Text,
    age_label: tk.Label,
    lm_value: any,
    use_24h: bool = True
) -> None:
    """
    Update lastMatch display field with formatted datetime information.
    
    Args:
        text_widget: Text widget to display lastMatch value
        age_label: Label widget to display age information
        lm_value: lastMatch value to display
        use_24h: Whether to use 24-hour time format
    """
    try:
        # Enable text widget for editing
        text_widget.config(state='normal')
        text_widget.delete('1.0', 'end')
        
        age_text = 'Age: N/A'
        
        # Handle different value types
        if isinstance(lm_value, (dict, list)):
            # JSON object/array
            text_widget.insert('1.0', json.dumps(lm_value, indent=2))
        elif isinstance(lm_value, str) and lm_value.strip():
            # Try to parse as datetime
            dt = parse_datetime_from_string(lm_value)
            
            if dt:
                # Format datetime
                if use_24h:
                    formatted = dt.strftime('%d %b %Y %H:%M:%S')
                else:
                    formatted = dt.strftime('%d %b %Y %I:%M:%S %p')
                
                text_widget.insert('1.0', formatted)
                
                # Calculate age
                try:
                    now = datetime.now(timezone.utc)
                    age = now - dt
                    age_text = f'Age: {format_timedelta(age)}'
                except Exception:
                    age_text = 'Age: N/A'
            else:
                # Not a datetime, show as-is
                text_widget.insert('1.0', lm_value)
        else:
            # None or other type
            text_widget.insert('1.0', '' if lm_value is None else str(lm_value))
        
        age_label.config(text=age_text)
        
    except Exception as e:
        logger.error(f"Error updating lastmatch display: {e}")
        try:
            text_widget.insert('1.0', '' if lm_value is None else str(lm_value))
        except Exception:
            pass
    finally:
        try:
            text_widget.config(state='disabled')
        except Exception:
            pass


def center_window(
    window: tk.Toplevel,
    width: int = None,
    height: int = None,
    parent: Optional[tk.Widget] = None,
) -> None:
    """
    Center a window on the screen.
    
    Args:
        window: Window to center
        width: Optional width (uses current width if None)
        height: Optional height (uses current height if None)
        parent: Optional parent widget to center within. If omitted, the
            function attempts to use window.master when available.
    """
    try:
        window.update_idletasks()

        # Backward compatibility: center_window(window, parent)
        # and center_window(window, width, height) are both supported.
        if parent is None and width is not None and not isinstance(width, (int, float)):
            parent = width
            width = None
            height = None
        
        if width is None:
            width = window.winfo_width()
        if height is None:
            height = window.winfo_height()
        
        ref = parent
        if ref is None:
            ref = window.master if isinstance(getattr(window, 'master', None), tk.Widget) else None

        if isinstance(ref, tk.Widget):
            ref.update_idletasks()
            ref_x = ref.winfo_rootx()
            ref_y = ref.winfo_rooty()
            ref_w = max(1, ref.winfo_width())
            ref_h = max(1, ref.winfo_height())
            x = ref_x + (ref_w - width) // 2
            y = ref_y + (ref_h - height) // 2
        else:
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2

        # Keep title bar visible.
        x = max(0, int(x))
        y = max(0, int(y))
        
        window.geometry(f'{width}x{height}+{x}+{y}')
    except Exception as e:
        logger.error(f"Error centering window: {e}")


__all__ = [
    'parse_datetime_from_string',
    'format_timedelta',
    'looks_like_json_candidate',
    'validate_json_string',
    'validate_lastmatch_json',
    'update_lastmatch_display',
    'center_window',
]
