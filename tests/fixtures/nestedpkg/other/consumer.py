"""Sibling of ``sub/`` - neither directory contains the other.

References from here are invisible to a project root pinned to ``sub/``, which
is exactly the geometry a flat or strictly-nested fixture cannot reproduce.
"""

from __future__ import annotations

from ..sub.deep import deep_helper


def consume(n: int) -> int:
    return deep_helper(n) * 3
