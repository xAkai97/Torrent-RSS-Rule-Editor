"""
Theme Engine Module — Material 3 Styling and Auto-Detection.

Provides utilities for:
  - Detecting the host operating system's light/dark mode preference
  - Resolving the 'auto' theme preference into 'light' or 'dark'
  - Generating and applying a comprehensive Qt stylesheet (QSS)
    based on a modern, premium Material 3 design system.
"""

import os
import logging
import tempfile
from PySide6.QtGui import QGuiApplication, Qt
from PySide6.QtWidgets import QApplication
from src.config import config

logger = logging.getLogger(__name__)


def get_host_machine_theme() -> str:
    """
    Detect the host machine's UI theme (dark or light mode).

    Tries PySide6 style hints first (Qt 6.5+ native API), then falls back
    to querying the Windows Registry directly. Defaults to 'light' on
    unsupported platforms or if detection fails.

    Returns:
        'dark' or 'light'.
    """
    try:
        app = QGuiApplication.instance()
        if app is not None:
            hints = app.styleHints()
            if hasattr(hints, 'colorScheme'):
                scheme = hints.colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return 'dark'
                elif scheme == Qt.ColorScheme.Light:
                    return 'light'
    except Exception:
        pass

    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return 'dark' if value == 0 else 'light'
    except Exception:
        pass

    return 'light'


def get_effective_theme(theme_pref: str) -> str:
    """
    Resolve the raw theme preference to an absolute 'light' or 'dark' value.

    If the preference is 'auto', it delegates to get_host_machine_theme().

    Args:
        theme_pref: 'light', 'dark', or 'auto'.

    Returns:
        'light' or 'dark'.
    """
    pref = str(theme_pref).strip().lower()
    if pref == 'auto':
        return get_host_machine_theme()
    if pref in {'light', 'dark'}:
        return pref
    return 'light'


def apply_app_theme(window, theme_pref: str) -> None:
    """
    Generate and apply the global CSS stylesheet for the application.

    This function defines a custom, premium design system using Material 3
    principles (slate blues, rounded corners, subtle borders). It injects
    the correct color palette based on the effective theme ('light' or 'dark').

    It also generates inline SVG icons for checkboxes, radio buttons, and
    dropdown arrows to ensure crisp scaling on high-DPI displays.

    Args:
        window: The main application window instance (used to store state).
        theme_pref: The user's theme preference ('light', 'dark', 'auto').
    """
    effective = get_effective_theme(theme_pref)

    # Save active effective theme so the GUI can check if it changed later
    window._theme_pref = theme_pref
    window._effective_theme = effective

    # Define paths for generated SVG assets
    temp_dir = tempfile.gettempdir()
    checkmark_path = os.path.join(temp_dir, 'qbt_checkmark.svg').replace('\\', '/')
    radio_path = os.path.join(temp_dir, 'qbt_radio_dot.svg').replace('\\', '/')
    down_arrow_path = os.path.join(temp_dir, 'qbt_down_arrow.svg').replace('\\', '/')
    up_arrow_path = os.path.join(temp_dir, 'qbt_up_arrow.svg').replace('\\', '/')

    # Define the color palettes
    if effective == 'dark':
        bg_color = '#0b0e14'        # Premium dark slate blue
        surface_color = '#151b26'   # Deep card background
        text_color = '#f1f5f9'      # Crisp off-white
        text_variant = '#94a3b8'    # Slate 400
        border_color = '#223147'    # Sleek dark blue border
        primary_color = '#3b82f6'   # Vibrant primary blue
        primary_container = '#1d4ed8'
        on_primary_container = '#f8fafc'
        button_bg = '#1e293b'
        button_text = '#f8fafc'
        button_hover = '#334155'
        button_press = '#1d4ed8'
        disabled_bg = '#1e293b'
        disabled_text = '#475569'
        input_bg = '#0b0e14'
        chip_bg = '#1e293b'
    else:
        bg_color = '#f8fafc'        # Soft grey-blue background
        surface_color = '#ffffff'   # Clean white cards
        text_color = '#0f172a'      # Deep slate text
        text_variant = '#475569'    # Slate 600
        border_color = '#e2e8f0'    # Slate 200 borders
        primary_color = '#0284c7'   # Sky blue accent
        primary_container = '#e0f2fe'
        on_primary_container = '#0369a1'
        button_bg = '#ffffff'
        button_text = '#0284c7'
        button_hover = '#f1f5f9'
        button_press = '#e0f2fe'
        disabled_bg = '#f1f5f9'
        disabled_text = '#94a3b8'
        input_bg = '#ffffff'
        chip_bg = '#ffffff'

    # Premium design styles with inline SVG checkbox/radio indicators
    stylesheet = f"""
        QMainWindow, QDialog {{
            background-color: {bg_color};
            color: {text_color};
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            font-size: 13px;
        }}
        QToolTip {{
            background-color: {surface_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 6px;
            padding: 4px 8px;
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            font-size: 12px;
        }}
        QWidget {{
            color: {text_color};
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            font-size: 13px;
        }}
        QLabel, QCheckBox, QRadioButton {{
            background-color: transparent;
        }}
        QMenuBar {{
            background-color: {surface_color};
            color: {text_color};
            border-bottom: 1px solid {border_color};
            padding: 4px;
        }}
        QMenuBar::item {{
            background-color: transparent;
            padding: 6px 12px;
            border-radius: 6px;
        }}
        QMenuBar::item:selected {{
            background-color: {button_hover};
        }}
        QMenu {{
            background-color: {surface_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {button_hover};
            color: {primary_color};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {border_color};
            margin: 4px 0;
        }}
        QGroupBox {{
            color: {primary_color};
            font-weight: 600;
            border: 1px solid {border_color};
            border-radius: 12px;
            margin-top: 14px;
            padding-top: 14px;
            background-color: {surface_color};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 2px 6px;
            background-color: {bg_color};
            border-radius: 4px;
            font-size: 12px;
        }}
        QPushButton {{
            background-color: {button_bg};
            color: {button_text};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 6px 16px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {button_hover};
            border-color: {primary_color};
        }}
        QPushButton:pressed {{
            background-color: {button_press};
        }}
        QPushButton:disabled {{
            background-color: {disabled_bg};
            color: {disabled_text};
            border-color: {disabled_bg};
        }}
        QLineEdit, QSpinBox {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 6px 12px;
        }}
        QSpinBox {{
            padding: 6px 24px 6px 12px;
        }}
        QComboBox {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 6px 36px 6px 12px;
            combobox-popup: 0;
        }}
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
            border-color: {primary_color};
        }}
        QLineEdit:focus, QSpinBox:focus {{
            border: 2px solid {primary_color};
            padding: 5px 11px;
        }}
        QSpinBox:focus {{
            padding: 5px 23px 5px 11px;
        }}
        QComboBox:focus {{
            border: 2px solid {primary_color};
            padding: 5px 35px 5px 11px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border: none;
        }}
        QComboBox::down-arrow {{
            image: url("{down_arrow_path}");
            width: 12px;
            height: 12px;
        }}
        QSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 20px;
            border-left: 1px solid {border_color};
            border-bottom: 1px solid {border_color};
            border-top-right-radius: 7px;
            background-color: {button_bg};
        }}
        QSpinBox::up-button:hover {{
            background-color: {button_hover};
        }}
        QSpinBox::up-button:pressed {{
            background-color: {button_press};
        }}
        QSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 20px;
            border-left: 1px solid {border_color};
            border-bottom-right-radius: 7px;
            background-color: {button_bg};
        }}
        QSpinBox::down-button:hover {{
            background-color: {button_hover};
        }}
        QSpinBox::down-button:pressed {{
            background-color: {button_press};
        }}
        QSpinBox::up-arrow {{
            image: url("{up_arrow_path}");
            width: 8px;
            height: 8px;
        }}
        QSpinBox::down-arrow {{
            image: url("{down_arrow_path}");
            width: 8px;
            height: 8px;
        }}
        QSpinBox:disabled {{
            background-color: {disabled_bg};
            color: {disabled_text};
            border-color: {disabled_bg};
        }}
        QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{
            background-color: {disabled_bg};
            border-left-color: {disabled_bg};
        }}
        QComboBox QAbstractItemView {{
            background-color: {surface_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 6px 12px;
            border-radius: 6px;
        }}
        QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
            background-color: {primary_container};
            color: {on_primary_container};
        }}
        QScrollArea {{
            background-color: transparent;
            border: none;
        }}
        QScrollArea > QWidget {{
            background-color: transparent;
        }}
        QScrollArea > QWidget > QWidget {{
            background-color: transparent;
        }}
        QTreeWidget, QListWidget, QTableWidget, QTableView, QTextEdit {{
            background-color: {surface_color};
            alternate-background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 12px;
            padding: 8px;
            gridline-color: {border_color};
        }}
        QTreeWidget::item, QListWidget::item, QTableWidget::item, QTableView::item {{
            padding: 6px;
            border-radius: 6px;
            margin-bottom: 2px;
        }}
        QTreeWidget::item:hover, QListWidget::item:hover, QTableWidget::item:hover, QTableView::item:hover {{
            background-color: {button_hover};
        }}
        QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected, QTableView::item:selected {{
            background-color: {primary_container};
            color: {on_primary_container};
        }}
        QHeaderView::section {{
            background-color: {surface_color};
            color: {text_color};
            padding: 8px;
            border: none;
            border-bottom: 2px solid {border_color};
            font-weight: bold;
        }}
        QTabWidget::pane {{
            border: 1px solid {border_color};
            border-radius: 12px;
            background-color: {bg_color};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: transparent;
            color: {text_variant};
            padding: 8px 16px;
            border-bottom: 2px solid transparent;
            margin-right: 4px;
            font-weight: 500;
        }}
        QTabBar::tab:hover {{
            color: {primary_color};
            background-color: {button_hover};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        QTabBar::tab:selected {{
            color: {primary_color};
            border-bottom: 3px solid {primary_color};
            font-weight: bold;
        }}
        QStatusBar {{
            background-color: {surface_color};
            border-top: 1px solid {border_color};
            color: {text_variant};
        }}
        QSplitter::handle {{
            background-color: {border_color};
        }}
        QSplitter::handle:horizontal {{
            width: 4px;
        }}
        QSplitter::handle:vertical {{
            height: 4px;
        }}
        QScrollBar:vertical {{
            border: none;
            background-color: transparent;
            width: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {border_color};
            min-height: 20px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {text_variant};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            border: none;
            background: none;
        }}
        QScrollBar:horizontal {{
            border: none;
            background-color: transparent;
            height: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {border_color};
            min-width: 20px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {text_variant};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            border: none;
            background: none;
        }}
        QCheckBox {{
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1.5px solid {border_color};
            border-radius: 4px;
            background-color: {input_bg};
        }}
        QCheckBox::indicator:hover {{
            border-color: {primary_color};
        }}
        QCheckBox::indicator:checked {{
            background-color: {primary_color};
            border-color: {primary_color};
            image: url("{checkmark_path}");
        }}
        QCheckBox::indicator:disabled {{
            border-color: {border_color};
            background-color: {disabled_bg};
        }}
        QRadioButton {{
            spacing: 8px;
        }}
        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 1.5px solid {border_color};
            border-radius: 9px;
            background-color: {input_bg};
        }}
        QRadioButton::indicator:hover {{
            border-color: {primary_color};
        }}
        QRadioButton::indicator:checked {{
            background-color: {primary_color};
            border-color: {primary_color};
            image: url("{radio_path}");
        }}
        QRadioButton::indicator:disabled {{
            border-color: {border_color};
            background-color: {disabled_bg};
        }}
        #connection_chip, #titles_chip {{
            background-color: {chip_bg};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 11px;
        }}
        #actions_separator {{
            background-color: {border_color};
            border: none;
            width: 1px;
            max-width: 1px;
            margin: 6px 12px;
        }}
    """
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet)
