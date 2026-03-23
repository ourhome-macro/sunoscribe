"""Backward-compatible shim for typo filename.

Prefer importing from `app.modules.vocal.separator`.
"""

from .separator import SeparationError, SeparationResult, VocalSeparator

__all__ = ["VocalSeparator", "SeparationResult", "SeparationError"]
