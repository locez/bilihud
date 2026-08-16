import asyncio
from dataclasses import replace
from io import BytesIO

from bilihud.app import application_controller as application_module
from bilihud.app.application_controller import ApplicationController
from bilihud.app.lifecycle import TaskSupervisor
from bilihud.app.mirror_coordinator import MirrorCoordinatorState, MirrorOperationResult
from bilihud.app.services import create_default_services
from bilihud.config.store import AppConfig
from bilihud.danmaku.messages import HudMessage
from bilihud.live.models import (
    LiveControlOperationResult,
    LiveControlSettings,
    LiveControlState,
    ObsCheckOutcome,
    ObsSettings,
    ObsStreamOutcome,
    SettingsSaveOutcome,
    StartLiveOutcome,
    StopLiveOutcome,
)
from bilihud.mirror.state import MirrorDisplaySettings, MirrorEntry


class FakeConfigStore:
    def load(self) -> AppConfig:
        return AppConfig()

    def save(self, _config: AppConfig) -> bool:
        return True


class FakeLiveControlService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    @property
    def state(self) -> LiveControlState:
        raise AssertionError("live state is not used in this shutdown test")

    def load_settings(self) -> LiveControlSettings:
        raise AssertionError("live settings are not used in this shutdown test")

    def save_settings(self, _settings: LiveControlSettings) -> SettingsSaveOutcome:
        raise AssertionError("live settings are not used in this shutdown test")

    def generate_qr_image(self, _url: str) -> BytesIO | None:
        raise AssertionError("live QR is not used in this shutdown test")

    async def initialize(self, _room_id: int | None) -> LiveControlOperationResult:
        raise AssertionError("live initialization is not used in this shutdown test")

    async def load_room_info(self, _room_id: int | None) -> LiveControlOperationResult:
        raise AssertionError("live room loading is not used in this shutdown test")

    async def update_title(self, _room_id: int | None, _title: str) -> LiveControlOperationResult:
        raise AssertionError("live title updates are not used in this shutdown test")

    async def update_area(self, _room_id: int | None, _area_id: str) -> LiveControlOperationResult:
        raise AssertionError("live area updates are not used in this shutdown test")

    async def start_live(
        self,
        _room_id: int | None,
        _title: str,
        _area_id: str,
        _obs_settings: ObsSettings | None,
        *,
        allow_obs_switch: bool = False,
    ) -> StartLiveOutcome:
        del allow_obs_switch
        raise AssertionError("live start is not used in this shutdown test")

    async def stop_live(
        self,
        _room_id: int | None,
        _obs_settings: ObsSettings | None,
    ) -> StopLiveOutcome:
        raise AssertionError("live stop is not used in this shutdown test")

    async def check_obs(self, _settings: ObsSettings | None) -> ObsCheckOutcome:
        raise AssertionError("OBS checks are not used in this shutdown test")

    async def stop_obs_stream(self, _settings: ObsSettings | None) -> ObsStreamOutcome:
        raise AssertionError("OBS stopping is not used in this shutdown test")

    async def close(self) -> None:
        raise AssertionError("live close is not used in this shutdown test")

    async def shutdown(self) -> None:
        self._events.append("live-shutdown")


class FakeMirrorCoordinator:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.state = MirrorCoordinatorState(
            enabled=False,
            running=False,
            port=2233,
            url="http://127.0.0.1:2233/bilihud-mirror",
        )

    def apply_config(self, _config: AppConfig) -> None:
        self._events.append("mirror-config")

    def apply_display_settings(self, _settings: MirrorDisplaySettings) -> None:
        raise AssertionError("Mirror display settings are not used in this shutdown test")

    async def start(self) -> MirrorOperationResult:
        raise AssertionError("Mirror start is not used in this shutdown test")

    async def set_enabled(self, _enabled: bool) -> MirrorOperationResult:
        raise AssertionError("Mirror toggling is not used in this shutdown test")

    def publish_message(self, _message: HudMessage) -> MirrorEntry:
        raise AssertionError("Mirror messages are not used in this shutdown test")

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
        services = replace(
            create_default_services(),
            config_store=FakeConfigStore(),
            live_control_service=FakeLiveControlService(events),
            mirror_coordinator=FakeMirrorCoordinator(events),
        )
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
