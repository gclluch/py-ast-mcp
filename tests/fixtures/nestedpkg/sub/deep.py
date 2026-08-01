"""Lives one directory below the module it imports from.

The reference to ``shared_helper`` below crosses a directory boundary, which is
what a project root pinned to this file's own folder cannot see.
"""

from __future__ import annotations

from ..top import shared_helper


def use_helper(n: int) -> int:
    return shared_helper(n) + 1


def deep_helper(n: int) -> int:
    """Referenced from nestedpkg/other/consumer.py, a sibling directory."""
    return n + 100
