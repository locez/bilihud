import asyncio

import pytest

from bilihud.app.mirror_coordinator import MirrorCoordinator
from bilihud.config.store import AppConfig
from bilihud.danmaku.messages import DanmakuMessage, MessageAuthor, TextSegment
from bilihud.mirror.state import MirrorDisplaySettings, MirrorEntry, MirrorState


class FakeConfigStore:
    def __init__(self, config: AppConfig, save_result: bool = True) -> None:
        self.config = config
        self.save_result = save_result
        self.saved: list[AppConfig] = []

    def load(self) -> AppConfig:
        return self.config

    def save(self, config: AppConfig) -> bool:
        self.saved.append(config)
        if self.save_result:
            self.config = config
        return self.save_result


class FakeServer:
    def __init__(self, port: int, *, stop_failures: int = 0, start_failure: bool = False) -> None:
        self.url = f"http://127.0.0.1:{port}/bilihud-mirror"
        self.stop_failures = stop_failures
        self.start_failure = start_failure
        self.start_calls = 0
        self.stop_calls = 0
        self.entries: list[MirrorEntry] = []
        self.display_settings = MirrorDisplaySettings()

    async def start(self) -> None:
        self.start_calls += 1
        if self.start_failure:
            raise OSError("address already in use")

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_calls <= self.stop_failures:
            raise RuntimeError("mirror close failed")

    def publish_append(self, entry: MirrorEntry) -> None:
        self.entries.append(entry)

    def set_display_settings(self, settings: MirrorDisplaySettings) -> None:
        self.display_settings = settings


def test_mirror_coordinator_owns_start_stop_and_message_publication():
    config_store = FakeConfigStore(
        AppConfig(
            mirror_enabled=True,
            mirror_port=9876,
            show_user_avatars=True,
            hud_font_family="Noto Sans CJK SC",
        )
    )
    server = FakeServer(9876)

    def factory(state: MirrorState, *, port: int, display_settings: MirrorDisplaySettings) -> FakeServer:
        del state
        assert port == 9876
        server.display_settings = display_settings
        return server

    coordinator = MirrorCoordinator(config_store=config_store, server_factory=factory)
    coordinator.load_settings()

    async def run_test() -> None:
        started = await coordinator.start()
        assert started.state.running is True
        assert started.notices[0].text.startswith("BiliHUD Mirror 已启动")
        assert server.display_settings.font_family == "Noto Sans CJK SC"
        assert server.display_settings.user_avatars_enabled is True

        coordinator.apply_display_settings(
            MirrorDisplaySettings(
                gift_effects_enabled=True,
                font_family="Microsoft YaHei",
                danmaku_x=20,
                danmaku_y=70,
            )
        )
        assert server.display_settings == MirrorDisplaySettings(
            gift_effects_enabled=True,
            font_family="Microsoft YaHei",
            danmaku_x=20,
            danmaku_y=70,
        )

        message = DanmakuMessage(
            author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
            segments=(TextSegment("测试"),),
        )
        entry = coordinator.publish_message(message)
        assert server.entries == [entry]
        assert coordinator.message_state.snapshot() == [entry]

        stopped = await coordinator.stop()
        assert stopped.state.enabled is True
        assert stopped.state.running is False
        assert server.stop_calls == 1

    asyncio.run(run_test())


def test_mirror_coordinator_persists_enabled_preference_without_dropping_other_config():
    config_store = FakeConfigStore(
        AppConfig(
            room_id=7450109,
            live_title="保留标题",
            mirror_port=9877,
            mirror_enabled=False,
        )
    )
    server = FakeServer(9877)

    def factory(state: MirrorState, *, port: int, display_settings: MirrorDisplaySettings) -> FakeServer:
        del state
        assert port == 9877
        server.display_settings = display_settings
        return server

    coordinator = MirrorCoordinator(config_store=config_store, server_factory=factory)
    coordinator.load_settings()

    async def run_test() -> None:
        await coordinator.set_enabled(True)
        assert config_store.saved[-1].mirror_enabled is True
        assert config_store.saved[-1].room_id == 7450109
        assert config_store.saved[-1].live_title == "保留标题"

        result = await coordinator.set_enabled(False)
        assert result.state.enabled is False
        assert result.state.running is False
        assert result.notices[-1].text == "BiliHUD Mirror 已停止。"
        assert config_store.saved[-1].mirror_enabled is False

    asyncio.run(run_test())


def test_mirror_coordinator_keeps_failed_server_for_retry_during_shutdown():
    config_store = FakeConfigStore(AppConfig(mirror_enabled=True))
    server = FakeServer(2233, stop_failures=1)

    def factory(state: MirrorState, *, port: int, display_settings: MirrorDisplaySettings) -> FakeServer:
        del state
        assert port == 2233
        server.display_settings = display_settings
        return server

    coordinator = MirrorCoordinator(config_store=config_store, server_factory=factory)
    coordinator.load_settings()

    async def run_test() -> None:
        await coordinator.start()
        with pytest.raises(RuntimeError, match="mirror close failed"):
            await coordinator.shutdown()
        assert coordinator.state.running is True

        await coordinator.shutdown()
        assert coordinator.state.running is False
        assert server.stop_calls == 2

    asyncio.run(run_test())


def test_mirror_coordinator_reports_bind_failure_without_claiming_server_ownership():
    config_store = FakeConfigStore(AppConfig(mirror_enabled=True, mirror_port=9988))
    server = FakeServer(9988, start_failure=True)

    def factory(state: MirrorState, *, port: int, display_settings: MirrorDisplaySettings) -> FakeServer:
        del state
        server.display_settings = display_settings
        return server

    coordinator = MirrorCoordinator(config_store=config_store, server_factory=factory)
    coordinator.load_settings()

    async def run_test() -> None:
        result = await coordinator.start()
        assert result.state.running is False
        assert result.state.error == "address already in use"
        assert result.notices[0].level.value == "error"

    asyncio.run(run_test())
