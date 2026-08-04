import asyncio

from bilihud.app.account_controller import (
    AccountLogoutIssue,
    AccountSessionController,
)
from bilihud.app.lifecycle import TaskSupervisor
from bilihud.auth.account import AccountLookupResult, AccountLookupStatus, AccountProfile


class FakeAuthenticationService:
    def __init__(self, lookup_result: AccountLookupResult, *, logout_result: bool = True) -> None:
        self.lookup_result = lookup_result
        self.logout_result = logout_result
        self.events: list[str] = []

    async def lookup_account(self) -> AccountLookupResult:
        self.events.append("lookup")
        return self.lookup_result

    def logout(self) -> bool:
        self.events.append("logout")
        return self.logout_result


class FakeHudController:
    def __init__(self, events: list[str], *, failure: Exception | None = None) -> None:
        self._events = events
        self._failure = failure

    async def disconnect(self) -> None:
        self._events.append("hud-disconnect")
        if self._failure is not None:
            raise self._failure


class FakeLiveControlService:
    def __init__(self, events: list[str], *, failure: Exception | None = None) -> None:
        self._events = events
        self._failure = failure

    async def close(self) -> None:
        self._events.append("live-close")
        if self._failure is not None:
            raise self._failure


def test_account_lookup_publishes_normalized_state() -> None:
    async def run_test() -> None:
        profile = AccountProfile("123", "测试用户")
        auth = FakeAuthenticationService(
            AccountLookupResult(AccountLookupStatus.AUTHENTICATED, profile)
        )
        supervisor = TaskSupervisor()
        controller = AccountSessionController(
            auth_service=auth,
            hud_controller=FakeHudController([]),
            live_control_service=FakeLiveControlService([]),
            task_scope=supervisor.create_scope("account"),
        )
        states = []
        controller.subscribe(states.append)

        task = controller.start()
        assert task is not None
        await task
        await controller.shutdown()
        await supervisor.shutdown()

        assert controller.state.profile == profile
        assert controller.state.status.value == "logged_in"
        assert states[-1] == controller.state
        assert auth.events == ["lookup"]

    asyncio.run(run_test())


def test_logout_closes_consumers_before_clearing_secure_session() -> None:
    async def run_test() -> None:
        events: list[str] = []
        auth = FakeAuthenticationService(
            AccountLookupResult(AccountLookupStatus.NO_SESSION),
        )
        auth.events = events
        supervisor = TaskSupervisor()
        controller = AccountSessionController(
            auth_service=auth,
            hud_controller=FakeHudController(events),
            live_control_service=FakeLiveControlService(events),
            task_scope=supervisor.create_scope("account"),
        )

        result = await controller.logout()
        await controller.shutdown()
        await supervisor.shutdown()

        assert result.succeeded is True
        assert result.issues == ()
        assert events == ["hud-disconnect", "live-close", "logout"]

    asyncio.run(run_test())


def test_logout_reports_cleanup_failures_but_still_attempts_session_clear() -> None:
    async def run_test() -> None:
        events: list[str] = []
        auth = FakeAuthenticationService(
            AccountLookupResult(AccountLookupStatus.NO_SESSION),
            logout_result=False,
        )
        auth.events = events
        supervisor = TaskSupervisor()
        controller = AccountSessionController(
            auth_service=auth,
            hud_controller=FakeHudController(events, failure=RuntimeError("HUD close failed")),
            live_control_service=FakeLiveControlService(
                events,
                failure=RuntimeError("live close failed"),
            ),
            task_scope=supervisor.create_scope("account"),
        )

        result = await controller.logout()
        await controller.shutdown()
        await supervisor.shutdown()

        assert result.succeeded is False
        assert result.issues == (
            AccountLogoutIssue.HUD_DISCONNECT,
            AccountLogoutIssue.LIVE_SESSION_CLOSE,
            AccountLogoutIssue.SESSION_CLEAR,
        )
        assert events == ["hud-disconnect", "live-close", "logout"]

    asyncio.run(run_test())
