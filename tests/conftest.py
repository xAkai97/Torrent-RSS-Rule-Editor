import pytest


@pytest.fixture(autouse=True)
def reset_gui_app_state_singleton():
    """Reset global AppState singletons to avoid cross-test contamination."""
    from src.gui import app_state as app_state_module

    app_state_module._app_state = None
    app_state_module.AppState._instance = None
    yield
    app_state_module._app_state = None
    app_state_module.AppState._instance = None
