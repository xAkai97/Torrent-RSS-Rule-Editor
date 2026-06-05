"""
Theme Color Management

Provides theme-aware color palettes for editor and UI components.
"""

from typing import Dict
from src.config import config


def get_editor_theme_colors() -> Dict[str, str]:
    """
    Get theme-aware color palette for editor panel.
    
    Returns:
        Dict with keys: bg, input_bg, input_fg, border, link, success, tooltip_bg, tooltip_fg
    """
    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'

    if theme_pref == 'dark':
        return {
            'bg': '#0f172a',
            'input_bg': '#1e293b',
            'input_fg': '#f8fafc',
            'border': '#334155',
            'link': '#60a5fa',
            'success': '#10b981',
            'tooltip_bg': '#1e293b',
            'tooltip_fg': '#f8fafc',
        }
    else:
        return {
            'bg': '#ffffff',
            'input_bg': '#f8fafc',
            'input_fg': '#0f172a',
            'border': '#cbd5e1',
            'link': '#2563eb',
            'success': '#059669',
            'tooltip_bg': '#1e293b',
            'tooltip_fg': '#f8fafc',
        }


def get_ui_theme_colors(font_size_pref: int) -> Dict[str, str]:
    """
    Get theme-aware color palette for main UI styling.
    
    Args:
        font_size_pref: Font size in points
        
    Returns:
        Dict with keys: bg_color, frame_bg, text_color, button_bg, button_text,
        button_hover, button_pressed, button_disabled_bg, button_disabled_text,
        accent_color, accent_hover, accent_pressed, border_color, tree_field_bg,
        tree_select_bg, tree_select_fg, danger_bg, danger_border, danger_hover,
        danger_pressed, tree_bg, tree_fg, tree_heading_bg, tree_heading_fg
    """
    try:
        theme_pref = str(config.get_pref('theme', 'light')).lower()
    except Exception:
        theme_pref = 'light'

    if theme_pref == 'dark':
        return {
            'theme_pref': 'dark',
            'bg_color': '#0f172a',
            'frame_bg': '#1e293b',
            'text_color': '#f8fafc',
            'button_bg': '#334155',
            'button_text': '#f8fafc',
            'button_hover': '#475569',
            'button_pressed': '#1e293b',
            'button_disabled_bg': '#1e293b',
            'button_disabled_text': '#64748b',
            'accent_color': '#6366f1',
            'accent_hover': '#818cf8',
            'accent_pressed': '#4f46e5',
            'border_color': '#334155',
            'tree_field_bg': '#0f172a',
            'tree_select_bg': '#6366f1',
            'tree_select_fg': '#ffffff',
            'danger_bg': '#ef4444',
            'danger_border': '#b91c1c',
            'danger_hover': '#f87171',
            'danger_pressed': '#dc2626',
            'tree_bg': '#0f172a',
            'tree_fg': '#f8fafc',
            'tree_heading_bg': '#1e293b',
            'tree_heading_fg': '#e2e8f0',
        }
    else:  # light theme
        return {
            'theme_pref': 'light',
            'bg_color': '#f1f5f9',
            'frame_bg': '#ffffff',
            'text_color': '#0f172a',
            'button_bg': '#e2e8f0',
            'button_text': '#0f172a',
            'button_hover': '#cbd5e1',
            'button_pressed': '#94a3b8',
            'button_disabled_bg': '#f1f5f9',
            'button_disabled_text': '#94a3b8',
            'accent_color': '#4f46e5',
            'accent_hover': '#4338ca',
            'accent_pressed': '#3730a3',
            'border_color': '#cbd5e1',
            'tree_field_bg': '#ffffff',
            'tree_select_bg': '#4f46e5',
            'tree_select_fg': '#ffffff',
            'danger_bg': '#ef4444',
            'danger_border': '#dc2626',
            'danger_hover': '#f87171',
            'danger_pressed': '#b91c1c',
            'tree_bg': '#ffffff',
            'tree_fg': '#0f172a',
            'tree_heading_bg': '#e2e8f0',
            'tree_heading_fg': '#1e293b',
        }
