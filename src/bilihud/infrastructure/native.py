"""Small typed helpers for loading optional native-library symbols."""

from __future__ import annotations

import ctypes
from typing import Protocol


class NativeFunction(Protocol):
    """Minimal typed view of a ctypes function pointer at the native boundary."""

    argtypes: list[object] | None
    restype: object | None

    def __call__(self, *arguments: object) -> object:
        """Invoke the configured native symbol."""


def load_native_function(
    library: ctypes.CDLL,
    symbol: str,
    argument_types: list[object],
    return_type: object | None = None,
) -> NativeFunction | None:
    """Resolve and type one required or optional symbol at the native boundary."""
    candidate: NativeFunction | None = getattr(library, symbol, None)
    if candidate is None or not callable(candidate):
        return None
    candidate.argtypes = argument_types
    candidate.restype = return_type
    return candidate
