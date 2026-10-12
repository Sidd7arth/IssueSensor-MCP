"""Pure repository-inspection helpers, maintained for backward compatibility.

All implementation logic resides in the modular `repromcp.workspace` package.
"""
from __future__ import annotations

from repromcp.workspace import (
    ALLOWED_IMAGE_SUFFIXES,
    IGNORE_DIRS,
    MAX_FILE_BYTES,
    MAX_IMAGE_BYTES,
    MAX_MATCHES,
    SECRET_FILENAMES,
    SECRET_SUFFIXES,
    is_ignored,
    iter_text_files,
    ranked_matches,
    relative,
    resolve_screenshot,
)

__all__ = [
    "ALLOWED_IMAGE_SUFFIXES",
    "IGNORE_DIRS",
    "MAX_FILE_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_MATCHES",
    "SECRET_FILENAMES",
    "SECRET_SUFFIXES",
    "is_ignored",
    "iter_text_files",
    "ranked_matches",
    "relative",
    "resolve_screenshot",
]
