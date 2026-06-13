"""
Cache Viewer Dialog — Inspect SubsPlease and AniList Cached Data.

This dialog lets the user browse the locally cached data that drives
the Rule Editor's title variation features:

  Tab 1 — SubsPlease Cache:
    Shows the mapping between MAL/AniList titles and their SubsPlease
    equivalents. Used for matching anime titles to torrent release names.
    Columns: MAL Title | SubsPlease Title | Last Updated | Exact Match

  Tab 2 — AniList Cache:
    Shows the title variation/alias data fetched from AniList's GraphQL API.
    Each top-level entry is a title key, with child nodes for each alias
    (tagged with language: romaji, english, native, synonym).

Both tabs support:
  - Real-time text filtering (searches across all visible columns)
  - Sortable columns (click headers)
  - Refresh button to reload from the cache file
"""

import logging
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTabWidget,
    QHeaderView,
    QWidget
)
from src.api.subsplease import load_subsplease_cache, load_title_variations_cache

logger = logging.getLogger(__name__)


class CacheViewerDialog(QDialog):
    """
    API Cache Data Viewer Dialog.

    Two-tab interface for browsing SubsPlease schedule mappings and
    AniList title variations. All data comes from the local cache file
    (no network requests are made by this dialog).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('API Cache Data Viewer')
        self.resize(980, 680)
        self._setup_ui()

    def _setup_ui(self):
        """Build the tabbed dialog layout with search bars and tree widgets."""
        dialog_layout = QVBoxLayout(self)

        # Tab widget splitting SubsPlease and AniList data
        tab_widget = QTabWidget(self)
        dialog_layout.addWidget(tab_widget, 1)

        # =================================================================
        # Tab 1: SubsPlease Schedule Cache
        # Shows MAL title → SubsPlease title mappings
        # =================================================================
        subs_tab = QWidget()
        subs_layout = QVBoxLayout(subs_tab)

        # Search bar for filtering SubsPlease entries
        subs_search_layout = QHBoxLayout()
        subs_search_layout.addWidget(QLabel('Filter Titles:'))
        self.subs_search_edit = QLineEdit()
        self.subs_search_edit.setPlaceholderText('Search MAL title or SubsPlease title...')
        self.subs_search_edit.setToolTip('Type here to search MAL titles or SubsPlease titles in the schedule cache')
        subs_search_layout.addWidget(self.subs_search_edit)
        subs_refresh_btn = QPushButton('Refresh View')
        subs_refresh_btn.setToolTip('Reload the cache data from the local cache file to update the table display')
        subs_search_layout.addWidget(subs_refresh_btn)
        subs_layout.addLayout(subs_search_layout)

        # Table showing MAL ↔ SubsPlease title mappings
        self.subs_tree = QTreeWidget()
        self.subs_tree.setToolTip('Table of cached schedule titles showing MAL and SubsPlease match mappings')
        self.subs_tree.setHeaderLabels(['MAL Title', 'SubsPlease Title', 'Last Updated', 'Exact Match'])
        self.subs_tree.setAlternatingRowColors(True)
        self.subs_tree.setSortingEnabled(True)
        self.subs_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.subs_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.subs_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.subs_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        subs_layout.addWidget(self.subs_tree)
        tab_widget.addTab(subs_tab, 'SubsPlease Cache')

        # =================================================================
        # Tab 2: AniList Title Variations Cache
        # Shows title keys with expandable child alias nodes
        # =================================================================
        ani_tab = QWidget()
        ani_layout = QVBoxLayout(ani_tab)

        # Search bar for filtering AniList entries
        ani_search_layout = QHBoxLayout()
        ani_search_layout.addWidget(QLabel('Filter Variants:'))
        self.ani_search_edit = QLineEdit()
        self.ani_search_edit.setPlaceholderText('Search variants, aliases or languages...')
        self.ani_search_edit.setToolTip('Type here to search cached AniList titles, aliases, or languages')
        ani_search_layout.addWidget(self.ani_search_edit)
        ani_refresh_btn = QPushButton('Refresh View')
        ani_refresh_btn.setToolTip('Reload the cache data from the local cache file to update the tree display')
        ani_search_layout.addWidget(ani_refresh_btn)
        ani_layout.addLayout(ani_search_layout)

        # Tree widget showing title keys with expandable alias children
        self.ani_tree = QTreeWidget()
        self.ani_tree.setToolTip('Tree hierarchy of AniList variants. Expand to see language-specific aliases')
        self.ani_tree.setHeaderLabels(['Title Key / Variant', 'Language / Type', 'Last Updated'])
        self.ani_tree.setAlternatingRowColors(True)
        self.ani_tree.setSortingEnabled(True)
        self.ani_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ani_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ani_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        ani_layout.addWidget(self.ani_tree)
        tab_widget.addTab(ani_tab, 'AniList Cache')

        # --- Connect signals ---
        self.subs_search_edit.textChanged.connect(self._populate_subsplease)
        self.ani_search_edit.textChanged.connect(self._populate_anilist)
        subs_refresh_btn.clicked.connect(self._populate_subsplease)
        ani_refresh_btn.clicked.connect(self._populate_anilist)

        # Load data immediately when the dialog opens
        self._populate_subsplease()
        self._populate_anilist()

    def _populate_subsplease(self) -> None:
        """
        Load and display SubsPlease cache data in the table.

        Reads the SubsPlease schedule cache and populates the tree widget.
        Filters entries by the search text (matches against both MAL and
        SubsPlease title columns).
        """
        self.subs_tree.clear()
        filter_text = self.subs_search_edit.text().strip().lower()
        try:
            cache = load_subsplease_cache() or {}
        except Exception as e:
            logger.error('Failed to load SubsPlease cache: %s', e)
            cache = {}

        items = []
        for mal_title, data in cache.items():
            sp_title = ''
            updated = ''
            exact = ''
            if isinstance(data, dict):
                sp_title = str(data.get('subsplease', '') or '')
                updated = str(data.get('last_updated', '') or '')
                exact = 'Yes' if bool(data.get('exact_match', False)) else 'No'
            else:
                sp_title = str(data)

            # Apply search filter (matches either MAL or SubsPlease title)
            if filter_text and filter_text not in mal_title.lower() and filter_text not in sp_title.lower():
                continue

            item = QTreeWidgetItem([mal_title, sp_title, updated, exact])
            items.append(item)

        self.subs_tree.addTopLevelItems(items)

    def _populate_anilist(self) -> None:
        """
        Load and display AniList variation cache data in the tree.

        Each cache entry becomes a top-level tree node showing the title key
        and alias count. Child nodes show individual aliases with their
        language tags.

        The search filter matches against title keys, alias text, and
        language labels.
        """
        self.ani_tree.clear()
        filter_text = self.ani_search_edit.text().strip().lower()
        try:
            cache = load_title_variations_cache() or {}
        except Exception as e:
            logger.error('Failed to load AniList variations cache: %s', e)
            cache = {}

        for key, val in cache.items():
            aliases = []
            updated = ''
            if isinstance(val, dict):
                aliases = val.get('aliases', []) or []
                updated = str(val.get('last_updated', '') or '')

            # Check if this entry (or any of its aliases) matches the search filter
            match_filter = True
            if filter_text:
                match_filter = False
                if filter_text in key.lower() or filter_text in updated.lower():
                    match_filter = True
                else:
                    # Search through child aliases for a match
                    for alias in aliases:
                        alias_txt = ''
                        alias_lang = ''
                        if isinstance(alias, str):
                            alias_txt = alias
                        elif isinstance(alias, dict):
                            alias_txt = str(alias.get('text', ''))
                            alias_lang = str(alias.get('lang', ''))
                        if filter_text in alias_txt.lower() or filter_text in alias_lang.lower():
                            match_filter = True
                            break

            if not match_filter:
                continue

            # Create top-level node: "Title Key" | "(N aliases)" | "2026-06-01"
            top_item = QTreeWidgetItem([key, f'({len(aliases)} aliases)', updated])

            # Create child nodes for each alias: "Alias Text" | "romaji" | "-"
            for alias in aliases:
                alias_txt = ''
                alias_lang = 'synonym'
                if isinstance(alias, str):
                    alias_txt = alias
                elif isinstance(alias, dict):
                    alias_txt = str(alias.get('text', ''))
                    alias_lang = str(alias.get('lang', 'synonym'))

                child_item = QTreeWidgetItem([alias_txt, alias_lang, '-'])
                top_item.addChild(child_item)

            self.ani_tree.addTopLevelItem(top_item)
