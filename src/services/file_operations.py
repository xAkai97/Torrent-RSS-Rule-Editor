"""
File Operations — Import/Export Business Logic.

This module handles all the business logic for importing and exporting rule data.
It's completely UI-agnostic — no Tkinter or Qt dependencies. The GUI layers
call these functions and handle the display themselves.

Import pipeline:
  1. Parse raw input (JSON, CSV, or line-delimited text)
  2. Normalize into the standard ALL_TITLES structure
  3. Validate folder name safety (reject/auto-sanitize invalid names)
  4. Deduplicate against existing titles
  5. Apply default fields (category, save path, feeds)
  6. Optionally prefix with season/year
  7. Merge into config.ALL_TITLES

Export pipeline:
  - Strip internal fields (node, ruleName) before writing JSON
  - Handled separately in the GUI layer (this module focuses on import)

Supported import formats:
  - JSON files (qBittorrent rules export, or our own format)
  - CSV/TSV text (title lists from spreadsheets)
  - Plain text (one title per line)
"""

import csv
import json
import logging
import os.path
from typing import Any, Dict, List, Optional, Tuple

from src.config import config
from src.utils import (
    sanitize_folder_name,
    validate_folder_name_by_filesystem,
)

logger = logging.getLogger(__name__)


# ============================================================================
# INPUT PARSING — Converting raw data into the standard titles structure
# ============================================================================

def normalize_titles_structure(data: Any) -> Optional[Dict[str, List]]:
    """
    Normalize various input formats into the standard ALL_TITLES structure.

    This is the universal input adapter — it handles whatever format the user
    throws at it and converts it into our standard dict-of-lists structure:
      {'anime': [...], 'manga': [...], etc.}

    Supported input formats:
      1. Already-standard dict with media type keys ('anime', 'manga', 'novel')
      2. qBittorrent rules dict ({'rules': {name: rule_data, ...}})
      3. Flat dict of rule definitions ({name: rule_data, ...})
      4. List of entries → wrapped as {'anime': [list]}
      5. Single string → wrapped as {'anime': [{title entry}]}

    Args:
        data: The raw parsed data (could be dict, list, string, etc.)

    Returns:
        A normalized titles dictionary, or None if the data is unrecognizable.
    """
    try:
        if isinstance(data, dict):
            # Already in standard format (has media type keys)
            if any(k in data for k in ['anime', 'manga', 'novel']):
                return data

            # qBittorrent rules export format: {'rules': {name: {...}, ...}}
            # or a flat dict of rules: {name: {...}, ...}
            if 'rules' in data or all(isinstance(v, dict) for v in data.values()):
                rules = data.get('rules', data)
                if isinstance(rules, dict):
                    # Convert from {name: rule_data} to [{...with node/ruleName...}]
                    normalized_list = []
                    for name, rule_data in rules.items():
                        if isinstance(rule_data, dict):
                            item = dict(rule_data)
                            # Inject internal tracking fields from the rule name
                            if 'ruleName' not in item:
                                item['ruleName'] = name
                            if 'node' not in item:
                                item['node'] = {'title': name}
                            elif isinstance(item['node'], dict) and 'title' not in item['node']:
                                item['node']['title'] = name
                            normalized_list.append(item)
                    return {'anime': normalized_list}
                return {'anime': rules}

            # Single dict entry — wrap in a list
            return {'anime': [data]}
        elif isinstance(data, list):
            return {'anime': data}
        elif isinstance(data, str):
            # Single title string — create a minimal entry
            return {'anime': [{'node': {'title': data}, 'mustContain': data}]}
        return None
    except Exception as e:
        logger.error(f"Error normalizing titles structure: {e}")
        return None


def import_titles_from_text(text: str) -> Optional[Dict[str, List]]:
    """
    Parse and normalize titles from raw text input (JSON, CSV, or plain text).

    Tries formats in order:
      1. JSON parsing (most structured)
      2. CSV parsing (for spreadsheet data)
      3. Line-delimited text (one title per line)

    Args:
        text: The raw text content to parse.

    Returns:
        A normalized titles structure, or None if all parsing attempts fail.
    """
    # Try JSON first (most common for rule files)
    try:
        parsed = json.loads(text)
    except Exception:
        # Not valid JSON — try CSV, then plain text
        csv_parsed = _import_titles_from_csv_text(text, force=False)
        if csv_parsed:
            return csv_parsed
        # Fall back to line-delimited plain text
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        parsed = lines if lines else None
        if not parsed:
            return None

    return normalize_titles_structure(parsed)


def _import_titles_from_csv_text(text: str, force: bool = False) -> Optional[Dict[str, List]]:
    """
    Parse CSV/TSV-like text into normalized titles.

    Auto-detects the delimiter (comma vs semicolon) based on which appears
    more frequently in the first line. Optionally detects and skips a header row.

    When force=False, this parser only activates for clear multi-line CSV input
    (2+ lines with delimiters) to avoid misclassifying plain title text as CSV.

    Args:
        text: The raw text that might be CSV.
        force: If True, parse even single-line input as CSV.

    Returns:
        A normalized titles structure, or None if the text isn't CSV-like.
    """
    try:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        has_csv_delimiter = (',' in first_line) or (';' in first_line)

        # Only auto-detect CSV if there are 2+ lines with delimiters
        if not force and (len(lines) < 2 or not has_csv_delimiter):
            return None

        # Auto-detect delimiter: use whichever appears more in the first line
        delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
        reader = csv.reader(lines, delimiter=delimiter)
        rows = [row for row in reader if row and any(str(cell).strip() for cell in row)]
        if not rows:
            return None

        # Detect header row by checking if first cell is a known header keyword
        header_key = str(rows[0][0]).strip().lower() if rows[0] else ''
        has_header = header_key in {'title', 'name', 'rule', 'rule_name', 'mustcontain', 'must_contain'}
        start_idx = 1 if has_header else 0

        # Extract titles from the first column of each row
        titles: List[str] = []
        for row in rows[start_idx:]:
            if not row:
                continue
            candidate = str(row[0]).strip()
            if candidate:
                titles.append(candidate)

        if not titles:
            return None

        # Build standard title entries from the extracted strings
        return {
            'anime': [
                {
                    'node': {'title': title},
                    'mustContain': title,
                    'ruleName': title,
                }
                for title in titles
            ]
        }
    except Exception:
        return None


# ============================================================================
# VALIDATION AND SANITIZATION — Ensuring titles are filesystem-safe
# ============================================================================

def _snapshot_import_entries(all_titles: Dict[str, List]) -> List[Dict[str, str]]:
    """
    Build a before/after snapshot of all titles showing sanitization effects.

    For each title, compares the raw name against the sanitized version and
    assigns a severity level:
      - 'ok'       — no changes needed
      - 'warn'     — sanitization changed the name (minor)
      - 'critical' — sanitization failed or removed too much (>40% of characters)

    Used by the import preview dialog to show the user what will happen to
    their title names when used as folder names.

    Args:
        all_titles: The imported titles to analyze.

    Returns:
        A list of snapshot dicts, each with: display, before, after, severity, reason.
    """
    snapshots: List[Dict[str, str]] = []

    if not isinstance(all_titles, dict):
        return snapshots

    for items in all_titles.values():
        if not isinstance(items, list):
            continue
        for entry in items:
            try:
                # Extract the raw title text from various entry formats
                if isinstance(entry, dict):
                    node = entry.get('node') or {}
                    display = str(node.get('title') or entry.get('title') or entry.get('name') or '').strip()
                    raw = str(entry.get('mustContain') or entry.get('title') or entry.get('name') or '').strip()
                    if not raw and display:
                        # Try extracting from "Season Year - Title" format
                        raw = display.split(' - ', 1)[-1].strip()
                else:
                    display = str(entry).strip()
                    raw = display

                if not raw:
                    continue

                # Run sanitization and validation
                sanitized = sanitize_folder_name(raw)
                valid, reason = validate_folder_name_by_filesystem(sanitized)

                # Determine severity level
                severity = 'ok'
                if sanitized != raw:
                    severity = 'warn'  # Name was modified by sanitization

                if (not valid) or (not sanitized.strip()):
                    severity = 'critical'  # Sanitized name is still invalid or empty
                elif raw:
                    try:
                        # Check character retention ratio
                        retention = len(sanitized) / max(1, len(raw))
                    except Exception:
                        retention = 1.0
                    if retention < 0.6:
                        severity = 'critical'  # Lost more than 40% of the name

                snapshots.append(
                    {
                        'display': display or raw,
                        'before': raw,
                        'after': sanitized,
                        'severity': severity,
                        'reason': reason or ('Sanitized for folder safety' if sanitized != raw else 'No change needed'),
                    }
                )
            except Exception:
                continue

    return snapshots


def prefix_titles_with_season_year(
    all_titles: Dict[str, List],
    season: str,
    year: str
) -> None:
    """
    Add a "Season Year - " prefix to all title display names.

    Also sets the savePath to include a season/year subdirectory structure:
      savePath = "Spring 2026/Sanitized Title"

    This is called during import to organize downloads by anime season.
    Respects the user's 'prefix_imports' preference — does nothing if disabled.

    Modifies entries in-place.

    Args:
        all_titles: Dictionary of titles to prefix.
        season: Season name (e.g. "Spring").
        year: Year string (e.g. "2026").
    """
    try:
        # Check if the user has disabled import prefixing
        try:
            if not bool(config.get_pref('prefix_imports', True)):
                return
        except Exception:
            pass

        if not season or not year:
            return

        prefix = f"{season} {year} - "
        season_year_folder = f"{season} {year}"

        if not isinstance(all_titles, dict):
            return

        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue

            for i, entry in enumerate(items):
                try:
                    if isinstance(entry, dict):
                        node = entry.get('node', {})
                        title = node.get('title') or entry.get('title') or ''
                        orig_title = str(title) if title else ''

                        if orig_title and not orig_title.startswith(prefix):
                            # Add prefix to display title
                            node['title'] = prefix + orig_title
                            entry['node'] = node

                            # Keep mustContain as the original (unprefixed) title
                            if not entry.get('mustContain'):
                                entry['mustContain'] = orig_title

                            # Build save path: "Season Year/Sanitized Title"
                            sanitized_title = sanitize_folder_name(orig_title)
                            new_save_path = os.path.join(season_year_folder, sanitized_title).replace('\\', '/')

                            entry['savePath'] = new_save_path

                            # Also set torrentParams.save_path for qBittorrent compatibility
                            if 'torrentParams' not in entry:
                                entry['torrentParams'] = {}
                            entry['torrentParams']['save_path'] = new_save_path

                            logger.debug(f"Set save path to: '{new_save_path}' (category path handled by qBit)")
                    else:
                        # Convert string entries to dict format with prefix
                        title = str(entry)
                        if title and not title.startswith(prefix):
                            items[i] = {
                                'node': {'title': prefix + title},
                                'mustContain': title
                            }
                except Exception as e:
                    logger.error(f"Error prefixing title {i}: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in prefix_titles_with_season_year: {e}")


def collect_invalid_folder_titles(all_titles: Dict[str, List]) -> List[Tuple[str, str, str]]:
    """
    Find all titles whose names would be invalid as filesystem folder names.

    Checks each title's mustContain value after sanitization against the
    user's configured filesystem type (Windows vs Linux).

    Args:
        all_titles: Dictionary of titles to check.

    Returns:
        A list of (display_name, raw_name, error_message) tuples for invalid titles.
    """
    invalid = []

    try:
        if not isinstance(all_titles, dict):
            return invalid

        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue

            for entry in items:
                try:
                    raw = ''
                    display = ''

                    if isinstance(entry, dict):
                        node = entry.get('node', {})
                        display = node.get('title') or entry.get('title') or ''
                        raw = entry.get('mustContain') or entry.get('title') or entry.get('name') or ''

                        # Try extracting raw title from "Season Year - Title" format
                        if display and isinstance(display, str) and ' - ' in display:
                            parts = display.split(' - ', 1)
                            if len(parts) == 2:
                                maybe_raw = parts[1]
                                if maybe_raw and not raw:
                                    raw = maybe_raw
                    else:
                        display = str(entry)
                        raw = display

                    if not raw:
                        continue

                    # Validate the sanitized version of the name
                    sanitized_raw = sanitize_folder_name(raw)
                    is_valid, reason = validate_folder_name_by_filesystem(sanitized_raw)
                    if not is_valid:
                        invalid.append((display or raw, raw, reason))

                except Exception as e:
                    logger.error(f"Error checking folder name: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in collect_invalid_folder_titles: {e}")

    return invalid


def auto_sanitize_titles(all_titles: Dict[str, List]) -> None:
    """
    Automatically sanitize folder-unsafe characters in all title names.

    Modifies entries in-place:
      - mustContain: sanitized directly
      - node.title: if it has a "Season Year - Title" prefix, only the
        title part (after " - ") is sanitized

    Args:
        all_titles: Dictionary of titles to sanitize.
    """
    try:
        if not isinstance(all_titles, dict):
            return

        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue

            for entry in items:
                try:
                    if isinstance(entry, dict):
                        # Sanitize mustContain
                        must_contain = entry.get('mustContain', '')
                        if must_contain:
                            entry['mustContain'] = sanitize_folder_name(must_contain)

                        # Sanitize the title portion of node.title (preserve prefix)
                        node = entry.get('node', {})
                        node_title = node.get('title', '')
                        if node_title and ' - ' in node_title:
                            parts = node_title.split(' - ', 1)
                            if len(parts) == 2:
                                prefix, raw = parts
                                node['title'] = f"{prefix} - {sanitize_folder_name(raw)}"
                                entry['node'] = node
                except Exception as e:
                    logger.error(f"Error sanitizing title: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in auto_sanitize_titles: {e}")


# ============================================================================
# DEFAULT FIELD POPULATION — Fill in missing rule fields with config defaults
# ============================================================================

def populate_missing_rule_fields(
    all_titles: Dict[str, List],
    season: str,
    year: str,
    apply_default_save_path: bool = True
) -> None:
    """
    Fill in missing fields in imported rule entries with sensible defaults.

    Newly imported titles often have only a display title and mustContain.
    This function adds the defaults from the user's config:
      - Default category (e.g. "Anime")
      - Default save path (e.g. "/downloads/anime")
      - Default affected feeds (which RSS feeds to watch)
      - Enabled state (True by default)
      - Empty torrentParams dict (required by qBittorrent)

    Modifies entries in-place. Only fills fields that are currently empty/missing.

    Args:
        all_titles: Dictionary of titles to populate.
        season: Current anime season (used if not provided).
        year: Current year (used if not provided).
        apply_default_save_path: If False, skip the save path default (useful
                                 when season/year prefixing will set it instead).
    """
    logger.debug(f"populate_missing_rule_fields called with {sum(len(v) for v in all_titles.values() if isinstance(v, list))} total titles")
    try:
        from src.utils import get_current_anime_season
        from src.config import config as cfg

        # Auto-detect season/year if not provided
        if not season or not year:
            year_val, season_val = get_current_anime_season()
            season = season or season_val
            year = year or str(year_val)

        # Load defaults from the user's config
        default_save_path = getattr(cfg, 'DEFAULT_SAVE_PATH', '') or ''
        default_category = getattr(cfg, 'DEFAULT_CATEGORY', '') or ''
        default_affected_feeds = getattr(cfg, 'DEFAULT_AFFECTED_FEEDS', []) or []

        for media_type, items in all_titles.items():
            if not isinstance(items, list):
                continue

            for entry in items:
                if not isinstance(entry, dict):
                    continue

                try:
                    # Ensure required internal fields exist
                    if 'node' not in entry:
                        entry['node'] = {}

                    if 'enabled' not in entry:
                        entry['enabled'] = True

                    # Set mustContain from title if missing
                    if not entry.get('mustContain'):
                        node = entry.get('node', {})
                        title = node.get('title') or entry.get('title', '')
                        if title:
                            entry['mustContain'] = title

                    # Apply default category if not already set
                    if not entry.get('assignedCategory') and default_category:
                        entry['assignedCategory'] = default_category
                        logger.debug(f"Applied default category '{default_category}' to {entry.get('mustContain', 'unknown')}")

                    # Apply default save path if not already set (and not skipped)
                    if apply_default_save_path and not entry.get('savePath') and default_save_path:
                        entry['savePath'] = default_save_path
                        logger.debug(f"Applied default save path '{default_save_path}' to {entry.get('mustContain', 'unknown')}")

                    # Apply default RSS feeds if not already set
                    if not entry.get('affectedFeeds') and default_affected_feeds:
                        entry['affectedFeeds'] = default_affected_feeds.copy()
                        logger.debug(f"Applied default affected feeds to {entry.get('mustContain', 'unknown')}")

                    # Ensure torrentParams exists and mirrors key fields
                    if 'torrentParams' not in entry:
                        entry['torrentParams'] = {}

                    if entry.get('assignedCategory'):
                        entry['torrentParams']['category'] = entry['assignedCategory']
                    if entry.get('savePath'):
                        entry['torrentParams']['save_path'] = entry['savePath']

                except Exception as e:
                    logger.error(f"Error populating fields: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error in populate_missing_rule_fields: {e}")


# ============================================================================
# CORE IMPORT PIPELINE — The main import orchestrator
# ============================================================================

def _import_titles_core(
    parsed_data: Dict[str, List],
    season: str,
    year: str,
    prefix_imports: bool,
    source_name: str = "import",
    auto_sanitize_override: Optional[bool] = None,
    skip_validation: bool = False,
) -> Tuple[bool, str, int, int]:
    """
    Core import pipeline — shared by file import, clipboard import, and recent file import.

    This is the main orchestrator that runs the full import pipeline:
      1. Optionally validate folder names (reject or auto-sanitize)
      2. Deduplicate against existing titles in config.ALL_TITLES
      3. Merge new (non-duplicate) entries into config.ALL_TITLES
      4. Populate missing fields with defaults
      5. Optionally prefix with season/year

    Only NEW entries (steps 4-5) get defaults and prefixing applied — existing
    entries in ALL_TITLES are left untouched.

    On catastrophic errors, the import still succeeds by directly assigning
    parsed_data to config.ALL_TITLES (fallback behavior).

    Args:
        parsed_data: Already-parsed and normalized titles dictionary.
        season: Season name for prefixing (e.g. "Spring").
        year: Year string for prefixing (e.g. "2026").
        prefix_imports: Whether to add season/year prefix to display titles.
        source_name: Label for status messages ("file", "clipboard", etc.).
        auto_sanitize_override: Override auto-sanitize preference (None = use config).
        skip_validation: If True, skip folder name validation entirely.

    Returns:
        A tuple of (success, status_message, new_count, duplicate_count).
        Returns ("validation_failed", 0, 0) if validation fails and can't auto-fix.
    """
    try:
        # Determine auto-sanitize behavior
        if auto_sanitize_override is None:
            try:
                auto_sanitize = bool(config.get_pref('auto_sanitize_imports', True))
            except Exception:
                auto_sanitize = True
        else:
            auto_sanitize = bool(auto_sanitize_override)

        # --- Step 1: Validate folder names ---
        if not skip_validation:
            invalid_titles = collect_invalid_folder_titles(parsed_data)

            if invalid_titles:
                if auto_sanitize:
                    # Try to fix invalid names automatically
                    auto_sanitize_titles(parsed_data)
                    invalid_titles = collect_invalid_folder_titles(parsed_data)

                if invalid_titles:
                    # Still invalid after sanitization — abort
                    return False, "validation_failed", 0, 0

        # --- Step 2: Build index of existing titles for deduplication ---
        current = getattr(config, 'ALL_TITLES', {}) or {}
        if not isinstance(current, dict):
            current = {}

        logger.debug(f"Import check: current ALL_TITLES has {sum(len(v) if isinstance(v, list) else 0 for v in current.values())} items")

        existing_titles = set()
        existing_must_contain = set()
        existing_rule_names = set()

        for k, lst in current.items():
            if not isinstance(lst, list):
                continue
            for it in lst:
                try:
                    if isinstance(it, dict):
                        t = (it.get('node') or {}).get('title') or it.get('ruleName') or it.get('name')
                        if t:
                            existing_titles.add(str(t))
                        must = it.get('mustContain')
                        if must:
                            existing_must_contain.add(str(must))
                        rule_name = it.get('ruleName') or it.get('name')
                        if rule_name:
                            existing_rule_names.add(str(rule_name))
                    else:
                        t = str(it)
                        existing_titles.add(t)
                except Exception:
                    pass

        # --- Step 3: Merge new entries, skipping duplicates ---
        new_items = {media_type: [] for media_type in parsed_data.keys() if isinstance(parsed_data.get(media_type), list)}
        new_count = 0

        for media_type, items in parsed_data.items():
            if not isinstance(items, list):
                continue
            if media_type not in current:
                current[media_type] = []

            for item in items:
                try:
                    if isinstance(item, dict):
                        title = (item.get('node') or {}).get('title') or item.get('ruleName') or item.get('name')
                        must = item.get('mustContain')
                        rule_name = item.get('ruleName') or item.get('name')
                    else:
                        title = str(item)
                        must = title
                        rule_name = title
                        # Convert string entries to proper dict format
                        item = {'node': {'title': title}, 'mustContain': must, 'ruleName': rule_name}

                    key = str(title) if title else None
                except (AttributeError, TypeError, ValueError):
                    logger.debug("Failed to parse imported item; skipping", exc_info=True)
                    key = None
                    must = None
                    rule_name = None

                # Check for duplicates across all three identity fields
                is_duplicate = False
                if key and key in existing_titles:
                    is_duplicate = True
                elif must and str(must) in existing_must_contain:
                    is_duplicate = True
                elif rule_name and str(rule_name) in existing_rule_names:
                    is_duplicate = True

                if not is_duplicate:
                    # Add to both the merged collection and the "new items only" tracker
                    current[media_type].append(item)
                    new_items[media_type].append(item)
                    # Update the dedup index so subsequent items in this batch are caught
                    if key:
                        existing_titles.add(key)
                    if must:
                        existing_must_contain.add(str(must))
                    if rule_name:
                        existing_rule_names.add(str(rule_name))
                    new_count += 1

        # --- Step 4: Update config and compute stats ---
        config.ALL_TITLES = current
        total_imported = sum(len(v) for v in parsed_data.values() if isinstance(v, list))
        duplicates = total_imported - new_count

        total_in_all_titles = sum(len(v) for v in current.values() if isinstance(v, list))
        logger.info(f"Import merge complete: {new_count} new, {duplicates} duplicates, total in ALL_TITLES: {total_in_all_titles}")

        # --- Step 5: Apply defaults and prefixing to NEW items only ---
        try:
            prefix_feature_enabled = bool(config.get_pref('prefix_imports', True))
        except Exception:
            prefix_feature_enabled = True
        effective_prefix_imports = bool(prefix_imports and prefix_feature_enabled)

        if new_items:
            # Populate defaults (category, save path, feeds) for new entries only
            logger.debug(f"Populating fields for {sum(len(v) for v in new_items.values())} new items only")
            populate_missing_rule_fields(new_items, season, year, apply_default_save_path=not effective_prefix_imports)

            # Add season/year prefix to new entries only (if enabled)
            if effective_prefix_imports:
                logger.debug(f"Applying prefix to {sum(len(v) for v in new_items.values())} new items only")
                prefix_titles_with_season_year(new_items, season, year)

        # Build status message
        status_msg = f'Imported {new_count} new titles from {source_name}.'
        if duplicates > 0:
            status_msg += f' ({duplicates} duplicates skipped)'

        return True, status_msg, new_count, duplicates

    except Exception as e:
        # Catastrophic error fallback — still import what we can
        logger.error(f"Error in core import logic: {e}")
        config.ALL_TITLES = parsed_data
        status_msg = f'Imported {sum(len(v) for v in parsed_data.values())} titles from {source_name}.'
        return True, status_msg, sum(len(v) for v in parsed_data.values()), 0
