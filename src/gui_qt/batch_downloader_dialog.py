"""
Batch Downloader Dialog Module.

Implements the PySide6 user interface for the Multi Batch Downloader.
Provides a list of imported shows, source selection, resolution filters,
an episode checklist table, and action execution triggers:
  - Local Download: Save .torrent files to disk
  - Copy Magnets: Copy magnet URIs to clipboard
  - Push to qBittorrent: Direct integration to start downloading immediately

Uses QThread background workers for all heavy lifting (API fetching, downloading,
and qBittorrent communication) to ensure the UI remains responsive.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QListWidget,
    QListWidgetItem,
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

from src.services.batch_downloader import (
    get_imported_shows_list,
    fetch_and_filter_episodes,
    download_torrent_file,
    push_to_qbittorrent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Background Workers (Non-blocking I/O)
# ============================================================================

class FetchRSSWorker(QThread):
    """
    Background worker thread to fetch and filter episodes from an RSS/API source.
    
    Prevents the GUI from freezing during network requests. Emits a list of
    parsed episode dictionaries when finished.
    """
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, source: str, query: str, feed_url: Optional[str] = None, resolution: str = 'Any'):
        super().__init__()
        self.source = source
        self.query = query
        self.feed_url = feed_url
        self.resolution = resolution

    def run(self):
        try:
            episodes = fetch_and_filter_episodes(
                source=self.source,
                query=self.query,
                feed_url=self.feed_url,
                resolution=self.resolution
            )
            self.finished.emit(episodes)
        except Exception as e:
            logger.error(f"Error fetching RSS in worker: {e}", exc_info=True)
            self.error.emit(str(e))


class PushQBTWorker(QThread):
    """
    Background worker thread to push torrent URLs to the qBittorrent server.
    
    Handles the authentication and submission logic asynchronously.
    Emits a success boolean and a status message string when finished.
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


class DownloadLocalWorker(QThread):
    """
    Background worker thread to download multiple .torrent files to disk.
    
    Files are saved with sanitized names to the user-selected destination.
    Emits counts of successful downloads and skipped magnets (since magnet
    links cannot be downloaded as files).
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

                # Sanitize the episode title for use as a filename
                clean_title = re.sub(r'[<>:"/\\|?*]', '_', title)
                dest_path = os.path.join(self.dest_dir, f"{clean_title}.torrent")

                if download_torrent_file(url, dest_path):
                    success_count += 1

            self.finished.emit(success_count, skipped_magnets)
        except Exception as e:
            logger.error(f"Error downloading torrents locally in worker: {e}", exc_info=True)
            self.error.emit(str(e))


# ============================================================================
# Main Dialog Class
# ============================================================================

class BatchDownloaderDialog(QDialog):
    """
    Multi Batch Downloader user interface dialog.
    
    A split-pane dialog:
      - Left: List of imported shows from the user's library
      - Right: Search parameters, episode checklist table, and action buttons
      
    Coordinates the background workers to fetch data and execute download actions
    based on the user's table selections.
    """

    def __init__(self, parent: Optional[QWidget] = None, preselected_show_name: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Multi Batch Downloader")
        self.resize(1100, 680)
        self.setMinimumSize(950, 580)
        
        self.shows = get_imported_shows_list()
        self.preselected_show_name = preselected_show_name
        self.fetched_episodes: List[Dict[str, Any]] = []
        self._active_worker: Optional[QThread] = None

        self._setup_ui()
        self._populate_shows()
        self._select_initial_show()

    def _setup_ui(self):
        """Build the complete dialog layout."""
        # Main Layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # Left Panel - Show List Selection
        # -------------------------------------------------------------
        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.StyledPanel)
        left_panel.setMinimumWidth(280)
        left_panel.setMaximumWidth(340)
        
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("<b>Imported Show Rules:</b>"))

        # Search filter for shows list
        self.show_filter_edit = QLineEdit()
        self.show_filter_edit.setPlaceholderText("Filter imported shows...")
        self.show_filter_edit.textChanged.connect(self._filter_shows_list)
        left_layout.addWidget(self.show_filter_edit)

        # Show list widget
        self.shows_list = QListWidget()
        self.shows_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.shows_list.currentItemChanged.connect(self._on_selected_show_changed)
        left_layout.addWidget(self.shows_list)

        main_layout.addWidget(left_panel)

        # -------------------------------------------------------------
        # Right Panel - Controls & Episode Table
        # -------------------------------------------------------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # 1. Search Query Parameters Panel
        query_panel = QFrame()
        query_panel.setFrameShape(QFrame.StyledPanel)
        query_layout = QGridLayout(query_panel)
        query_layout.setContentsMargins(10, 10, 10, 10)
        query_layout.setSpacing(8)

        # Row 0: Source Combobox & Query Edit
        query_layout.addWidget(QLabel("Feed Source:"), 0, 0)
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        query_layout.addWidget(self.source_combo, 0, 1)

        query_layout.addWidget(QLabel("Search Query:"), 0, 2)
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Enter search term (e.g. show title)...")
        query_layout.addWidget(self.query_edit, 0, 3)

        # Row 1: Resolution & Custom Feed URL
        query_layout.addWidget(QLabel("Resolution:"), 1, 0)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["Any", "1080p", "720p", "480p"])
        query_layout.addWidget(self.resolution_combo, 1, 1)

        query_layout.addWidget(QLabel("Feed URL:"), 1, 2)
        self.feed_url_edit = QLineEdit()
        self.feed_url_edit.setPlaceholderText("Custom RSS Feed URL...")
        query_layout.addWidget(self.feed_url_edit, 1, 3)

        # Fetch button
        self.fetch_btn = QPushButton("Search Episodes")
        self.fetch_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.fetch_btn.clicked.connect(self._fetch_feed_episodes)
        query_layout.addWidget(self.fetch_btn, 0, 4, 2, 1)

        # Grid column stretch options
        query_layout.setColumnStretch(3, 1)
        
        right_layout.addWidget(query_panel)

        # 2. Progress / Loading Indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate marquee
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        right_layout.addWidget(self.progress_bar)

        # 3. Episode Checklist Table
        self.episodes_table = QTableWidget()
        self.episodes_table.setColumnCount(4)
        self.episodes_table.setHorizontalHeaderLabels(["Select", "Episode Title", "Publish Date", "Link Type"])
        self.episodes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.episodes_table.verticalHeader().setVisible(False)
        self.episodes_table.setAlternatingRowColors(True)
        
        header = self.episodes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        right_layout.addWidget(self.episodes_table)

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

        self.status_label = QLabel("No episodes loaded.")
        self.status_label.setStyleSheet("color: gray;")
        select_action_layout.addWidget(self.status_label)

        right_layout.addLayout(select_action_layout)

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

        config_layout.addWidget(QLabel("Tags:"))
        self.tags_edit = QLineEdit("batch-download")
        self.tags_edit.setMaximumWidth(150)
        self.tags_edit.setToolTip("Comma separated list of tags to append to the qBittorrent torrents.")
        config_layout.addWidget(self.tags_edit)

        right_layout.addWidget(config_frame)

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

        right_layout.addLayout(actions_layout)

        main_layout.addWidget(right_panel)

    def _populate_shows(self):
        """Populate the left-hand list widget with imported shows."""
        self.shows_list.clear()
        for show in self.shows:
            item = QListWidgetItem(show['display_name'])
            item.setData(Qt.UserRole, show)
            self.shows_list.addItem(item)

    def _select_initial_show(self):
        """Select a specific show on launch, or the first one if not specified."""
        if self.preselected_show_name:
            items = self.shows_list.findItems(self.preselected_show_name, Qt.MatchExactly)
            if items:
                self.shows_list.setCurrentItem(items[0])
                return
        if self.shows_list.count() > 0:
            self.shows_list.setCurrentRow(0)

    def _filter_shows_list(self, text: str):
        """Hide/show items in the left-hand list based on search text."""
        for i in range(self.shows_list.count()):
            item = self.shows_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _on_selected_show_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        """
        Handle show selection change.
        
        Auto-fills the search query with the show's must_contain property
        and sets up the available feed sources (enabling 'Configured Feeds'
        only if the show actually has them).
        """
        if not current:
            return
        
        show = current.data(Qt.UserRole)
        self.query_edit.setText(show['must_contain'] or show['display_name'])
        self.save_path_edit.setText(show['save_path'])

        # Setup feed source combobox dynamically based on whether the show has configured feeds
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        
        feeds = show.get('feeds', [])
        if feeds:
            self.source_combo.addItem("Configured Feeds", "feeds")
        
        self.source_combo.addItem("SubsPlease Search", "subsplease")
        self.source_combo.addItem("Nyaa Search", "nyaa")
        self.source_combo.addItem("Custom Feed URL", "custom")
        self.source_combo.blockSignals(False)

        # Trigger initial source UI layout setup
        self._on_source_changed(0)

    def _on_source_changed(self, index: int):
        """Toggle input field enabled/disabled states based on selected source."""
        source_data = self.source_combo.currentData()
        
        show = None
        current_item = self.shows_list.currentItem()
        if current_item:
            show = current_item.data(Qt.UserRole)

        if source_data == "feeds" and show:
            # Feeds: disable custom URL, disable query (it filters automatically)
            self.feed_url_edit.setEnabled(False)
            feeds = show.get('feeds', [])
            self.feed_url_edit.setText(feeds[0] if feeds else "")
            self.query_edit.setEnabled(False)
        elif source_data == "custom":
            # Custom: enable URL edit, enable query for local filtering
            self.feed_url_edit.setEnabled(True)
            self.feed_url_edit.setText("")
            self.feed_url_edit.setFocus()
            self.query_edit.setEnabled(True)
        else:
            # SubsPlease/Nyaa: disable URL, enable query for API search
            self.feed_url_edit.setEnabled(False)
            self.feed_url_edit.setText("")
            self.query_edit.setEnabled(True)

    def _fetch_feed_episodes(self):
        """Validate inputs and launch the background worker to fetch episodes."""
        source = self.source_combo.currentData()
        query = self.query_edit.text().strip()
        feed_url = self.feed_url_edit.text().strip()
        resolution = self.resolution_combo.currentText()

        if source == "custom" and not feed_url:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid custom feed RSS URL.")
            return
        
        if (source == "subsplease" or source == "nyaa") and not query:
            QMessageBox.warning(self, "Validation Error", "Please enter a search query.")
            return

        # Disable search interface during request
        self.fetch_btn.setEnabled(False)
        self.shows_list.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Searching episodes...")
        
        self._active_worker = FetchRSSWorker(
            source=source,
            query=query,
            feed_url=feed_url,
            resolution=resolution
        )
        self._active_worker.finished.connect(self._on_fetch_completed)
        self._active_worker.error.connect(self._on_fetch_failed)
        self._active_worker.start()

    def _on_fetch_completed(self, episodes: List[Dict[str, Any]]):
        """Worker callback: Populate the results table with fetched episodes."""
        self._cleanup_worker()
        self.fetch_btn.setEnabled(True)
        self.shows_list.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        self.fetched_episodes = episodes
        self.episodes_table.setRowCount(0)
        
        if not episodes:
            self.status_label.setText("No episodes found matching criteria.")
            return

        self.status_label.setText(f"Found {len(episodes)} release(s).")
        self.episodes_table.setRowCount(len(episodes))

        for row, ep in enumerate(episodes):
            # Checkbox item (Select)
            check_item = QTableWidgetItem()
            check_item.setCheckState(Qt.Checked)  # Auto-select all by default
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.episodes_table.setItem(row, 0, check_item)

            # Title
            self.episodes_table.setItem(row, 1, QTableWidgetItem(ep['title']))
            
            # Pub Date
            self.episodes_table.setItem(row, 2, QTableWidgetItem(ep['pub_date'] or "Unknown"))
            
            # Link Type
            link_type = "Both" if ep.get('magnet') and ep.get('torrent_url') else ("Magnet Only" if ep.get('magnet') else "Torrent Only")
            self.episodes_table.setItem(row, 3, QTableWidgetItem(link_type))

    def _on_fetch_failed(self, error_msg: str):
        """Worker callback: Handle fetch errors gracefully."""
        self._cleanup_worker()
        self.fetch_btn.setEnabled(True)
        self.shows_list.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Search failed.")
        QMessageBox.critical(self, "Search Error", f"Failed to retrieve episodes: {error_msg}")

    def _cleanup_worker(self):
        """Release the current background worker thread reference to free memory."""
        if self._active_worker is not None:
            self._active_worker.deleteLater()
            self._active_worker = None

    def _set_all_checkboxes(self, state: Qt.CheckState):
        """Helper to mass select/deselect all rows."""
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _invert_checkboxes(self):
        """Helper to invert the selection state of all rows."""
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item:
                current_state = item.checkState()
                new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)

    def _get_selected_rows_indices(self) -> List[int]:
        """Return the row indices of all currently checked episodes."""
        selected = []
        for row in range(self.episodes_table.rowCount()):
            item = self.episodes_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected.append(row)
        return selected

    def _browse_save_path(self):
        """Open a directory picker to select a custom local save path."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Local Save Directory")
        if dir_path:
            self.save_path_edit.setText(dir_path)

    def _action_download_local(self):
        """Execute the 'Download Torrents Locally' action via background worker."""
        selected_rows = self._get_selected_rows_indices()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select at least one episode to download.")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Select Local Save Directory for Torrent Files")
        if not dest_dir:
            return

        # Gather selected episodes for the worker
        selected_episodes = [self.fetched_episodes[idx] for idx in selected_rows]

        self.download_local_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Downloading {len(selected_episodes)} torrent file(s)...")

        self._active_worker = DownloadLocalWorker(selected_episodes, dest_dir)
        self._active_worker.finished.connect(self._on_download_local_completed)
        self._active_worker.error.connect(self._on_download_local_failed)
        self._active_worker.start()

    def _on_download_local_completed(self, success_count: int, skipped_magnets: int):
        """Worker callback: Report local download results to the user."""
        self._cleanup_worker()
        self.download_local_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Download finished.")

        msg = f"Successfully downloaded {success_count} torrent file(s) locally."
        if skipped_magnets > 0:
            msg += f"\nSkipped {skipped_magnets} release(s) because they only provide magnet links."
        QMessageBox.information(self, "Downloads Completed", msg)

    def _on_download_local_failed(self, error_msg: str):
        """Worker callback: Handle local download errors gracefully."""
        self._cleanup_worker()
        self.download_local_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Download failed.")
        QMessageBox.critical(self, "Download Error", f"Failed to download torrent files: {error_msg}")

    def _action_copy_magnets(self):
        """Execute the 'Copy Magnet Links' action synchronously."""
        selected_rows = self._get_selected_rows_indices()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select at least one episode to copy.")
            return

        magnets = []
        for idx in selected_rows:
            ep = self.fetched_episodes[idx]
            mag = ep.get('magnet')
            if mag:
                magnets.append(mag)

        if not magnets:
            QMessageBox.warning(self, "No Magnet Links", "None of the selected releases contain magnet links.")
            return

        # Write to clipboard (newline separated)
        clipboard_text = "\n".join(magnets)
        QGuiApplication.clipboard().setText(clipboard_text)
        
        QMessageBox.information(
            self, 
            "Copied to Clipboard", 
            f"Successfully copied {len(magnets)} magnet link(s) to the clipboard."
        )

    def _action_push_qbt(self):
        """Execute the 'Push to qBittorrent' action via background worker."""
        selected_rows = self._get_selected_rows_indices()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select at least one episode to push.")
            return

        urls = []
        for idx in selected_rows:
            ep = self.fetched_episodes[idx]
            # Prefer magnet link for direct pushing, fallback to torrent_url
            url = ep.get('magnet') or ep.get('torrent_url')
            if url:
                urls.append(url)

        if not urls:
            QMessageBox.warning(self, "No Links Found", "Selected items do not contain any downloadable URLs or magnet links.")
            return

        save_path = self.save_path_edit.text().strip() or None
        tags = self.tags_edit.text().strip() or None

        # Fetch Category from currently selected show config if available
        category = None
        current_show = self.shows_list.currentItem()
        if current_show:
            show_data = current_show.data(Qt.UserRole)
            category = show_data.get('category') or None

        # Execute push in background thread
        self.push_qbt_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Pushing to qBittorrent...")

        self._active_worker = PushQBTWorker(urls, save_path=save_path, category=category, tags=tags)
        self._active_worker.finished.connect(self._on_push_qbt_completed)
        self._active_worker.start()

    def _on_push_qbt_completed(self, success: bool, msg: str):
        """Worker callback: Report qBittorrent push results to the user."""
        self._cleanup_worker()
        self.push_qbt_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Push finished.")

        if success:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Push Failed", msg)
