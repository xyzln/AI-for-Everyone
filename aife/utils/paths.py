"""Bundled-resource resolution, frozen-binary aware.

When packaged with PyInstaller, data files (``web/``, ``config/aife.yaml``) are
extracted to ``sys._MEIPASS`` at runtime. In a normal source checkout they live
at the repository root (two levels above this file).
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "_MEIPASS", None))


def resource_root() -> Path:
    """Base directory for bundled data resources."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # Source tree: this file is <repo>/aife/utils/paths.py
    return Path(__file__).resolve().parents[2]
