"""
Settings Dialog Module.

Implements the monolithic Settings Dialog which manages all user configuration.
The settings are split across several tabs:
  - Connection: qBittorrent server profiles and SSL settings
  - Defaults: Default paths, categories, and tags
  - Import/Export: Auto-sanitization and prefix handling logic
  - Sanitization: Custom character replacement rules
  - Appearance: Theme, time format, and list view densities
  - Action Bar: Fully customizable toolbar (add/remove/reorder buttons)
  - Font & Style: Global UI scaling and styling preferences
  - Diagnostics: Application logs and worker thread statuses
  - API Rate Limits: Cache TTLs and cooldown timers for external APIs
"""

import os
import copy
import logging
from PySide6 import QtCore as core
from PySide6 import QtGui as gui
from PySide6 import QtWidgets as widgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QCheckBox, QRadioButton, QWidget, QGroupBox,
    QStackedWidget, QMessageBox, QTabWidget, QFileDialog, QFrame, QListWidget,
    QListWidgetItem, QSpinBox, QTreeWidget, QTreeWidgetItem, QInputDialog,
    QAbstractItemView, QStyle, QScrollArea
)
from PySide6.QtGui import QIcon

from src.config import config
from src.constants import PrefKeys, CacheRetentionMode, AniListRefreshScope, FileSystem
from src.gui_qt.main_window import (
    DEFAULT_ACTION_BAR_ORDER,
    DEFAULT_BUTTON_METADATA,
    DEFAULT_DROPDOWN_SUBACTIONS,
    STANDARD_ICONS,
    SUBACTION_METADATA,
    run_qt_get_connection_settings,
    run_qt_get_runtime_settings,
    run_qt_get_platform_settings,
    run_qt_save_connection_settings,
    run_qt_save_platform_settings,
    run_qt_save_runtime_settings,
    run_qt_clear_log_file
)
from src.gui_qt.workers import ConnectionTestWorker
from src.api.qbittorrent import ping_qbittorrent
from src.utils import restart_application

logger = logging.getLogger(__name__)

class SettingsDialog(QDialog):
    """
    Main Configuration UI.

    A complex tabbed dialog that binds directly to the central `config` module.
    Due to the extensive number of settings, the UI is dynamically generated
    in a single massive `__init__` pass. When the user clicks 'Apply' or 'Save',
    the fields are read and written to the respective config sub-systems.
    """
    def __init__(self, parent=None, rebuild_action_bar_callback=None, set_theme_pref_callback=None, on_window_resize_callback=None, active_workers=None):
        super().__init__(parent)
        
        # Setup local references to match closure variables in monolithic setup_gui_qt
        window = parent
        dialog = self
        rebuild_action_bar = rebuild_action_bar_callback
        set_theme_pref = set_theme_pref_callback
        _on_window_resize = on_window_resize_callback
        
        if active_workers is None:
            active_workers = []

        import tempfile
        temp_dir = tempfile.gettempdir()
        settings_path = os.path.join(temp_dir, 'qbt_settings_gear.svg').replace('\\', '/')
        theme_light_path = os.path.join(temp_dir, 'qbt_theme_light.svg').replace('\\', '/')
        theme_dark_path = os.path.join(temp_dir, 'qbt_theme_dark.svg').replace('\\', '/')
        theme_auto_path = os.path.join(temp_dir, 'qbt_theme_auto.svg').replace('\\', '/')
        undo_path = os.path.join(temp_dir, 'qbt_undo.svg').replace('\\', '/')
        export_path = os.path.join(temp_dir, 'qbt_export.svg').replace('\\', '/')
        fetch_rules_path = os.path.join(temp_dir, 'qbt_fetch_rules.svg').replace('\\', '/')

        def _open_qt_log_viewer():
            from src.gui_qt.log_viewer_dialog import LogViewerDialog
            log_dialog = LogViewerDialog(parent=dialog)
            log_dialog.exec()
        settings = run_qt_get_connection_settings()
        runtime = run_qt_get_runtime_settings()
        platform_settings = run_qt_get_platform_settings()
        export_targets = set(platform_settings.get('export_targets', []))
        # dialog = QDialog(window)
        dialog.setWindowTitle('Settings - Configuration')
        dialog.setMinimumSize(800, 600)
        dialog.resize(980, 760)
        dialog.setSizeGripEnabled(True)
        dialog_layout = QVBoxLayout(dialog)

        tabs = QTabWidget(dialog)
        dialog_layout.addWidget(tabs, 1)

        tab_connection = QWidget()
        tab_connection_layout = QVBoxLayout(tab_connection)
        mode_group = QGroupBox('Connection Mode')
        mode_layout = QHBoxLayout(mode_group)
        online_radio = QRadioButton('Online - Direct API connection')
        online_radio.setToolTip('Enable direct network communication with the qBittorrent server')
        offline_radio = QRadioButton('Offline - Generate JSON file only')
        offline_radio.setToolTip('Disable server network checks and export rule files only')
        mode_layout.addWidget(online_radio)
        mode_layout.addWidget(offline_radio)
        mode_layout.addStretch()
        online_radio.setChecked(str(settings.get('mode', 'online')) == 'online')
        offline_radio.setChecked(not online_radio.isChecked())
        tab_connection_layout.addWidget(mode_group)



        profile_group = QGroupBox('Unified Connection Profile Editor')
        profile_form = QFormLayout(profile_group)
        protocol_combo = QComboBox()
        protocol_combo.setMaxVisibleItems(20)
        protocol_combo.addItems(['http', 'https'])
        protocol_combo.setCurrentText(str(settings.get('protocol', 'http')))
        protocol_combo.setToolTip('Set the connection protocol (http or https)')
        host_edit = QLineEdit(str(settings.get('host', '')))
        host_edit.setToolTip('Enter the IP address or domain name of your qBittorrent server')
        port_edit = QLineEdit(str(settings.get('port', '8080')))
        port_edit.setToolTip('Enter the web UI port of your qBittorrent server')
        user_edit = QLineEdit(str(settings.get('username', '')))
        user_edit.setToolTip('Enter the username for the qBittorrent Web UI')
        pass_edit = QLineEdit(str(settings.get('password', '')))
        pass_edit.setToolTip('Enter the password for the qBittorrent Web UI')
        ca_cert_edit = QLineEdit(str(settings.get('ca_cert', '') or ''))
        ca_cert_edit.setToolTip('Optional path to custom CA certificate bundle for HTTPS validation')
        ca_cert_row = QWidget()
        ca_cert_layout = QHBoxLayout(ca_cert_row)
        ca_cert_layout.setContentsMargins(0, 0, 0, 0)
        ca_cert_layout.addWidget(ca_cert_edit, 1)
        ca_browse_btn = QPushButton('Browse...')
        ca_browse_btn.setToolTip('Select the CA certificate file from your local disk')

        def _browse_ca_cert() -> None:
            path, _ = QFileDialog.getOpenFileName(dialog, 'Select CA certificate', '', 'PEM/CRT/CER files (*.pem *.crt *.cer);;All files (*.*)')
            if path:
                ca_cert_edit.setText(path)

        ca_browse_btn.clicked.connect(_browse_ca_cert)
        ca_cert_layout.addWidget(ca_browse_btn)
        verify_ssl_box = QCheckBox('Verify SSL Certificate')
        verify_ssl_box.setChecked(bool(settings.get('verify_ssl', True)))
        verify_ssl_box.setToolTip('Enforce SSL certificate verification during HTTPS communication')
        test_conn_btn = QPushButton('Test Connection')
        test_conn_btn.setToolTip('Send a ping request to verify qBittorrent connection settings')
        profile_form.addRow('Protocol:', protocol_combo)
        profile_form.addRow('Host:', host_edit)
        profile_form.addRow('Port:', port_edit)
        profile_form.addRow('Username:', user_edit)
        profile_form.addRow('Password:', pass_edit)
        profile_form.addRow('CA Certificate:', ca_cert_row)
        profile_form.addRow('', verify_ssl_box)
        profile_form.addRow('', test_conn_btn)
        tab_connection_layout.addWidget(profile_group)

        profiles_group = QGroupBox('Saved Connection Profiles')
        profiles_layout = QVBoxLayout(profiles_group)
        profile_name_edit = QLineEdit('')
        profile_name_edit.setToolTip('Name of the connection profile to save or update')
        profiles_layout.addWidget(QLabel('Profile Name:'))
        profiles_layout.addWidget(profile_name_edit)
        profiles_list = QListWidget()
        profiles_list.setSelectionMode(QAbstractItemView.SingleSelection)
        profiles_list.setToolTip('List of saved connection profiles. Select one to load or delete')
        profiles_layout.addWidget(profiles_list)
        profiles_buttons = QHBoxLayout()
        profile_new_btn = QPushButton('New')
        profile_new_btn.setToolTip('Clear the input fields to define a new connection profile')
        profile_save_btn = QPushButton('Save Profile')
        profile_save_btn.setToolTip('Save the current connection settings as a profile under the specified name')
        profile_load_btn = QPushButton('Load Selected')
        profile_load_btn.setToolTip('Load the connection settings from the selected profile')
        profile_delete_btn = QPushButton('Delete Selected')
        profile_delete_btn.setToolTip('Delete the selected connection profile')
        profiles_buttons.addWidget(profile_new_btn)
        profiles_buttons.addWidget(profile_save_btn)
        profiles_buttons.addWidget(profile_load_btn)
        profiles_buttons.addWidget(profile_delete_btn)
        profiles_layout.addLayout(profiles_buttons)

        def _load_profiles_cache() -> list[dict[str, object]]:
            try:
                profiles = config.load_connection_profiles()
            except Exception:
                profiles = []
            if not isinstance(profiles, list):
                return []
            result: list[dict[str, object]] = []
            for profile in profiles:
                if isinstance(profile, dict):
                    result.append(dict(profile))
            return result

        def _refresh_profiles_list() -> None:
            profiles_list.clear()
            for profile in _load_profiles_cache():
                name = str(profile.get('name', '') or '').strip() or 'Unnamed'
                server = str(profile.get('server', 'qbittorrent') or 'qbittorrent').strip().lower()
                profiles_list.addItem(f'{name} - {server}')

        def _new_profile() -> None:
            profile_name_edit.setText('')
            protocol_combo.setCurrentText('http')
            host_edit.setText('localhost')
            port_edit.setText('8080')
            user_edit.setText('')
            pass_edit.setText('')
            ca_cert_edit.setText('')
            verify_ssl_box.setChecked(True)
            if defaults_save_path_edit is not None:
                defaults_save_path_edit.setText('')
            if defaults_download_path_edit is not None:
                defaults_download_path_edit.setText('')
            if defaults_category_combo is not None:
                defaults_category_combo.setCurrentText('')
            elif defaults_category_edit is not None:
                defaults_category_edit.setText('')
            if defaults_feeds_edit is not None:
                defaults_feeds_edit.setText('')

        def _save_profile() -> None:
            profile_name = profile_name_edit.text().strip()
            if not profile_name:
                QMessageBox.warning(dialog, 'Profile Name Required', 'Please enter a profile name before saving.')
                return
            new_profile = {
                'name': profile_name,
                'server': 'qbittorrent',
                'protocol': protocol_combo.currentText().strip().lower() or 'http',
                'host': host_edit.text().strip() or 'localhost',
                'port': port_edit.text().strip() or '8080',
                'username': user_edit.text().strip(),
                'password': pass_edit.text(),
                'verify_ssl': bool(verify_ssl_box.isChecked()),
                'ca_cert': ca_cert_edit.text().strip(),
                'default_save_path': defaults_save_path_edit.text().strip() if defaults_save_path_edit is not None else '',
                'default_download_path': defaults_download_path_edit.text().strip() if defaults_download_path_edit is not None else '',
                'default_category': defaults_category_combo.currentText().strip() if defaults_category_combo is not None else (defaults_category_edit.text().strip() if defaults_category_edit is not None else ''),
                'default_affected_feeds': defaults_feeds_edit.text().strip() if defaults_feeds_edit is not None else '',
            }
            profiles = _load_profiles_cache()
            replaced = False
            for idx, profile in enumerate(profiles):
                if str(profile.get('name', '') or '').strip().lower() == profile_name.lower():
                    profiles[idx] = new_profile
                    replaced = True
                    break
            if not replaced:
                profiles.append(new_profile)
            if config.save_connection_profiles(profiles):
                _refresh_profiles_list()
                QMessageBox.information(dialog, 'Profile Saved', f'Saved profile: {profile_name}')
            else:
                QMessageBox.warning(dialog, 'Profile Save Failed', 'Could not save connection profile.')

        def _load_selected_profile() -> None:
            row = profiles_list.currentRow()
            if row < 0:
                return
            profiles = _load_profiles_cache()
            if row >= len(profiles):
                return
            profile = profiles[row]
            profile_name_edit.setText(str(profile.get('name', '') or ''))
            protocol_combo.setCurrentText(str(profile.get('protocol', 'http') or 'http'))
            host_edit.setText(str(profile.get('host', 'localhost') or 'localhost'))
            port_edit.setText(str(profile.get('port', '8080') or '8080'))
            user_edit.setText(str(profile.get('username', '') or ''))
            pass_edit.setText(str(profile.get('password', '') or ''))
            ca_cert_edit.setText(str(profile.get('ca_cert', '') or ''))
            verify_ssl_box.setChecked(bool(profile.get('verify_ssl', True)))
            if defaults_save_path_edit is not None:
                defaults_save_path_edit.setText(str(profile.get('default_save_path', '') or ''))
            if defaults_download_path_edit is not None:
                defaults_download_path_edit.setText(str(profile.get('default_download_path', '') or ''))
            if defaults_category_combo is not None:
                defaults_category_combo.setCurrentText(str(profile.get('default_category', '') or ''))
            elif defaults_category_edit is not None:
                defaults_category_edit.setText(str(profile.get('default_category', '') or ''))
            if defaults_feeds_edit is not None:
                defaults_feeds_edit.setText(str(profile.get('default_affected_feeds', '') or ''))

        def _delete_selected_profile() -> None:
            row = profiles_list.currentRow()
            if row < 0:
                return
            profiles = _load_profiles_cache()
            if row >= len(profiles):
                return
            profile_name = str(profiles[row].get('name', 'Unnamed') or 'Unnamed')
            if QMessageBox.question(dialog, 'Delete Profile', f"Delete connection profile '{profile_name}'?") != QMessageBox.Yes:
                return
            del profiles[row]
            config.save_connection_profiles(profiles)
            _refresh_profiles_list()

        def _test_connection() -> None:
            protocol = protocol_combo.currentText().strip() or 'http'
            host = host_edit.text().strip()
            port = port_edit.text().strip() or '8080'
            username = user_edit.text().strip()
            password = pass_edit.text()
            verify_ssl = bool(verify_ssl_box.isChecked())
            ca_cert = ca_cert_edit.text().strip() or None
            if not host:
                QMessageBox.warning(dialog, 'Connection Test', 'Host is required for connection test.')
                return
            ok, message = ping_qbittorrent(protocol, host, port, username, password, verify_ssl, ca_cert)
            if ok:
                QMessageBox.information(dialog, 'Connection Test', str(message or 'Connection successful.'))
            else:
                QMessageBox.warning(dialog, 'Connection Test', str(message or 'Connection failed.'))

        profile_new_btn.clicked.connect(_new_profile)
        profile_save_btn.clicked.connect(_save_profile)
        profile_load_btn.clicked.connect(_load_selected_profile)
        profile_delete_btn.clicked.connect(_delete_selected_profile)
        test_conn_btn.clicked.connect(_test_connection)
        _refresh_profiles_list()

        tab_connection_layout.addWidget(profiles_group)
        # Wrap the Connection tab in a scroll area so it works at any window height
        tab_connection_layout.addStretch()
        _conn_scroll = QScrollArea()
        _conn_scroll.setWidgetResizable(True)
        _conn_scroll.setFrameShape(QFrame.NoFrame)
        _conn_scroll.setWidget(tab_connection)
        tabs.addTab(_conn_scroll, 'Connection')

        defaults_save_path_edit = None
        defaults_download_path_edit = None
        defaults_category_edit = None
        defaults_category_combo = None
        categories_tree = None
        defaults_feeds_edit = None
        ask_delete_confirm_box = None
        prefix_imports_box = None
        auto_sanitize_box = None
        pre_import_check_box = None
        auto_import_sanitize_box = None
        show_import_check_box = None
        filesystem_combo = None
        sanitize_replace_all_box = None
        sanitize_global_char_edit = None
        sanitize_char_edits = {}
        sanitize_preview_labels = {}
        theme_combo = None
        time_format_combo = None
        view_mode_combo = None
        font_family_combo = None
        font_size_spin = None
        ui_style_combo = None
        level_combo = None
        anilist_interval_spin = None
        subsplease_interval_spin = None
        save_subsplease_cache_box = None
        retention_mode_combo = None
        cache_ttl_spin = None
        cache_max_mb_spin = None
        refresh_scope_combo = None
        lang_romaji_box = None
        lang_english_box = None
        lang_native_box = None
        lang_synonym_box = None
        lang_synonym_other_box = None
        defaults_tab_index = None
        action_bar_list_widget = None
        available_list_widget = None
        temp_custom_labels = {}
        temp_custom_icons = {}
        action_bar_mode_combo = None
        action_bar_size_combo = None

        display_names = {
            "season_year": "Season & Year Combos",
            "import": "Import Button",
            "fetch_rules": "Fetch Rules Button",
            "apply": "Apply Rules Button",
            "batch": "Batch Downloader Button",
            "refresh": "Refresh API Cache Button",
            "undo": "Undo Button",
            "enabled": "Rule Enabled Checkbox",
            "clear_all": "Clear All Button",
            "validate": "Validate Titles Button",
            "trash": "View Trash Button",
            "export": "Export Button",
            "theme": "Theme Button",
            "settings": "Settings Button",
            "refresh_library": "Refresh Library Button",
            "backup": "Backup Button",
            "templates": "Templates Button",
            "edit_rules": "Edit Rules Button",
            "view_logs": "View Logs Button",
            "api_cache_viewer": "API Cache Viewer Button",
            "setup_wizard": "Setup Wizard Button",
            "shortcuts_help": "Help Shortcuts Button",
            "batch_apply": "Batch Apply Titles Button",
            "import_file": "Import File (Action)",
            "import_clipboard": "Paste Clipboard (Action)",
            "export_selected": "Export Selected (Action)",
            "export_all": "Export All (Action)",
            "backup_create": "Create Backup (Action)",
            "backup_restore": "Restore Backup (Action)",
            "backup_manage": "Manage Backups (Action)",
            "templates_apply": "Apply Template (Action)",
            "templates_save": "Save Template (Action)",
            "templates_manage": "Manage Templates (Action)",
            "edit_rules_toggle": "Toggle Selected Rules (Action)",
            "edit_rules_bulk": "Bulk Edit Rules (Action)",
            "edit_rules_batch_title": "Batch Edit Titles (Action)",
            "edit_rules_batch_apply": "Batch Apply Matches (Action)",
            "refresh_subsplease": "Refresh SubsPlease Cache (Action)",
            "refresh_anilist": "Refresh AniList Cache (Action)"
        }

        for tab_name in ['Defaults', 'Import/Export', 'Sanitization', 'Appearance', 'Action Bar', 'Font && Style', 'Diagnostics', 'API Rate Limits']:
            tab = QWidget()
            # Each tab's content is wrapped in a scroll area so it never clips on small screens
            tab_scroll = QScrollArea()
            tab_scroll.setWidgetResizable(True)
            tab_scroll.setFrameShape(QFrame.NoFrame)
            tab_scroll.setWidget(tab)
            tab_layout = QVBoxLayout(tab)
            section = QGroupBox(tab_name)
            section_layout = QVBoxLayout(section)
            if tab_name == 'Defaults':
                defaults_tab_index = tabs.count()
            if tab_name == 'Defaults':
                defaults_save_path_edit = QLineEdit(str(getattr(config, 'DEFAULT_SAVE_PATH', '') or ''))
                defaults_save_path_edit.setToolTip('Enter the default save path folder for matching torrent files')
                defaults_download_path_edit = QLineEdit(str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or ''))
                defaults_download_path_edit.setToolTip('Reference download path of qBittorrent (fetched from server)')
                defaults_download_path_edit.setReadOnly(True)
                defaults_category_edit = QLineEdit(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                defaults_category_edit.hide()
                defaults_category_combo = QComboBox()
                defaults_category_combo.setMaxVisibleItems(20)
                defaults_category_combo.setEditable(True)
                defaults_category_combo.setCurrentText(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                defaults_category_combo.setToolTip('Select or type the default category to apply to rule items')
                defaults_feeds_edit = QLineEdit(', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or []))
                defaults_feeds_edit.setToolTip('Comma-separated list of RSS feed URLs to associate with rules by default')
                ask_delete_confirm_box = QCheckBox('Ask for confirmation before deleting titles')
                ask_delete_confirm_box.setChecked(bool(config.get_pref('confirm_delete_titles', True)))
                ask_delete_confirm_box.setToolTip('When checked, prompts you for confirmation before deleting rules')
                section_layout.addWidget(QLabel('Default Save Path:'))
                section_layout.addWidget(defaults_save_path_edit)
                section_layout.addWidget(QLabel('qBittorrent Download Path (profile):'))
                section_layout.addWidget(defaults_download_path_edit)
                fetch_download_btn = QPushButton('Fetch Download Path from qBittorrent')
                fetch_download_btn.setToolTip('Query the qBittorrent server to fetch its default download path configuration')

                def _fetch_download_path(silent: bool = False) -> None:
                    try:
                        from src.api.qbittorrent import QBittorrentClient
                        api = QBittorrentClient(
                            protocol=protocol_combo.currentText().strip().lower() or 'http',
                            host=host_edit.text().strip(),
                            port=port_edit.text().strip() or '8080',
                            username=user_edit.text().strip(),
                            password=pass_edit.text(),
                            verify_ssl=bool(verify_ssl_box.isChecked()),
                            ca_cert=ca_cert_edit.text().strip() or None,
                        )
                        if not api.connect():
                            if not silent:
                                QMessageBox.warning(dialog, 'Download Path', 'Could not connect to qBittorrent.')
                            return
                        prefs = api.get_preferences() or {}
                        api.close()
                        save_path = str(prefs.get('save_path', '') or '').strip()
                        if save_path:
                            defaults_download_path_edit.setText(save_path)
                            if not silent:
                                QMessageBox.information(dialog, 'Download Path', f'Fetched: {save_path}')
                        elif not silent:
                            QMessageBox.warning(dialog, 'Download Path', 'No save_path found in qBittorrent preferences.')
                    except Exception as exc:
                        if not silent:
                            QMessageBox.warning(dialog, 'Download Path', f'Failed to fetch download path: {exc}')

                fetch_download_btn.clicked.connect(_fetch_download_path)
                section_layout.addWidget(fetch_download_btn)
                section_layout.addWidget(QLabel('Default Category:'))
                section_layout.addWidget(defaults_category_combo)

                categories_tree = QTreeWidget()
                categories_tree.setHeaderLabels(['Category', 'Save Path'])
                categories_tree.setRootIsDecorated(False)
                categories_tree.setUniformRowHeights(True)
                categories_tree.setMinimumHeight(140)
                categories_tree.setToolTip('Double-click a category to select it as the default category')

                def _category_save_path(category_def: object) -> str:
                    if isinstance(category_def, dict):
                        for key in ('save_path', 'savePath', 'savePath', 'download_path', 'path'):
                            value = str(category_def.get(key, '') or '').strip()
                            if value:
                                return value
                    return ''

                def _load_categories_list() -> None:
                    try:
                        config.load_cached_categories()
                    except Exception:
                        pass
                    categories_tree.clear()
                    current_cat = defaults_category_combo.currentText()
                    defaults_category_combo.clear()
                    cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
                    if isinstance(cats, dict):
                        for category_name in sorted(cats.keys()):
                            item = QTreeWidgetItem([
                                str(category_name),
                                _category_save_path(cats.get(category_name, {})),
                            ])
                            categories_tree.addTopLevelItem(item)
                            defaults_category_combo.addItem(str(category_name))
                    defaults_category_combo.setCurrentText(current_cat)

                def _on_category_pick() -> None:
                    item = categories_tree.currentItem()
                    if not item:
                        return
                    defaults_category_combo.setCurrentText(item.text(0))

                categories_tree.itemSelectionChanged.connect(_on_category_pick)
                refresh_categories_btn = QPushButton('Refresh Cached Categories')
                refresh_categories_btn.setToolTip('Fetch and refresh the list of cached categories from qBittorrent')
            
                def _refresh_categories_action() -> None:
                    try:
                        from src.api.qbittorrent import QBittorrentClient
                        api = QBittorrentClient(
                            protocol=protocol_combo.currentText().strip().lower() or 'http',
                            host=host_edit.text().strip(),
                            port=port_edit.text().strip() or '8080',
                            username=user_edit.text().strip(),
                            password=pass_edit.text(),
                            verify_ssl=bool(verify_ssl_box.isChecked()),
                            ca_cert=ca_cert_edit.text().strip() or None,
                        )
                        if not api.connect():
                            QMessageBox.warning(dialog, 'Refresh Categories', 'Could not connect to qBittorrent.')
                            return
                        categories = api.get_categories() or {}
                        api.close()
                    
                        config.save_cached_categories(categories)
                        _load_categories_list()
                        QMessageBox.information(dialog, 'Refresh Categories', f'Successfully refreshed {len(categories)} categories.')
                    except Exception as exc:
                        QMessageBox.warning(dialog, 'Refresh Categories', f'Failed to refresh categories: {exc}')

                refresh_categories_btn.clicked.connect(_refresh_categories_action)
                section_layout.addWidget(QLabel('Categories & Save Paths:'))
                section_layout.addWidget(categories_tree)
                section_layout.addWidget(refresh_categories_btn)
                _load_categories_list()

                section_layout.addWidget(QLabel('Default Affected Feeds (comma-separated):'))
                section_layout.addWidget(defaults_feeds_edit)
                section_layout.addWidget(ask_delete_confirm_box)
            elif tab_name == 'Import/Export':
                prefix_imports_box = QCheckBox('Enable Season/Year prefix logic')
                prefix_imports_box.setChecked(bool(config.get_pref('prefix_imports', True)))
                prefix_imports_box.setToolTip('Prepend season and year prefix to rules automatically on import')
                auto_sanitize_box = QCheckBox('Automatically sanitize invalid folder names')
                auto_sanitize_box.setChecked(bool(config.get_pref('auto_sanitize_paths', True)))
                auto_sanitize_box.setToolTip('Automatically fix invalid directory characters on importing files')
                pre_import_check_box = QCheckBox('Show pre-import sanitize check')
                pre_import_check_box.setChecked(bool(config.get_pref('pre_import_sanitize_check', True)))
                pre_import_check_box.setToolTip('Display a comparison window showing sanitization changes before applying')
                auto_import_sanitize_box = QCheckBox('Apply automatic sanitization during import')
                auto_import_sanitize_box.setChecked(bool(config.get_pref(PrefKeys.AUTO_SANITIZE, True)))
                auto_import_sanitize_box.setToolTip('Enable automated string sanitation on imported titles')
                show_import_check_box = QCheckBox('Always show sanitize review dialog before import')
                show_import_check_box.setChecked(bool(config.get_pref('show_import_sanitize_check', True)))
                show_import_check_box.setToolTip('Always display the sanitization check preview table before import proceeds')
                section_layout.addWidget(prefix_imports_box)
                section_layout.addWidget(auto_sanitize_box)
                section_layout.addWidget(pre_import_check_box)
                section_layout.addWidget(auto_import_sanitize_box)
                section_layout.addWidget(show_import_check_box)
            elif tab_name == 'Sanitization':
                filesystem_combo = QComboBox()
                filesystem_combo.setMaxVisibleItems(20)
                filesystem_combo.addItems(['linux', 'windows'])
                filesystem_combo.setCurrentText(str(config.get_pref('filesystem_type', 'linux') or 'linux'))
                filesystem_combo.setToolTip('Select target operating system character rules (Windows allows fewer characters than Linux)')
                sanitize_replace_all_box = QCheckBox('Replace all invalid chars with a single replacement character')
                sanitize_replace_all_box.setChecked(bool(config.get_pref(PrefKeys.SANITIZE_REPLACE_ALL, True)))
                sanitize_replace_all_box.setToolTip('Replace all invalid characters with the global replacement character instead of custom mappings')
                sanitize_global_char_edit = QLineEdit(str(config.get_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, '_') or '_')[:1])
                sanitize_global_char_edit.setToolTip('Single character used to replace any invalid characters (defaults to underscore)')
                custom_map = config.get_pref(PrefKeys.SANITIZE_CUSTOM_MAP, {}) or {}
                if not isinstance(custom_map, dict):
                    custom_map = {}
                section_layout.addWidget(QLabel('Target Filesystem Type:'))
                section_layout.addWidget(filesystem_combo)
                section_layout.addWidget(sanitize_replace_all_box)
                section_layout.addWidget(QLabel('Global replacement character:'))
                section_layout.addWidget(sanitize_global_char_edit)
                section_layout.addWidget(QLabel('Custom per-character replacements (space/remove/text):'))

                def _set_preview_text(preview_label, value: str) -> None:
                    token = str(value or '').strip().lower()
                    if token == 'space':
                        preview_label.setText('(space)')
                    elif token == 'remove':
                        preview_label.setText('(remove)')
                    elif str(value or '') == '':
                        preview_label.setText('(empty)')
                    else:
                        preview_label.setText(str(value))

                def _on_sanitize_value_changed(ch: str, value: str) -> None:
                    preview_label = sanitize_preview_labels.get(ch)
                    if preview_label is None:
                        return
                    _set_preview_text(preview_label, value)

                for ch in FileSystem.INVALID_CHARS:
                    raw_val = str(custom_map.get(ch, '') or '')
                    token = raw_val.strip().lower()
                    if token == '__remove__':
                        display_val = 'remove'
                    elif token == '__space__':
                        display_val = 'space'
                    else:
                        display_val = raw_val
                    edit = QLineEdit(display_val)
                    edit.setToolTip(f"Specify a replacement string for the invalid character '{ch}'. Enter 'remove' to delete or 'space' to replace with space")
                    sanitize_char_edits[ch] = edit
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(QLabel(f'{ch} ->'))
                    row_layout.addWidget(edit, 1)
                    preview_label = QLabel('(empty)')
                    sanitize_preview_labels[ch] = preview_label
                    row_layout.addWidget(QLabel('Preview:'))
                    row_layout.addWidget(preview_label)
                    edit.textChanged.connect(lambda text, c=ch: _on_sanitize_value_changed(c, text))
                    _set_preview_text(preview_label, display_val)
                    section_layout.addWidget(row)
            elif tab_name == 'Appearance':
                theme_combo = QComboBox()
                theme_combo.setMaxVisibleItems(20)
                theme_combo.addItems(['light', 'dark', 'auto'])
                theme_combo.setCurrentText(str(runtime.get('theme', 'light')))
                theme_combo.setToolTip('Change the UI theme profile (light, dark, or system auto)')
                time_format_combo = QComboBox()
                time_format_combo.setMaxVisibleItems(20)
                time_format_combo.addItems(['24h', '12h'])
                time_format_combo.setCurrentText(str(config.get_pref('time_format', '24h') or '24h'))
                time_format_combo.setToolTip('Choose between 24-hour and 12-hour timestamp formatting in lists')
                view_mode_combo = QComboBox()
                view_mode_combo.setMaxVisibleItems(20)
                view_mode_combo.addItems(['expanded', 'compact'])
                view_mode_combo.setCurrentText(str(config.get_pref('view_mode', 'expanded') or 'expanded'))
                view_mode_combo.setToolTip('Switch between expanded (spacious spacing) and compact list view layouts')
                section_layout.addWidget(QLabel('Theme:'))
                section_layout.addWidget(theme_combo)
                section_layout.addWidget(QLabel('Time Format:'))
                section_layout.addWidget(time_format_combo)
                section_layout.addWidget(QLabel('View Mode:'))
                section_layout.addWidget(view_mode_combo)
            elif tab_name == 'Action Bar':
                QSizePolicy = getattr(widgets, 'QSizePolicy')
                section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
                section_layout.addWidget(QLabel("Configure the order and visibility of the items on the main action bar.\nMove items between the lists to show or hide them. Use Move Up / Move Down to order active items, or add custom Separators and Spacers."))
            
                # Global Options (moved to top)
                global_group = QGroupBox('Global Action Bar Options')
                global_layout = QHBoxLayout(global_group)
            
                mode_label = QLabel('Adaptability Mode:')
                action_bar_mode_combo = QComboBox()
                action_bar_mode_combo.setMaxVisibleItems(10)
                action_bar_mode_combo.addItems([
                    'Responsive (Icon-only when narrow)',
                    'Scrollable (Horizontal Scrollbar)',
                    'Hybrid (Icons-only when narrow + Scrollable)',
                    'Icons Only (Always)',
                    'Text & Icons (Static)'
                ])
                current_mode = str(config.get_pref('action_bar_mode', 'responsive')).lower()
                if current_mode == 'scrollable':
                    action_bar_mode_combo.setCurrentIndex(1)
                elif current_mode == 'hybrid':
                    action_bar_mode_combo.setCurrentIndex(2)
                elif current_mode == 'icons_only':
                    action_bar_mode_combo.setCurrentIndex(3)
                elif current_mode == 'static':
                    action_bar_mode_combo.setCurrentIndex(4)
                else:
                    action_bar_mode_combo.setCurrentIndex(0)
                
                size_label = QLabel('Button Size:')
                action_bar_size_combo = QComboBox()
                action_bar_size_combo.setMaxVisibleItems(10)
                action_bar_size_combo.addItems(['Compact', 'Standard', 'Large'])
                action_bar_size_combo.setCurrentText(str(config.get_pref('action_bar_button_size', 'standard')).title())
            
                global_layout.addWidget(mode_label)
                global_layout.addWidget(action_bar_mode_combo)
                global_layout.addWidget(size_label)
                global_layout.addWidget(action_bar_size_combo)
                global_layout.addStretch()
            
                reset_btn = QPushButton("Reset to Defaults")
                reset_btn.setToolTip("Reset all Action Bar configuration to system defaults")
                global_layout.addWidget(reset_btn)
                section_layout.addWidget(global_group)

                # Setup dual lists: Active Items (visible) and Available Items (hidden)
                active_group = QGroupBox("Active Items (Shown in Action Bar)")
                active_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                active_layout = QVBoxLayout(active_group)
                action_bar_list_widget = QListWidget()
                action_bar_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                action_bar_list_widget.setMinimumHeight(280)
                active_layout.addWidget(action_bar_list_widget)

                available_group = QGroupBox("Available Items (Hidden)")
                available_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                available_layout = QVBoxLayout(available_group)
                available_list_widget = QListWidget()
                available_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                available_list_widget.setMinimumHeight(280)
                available_list_widget.setSortingEnabled(True)
                available_layout.addWidget(available_list_widget)
            
                # Fetch current order
                default_order = DEFAULT_ACTION_BAR_ORDER.copy()
                order = config.get_pref('action_bar_order', default_order)
                if "separator" in order:
                    order = [name if name != "separator" else "separator_1" for name in order]
            
                # Check for backward compatibility migration from action_bar_visible
                visible = config.get_pref('action_bar_visible', None)
                if visible is not None:
                    order = [name for name in order if visible.get(name, True)]

                temp_custom_labels = config.get_pref('action_bar_custom_labels', {}).copy()
                temp_custom_icons = config.get_pref('action_bar_custom_icons', {})
                if not isinstance(temp_custom_icons, dict):
                    temp_custom_icons = {}
                else:
                    temp_custom_icons = temp_custom_icons.copy()

                temp_dropdown_subactions = config.get_pref('action_bar_dropdown_subactions', {}).copy()
                temp_custom_dropdowns = config.get_pref('action_bar_custom_dropdowns', {}).copy()

                # Helpers to create list items
                def create_active_item(key):
                    friendly_name = ""
                    if key.startswith("separator"):
                        friendly_name = "Separator Line"
                    elif key.startswith("spacer"):
                        friendly_name = "Flexible Spacer"
                    elif key.startswith("custom_dropdown_"):
                        conf = temp_custom_dropdowns.get(key, {})
                        label = conf.get("label", "Custom Dropdown")
                        friendly_name = f"Dropdown: {label}"
                    elif key in display_names:
                        friendly_name = display_names[key]
                        custom_txt = temp_custom_labels.get(key, "")
                        if custom_txt:
                            friendly_name = f"{friendly_name} ({custom_txt})"
                    else:
                        return None
                    
                    item = QListWidgetItem(friendly_name)
                    item.setData(core.Qt.UserRole, key)
                    item.setFlags(item.flags() | core.Qt.ItemIsEnabled | core.Qt.ItemIsSelectable)
                    item.setFlags(item.flags() & ~core.Qt.ItemIsUserCheckable)
                
                    icon_name = temp_custom_icons.get(key, "")
                    if not icon_name:
                        if key == "settings":
                            item.setIcon(QIcon(settings_path))
                        elif key == "theme":
                            current = str(config.get_pref('theme', 'light')).lower()
                            path = theme_dark_path if current == 'dark' else (theme_auto_path if current == 'auto' else theme_light_path)
                            item.setIcon(QIcon(path))
                        elif key == "undo":
                            item.setIcon(QIcon(undo_path))
                        elif key == "export":
                            item.setIcon(QIcon(export_path))
                        elif key == "fetch_rules":
                            item.setIcon(QIcon(fetch_rules_path))
                        else:
                            meta = DEFAULT_BUTTON_METADATA.get(key, {})
                            icon_name = meta.get("icon", "")
                            if icon_name:
                                try:
                                    std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                                    item.setIcon(std_icon)
                                except Exception:
                                    pass
                    else:
                        try:
                            std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                            item.setIcon(std_icon)
                        except Exception:
                            pass
                    return item

                def create_available_item(key):
                    if key not in display_names:
                        return None
                    friendly_name = display_names[key]
                    item = QListWidgetItem(friendly_name)
                    item.setData(core.Qt.UserRole, key)
                    item.setFlags(item.flags() | core.Qt.ItemIsEnabled | core.Qt.ItemIsSelectable)
                    item.setFlags(item.flags() & ~core.Qt.ItemIsUserCheckable)
                
                    if key == "settings":
                        item.setIcon(QIcon(settings_path))
                    elif key == "theme":
                        current = str(config.get_pref('theme', 'light')).lower()
                        path = theme_dark_path if current == 'dark' else (theme_auto_path if current == 'auto' else theme_light_path)
                        item.setIcon(QIcon(path))
                    elif key == "undo":
                        item.setIcon(QIcon(undo_path))
                    elif key == "export":
                        item.setIcon(QIcon(export_path))
                    elif key == "fetch_rules":
                        item.setIcon(QIcon(fetch_rules_path))
                    else:
                        meta = DEFAULT_BUTTON_METADATA.get(key, {})
                        icon_name = meta.get("icon", "")
                        if icon_name:
                            try:
                                std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                                item.setIcon(std_icon)
                            except Exception:
                                pass
                    return item

                # Populate lists
                active_keys = set()
                for name in order:
                    item = create_active_item(name)
                    if item:
                        action_bar_list_widget.addItem(item)
                        active_keys.add(name)

                for name in display_names:
                    if name not in active_keys:
                        item = create_available_item(name)
                        if item:
                            available_list_widget.addItem(item)

                # Buttons for Active list - Row 1: Order
                active_btn_layout_1 = QHBoxLayout()
                move_to_top_btn = QPushButton("Move to Top")
                move_up_btn = QPushButton("Move Up")
                move_down_btn = QPushButton("Move Down")
                move_to_bottom_btn = QPushButton("Move to Bottom")
            
                active_btn_layout_1.addWidget(move_to_top_btn)
                active_btn_layout_1.addWidget(move_up_btn)
                active_btn_layout_1.addWidget(move_down_btn)
                active_btn_layout_1.addWidget(move_to_bottom_btn)
                active_btn_layout_1.addStretch()

                # Buttons for Active list - Row 2: Edit
                active_btn_layout_2 = QHBoxLayout()
                remove_btn = QPushButton("Remove")
                remove_btn.setEnabled(False)
                add_sep_btn = QPushButton("Add Separator")
                add_spacer_btn = QPushButton("Add Spacer")
                add_dropdown_btn = QPushButton("Add Dropdown")
            
                active_btn_layout_2.addWidget(remove_btn)
                active_btn_layout_2.addWidget(add_sep_btn)
                active_btn_layout_2.addWidget(add_spacer_btn)
                active_btn_layout_2.addWidget(add_dropdown_btn)
                active_btn_layout_2.addStretch()
            
                active_layout.addLayout(active_btn_layout_1)
                active_layout.addLayout(active_btn_layout_2)

                # Buttons for Available list
                available_btn_layout = QHBoxLayout()
                add_btn = QPushButton("Add to Active")
                add_btn.setEnabled(False)
            
                available_btn_layout.addWidget(add_btn)
                available_btn_layout.addStretch()
                available_layout.addLayout(available_btn_layout)

                # Button actions
                def _move_item_to_top():
                    items_to_move = action_bar_list_widget.selectedItems()
                    if not items_to_move:
                        return
                    items_to_move.sort(key=lambda x: action_bar_list_widget.row(x))
                    selected_keys = [item.data(core.Qt.UserRole) for item in items_to_move]
                    for idx, item in enumerate(items_to_move):
                        r = action_bar_list_widget.row(item)
                        taken = action_bar_list_widget.takeItem(r)
                        action_bar_list_widget.insertItem(idx, taken)
                    action_bar_list_widget.clearSelection()
                    for i in range(action_bar_list_widget.count()):
                        it = action_bar_list_widget.item(i)
                        if it.data(core.Qt.UserRole) in selected_keys:
                            it.setSelected(True)

                def _move_item_up():
                    items_to_move = action_bar_list_widget.selectedItems()
                    if not items_to_move:
                        return
                    items_to_move.sort(key=lambda x: action_bar_list_widget.row(x))
                
                    selected_keys = [item.data(core.Qt.UserRole) for item in items_to_move]
                
                    for item in items_to_move:
                        r = action_bar_list_widget.row(item)
                        if r > 0:
                            taken = action_bar_list_widget.takeItem(r)
                            action_bar_list_widget.insertItem(r - 1, taken)
                        
                    action_bar_list_widget.clearSelection()
                    for i in range(action_bar_list_widget.count()):
                        it = action_bar_list_widget.item(i)
                        if it.data(core.Qt.UserRole) in selected_keys:
                            it.setSelected(True)
                    
                def _move_item_down():
                    items_to_move = action_bar_list_widget.selectedItems()
                    if not items_to_move:
                        return
                    items_to_move.sort(key=lambda x: action_bar_list_widget.row(x), reverse=True)
                
                    selected_keys = [item.data(core.Qt.UserRole) for item in items_to_move]
                
                    for item in items_to_move:
                        r = action_bar_list_widget.row(item)
                        if r < action_bar_list_widget.count() - 1:
                            taken = action_bar_list_widget.takeItem(r)
                            action_bar_list_widget.insertItem(r + 1, taken)
                        
                    action_bar_list_widget.clearSelection()
                    for i in range(action_bar_list_widget.count()):
                        it = action_bar_list_widget.item(i)
                        if it.data(core.Qt.UserRole) in selected_keys:
                            it.setSelected(True)

                def _move_item_to_bottom():
                    items_to_move = action_bar_list_widget.selectedItems()
                    if not items_to_move:
                        return
                    items_to_move.sort(key=lambda x: action_bar_list_widget.row(x))
                    selected_keys = [item.data(core.Qt.UserRole) for item in items_to_move]
                    for item in items_to_move:
                        r = action_bar_list_widget.row(item)
                        taken = action_bar_list_widget.takeItem(r)
                        action_bar_list_widget.addItem(taken)
                    action_bar_list_widget.clearSelection()
                    for i in range(action_bar_list_widget.count()):
                        it = action_bar_list_widget.item(i)
                        if it.data(core.Qt.UserRole) in selected_keys:
                            it.setSelected(True)

                def _add_separator():
                    existing = [action_bar_list_widget.item(i).data(core.Qt.UserRole) for i in range(action_bar_list_widget.count())]
                    idx = 1
                    while f"separator_{idx}" in existing:
                        idx += 1
                    key = f"separator_{idx}"
                
                    item = create_active_item(key)
                    r = action_bar_list_widget.currentRow()
                    if r >= 0:
                        action_bar_list_widget.insertItem(r, item)
                    else:
                        action_bar_list_widget.addItem(item)
                    action_bar_list_widget.setCurrentItem(item)

                def _add_spacer():
                    existing = [action_bar_list_widget.item(i).data(core.Qt.UserRole) for i in range(action_bar_list_widget.count())]
                    idx = 1
                    while f"spacer_{idx}" in existing:
                        idx += 1
                    key = f"spacer_{idx}"
                
                    item = create_active_item(key)
                    r = action_bar_list_widget.currentRow()
                    if r >= 0:
                        action_bar_list_widget.insertItem(r, item)
                    else:
                        action_bar_list_widget.addItem(item)
                    action_bar_list_widget.setCurrentItem(item)

                def _add_custom_dropdown():
                    name, ok = QInputDialog.getText(dialog, "Create Dropdown", "Enter label for custom dropdown:")
                    if not ok or not name.strip():
                        return
                    existing = [action_bar_list_widget.item(i).data(core.Qt.UserRole) for i in range(action_bar_list_widget.count())]
                    idx = 1
                    while f"custom_dropdown_{idx}" in existing:
                        idx += 1
                    key = f"custom_dropdown_{idx}"
                
                    temp_custom_dropdowns[key] = {
                        "label": name.strip(),
                        "icon": "SP_TitleBarMenuButton",
                        "children": []
                    }
                
                    item = create_active_item(key)
                    r = action_bar_list_widget.currentRow()
                    if r >= 0:
                        action_bar_list_widget.insertItem(r, item)
                    else:
                        action_bar_list_widget.addItem(item)
                    action_bar_list_widget.setCurrentItem(item)

                def _remove_selected_item():
                    selected_items = action_bar_list_widget.selectedItems()
                    if not selected_items:
                        return
                    selected_items.sort(key=lambda x: action_bar_list_widget.row(x), reverse=True)
                
                    added_to_avail = []
                    for item in selected_items:
                        row = action_bar_list_widget.row(item)
                        taken = action_bar_list_widget.takeItem(row)
                        key = str(taken.data(core.Qt.UserRole) or '')
                    
                        if key.startswith("custom_dropdown_"):
                            temp_custom_dropdowns.pop(key, None)
                        
                        if not (key.startswith("separator") or key.startswith("spacer") or key.startswith("custom_dropdown_")):
                            avail_item = create_available_item(key)
                            if avail_item:
                                available_list_widget.addItem(avail_item)
                                added_to_avail.append(avail_item)
                            
                    available_list_widget.clearSelection()
                    for item in added_to_avail:
                        item.setSelected(True)
                    if added_to_avail:
                        available_list_widget.setCurrentItem(added_to_avail[-1])

                def _add_selected_item():
                    selected_items = available_list_widget.selectedItems()
                    if not selected_items:
                        return
                    selected_items.sort(key=lambda x: available_list_widget.row(x), reverse=True)
                
                    active_r = action_bar_list_widget.currentRow()
                    added_items = []
                
                    for item in selected_items:
                        row = available_list_widget.row(item)
                        taken = available_list_widget.takeItem(row)
                        key = taken.data(core.Qt.UserRole)
                    
                        active_item = create_active_item(key)
                        if active_item:
                            if active_r >= 0:
                                action_bar_list_widget.insertItem(active_r, active_item)
                                active_r += 1
                            else:
                                action_bar_list_widget.addItem(active_item)
                            added_items.append(active_item)
                        
                    action_bar_list_widget.clearSelection()
                    for item in added_items:
                        item.setSelected(True)
                    if added_items:
                        action_bar_list_widget.setCurrentItem(added_items[-1])

                # Properties Panel (Below side-by-side lists)
                properties_group = QGroupBox('Item Properties')
                properties_outer_layout = QVBoxLayout(properties_group)
            
                properties_form = QFormLayout()
                label_label = QLabel('Custom Label:')
                properties_label_edit = QLineEdit()
                properties_label_edit.setToolTip('Set a custom label text for the selected button')
            
                icon_label = QLabel('Custom Icon:')
                properties_icon_combo = QComboBox()
                properties_icon_combo.setMaxVisibleItems(15)
                properties_icon_combo.setToolTip('Choose a custom icon for the selected button')
            
                properties_form.addRow(label_label, properties_label_edit)
                properties_form.addRow(icon_label, properties_icon_combo)
                properties_outer_layout.addLayout(properties_form)
            
                properties_icon_combo.addItem('Default Icon', '')
                all_icon_keys = list(STANDARD_ICONS.keys())
                for key, meta in DEFAULT_BUTTON_METADATA.items():
                    ico = meta.get("icon", "")
                    if ico and ico.startswith("SP_") and ico not in all_icon_keys:
                        all_icon_keys.append(ico)
                    
                for icon_name in sorted(all_icon_keys):
                    friendly_name = STANDARD_ICONS.get(icon_name, icon_name.replace("SP_", "").replace("Icon", "").replace("Button", "").replace("Dialog", "").replace("MessageBox", ""))
                    try:
                        std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                        properties_icon_combo.addItem(std_icon, friendly_name, icon_name)
                    except Exception:
                        properties_icon_combo.addItem(friendly_name, icon_name)
                    
                preview_layout = QHBoxLayout()
                preview_title_lbl = QLabel('Live Preview:')
                preview_btn = QPushButton()
                preview_btn.setFixedHeight(30)
                preview_btn.setMinimumWidth(140)
                preview_btn.setStyleSheet("padding: 4px 10px; font-size: 12px; font-weight: bold;")
                preview_layout.addWidget(preview_title_lbl)
                preview_layout.addWidget(preview_btn)
                preview_layout.addStretch()
                properties_outer_layout.addLayout(preview_layout)

                # Sub-actions / Children Configuration Container
                subactions_group = QGroupBox("Configuration Options")
                subactions_layout = QVBoxLayout(subactions_group)
                subactions_scroll = QScrollArea()
                subactions_scroll.setWidgetResizable(True)
                subactions_scroll.setMinimumHeight(150)
                subactions_scroll_widget = QWidget()
                subactions_scroll_layout = QVBoxLayout(subactions_scroll_widget)
                subactions_scroll_layout.setContentsMargins(0, 0, 0, 0)
                subactions_scroll_layout.setSpacing(4)
                subactions_scroll.setWidget(subactions_scroll_widget)
                subactions_layout.addWidget(subactions_scroll)
                properties_outer_layout.addWidget(subactions_group)
                subactions_group.hide()

                def _update_properties_checkboxes(key):
                    # Clear subactions scroll layout
                    while subactions_scroll_layout.count() > 0:
                        item = subactions_scroll_layout.takeAt(0)
                        w = item.widget()
                        if w is not None:
                            w.deleteLater()
                
                    if not key:
                        subactions_group.hide()
                        return

                    if key in DEFAULT_DROPDOWN_SUBACTIONS:
                        subactions_group.show()
                        subactions_group.setTitle("Select Enabled Sub-actions")
                    
                        sub_keys = DEFAULT_DROPDOWN_SUBACTIONS[key]
                        enabled_subs = temp_dropdown_subactions.get(key, DEFAULT_DROPDOWN_SUBACTIONS[key].copy())
                        if not isinstance(enabled_subs, list):
                            enabled_subs = list(enabled_subs)
                    
                        for sub_key in sub_keys:
                            meta = SUBACTION_METADATA.get(sub_key, {})
                            label = meta.get("label", sub_key)
                            tooltip = meta.get("tooltip", "")
                        
                            cb = QCheckBox(label)
                            cb.setToolTip(tooltip)
                            cb.setChecked(sub_key in enabled_subs)
                        
                            def _make_toggle_sub(sk=sub_key, k=key):
                                def _toggle_sub(state):
                                    if k not in temp_dropdown_subactions:
                                        temp_dropdown_subactions[k] = DEFAULT_DROPDOWN_SUBACTIONS[k].copy()
                                    current_list = temp_dropdown_subactions[k]
                                    if state:
                                        if sk not in current_list:
                                            idx_map = {name: i for i, name in enumerate(DEFAULT_DROPDOWN_SUBACTIONS[k])}
                                            current_list.append(sk)
                                            current_list.sort(key=lambda x: idx_map.get(x, 99))
                                    else:
                                        if sk in current_list:
                                            current_list.remove(sk)
                                    _update_properties_preview()
                                return _toggle_sub
                            
                            cb.stateChanged.connect(_make_toggle_sub())
                            subactions_scroll_layout.addWidget(cb)
                    
                        subactions_scroll_layout.addStretch()
                    
                    elif key.startswith("custom_dropdown_"):
                        subactions_group.show()
                        subactions_group.setTitle("Select Dropdown Children")
                    
                        conf = temp_custom_dropdowns.get(key, {})
                        children = conf.get("children", [])
                    
                        for btn_key in sorted(display_names.keys()):
                            if btn_key.startswith("custom_dropdown_") or btn_key.startswith("separator") or btn_key.startswith("spacer"):
                                continue
                        
                            friendly = display_names.get(btn_key, btn_key)
                            cb = QCheckBox(friendly)
                            cb.setChecked(btn_key in children)
                        
                            def _make_toggle_child(bk=btn_key, k=key):
                                def _toggle_child(state):
                                    if k not in temp_custom_dropdowns:
                                        temp_custom_dropdowns[k] = {"label": "Custom Dropdown", "icon": "SP_TitleBarMenuButton", "children": []}
                                    curr_children = temp_custom_dropdowns[k].get("children", [])
                                    if state:
                                        if bk not in curr_children:
                                            curr_children.append(bk)
                                    else:
                                        if bk in curr_children:
                                            curr_children.remove(bk)
                                    temp_custom_dropdowns[k]["children"] = curr_children
                                    _update_properties_preview()
                                return _toggle_child
                            
                            cb.stateChanged.connect(_make_toggle_child())
                            subactions_scroll_layout.addWidget(cb)
                    
                        subactions_scroll_layout.addStretch()
                    
                    else:
                        subactions_group.hide()

                def _update_properties_preview():
                    r = action_bar_list_widget.currentRow()
                    if r < 0:
                        preview_btn.setText("")
                        preview_btn.setIcon(QIcon())
                        preview_btn.setVisible(False)
                        preview_title_lbl.setVisible(False)
                        return
                    
                    item = action_bar_list_widget.item(r)
                    key = item.data(core.Qt.UserRole)
                    if key.startswith("separator") or key.startswith("spacer"):
                        preview_btn.setText("")
                        preview_btn.setIcon(QIcon())
                        preview_btn.setVisible(False)
                        preview_title_lbl.setVisible(False)
                        return
                    
                    preview_btn.setVisible(True)
                    preview_title_lbl.setVisible(True)
                
                    if key.startswith("custom_dropdown_"):
                        conf = temp_custom_dropdowns.get(key, {})
                        display_lbl = conf.get("label", "Custom Dropdown")
                    else:
                        custom_lbl = temp_custom_labels.get(key, "").strip()
                        display_lbl = custom_lbl if custom_lbl else DEFAULT_BUTTON_METADATA.get(key, {}).get("label", key)
                    preview_btn.setText(display_lbl)
                
                    if key.startswith("custom_dropdown_"):
                        icon_name = temp_custom_dropdowns.get(key, {}).get("icon", "SP_TitleBarMenuButton")
                    else:
                        icon_name = temp_custom_icons.get(key, "")
                    if not icon_name:
                        if key == "settings":
                            preview_btn.setIcon(QIcon(settings_path))
                        elif key == "theme":
                            current = str(config.get_pref('theme', 'light')).lower()
                            path = theme_dark_path if current == 'dark' else (theme_auto_path if current == 'auto' else theme_light_path)
                            preview_btn.setIcon(QIcon(path))
                        elif key == "undo":
                            preview_btn.setIcon(QIcon(undo_path))
                        elif key == "export":
                            preview_btn.setIcon(QIcon(export_path))
                        elif key == "fetch_rules":
                            preview_btn.setIcon(QIcon(fetch_rules_path))
                        else:
                            icon_name = DEFAULT_BUTTON_METADATA.get(key, {}).get("icon", "")
                            if icon_name:
                                try:
                                    std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                                    preview_btn.setIcon(std_icon)
                                except Exception:
                                    preview_btn.setIcon(QIcon())
                            else:
                                preview_btn.setIcon(QIcon())
                    else:
                        try:
                            std_icon = window.style().standardIcon(getattr(QStyle, icon_name))
                            preview_btn.setIcon(std_icon)
                        except Exception:
                            preview_btn.setIcon(QIcon())

                def _on_label_edited(text):
                    r = action_bar_list_widget.currentRow()
                    if r < 0:
                        return
                    item = action_bar_list_widget.item(r)
                    key = item.data(core.Qt.UserRole)
                    if not key.startswith("separator") and not key.startswith("spacer"):
                        if key.startswith("custom_dropdown_"):
                            if key not in temp_custom_dropdowns:
                                temp_custom_dropdowns[key] = {"label": "Custom Dropdown", "icon": "SP_TitleBarMenuButton", "children": []}
                            temp_custom_dropdowns[key]["label"] = text.strip() or "Custom Dropdown"
                            item.setText(f"Dropdown: {temp_custom_dropdowns[key]['label']}")
                        else:
                            temp_custom_labels[key] = text.strip()
                            base_name = display_names.get(key, key)
                            if text.strip():
                                item.setText(f"{base_name} ({text.strip()})")
                            else:
                                item.setText(base_name)
                        _update_properties_preview()

                def _on_icon_selected(index):
                    r = action_bar_list_widget.currentRow()
                    if r < 0:
                        return
                    item = action_bar_list_widget.item(r)
                    key = item.data(core.Qt.UserRole)
                    if not key.startswith("separator") and not key.startswith("spacer"):
                        icon_name = properties_icon_combo.itemData(index)
                        if key.startswith("custom_dropdown_"):
                            if key not in temp_custom_dropdowns:
                                temp_custom_dropdowns[key] = {"label": "Custom Dropdown", "icon": "SP_TitleBarMenuButton", "children": []}
                            temp_custom_dropdowns[key]["icon"] = icon_name or "SP_TitleBarMenuButton"
                            try:
                                std_icon = window.style().standardIcon(getattr(QStyle, temp_custom_dropdowns[key]["icon"]))
                                item.setIcon(std_icon)
                            except Exception:
                                pass
                        else:
                            if icon_name:
                                temp_custom_icons[key] = icon_name
                                try:
                                    item.setIcon(properties_icon_combo.itemIcon(index))
                                except Exception:
                                    pass
                            else:
                                if key in temp_custom_icons:
                                    del temp_custom_icons[key]
                                if key == "settings":
                                    item.setIcon(QIcon(settings_path))
                                elif key == "theme":
                                    current = str(config.get_pref('theme', 'light')).lower()
                                    path = theme_dark_path if current == 'dark' else (theme_auto_path if current == 'auto' else theme_light_path)
                                    item.setIcon(QIcon(path))
                                elif key == "undo":
                                    item.setIcon(QIcon(undo_path))
                                elif key == "export":
                                    item.setIcon(QIcon(export_path))
                                elif key == "fetch_rules":
                                    item.setIcon(QIcon(fetch_rules_path))
                                else:
                                    meta = DEFAULT_BUTTON_METADATA.get(key, {})
                                    def_icon_key = meta.get("icon", "")
                                    if def_icon_key:
                                        try:
                                            std_icon = window.style().standardIcon(getattr(QStyle, def_icon_key))
                                            item.setIcon(std_icon)
                                        except Exception:
                                            item.setIcon(QIcon())
                                    else:
                                        item.setIcon(QIcon())
                        _update_properties_preview()

                properties_label_edit.textEdited.connect(_on_label_edited)
                properties_icon_combo.currentIndexChanged.connect(_on_icon_selected)

                _updating_selection = False

                def _on_active_selection_changed():
                    nonlocal _updating_selection
                    if _updating_selection:
                        return
                    _updating_selection = True
                    available_list_widget.clearSelection()
                    _updating_selection = False

                    selected_items = action_bar_list_widget.selectedItems()
                    if not selected_items:
                        move_up_btn.setEnabled(False)
                        move_down_btn.setEnabled(False)
                        move_to_top_btn.setEnabled(False)
                        move_to_bottom_btn.setEnabled(False)
                        remove_btn.setEnabled(False)
                        properties_group.setEnabled(False)
                        properties_group.setTitle('Item Properties (Select a button to customize)')
                        properties_label_edit.clear()
                        properties_icon_combo.setCurrentIndex(0)
                        _update_properties_checkboxes(None)
                        _update_properties_preview()
                        return
                    
                    rows = [action_bar_list_widget.row(item) for item in selected_items]
                    is_not_empty = len(rows) > 0
                    has_room_above = any(r > 0 for r in rows)
                    has_room_below = any(r < action_bar_list_widget.count() - 1 for r in rows)
                
                    move_up_btn.setEnabled(is_not_empty and has_room_above)
                    move_down_btn.setEnabled(is_not_empty and has_room_below)
                    move_to_top_btn.setEnabled(is_not_empty and has_room_above)
                    move_to_bottom_btn.setEnabled(is_not_empty and has_room_below)
                    remove_btn.setEnabled(True)
                
                    if len(selected_items) == 1:
                        item = selected_items[0]
                        key = str(item.data(core.Qt.UserRole) or '')
                        properties_label_edit.blockSignals(True)
                        properties_icon_combo.blockSignals(True)
                        try:
                            if key.startswith("separator") or key.startswith("spacer"):
                                properties_group.setEnabled(False)
                                properties_group.setTitle('Item Properties (Separators/Spacers Not Customizable)')
                                properties_label_edit.clear()
                                properties_icon_combo.setCurrentIndex(0)
                                _update_properties_checkboxes(None)
                            else:
                                properties_group.setEnabled(True)
                                if key.startswith("custom_dropdown_"):
                                    properties_group.setTitle(f'Customize: {temp_custom_dropdowns.get(key, {}).get("label", "Custom Dropdown")}')
                                    properties_label_edit.setPlaceholderText("Default: Custom Dropdown")
                                    properties_label_edit.setText(temp_custom_dropdowns.get(key, {}).get("label", ""))
                                else:
                                    base_name = display_names.get(key, key)
                                    properties_group.setTitle(f'Customize: {base_name}')
                                    default_lbl = DEFAULT_BUTTON_METADATA.get(key, {}).get("label", key)
                                    properties_label_edit.setPlaceholderText(f"Default: {default_lbl}")
                                    properties_label_edit.setText(temp_custom_labels.get(key, ""))
                            
                                # Update Default Icon combo item with current default icon details
                                if key.startswith("custom_dropdown_"):
                                    properties_icon_combo.setItemText(0, "Default (Menu Button)")
                                    try:
                                        std_icon = window.style().standardIcon(QStyle.SP_TitleBarMenuButton)
                                        properties_icon_combo.setItemIcon(0, std_icon)
                                    except Exception:
                                        properties_icon_combo.setItemIcon(0, QIcon())
                                    current_icon_name = temp_custom_dropdowns.get(key, {}).get("icon", "SP_TitleBarMenuButton")
                                else:
                                    meta = DEFAULT_BUTTON_METADATA.get(key, {})
                                    def_icon_key = meta.get("icon", "")
                                    if key == "settings":
                                        properties_icon_combo.setItemText(0, "Default (Gear SVG)")
                                        properties_icon_combo.setItemIcon(0, QIcon(settings_path))
                                    elif key == "theme":
                                        current = str(config.get_pref('theme', 'light')).lower()
                                        path = theme_dark_path if current == 'dark' else (theme_auto_path if current == 'auto' else theme_light_path)
                                        properties_icon_combo.setItemText(0, f"Default ({current.title()} SVG)")
                                        properties_icon_combo.setItemIcon(0, QIcon(path))
                                    elif key == "undo":
                                        properties_icon_combo.setItemText(0, "Default (Undo SVG)")
                                        properties_icon_combo.setItemIcon(0, QIcon(undo_path))
                                    elif key == "export":
                                        properties_icon_combo.setItemText(0, "Default (Export SVG)")
                                        properties_icon_combo.setItemIcon(0, QIcon(export_path))
                                    elif key == "fetch_rules":
                                        properties_icon_combo.setItemText(0, "Default (Fetch Rules SVG)")
                                        properties_icon_combo.setItemIcon(0, QIcon(fetch_rules_path))
                                    elif def_icon_key:
                                        def_friendly = STANDARD_ICONS.get(def_icon_key, def_icon_key.replace("SP_", "").replace("Icon", "").replace("Button", ""))
                                        properties_icon_combo.setItemText(0, f"Default ({def_friendly})")
                                        try:
                                            std_icon = window.style().standardIcon(getattr(QStyle, def_icon_key))
                                            properties_icon_combo.setItemIcon(0, std_icon)
                                        except Exception:
                                            properties_icon_combo.setItemIcon(0, QIcon())
                                    else:
                                        properties_icon_combo.setItemText(0, "Default (None)")
                                        properties_icon_combo.setItemIcon(0, QIcon())
                                    current_icon_name = temp_custom_icons.get(key, "")
                                
                                found = False
                                for idx in range(properties_icon_combo.count()):
                                    if properties_icon_combo.itemData(idx) == current_icon_name:
                                        properties_icon_combo.setCurrentIndex(idx)
                                        found = True
                                        break
                                if not found:
                                    properties_icon_combo.setCurrentIndex(0)
                                _update_properties_checkboxes(key)
                        finally:
                            properties_label_edit.blockSignals(False)
                            properties_icon_combo.blockSignals(False)
                    else:
                        properties_group.setEnabled(False)
                        properties_group.setTitle('Item Properties (Multiple Items Selected)')
                        properties_label_edit.clear()
                        properties_icon_combo.setCurrentIndex(0)
                        _update_properties_checkboxes(None)
                    _update_properties_preview()

                def _on_available_selection_changed():
                    nonlocal _updating_selection
                    if _updating_selection:
                        return
                    _updating_selection = True
                    action_bar_list_widget.clearSelection()
                    _updating_selection = False

                    selected_items = available_list_widget.selectedItems()
                    add_btn.setEnabled(len(selected_items) > 0)
                    properties_group.setEnabled(False)
                    properties_group.setTitle('Item Properties (Select a button to customize)')
                    properties_label_edit.clear()
                    properties_icon_combo.setCurrentIndex(0)
                    move_up_btn.setEnabled(False)
                    move_down_btn.setEnabled(False)
                    move_to_top_btn.setEnabled(False)
                    move_to_bottom_btn.setEnabled(False)
                    remove_btn.setEnabled(False)
                    _update_properties_checkboxes(None)
                    _update_properties_preview()

                def _reset_action_bar_settings():
                    if QMessageBox.question(dialog, "Reset Action Bar", "Are you sure you want to reset all Action Bar settings (order, visibility, custom labels, custom icons, and global options) to default?") != QMessageBox.Yes:
                        return
                
                    action_bar_list_widget.clear()
                    available_list_widget.clear()
                    temp_custom_labels.clear()
                    temp_custom_icons.clear()
                    temp_dropdown_subactions.clear()
                    temp_custom_dropdowns.clear()
                
                    active_keys = set()
                    for name in DEFAULT_ACTION_BAR_ORDER:
                        item = create_active_item(name)
                        if item:
                            action_bar_list_widget.addItem(item)
                            active_keys.add(name)
                            
                    for name in display_names:
                        if name not in active_keys:
                            item = create_available_item(name)
                            if item:
                                available_list_widget.addItem(item)
                            
                    action_bar_mode_combo.setCurrentIndex(0) # Responsive
                    action_bar_size_combo.setCurrentText('Standard')
                
                    properties_label_edit.clear()
                    properties_icon_combo.setCurrentIndex(0)
                    properties_group.setEnabled(False)
                    properties_group.setTitle('Item Properties (Select a button to customize)')
                    _update_properties_checkboxes(None)
                    _update_properties_preview()

                action_bar_list_widget.itemSelectionChanged.connect(_on_active_selection_changed)
                available_list_widget.itemSelectionChanged.connect(_on_available_selection_changed)
                move_to_top_btn.clicked.connect(_move_item_to_top)
                move_up_btn.clicked.connect(_move_item_up)
                move_down_btn.clicked.connect(_move_item_down)
                move_to_bottom_btn.clicked.connect(_move_item_to_bottom)
                add_sep_btn.clicked.connect(_add_separator)
                add_spacer_btn.clicked.connect(_add_spacer)
                add_dropdown_btn.clicked.connect(_add_custom_dropdown)
                remove_btn.clicked.connect(_remove_selected_item)
                add_btn.clicked.connect(_add_selected_item)


                action_bar_list_widget.itemDoubleClicked.connect(lambda item: _remove_selected_item())
                available_list_widget.itemDoubleClicked.connect(lambda item: _add_selected_item())

                lists_layout = QHBoxLayout()
                lists_layout.addWidget(active_group, 1)
                lists_layout.addWidget(available_group, 1)
                section_layout.addLayout(lists_layout, 1)
                section_layout.addWidget(properties_group)

                # Connect the reset button click signal (which was declared at the top)
                reset_btn.clicked.connect(_reset_action_bar_settings)
            elif tab_name == 'Font && Style':
                font_size_spin = QSpinBox()
                font_size_spin.setRange(8, 14)
                font_size_spin.setValue(int(config.get_pref('font_size', 10) or 10))
                font_size_spin.setToolTip('Adjust the font size of the application text')
                QFont = getattr(gui, 'QFont')
                QFontComboBox = getattr(widgets, 'QFontComboBox')
                font_family_combo = QFontComboBox()
                font_family_combo.setMaxVisibleItems(20)
                font_family_name = str(config.get_pref('font_family', 'Segoe UI') or 'Segoe UI')
                font_family_combo.setCurrentFont(QFont(font_family_name))
                font_family_combo.setToolTip('Choose the font family to apply across the application GUI')
                ui_style_combo = QComboBox()
                ui_style_combo.setMaxVisibleItems(20)
                ui_style_combo.addItems(['clam', 'vista', 'default'])
                ui_style_combo.setCurrentText(str(runtime.get('ui_style_theme', 'clam')))
                ui_style_combo.setToolTip('Change the visual widget style theme applied by the Qt engine')
                section_layout.addWidget(QLabel('Font Family:'))
                section_layout.addWidget(font_family_combo)
                section_layout.addWidget(QLabel('Font Size:'))
                section_layout.addWidget(font_size_spin)
                section_layout.addWidget(QLabel('Widget Style:'))
                section_layout.addWidget(ui_style_combo)
            elif tab_name == 'Diagnostics':
                level_combo = QComboBox()
                level_combo.setMaxVisibleItems(20)
                level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
                level_combo.setCurrentText(str(runtime.get('log_level', 'INFO')))
                level_combo.setToolTip('Set the detail level of logging messages written to the log file')
                section_layout.addWidget(QLabel('Log level:'))
                section_layout.addWidget(level_combo)
                test_btn = QPushButton('Test Connection')
                test_btn.setToolTip('Test connection settings to the qBittorrent server')

                def _start_connection_test(btn=test_btn):
                    btn.setEnabled(False)
                    btn.setText('Testing connection...')
                    worker = ConnectionTestWorker()

                    def _on_test_finished(result, w=worker):
                        btn.setEnabled(True)
                        btn.setText('Test Connection')
                        QMessageBox.information(dialog, 'Connection Test', str(result.get('message', 'Test completed.')))
                        if w in active_workers:
                            active_workers.remove(w)

                    worker.finished.connect(_on_test_finished)
                    active_workers.append(worker)
                    worker.start()

                test_btn.clicked.connect(lambda: _start_connection_test())
                section_layout.addWidget(test_btn)
                logs_btn = QPushButton('View Logs')
                logs_btn.setToolTip('Open the log viewer utility')
                logs_btn.clicked.connect(_open_qt_log_viewer)
                clear_logs_btn = QPushButton('Clear Log File')
                clear_logs_btn.setToolTip('Clear all entries from the active application log file')
                clear_logs_btn.clicked.connect(lambda: QMessageBox.information(dialog, 'Logs', str(run_qt_clear_log_file().get('message', 'Done'))))
                section_layout.addWidget(logs_btn)
                section_layout.addWidget(clear_logs_btn)
            elif tab_name == 'API Rate Limits':
                anilist_interval_spin = QSpinBox()
                anilist_interval_spin.setRange(1, 1440)
                anilist_interval_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, config.get_pref('anilist_manual_refresh_interval_minutes', 15)) or 15))
                anilist_interval_spin.setToolTip('Minimum cooldown minutes between active AniList cache API updates')
                subsplease_interval_spin = QSpinBox()
                subsplease_interval_spin.setRange(1, 1440)
                subsplease_interval_spin.setValue(int(config.get_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, config.get_pref('subsplease_manual_refresh_interval_minutes', 15)) or 15))
                subsplease_interval_spin.setToolTip('Minimum cooldown minutes between active SubsPlease API updates')
                retention_mode_combo = QComboBox()
                retention_mode_combo.setMaxVisibleItems(20)
                retention_mode_combo.addItems([
                    CacheRetentionMode.AGE,
                    CacheRetentionMode.SIZE,
                    CacheRetentionMode.ROTATE,
                ])
                retention_mode_combo.setCurrentText(str(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, CacheRetentionMode.AGE) or CacheRetentionMode.AGE).strip().lower())
                retention_mode_combo.setToolTip('Set how the cache retention is limited (by age, total file size, or rotation count)')
                cache_ttl_spin = QSpinBox()
                cache_ttl_spin.setRange(0, 3650)
                cache_ttl_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, 30) or 30))
                cache_ttl_spin.setToolTip('Max age in days for cache entries. (Recommended: 30-90 days)')
                cache_max_mb_spin = QSpinBox()
                cache_max_mb_spin.setRange(1, 1024)
                cache_max_mb_spin.setValue(int(config.get_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, 10) or 10))
                cache_max_mb_spin.setToolTip('Max file size limit in MB for the cache on disk. (Recommended: 5-20 MB)')
                refresh_scope_combo = QComboBox()
                refresh_scope_combo.setMaxVisibleItems(20)
                refresh_scope_combo.addItems([AniListRefreshScope.TITLE_ONLY, AniListRefreshScope.TITLE_AND_SEASON])
                refresh_scope_combo.setCurrentText(str(config.get_pref(PrefKeys.ANILIST_REFRESH_SCOPE, AniListRefreshScope.TITLE_ONLY) or AniListRefreshScope.TITLE_ONLY).strip().lower())
                refresh_scope_combo.setToolTip('Select scope of data pulled: TITLE_ONLY or TITLE_AND_SEASON')
                langs = config.get_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, ['romaji', 'english', 'native', 'synonym', 'synonym_other']) or []
                if not isinstance(langs, list):
                    langs = ['romaji', 'english', 'native', 'synonym', 'synonym_other']
                lang_romaji_box = QCheckBox('Romaji')
                lang_romaji_box.setChecked('romaji' in langs)
                lang_romaji_box.setToolTip('Enable Romaji variant titles from AniList')
                lang_english_box = QCheckBox('English')
                lang_english_box.setChecked('english' in langs)
                lang_english_box.setToolTip('Enable English translated titles from AniList')
                lang_native_box = QCheckBox('Native')
                lang_native_box.setChecked('native' in langs)
                lang_native_box.setToolTip('Enable native Japanese/original script titles from AniList')
                lang_synonym_box = QCheckBox('Synonyms')
                lang_synonym_box.setChecked('synonym' in langs)
                lang_synonym_box.setToolTip('Enable alternative naming synonyms from AniList')
                lang_synonym_other_box = QCheckBox('Other-Lang Synonyms')
                lang_synonym_other_box.setChecked('synonym_other' in langs)
                lang_synonym_other_box.setToolTip('Enable non-English language name variations from AniList')
                section_layout.addWidget(QLabel('AniList minimum interval (minutes):'))
                section_layout.addWidget(anilist_interval_spin)
                save_subsplease_cache_box = QCheckBox('Save SubsPlease Cache to Disk')
                save_subsplease_cache_box.setChecked(bool(config.get_pref('save_subsplease_cache', False)))
                save_subsplease_cache_box.setToolTip('Save the fetched schedule to disk so it persists across app restarts.')

                section_layout.addWidget(QLabel('SubsPlease minimum interval (minutes):'))
                section_layout.addWidget(subsplease_interval_spin)
                section_layout.addWidget(save_subsplease_cache_box)
                section_layout.addWidget(QLabel('Cache retention mode:'))
                section_layout.addWidget(retention_mode_combo)
                section_layout.addWidget(QLabel('Cache max age (days):'))
                section_layout.addWidget(cache_ttl_spin)
                section_layout.addWidget(QLabel('Cache max size (MB):'))
                section_layout.addWidget(cache_max_mb_spin)
                section_layout.addWidget(QLabel('AniList manual refresh scope:'))
                section_layout.addWidget(refresh_scope_combo)
                section_layout.addWidget(QLabel('AniList title variation languages:'))
                section_layout.addWidget(lang_romaji_box)
                section_layout.addWidget(lang_english_box)
                section_layout.addWidget(lang_native_box)
                section_layout.addWidget(lang_synonym_box)
                section_layout.addWidget(lang_synonym_other_box)
            else:
                section_layout.addWidget(QLabel(f'{tab_name} settings are available in this preview tab.'))
            tab_layout.addWidget(section)
            if tab_name != 'Action Bar':
                tab_layout.addStretch()
            tabs.addTab(tab_scroll, tab_name)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QPushButton('Save && Close')

        def _on_settings_tab_changed(index: int) -> None:
            if defaults_tab_index is None or index != defaults_tab_index:
                return
            try:
                _load_categories_list()
            except Exception:
                pass

        tabs.currentChanged.connect(_on_settings_tab_changed)
        if defaults_tab_index is not None:
            _on_settings_tab_changed(defaults_tab_index)

        def _save_settings_preview() -> None:
            needs_restart = False
            payload = {
                'protocol': protocol_combo.currentText(),
                'host': host_edit.text(),
                'port': port_edit.text(),
                'username': user_edit.text(),
                'password': pass_edit.text(),
                'ca_cert': ca_cert_edit.text().strip(),
                'verify_ssl': verify_ssl_box.isChecked(),
                'mode': 'online' if online_radio.isChecked() else 'offline',
                'default_save_path': (defaults_save_path_edit.text().strip() if defaults_save_path_edit is not None else str(getattr(config, 'DEFAULT_SAVE_PATH', '') or '')),
                'default_download_path': (defaults_download_path_edit.text().strip() if defaults_download_path_edit is not None else str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or '')),
                'default_category': (
                    defaults_category_combo.currentText().strip()
                    if defaults_category_combo is not None
                    else (defaults_category_edit.text().strip() if defaults_category_edit is not None else str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
                ),
                'default_affected_feeds': (defaults_feeds_edit.text().strip() if defaults_feeds_edit is not None else ', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or [])),
            }
            connection_result = run_qt_save_connection_settings(payload)

            if defaults_category_edit is not None:
                config.DEFAULT_SAVE_PATH = defaults_save_path_edit.text().strip() if defaults_save_path_edit is not None else config.DEFAULT_SAVE_PATH
                config.DEFAULT_DOWNLOAD_PATH = defaults_download_path_edit.text().strip() if defaults_download_path_edit is not None else config.DEFAULT_DOWNLOAD_PATH
                config.DEFAULT_CATEGORY = (
                    defaults_category_combo.currentText().strip()
                    if defaults_category_combo is not None
                    else defaults_category_edit.text().strip()
                )
                config.set_pref('default_affected_feeds_manual', (defaults_feeds_edit.text().strip() if defaults_feeds_edit is not None else ''))
                if ask_delete_confirm_box is not None:
                    config.set_pref('confirm_delete_titles', bool(ask_delete_confirm_box.isChecked()))

            if prefix_imports_box is not None:
                config.set_pref('prefix_imports', bool(prefix_imports_box.isChecked()))
            if auto_sanitize_box is not None:
                config.set_pref('auto_sanitize_paths', bool(auto_sanitize_box.isChecked()))
            if pre_import_check_box is not None:
                config.set_pref('pre_import_sanitize_check', bool(pre_import_check_box.isChecked()))
            if auto_import_sanitize_box is not None:
                config.set_pref(PrefKeys.AUTO_SANITIZE, bool(auto_import_sanitize_box.isChecked()))
            if show_import_check_box is not None:
                value = bool(show_import_check_box.isChecked())
                config.set_pref('show_import_sanitize_check', value)
                config.set_pref('pre_import_sanitize_check', value)
            if filesystem_combo is not None:
                config.set_pref('filesystem_type', filesystem_combo.currentText())
            if sanitize_replace_all_box is not None:
                config.set_pref(PrefKeys.SANITIZE_REPLACE_ALL, bool(sanitize_replace_all_box.isChecked()))
            if sanitize_global_char_edit is not None:
                char_val = str(sanitize_global_char_edit.text() or '_')[:1]
                config.set_pref(PrefKeys.SANITIZE_GLOBAL_CHAR, char_val or '_')
            if sanitize_char_edits:
                custom_map = {}
                for ch, edit in sanitize_char_edits.items():
                    val = str(edit.text() or '').strip()
                    if not val:
                        continue
                    token = val.lower()
                    if token == 'remove':
                        custom_map[ch] = '__REMOVE__'
                    elif token == 'space':
                        custom_map[ch] = '__SPACE__'
                    else:
                        custom_map[ch] = val
                config.set_pref(PrefKeys.SANITIZE_CUSTOM_MAP, custom_map)
            if theme_combo is not None:
                old_theme = config.get_pref("theme", "light")
                new_theme = theme_combo.currentText().strip() or "light"
                if str(old_theme).strip().lower() != str(new_theme).strip().lower():
                    set_theme_pref(new_theme)
            if time_format_combo is not None:
                config.set_pref('time_format', time_format_combo.currentText())
            if view_mode_combo is not None:
                config.set_pref('view_mode', view_mode_combo.currentText())
            if font_family_combo is not None:
                config.set_pref('font_family', font_family_combo.currentFont().family() or 'Segoe UI')
            if font_size_spin is not None:
                config.set_pref('font_size', int(font_size_spin.value()))
            if ui_style_combo is not None:
                config.set_pref(PrefKeys.UI_STYLE_THEME, ui_style_combo.currentText())
            if level_combo is not None:
                config.set_pref('log_level', level_combo.currentText())
            if anilist_interval_spin is not None:
                interval = int(anilist_interval_spin.value())
                config.set_pref(PrefKeys.ANILIST_PULL_COOLDOWN_MINUTES, interval)
                config.set_pref('anilist_manual_refresh_interval_minutes', interval)
            if subsplease_interval_spin is not None:
                interval = int(subsplease_interval_spin.value())
                config.set_pref(PrefKeys.SUBSPLEASE_PULL_COOLDOWN_MINUTES, interval)
                config.set_pref('subsplease_manual_refresh_interval_minutes', interval)
            if save_subsplease_cache_box is not None:
                config.set_pref('save_subsplease_cache', bool(save_subsplease_cache_box.isChecked()))
            if retention_mode_combo is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_RETENTION_MODE, retention_mode_combo.currentText().strip().lower() or CacheRetentionMode.AGE)
            if cache_ttl_spin is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_TTL_DAYS, int(cache_ttl_spin.value()))
            if cache_max_mb_spin is not None:
                config.set_pref(PrefKeys.ANILIST_TITLE_VARIATION_CACHE_MAX_MB, int(cache_max_mb_spin.value()))
            if refresh_scope_combo is not None:
                config.set_pref(PrefKeys.ANILIST_REFRESH_SCOPE, refresh_scope_combo.currentText().strip().lower() or AniListRefreshScope.TITLE_ONLY)
            if all(v is not None for v in [lang_romaji_box, lang_english_box, lang_native_box, lang_synonym_box, lang_synonym_other_box]):
                selected_langs = []
                if lang_romaji_box.isChecked():
                    selected_langs.append('romaji')
                if lang_english_box.isChecked():
                    selected_langs.append('english')
                if lang_native_box.isChecked():
                    selected_langs.append('native')
                if lang_synonym_box.isChecked():
                    selected_langs.append('synonym')
                if lang_synonym_other_box.isChecked():
                    selected_langs.append('synonym_other')
                if not selected_langs:
                    selected_langs = ['romaji']
                config.set_pref(PrefKeys.ANILIST_DISPLAY_LANGUAGES, selected_langs)

            if action_bar_list_widget is not None:
                new_order = []
                for i in range(action_bar_list_widget.count()):
                    item = action_bar_list_widget.item(i)
                    key = item.data(core.Qt.UserRole)
                    new_order.append(key)
            
                config.set_pref('action_bar_order', new_order)
                if config._cached_prefs is None:
                    config._cached_prefs = config._load_ini_prefs()
                config._cached_prefs.pop('action_bar_visible', None)
                config._save_ini_prefs(config._cached_prefs)
            
                config.set_pref('action_bar_custom_labels', temp_custom_labels)
                config.set_pref('action_bar_custom_icons', temp_custom_icons)
                config.set_pref('action_bar_custom_dropdowns', temp_custom_dropdowns)
                config.set_pref('action_bar_dropdown_subactions', temp_dropdown_subactions)
                if action_bar_mode_combo is not None:
                    mode_idx = action_bar_mode_combo.currentIndex()
                    if mode_idx == 1:
                        mode_str = 'scrollable'
                    elif mode_idx == 2:
                        mode_str = 'hybrid'
                    elif mode_idx == 3:
                        mode_str = 'icons_only'
                    elif mode_idx == 4:
                        mode_str = 'static'
                    else:
                        mode_str = 'responsive'
                    config.set_pref('action_bar_mode', mode_str)
                if action_bar_size_combo is not None:
                    config.set_pref('action_bar_button_size', action_bar_size_combo.currentText().lower())
            
                # Instantly rebuild action bar on main window
                try:
                    rebuild_action_bar()
                    if '_on_window_resize' in globals() or '_on_window_resize' in locals():
                        _on_window_resize()
                    elif hasattr(window, 'resizeEvent'):
                        window.resizeEvent(None)
                except Exception as e:
                    logger.error(f"Failed to rebuild action bar: {e}")

            run_qt_save_platform_settings({'main_server': 'qbittorrent', 'export_targets': ['qbittorrent']})

            if needs_restart:
                resp = QMessageBox.question(dialog, "Restart Required", "Theme has been changed. Do you want to restart the application now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if resp == QMessageBox.StandardButton.Yes:
                    from src.utils import restart_application
                    restart_application()
        
            dialog.accept()

        save_btn.clicked.connect(_save_settings_preview)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        dialog_layout.addLayout(footer)
        # dialog.exec() is called by the launcher
