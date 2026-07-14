"""
Nyaa.si Custom Search and Downloader Dialog Module.

Implements a premium user interface for custom Nyaa.si search queries,
supporting combinations of show names, uploaders, and custom tag/word filters.
Provides action triggers to download locally, copy magnets, or push to qBittorrent.
"""

import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QWidget,
    QFrame,
    QAbstractItemView
)

from src.config import config
from src.services.batch_downloader import (
    fetch_and_filter_episodes,
    download_torrent_file,
    push_to_qbittorrent,
)

logger = logging.getLogger(__name__)


class NyaaCustomSearchWorker(QThread):
    """
    Background worker thread to fetch and filter episodes from Nyaa.si.
    """
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, query: str, resolution: str = 'Any'):
        super().__init__()
        self.query = query
        self.resolution = resolution

    def run(self):
        try:
            episodes = fetch_and_filter_episodes(
                source='nyaa',
                query=self.query,
                resolution=self.resolution
            )
            self.finished.emit(episodes)
        except Exception as e:
            logger.error(f"Error fetching Nyaa in worker: {e}", exc_info=True)
            self.error.emit(str(e))


class NyaaDownloadWorker(QThread):
    """
    Background worker thread to download multiple .torrent files to disk.
    """
    finished = Signal(int, int)  # success_count, skipped_magnets
    error = Signal(str)

    def __init__(self, episodes: List[Dict[str, Any]], dest_dir: str):
        super().__init__()
        self.episodes = episodes
        self.dest_dir = dest_dir

    def run(self):
        try:
            success_count = 0
            skipped_magnets = 0

            for ep in self.episodes:
                url = ep.get('torrent_url')
                title = ep.get('title', 'release')

                if not url:
                    skipped_magnets += 1
                    continue

                clean_title = re.sub(r'[<>:"/\\|?*]', '_', title)
                dest_path = os.path.join(self.dest_dir, f"{clean_title}.torrent")

                if download_torrent_file(url, dest_path):
                    success_count += 1

            self.finished.emit(success_count, skipped_magnets)
        except Exception as e:
            logger.error(f"Error downloading torrents locally in worker: {e}", exc_info=True)
            self.error.emit(str(e))


class NyaaPushWorker(QThread):
    """
    Background worker thread to push torrent URLs to the qBittorrent server.
    """
    finished = Signal(bool, str)  # success, message

    def __init__(self, urls: List[str], save_path: Optional[str] = None,
                 category: Optional[str] = None, tags: Optional[str] = None):
        super().__init__()
        self.urls = urls
        self.save_path = save_path
        self.category = category
        self.tags = tags

    def run(self):
        try:
            success, msg = push_to_qbittorrent(
                urls=self.urls,
                save_path=self.save_path,
                category=self.category,
                tags=self.tags
            )
            self.finished.emit(success, msg)
        except Exception as e:
            logger.error(f"Error pushing to qBittorrent in worker: {e}", exc_info=True)
            self.finished.emit(False, f"Unexpected error: {e}")


class NyaaSearchDialog(QDialog):
    """
    Dialog providing UI for custom Nyaa RSS search.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Nyaa.si Custom RSS Search Addon")
        self.resize(950, 620)
        self.setMinimumSize(850, 520)
        
        self.fetched_episodes: List[Dict[str, Any]] = []
        self._active_worker: Optional[QThread] = None

        self._setup_ui()

    def _setup_ui(self):
        """Set up standard GUI controls for Nyaa Custom Search."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Search Query Parameters Panel
        query_panel = QFrame()
        query_panel.setFrameShape(QFrame.StyledPanel)
        query_layout = QGridLayout(query_panel)
        query_layout.setContentsMargins(10, 10, 10, 10)
        query_layout.setSpacing(8)

        query_layout.addWidget(QLabel("<b>Show / Search Query:</b>"), 0, 0)
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Enter anime title or general keywords...")
        query_layout.addWidget(self.query_edit, 0, 1, 1, 3)

        query_layout.addWidget(QLabel("<b>Uploader / User:</b>"), 1, 0)
        self.uploader_edit = QLineEdit()
        self.uploader_edit.setPlaceholderText("e.g. Erai-raws, SubsPlease (optional)...")
        query_layout.addWidget(self.uploader_edit, 1, 1)

        query_layout.addWidget(QLabel("<b>Custom Words / Filter:</b>"), 1, 2)
        self.custom_words_edit = QLineEdit()
        self.custom_words_edit.setPlaceholderText("e.g. 1080 HEVC dual-audio (optional)...")
        query_layout.addWidget(self.custom_words_edit, 1, 3)

        query_layout.addWidget(QLabel("<b>Resolution:</b>"), 2, 0)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["Any", "1080p", "720p", "480p"])
        query_layout.addWidget(self.resolution_combo, 2, 1)

        # Search button
        self.search_btn = QPushButton("Search Nyaa")
        self.search_btn.setStyleSheet("font-weight: bold; padding: 6px 16px; background-color: #0284c7; color: white;")
        self.search_btn.clicked.connect(self._search_nyaa)
        query_layout.addWidget(self.search_btn, 2, 2, 1, 2)

        main_layout.addWidget(query_panel)

        # 2. Progress / Loading Indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        main_layout.addWidget(self.progress_bar)

        # 3. Episode Checklist Table
        self.episodes_table = QTableWidget()
        self.episodes_table.setColumnCount(4)
        self.episodes_table.setHorizontalHeaderLabels(["Select", "Release Title", "Publish Date", "Link Type"])
        self.episodes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.episodes_table.verticalHeader().setVisible(False)
        self.episodes_table.setAlternatingRowColors(True)
        
        header = self.episodes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.episodes_table)

        # 4. Selection Action Panel
        select_action_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checkboxes(Qt.Checked))
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_checkboxes(Qt.Unchecked))
        self.invert_select_btn = QPushButton("Invert Selection")
        self.invert_select_btn.clicked.connect(self._invert_checkboxes)
        
        select_action_layout.addWidget(self.select_all_btn)
        select_action_layout.addWidget(self.deselect_all_btn)
        select_action_layout.addWidget(self.invert_select_btn)
        select_action_layout.addStretch()

        self.status_label = QLabel("No releases loaded.")
        self.status_label.setStyleSheet("color: gray;")
        select_action_layout.addWidget(self.status_label)

        main_layout.addLayout(select_action_layout)

        # 5. Save Path and Push Configuration (Bottom Frame)
        config_frame = QFrame()
        config_frame.setFrameShape(QFrame.StyledPanel)
        config_layout = QHBoxLayout(config_frame)
        config_layout.setContentsMargins(10, 8, 10, 8)
        config_layout.setSpacing(10)

        config_layout.addWidget(QLabel("Target Save Path:"))
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("Using qBittorrent defaults...")
        config_layout.addWidget(self.save_path_edit)

        self.browse_path_btn = QPushButton("Browse...")
        self.browse_path_btn.clicked.connect(self._browse_save_path)
        config_layout.addWidget(self.browse_path_btn)

        config_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setMinimumWidth(120)
        try:
            cached_cats = getattr(config, 'CACHED_CATEGORIES', {}) or {}
            if isinstance(cached_cats, dict):
                self.category_combo.addItems(sorted(str(k) for k in cached_cats.keys()))
        except Exception:
            pass
        config_layout.addWidget(self.category_combo)

        config_layout.addWidget(QLabel("Tags:"))
        self.tags_edit = QLineEdit("nyaa-custom-search")
        self.tags_edit.setMaximumWidth(150)
        config_layout.addWidget(self.tags_edit)

        main_layout.addWidget(config_frame)

        # 6. Bottom Row Actions
        actions_layout = QHBoxLayout()
        
        self.download_local_btn = QPushButton("Download Torrents Locally...")
        self.download_local_btn.clicked.connect(self._action_download_local)
        
        self.copy_magnets_btn = QPushButton("Copy Magnet Links")
        self.copy_magnets_btn.clicked.connect(self._action_copy_magnets)
        
        self.push_qbt_btn = QPushButton("Push to qBittorrent")
        self.push_qbt_btn.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white;")
        self.push_qbt_btn.clicked.connect(self._action_push_qbt)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        actions_layout.addWidget(self.download_local_btn)
        actions_layout.addWidget(self.copy_magnets_btn)
        actions_layout.addWidget(self.push_qbt_btn)
        actions_layout.addStretch()
        actions_layout.addWidget(self.close_btn)

        main_layout.addLayout(actions_layout)

    def _set_all_checkboxes(self, state: Qt.CheckState):
        """Set checking states on all checkboxes in table."""
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _invert_checkboxes(self):
        """Invert currently checked boxes state."""
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item:
                current_state = item.checkState()
                new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)

    def _browse_save_path(self):
        """Open a directory chooser to select output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_path_edit.text())
        if dir_path:
            self.save_path_edit.setText(dir_path)

    def _search_nyaa(self):
        """Build custom Nyaa search query and trigger the background worker."""
        if self._active_worker and self._active_worker.isRunning():
            return

        show = self.query_edit.text().strip()
        uploader = self.uploader_edit.text().strip()
        custom = self.custom_words_edit.text().strip()

        if not show and not uploader and not custom:
            QMessageBox.warning(self, "Input Required", "Please enter at least a query show name, uploader, or custom words.")
            return

        # Combine terms
        query_parts = []
        if uploader:
            query_parts.append(f'"{uploader}"')
        if show:
            query_parts.append(show)
        if custom:
            for word in re.split(r'[,\s]+', custom):
                if word.strip():
                    query_parts.append(word.strip())

        full_query = " ".join(query_parts)
        resolution = self.resolution_combo.currentText()

        self.search_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Searching Nyaa.si...")

        # Spawn worker
        worker = NyaaCustomSearchWorker(query=full_query, resolution=resolution)
        worker.finished.connect(self._on_search_finished)
        worker.error.connect(self._on_search_error)
        self._active_worker = worker
        worker.start()

    def _on_search_finished(self, episodes: List[Dict[str, Any]]):
        """Handle search finished success callback."""
        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.fetched_episodes = episodes

        self.episodes_table.setRowCount(0)
        if not episodes:
            self.status_label.setText("No results found.")
            return

        self.episodes_table.setRowCount(len(episodes))
        for row, ep in enumerate(episodes):
            # Checkbox item
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk_item.setCheckState(Qt.Checked)
            self.episodes_table.setItem(row, 0, chk_item)

            # Title
            title_item = QTableWidgetItem(ep.get('title', '(No Title)'))
            title_item.setToolTip(ep.get('title', ''))
            self.episodes_table.setItem(row, 1, title_item)

            # Date
            pub_date = ep.get('pub_date', '')
            date_item = QTableWidgetItem(pub_date)
            self.episodes_table.setItem(row, 2, date_item)

            # Link Type
            link_type = "Magnet" if ep.get('magnet') and not ep.get('torrent_url') else "Torrent"
            type_item = QTableWidgetItem(link_type)
            self.episodes_table.setItem(row, 3, type_item)

        self.status_label.setText(f"Found {len(episodes)} results.")

    def _on_search_error(self, err_msg: str):
        """Handle search finished failure callback."""
        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Search failed.")
        QMessageBox.warning(self, "Search Error", f"Failed to search Nyaa:\n\n{err_msg}")

    def _get_selected_episodes(self) -> List[Dict[str, Any]]:
        """Filter list of fetched episodes based on checked checkbox status."""
        selected = []
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                if row < len(self.fetched_episodes):
                    selected.append(self.fetched_episodes[row])
        return selected

    def _action_download_local(self):
        """Download checked items torrent files locally."""
        if self._active_worker and self._active_worker.isRunning():
            return

        selected = self._get_selected_episodes()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Please select at least one release to download.")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if not dest_dir:
            return

        self.progress_bar.setVisible(True)
        self.download_local_btn.setEnabled(False)

        worker = NyaaDownloadWorker(episodes=selected, dest_dir=dest_dir)
        
        def _on_download_finished(success_count, skipped_magnets):
            self.progress_bar.setVisible(False)
            self.download_local_btn.setEnabled(True)
            msg = f"Successfully downloaded {success_count} torrent file(s)."
            if skipped_magnets > 0:
                msg += f"\nSkipped {skipped_magnets} magnet links (cannot save as files)."
            QMessageBox.information(self, "Download Complete", msg)

        def _on_download_error(err):
            self.progress_bar.setVisible(False)
            self.download_local_btn.setEnabled(True)
            QMessageBox.warning(self, "Download Error", f"Failed to download files:\n\n{err}")

        worker.finished.connect(_on_download_finished)
        worker.error.connect(_on_download_error)
        self._active_worker = worker
        worker.start()

    def _action_copy_magnets(self):
        """Copy magnet URLs of checked items to clipboard."""
        selected = self._get_selected_episodes()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Please select at least one release to copy.")
            return

        magnets = [ep.get('magnet') for ep in selected if ep.get('magnet')]
        if not magnets:
            QMessageBox.information(self, "Copy Magnets", "None of the selected releases contain magnet links.")
            return

        clipboard = QGuiApplication.clipboard()
        clipboard.setText("\n".join(magnets))
        QMessageBox.information(self, "Copied", f"Copied {len(magnets)} magnet link(s) to the clipboard.")

    def _action_push_qbt(self):
        """Push checked items direct link/magnets to qBittorrent client."""
        if self._active_worker and self._active_worker.isRunning():
            return

        selected = self._get_selected_episodes()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Please select at least one release to push.")
            return

        urls = []
        for ep in selected:
            # Prefer torrent_url, fallback to magnet
            url = ep.get('torrent_url') or ep.get('magnet')
            if url:
                urls.append(url)

        if not urls:
            QMessageBox.warning(self, "Invalid Selection", "Selected releases do not contain download URLs or magnet links.")
            return

        save_path = self.save_path_edit.text().strip() or None
        category = self.category_combo.currentText().strip() or None
        tags = self.tags_edit.text().strip() or None

        self.progress_bar.setVisible(True)
        self.push_qbt_btn.setEnabled(False)

        worker = NyaaPushWorker(urls=urls, save_path=save_path, category=category, tags=tags)

        def _on_push_finished(success, msg):
            self.progress_bar.setVisible(False)
            self.push_qbt_btn.setEnabled(True)
            if success:
                QMessageBox.information(self, "Push to qBittorrent", f"Successfully pushed releases:\n\n{msg}")
            else:
                QMessageBox.warning(self, "Push Failed", f"Failed to push releases:\n\n{msg}")

        worker.finished.connect(_on_push_finished)
        self._active_worker = worker
        worker.start()
