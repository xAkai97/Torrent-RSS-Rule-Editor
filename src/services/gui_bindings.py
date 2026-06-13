"""
GUI Binding Helpers — Keyboard Shortcuts and Drag-and-Drop (Tk Fallback).

These helpers wire up keyboard shortcuts and drag-and-drop file handling
for the Tk fallback GUI. They're extracted from the main window module to
keep the GUI code thinner and make the bindings easier to test.

Note: The Qt GUI (PySide6) has its own shortcut system. This module is
specifically for the legacy Tk fallback runtime.
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
    refresh_library_display_fn: Callable[[], Any],
    focus_search_fn: Callable[[], Any],
) -> Dict[str, Callable[[Any], Any]]:
    """
    Build the keyboard shortcut → callback map for the Tk main window.

    Returns a dictionary mapping Tk key sequences to their handler functions.
    Both uppercase and lowercase variants are registered for each shortcut
    to work regardless of Caps Lock state.

    Supported shortcuts:
      Ctrl+O         → Import titles from file
      Ctrl+S         → Generate/save rules
      Ctrl+E         → Export selected titles
      Ctrl+Shift+E   → Export all titles
      Ctrl+Q         → Quit application
      Ctrl+Shift+C   → Clear all titles
      F5             → Refresh library display
      Ctrl+F         → Focus the search bar
      Ctrl+B/Z/T     → Reserved (no-op placeholders for future features)

    Args:
        root: The Tk root window.
        season_var / year_var / status_var: Tk StringVars for current state.
        *_fn: Callback functions for each shortcut action.

    Returns:
        A dict of {key_sequence: callback_function}.
    """

    def _focus_search(_event):
        focus_search_fn()
        return 'break'  # Prevent the event from propagating further

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
        '<F5>': lambda _e: refresh_library_display_fn(),
        # Reserved shortcuts — currently no-ops, available for future features
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
    """
    Register all keyboard shortcut callbacks on the Tk root window.

    Args:
        root: The Tk root window.
        actions: The shortcut map from build_keyboard_shortcut_actions().
    """
    for key, callback in actions.items():
        root.bind_all(key, callback)


def parse_dropped_paths(raw_data: str, splitlist_fn: Callable[[str], Iterable[str]]) -> List[str]:
    """
    Parse a drag-and-drop payload into a list of file paths.

    Tk's drag-and-drop gives us raw data that needs to be split using
    the platform-specific splitlist function. This wraps that parsing
    with error handling.

    Args:
        raw_data: The raw drop event data string.
        splitlist_fn: Platform-specific function to split the data into paths
                      (usually tk.splitlist).

    Returns:
        A list of file path strings, or empty list on error.
    """
    try:
        return [str(item) for item in splitlist_fn(raw_data or '')]
    except Exception:
        return []


def first_json_path(paths: Iterable[str]) -> Optional[str]:
    """
    Find the first .json file in a list of dropped file paths.

    When a user drops multiple files, we only care about JSON rule files.
    This picks the first one found.

    Args:
        paths: Iterable of file path strings.

    Returns:
        The first path ending in '.json', or None if none found.
    """
    for path in paths or []:
        text = str(path or '')
        if text.lower().endswith('.json'):
            return text
    return None
