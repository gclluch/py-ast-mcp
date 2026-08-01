"""Dataclass field defaults. The reported ones are import-time ValueErrors."""

from dataclasses import InitVar, dataclass, field
from typing import ClassVar


@dataclass
class Crashes:
    tags: list = []
    mapping: dict = {}
    lookup: set = set()
    boxed: bytearray = bytearray()


@dataclass(frozen=True, slots=True)
class CrashesWithArgs:
    items: list = []


@dataclass
class Fine:
    tags: list = field(default_factory=list)
    name: str = "ok"
    count: int = 0
    registry: ClassVar[dict] = {}
    seed: InitVar[list] = []
    untyped_attr = []


class NotADataclass:
    """No decorator, so nothing raises - a plain shared class attribute."""

    tags: list = []
