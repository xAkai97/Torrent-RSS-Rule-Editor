import builtins
from unittest.mock import MagicMock, patch

import main as main_module


def test_main_import_error_exits_cleanly(capsys):
    """Import failures should not trigger secondary logger/unbound errors."""
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'src.config':
            raise ImportError('No module named src.config')
        return original_import(name, globals, locals, fromlist, level)

    with patch('builtins.__import__', side_effect=_fake_import), patch('sys.exit', side_effect=SystemExit(1)):
        try:
            main_module.main()
        except SystemExit as e:
            assert e.code == 1

    output = capsys.readouterr().out
    assert 'ERROR: Failed to import required modules' in output


def test_resolve_ui_mode_defaults_to_qt(monkeypatch):
    monkeypatch.delenv('TRRE_UI', raising=False)
    assert main_module._resolve_ui_mode([]) == 'qt'


def test_resolve_ui_mode_accepts_cli_over_env(monkeypatch):
    monkeypatch.setenv('TRRE_UI', 'tk')
    assert main_module._resolve_ui_mode(['--ui=qt']) == 'qt'


def test_main_routes_to_qt_when_requested(monkeypatch):
    monkeypatch.setattr(main_module, '_run_qt_gui', MagicMock())
    monkeypatch.setattr(main_module, '_run_tk_gui', MagicMock())

    main_module.main(['--ui=qt'])

    main_module._run_qt_gui.assert_called_once()
    main_module._run_tk_gui.assert_not_called()


def test_main_routes_to_tk_by_default(monkeypatch):
    monkeypatch.setattr(main_module, '_run_qt_gui', MagicMock())
    monkeypatch.setattr(main_module, '_run_tk_gui', MagicMock())

    main_module.main([])

    main_module._run_qt_gui.assert_called_once()
    main_module._run_tk_gui.assert_not_called()


def test_main_routes_to_tk_when_requested(monkeypatch):
    monkeypatch.setattr(main_module, '_run_qt_gui', MagicMock())
    monkeypatch.setattr(main_module, '_run_tk_gui', MagicMock())

    main_module.main(['--ui=tk'])

    main_module._run_tk_gui.assert_called_once()
    main_module._run_qt_gui.assert_not_called()


def test_main_qt_missing_dependency_exits_cleanly(monkeypatch, capsys):
    def _raise_import_error():
        raise ImportError('PySide6 is required for Qt preview mode.')

    monkeypatch.setattr(main_module, '_run_qt_gui', _raise_import_error)
    monkeypatch.setattr(main_module, '_run_tk_gui', MagicMock())

    with patch('sys.exit', side_effect=SystemExit(1)):
        try:
            main_module.main(['--ui=qt'])
        except SystemExit as e:
            assert e.code == 1

    output = capsys.readouterr().out
    assert 'ERROR: Qt mode is unavailable' in output


def test_open_settings_window_reuses_existing_instance():
    """Opening settings twice should focus existing window and avoid duplicates."""
    from src.gui.dialogs import open_settings_window

    root = MagicMock()
    existing_window = MagicMock()
    existing_window.winfo_exists.return_value = True
    root._settings_window = existing_window

    status_var = MagicMock()

    with patch('src.gui.dialogs.tk.Toplevel') as toplevel_mock:
        open_settings_window(root, status_var)

    toplevel_mock.assert_not_called()
    existing_window.lift.assert_called_once()
    existing_window.focus_force.assert_called_once()


def test_open_setup_wizard_reuses_existing_instance():
    """Setup wizard should reuse the existing settings window instance."""
    from src.gui.dialogs import open_setup_wizard

    root = MagicMock()
    existing_window = MagicMock()
    existing_window.winfo_exists.return_value = True
    root._settings_window = existing_window

    status_var = MagicMock()

    with patch('src.gui.dialogs.tk.Toplevel') as toplevel_mock, patch('src.gui.dialogs.messagebox.showinfo'):
        open_setup_wizard(root, status_var)

    toplevel_mock.assert_not_called()
    existing_window.lift.assert_called_once()
    existing_window.focus_force.assert_called_once()


def test_open_log_viewer_reuses_existing_instance():
    """Opening log viewer twice should focus existing window and avoid duplicates."""
    from src.gui.dialogs import open_log_viewer

    root = MagicMock()
    existing_window = MagicMock()
    existing_window.winfo_exists.return_value = True
    root._log_window = existing_window

    with patch('src.gui.dialogs.tk.Toplevel') as toplevel_mock:
        open_log_viewer(root)

    toplevel_mock.assert_not_called()
    existing_window.lift.assert_called_once()
    existing_window.focus_force.assert_called_once()
