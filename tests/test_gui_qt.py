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
def test_headless_qapplication_initialization():
    """Verify that QApplication can be initialized in headless 'offscreen' mode."""
    # This utilizes the QT_QPA_PLATFORM='offscreen' set in conftest.py
    app = QApplication.instance() or QApplication([])
    assert app is not None
    
    # Create a simple window and label
    window = QMainWindow()
    window.setWindowTitle("Test Headless Window")
    label = QLabel("Hello Headless Qt", parent=window)
    window.setCentralWidget(label)
    
    # Verify properties
    assert window.windowTitle() == "Test Headless Window"
    assert label.text() == "Hello Headless Qt"
    
    # Show and close window headlessly (forces layout and events, no display needed)
    window.show()
    window.close()


@pytest.mark.skipif(not pyside_available, reason="PySide6 is not installed")
def test_widget_creation_and_events():
    """Verify standard widgets can be created, styled, and clicked without a real display."""
    app = QApplication.instance() or QApplication([])
    btn = QPushButton("Click Me")
    assert btn.text() == "Click Me"
    
    # Verify connection and slot trigger
    clicked = False
    def on_click():
        nonlocal clicked
        clicked = True
        
    btn.clicked.connect(on_click)
    btn.click()
    assert clicked is True
