"""GUI binding helpers for Tk fallback runtime.

These helpers keep repetitive shortcut and drag-and-drop callback wiring out of
the Tk main window module while preserving current behavior.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


def build_keyboard_shortcut_actions(
    root: Any,
    season_var: Any,
    year_var: Any,
    status_var: Any,
    import_titles_from_file_fn: Callable[..., Any],
    dispatch_generation_fn: Callable[..., Any],
    export_selected_titles_fn: Callable[..., Any],
    export_all_titles_fn: Callable[..., Any],
    clear_all_titles_fn: Callable[..., Any],
    refresh_treeview_display_fn: Callable[[], Any],
    focus_search_fn: Callable[[], Any],
) -> Dict[str, Callable[[Any], Any]]:
    """Build keybinding callback map used by setup_keyboard_shortcuts."""

    def _focus_search(_event):
        focus_search_fn()
        return 'break'

    return {
        '<Control-o>': lambda _e: import_titles_from_file_fn(root, status_var),
        '<Control-O>': lambda _e: import_titles_from_file_fn(root, status_var),
        '<Control-s>': lambda _e: dispatch_generation_fn(root, season_var, year_var, status_var),
        '<Control-S>': lambda _e: dispatch_generation_fn(root, season_var, year_var, status_var),
        '<Control-e>': lambda _e: export_selected_titles_fn(),
        '<Control-E>': lambda _e: export_selected_titles_fn(),
        '<Control-Shift-E>': lambda _e: export_all_titles_fn(),
        '<Control-Shift-e>': lambda _e: export_all_titles_fn(),
        '<Control-q>': lambda _e: root.quit(),
        '<Control-Q>': lambda _e: root.quit(),
        '<Control-Shift-C>': lambda _e: clear_all_titles_fn(root, status_var),
        '<Control-Shift-c>': lambda _e: clear_all_titles_fn(root, status_var),
        '<F5>': lambda _e: refresh_treeview_display_fn(),
        '<Control-b>': lambda _e: None,
        '<Control-B>': lambda _e: None,
        '<Control-z>': lambda _e: None,
        '<Control-Z>': lambda _e: None,
        '<Control-t>': lambda _e: None,
        '<Control-T>': lambda _e: None,
        '<Control-Shift-t>': lambda _e: None,
        '<Control-Shift-T>': lambda _e: None,
        '<Control-f>': _focus_search,
        '<Control-F>': _focus_search,
    }


def bind_all_shortcuts(root: Any, actions: Dict[str, Callable[[Any], Any]]) -> None:
    """Bind all configured keyboard shortcut callbacks on root."""
    for key, callback in actions.items():
        root.bind_all(key, callback)


def parse_dropped_paths(raw_data: str, splitlist_fn: Callable[[str], Iterable[str]]) -> List[str]:
    """Parse drag-and-drop payload into normalized path list."""
    try:
        return [str(item) for item in splitlist_fn(raw_data or '')]
    except Exception:
        return []


def first_json_path(paths: Iterable[str]) -> Optional[str]:
    """Return first dropped .json path, if any."""
    for path in paths or []:
        text = str(path or '')
        if text.lower().endswith('.json'):
            return text
    return None
