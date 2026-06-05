"""Tests for Tk binding helper services extracted from main_window callbacks."""

from unittest.mock import MagicMock

from src.services.gui_bindings import (
    bind_all_shortcuts,
    build_keyboard_shortcut_actions,
    first_json_path,
    parse_dropped_paths,
)


def test_parse_dropped_paths_uses_splitlist_function():
    out = parse_dropped_paths('{a.json} {b.txt}', lambda data: ['a.json', 'b.txt'] if data else [])
    assert out == ['a.json', 'b.txt']


def test_first_json_path_returns_first_json_only():
    assert first_json_path(['a.txt', 'first.JSON', 'second.json']) == 'first.JSON'
    assert first_json_path(['a.txt', 'b.csv']) is None


def test_bind_all_shortcuts_binds_each_action():
    root = MagicMock()
    bind_all_shortcuts(root, {'<Control-o>': lambda _e: None, '<F5>': lambda _e: None})
    assert root.bind_all.call_count == 2


def test_build_keyboard_shortcut_actions_maps_expected_keys():
    root = MagicMock()
    season_var = MagicMock()
    year_var = MagicMock()
    status_var = MagicMock()

    import_fn = MagicMock()
    dispatch_fn = MagicMock()
    export_selected_fn = MagicMock()
    export_all_fn = MagicMock()
    clear_fn = MagicMock()
    refresh_fn = MagicMock()
    focus_search_fn = MagicMock()

    actions = build_keyboard_shortcut_actions(
        root=root,
        season_var=season_var,
        year_var=year_var,
        status_var=status_var,
        import_titles_from_file_fn=import_fn,
        dispatch_generation_fn=dispatch_fn,
        export_selected_titles_fn=export_selected_fn,
        export_all_titles_fn=export_all_fn,
        clear_all_titles_fn=clear_fn,
        refresh_treeview_display_fn=refresh_fn,
        focus_search_fn=focus_search_fn,
    )

    assert '<Control-o>' in actions
    assert '<Control-s>' in actions
    assert '<Control-f>' in actions

    actions['<Control-o>'](None)
    import_fn.assert_called_once_with(root, status_var)

    actions['<Control-s>'](None)
    dispatch_fn.assert_called_once_with(root, season_var, year_var, status_var)

    result = actions['<Control-f>'](None)
    focus_search_fn.assert_called_once()
    assert result == 'break'
