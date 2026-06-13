"""
RSS Rules Management Module — Core Data Model.

This module defines the RSSRule dataclass, which is the central representation
of a qBittorrent RSS auto-download rule in the application. Think of it as the
"blueprint" for a rule: it knows what fields qBittorrent expects, how to convert
between Python and qBittorrent's JSON format, and how to validate itself.

Key responsibilities:
  - RSSRule dataclass: The immutable-ish data structure for a single rule
  - Rule creation: Factory functions with sensible defaults
  - Save path generation: Building folder paths from title + season + year
  - Import/Export: Reading and writing rules as JSON files
  - Validation: Checking that rules have all required fields
  - Sanitization: Cleaning rule names so they work as filesystem folder names

INTERNAL FORMAT NOTE:
    The app uses a "hybrid" format for title entries in the GUI — each entry
    contains both qBittorrent fields (mustContain, savePath, etc.) AND internal
    tracking fields ('node', 'ruleName') used for display purposes. These
    internal fields MUST be filtered out before:
      - Exporting to JSON files
      - Previewing rules in the UI
      - Syncing rules to the qBittorrent server
    See config.py ALL_TITLES for the full format documentation.
"""

# Standard library imports
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Local application imports
from src.config import config
from src.constants import Season
from src.utils import (
    sanitize_folder_name,
    validate_folder_name,
)

logger = logging.getLogger(__name__)


@dataclass
class RSSRule:
    """
    Represents a single qBittorrent RSS auto-download rule.

    This maps 1:1 to qBittorrent's internal rule structure. When a new RSS feed
    item matches the rule's 'mustContain' pattern (and doesn't match 'mustNotContain'),
    qBittorrent will automatically download it to the specified save path.

    The dataclass can be created from scratch (for new rules) or hydrated from
    a qBittorrent JSON dict (for existing rules fetched from the server).

    Field categories:
      - Required: title, must_contain (what to match)
      - Paths: save_path, feed_url, category (where to save and what to watch)
      - Behavior flags: enabled, smart_filter, use_regex, add_paused, etc.
      - Speed/ratio limits: download_limit, upload_limit, ratio_limit, etc.
      - Tracking: previously_matched, last_match (managed by qBittorrent)
    """

    # --- Core fields ---
    title: str                                          # Display name for the rule (also used as rule key)
    must_contain: str = ""                              # Pattern that RSS titles must match to trigger download
    save_path: str = ""                                 # Relative path where downloaded files are saved
    feed_url: str = ""                                  # RSS feed URL this rule watches
    category: str = ""                                  # qBittorrent category to assign (e.g. "Anime")

    # --- Behavior flags ---
    add_paused: bool = False                            # If True, add torrent in paused state (don't start downloading)
    enabled: bool = True                                # If False, rule exists but won't match anything
    smart_filter: bool = False                          # If True, use qBittorrent's smart episode filter
    use_regex: bool = False                             # If True, must_contain is treated as a regex pattern
    skip_checking: bool = False                         # If True, skip hash checking after download
    use_auto_tmm: bool = False                          # If True, use Automatic Torrent Management for save path

    # --- Optional text fields ---
    episode_filter: str = ""                            # Episode number filter (e.g. "1-12" or "1x01-1x12")
    last_match: str = ""                                # Timestamp of the last time this rule matched (set by qBittorrent)
    must_not_contain: str = ""                          # Pattern that RSS titles must NOT match (exclusion filter)
    torrent_content_layout: Optional[str] = None        # How to arrange files: None (default), "Original", "Subfolder", etc.
    operating_mode: str = "AutoManaged"                 # Torrent operating mode
    share_limit_action: str = "Default"                 # What to do when share ratio limit is reached

    # --- Speed and ratio limits ---
    # Values of -1 mean "use global setting", -2 means "use category setting"
    ignore_days: int = 0                                # Days to ignore duplicate matches
    priority: int = 0                                   # Download priority (0 = normal)
    download_limit: int = -1                            # Download speed limit in bytes/sec (-1 = global)
    upload_limit: int = -1                              # Upload speed limit in bytes/sec (-1 = global)
    ratio_limit: int = -2                               # Share ratio limit (-2 = category default)
    seeding_time_limit: int = -2                        # Max seeding time in minutes (-2 = category default)
    inactive_seeding_time_limit: int = -2               # Max inactive seeding time (-2 = category default)

    # --- List fields ---
    previously_matched: List[str] = field(default_factory=list)  # Episode hashes already matched (prevents re-downloading)
    tags: List[str] = field(default_factory=list)                # Tags to assign to downloaded torrents

    def __post_init__(self) -> None:
        """
        Auto-fill and normalize values after the dataclass is created.

        - If must_contain is empty, default it to the title (most rules match by title)
        - Normalize save paths to use forward slashes (qBittorrent uses Unix-style paths)
        """
        if not self.must_contain:
            self.must_contain = self.title

        if self.save_path:
            self.save_path = self.save_path.replace('\\', '/')

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert this rule to the JSON dictionary format that qBittorrent expects.

        qBittorrent uses camelCase keys (e.g. 'mustContain', 'savePath') and nests
        speed/ratio limits inside a 'torrentParams' sub-object. This method handles
        all that formatting.

        Returns:
            A dictionary matching qBittorrent's RSS rule schema, ready to be
            JSON-encoded and sent to the API.
        """
        return {
            "addPaused": self.add_paused,
            "affectedFeeds": [self.feed_url] if self.feed_url else [],
            "assignedCategory": self.category,
            "enabled": self.enabled,
            "episodeFilter": self.episode_filter,
            "ignoreDays": self.ignore_days,
            "lastMatch": self.last_match or None,
            "mustContain": self.must_contain,
            "mustNotContain": self.must_not_contain,
            "previouslyMatchedEpisodes": self.previously_matched,
            "priority": self.priority,
            "savePath": self.save_path,
            "smartFilter": self.smart_filter,
            "torrentContentLayout": self.torrent_content_layout,
            # Nested torrent parameters — these control per-torrent behavior
            "torrentParams": {
                "category": self.category,
                "download_limit": self.download_limit,
                "download_path": "",
                "inactive_seeding_time_limit": self.inactive_seeding_time_limit,
                "operating_mode": self.operating_mode,
                "ratio_limit": self.ratio_limit,
                "save_path": self.save_path,
                "seeding_time_limit": self.seeding_time_limit,
                "share_limit_action": self.share_limit_action,
                "skip_checking": self.skip_checking,
                "ssl_certificate": "",          # Unused but required by qBittorrent schema
                "ssl_dh_params": "",             # Unused but required by qBittorrent schema
                "ssl_private_key": "",           # Unused but required by qBittorrent schema
                "stopped": False,
                "tags": self.tags,
                "upload_limit": self.upload_limit,
                "use_auto_tmm": self.use_auto_tmm
            },
            "useRegex": self.use_regex
        }

    @classmethod
    def from_dict(cls, title: str, rule_dict: Dict[str, Any]) -> 'RSSRule':
        """
        Create an RSSRule from a qBittorrent-format dictionary.

        This is the reverse of to_dict() — it takes a dictionary (either from
        the qBittorrent API or from a JSON file) and creates an RSSRule object.

        Args:
            title: The rule name/title (used as the display name).
            rule_dict: A dictionary containing rule fields in qBittorrent format.

        Returns:
            A new RSSRule instance populated from the dictionary.
        """
        # affectedFeeds is a list of feed URLs; we only use the first one
        feeds = rule_dict.get('affectedFeeds', [])
        feed_url = feeds[0] if feeds else ""

        # Speed/ratio limits are nested inside torrentParams
        params = rule_dict.get('torrentParams', {})

        return cls(
            title=title,
            must_contain=rule_dict.get('mustContain', title),
            save_path=rule_dict.get('savePath', ''),
            feed_url=feed_url,
            category=rule_dict.get('assignedCategory', ''),
            # Behavior flags
            add_paused=rule_dict.get('addPaused', False),
            enabled=rule_dict.get('enabled', True),
            episode_filter=rule_dict.get('episodeFilter', ''),
            ignore_days=rule_dict.get('ignoreDays', 0),
            last_match=rule_dict.get('lastMatch', '') or '',
            must_not_contain=rule_dict.get('mustNotContain', ''),
            previously_matched=rule_dict.get('previouslyMatchedEpisodes', []),
            priority=rule_dict.get('priority', 0),
            smart_filter=rule_dict.get('smartFilter', False),
            use_regex=rule_dict.get('useRegex', False),
            torrent_content_layout=rule_dict.get('torrentContentLayout'),
            # Speed/ratio limits from torrentParams
            download_limit=params.get('download_limit', -1),
            upload_limit=params.get('upload_limit', -1),
            ratio_limit=params.get('ratio_limit', -2),
            seeding_time_limit=params.get('seeding_time_limit', -2),
            inactive_seeding_time_limit=params.get('inactive_seeding_time_limit', -2),
            operating_mode=params.get('operating_mode', 'AutoManaged'),
            share_limit_action=params.get('share_limit_action', 'Default'),
            skip_checking=params.get('skip_checking', False),
            use_auto_tmm=params.get('use_auto_tmm', False),
            tags=params.get('tags', [])
        )

    def validate(self) -> Tuple[bool, str]:
        """
        Check that this rule has all the required fields to work correctly.

        A valid rule needs at minimum:
          - A mustContain pattern (what to search for in RSS feed titles)
          - At least one RSS feed URL (where to look for matching items)
          - A valid save path (if one is specified)

        Returns:
            A tuple of (is_valid, message). If invalid, the message explains why.
        """
        if not self.must_contain:
            return False, "Rule must have a 'mustContain' pattern"

        if not self.feed_url:
            return False, "Rule must have at least one RSS feed"

        if self.save_path:
            is_valid, error_msg = validate_folder_name(self.save_path)
            if not is_valid:
                return False, f"Invalid save path: {error_msg}"

        return True, "Valid"


# ============================================================================
# Rule Factory Functions
# ============================================================================

def create_rule(title: str, must_contain: str = "", save_path: str = "",
                feed_url: str = "", category: str = "") -> RSSRule:
    """
    Create a new RSS rule with sensible defaults.

    This is the preferred way to create a new rule from scratch. It fills in
    the default RSS feed URL from the app's config if none is specified.

    Args:
        title: The display title and default match pattern for the rule.
        must_contain: Custom match pattern (defaults to title if empty).
        save_path: Relative download directory path.
        feed_url: RSS feed URL to watch (defaults to the app's configured default feed).
        category: qBittorrent category to assign to matched torrents.

    Returns:
        A new RSSRule instance ready to use.
    """
    return RSSRule(
        title=title,
        must_contain=must_contain or title,
        save_path=save_path,
        feed_url=feed_url or config.DEFAULT_RSS_FEED,
        category=category
    )


# ============================================================================
# Save Path Construction
# ============================================================================

def build_save_path(title: str, season: Optional[str] = None,
                   year: Optional[str] = None,
                   category: Optional[str] = None) -> str:
    """
    Build a relative save path for a rule based on the title and season/year.

    The generated path structure depends on user preferences:
      - With season/year prefix enabled: "Spring 2026/Attack on Titan"
      - Without prefix:                  "Attack on Titan"

    The path is kept RELATIVE (not absolute) because qBittorrent composes
    the final download location by concatenating:
      default_download_path + category_save_path + rule_save_path

    The title is sanitized to remove characters that are invalid in folder names.

    Args:
        title: The anime/show title.
        season: Optional season name (e.g. "Spring", "Fall").
        year: Optional year string (e.g. "2026").
        category: Optional qBittorrent category (reserved for future use).

    Returns:
        A relative path string with forward slashes (e.g. "Spring 2026/My Show").
    """
    try:
        sanitized = sanitize_folder_name(title)

        # Check if the user wants season/year prefixes on their save paths
        try:
            season_year_prefix_enabled = bool(config.get_pref('prefix_imports', True))
        except Exception:
            season_year_prefix_enabled = True

        # Build the path: optionally prefix with "Season Year/" folder
        rule_segment = os.path.join(f"{season} {year}", sanitized) if (season_year_prefix_enabled and season and year) else sanitized
        # Always use forward slashes (qBittorrent convention, works on all platforms)
        return rule_segment.replace('\\', '/')

    except Exception as e:
        logger.warning(f"Failed to build save path for '{title}': {e}")
        return title  # Fallback: just use the raw title


# ============================================================================
# Title Entry Parsing
# ============================================================================

def parse_title_metadata(entry: Any) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Extract display info from a title entry in the user's library.

    Title entries can be either:
      - A dict (from the GUI): has 'node.title', 'mustContain', 'season', 'year'
      - A plain string (simple import): the string is used as both title and name

    Args:
        entry: A title entry — either a dict or a string.

    Returns:
        A tuple of (display_title, raw_name, season, year) where:
          display_title — what the user sees in the GUI
          raw_name      — the actual match pattern (mustContain)
          season        — anime season if available, else None
          year          — year if available, else None
    """
    if isinstance(entry, dict):
        node = entry.get('node', {})
        # Try multiple fields for the display title, in priority order
        display_title = node.get('title') or entry.get('title') or entry.get('mustContain', '')
        raw_name = entry.get('mustContain') or display_title
        return display_title, raw_name, entry.get('season'), entry.get('year')

    # Plain string entry — use as both title and name
    display_title = raw_name = str(entry)
    return display_title, raw_name, None, None


# ============================================================================
# Bulk Rule Building
# ============================================================================

def build_rules_from_titles(titles: Dict[str, List[Any]],
                            default_feed: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Convert the user's title library into qBittorrent-compatible rule dicts.

    This is the main function that transforms the internal title format
    (used by the GUI) into the external rule format (used by qBittorrent).
    It processes all titles across all media types and generates a complete
    rules dictionary ready for export or syncing.

    For each title entry, it:
      1. Parses the entry to extract title, season, year
      2. Sanitizes the title for use as a folder name
      3. Determines the save path (from entry or auto-generated)
      4. Creates an RSSRule (from existing data or fresh)
      5. Converts to qBittorrent dict format

    Args:
        titles: The user's title library, organized by media type.
                Format: {"anime": [entry1, entry2, ...], "manga": [...]}
        default_feed: RSS feed URL to use when entries don't specify one.

    Returns:
        A dictionary mapping rule names to their qBittorrent-format definitions.
    """
    if not isinstance(titles, dict):
        return {}

    rules = {}
    feed = default_feed or config.DEFAULT_RSS_FEED

    for media_type, items in titles.items():
        if not isinstance(items, list):
            continue

        for entry in items:
            try:
                # Step 1: Extract title metadata from the entry
                display_title, raw_name, season, year = parse_title_metadata(entry)

                # Step 2: Sanitize the title so it's safe to use as a folder name
                try:
                    sanitized = sanitize_folder_name(raw_name)
                except Exception:
                    sanitized = raw_name

                # Step 3: Get the category (used in save path generation)
                category = entry.get('assignedCategory', '') if isinstance(entry, dict) else ''

                # Step 4: Determine save path — use existing one or generate a new one
                if isinstance(entry, dict):
                    save_path = entry.get('savePath') or entry.get('save_path')
                    if not save_path:
                        # No save path specified in the entry — generate a default
                        save_path = build_save_path(sanitized, season, year, category)
                else:
                    save_path = build_save_path(sanitized, season, year)

                # Step 5: Get the RSS feed URL
                if isinstance(entry, dict):
                    feeds = entry.get('affectedFeeds', [])
                    entry_feed = feeds[0] if feeds else feed
                else:
                    entry_feed = feed

                # Step 6: Create the RSSRule object
                if isinstance(entry, dict):
                    # Entry already has rule data — hydrate from dict
                    rule = RSSRule.from_dict(display_title, entry)
                    # Only override save_path if the entry didn't have one
                    if not entry.get('savePath') and not entry.get('save_path'):
                        rule.save_path = save_path
                    # Only override must_contain if the entry didn't specify one
                    if not entry.get('mustContain'):
                        rule.must_contain = sanitized
                else:
                    # New entry (string) — create a fresh rule
                    rule = create_rule(
                        title=display_title,
                        must_contain=sanitized,
                        save_path=save_path,
                        feed_url=entry_feed,
                        category=category
                    )

                # Step 7: Convert to qBittorrent format and add to results
                rules[display_title] = rule.to_dict()

            except Exception as e:
                logger.error(f"Failed to build rule for entry: {e}")
                continue

    return rules


# ============================================================================
# JSON Import / Export
# ============================================================================

def export_rules_to_json(rules: Dict[str, Dict[str, Any]],
                         output_path: str) -> Tuple[bool, str]:
    """
    Save a rules dictionary to a JSON file on disk.

    Creates parent directories automatically if they don't exist.

    Args:
        rules: The rules dictionary to export.
        output_path: File path where the JSON file should be written.

    Returns:
        A tuple of (success: bool, message: str).
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(rules)} rules to {output_path}")
        return True, f"Successfully exported {len(rules)} rules"

    except Exception as e:
        logger.error(f"Failed to export rules: {e}")
        return False, f"Export failed: {e}"


def import_rules_from_json(input_path: str) -> Tuple[bool, Any]:
    """
    Load rules from a JSON file on disk.

    Validates that the parsed data is a dictionary (the expected format for
    a rules collection). Individual rule validation should be done separately
    using validate_rules().

    Args:
        input_path: File path to the JSON file to import.

    Returns:
        A tuple of (success: bool, result).
        On success: (True, rules_dict)
        On failure: (False, error_message_string)
    """
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            rules = json.load(f)

        if not isinstance(rules, dict):
            return False, "Invalid rules format: expected dictionary"

        logger.info(f"Imported {len(rules)} rules from {input_path}")
        return True, rules

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        logger.error(f"Failed to import rules: {e}")
        return False, f"Import failed: {e}"


# ============================================================================
# Validation and Sanitization
# ============================================================================

def validate_rules(rules: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Validate every rule in a rules dictionary and report any problems.

    Hydrates each rule dict into an RSSRule object and runs its validate()
    method. Returns a list of errors — an empty list means all rules are valid.

    Args:
        rules: Dictionary mapping rule names to their definition dicts.

    Returns:
        A list of (rule_name, error_message) tuples for each invalid rule.
        Empty list if all rules are valid.
    """
    errors = []

    for rule_name, rule_dict in rules.items():
        try:
            rule = RSSRule.from_dict(rule_name, rule_dict)
            is_valid, error_msg = rule.validate()

            if not is_valid:
                errors.append((rule_name, error_msg))

        except Exception as e:
            errors.append((rule_name, f"Failed to parse rule: {e}"))

    return errors


def sanitize_rules(rules: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Clean up all rules so their titles and save paths are valid folder names.

    This processes each rule to:
      1. Sanitize the mustContain field (remove/replace invalid filesystem chars)
      2. Sanitize each segment of the save path individually

    If sanitization fails for a rule, the original (unsanitized) version is
    kept rather than dropping the rule entirely.

    Args:
        rules: Dictionary of rules to sanitize.

    Returns:
        A new dictionary with all rules sanitized.
    """
    sanitized = {}

    for rule_name, rule_dict in rules.items():
        try:
            rule = RSSRule.from_dict(rule_name, rule_dict)

            # Clean the match pattern (it's often used as a folder name too)
            if rule.must_contain:
                rule.must_contain = sanitize_folder_name(rule.must_contain)

            # Clean each segment of the save path separately
            # e.g. "Spring 2026/My:Show" → "Spring 2026/My Show"
            if rule.save_path:
                path_parts = rule.save_path.split('/')
                sanitized_parts = [sanitize_folder_name(part) for part in path_parts if part]
                rule.save_path = '/'.join(sanitized_parts)

            sanitized[rule_name] = rule.to_dict()

        except Exception as e:
            logger.warning(f"Failed to sanitize rule '{rule_name}': {e}")
            sanitized[rule_name] = rule_dict  # Keep the original if sanitization fails

    return sanitized


# Public API
__all__ = [
    'RSSRule',
    'create_rule',
    'build_save_path',
    'parse_title_metadata',
    'build_rules_from_titles',
    'export_rules_to_json',
    'import_rules_from_json',
    'validate_rules',
    'sanitize_rules',
]
