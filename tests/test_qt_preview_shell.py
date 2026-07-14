import pytest
try:
    from src.gui_qt.main_window import (
        run_qt_subsplease_refresh,
        run_qt_anilist_refresh,
        run_qt_qbittorrent_snapshot,
        run_qt_connection_test,
        run_qt_get_connection_settings,
        run_qt_save_connection_settings,
        run_qt_get_runtime_settings,
        run_qt_save_runtime_settings,
        run_qt_get_platform_settings,
        run_qt_save_platform_settings,
        run_qt_load_log_tail,
        run_qt_clear_log_file,
        run_qt_import_titles_from_text,
        run_qt_import_titles_from_path,
        run_qt_import_dropped_paths,
        run_qt_clear_all_titles,
        run_qt_export_all_titles_to_path,
        run_qt_remove_titles_by_rule_names,
        run_qt_export_selected_titles_to_path,
        run_qt_commit_rule_drafts,
        run_qt_rule_sync_dry_run,
        run_qt_apply_rule_sync,
    )
    pyside_available = True
except ImportError:
    pyside_available = False

from src.constants import AniListRefreshScope

pytestmark = pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")

def test_run_qt_subsplease_refresh_uses_service_wrapper(monkeypatch):
    expected = {'fetch_status': 'ok', 'app_status': 'done', 'should_update_variations': True}

    def _fake_run_subsplease_refresh(**kwargs):
        assert callable(kwargs['can_pull_subsplease_cache'])
        assert callable(kwargs['fetch_subsplease_schedule'])
        assert kwargs['force_refresh'] is True
        return expected

    monkeypatch.setattr('src.gui_qt.main_window.run_subsplease_refresh', _fake_run_subsplease_refresh)

    result = run_qt_subsplease_refresh()
    assert result == expected

def test_run_qt_anilist_refresh_passes_inputs(monkeypatch):
    expected = {'fetch_status': 'ok', 'app_status': 'done', 'should_update_variations': False}

    def _fake_run_anilist_refresh(**kwargs):
        assert kwargs['current_title'] == 'Darwin Jihen'
        assert kwargs['current_must'] == 'Darwin'
        assert kwargs['selected_season'] == 'Spring'
        assert kwargs['selected_year'] == '2026'
        assert kwargs['refresh_scope_override'] == AniListRefreshScope.TITLE_AND_SEASON
        return expected

    monkeypatch.setattr('src.gui_qt.main_window.run_anilist_refresh', _fake_run_anilist_refresh)

    result = run_qt_anilist_refresh(
        current_title='Darwin Jihen',
        current_must='Darwin',
        selected_season='Spring',
        selected_year='2026',
        refresh_scope_override=AniListRefreshScope.TITLE_AND_SEASON,
    )
    assert result == expected

def test_run_qt_qbittorrent_snapshot_uses_service(monkeypatch):
    expected = {'success': True, 'message': 'Snapshot loaded.'}

    monkeypatch.setattr('src.gui_qt.main_window.load_qbittorrent_snapshot', lambda: expected)

    result = run_qt_qbittorrent_snapshot()
    assert result == expected

def test_run_qt_commit_rule_drafts_uses_service(monkeypatch):
    expected = {'updated_count': 2, 'matched_count': 2, 'requested_count': 2, 'unresolved_rule_names': []}

    def _fake_commit(rows):
        assert isinstance(rows, list)
        return expected

    monkeypatch.setattr('src.gui_qt.main_window.commit_rule_enabled_drafts_to_local_titles', _fake_commit)

    result = run_qt_commit_rule_drafts([{'rule_name': 'Rule A', 'enabled': 'Yes'}])
    assert result == expected

def test_run_qt_rule_sync_dry_run_uses_service(monkeypatch):
    expected = {'change_count': 1, 'missing_count': 0, 'changes': [{}]}

    def _fake_dry_run(rule_rows, selected_rule_names, **kwargs):
        assert isinstance(rule_rows, list)
        assert selected_rule_names == ['Rule A']
        return expected

    monkeypatch.setattr('src.gui_qt.main_window.build_rule_sync_dry_run', _fake_dry_run)

    result = run_qt_rule_sync_dry_run([{'rule_name': 'Rule A'}], ['Rule A'])
    assert result == expected

def test_run_qt_apply_rule_sync_uses_service(monkeypatch):
    expected = {'applied_count': 1, 'failed_count': 0, 'success': True}

    def _fake_apply(changes):
        assert isinstance(changes, list)
        return expected

    monkeypatch.setattr('src.gui_qt.main_window.apply_rule_sync_plan', _fake_apply)

    result = run_qt_apply_rule_sync([{'rule_name': 'Rule A', 'rule_def': {'enabled': True}}])
    assert result == expected

def test_run_qt_connection_test_success(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.get_connection_status_text', lambda _cfg: 'Online: http://localhost:8080')
    monkeypatch.setattr('src.gui_qt.main_window.ping_qbittorrent', lambda *args, **kwargs: (True, 'Connected - version 5.0.0'))

    result = run_qt_connection_test()

    assert result['success'] is True
    assert result['status_text'] == 'Online: http://localhost:8080'
    assert 'Connected' in result['message']

def test_run_qt_connection_test_failure(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.get_connection_status_text', lambda _cfg: 'Online: http://bad-host:8080')
    monkeypatch.setattr('src.gui_qt.main_window.ping_qbittorrent', lambda *args, **kwargs: (False, 'Connection failed'))

    result = run_qt_connection_test()

    assert result['success'] is False
    assert result['status_text'] == 'Online: http://bad-host:8080'
    assert result['message'] == 'Connection failed'

def test_run_qt_get_connection_settings_reads_config(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_PROTOCOL', 'https')
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_HOST', 'example.local')
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_PORT', '8443')
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_USER', 'alice')
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_PASS', 'secret')
    monkeypatch.setattr('src.gui_qt.main_window.config.CONNECTION_MODE', 'auto')
    monkeypatch.setattr('src.gui_qt.main_window.config.QBT_VERIFY_SSL', False)

    settings = run_qt_get_connection_settings()

    assert settings['protocol'] == 'https'
    assert settings['host'] == 'example.local'
    assert settings['port'] == '8443'
    assert settings['username'] == 'alice'
    assert settings['password'] == 'secret'
    assert settings['mode'] == 'auto'
    assert settings['verify_ssl'] is False

def test_run_qt_save_connection_settings_success(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.get_connection_status_text', lambda _cfg: 'Online: https://example.local:8443')

    captured = {}

    def _fake_save(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return True

    result = run_qt_save_connection_settings(
        {
            'protocol': 'https',
            'host': 'example.local',
            'port': '8443',
            'username': 'alice',
            'password': 'secret',
            'mode': 'auto',
            'verify_ssl': True,
        },
        save_config_fn=_fake_save,
    )

    assert result['success'] is True
    assert result['message'] == 'Connection settings saved.'
    assert result['status_text'] == 'Online: https://example.local:8443'
    assert captured['args'][:7] == ('https', 'example.local', '8443', 'alice', 'secret', 'auto', True)

def test_run_qt_save_connection_settings_invalid_values_normalized(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.get_connection_status_text', lambda _cfg: 'Mode: unknown')

    captured = {}

    def _fake_save(*args, **kwargs):
        captured['args'] = args
        return False

    result = run_qt_save_connection_settings(
        {
            'protocol': 'bad',
            'host': ' h ',
            'port': '',
            'username': 'u',
            'password': 'p',
            'mode': 'invalid',
            'verify_ssl': False,
        },
        save_config_fn=_fake_save,
    )

    assert captured['args'][:7] == ('http', 'h', '8080', 'u', 'p', 'online', False)
    assert result['success'] is False
    assert result['message'] == 'Failed to save connection settings.'

def test_run_qt_get_runtime_settings_reads_and_normalizes(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.get_pref', lambda k, d=None: {
        'theme': 'DARK',
        'log_level': 'warning',
        'ui_style_theme': 'vista',
    }.get(k, d))

    settings = run_qt_get_runtime_settings()

    assert settings['theme'] == 'dark'
    assert settings['log_level'] == 'WARNING'
    assert settings['ui_style_theme'] == 'vista'

def test_run_qt_save_runtime_settings_success(monkeypatch):
    captured = []

    def _fake_set_pref(key, value):
        captured.append((key, value))
        return True

    result = run_qt_save_runtime_settings(
        {
            'theme': 'light',
            'log_level': 'debug',
            'ui_style_theme': 'clam',
        },
        set_pref_fn=_fake_set_pref,
    )

    assert result['success'] is True
    assert result['message'] == 'Runtime settings saved.'
    assert ('theme', 'light') in captured
    assert ('log_level', 'DEBUG') in captured
    assert ('ui_style_theme', 'clam') in captured

def test_run_qt_save_runtime_settings_invalid_values_normalized():
    captured = []

    def _fake_set_pref(key, value):
        captured.append((key, value))
        return key != 'log_level'

    result = run_qt_save_runtime_settings(
        {
            'theme': 'bad',
            'log_level': 'bad',
            'ui_style_theme': '',
        },
        set_pref_fn=_fake_set_pref,
    )

    assert ('theme', 'light') in captured
    assert ('log_level', 'INFO') in captured
    assert ('ui_style_theme', 'clam') in captured
    assert result['success'] is False
    assert result['message'] == 'Failed to save runtime settings.'


def test_auto_theme_detection_and_resolution():
    from src.gui_qt.main_window import get_host_machine_theme, get_effective_theme

    host_theme = get_host_machine_theme()
    assert host_theme in {'light', 'dark'}

    assert get_effective_theme('light') == 'light'
    assert get_effective_theme('dark') == 'dark'
    assert get_effective_theme('auto') == host_theme
    assert get_effective_theme('invalid_theme') == 'light'


def test_run_qt_get_runtime_settings_supports_auto(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.get_pref', lambda k, d=None: {
        'theme': 'AUTO',
        'log_level': 'warning',
        'ui_style_theme': 'vista',
    }.get(k, d))

    settings = run_qt_get_runtime_settings()

    assert settings['theme'] == 'auto'
    assert settings['log_level'] == 'WARNING'
    assert settings['ui_style_theme'] == 'vista'


def test_run_qt_save_runtime_settings_supports_auto(monkeypatch):
    captured = []

    def _fake_set_pref(key, value):
        captured.append((key, value))
        return True

    result = run_qt_save_runtime_settings(
        {
            'theme': 'auto',
            'log_level': 'debug',
            'ui_style_theme': 'clam',
        },
        set_pref_fn=_fake_set_pref,
    )

    assert result['success'] is True
    assert result['message'] == 'Runtime settings saved.'
    assert ('theme', 'auto') in captured


def test_run_qt_get_platform_settings_reads_and_normalizes(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.SUPPORTED_SERVERS', ['qbittorrent'])
    monkeypatch.setattr('src.gui_qt.main_window.config.MAIN_SERVER', 'BAD')
    monkeypatch.setattr('src.gui_qt.main_window.config.EXPORT_TARGETS', ['qbittorrent', 'invalid'])

    result = run_qt_get_platform_settings()

    assert result['main_server'] == 'qbittorrent'
    assert result['export_targets'] == ['qbittorrent']
    assert result['supported_servers'] == ['qbittorrent']

def test_run_qt_save_platform_settings_success(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.SUPPORTED_SERVERS', ['qbittorrent'])
    captured = {}

    def _fake_save(main_server, export_targets):
        captured['main_server'] = main_server
        captured['export_targets'] = export_targets
        return True

    result = run_qt_save_platform_settings(
        {
            'main_server': 'qbittorrent',
            'export_targets': ['qbittorrent', 'invalid'],
        },
        save_platform_config_fn=_fake_save,
    )

    assert result['success'] is True
    assert result['message'] == 'Platform settings saved.'
    assert captured['main_server'] == 'qbittorrent'
    assert captured['export_targets'] == ['qbittorrent']

def test_run_qt_save_platform_settings_defaults_when_empty(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.SUPPORTED_SERVERS', ['qbittorrent'])
    captured = {}

    def _fake_save(main_server, export_targets):
        captured['main_server'] = main_server
        captured['export_targets'] = export_targets
        return False

    result = run_qt_save_platform_settings(
        {
            'main_server': 'invalid',
            'export_targets': [],
        },
        save_platform_config_fn=_fake_save,
    )

    assert captured['main_server'] == 'qbittorrent'
    assert captured['export_targets'] == ['qbittorrent']
    assert result['success'] is False
    assert result['message'] == 'Failed to save platform settings.'

def test_run_qt_load_log_tail_returns_recent_lines(tmp_path):
    log_file = tmp_path / 'qbt_editor.log'
    log_file.write_text('line1\nline2\nline3\n', encoding='utf-8')

    result = run_qt_load_log_tail(str(log_file), max_lines=2)

    assert result['success'] is True
    assert result['line_count'] == 2
    assert result['content'] == 'line2\nline3\n'

def test_run_qt_load_log_tail_handles_missing_file(tmp_path):
    missing = tmp_path / 'missing.log'

    result = run_qt_load_log_tail(str(missing), max_lines=10)

    assert result['success'] is False
    assert result['line_count'] == 0
    assert 'Log file not found' in result['message']

def test_run_qt_import_titles_from_path_success(tmp_path, monkeypatch):
    import_file = tmp_path / 'titles.json'
    import_file.write_text('{"anime": [{"node": {"title": "Show A"}, "mustContain": "Show A", "ruleName": "Show A"}]}', encoding='utf-8')

    monkeypatch.setattr('src.gui_qt.main_window.config.ALL_TITLES', {'anime': []})
    monkeypatch.setattr(
        'src.gui_qt.main_window._import_titles_core',
        lambda parsed_data, season, year, prefix_imports, source_name, auto_sanitize_override: (True, 'Imported 1 new titles from qt file.', 1, 0),
    )

    result = run_qt_import_titles_from_path(str(import_file), season='Spring', year='2026', prefix_imports=True)

    assert result['success'] is True
    assert result['new_count'] == 1
    assert result['duplicates'] == 0
    assert 'Imported 1 new titles' in result['message']

def test_run_qt_import_titles_from_path_missing_file(tmp_path):
    missing = tmp_path / 'missing.json'
    result = run_qt_import_titles_from_path(str(missing))

    assert result['success'] is False
    assert 'Import file not found' in result['message']

def test_run_qt_import_titles_from_text_success(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.ALL_TITLES', {'anime': []})
    monkeypatch.setattr(
        'src.gui_qt.main_window._import_titles_core',
        lambda parsed_data, season, year, prefix_imports, source_name, auto_sanitize_override: (True, 'Imported 2 new titles.', 2, 0),
    )

    result = run_qt_import_titles_from_text(
        text='{"anime": [{"node": {"title": "A"}}, {"node": {"title": "B"}}]}',
        season='Spring',
        year='2026',
        prefix_imports=True,
        source_name='qt clipboard',
    )

    assert result['success'] is True
    assert result['new_count'] == 2
    assert result['duplicates'] == 0

def test_run_qt_import_titles_from_text_parse_failure():
    result = run_qt_import_titles_from_text(text='')

    assert result['success'] is False
    assert result['new_count'] == 0
    assert 'parse' in result['message'].lower()

def test_run_qt_export_all_titles_to_path_success(tmp_path, monkeypatch):
    export_path = tmp_path / 'export.json'
    monkeypatch.setattr('src.gui_qt.main_window.config.ALL_TITLES', {'anime': [{'mustContain': 'Show A'}]})
    monkeypatch.setattr('src.gui_qt.main_window.build_rules_from_titles', lambda _data: {'Show A': {'mustContain': 'Show A'}})

    result = run_qt_export_all_titles_to_path(str(export_path))

    assert result['success'] is True
    assert result['exported_rules'] == 1
    assert export_path.exists()

def test_run_qt_export_all_titles_to_path_no_data(monkeypatch):
    monkeypatch.setattr('src.gui_qt.main_window.config.ALL_TITLES', {})

    result = run_qt_export_all_titles_to_path('x.json')

    assert result['success'] is False
    assert result['exported_rules'] == 0
    assert result['message'] == 'No titles available to export.'

def test_run_qt_remove_titles_by_rule_names_success(monkeypatch):
    monkeypatch.setattr(
        'src.gui_qt.main_window.config.ALL_TITLES',
        {
            'anime': [
                {'node': {'title': 'Show A'}, 'ruleName': 'Rule A', 'mustContain': 'Show A'},
                {'node': {'title': 'Show B'}, 'ruleName': 'Rule B', 'mustContain': 'Show B'},
            ]
        },
    )

    result = run_qt_remove_titles_by_rule_names(['Rule A'])

    assert result['success'] is True
    assert result['removed_count'] == 1
    assert result['remaining_count'] == 1

def test_run_qt_remove_titles_by_rule_names_no_matches(monkeypatch):
    monkeypatch.setattr(
        'src.gui_qt.main_window.config.ALL_TITLES',
        {'anime': [{'node': {'title': 'Show A'}, 'ruleName': 'Rule A', 'mustContain': 'Show A'}]},
    )

    result = run_qt_remove_titles_by_rule_names(['Rule Z'])

    assert result['success'] is False
    assert result['removed_count'] == 0
    assert 'No matching library entries found' in result['message']

def test_run_qt_export_selected_titles_to_path_success(tmp_path, monkeypatch):
    export_path = tmp_path / 'selected_export.json'
    monkeypatch.setattr(
        'src.gui_qt.main_window.config.ALL_TITLES',
        {
            'anime': [
                {'node': {'title': 'Show A'}, 'ruleName': 'Rule A', 'mustContain': 'Show A'},
                {'node': {'title': 'Show B'}, 'ruleName': 'Rule B', 'mustContain': 'Show B'},
            ]
        },
    )
    monkeypatch.setattr('src.gui_qt.main_window.build_rules_from_titles', lambda data: {'Rule A': {'mustContain': 'Show A'}})

    result = run_qt_export_selected_titles_to_path(str(export_path), ['Rule A'])

    assert result['success'] is True
    assert result['exported_rules'] == 1
    assert export_path.exists()

def test_run_qt_export_selected_titles_to_path_no_selection(tmp_path, monkeypatch):
    export_path = tmp_path / 'selected_export.json'
    monkeypatch.setattr('src.gui_qt.main_window.config.ALL_TITLES', {'anime': []})

    result = run_qt_export_selected_titles_to_path(str(export_path), [])

    assert result['success'] is False
    assert result['exported_rules'] == 0
    assert result['message'] == 'No rule names selected for export.'

def test_run_qt_clear_all_titles_resets_config(monkeypatch):
    import src.gui_qt.main_window as qt_main_window
    monkeypatch.setattr(
        'src.gui_qt.main_window.config.ALL_TITLES',
        {
            'anime': [{'ruleName': 'Rule A'}],
            'manga': [{'ruleName': 'Rule B'}],
        },
    )

    result = run_qt_clear_all_titles()

    assert result['success'] is True
    assert result['cleared_count'] == 2
    assert qt_main_window.config.ALL_TITLES == {}

def test_run_qt_clear_log_file_success(tmp_path):
    log_file = tmp_path / 'qbt_editor.log'
    log_file.write_text('hello\nworld\n', encoding='utf-8')

    result = run_qt_clear_log_file(str(log_file))

    assert result['success'] is True
    assert log_file.read_text(encoding='utf-8') == ''
