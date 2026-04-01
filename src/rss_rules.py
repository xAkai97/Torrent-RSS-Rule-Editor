"""RSS Rules Management Module

This module handles the creation, validation, and management of qBittorrent
RSS auto-download rules. It provides functionality for:
- Creating rule definitions
- Building save paths
- Sanitizing titles
- Exporting rules to JSON
- Validating rule configurations

Internal Format Note:
    The application uses a hybrid format where title entries contain both qBittorrent
    fields AND internal tracking fields ('node', 'ruleName'). These internal fields
    are used for display purposes in the GUI but must be filtered out before:
    - Exporting to JSON files
    - Previewing rules
    - Syncing to qBittorrent
    
    See config.py ALL_TITLES for the full format documentation.

Phase 5: RSS Rule Management
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
    Represents a qBittorrent RSS auto-download rule.
    
    This class encapsulates all the fields and logic for a single RSS rule,
    making it easier to create, modify, and validate rules.
    """
    # Required fields
    title: str
    must_contain: str = ""
    save_path: str = ""
    feed_url: str = ""
    category: str = ""
    
    # Optional boolean flags
    add_paused: bool = False
    enabled: bool = True
    smart_filter: bool = False
    use_regex: bool = False
    skip_checking: bool = False
    use_auto_tmm: bool = False
    
    # Optional string fields
    episode_filter: str = ""
    last_match: str = ""
    must_not_contain: str = ""
    torrent_content_layout: Optional[str] = None
    operating_mode: str = "AutoManaged"
    share_limit_action: str = "Default"
    
    # Optional numeric fields
    ignore_days: int = 0
    priority: int = 0
    download_limit: int = -1
    upload_limit: int = -1
    ratio_limit: int = -2
    seeding_time_limit: int = -2
    inactive_seeding_time_limit: int = -2
    
    # List fields
    previously_matched: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Normalize values after initialization."""
        # Set must_contain to title if empty
        if not self.must_contain:
            self.must_contain = self.title
        
        # Normalize save path to forward slashes
        if self.save_path:
            self.save_path = self.save_path.replace('\\', '/')
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert rule to qBittorrent API dictionary format.
        
        Returns:
            dict: Complete rule definition matching qBittorrent's schema
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
                "ssl_certificate": "",
                "ssl_dh_params": "",
                "ssl_private_key": "",
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
        Create RSSRule from dictionary.
        
        Args:
            title: Rule title
            rule_dict: Dictionary containing rule configuration
            
        Returns:
            RSSRule: New rule instance
        """
        feeds = rule_dict.get('affectedFeeds', [])
        feed_url = feeds[0] if feeds else ""
        
        # Extract torrent params
        params = rule_dict.get('torrentParams', {})
        
        return cls(
            title=title,
            must_contain=rule_dict.get('mustContain', title),
            save_path=rule_dict.get('savePath', ''),
            feed_url=feed_url,
            category=rule_dict.get('assignedCategory', ''),
            # Optional fields
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
            # Torrent params
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
        Validate the rule configuration.
        
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
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


def create_rule(title: str, must_contain: str = "", save_path: str = "",
                feed_url: str = "", category: str = "") -> RSSRule:
    """
    Create a new RSS rule with sensible defaults.
    
    Args:
        title: Display title
        must_contain: Pattern to match (defaults to title)
        save_path: Download location
        feed_url: RSS feed URL
        category: qBittorrent category
        
    Returns:
        RSSRule: New rule instance
    """
    return RSSRule(
        title=title,
        must_contain=must_contain or title,
        save_path=save_path,
        feed_url=feed_url or config.DEFAULT_RSS_FEED,
        category=category
    )


def build_save_path(title: str, season: Optional[str] = None,
                   year: Optional[str] = None,
                   category: Optional[str] = None) -> str:
    """
    Generate a save path for a title based on season and year.
    
    Args:
        title: Title name
        season: Optional season (Winter, Spring, Summer, Fall)
        year: Optional year
        category: Optional qBittorrent category name (reserved for compatibility)
        
    Returns:
        str: Relative save path with forward slashes
    """
    try:
        sanitized = sanitize_folder_name(title)

        # Keep rule save paths relative so qBittorrent can compose
        # default download path + category save_path + rule savePath.
        rule_segment = os.path.join(f"{season} {year}", sanitized) if (season and year) else sanitized
        return rule_segment.replace('\\', '/')
        
    except Exception as e:
        logger.warning(f"Failed to build save path for '{title}': {e}")
        return title


def parse_title_metadata(entry: Any) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Extract title metadata from an entry.
    
    Args:
        entry: Title entry (dict or string)
        
    Returns:
        Tuple[str, str, Optional[str], Optional[str]]: 
            (display_title, raw_name, season, year)
    """
    if isinstance(entry, dict):
        node = entry.get('node', {})
        display_title = node.get('title') or entry.get('title') or entry.get('mustContain', '')
        raw_name = entry.get('mustContain') or display_title
        return display_title, raw_name, entry.get('season'), entry.get('year')
    
    display_title = raw_name = str(entry)
    return display_title, raw_name, None, None


def build_rules_from_titles(titles: Dict[str, List[Any]], 
                            default_feed: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Build a complete rules dictionary from titles.
    
    Converts internal title structure into qBittorrent-compatible format.
    
    Args:
        titles: Dictionary of titles organized by media type
        default_feed: Default RSS feed URL to use
        
    Returns:
        dict: Rules dictionary ready for export
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
                # Parse entry metadata
                display_title, raw_name, season, year = parse_title_metadata(entry)
                
                # Sanitize title for folder name
                try:
                    sanitized = sanitize_folder_name(raw_name)
                except Exception:
                    sanitized = raw_name
                
                # Get category early (used by default save path generation)
                category = entry.get('assignedCategory', '') if isinstance(entry, dict) else ''

                # Get save path from entry, or build default if not present
                if isinstance(entry, dict):
                    save_path = entry.get('savePath') or entry.get('save_path')
                    if not save_path:
                        # Build default save path only if not specified
                        save_path = build_save_path(sanitized, season, year, category)
                else:
                    # Build default save path for non-dict entries
                    save_path = build_save_path(sanitized, season, year)
                
                # Get feed URL
                if isinstance(entry, dict):
                    feeds = entry.get('affectedFeeds', [])
                    entry_feed = feeds[0] if feeds else feed
                else:
                    entry_feed = feed
                
                # Create rule
                if isinstance(entry, dict):
                    # Load from existing dict
                    rule = RSSRule.from_dict(display_title, entry)
                    # Update save_path if it was just computed (not from entry)
                    if not entry.get('savePath') and not entry.get('save_path'):
                        rule.save_path = save_path
                    # Update must_contain to sanitized version if needed
                    if not entry.get('mustContain'):
                        rule.must_contain = sanitized
                else:
                    # Create new rule
                    rule = create_rule(
                        title=display_title,
                        must_contain=sanitized,
                        save_path=save_path,
                        feed_url=entry_feed,
                        category=category
                    )
                
                # Add to rules dict
                rules[display_title] = rule.to_dict()
                
            except Exception as e:
                logger.error(f"Failed to build rule for entry: {e}")
                continue
    
    return rules


def export_rules_to_json(rules: Dict[str, Dict[str, Any]], 
                         output_path: str) -> Tuple[bool, str]:
    """
    Export rules to JSON file.
    
    Args:
        rules: Rules dictionary
        output_path: Path to output JSON file
        
    Returns:
        Tuple[bool, str]: (success, message)
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
    Import rules from JSON file.
    
    Args:
        input_path: Path to JSON file
        
    Returns:
        Tuple[bool, Any]: (success, rules_dict or error_message)
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


def validate_rules(rules: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Validate all rules in a rules dictionary.
    
    Args:
        rules: Dictionary of rules to validate
        
    Returns:
        List[Tuple[str, str]]: List of (rule_name, error_message) for invalid rules
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
    Sanitize all mustContain fields in rules to be valid folder names.
    
    Args:
        rules: Dictionary of rules
        
    Returns:
        dict: Sanitized rules dictionary
    """
    sanitized = {}
    
    for rule_name, rule_dict in rules.items():
        try:
            # Create rule object
            rule = RSSRule.from_dict(rule_name, rule_dict)
            
            # Sanitize must_contain
            if rule.must_contain:
                rule.must_contain = sanitize_folder_name(rule.must_contain)
            
            # Sanitize save_path components
            if rule.save_path:
                path_parts = rule.save_path.split('/')
                sanitized_parts = [sanitize_folder_name(part) for part in path_parts if part]
                rule.save_path = '/'.join(sanitized_parts)
            
            sanitized[rule_name] = rule.to_dict()
            
        except Exception as e:
            logger.warning(f"Failed to sanitize rule '{rule_name}': {e}")
            sanitized[rule_name] = rule_dict
    
    return sanitized


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
