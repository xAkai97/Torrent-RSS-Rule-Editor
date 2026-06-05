"""Rule sync helpers for merging fetched server rules into local titles."""

from __future__ import annotations

from typing import Any, Callable, Dict


def _normalize_sync_key(value: Any) -> str:
    try:
        if value is None:
            return ''
        text = str(value).strip().lower()
        if not text:
            return ''
        return ' '.join(text.split())
    except Exception:
        return ''


def _extract_sync_keys(
    item: Any,
    get_display_title_fn: Callable[[Any], str],
    get_rule_name_fn: Callable[[Any], str],
) -> tuple[str, str, str]:
    try:
        if isinstance(item, dict):
            title_val = get_display_title_fn(item) or get_rule_name_fn(item)
            must_val = item.get('mustContain') or item.get('must_contain')
            rule_val = (
                item.get('ruleName')
                or item.get('rule_name')
                or item.get('name')
                or get_rule_name_fn(item)
            )
        else:
            title_val = str(item)
            must_val = None
            rule_val = None
    except Exception:
        title_val = str(item)
        must_val = None
        rule_val = None

    return (
        _normalize_sync_key(title_val),
        _normalize_sync_key(must_val),
        _normalize_sync_key(rule_val),
    )


def merge_existing_rule_entries(
    current_titles: dict[str, list[Any]] | Any,
    incoming_entries: list[Any] | Any,
    get_display_title_fn: Callable[[Any], str],
    get_rule_name_fn: Callable[[Any], str],
) -> Dict[str, Any]:
    """Merge incoming existing-rule entries into local titles with dedupe.

    Returns payload containing updated titles and merge statistics.
    """
    current = current_titles if isinstance(current_titles, dict) else {}
    entries = incoming_entries if isinstance(incoming_entries, list) else []

    existing_titles: set[str] = set()
    existing_must_contain: set[str] = set()
    existing_rule_names: set[str] = set()

    for _, item_list in current.items():
        if not isinstance(item_list, list):
            continue
        for item in item_list:
            norm_title, norm_must, norm_rule = _extract_sync_keys(item, get_display_title_fn, get_rule_name_fn)
            if norm_title:
                existing_titles.add(norm_title)
            if norm_must:
                existing_must_contain.add(norm_must)
            if norm_rule:
                existing_rule_names.add(norm_rule)

    new_entries: list[Any] = []
    for entry in entries:
        key, must_key, rule_key = _extract_sync_keys(entry, get_display_title_fn, get_rule_name_fn)

        is_duplicate = False
        if key and key in existing_titles:
            is_duplicate = True
        elif must_key and must_key in existing_must_contain:
            is_duplicate = True
        elif rule_key and rule_key in existing_rule_names:
            is_duplicate = True

        if is_duplicate:
            continue

        if key:
            existing_titles.add(key)
        if must_key:
            existing_must_contain.add(must_key)
        if rule_key:
            existing_rule_names.add(rule_key)

        new_entries.append(entry)

    updated_titles = dict(current)
    current_existing = updated_titles.get('existing', [])
    if not isinstance(current_existing, list):
        current_existing = []
    current_existing.extend(new_entries)

    deduped_list: list[Any] = []
    seen_identities: set[tuple[str, str]] = set()
    removed_count = 0
    for item in current_existing:
        title_key, must_key, rule_key = _extract_sync_keys(item, get_display_title_fn, get_rule_name_fn)
        identity = (
            ('r', rule_key)
            if rule_key
            else (('m', must_key) if must_key else ('t', title_key))
        )
        if identity[1] and identity in seen_identities:
            removed_count += 1
            continue
        seen_identities.add(identity)
        deduped_list.append(item)

    updated_titles['existing'] = deduped_list

    return {
        'updated_titles': updated_titles,
        'new_entries_count': len(new_entries),
        'removed_duplicates_count': removed_count,
    }
