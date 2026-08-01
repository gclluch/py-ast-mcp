"""Sample module exercising most of the Python surface py-ast-mcp cares about.

It defines protocols, dataclasses, enums, TypedDicts, NamedTuples, async
functions, decorators, comprehensions and a match statement.
"""

from __future__ import annotations

import asyncio
import enum as _enum
import os
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Optional, Protocol, TypeAlias, TypedDict

from . import helpers
from .helpers import HELPER_CONSTANT, helper_function as aliased_helper

__all__ = ["Repository", "Widget", "Color", "process", "main", "PathLike"]

PathLike: TypeAlias = str | os.PathLike[str]
DEFAULT_TIMEOUT = 30
RETRIES: int = 3
NAMES = ["alpha", "beta"]
_PRIVATE_CACHE: dict[str, Any] = {}
UNUSED_CONSTANT = "nobody reads me"


class Color(_enum.Enum):
    """Colours a widget may take."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class WidgetDict(TypedDict):
    name: str
    color: str


class Point(NamedTuple):
    x: float
    y: float


class Repository(Protocol):
    """Anything that can fetch and store records by id."""

    def get(self, key: str) -> dict[str, Any] | None:
        """Fetch a record."""
        ...

    def put(self, key: str, value: dict[str, Any]) -> None:
        """Store a record."""
        ...


class InMemoryRepository:
    """Structural implementation of :class:`Repository`."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value

    def _evict(self) -> None:
        self._store.clear()


class BaseWidget:
    """Base class providing shared widget behaviour."""

    kind = "base"

    def describe(self) -> str:
        return f"{self.kind} widget"

    def render(self) -> str:
        return self.describe()


@dataclass
class Widget(BaseWidget):
    """A widget with a name and colour.

    Args:
        name: Human readable label.
        color: The widget colour.
        tags: Optional free-form tags.

    Returns:
        Nothing; this is a data container.

    Raises:
        ValueError: If the name is empty.
    """

    name: str
    color: Color = Color.RED
    tags: list[str] = field(default_factory=list)

    kind = "widget"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")

    @property
    def slug(self) -> str:
        """URL-safe form of the name."""
        return self.name.lower().replace(" ", "-")

    @staticmethod
    def palette() -> list[Color]:
        return [c for c in Color]

    @classmethod
    def build(cls, name: str, *, color: Color = Color.BLUE) -> "Widget":
        return cls(name=name, color=color)

    def render(self) -> str:
        return f"<{self.slug} {self.color.value}>"

    def classify(self, score: int) -> str:
        """Classify a score using a match statement.

        Parameters
        ----------
        score : int
            The score to classify.

        Returns
        -------
        str
            A textual band.
        """
        match score:
            case 0:
                return "zero"
            case n if n < 0:
                return "negative"
            case 1 | 2 | 3:
                return "small"
            case _:
                return "large"


def process(items: list[str], /, prefix: str = "", *extra: str, upper: bool = False,
            **options: Any) -> list[str]:
    """Process a list of items.

    Args:
        items: Items to process.
        prefix: String to prepend to every item.
        extra: Additional items appended to the batch.
        upper: Whether to upper-case the result.
        options: Ignored extra options.

    Returns:
        The processed items.
    """
    combined = [*items, *extra]
    result = [prefix + item for item in combined if item]
    if upper:
        result = [r.upper() for r in result]
    _PRIVATE_CACHE["last"] = result
    return result


def make_callbacks(names: list[str]) -> list[Any]:
    callbacks = []
    for name in names:
        callbacks.append(lambda: name)
    return callbacks


async def fetch_one(key: str, repo: Repository) -> dict[str, Any] | None:
    """Fetch a single record asynchronously."""
    await asyncio.sleep(0)
    return repo.get(key)


async def fetch_all(keys: list[str], repo: Repository) -> list[Any]:
    results = []
    for key in keys:
        results.append(await fetch_one(key, repo))
    return results


def _internal_helper(value: int) -> int:
    return value * 2


def _never_called(value: int) -> int:
    """Nothing in the package references this."""
    return value + 1


def outer(n: int) -> int:
    def inner(m: int) -> int:
        return _internal_helper(m)

    return inner(n) + helpers.double(n) + aliased_helper(n) + HELPER_CONSTANT


def main() -> int:
    """Entry point."""
    repo = InMemoryRepository()
    widget = Widget.build("Hello World")
    repo.put(widget.slug, {"name": widget.name})
    print(process(NAMES, prefix="x-"), widget.render(), outer(DEFAULT_TIMEOUT))
    return 0
