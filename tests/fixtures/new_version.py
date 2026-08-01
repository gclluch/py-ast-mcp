"""Version 2 of a module, used for diff_ast tests."""

import os
from pathlib import Path

VERSION = "2.0"
DEBUG = False
NEW_SETTING = 42


class Service:
    """A service."""

    def start(self, port: int, host: str = "0.0.0.0") -> None:
        self.port = port
        self.host = host

    def stop(self) -> None:
        pass

    def restart(self) -> None:
        self.stop()


class NewService(Service):
    """Added in v2."""

    def ping(self) -> bool:
        return True


def added_function(a: int) -> int:
    return a


def changed_signature(a: int, b: str = "x") -> str:
    return f"{a}{b}"


def same_function(a: int, b: int = 1) -> int:
    return a + b + 0
