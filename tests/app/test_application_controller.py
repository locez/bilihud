import asyncio

from bilihud.app import application_controller as application_module
from bilihud.app.application_controller import ApplicationController
from bilihud.app.lifecycle import TaskSupervisor
from bilihud.config.store import AppConfig


class FakeConfigStore:
    def save(self, _config: AppConfig) -> bool:
        return True


class FakeLiveControlService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def shutdown(self) -> None:
        self._events.append("live-shutdown")


class FakeMirrorCoordinator:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def apply_config(self, _config: AppConfig) -> None:
        self._events.append("mirror-config")

    async def shutdown(self) -> None:
        self._events.append("mirror-shutdown")


class FakeHudController:
    def __init__(self, **_kwargs) -> None:
        self._events = _kwargs["events"]

    async def shutdown(self) -> None:
        self._events.append("hud-shutdown")


class FakeAccountController:
    def __init__(self, **_kwargs) -> None:
        self._events = _kwargs["events"]

    async def shutdown(self) -> None:
        self._events.append("account-shutdown")


class FakeServices:
    def __init__(self, events: list[str]) -> None:
        self.config_store = FakeConfigStore()
        self.auth_service = object()
        self.hud_client_factory = object()
        self.live_control_service = FakeLiveControlService(events)
        self.mirror_coordinator = FakeMirrorCoordinator(events)


def test_application_shutdown_uses_one_owner_and_keeps_order(monkeypatch) -> None:
    async def run_test() -> None:
        events: list[str] = []

        class HudController(FakeHudController):
            def __init__(self, **kwargs) -> None:
                kwargs["events"] = events
                super().__init__(**kwargs)

        class AccountController(FakeAccountController):
            def __init__(self, **kwargs) -> None:
                kwargs["events"] = events
                super().__init__(**kwargs)

        monkeypatch.setattr(application_module, "HudController", HudController)
        monkeypatch.setattr(application_module, "AccountSessionController", AccountController)
        supervisor = TaskSupervisor()
        application_scope = supervisor.create_scope("application")
        services = FakeServices(events)
        application = ApplicationController(
            room_id=7450109,
            sessdata="",
            services=services,
            config=AppConfig(),
            task_scope=application_scope,
        )

        workflow_started = asyncio.Event()

        async def owned_workflow() -> None:
            workflow_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("application-tasks")
                raise

        application_scope.create_task(owned_workflow(), name="owned-workflow")
        await workflow_started.wait()
        await application.shutdown()
        await application.shutdown()
        await supervisor.shutdown()

        assert events == [
            "mirror-config",
            "account-shutdown",
            "live-shutdown",
            "hud-shutdown",
            "mirror-shutdown",
            "application-tasks",
        ]

    asyncio.run(run_test())
