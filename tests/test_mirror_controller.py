import asyncio

import pytest

from bilihud.app.mirror_coordinator import MirrorCoordinatorState, MirrorOperationResult
from bilihud.ui.hud.mirror_controller import MirrorController


class FakeCoordinator:
    def __init__(self) -> None:
        self.state = MirrorCoordinatorState(
            enabled=True,
            running=True,
            port=2233,
            url="http://127.0.0.1:2233/bilihud-mirror",
        )
        self.shutdown_calls = 0
        self.failures = 0

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
        self.settings_controller = FakeSettingsController()
        self.messages: list[tuple[str, object]] = []
        self.tray_refreshes = 0

    def add_system_message(self, message: str, level: object) -> None:
        self.messages.append((message, level))

    def update_tray_menu_state(self) -> None:
        self.tray_refreshes += 1


def _controller(view: FakeView) -> MirrorController:
    def task_factory(coroutine, name: str):
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
        assert view.settings_controller.refresh_calls == 1

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
