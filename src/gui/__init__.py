"""GUI package entrypoint.

This package keeps Tk fallback functionality available while avoiding eager
imports of legacy Tk modules unless they are explicitly accessed.
"""

from __future__ import annotations

import importlib

_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    'setup_gui': ('main_window', 'setup_gui'),
    'exit_handler': ('main_window', 'exit_handler'),
    # Module-level compatibility access.
    'app_state': ('app_state', None),
    'widgets': ('widgets', None),
}


def __getattr__(name: str):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    'setup_gui',
    'exit_handler',
    'app_state',
    'widgets',
]

__version__ = '1.0.0'
