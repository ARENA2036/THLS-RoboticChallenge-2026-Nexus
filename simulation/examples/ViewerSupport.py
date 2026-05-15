"""
Viewer support probing utilities.

On Wayland, MuJoCo viewer works in-process but crashes in subprocesses
due to Wayland compositor session inheritance issues. Calling
glfw.init()/terminate() before launch_passive also corrupts EGL state.
This module performs only safe, non-destructive import checks.
"""

from __future__ import annotations

from typing import Tuple


def probe_viewer_support() -> Tuple[bool, str]:
    try:
        import mujoco  # noqa: F401
        import mujoco.viewer  # noqa: F401
    except ImportError as import_error:
        return False, f"MuJoCo viewer not available: {import_error}"

    try:
        import glfw  # noqa: F401
    except ImportError as import_error:
        return False, f"GLFW not available: {import_error}"

    return True, ""
