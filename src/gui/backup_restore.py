"""
GUI dialogs for backup and restore operations.

Provides dialogs for:
- Creating qBittorrent rules backups
- Restoring from backup snapshots
- Managing backup files
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, Optional

from src import backup
from src.qbittorrent_api import fetch_rules, fetch_categories, fetch_feeds
from src.config import config
from src.gui.helpers import center_window

logger = logging.getLogger(__name__)


def backup_qbittorrent_rules(root: tk.Widget, status_var: tk.StringVar) -> None:
    """
    Create a backup of current qBittorrent rules.
    
    Shows a dialog to get connection info and backs up existing rules from qBittorrent.
    
    Args:
        root: Parent tkinter widget
        status_var: StringVar for status messages
    """
    
    def _perform_backup():
        """Perform backup in background thread."""
        try:
            # Get connection info
            protocol = config.get_pref('qb_protocol', 'http')
            host = config.get_pref('qb_host', 'localhost')
            port = config.get_pref('qb_port', '8080')
            username = config.get_pref('qb_username', '')
            password = config.get_pref('qb_password', '')
            
            status_var.set("Connecting to qBittorrent...")
            root.update()
            
            # Fetch current rules, categories, and feeds
            rules = fetch_rules(protocol, host, port, username, password) or {}
            categories = fetch_categories(protocol, host, port, username, password) or {}
            feeds = fetch_feeds(protocol, host, port, username, password) or []
            
            # Get qBittorrent version for metadata
            try:
                import src.qbittorrent_api as qbt_api
                client = qbt_api.QBittorrentClient(protocol, host, port, username, password)
                qbt_version = client.client.app_version() if hasattr(client.client, 'app_version') else 'Unknown'
            except:
                qbt_version = 'Unknown'
            
            metadata = {
                'qbittorrent_version': str(qbt_version),
                'rule_count': len(rules),
                'category_count': len(categories),
            }
            
            status_var.set("Creating backup...")
            root.update()
            
            # Create backup
            success, message = backup.create_backup(
                rules=rules,
                categories=categories,
                feeds=feeds,
                metadata=metadata
            )
            
            status_var.set(message)
            
            if success:
                messagebox.showinfo(
                    "Backup Created",
                    f"{message}\n\n{len(rules)} rules backed up successfully.",
                    parent=root
                )
            else:
                messagebox.showerror(
                    "Backup Failed",
                    message,
                    parent=root
                )
                
        except Exception as e:
            error_msg = f"Backup failed: {e}"
            logger.error(error_msg)
            status_var.set(error_msg)
            messagebox.showerror(
                "Backup Error",
                error_msg,
                parent=root
            )
    
    # Run backup in background thread
    thread = threading.Thread(target=_perform_backup, daemon=True)
    thread.start()


def restore_from_backup(
    root: tk.Widget,
    status_var: tk.StringVar,
    apply_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> None:
    """
    Restore rules from a backup file.
    
    Shows a file dialog to select backup file, then displays restore options.
    
    Args:
        root: Parent tkinter widget
        status_var: StringVar for status messages
        apply_callback: Optional callback function to apply restored rules
                       Called with (rules: dict)
    """
    
    # Create file dialog
    backup_dir = os.path.dirname(backup.DEFAULT_BACKUP_DIR) or '.'
    backup_path = filedialog.askopenfilename(
        parent=root,
        title='Select Backup to Restore',
        initialdir=backup_dir,
        filetypes=[('JSON Backups', '*.json'), ('All Files', '*.*')]
    )
    
    if not backup_path:
        status_var.set("Restore cancelled")
        return
    
    # Load backup
    success, backup_data, message = backup.load_backup(backup_path)
    
    if not success:
        messagebox.showerror(
            "Backup Load Failed",
            message,
            parent=root
        )
        status_var.set(message)
        return
    
    # Get backup metadata
    metadata = backup.extract_backup_metadata(backup_data)
    
    # Create restore options dialog
    _show_restore_options_dialog(
        root,
        backup_path,
        backup_data,
        metadata,
        status_var,
        apply_callback
    )


def _show_restore_options_dialog(
    root: tk.Widget,
    backup_path: str,
    backup_data: Dict[str, Any],
    metadata: Dict[str, str],
    status_var: tk.StringVar,
    apply_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> None:
    """
    Show dialog with restore options.
    
    Args:
        root: Parent tkinter widget
        backup_path: Path to backup file
        backup_data: Loaded backup data
        metadata: Backup metadata
        status_var: StringVar for status messages
        apply_callback: Optional callback to apply restored rules
    """
    
    dialog = tk.Toplevel(root)
    dialog.title('Restore from Backup')
    dialog.geometry('500x400')
    dialog.resizable(True, True)
    center_window(dialog)
    dialog.transient(root)
    dialog.grab_set()
    
    # Backup info frame
    info_frame = ttk.LabelFrame(dialog, text='Backup Information', padding=10)
    info_frame.pack(fill=tk.X, padx=10, pady=10)
    
    # Display metadata
    ttk.Label(info_frame, text=f"Backup Time: {metadata.get('backup_time', 'Unknown')}").pack(anchor=tk.W)
    ttk.Label(info_frame, text=f"Rules: {metadata.get('rule_count', '0')}").pack(anchor=tk.W)
    ttk.Label(info_frame, text=f"Categories: {metadata.get('category_count', '0')}").pack(anchor=tk.W)
    ttk.Label(info_frame, text=f"Feeds: {metadata.get('feed_count', '0')}").pack(anchor=tk.W)
    ttk.Label(info_frame, text=f"qBittorrent Version: {metadata.get('qbittorrent_version', 'Unknown')}").pack(anchor=tk.W)
    
    # Restore options frame
    options_frame = ttk.LabelFrame(dialog, text='Restore Options', padding=10)
    options_frame.pack(fill=tk.X, padx=10, pady=10)
    
    restore_mode = tk.StringVar(value='merge')
    
    ttk.Radiobutton(
        options_frame,
        text='Merge with existing rules (new rules added, existing updated)',
        variable=restore_mode,
        value='merge'
    ).pack(anchor=tk.W, pady=5)
    
    ttk.Radiobutton(
        options_frame,
        text='Replace all rules (⚠️ WARNING: Deletes current rules)',
        variable=restore_mode,
        value='replace'
    ).pack(anchor=tk.W, pady=5)
    
    # Warning text for replace mode
    warning_text = ttk.Label(
        options_frame,
        text='⚠️ Replace mode will delete all current rules!',
        foreground='red'
    )
    warning_text.pack(anchor=tk.W, pady=5)
    
    # Hide warning initially
    warning_text.grid_remove() if restore_mode.get() == 'merge' else None
    
    def _toggle_warning():
        """Show/hide warning based on restore mode."""
        if restore_mode.get() == 'replace':
            warning_text.grid()
        else:
            warning_text.grid_remove()
    
    restore_mode.trace('w', lambda *_: _toggle_warning())
    
    # Button frame
    button_frame = ttk.Frame(dialog, padding=10)
    button_frame.pack(fill=tk.X, side=tk.BOTTOM)
    
    def _perform_restore():
        """Apply the restore operation."""
        try:
            rules_to_restore = backup_data.get('rules', {})
            
            if not rules_to_restore:
                messagebox.showwarning(
                    "No Rules",
                    "This backup contains no rules to restore.",
                    parent=dialog
                )
                return
            
            # Confirm action
            if restore_mode.get() == 'replace':
                confirm = messagebox.askyesno(
                    "Confirm Replace",
                    f"This will delete all existing rules and restore {len(rules_to_restore)} rules from backup.\n\nContinue?",
                    parent=dialog
                )
                if not confirm:
                    return
            
            status_var.set(f"Restoring {len(rules_to_restore)} rules...")
            root.update()
            
            # Call apply callback if provided
            if apply_callback:
                apply_callback({
                    'rules': rules_to_restore,
                    'mode': restore_mode.get(),
                    'categories': backup_data.get('categories', {}),
                    'feeds': backup_data.get('feeds', []),
                })
            
            status_var.set("Restore completed")
            messagebox.showinfo(
                "Restore Complete",
                f"Restored {len(rules_to_restore)} rules from backup.",
                parent=dialog
            )
            dialog.destroy()
            
        except Exception as e:
            error_msg = f"Restore failed: {e}"
            logger.error(error_msg)
            status_var.set(error_msg)
            messagebox.showerror(
                "Restore Error",
                error_msg,
                parent=dialog
            )
    
    ttk.Button(dialog, text='Restore', command=_perform_restore).pack(side=tk.RIGHT, padx=5)
    ttk.Button(dialog, text='Cancel', command=dialog.destroy).pack(side=tk.RIGHT, padx=5)


def open_backup_manager(root: tk.Widget, status_var: tk.StringVar) -> None:
    """
    Open backup manager dialog to browse and manage backups.
    
    Args:
        root: Parent tkinter widget
        status_var: StringVar for status messages
    """
    
    dialog = tk.Toplevel(root)
    dialog.title('Backup Manager')
    dialog.geometry('700x400')
    dialog.resizable(True, True)
    center_window(dialog)
    dialog.transient(root)
    dialog.grab_set()
    
    # Backups listbox
    listframe = ttk.Frame(dialog, padding=10)
    listframe.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(listframe, text='Available Backups:', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)
    
    # Create treeview for backup list
    tree_frame = ttk.Frame(listframe)
    tree_frame.pack(fill=tk.BOTH, expand=True, pady=10)
    
    tree = ttk.Treeview(tree_frame, columns=('Modified', 'Rules', 'Categories'), height=10)
    tree.column('#0', width=250, heading='Backup File')
    tree.column('Modified', width=150, heading='Modified')
    tree.column('Rules', width=70, heading='Rules')
    tree.column('Categories', width=80, heading='Categories')
    
    tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
    
    # Scrollbar
    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    tree.configure(yscroll=scrollbar.set)
    
    def _refresh_backups():
        """Refresh backup list."""
        tree.delete(*tree.get_children())
        backups = backup.list_backups()
        
        for filename, full_path, mod_time in backups:
            try:
                success, backup_data, _ = backup.load_backup(full_path)
                if success:
                    rule_count = len(backup_data.get('rules', {}))
                    category_count = len(backup_data.get('categories', {}))
                    tree.insert('', 'end', values=(
                        mod_time.strftime('%Y-%m-%d %H:%M:%S'),
                        str(rule_count),
                        str(category_count)
                    ), text=filename)
            except Exception as e:
                logger.warning(f"Failed to load backup info for {filename}: {e}")
    
    def _delete_backup():
        """Delete selected backup."""
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to delete.", parent=dialog)
            return
        
        item = selection[0]
        filename = tree.item(item)['text']
        
        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Delete backup '{filename}'?",
            parent=dialog
        )
        
        if confirm:
            try:
                backups = backup.list_backups()
                for fname, full_path, _ in backups:
                    if fname == filename:
                        os.remove(full_path)
                        status_var.set(f"Deleted backup: {filename}")
                        _refresh_backups()
                        break
            except Exception as e:
                messagebox.showerror("Delete Failed", f"Failed to delete backup: {e}", parent=dialog)
    
    # Button frame
    button_frame = ttk.Frame(dialog, padding=10)
    button_frame.pack(fill=tk.X, side=tk.BOTTOM)
    
    ttk.Button(button_frame, text='Refresh', command=_refresh_backups).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text='Delete', command=_delete_backup).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text='Close', command=dialog.destroy).pack(side=tk.RIGHT, padx=5)
    
    # Load initial backup list
    _refresh_backups()
