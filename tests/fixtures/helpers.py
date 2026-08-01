"""Helper module used to exercise cross-file behaviour."""

HELPER_CONSTANT = 7
_UNUSED_PRIVATE = "dead"


def double(value: int) -> int:
    """Double a value."""
    return value * 2


def helper_function(value: int) -> int:
    """Add the helper constant to a value."""
    return value + HELPER_CONSTANT


def _private_unused(value: int) -> int:
    return value
