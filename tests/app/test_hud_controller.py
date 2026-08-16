import asyncio
from collections.abc import Mapping

import aiohttp

from bilihud.app.hud import (
    HudConnectionStatus,
    HudLoginFailed,
    HudMessageReceived,
    HudOperation,
    HudOperationFailed,
    HudStateChanged,
)
from bilihud.app.hud_controller import HudController
from bilihud.config.store import AppConfig
from bilihud.danmaku.messages import DanmakuMessage, MessageAuthor, TextSegment
from bilihud.live.audience import AudienceSnapshot


class FakeConfigStore:
    def __init__(self):
        self.config = AppConfig()
        self.saved = []

    def load(self):
        return self.config

    def save(self, config):
        self.config = config
        self.saved.append(config)
        return True


class FakeClient:
    def __init__(self, room_id, *, stop_error=None):
        self.room_id = room_id
        self.stop_error = stop_error
        self.started = False
        self.running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.message_callback = None
        self.login_failed_callback = None
        self.audience_snapshot = AudienceSnapshot(room_id, 1, 2, 0, ())
        self.send_started = asyncio.Event()
        self.send_release = asyncio.Event()
        self.stop_started = asyncio.Event()
        self.block_send = False

    @property
    def is_running(self):
        return self.running

    def set_message_callback(self, callback):
        self.message_callback = callback

    def set_login_failed_callback(self, callback):
        self.login_failed_callback = callback

    async def start(self):
        self.start_calls += 1
        self.started = True
        self.running = True

    async def stop(self):
        self.stop_calls += 1
        self.stop_started.set()
        if self.stop_error is not None:
            error = self.stop_error
            self.stop_error = None
            raise error
        self.running = False

    async def send_danmaku(self, _message):
        if self.block_send:
            self.send_started.set()
            await self.send_release.wait()
        return True, "发送成功"

    async def fetch_audience_snapshot(self):
        return self.audience_snapshot

    async def fetch_live_emoticons(self):
        return []

    async def send_live_emoticon(self, _emoticon):
        return True, "发送成功"

    def emit_message(self, message):
        if self.message_callback is not None:
            self.message_callback(message)

    def emit_login_failure(self, message):
        if self.login_failed_callback is not None:
            self.login_failed_callback(message)


class FakeAuthenticationService:
    """Typed authentication boundary for HUD tests that never open a session."""

    def load_auth_cookies(self) -> tuple[dict[str, str], bool]:
        return {}, False

    async def validate_session(self, cookies: Mapping[str, str]) -> bool:
        del cookies
        return False

    def create_session_from_cookies(self, cookies: Mapping[str, str]) -> aiohttp.ClientSession:
        del cookies
        raise AssertionError("the fake HUD client does not create a network session")


def _message(text):
    return DanmakuMessage(
        author=MessageAuthor(uid=1, name="user", color="#fff"),
        segments=(TextSegment(text),),
    )


def _controller(factory, config_store=None):
    return HudController(
        initial_room_id=0,
        sessdata="",
        auth_service=FakeAuthenticationService(),
        client_factory=factory,
        config_store=config_store,
    )


def test_controller_reuses_same_room_and_discards_old_client_events():
    async def run_test():
        clients = []
        events = []
        config_store = FakeConfigStore()

        def factory(room_id, _sessdata, _auth_service):
            client = FakeClient(room_id)
            clients.append(client)
            return client

        controller = _controller(factory, config_store)
        controller.subscribe(events.append)

        await controller.connect(100)
        await controller.connect(100)
        assert len(clients) == 1
        assert clients[0].start_calls == 1

        first_message = _message("first")
        clients[0].emit_message(first_message)
        assert any(
            isinstance(event, HudMessageReceived) and event.message == first_message
            for event in events
        )

        await controller.connect(200)
        assert len(clients) == 2
        assert clients[0].stop_calls == 1
        assert clients[1].started is True
        assert controller.state.connection is HudConnectionStatus.CONNECTED
        assert controller.state.room_id == 200
        assert [config.room_id for config in config_store.saved] == [100, 200]

        event_count = len([event for event in events if isinstance(event, HudMessageReceived)])
        clients[0].emit_message(_message("stale"))
        clients[1].emit_message(_message("current"))
        assert len([event for event in events if isinstance(event, HudMessageReceived)]) == event_count + 1

        await controller.shutdown()
        assert clients[1].stop_calls == 1

    asyncio.run(run_test())


def test_controller_publishes_login_failure_and_operation_errors():
    async def run_test():
        events = []
        client = FakeClient(100)
        controller = _controller(lambda *_args: client)
        controller.subscribe(events.append)

        await controller.connect(100)
        client.emit_login_failure("登录已失效")
        assert any(
            isinstance(event, HudLoginFailed) and event.message == "登录已失效"
            for event in events
        )
        assert controller.state.error == "登录已失效"

        result = await controller.send_danmaku("hello")
        assert result.success is True
        assert controller.state.error is None

        client.stop_error = RuntimeError("close failed")
        try:
            await controller.disconnect()
        except RuntimeError as exc:
            assert str(exc) == "close failed"
        else:
            raise AssertionError("disconnect should expose the cleanup failure")

        assert controller.state.connection is HudConnectionStatus.CONNECTED
        assert controller.state.error == "close failed"
        assert any(
            isinstance(event, HudOperationFailed)
            and event.operation is HudOperation.DISCONNECT
            and event.message == "close failed"
            for event in events
        )

        await controller.disconnect()
        await controller.shutdown()

    asyncio.run(run_test())


def test_controller_serializes_send_and_disconnect():
    async def run_test():
        client = FakeClient(100)
        controller = _controller(lambda *_args: client)
        await controller.connect(100)
        client.block_send = True

        send_task = asyncio.create_task(controller.send_danmaku("hello"))
        await client.send_started.wait()
        disconnect_task = asyncio.create_task(controller.disconnect())
        assert disconnect_task.done() is False
        assert client.stop_started.is_set() is False

        client.send_release.set()
        result = await send_task
        await disconnect_task
        assert result.success is True
        assert controller.state.connection is HudConnectionStatus.DISCONNECTED
        await controller.shutdown()

    asyncio.run(run_test())


def test_controller_ignores_audience_result_from_old_room_generation():
    class SlowAudienceClient(FakeClient):
        def __init__(self, room_id):
            super().__init__(room_id)
            self.audience_started = asyncio.Event()
            self.cancel_seen = asyncio.Event()
            self.audience_release = asyncio.Event()

        async def fetch_audience_snapshot(self):
            self.audience_started.set()
            try:
                await self.audience_release.wait()
            except asyncio.CancelledError:
                self.cancel_seen.set()
                await self.audience_release.wait()
            return self.audience_snapshot

    async def run_test():
        clients = []
        audience_applied = asyncio.Event()

        def factory(room_id, _sessdata, _auth_service):
            client = SlowAudienceClient(room_id) if room_id == 100 else FakeClient(room_id)
            clients.append(client)
            return client

        controller = _controller(factory)

        def on_event(event):
            if isinstance(event, HudStateChanged) and event.state.audience_snapshot is not None:
                audience_applied.set()

        controller.subscribe(on_event)
        await controller.connect(100)
        slow_client = clients[0]
        await slow_client.audience_started.wait()

        switch_task = asyncio.create_task(controller.connect(200))
        await slow_client.cancel_seen.wait()
        slow_client.audience_release.set()
        await switch_task
        await asyncio.wait_for(audience_applied.wait(), timeout=1.0)

        assert controller.state.room_id == 200
        assert controller.state.audience_snapshot is not None
        assert controller.state.audience_snapshot.room_id == 200
        await controller.shutdown()

    asyncio.run(run_test())
