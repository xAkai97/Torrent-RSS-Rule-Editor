"""GUI helpers package with backward-compatible exports."""

import logging
import json
import tkinter as tk
from typing import Optional

from src.config import config

from .constants import UIConstants
from .debounce import create_auto_apply_debounce
from .parsers import parse_datetime_from_string
from .theme import get_editor_theme_colors, get_ui_theme_colors
from .variables import create_editor_variables

logger = logging.getLogger(__name__)


def get_ui_font_family(default: str = 'Segoe UI') -> str:
    try:
        family = str(config.get_pref('font_family', default) or '').strip()
    except Exception:
        family = default
    return family or default


def get_ui_font_size(default: int = 9, min_size: int = 8, max_size: int = 14) -> int:
    try:
        size = int(config.get_pref('font_size', default))
    except (TypeError, ValueError, AttributeError):
        size = default
    return max(min_size, min(max_size, size))


def get_ui_font(
    size_delta: int = 0,
    weight: str = 'normal',
    slant: str = 'roman',
    family: Optional[str] = None,
) -> tuple:
    size = max(8, get_ui_font_size() + int(size_delta))
    resolved_family = family or get_ui_font_family()
    return (resolved_family, size, weight, slant)


def get_ui_mono_font(size_delta: int = 0) -> tuple:
    size = max(8, get_ui_font_size() + int(size_delta))
    return ('Consolas', size)


def enable_global_mousewheel_scrolling(root: tk.Tk) -> None:
    def _wheel_units(event: tk.Event) -> int:
        if hasattr(event, 'num') and event.num in (4, 5):
            return -1 if event.num == 4 else 1
        delta = getattr(event, 'delta', 0)
        if delta == 0:
            return 0
        return int(-1 * (delta / 120))

    def _is_shift_held(event: tk.Event) -> bool:
        try:
            return bool(getattr(event, 'state', 0) & 0x0001)
        except Exception:
            return False

    def _find_scroll_target(widget: tk.Misc, axis: str = 'y'):
        cur = widget
        while cur is not None:
            if cur.winfo_class() == 'Treeview':
                return None
            if axis == 'x' and hasattr(cur, 'xview_scroll'):
                return cur
            if axis == 'y' and hasattr(cur, 'yview_scroll'):
                return cur
            parent_name = cur.winfo_parent()
            if not parent_name:
                break
            try:
                cur = cur.nametowidget(parent_name)
            except Exception:
                break
        return None

    def _on_mousewheel(event: tk.Event):
        try:
            units = _wheel_units(event)
            if units == 0:
                return None
            if _is_shift_held(event):
                target_x = _find_scroll_target(event.widget, axis='x')
                if target_x is not None:
                    target_x.xview_scroll(units, 'units')
                    return 'break'

            target_y = _find_scroll_target(event.widget, axis='y')
            if target_y is None:
                return None
            target_y.yview_scroll(units, 'units')
            return 'break'
        except Exception:
            return None

    try:
        root.bind_all('<MouseWheel>', _on_mousewheel, add='+')
        root.bind_all('<Button-4>', _on_mousewheel, add='+')
        root.bind_all('<Button-5>', _on_mousewheel, add='+')
    except Exception:
        logger.debug('Global mousewheel binding skipped', exc_info=True)


def center_window(
    window: tk.Toplevel,
    width: int = None,
    height: int = None,
    parent: Optional[tk.Widget] = None,
) -> None:
    try:
        window.update_idletasks()

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

        window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
    except Exception as e:
        logger.error(f'Error centering window: {e}')


def looks_like_json_candidate(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    return s.strip().startswith(('{', '[', '"'))


def validate_json_string(s: str) -> tuple[bool, Optional[str]]:
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
        return (False, f'Validation error: {e}')


__all__ = [
    'UIConstants',
    'create_auto_apply_debounce',
    'create_editor_variables',
    'parse_datetime_from_string',
    'get_editor_theme_colors',
    'get_ui_theme_colors',
    'get_ui_font_family',
    'get_ui_font_size',
    'get_ui_font',
    'get_ui_mono_font',
    'enable_global_mousewheel_scrolling',
    'center_window',
    'looks_like_json_candidate',
    'validate_json_string',
]
