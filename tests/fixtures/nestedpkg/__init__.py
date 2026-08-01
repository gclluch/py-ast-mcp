"""Nested fixture package: two levels deep, unlike the flat samplepkg.

Exists so that cross-*directory* resolution is exercised. A flat package
cannot catch a project root that is wrongly pinned to the file's own folder.
"""

from .top import shared_helper

__all__ = ["shared_helper"]
