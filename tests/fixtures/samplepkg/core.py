"""Core engine."""

from abc import ABC, abstractmethod
from typing import Protocol

from .util import normalize, validate


class Serializer(Protocol):
    """Anything able to dump and load payloads."""

    def dumps(self, obj: dict) -> str: ...

    def loads(self, text: str) -> dict: ...


class Storage(ABC):
    """Abstract storage backend."""

    @abstractmethod
    def save(self, key: str, blob: str) -> None: ...

    @abstractmethod
    def load(self, key: str) -> str: ...


class MemoryStorage(Storage):
    """Explicit ABC implementation."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def save(self, key: str, blob: str) -> None:
        self._items[key] = blob

    def load(self, key: str) -> str:
        return self._items[key]


class JsonSerializer:
    """Structural implementation of Serializer."""

    def dumps(self, obj: dict) -> str:
        return repr(obj)

    def loads(self, text: str) -> dict:
        return eval(text)


class Engine:
    """Ties storage and serialization together."""

    def __init__(self, storage: Storage, serializer: Serializer) -> None:
        self.storage = storage
        self.serializer = serializer

    def store(self, key: str, payload: dict) -> None:
        validate(payload)
        self.storage.save(normalize(key), self.serializer.dumps(payload))

    def fetch(self, key: str) -> dict:
        return self.serializer.loads(self.storage.load(normalize(key)))


def run_pipeline(keys: list[str]) -> list[dict]:
    """Round-trip a batch of keys through the engine."""
    engine = Engine(MemoryStorage(), JsonSerializer())
    out = []
    for key in keys:
        engine.store(key, {"key": key})
        out.append(engine.fetch(key))
    return out
