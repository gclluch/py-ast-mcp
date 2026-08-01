"""Version 1 of a module, used for diff_ast tests."""

import os
import sys

VERSION = "1.0"
DEBUG = False


class Service:
    """A service."""

    def start(self, port: int) -> None:
        self.port = port

    def stop(self) -> None:
        pass

    def legacy(self) -> str:
        return "old"


def removed_function(a: int) -> int:
    return a


def changed_signature(a: int) -> int:
    return a


def same_function(a: int, b: int = 1) -> int:
    return a + b
