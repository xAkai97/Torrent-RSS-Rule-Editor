"""
Log Viewer Dialog — View and Manage Application Logs.

Provides a read-only log viewer with:
  - Severity filtering (ALL, ERROR, WARNING, INFO, DEBUG)
  - Live refresh from the log file
  - Log file clearing with confirmation
  - "Open File" to open the log in the system's default text editor

The log file path comes from config.LOG_FILE (default: data/qbt_editor.log).
"""

import os
import logging
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTextEdit,
    QMessageBox
)
from src.config import config

logger = logging.getLogger(__name__)


class LogViewerDialog(QDialog):
    """
    Application Log Viewer Dialog.

    Shows the last 1000 lines of the application log file with
    optional severity filtering. Auto-scrolls to the bottom on load.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Application Log Viewer')
        self.resize(980, 620)
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: toolbar + log text area + status bar."""
        # Lazy import to avoid circular dependency with main_window
        from src.gui_qt.main_window import run_qt_load_log_tail, run_qt_clear_log_file

        dialog_layout = QVBoxLayout(self)

        # --- Toolbar: filter dropdown + action buttons ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('Filter:'))

        self.filter_combo = QComboBox(self)
        self.filter_combo.setMaxVisibleItems(20)
        self.filter_combo.addItems(['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'])
        self.filter_combo.setToolTip('Filter logs by severity level (ALL, ERROR, WARNING, INFO, DEBUG)')
        toolbar.addWidget(self.filter_combo)

        refresh_btn = QPushButton('Refresh')
        refresh_btn.setToolTip('Refresh log lines from the active log file')

        clear_btn = QPushButton('Clear Log')
        clear_btn.setToolTip('Empty the contents of the log file permanently')

        open_btn = QPushButton('Open File')
        open_btn.setToolTip('Open the log file in the default system text editor')

        close_btn = QPushButton('Close')
        close_btn.setToolTip('Close the Log Viewer dialog')

        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(open_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(close_btn)
        dialog_layout.addLayout(toolbar)

        # --- Log content area (read-only, no line wrapping) ---
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)
        dialog_layout.addWidget(self.log_view, 1)

        # --- Status bar at the bottom ---
        self.status_label = QLabel('')
        dialog_layout.addWidget(self.status_label)

        # --- Internal callbacks ---

        def _load_log() -> None:
            """Load the last 1000 lines from the log file and apply filter."""
            result = run_qt_load_log_tail(max_lines=1000)
            content = str(result.get('content', '') or '')

            # Apply severity filter if not showing ALL
            level = self.filter_combo.currentText()
            if level != 'ALL':
                filtered = []
                for line in content.splitlines():
                    if f' - {level} - ' in line:
                        filtered.append(line)
                content = '\n'.join(filtered)

            self.log_view.setPlainText(content or 'No log entries for current filter.')
            self.status_label.setText(str(result.get('message', 'Ready')))

            # Auto-scroll to the bottom to show newest entries
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _clear_log() -> None:
            """Clear the log file after user confirmation."""
            log_name = os.path.basename(getattr(config, 'LOG_FILE', 'qbt_editor.log'))
            if QMessageBox.question(self, 'Clear Log', f'Clear {log_name}?') != QMessageBox.Yes:
                return
            result = run_qt_clear_log_file()
            QMessageBox.information(self, 'Logs', str(result.get('message', 'Done')))
            _load_log()  # Refresh the view after clearing

        def _open_log_file() -> None:
            """Open the log file in the system's default text editor."""
            path = os.path.abspath(getattr(config, 'LOG_FILE', 'qbt_editor.log'))
            if not os.path.exists(path):
                QMessageBox.information(self, 'Logs', f'Log file not found: {path}')
                return
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
                else:
                    QMessageBox.information(self, 'Logs', f'Open this file manually:\n{path}')
            except Exception as exc:
                QMessageBox.warning(self, 'Logs', f'Failed opening log file: {exc}')

        # --- Connect signals ---
        refresh_btn.clicked.connect(_load_log)
        self.filter_combo.currentTextChanged.connect(lambda _=None: _load_log())
        clear_btn.clicked.connect(_clear_log)
        open_btn.clicked.connect(_open_log_file)
        close_btn.clicked.connect(self.accept)

        # Load log content immediately when the dialog opens
        _load_log()
