# asciidoctor_backend/utils.py

"""
Utility functions module

Provides common utility functions used across the AsciiDoctor plugin:
- Git repository discovery
- File path validation
- HTML escaping
- Text slugification
- File modification time checking
"""

import pathlib
import re
from typing import Optional


def discover_git_root(start: pathlib.Path) -> Optional[pathlib.Path]:
    """Walk upward from `start` to find a directory containing .git. Return the path or None."""
    p = start
    try:
        for candidate in [p, *p.parents]:
            if (candidate / ".git").exists():
                return candidate.resolve()
    except Exception:
        pass
    return None


def is_valid_adoc_path(p: pathlib.Path) -> bool:
    try:
        if not p.exists():
            return False
        if p.is_dir():
            return False
        return True
    except OSError:
        return False


def safe_mtime(p: pathlib.Path) -> Optional[float]:
    try:
        return p.stat().st_mtime
    except (FileNotFoundError, OSError):
        return None


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_nonword = re.compile(r"[^0-9A-Za-z _-]+")
_spaces = re.compile(r"[ _]+")


def slugify(text: str) -> str:
    t = text.strip().lower()
    t = _nonword.sub("", t)
    t = _spaces.sub("-", t)
    return t
