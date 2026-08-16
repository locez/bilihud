import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from bilihud.app.mirror_coordinator import (
    MirrorCoordinatorState,
    MirrorOperationResult,
)
from bilihud.config.store import AppConfig
from bilihud.danmaku.messages import HudMessage, SystemMessageLevel
from bilihud.mirror.state import MirrorDisplaySettings, MirrorEntry
from bilihud.ui.hud.mirror_controller import (
    MirrorController,
)


class FakeCoordinator:
    def __init__(self) -> None:
        self._state = MirrorCoordinatorState(
            enabled=True,
            running=True,
            port=2233,
            url="http://127.0.0.1:2233/bilihud-mirror",
        )
        self.shutdown_calls = 0
        self.failures = 0

    @property
    def state(self) -> MirrorCoordinatorState:
        return self._state

    @state.setter
    def state(self, value: MirrorCoordinatorState) -> None:
        self._state = value

    def apply_config(self, config: AppConfig) -> None:
        del config

    def apply_display_settings(self, settings: MirrorDisplaySettings) -> None:
        del settings

    async def start(self) -> MirrorOperationResult:
        return MirrorOperationResult(self.state)

    async def set_enabled(self, enabled: bool) -> MirrorOperationResult:
        self.state = MirrorCoordinatorState(
            enabled=enabled,
            running=enabled,
            port=self.state.port,
            url=self.state.url,
        )
        return MirrorOperationResult(self.state)

    def publish_message(self, message: HudMessage) -> MirrorEntry:
        del message
        return {
            "seq": 1,
            "kind": "danmaku",
            "user": "",
            "userColor": "",
            "segments": [],
        }

    async def shutdown(self) -> MirrorOperationResult:
        self.shutdown_calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("mirror close failed")
        self.state = MirrorCoordinatorState(
            enabled=self.state.enabled,
            running=False,
            port=self.state.port,
            url="http://127.0.0.1:2233/bilihud-mirror",
        )
        return MirrorOperationResult(self.state)


class FakeSettingsController:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def set_mirror_state(self) -> None:
        self.refresh_calls += 1


class FakeView:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.mirror_coordinator = coordinator
        self.settings_controller_fake = FakeSettingsController()
        self.settings_controller = self.settings_controller_fake
        self.messages: list[tuple[str, SystemMessageLevel]] = []
        self.tray_refreshes = 0

    def add_system_message(self, message: str, level: SystemMessageLevel) -> None:
        self.messages.append((message, level))

    def update_tray_menu_state(self) -> None:
        self.tray_refreshes += 1


def _controller(view: FakeView) -> MirrorController:
    def task_factory(coroutine: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
        return asyncio.create_task(coroutine, name=name)

    return MirrorController(
        view,
        task_factory=task_factory,
        is_shutting_down=lambda: False,
    )


def test_mirror_shutdown_preserves_enabled_preference_and_refreshes_settings() -> None:
    async def run_test() -> None:
        coordinator = FakeCoordinator()
        view = FakeView(coordinator)
        controller = _controller(view)

        result = await controller.shutdown()

        assert result.state.running is False
        assert result.state.enabled is True
        assert coordinator.shutdown_calls == 1
        assert view.settings_controller_fake.refresh_calls == 1

    asyncio.run(run_test())


def test_mirror_shutdown_preserves_coordinator_reference_after_failure() -> None:
    async def run_test() -> None:
        coordinator = FakeCoordinator()
        coordinator.failures = 1
        view = FakeView(coordinator)
        controller = _controller(view)

        with pytest.raises(RuntimeError, match="mirror close failed"):
            await controller.shutdown()
        assert coordinator.state.running is True

        result = await controller.shutdown()
        assert result.state.running is False
        assert coordinator.shutdown_calls == 2

    asyncio.run(run_test())
