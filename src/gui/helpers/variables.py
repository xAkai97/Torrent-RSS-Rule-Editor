"""
Tkinter Variable Creation Helpers

Factory functions for creating and managing Tkinter variables.
"""

import tkinter as tk
from typing import Any, Dict


def create_editor_variables() -> Dict[str, Any]:
    """
    Create Tkinter variables for editor panel fields.
    
    Returns:
        Dict with keys: rule_name, must, savepath, category, enabled, undo_stack
    """
    return {
        'rule_name': tk.StringVar(value=''),
        'must': tk.StringVar(value=''),
        'savepath': tk.StringVar(value=''),
        'category': tk.StringVar(value=''),
        'enabled': tk.BooleanVar(value=True),
        'undo_stack': [],
    }
