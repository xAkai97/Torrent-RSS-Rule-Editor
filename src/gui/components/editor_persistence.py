"""Persistence and tree update helpers for editor apply flow."""

from __future__ import annotations

from typing import Any, Callable


def sync_entry_to_all_titles(
    all_titles: Any,
    entry: dict,
    old_title: str,
    new_title: str,
    get_display_title: Callable[[Any], str],
) -> bool:
    """Update matching entry in ALL_TITLES and return True when updated."""
    if not isinstance(all_titles, dict):
        return False

    for _, items in all_titles.items():
        if not isinstance(items, list):
            continue
        for i, it in enumerate(items):
            try:
                candidate_title = get_display_title(it) if isinstance(it, dict) else str(it)
            except Exception:
                candidate_title = str(it)

            if candidate_title == old_title or it is entry or candidate_title == new_title:
                items[i] = entry
                return True

    return False


def update_treeview_row_after_apply(treeview, idx: int, title: str, entry: dict) -> None:
    """Update only the selected row values when title text did not change."""
    items = treeview.get_children()
    if idx < 0 or idx >= len(items):
        return

    item_id = items[idx]
    enabled_mark = '✓' if entry.get('enabled', True) else ''
    category = entry.get('assignedCategory') or entry.get('category') or ''

    save_path = entry.get('savePath') or entry.get('save_path') or ''
    if not save_path:
        tp = entry.get('torrentParams') or entry.get('torrent_params') or {}
        save_path = tp.get('save_path') or tp.get('savePath') or ''

    save_path = str(save_path).replace('\\', '/') if save_path else ''
    treeview.item(item_id, values=(enabled_mark, str(idx + 1), title, category, save_path))


def persist_editor_entry_and_refresh_view(
    all_titles: Any,
    entry: dict,
    old_title: str,
    new_title: str,
    idx: int,
    treeview,
    tree_adapter,
    get_display_title: Callable[[Any], str],
    update_treeview_with_titles: Callable[[Any], None],
) -> dict:
    """Persist edited entry and refresh the tree view appropriately."""
    updated = sync_entry_to_all_titles(
        all_titles=all_titles,
        entry=entry,
        old_title=old_title,
        new_title=new_title,
        get_display_title=get_display_title,
    )

    title_changed = (old_title != new_title)
    if title_changed:
        update_treeview_with_titles(all_titles)
        tree_adapter.set_selection_indices([idx])
        tree_adapter.see_index(idx)
    else:
        update_treeview_row_after_apply(treeview, idx, new_title, entry)

    return {
        'updated_in_all_titles': bool(updated),
        'title_changed': bool(title_changed),
    }
