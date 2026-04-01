"""
Custom widgets and reusable GUI components.
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional


class ToolTip:
    """Displays a tooltip when hovering over a widget."""
    
    def __init__(self, widget, text: str):
        """
        Initialize tooltip for a widget.
        
        Args:
            widget: The tkinter widget to attach tooltip to
            text: The tooltip text to display
        """
        self.widget = widget
        self.text = text
        self.tooltip: Optional[tk.Toplevel] = None
        widget.bind('<Enter>', self.show)
        widget.bind('<Leave>', self.hide)
    
    def show(self, event=None):
        """Show the tooltip."""
        try:
            x = self.widget.winfo_rootx() + 25
            y = self.widget.winfo_rooty() + 25
            
            self.tooltip = tk.Toplevel(self.widget)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{x}+{y}")
            
            tk.Label(
                self.tooltip, 
                text=self.text,
                background='#ffffe0',
                relief='solid',
                borderwidth=1,
                font=('Segoe UI', 8),
                padx=5,
                pady=3
            ).pack()
        except Exception:
            pass
    
    def hide(self, event=None):
        """Hide the tooltip."""
        if self.tooltip:
            try:
                self.tooltip.destroy()
            except Exception:
                pass
            self.tooltip = None


class ScrollableFrame(tk.Frame):
    """A frame that can be scrolled with mouse wheel."""
    
    def __init__(self, parent, *args, **kwargs):
        """
        Initialize scrollable frame.
        
        Args:
            parent: Parent widget
            *args: Additional positional arguments for Frame
            **kwargs: Additional keyword arguments for Frame
        """
        super().__init__(parent, *args, **kwargs)
        
        # Create canvas and scrollbar
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mouse wheel
        self._bind_mousewheel()
    
    def _bind_mousewheel(self):
        """Bind mouse wheel scrolling."""
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(event, 
                _on_mousewheel if event == "<MouseWheel>" 
                else lambda e, d=-1 if event == "<Button-4>" else 1: self.canvas.yview_scroll(d, "units")
            )


def create_labeled_entry(parent, label_text: str, var: tk.StringVar, **kwargs) -> tk.Entry:
    """
    Create a labeled entry widget.
    
    Args:
        parent: Parent widget
        label_text: Text for the label
        var: StringVar to bind to entry
        **kwargs: Additional arguments for Entry widget
    
    Returns:
        The created Entry widget
    """
    ttk.Label(parent, text=label_text, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    entry = ttk.Entry(parent, textvariable=var, font=('Segoe UI', 9), **kwargs)
    entry.pack(anchor='w', fill='x', pady=(0, 8))
    return entry


def create_labeled_combobox(parent, label_text: str, var: tk.StringVar, values: list, **kwargs):
    """
    Create a labeled combobox widget.
    
    Args:
        parent: Parent widget
        label_text: Text for the label
        var: StringVar to bind to combobox
        values: List of values for combobox
        **kwargs: Additional arguments for Combobox widget
    
    Returns:
        The created Combobox widget
    """
    ttk.Label(parent, text=label_text, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    combo = ttk.Combobox(parent, textvariable=var, values=values, font=('Segoe UI', 9), **kwargs)
    combo.pack(anchor='w', fill='x', pady=(0, 8))
    return combo


def create_labeled_text(parent, label_text: str, height: int = 10, width: int = 60, **kwargs) -> tk.Text:
    """
    Create a labeled text widget with scrollbar.
    
    Args:
        parent: Parent widget
        label_text: Text for the label
        height: Height of text widget in lines (default: 10)
        width: Width of text widget in characters (default: 60)
        **kwargs: Additional arguments for Text widget
    
    Returns:
        The created Text widget
    """
    # Create label
    ttk.Label(parent, text=label_text, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 2))
    
    # Create frame for text and scrollbar
    text_frame = tk.Frame(parent)
    text_frame.pack(anchor='w', fill='both', expand=True, pady=(0, 8))
    
    # Create text widget
    text = tk.Text(text_frame, height=height, width=width, wrap=tk.WORD, font=('Segoe UI', 9), **kwargs)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
    # Create scrollbar
    scrollbar = ttk.Scrollbar(text_frame, command=text.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    text.config(yscrollcommand=scrollbar.set)
    
    return text


def center_window(window: tk.Toplevel, width: int = None, height: int = None, parent=None):
    """
    Center a window on the screen.
    
    Args:
        window: The window to center
        width: Optional width (if None, uses current width)
        height: Optional height (if None, uses current height)
        parent: Optional parent widget to center within
    """
    window.update_idletasks()

    if parent is None and width is not None and not isinstance(width, (int, float)):
        parent = width
        width = None
        height = None
    
    if width is None:
        width = window.winfo_width()
    if height is None:
        height = window.winfo_height()
    
    ref = parent
    if ref is None:
        ref = window.master if isinstance(getattr(window, 'master', None), tk.Widget) else None

    if isinstance(ref, tk.Widget):
        ref.update_idletasks()
        x = ref.winfo_rootx() + (max(1, ref.winfo_width()) - width) // 2
        y = ref.winfo_rooty() + (max(1, ref.winfo_height()) - height) // 2
    else:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

    x = max(0, int(x))
    y = max(0, int(y))
    
    window.geometry(f"{width}x{height}+{x}+{y}")
