"""Utility helpers."""


def normalize(key: str) -> str:
    """Lower-case and strip a key."""
    return key.strip().lower()


def validate(payload: dict) -> None:
    """Raise if the payload is not a dict."""
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")


def _unused_private(value: int) -> int:
    return value
