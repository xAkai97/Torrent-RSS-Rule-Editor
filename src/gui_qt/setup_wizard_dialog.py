"""
Setup Wizard Dialog Module.

Implements the step-by-step application configuration wizard shown on
first run (or when triggered manually from Settings).

The wizard guides the user through:
  - Step 1: UI Basics (theme, log level)
  - Step 2: qBittorrent Connection (host, port, credentials, online/offline mode)
  - Step 3: Platform Defaults (default category, download path, save path)
"""

import logging
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QCheckBox,
    QRadioButton,
    QWidget,
    QGroupBox,
    QStackedWidget,
    QMessageBox
)
from src.config import config
from src.constants import PrefKeys
from src.api.qbittorrent import ping_qbittorrent

logger = logging.getLogger(__name__)


class SetupWizardDialog(QDialog):
    """
    Modern step-by-step configuration wizard.

    Uses a QStackedWidget to implement a paginated wizard flow without
    using the heavier QWizard component. Saves all configurations to the
    central AppConfig when the user clicks 'Finish'.
    """

    def __init__(self, parent=None, refresh_chips_callback=None, set_theme_pref_callback=None):
        super().__init__(parent)
        self.refresh_chips_callback = refresh_chips_callback
        self.set_theme_pref_callback = set_theme_pref_callback

        self.setWindowTitle('Setup Wizard')
        self.resize(760, 560)
        self._setup_ui()

    def _setup_ui(self):
        """Build the wizard layout, including all pages and the navigation footer."""
        # Import lazily to avoid circular import issues with main_window
        from src.gui_qt.main_window import (
            run_qt_get_connection_settings,
            run_qt_get_platform_settings,
            run_qt_get_runtime_settings
        )

        # Pre-load current settings to populate the form fields
        self.conn_settings = run_qt_get_connection_settings()
        self.platform_settings = run_qt_get_platform_settings()
        self.runtime = run_qt_get_runtime_settings()

        wizard_layout = QVBoxLayout(self)

        # Header
        title_label = QLabel('Setup Wizard')
        title_label.setStyleSheet('font-weight: 600; font-size: 18px;')
        subtitle_label = QLabel('Configure connection, platform targets, and defaults in three quick steps.')
        subtitle_label.setWordWrap(True)
        wizard_layout.addWidget(title_label)
        wizard_layout.addWidget(subtitle_label)

        # Main content stack
        self.stack = QStackedWidget(self)
        wizard_layout.addWidget(self.stack, 1)

        # =====================================================================
        # Step 1: Welcome and UI basics
        # =====================================================================
        step1 = QWidget()
        step1_layout = QVBoxLayout(step1)
        step1_layout.addWidget(QLabel('Step 1 of 3 - Basics'))
        intro = QLabel(
            'This wizard sets up the essential defaults for a modern Qt workflow. '
            'You can fine-tune everything later in Settings.'
        )
        intro.setWordWrap(True)
        step1_layout.addWidget(intro)
        step1_group = QGroupBox('Quick UI Defaults')
        step1_form = QFormLayout(step1_group)
        
        self.theme_combo = QComboBox()
        self.theme_combo.setMaxVisibleItems(20)
        self.theme_combo.addItems(['light', 'dark', 'auto'])
        self.theme_combo.setCurrentText(str(self.runtime.get('theme', 'light')))
        self.theme_combo.setToolTip('Set the application theme (Light, Dark, or Auto to sync with OS theme)')
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.setMaxVisibleItems(20)
        self.log_level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
        self.log_level_combo.setCurrentText(str(self.runtime.get('log_level', 'INFO')))
        self.log_level_combo.setToolTip('Choose the minimum logging level to output in the log files')
        
        step1_form.addRow('Theme:', self.theme_combo)
        step1_form.addRow('Log level:', self.log_level_combo)
        step1_layout.addWidget(step1_group)
        step1_layout.addStretch()
        self.stack.addWidget(step1)

        # =====================================================================
        # Step 2: qBittorrent connection
        # =====================================================================
        step2 = QWidget()
        step2_layout = QVBoxLayout(step2)
        step2_layout.addWidget(QLabel('Step 2 of 3 - qBittorrent Connection'))
        step2_group = QGroupBox('Connection Profile')
        step2_form = QFormLayout(step2_group)
        
        self.protocol_combo = QComboBox()
        self.protocol_combo.setMaxVisibleItems(20)
        self.protocol_combo.addItems(['http', 'https'])
        self.protocol_combo.setCurrentText(str(self.conn_settings.get('protocol', 'http')))
        self.protocol_combo.setToolTip('Choose HTTP or HTTPS protocol for qBittorrent connection')
        
        self.host_edit = QLineEdit(str(self.conn_settings.get('host', '')))
        self.host_edit.setToolTip('IP address or host name of the qBittorrent server')
        
        self.port_edit = QLineEdit(str(self.conn_settings.get('port', '8080')))
        self.port_edit.setToolTip('Port number of the qBittorrent server (typically 8080)')
        
        self.user_edit = QLineEdit(str(self.conn_settings.get('username', '')))
        self.user_edit.setToolTip('Username for qBittorrent web UI authentication')
        
        self.pass_edit = QLineEdit(str(self.conn_settings.get('password', '')))
        self.pass_edit.setToolTip('Password for qBittorrent web UI authentication')
        self.pass_edit.setEchoMode(QLineEdit.Password)
        
        self.verify_ssl_box = QCheckBox('Verify SSL Certificate')
        self.verify_ssl_box.setChecked(bool(self.conn_settings.get('verify_ssl', True)))
        self.verify_ssl_box.setToolTip('Enable to verify HTTPS certificate validation')
        
        self.online_radio = QRadioButton('Online mode')
        self.online_radio.setToolTip('Connect directly to qBittorrent API for online sync')
        self.offline_radio = QRadioButton('Offline mode')
        self.offline_radio.setToolTip('Export rules to a JSON file format offline without connecting')
        
        self.online_radio.setChecked(str(self.conn_settings.get('mode', 'online')) == 'online')
        self.offline_radio.setChecked(not self.online_radio.isChecked())
        
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.online_radio)
        mode_row.addWidget(self.offline_radio)
        mode_row.addStretch(1)
        
        test_conn_btn = QPushButton('Test Connection')
        test_conn_btn.setToolTip('Test connection parameters against the qBittorrent server')
        test_conn_btn.clicked.connect(self._test_connection)
        
        step2_form.addRow('Protocol:', self.protocol_combo)
        step2_form.addRow('Host:', self.host_edit)
        step2_form.addRow('Port:', self.port_edit)
        step2_form.addRow('Username:', self.user_edit)
        step2_form.addRow('Password:', self.pass_edit)
        step2_form.addRow('', self.verify_ssl_box)
        step2_form.addRow('Mode:', mode_row)
        step2_form.addRow('', test_conn_btn)
        step2_layout.addWidget(step2_group)
        
        self.step2_status = QLabel('')
        self.step2_status.setWordWrap(True)
        step2_layout.addWidget(self.step2_status)
        step2_layout.addStretch()
        self.stack.addWidget(step2)

        # =====================================================================
        # Step 3: Platform and export defaults
        # =====================================================================
        step3 = QWidget()
        step3_layout = QVBoxLayout(step3)
        step3_layout.addWidget(QLabel('Step 3 of 3 - Platform and Export'))
        step3_group = QGroupBox('Platform Defaults')
        step3_form = QFormLayout(step3_group)
        
        self.defaults_save_path = QLineEdit(str(getattr(config, 'DEFAULT_SAVE_PATH', '') or ''))
        self.defaults_save_path.setToolTip('The default save path for downloads on the server (relative to download path)')
        
        self.defaults_download_path = QLineEdit(str(getattr(config, 'DEFAULT_DOWNLOAD_PATH', '') or ''))
        self.defaults_download_path.setToolTip('The default qBittorrent default download path (absolute path on server)')
        
        self.defaults_category = QLineEdit(str(getattr(config, 'DEFAULT_CATEGORY', '') or ''))
        self.defaults_category.setToolTip('The default qBittorrent category to apply to new rules')
        
        step3_form.addRow('Default save path:', self.defaults_save_path)
        step3_form.addRow('Default download path:', self.defaults_download_path)
        step3_form.addRow('Default category:', self.defaults_category)
        step3_layout.addWidget(step3_group)
        finish_note = QLabel('Click Finish to apply and persist these settings.')
        finish_note.setWordWrap(True)
        step3_layout.addWidget(finish_note)
        step3_layout.addStretch()
        self.stack.addWidget(step3)

        # =====================================================================
        # Wizard Footer (Navigation controls)
        # =====================================================================
        footer = QHBoxLayout()
        self.step_indicator = QLabel('Step 1 of 3')
        footer.addWidget(self.step_indicator)
        footer.addStretch(1)
        
        self.back_btn = QPushButton('Back')
        self.back_btn.setToolTip('Go back to the previous setup step')
        self.back_btn.clicked.connect(self._back_step)
        
        self.next_btn = QPushButton('Next')
        self.next_btn.setToolTip('Go forward to the next setup step')
        self.next_btn.clicked.connect(self._next_step)
        
        self.finish_btn = QPushButton('Finish')
        self.finish_btn.setToolTip('Save all configuration wizard settings and close')
        self.finish_btn.clicked.connect(self._finish_setup)
        
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setToolTip('Discard settings and close the wizard')
        cancel_btn.clicked.connect(self.reject)
        
        footer.addWidget(self.back_btn)
        footer.addWidget(self.next_btn)
        footer.addWidget(self.finish_btn)
        footer.addWidget(cancel_btn)
        wizard_layout.addLayout(footer)

        self._update_nav()

    def _update_nav(self) -> None:
        """Update button states and the step indicator based on the current page."""
        index = int(self.stack.currentIndex())
        total = int(self.stack.count())
        self.step_indicator.setText(f'Step {index + 1} of {total}')
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < total - 1)
        self.finish_btn.setEnabled(index == total - 1)

    def _test_connection(self) -> None:
        """Synchronously test the qBittorrent connection with the form values."""
        protocol = self.protocol_combo.currentText().strip() or 'http'
        host = self.host_edit.text().strip()
        port = self.port_edit.text().strip() or '8080'
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        verify_ssl = bool(self.verify_ssl_box.isChecked())
        
        if not host:
            QMessageBox.warning(self, 'Connection Test', 'Host is required for connection test.')
            return
            
        ok, message = ping_qbittorrent(protocol, host, port, username, password, verify_ssl, getattr(config, 'QBT_CA_CERT', None))
        self.step2_status.setText(str(message or ('Connection successful.' if ok else 'Connection failed.')))
        
        if ok:
            QMessageBox.information(self, 'Connection Test', str(message or 'Connection successful.'))
        else:
            QMessageBox.warning(self, 'Connection Test', str(message or 'Connection failed.'))

    def _next_step(self) -> None:
        """Advance to the next wizard page."""
        index = int(self.stack.currentIndex())
        if index < self.stack.count() - 1:
            self.stack.setCurrentIndex(index + 1)
        self._update_nav()

    def _back_step(self) -> None:
        """Go back to the previous wizard page."""
        index = int(self.stack.currentIndex())
        if index > 0:
            self.stack.setCurrentIndex(index - 1)
        self._update_nav()

    def _finish_setup(self) -> None:
        """Save all collected wizard settings into the central config and close."""
        # Import dynamically to avoid circular references
        from src.gui_qt.main_window import (
            run_qt_save_connection_settings,
            run_qt_save_platform_settings,
            run_qt_save_runtime_settings
        )

        # 1. Save Connection Profile
        connection_payload = {
            'protocol': self.protocol_combo.currentText(),
            'host': self.host_edit.text(),
            'port': self.port_edit.text(),
            'username': self.user_edit.text(),
            'password': self.pass_edit.text(),
            'verify_ssl': self.verify_ssl_box.isChecked(),
            'mode': 'online' if self.online_radio.isChecked() else 'offline',
            'default_save_path': self.defaults_save_path.text().strip(),
            'default_download_path': self.defaults_download_path.text().strip(),
            'default_category': self.defaults_category.text().strip(),
            'default_affected_feeds': ', '.join(getattr(config, 'DEFAULT_AFFECTED_FEEDS', []) or []),
        }
        conn_result = run_qt_save_connection_settings(connection_payload)
        
        # 2. Save Platform Preferences
        platform_result = run_qt_save_platform_settings(
            {
                'main_server': 'qbittorrent',
                'export_targets': ['qbittorrent'],
            }
        )
        
        # 3. Save Runtime/UI Preferences
        new_theme = self.theme_combo.currentText().strip() or "light"
        runtime_result = run_qt_save_runtime_settings(
            {
                'theme': new_theme,
                'log_level': self.log_level_combo.currentText().strip() or 'INFO',
                'ui_style_theme': str(config.get_pref(PrefKeys.UI_STYLE_THEME, 'clam') or 'clam'),
            }
        )

        # Apply theme immediately if a callback was provided
        if self.set_theme_pref_callback:
            self.set_theme_pref_callback(new_theme)

        # Check if all saves succeeded
        ok_all = bool(conn_result.get('success')) and bool(platform_result.get('success')) and bool(runtime_result.get('success'))
        
        # Refresh the main window status chips
        if self.refresh_chips_callback:
            self.refresh_chips_callback()

        if ok_all:
            QMessageBox.information(self, 'Setup Wizard', 'Setup completed successfully.')
            self.accept()
        else:
            QMessageBox.warning(
                self,
                'Setup Wizard',
                'Setup completed with some issues. Review Settings for details.',
            )
            self.accept()
