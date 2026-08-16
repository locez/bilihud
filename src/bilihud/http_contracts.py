"""Small HTTP protocols shared by application-owned network workflows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol, runtime_checkable

QueryValue = str | int | float
QueryParams = Mapping[str, QueryValue] | Iterable[tuple[str, QueryValue]]


@runtime_checkable
class HttpCookie(Protocol):
    """Cookie fields consumed by authenticated live-room requests."""

    key: str
    value: str


class HttpResponse(Protocol):
    """Response surface required by the normalized API adapters."""

    status: int

    async def __aenter__(self) -> HttpResponse:
        """Enter the response context owned by one request."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Release the response context."""
        ...

    async def json(self, *, content_type: str | None = None) -> object:
        """Decode the response body at the external-data boundary."""
        ...


class HttpSession(Protocol):
    """Owned HTTP session capability used by live-room workflows."""

    closed: bool

    @property
    def cookie_jar(self) -> Iterable[HttpCookie]:
        """Return the iterable cookie view used for CSRF extraction."""
        ...

    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AbstractAsyncContextManager[HttpResponse]:
        """Start one GET request with optional query and request headers."""
        ...

    def post(
        self,
        url: str,
        *,
        data: object | None = None,
    ) -> AbstractAsyncContextManager[HttpResponse]:
        """Start one POST request with an application-owned payload."""
        ...

    async def close(self) -> None:
        """Close the session and release its transport resources."""
        ...


__all__ = ("HttpCookie", "HttpResponse", "HttpSession", "QueryParams", "QueryValue")
