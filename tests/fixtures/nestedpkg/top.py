"""Top-level module of the nested fixture package."""

from __future__ import annotations


def shared_helper(value: int) -> int:
    """Referenced from nestedpkg/sub/deep.py, one directory down."""
    return value * 2
