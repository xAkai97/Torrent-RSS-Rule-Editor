# Backup/Restore Feature Requirements

## 1. Current Export/Import Capability

### Export Functionality
- **Format**: JSON
- **Location**: [src/gui/file_operations.py](src/gui/file_operations.py#L1326) - `export_selected_titles()` and `export_all_titles()`
- **What's Exported**: 
  - Rules dictionary with qBittorrent-compatible format (name → rule definition)
  - Individual rule entries with all fields (mustContain, savePath, category, etc.)
  - Internal tracking fields stripped during export (node, ruleName)

### Import Functionality
- **Format**: JSON or CSV
- **Location**: [src/gui/file_operations.py](src/gui/file_operations.py#L1119) - `import_titles_from_file()` 
- **Also Supports**:
  - Clipboard paste: `import_titles_from_clipboard()`
  - Drag & drop: setup in [src/gui/main_window.py](src/gui/main_window.py#L901)
  - Recent files: tracked in config.RECENT_FILES
- **Features**:
  - Pre-import sanitization check (validation dialog)
  - Duplicate detection by title, mustContain, and ruleName
  - Auto-sanitization of folder names
  - CSV to JSON conversion
  - Prefix with season/year option

### Current Workflow
1. User creates rules in GUI (title, savePath, category, etc.)
2. User clicks "Generate Rules" → chooses:
   - **Export to JSON** (offline): `export_all_titles()` → saves to user-selected file
   - **Sync to qBittorrent** (online): `dispatch_generation()` → preview → apply to qBittorrent
3. Sync process: validate → build qBittorrent format → show preview → sync to API

**NOTE**: Currently NO backup mechanism for existing qBittorrent rules before sync/overwrite.

---

## 2. Data Structure - "qBittorrent Rules Snapshot"

### RSSRule Dataclass
Located in [src/rss_rules.py](src/rss_rules.py#L1)

```python
@dataclass
class RSSRule:
    # Required
    title: str
    must_contain: str = ""
    save_path: str = ""
    feed_url: str = ""
    category: str = ""
    
    # Boolean flags
    add_paused: bool = False
    enabled: bool = True
    smart_filter: bool = False
    use_regex: bool = False
    skip_checking: bool = False
    use_auto_tmm: bool = False
    
    # String fields
    episode_filter: str = ""
    last_match: str = ""
    must_not_contain: str = ""
    torrent_content_layout: Optional[str] = None
    operating_mode: str = "AutoManaged"
    share_limit_action: str = "Default"
    
    # Numeric fields
    ignore_days: int = 0
    priority: int = 0
    download_limit: int = -1
    upload_limit: int = -1
    ratio_limit: int = -2
    seeding_time_limit: int = -2
    inactive_seeding_time_limit: int = -2
    
    # List fields
    previously_matched: List[str] = []
    tags: List[str] = []
```

### Internal All_Titles Structure
From [src/config.py](src/config.py#L1) - `config.ALL_TITLES`

```python
# Hybrid format with both qBittorrent fields AND internal tracking fields
{
  'anime': [  # or 'manga', 'existing', etc.
    {
      # qBittorrent fields (exported)
      'mustContain': 'Rule Title',
      'savePath': '/path/to/save',
      'assignedCategory': 'Category',
      'enabled': True,
      'affectedFeeds': ['url'],
      'torrentParams': {...},
      'useRegex': False,
      # Internal tracking fields (FILTERED during export)
      'node': {'title': 'Display Title'},
      'ruleName': 'Title'
    }
  ]
}
```

### What a Snapshot Should Include

A complete qBittorrent **rules snapshot** should capture:

1. **RSS Rules Dictionary**
   - Rule name → complete RSSRule definition
   - All rule fields maintained
   - Feed URLs, categories, filters, limits

2. **Categories** (Optional but recommended)
   - Category name → settings
   - Fetched via: `qbt_api.get_categories()` → [src/qbittorrent_api.py](src/qbittorrent_api.py#L300)

3. **RSS Feeds** (Optional but recommended)
   - Feed URLs and metadata
   - Fetched via: `qbt_api.get_feeds()` → [src/qbittorrent_api.py](src/qbittorrent_api.py#L320)

4. **Metadata**
   - Backup timestamp
   - qBittorrent version (from `qbt_api.get_version()`)
   - Application version
   - Sync mode used (replace vs add)
   - Filesystem validation rules applied (Windows vs Unix/Linux)

---

## 3. API Interactions for Rule Retrieval

### Fetch Operations
Located in [src/qbittorrent_api.py](src/qbittorrent_api.py)

```python
# Get all RSS rules (as dict of {name: ruleDef})
success, rules = qbt_api.fetch_rules(
    protocol, host, port, username, password,
    verify_ssl=True, ca_cert=None, timeout=10
)
# Returns: Tuple[bool, Union[str, Dict]]

# Get all categories
qbt_api.fetch_categories(protocol, host, port, ...)
# Returns: Dict[str, Any]

# Get all feeds
qbt_api.fetch_feeds(protocol, host, port, ...)
# Returns: Dict[str, Any]

# Get application preferences
client.get_preferences()
# Returns: Dict with save_path, download_path, etc.
```

### Sync/Apply Operations

```python
# QBittorrentClient methods:
client.set_rule(rule_name: str, rule_def: Dict[str, Any]) → bool
client.remove_rule(rule_name: str) → bool
client.add_feed(feed_url: str, feed_name: Optional[str] = None) → bool
client.get_version() → str
```

### Current Sync Workflow
From [src/gui/file_operations.py](src/gui/file_operations.py#L1716) - `dispatch_generation()`

1. **Build rules** from CLI all_titles: `build_rules_from_titles(clean_titles)`
2. **Show preview** dialog with validation
3. **Choose sync mode**: Replace All vs Add/Update Only
4. **If Replace mode**:
   - Fetch existing rules from qBittorrent
   - Remove all old rules
   - Add new rules
5. **If Add mode**:
   - Fetch existing rules (for duplicate detection)
   - Only add/update rules that don't exist
6. **Report results**: success/failed counts

**NONE of this includes backup preservation!**

---

## 4. File Operations Handling

### Current File Operations
Located in [src/gui/file_operations.py](src/gui/file_operations.py#L1)

**Export Functions**:
- `export_selected_titles()` → JSON file dialog
- `export_all_titles()` → JSON file dialog
- Both use `json.dump()` with indent=4

**Import Functions**:
- `import_titles_from_file(path)` → filedialog or explicit path
- `import_titles_from_text(text)` → parses JSON/CSV
- `import_titles_from_clipboard()` → clipboard content

**Helper Functions**:
- `normalize_titles_structure(data)` → standardize format
- `_import_titles_from_csv_text(text)` → CSV → dict
- `_show_import_sanitize_check()` → pre-import validation UI
- `update_treeview_with_titles()` → refresh GUI

### Storage Locations
- **Config file**: `config.ini` (saved in working directory)
- **Cache file**: `seasonal_cache.json` (SubsPlease cache)
- **Recent files**: tracked in config.RECENT_FILES, persisted via `cache.py`
- **Exported rules**: user-selected directory (usually documents)

### Existing Persistence
From [src/cache.py](src/cache.py):
- `save_recent_files(files)` - persists to cache
- `load_recent_files()` - loads from cache
- `save_config()` - persists preferences
- `load_config()` - loads preferences

---

## 5. UI Location for Backup/Restore Controls

### Current Menu Structure
From [src/gui/main_window.py](src/gui/main_window.py#L473) - `setup_menu_bar()`

```
📁 File
  ├─ Open JSON File...           (Ctrl+O)
  ├─ Paste from Clipboard
  ├─ Recent Files                (submenu)
  ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  ├─ Export to Sonarr...         (Ctrl+Shift+S)
  ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  └─ Exit

✏️ Edit
  ├─ Toggle Enable/Disable       (Space)
  ├─ Undo                         (Ctrl+Z)
  ├─ Bulk Edit Selected...        (Ctrl+B)
  ├─ Clear All Titles             (Ctrl+Shift+C)
  ├─ Export Selected Titles...    (Ctrl+E)
  ├─ Export All Titles...         (Ctrl+Shift+E)
  ├─ Refresh Treeview             (F5)
  └─ View Trash...
```

### Recommended Backup/Restore Menu Location

**Option A: New "Tools" Menu** (Cleanest)
```
🛠️ Tools
  ├─ Backup qBittorrent Rules...
  ├─ Restore from Backup...
  └─ Backup Management...        (view, delete, compare backups)
```

**Option B: Expand File Menu** (Most Natural)
```
📁 File
  ├─ Open JSON File...           (Ctrl+O)
  ├─ Paste from Clipboard
  ├─ Recent Files                (submenu)
  ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  ├─ 💾 Backup qBittorrent Rules...
  ├─ 📥 Restore from Backup...
  ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  ├─ Export to Sonarr...
  └─ Exit
```

**Option C: Quick Buttons on Action Bar**
- Add "💾 Backup" button next to "⚡ Generate Rules" button
- Add "📥 Restore" button as dropdown/menu

### Additional UI Components

1. **Backup Dialog** (triggered by menu item)
   - Display list of existing backups (with timestamps)
   - Allow manual backup creation
   - Show: before/after rule counts, size, timestamp
   - Options: include categories, include feeds, include config metadata

2. **Restore Dialog** (triggered by menu item)
   - List available backups with preview
   - Option to preview what will be restored
   - Dry-run mode: show what would change
   - Confirm before applying

3. **Settings Panel** (in existing Settings window)
   - Auto-backup before sync: Yes/No
   - Backup location: custom path or default
   - Keep last N backups: (e.g., 10)
   - Backup compression: Yes/No

---

## 6. Storage Format for Backups

### Recommended Format: **JSON** (Consistent with current system)

**Simple per-file approach**:
```json
{
  "version": "1.0",
  "backup_timestamp": "2026-03-31T14:30:45Z",
  "qbittorrent_version": "4.5.2",
  "app_version": "1.0.0",
  "metadata": {
    "rule_count": 42,
    "category_count": 5,
    "feed_count": 3,
    "sync_mode_used": "replace",
    "filesystem_validation": "windows"
  },
  "rules": {
    "Rule Name": {
      "enabled": true,
      "mustContain": "pattern",
      "savePath": "anime/web",
      "assignedCategory": "Anime",
      "affectedFeeds": ["http://feed.url"],
      ... (all RSSRule fields)
    }
  },
  "categories": {
    "Anime": { ... },
    "Movies": { ... }
  },
  "feeds": {
    "http://feed.url": { ... }
  }
}
```

### Alternative: **Tarball** (for larger deployments)
```
backup_2026-03-31_14-30-45.tar.gz
├─ metadata.json
├─ rules.json
├─ categories.json
├─ feeds.json
└─ config_snapshot.ini  (optional, encrypted sensitive data)
```

### Backup Storage Location
- **Default**: `./backups/` subdirectory in application working directory
- **Naming convention**: `backup_YYYY-MM-DD_HH-MM-SS.json`
- **File permissions**: User-only read/write (mode 0600 on Unix)

---

## 7. Key API Functions to Call

### For Fetching Snapshot Data

```python
# From qbittorrent_api.py
fetch_rules(protocol, host, port, user, pass) → Tuple[bool, Dict]
fetch_categories(protocol, host, port, user, pass) → Tuple[bool, Dict]
fetch_feeds(protocol, host, port, user, pass) → Tuple[bool, Dict]

# From QBittorrentClient class
client = QBittorrentClient(protocol, host, port, user, pass, verify_ssl, ca_cert)
client.connect() → bool
client.get_rules() → Dict
client.get_categories() → Dict
client.get_feeds() → Dict
client.get_version() → str
client.get_preferences() → Dict
client.close() → None
```

### For Applying Snapshot

```python
# QBittorrentClient methods
client.set_rule(rule_name, rule_def) → bool
client.remove_rule(rule_name) → bool
client.add_feed(feed_url, feed_name) → bool
```

### For Building Rules Format

```python
# From rss_rules.py
from src.rss_rules import build_rules_from_titles, RSSRule

RSSRule.to_dict() → Dict[str, Any]
RSSRule.from_dict(title, rule_dict) → RSSRule
build_rules_from_titles(titles_dict) → Dict[str, Dict]
```

### For File Operations

```python
# From file_operations.py
import_titles_from_file(root, status_var, season_var, year_var, path) → bool
export_selected_titles() → None
export_all_titles() → None

# From cache.py
save_recent_files(files) → None
load_recent_files() → List[str]
save_config(config_data) → None
load_config() → Dict
```

---

## 8. Implementation Considerations

### Backup-Before-Sync Safety

The biggest gap: **No backup is created before sync/replace operations**.

When user clicks "Sync to qBittorrent" with Replace mode:
1. ❌ **No backup created** of existing rules
2. ✅ Validate new rules
3. ❌ **Delete all old rules** (if replace mode)
4. ✅ Add new rules
5. ❌ **If add fails**: old rules are already gone

**Recommended**: Auto-backup before EVERY sync operation, especially Replace mode.

### Restore Complexity

Restoring from snapshot requires handling:
1. **Rule ID conflicts**: qBittorrent uses rule names as IDs
   - What if user renamed rules since backup?
   - Solution: Let user choose merge/replace/skip strategy

2. **Feed validation**: 
   - Are feeds still accessible?
   - Need to re-add feeds if they don't exist?

3. **Categories**:
   - Restore or trust existing?
   - Pre-create missing categories

4. **Validation constraints**:
   - Folder names may be invalid on different filesystems
   - Save paths may not exist
   - Categories may not exist

### Sync Mode Interactions

Current sync modes (from `dispatch_generation()`):
- **Replace All**: Remove all, then add new ones
- **Add/Update Only**: Keep old, add/update new ones

Backup/restore should respect these patterns:
- **Restore Full**: Like Replace (remove all, then restore)
- **Restore + Merge**: Like Add (restore, but keep other rules)
- **Diff Restore**: Show what changed, let user pick

---

## 9. Summary Recommendations

### For Backup Feature:
1. **Storage**: JSON format, `backups/backup_YYYY-MM-DD_HH-MM-SS.json`
2. **Content**: Rules + categories + feeds + metadata + version info
3. **Triggers**: 
   - Manual: File > Backup Now (menu item)
   - Auto: Before every Sync operation (configurable)
4. **UI**: New Tools menu or expand File menu
5. **Retention**: Keep last N backups (config option, e.g., 10)

### For Restore Feature:
1. **UI**: File > Restore from Backup menu item
2. **Dialog**: List backups, preview, choose restore mode
3. **Modes**: Full restore, merge, and selective restore
4. **Validation**: Pre-restore checks for feed accessibility, category existence
5. **Recovery**: If restore fails, can still reload from backup file

### Key Functions to Implement:
- `backup_current_rules()` - snapshot current state from qBittorrent API
- `save_backup(backup_dict, filepath)` - persist to JSON
- `load_backup(filepath)` - load from JSON
- `restore_backup(backup_dict, restore_mode)` - apply to qBittorrent API
- `list_backups(backup_dir)` - enumerate available backups
- `cleanup_old_backups(backup_dir, keep_count)` - rotation policy

### Config Options to Add:
```python
BACKUP_ENABLED = True
BACKUP_AUTO_BEFORE_SYNC = True
BACKUP_LOCATION = "./backups"
BACKUP_KEEP_COUNT = 10
BACKUP_INCLUDE_CATEGORIES = True
BACKUP_INCLUDE_FEEDS = True
```

---

## 10. Test Strategy

Tests should verify:
1. ✅ Backup captures all rule fields accurately
2. ✅ Backup includes metadata (version, timestamp, counts)
3. ✅ Restore applies rules correctly to qBittorrent API
4. ✅ Restore modes (full/merge) work as expected
5. ✅ Cleanup removes old backups beyond keep_count
6. ✅ Backup/restore with categories and feeds
7. ✅ Error handling: inaccessible backups, corrupted JSON, API failures
8. ✅ Round-trip: backup → restore → backup should be identical
