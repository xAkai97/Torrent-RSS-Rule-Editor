"""Treeview adapter utilities for stable, predictable row operations."""

import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable, List, Optional, Sequence, Tuple


class TreeviewAdapter:
    """Small adapter around ttk.Treeview to avoid wrapper side effects."""

    def __init__(self, treeview: ttk.Treeview):
        self.treeview = treeview
        self._sort_reverse: dict[str, bool] = {}
        self._filter_job: Optional[str] = None
        self._all_items_cache: List[Tuple[str, Tuple[str, ...]]] = []
        self._search_var: Optional[tk.StringVar] = None
        self._filter_type_var: Optional[tk.StringVar] = None
        self._filter_debounce_ms: int = 150

    def _native_delete(self, item_ids: Sequence[str]) -> None:
        """Delete via native Treeview API to bypass monkey-patched instance methods."""
        if not item_ids:
            return
        try:
            ttk.Treeview.delete(self.treeview, *item_ids)
        except Exception:
            for item_id in item_ids:
                try:
                    self.treeview.delete(item_id)
                except Exception:
                    continue

    def clear_all(self) -> None:
        """Clear all rows from treeview."""
        children = list(self.treeview.get_children())
        self._native_delete(children)

    def insert_rows(self, rows: Iterable[Tuple[Tuple[str, ...], Optional[Tuple[str, ...]]]]) -> int:
        """Insert rows and return inserted count.

        Each row is: (values, tags)
        """
        inserted = 0
        for values, tags in rows:
            if tags:
                self.treeview.insert('', 'end', values=values, tags=tags)
            else:
                self.treeview.insert('', 'end', values=values)
            inserted += 1
        return inserted

    def get_item_id_at_index(self, index: int) -> Optional[str]:
        """Return tree item id for index, or None when out of bounds."""
        try:
            children = self.treeview.get_children()
            if 0 <= index < len(children):
                return children[index]
        except Exception:
            return None
        return None

    def get_selected_indices(self) -> List[int]:
        """Get selected row indices in display order."""
        try:
            children = list(self.treeview.get_children())
            selected = set(self.treeview.selection())
            return [idx for idx, item_id in enumerate(children) if item_id in selected]
        except Exception:
            return []

    def get_index_at_y(self, y: int) -> Optional[int]:
        """Get row index at y coordinate, or None."""
        try:
            item_id = self.treeview.identify_row(y)
            if not item_id:
                return None
            children = list(self.treeview.get_children())
            return children.index(item_id)
        except Exception:
            return None

    def clear_selection(self) -> None:
        """Clear all selected rows."""
        try:
            selected = self.treeview.selection()
            if selected:
                self.treeview.selection_remove(*selected)
        except Exception:
            pass

    def set_selection_indices(self, indices: Sequence[int]) -> None:
        """Set selection by row indices."""
        item_ids: List[str] = []
        try:
            children = self.treeview.get_children()
            for idx in indices:
                if 0 <= idx < len(children):
                    item_ids.append(children[idx])
            if item_ids:
                self.treeview.selection_set(item_ids)
        except Exception:
            pass

    def see_index(self, index: int) -> None:
        """Ensure row at index is visible."""
        item_id = self.get_item_id_at_index(index)
        if not item_id:
            return
        try:
            self.treeview.see(item_id)
        except Exception:
            pass

    def delete_indices(self, indices: Sequence[int]) -> None:
        """Delete rows by display indices."""
        try:
            children = list(self.treeview.get_children())
            item_ids = [children[idx] for idx in sorted(indices, reverse=True) if 0 <= idx < len(children)]
            self._native_delete(item_ids)
        except Exception:
            pass

    def update_title_at_index(self, index: int, new_title: str) -> None:
        """Update title column (index 2) for row at index."""
        item_id = self.get_item_id_at_index(index)
        if not item_id:
            return
        try:
            values = list(self.treeview.item(item_id, 'values') or [])
            if len(values) >= 3:
                values[2] = new_title
                self.treeview.item(item_id, values=tuple(values))
        except Exception:
            pass

    def sort_column_toggle(self, column: str) -> None:
        """Sort by column and toggle sort direction for the next click."""
        reverse = self._sort_reverse.get(column, False)
        self.sort_by_column(column, reverse)
        self._sort_reverse[column] = not reverse

    def sort_by_column(self, column: str, reverse: bool = False) -> None:
        """Sort tree rows by column using stable, type-aware key handling."""
        try:
            children = list(self.treeview.get_children(''))
            sortable: List[Tuple[Any, str]] = []
            for item in children:
                raw = self.treeview.set(item, column)
                if column == 'index':
                    try:
                        key = int(str(raw).strip())
                    except Exception:
                        key = 10**9
                elif column == 'enabled':
                    key = 1 if str(raw).strip() else 0
                else:
                    key = str(raw).lower()
                sortable.append((key, item))

            sortable.sort(key=lambda pair: pair[0], reverse=reverse)
            for idx, (_, item) in enumerate(sortable):
                self.treeview.move(item, '', idx)
        except Exception:
            pass

    def bind_filter_controls(
        self,
        search_var: tk.StringVar,
        filter_type_var: tk.StringVar,
        debounce_ms: int = 150,
    ) -> None:
        """Bind search/filter variables for managed tree filtering."""
        self._search_var = search_var
        self._filter_type_var = filter_type_var
        self._filter_debounce_ms = max(0, int(debounce_ms))

        def _on_filter_change(*_args: object) -> None:
            self.apply_filter_debounced()

        try:
            search_var.trace_add('write', _on_filter_change)
            filter_type_var.trace_add('write', _on_filter_change)
        except Exception:
            pass

    def invalidate_filter_cache(self) -> None:
        """Invalidate cached tree rows used for filtering."""
        self._all_items_cache = []

    def apply_filter_debounced(self, debounce_ms: Optional[int] = None) -> None:
        """Schedule filter application with debounce."""
        delay = self._filter_debounce_ms if debounce_ms is None else max(0, int(debounce_ms))
        try:
            if self._filter_job:
                self.treeview.after_cancel(self._filter_job)
            if delay == 0:
                self.apply_filter()
            else:
                self._filter_job = self.treeview.after(delay, self.apply_filter)
        except Exception:
            self.apply_filter()

    def apply_filter(self) -> None:
        """Apply current filter controls to tree rows."""
        self._filter_job = None
        if not self._search_var or not self._filter_type_var:
            return

        try:
            search_text = str(self._search_var.get() or '').lower().strip()
            filter_by = str(self._filter_type_var.get() or 'Title')

            if not self._all_items_cache:
                self._rebuild_items_cache()

            if not search_text:
                for item_id, _ in self._all_items_cache:
                    try:
                        self.treeview.reattach(item_id, '', 'end')
                    except Exception:
                        continue
                return

            for item_id, values in self._all_items_cache:
                enabled, idx, title, category, savepath = values[:5]
                _ = enabled, idx
                if filter_by == 'Title':
                    match_text = str(title).lower()
                elif filter_by == 'Category':
                    match_text = str(category).lower()
                elif filter_by == 'Save Path':
                    match_text = str(savepath).lower()
                else:
                    match_text = f"{title} {category} {savepath}".lower()

                try:
                    if search_text in match_text:
                        self.treeview.reattach(item_id, '', 'end')
                    else:
                        self.treeview.detach(item_id)
                except Exception:
                    continue
        except Exception:
            pass

    def on_data_changed(self) -> None:
        """Invalidate caches and reapply active filter after external updates."""
        self.invalidate_filter_cache()
        self.apply_filter_debounced(debounce_ms=0)

    def _rebuild_items_cache(self) -> None:
        """Rebuild item/value cache from current tree rows."""
        self._all_items_cache = []
        try:
            for item_id in self.treeview.get_children():
                values = self.treeview.item(item_id, 'values')
                if values and len(values) >= 5:
                    self._all_items_cache.append((item_id, tuple(values)))
        except Exception:
            self._all_items_cache = []


__all__ = ["TreeviewAdapter"]
