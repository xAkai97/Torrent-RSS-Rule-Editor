"""
Debounce and Scheduling Utilities

Helpers for debounced callbacks and scheduling operations.
"""

import tkinter as tk
from typing import Any, Callable, Dict


def create_auto_apply_debounce(root: tk.Tk, callback: Callable, debounce_ms: int = 300) -> Dict[str, Any]:
    """
    Create a debounced callback scheduler for auto-apply on field changes.
    
    Args:
        root: Tkinter root window for scheduling
        callback: Function to call after debounce delay
        debounce_ms: Delay in milliseconds (default 300ms)
    
    Returns:
        Dict with keys: 'after_id_holder' (dict to track scheduled ID), 'schedule_callback' (function to bind to traces)
    """
    after_id_holder = {'id': None}
    
    def schedule_callback(*args):
        """Schedules callback after a short delay (debouncing)."""
        try:
            # Cancel previous scheduled call
            if after_id_holder['id']:
                root.after_cancel(after_id_holder['id'])
            
            # Schedule new call after debounce period
            after_id_holder['id'] = root.after(debounce_ms, callback)
        except Exception:
            pass
    
    return {
        'after_id_holder': after_id_holder,
        'schedule_callback': schedule_callback,
    }
