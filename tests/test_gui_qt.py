"""
Unit tests for PySide6 GUI elements running headlessly in offscreen mode.
"""
import sys
import os
import pytest

try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton
    from PySide6.QtCore import Qt
    pyside_available = True
except ImportError:
    pyside_available = False


@pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")
def test_headless_qapplication_initialization(qtbot):
    """Verify that QApplication can be initialized in headless 'offscreen' mode."""
    # Create a simple window and label
    window = QMainWindow()
    window.setWindowTitle("Test Headless Window")
    label = QLabel("Hello Headless Qt", parent=window)
    window.setCentralWidget(label)
    
    qtbot.addWidget(window)
    
    # Verify properties
    assert window.windowTitle() == "Test Headless Window"
    assert label.text() == "Hello Headless Qt"
    
    # Show and close window headlessly (forces layout and events, no display needed)
    window.show()
    window.close()


@pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")
def test_widget_creation_and_events(qtbot):
    """Verify standard widgets can be created, styled, and clicked without a real display."""
    btn = QPushButton("Click Me")
    qtbot.addWidget(btn)
    assert btn.text() == "Click Me"
    
    # Verify connection and slot trigger
    clicked = False
    def on_click():
        nonlocal clicked
        clicked = True
        
    btn.clicked.connect(on_click)
    # Use qtbot to perform the click
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert clicked is True


@pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")
def test_nyaa_search_dialog_creation(qtbot):
    """Verify that NyaaSearchDialog can be instantiated and populated."""
    from src.gui_qt.nyaa_search_dialog import NyaaSearchDialog
    dialog = NyaaSearchDialog()
    qtbot.addWidget(dialog)
    
    assert dialog.windowTitle() == "Nyaa.si Custom RSS Search Addon"
    assert dialog.query_edit.text() == ""
    assert dialog.uploader_edit.text() == ""
    assert dialog.custom_words_edit.text() == ""
    assert dialog.tags_edit.text() == "nyaa-custom-search"
