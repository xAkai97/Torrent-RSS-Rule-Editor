"""Tests for Qt drag-and-drop import aggregation helpers."""

from pathlib import Path

from src.gui_qt.main_window import run_qt_import_dropped_paths


def test_run_qt_import_dropped_paths_imports_supported_files(tmp_path: Path):
    a = tmp_path / 'a.json'
    b = tmp_path / 'b.csv'
    a.write_text('{}', encoding='utf-8')
    b.write_text('name\nvalue\n', encoding='utf-8')

    calls = []

    def _fake_import(path, season='', year='', prefix_imports=False):
        calls.append((path, season, year, prefix_imports))
        return {'success': True, 'message': f'Imported {path}'}

    result = run_qt_import_dropped_paths(
        [str(a), str(b)],
        season='Spring',
        year='2026',
        prefix_imports=True,
        import_from_path_fn=_fake_import,
    )

    assert result['imported_count'] == 2
    assert result['attempted_count'] == 2
    assert result['failed_count'] == 0
    assert result['skipped_count'] == 0
    assert len(calls) == 2
    assert all(call[1] == 'Spring' and call[2] == '2026' and call[3] is True for call in calls)


def test_run_qt_import_dropped_paths_skips_unsupported_and_missing(tmp_path: Path):
    txt = tmp_path / 'ok.txt'
    txt.write_text('demo', encoding='utf-8')
    unsupported = tmp_path / 'bad.md'
    missing = tmp_path / 'missing.json'

    def _fake_import(path, season='', year='', prefix_imports=False):
        return {'success': True, 'message': f'Imported {path}'}

    result = run_qt_import_dropped_paths(
        [str(txt), str(unsupported), str(missing)],
        import_from_path_fn=_fake_import,
    )

    assert result['attempted_count'] == 1
    assert result['imported_count'] == 1
    assert result['failed_count'] == 1
    assert result['skipped_count'] == 1
    details = '\n'.join(result['details'])
    assert 'unsupported file type' in details.lower()
    assert 'File not found' in details


def test_run_qt_import_dropped_paths_records_failed_import_message(tmp_path: Path):
    a = tmp_path / 'a.json'
    a.write_text('{}', encoding='utf-8')

    def _fake_import(path, season='', year='', prefix_imports=False):
        return {'success': False, 'message': 'Import failed for payload'}

    result = run_qt_import_dropped_paths([str(a)], import_from_path_fn=_fake_import)

    assert result['attempted_count'] == 1
    assert result['imported_count'] == 0
    assert result['failed_count'] == 1
    assert any('Import failed for payload' in line for line in result['details'])
