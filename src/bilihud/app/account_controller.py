"""Application-owned authentication state and session cleanup workflows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..auth.service import (
    AccountLookupResult,
    AccountLookupStatus,
    AccountProfile,
    AuthenticationService,
)
from .lifecycle import TaskScope, cancel_task
from .menu import AccountStatus

logger = logging.getLogger(__name__)


class HudDisconnecter(Protocol):
    """Capability required to close an authenticated HUD consumer."""

    async def disconnect(self) -> None:
        """Close the active HUD connection."""
        ...


class LiveSessionCloser(Protocol):
    """Capability required to close an authenticated live-control session."""

    async def close(self) -> None:
        """Close the active live-control session."""
        ...


@dataclass(frozen=True, slots=True)
class AccountState:
    """Immutable account snapshot consumed by presentation surfaces."""

    status: AccountStatus = AccountStatus.UNKNOWN
    profile: AccountProfile | None = None


class AccountLogoutIssue(StrEnum):
    """Identify a cleanup step that failed during account logout."""

    HUD_DISCONNECT = "hud_disconnect"
    LIVE_SESSION_CLOSE = "live_session_close"
    SESSION_CLEAR = "session_clear"


@dataclass(frozen=True, slots=True)
class AccountLogoutResult:
    """Report secure-session removal and any consumer cleanup failures."""

    session_cleared: bool
    issues: tuple[AccountLogoutIssue, ...] = ()

    @property
    def succeeded(self) -> bool:
        """Return whether the saved authentication session was removed."""
        return self.session_cleared


AccountStateListener = Callable[[AccountState], None]


class AccountSessionController:
    """Own account lookup, session invalidation, and authenticated consumer cleanup."""

    def __init__(
        self,
        *,
        auth_service: AuthenticationService,
        hud_controller: HudDisconnecter,
        live_control_service: LiveSessionCloser,
        task_scope: TaskScope,
    ) -> None:
        """Create the controller with explicit services and task ownership."""
        self._auth_service = auth_service
        self._hud_controller = hud_controller
        self._live_control_service = live_control_service
        self._task_scope = task_scope
        self._state = AccountState()
        self._listeners: list[AccountStateListener] = []
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_generation = 0
        self._refresh_pending = False
        self._shutting_down = False

    @property
    def state(self) -> AccountState:
        """Return the latest normalized account snapshot."""
        return self._state

    def subscribe(self, listener: AccountStateListener) -> None:
        """Subscribe to account snapshots until the listener is removed."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: AccountStateListener) -> None:
        """Remove a previously registered account listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def start(self) -> asyncio.Task[None] | None:
        """Schedule one account lookup while retaining its task under this controller."""
        return self._schedule_refresh()

    def mark_login_succeeded(self) -> None:
        """Publish QR-login success and refresh the normalized account profile."""
        self._refresh_generation += 1
        self._set_state(AccountStatus.LOGGED_IN, None)
        self._schedule_refresh()

    def mark_login_expired(self) -> None:
        """Invalidate the visible account state after an authenticated request fails."""
        self._refresh_generation += 1
        self._refresh_pending = False
        self._set_state(AccountStatus.LOGIN_EXPIRED, None)

    async def logout(self) -> AccountLogoutResult:
        """Close authenticated consumers before clearing the secure session."""
        self._refresh_generation += 1
        self._refresh_pending = False
        await cancel_task(self._refresh_task)
        self._refresh_task = None

        issues: list[AccountLogoutIssue] = []
        try:
            await self._hud_controller.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to disconnect HUD during logout")
            issues.append(AccountLogoutIssue.HUD_DISCONNECT)

        try:
            await self._live_control_service.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to close live-control service during logout")
            issues.append(AccountLogoutIssue.LIVE_SESSION_CLOSE)

        try:
            session_cleared = self._auth_service.logout()
        except Exception:
            logger.exception("Failed to clear Bilibili session during logout")
            session_cleared = False

        if not session_cleared:
            issues.append(AccountLogoutIssue.SESSION_CLEAR)
            return AccountLogoutResult(False, tuple(issues))

        self._set_state(AccountStatus.LOGGED_OUT, None)
        return AccountLogoutResult(True, tuple(issues))

    async def shutdown(self) -> None:
        """Cancel account lookups without closing shared application services."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._refresh_generation += 1
        self._refresh_pending = False
        await cancel_task(self._refresh_task)
        self._refresh_task = None

    def _schedule_refresh(self) -> asyncio.Task[None] | None:
        """Queue one lookup and coalesce refresh requests while it is running."""
        if self._shutting_down:
            return None
        task = self._refresh_task
        if task is not None and not task.done():
            self._refresh_pending = True
            return task

        self._refresh_pending = False
        generation = self._refresh_generation
        self._set_state(AccountStatus.UNKNOWN, None)
        task = self._task_scope.create_task(
            self._refresh_account_state(generation),
            name="refresh-account",
        )
        self._refresh_task = task
        task.add_done_callback(self._clear_refresh_task)
        return task

    def _clear_refresh_task(self, task: asyncio.Task[None]) -> None:
        """Release a completed lookup and service one queued refresh request."""
        if self._refresh_task is not task:
            return
        self._refresh_task = None
        if self._refresh_pending and not self._shutting_down:
            self._schedule_refresh()

    async def _refresh_account_state(self, generation: int) -> None:
        """Resolve the secure session into a normalized account snapshot."""
        try:
            result = await self._auth_service.lookup_account()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to refresh account identity")
            if generation == self._refresh_generation:
                self._set_state(AccountStatus.UNAVAILABLE, None)
            return

        if generation != self._refresh_generation:
            return
        self._apply_lookup(result)

    def _apply_lookup(self, result: AccountLookupResult) -> None:
        """Map the authentication result into the stable account state contract."""
        if result.status is AccountLookupStatus.AUTHENTICATED:
            self._set_state(AccountStatus.LOGGED_IN, result.profile)
        elif result.status is AccountLookupStatus.NO_SESSION:
            self._set_state(AccountStatus.LOGGED_OUT, None)
        elif result.status is AccountLookupStatus.INVALID:
            self._set_state(AccountStatus.LOGIN_EXPIRED, None)
        else:
            self._set_state(AccountStatus.UNAVAILABLE, None)

    def _set_state(self, status: AccountStatus, profile: AccountProfile | None) -> None:
        """Publish a changed immutable account snapshot to all consumers."""
        state = AccountState(status, profile)
        if state == self._state:
            return
        self._state = state
        for listener in tuple(self._listeners):
            try:
                listener(state)
            except Exception:
                logger.exception("Account state listener failed")


__all__ = (
    "AccountLogoutIssue",
    "AccountLogoutResult",
    "AccountSessionController",
    "AccountState",
    "HudDisconnecter",
    "LiveSessionCloser",
)
