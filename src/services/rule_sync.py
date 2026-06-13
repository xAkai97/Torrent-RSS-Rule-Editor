"""
Rule Sync — Merging Server Rules into the Local Title Library.

When the user fetches existing rules from qBittorrent ("Import from Server"),
this module handles merging those incoming rules into the local ALL_TITLES
data structure without creating duplicates.

The merge algorithm:
  1. Index all existing local entries by normalized title, mustContain, and ruleName
  2. For each incoming entry, check if any of its keys match an existing entry
  3. If no match → add as a new entry
  4. If match → skip (it's a duplicate)
  5. After merging, run a final deduplication pass to remove any duplicates
     that might have existed in the original data

Key design: All comparisons are case-insensitive and whitespace-normalized
to prevent near-duplicate entries like "My Hero Academia" and "my hero academia".
"""

from __future__ import annotations

from typing import Any, Callable, Dict


def _normalize_sync_key(value: Any) -> str:
    """
    Normalize a string for duplicate detection: lowercase, collapsed whitespace.

    Examples:
      "  Attack on Titan  " → "attack on titan"
      "MY HERO   ACADEMIA" → "my hero academia"
      None → ""
    """
    try:
        if value is None:
            return ''
        text = str(value).strip().lower()
        if not text:
            return ''
        # Collapse multiple spaces into one
        return ' '.join(text.split())
    except Exception:
        return ''


def _extract_sync_keys(
    item: Any,
    get_display_title_fn: Callable[[Any], str],
    get_rule_name_fn: Callable[[Any], str],
) -> tuple[str, str, str]:
    """
    Extract all possible identity keys from a title entry for dedup matching.

    Returns three normalized keys (any may be empty):
      - title_key: from the display title
      - must_key: from the mustContain/must_contain field
      - rule_key: from the ruleName/rule_name/name field

    If any of these keys match between two entries, they're considered
    duplicates of each other.
    """
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
    """
    Merge incoming server rules into the local titles, deduplicating as we go.

    This is the main merge function called when importing rules from qBittorrent.
    It performs a two-phase deduplication:

    Phase 1 — Incoming filter:
      Check each incoming entry against all existing local entries.
      Skip any incoming entry that matches an existing one by title,
      mustContain, or ruleName.

    Phase 2 — Post-merge dedup:
      After merging, scan the combined 'existing' list for internal
      duplicates (entries that match each other). This catches duplicates
      that may have existed in the original data before the merge.

    Args:
        current_titles: The current ALL_TITLES dictionary.
        incoming_entries: List of new entries from the qBittorrent server.
        get_display_title_fn: Function to extract display title from an entry.
        get_rule_name_fn: Function to extract rule name from an entry.

    Returns:
        A payload dictionary with:
          updated_titles          — the merged titles dictionary
          new_entries_count       — how many new entries were added
          removed_duplicates_count — how many duplicates were removed in phase 2
    """
    current = current_titles if isinstance(current_titles, dict) else {}
    entries = incoming_entries if isinstance(incoming_entries, list) else []

    # --- Phase 1: Build index of existing entries for fast lookup ---
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

    # --- Phase 1: Filter incoming entries against existing index ---
    new_entries: list[Any] = []
    for entry in entries:
        key, must_key, rule_key = _extract_sync_keys(entry, get_display_title_fn, get_rule_name_fn)

        # Check for duplicates across all three key types
        is_duplicate = False
        if key and key in existing_titles:
            is_duplicate = True
        elif must_key and must_key in existing_must_contain:
            is_duplicate = True
        elif rule_key and rule_key in existing_rule_names:
            is_duplicate = True

        if is_duplicate:
            continue

        # Not a duplicate — add to new entries and update the index
        if key:
            existing_titles.add(key)
        if must_key:
            existing_must_contain.add(must_key)
        if rule_key:
            existing_rule_names.add(rule_key)

        new_entries.append(entry)

    # --- Phase 2: Merge and deduplicate ---
    updated_titles = dict(current)
    current_existing = updated_titles.get('existing', [])
    if not isinstance(current_existing, list):
        current_existing = []
    current_existing.extend(new_entries)

    # Final dedup pass: remove entries with the same identity
    deduped_list: list[Any] = []
    seen_identities: set[tuple[str, str]] = set()
    removed_count = 0
    for item in current_existing:
        title_key, must_key, rule_key = _extract_sync_keys(item, get_display_title_fn, get_rule_name_fn)
        # Build a unique identity tuple — prefer ruleName, then mustContain, then title
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
