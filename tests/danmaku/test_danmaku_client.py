import asyncio
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

from bilihud.danmaku import client as danmaku_client
from bilihud.danmaku.client import DanmakuClient, DanmakuHandler, DanmakuShutdownError
from bilihud.danmaku.messages import DanmakuMessage, GiftMessage, HudMessage, InteractionKind, InteractMessage
from bilihud.http_contracts import HttpResponse, QueryParams
from bilihud.live.emoticons import LiveEmoticon
from bilihud.live.gift_effects import FULL_SCREEN_EFFECT_CONFIG_URL, GiftEffectCatalog


class FakeWebSocketClient(danmaku_client.ws_base.WebSocketClientBase):
    """Type marker for handler callbacks that do not inspect websocket state."""

    def __init__(self) -> None:
        pass


def test_start_starts_blivedm_client_and_reports_missing_login(monkeypatch):
    class FakeAuthManager:
        def load_auth_cookies(self):
            return {}, False

        def create_session_from_cookies(self, _cookies):
            return FakeSession()

    class FakeBLiveClient:
        def __init__(self, room_id, *, session):
            self.room_id = room_id
            self.session = session
            self.start_calls = 0
            self.handler = None
            created_clients.append(self)

        @property
        def is_running(self):
            return self.start_calls > 0

        def set_handler(self, handler):
            self.handler = handler

        def start(self):
            self.start_calls += 1

    created_clients: list[FakeBLiveClient] = []

    async def run_test():
        monkeypatch.setattr(danmaku_client, "AuthManager", FakeAuthManager)
        monkeypatch.setattr(danmaku_client.blivedm, "BLiveClient", FakeBLiveClient)

        client = DanmakuClient(7450109)
        login_failures = []
        client.set_login_failed_callback(login_failures.append)

        await client.start()

        assert client.client is not None
        assert created_clients[0].start_calls == 1
        assert client.client.is_running is True
        assert login_failures == ["未找到有效登录信息，请扫码登录"]

    asyncio.run(run_test())


def test_handler_emits_normalized_domain_messages():
    client = DanmakuClient(7450109)
    received: list[HudMessage] = []
    websocket = FakeWebSocketClient()
    client.set_message_callback(received.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)

    handler._on_danmaku(websocket, danmaku_client.web_models.DanmakuMessage(uname="弹幕用户", msg="你好"))
    handler._on_gift(websocket, danmaku_client.web_models.GiftMessage(uname="礼物用户", gift_name="辣条", num=1))
    handler._on_interact_word_v2(
        websocket,
        danmaku_client.web_models.InteractWordV2Message(username="互动用户", msg_type=2),
    )

    assert isinstance(received[0], DanmakuMessage)
    assert isinstance(received[1], GiftMessage)
    assert isinstance(received[2], InteractMessage)
    assert [message.author.name for message in received] == ["弹幕用户", "礼物用户", "互动用户"]


def test_handler_emits_web_like_click_as_normalized_interaction():
    client = DanmakuClient(7450109)
    received: list[HudMessage] = []
    websocket = FakeWebSocketClient()
    client.set_message_callback(received.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)

    handler.handle(
        websocket,
        {
            "cmd": "LIKE_INFO_V3_CLICK",
            "data": {
                "uid": 7,
                "uname": "点赞用户",
                "like_text": "为主播点赞了",
                "msg_type": 6,
            },
        },
    )

    assert len(received) == 1
    message = received[0]
    assert isinstance(message, InteractMessage)
    assert message.author.uid == 7
    assert message.author.name == "点赞用户"
    assert message.interaction is InteractionKind.LIKE
    assert message.segments[0].text == "为主播点赞了"


def test_handler_updates_room_total_likes_without_emitting_a_message():
    client = DanmakuClient(7450109)
    received: list[HudMessage] = []
    total_likes: list[int] = []
    websocket = FakeWebSocketClient()
    client.set_message_callback(received.append)
    client.set_total_likes_callback(total_likes.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)

    handler.handle(
        websocket,
        {
            "cmd": "LIKE_INFO_V3_UPDATE",
            "data": {"click_count": 543},
        },
    )

    assert received == []
    assert total_likes == [543]


def test_handler_emits_voice_report_like_users_as_interactions():
    client = DanmakuClient(7450109)
    received: list[HudMessage] = []
    websocket = FakeWebSocketClient()
    client.set_message_callback(received.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)

    handler.handle(
        websocket,
        {
            "cmd": "VOICE_REPORT_LIKE",
            "data": {
                "anchor_id": 6003771,
                "live_id": 723541469275729405,
                "users": [{"uid": 319093111, "uname": "凌末淡花"}],
                "count": 1,
            },
        },
    )

    assert len(received) == 1
    message = received[0]
    assert isinstance(message, InteractMessage)
    assert message.author.uid == 319093111
    assert message.author.name == "凌末淡花"
    assert message.interaction is InteractionKind.LIKE
    assert message.count == 1
    assert message.text == "为主播点赞了"


def test_handler_preserves_voice_report_like_count_for_one_user():
    client = DanmakuClient(7450109)
    received: list[HudMessage] = []
    websocket = FakeWebSocketClient()
    client.set_message_callback(received.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)

    handler.handle(
        websocket,
        {
            "cmd": "VOICE_REPORT_LIKE",
            "data": {
                "users": [{"uid": 319093111, "uname": "凌末淡花"}],
                "count": 3,
            },
        },
    )

    assert len(received) == 1
    message = received[0]
    assert isinstance(message, InteractMessage)
    assert message.count == 3
    assert message.text == "为主播点赞了 x3"


def test_handler_resolves_official_gift_resources_before_delivery():
    async def run_test():
        raw_gift = {
            "giftName": "浪漫城堡",
            "num": 1,
            "uname": "礼物用户",
            "face": "",
            "guard_level": 0,
            "uid": 3,
            "timestamp": 1,
            "giftId": 32132,
            "giftType": 0,
            "gift_info": {
                "img_basic": "https://i0.hdslb.com/bfs/live/castle.png",
                "gif": "https://i0.hdslb.com/bfs/live/castle.gif",
            },
            "action": "赠送",
            "price": 2233000,
            "rnd": "gift-rnd",
            "coin_type": "gold",
            "total_coin": 2233000,
            "tid": "gift-tid",
        }

        class GiftSession(FakeHttpSession):
            def __init__(self):
                super().__init__(
                    get_payloads=[
                        {
                            "code": 0,
                            "data": {
                                "list": [
                                    {
                                        "config": {
                                            "gif": "https://i0.hdslb.com/bfs/live/castle.gif",
                                        },
                                        "full_sc_effect": [
                                            {
                                                "web_mp4": "https://i0.hdslb.com/bfs/live/castle.mp4",
                                                "web_mp4_json": "https://i0.hdslb.com/bfs/live/castle.json",
                                            }
                                        ],
                                    }
                                ]
                            },
                        },
                        {
                            "info": {
                                "rgbFrame": [0, 0, 720, 1280],
                                "aFrame": [724, 0, 360, 640],
                            }
                        },
                    ]
                )

        client = DanmakuClient(7450109)
        client._gift_effect_catalog = GiftEffectCatalog(GiftSession(), client.room_id)
        received = []
        delivered = asyncio.Event()

        def on_message(message):
            received.append(message)
            delivered.set()

        client.set_message_callback(on_message)
        handler = DanmakuHandler()
        handler.set_danmaku_client(client)
        websocket = FakeWebSocketClient()
        handler.handle(websocket, {"cmd": "SEND_GIFT", "data": raw_gift})

        await asyncio.wait_for(delivered.wait(), timeout=1)
        assert len(received) == 1
        assert isinstance(received[0], GiftMessage)
        assert received[0].gift_effect_url.endswith("castle.mp4")
        assert received[0].gift_animation_url.endswith("castle.gif")
        await client._cancel_gift_effect_tasks()

    asyncio.run(run_test())


def test_handler_resolves_guard_purchase_effect_and_deduplicates_toast_event():
    async def run_test():
        raw_guard = {
            "uid": 99,
            "username": "舰长用户",
            "guard_level": 3,
            "num": 1,
            "price": 198000,
            "gift_id": 10003,
            "gift_name": "舰长",
            "start_time": 123456,
        }
        duplicate_toast = {
            "sender_uinfo": {"uid": 99, "base": {"name": "舰长用户"}},
            "guard_info": {"guard_level": 3, "start_time": 123456},
            "pay_info": {"num": 1, "price": 198000},
            "gift_info": {"gift_id": 10003, "gift_name": "舰长"},
            "option": {"source": 0, "is_group": False},
            "effect_info": {"room_effect_id": 590},
        }

        class GuardEffectSession(FakeHttpSession):
            def __init__(self):
                super().__init__(
                    get_payloads=[
                        {
                            "code": 0,
                            "data": {
                                "conf_list": [
                                    {
                                        "id": 590,
                                        "type": 3,
                                        "web_mp4": "https://i0.hdslb.com/bfs/live/captain.mp4",
                                        "web_mp4_json": "https://i0.hdslb.com/bfs/live/captain.json",
                                    }
                                ]
                            },
                        },
                        {
                            "info": {
                                "rgbFrame": [0, 0, 720, 1280],
                                "aFrame": [724, 0, 360, 640],
                            }
                        },
                    ]
                )

        client = DanmakuClient(7450109)
        session = GuardEffectSession()
        client._gift_effect_catalog = GiftEffectCatalog(session, client.room_id)
        received = []
        delivered = asyncio.Event()

        def on_message(message):
            received.append(message)
            delivered.set()

        client.set_message_callback(on_message)
        handler = DanmakuHandler()
        handler.set_danmaku_client(client)
        websocket = FakeWebSocketClient()

        assert handler.handle(websocket, {"cmd": "GUARD_BUY", "data": raw_guard}) is None
        assert handler.handle(websocket, {"cmd": "USER_TOAST_MSG_V2", "data": duplicate_toast}) is None

        await asyncio.wait_for(delivered.wait(), timeout=1)
        assert len(received) == 1
        assert isinstance(received[0], GiftMessage)
        assert received[0].gift_name == "舰长"
        assert received[0].gift_effect_url.endswith("captain.mp4")
        assert received[0].gift_effect_layout is not None
        assert session.get_calls[0][0] == FULL_SCREEN_EFFECT_CONFIG_URL
        await client._cancel_gift_effect_tasks()

    asyncio.run(run_test())


def test_handler_emits_open_platform_guard_without_the_optional_catalog():
    client = DanmakuClient(7450109)
    received = []
    client.set_message_callback(received.append)
    handler = DanmakuHandler()
    handler.set_danmaku_client(client)
    websocket = FakeWebSocketClient()

    handler.handle(
        websocket,
        {
            "cmd": "LIVE_OPEN_PLATFORM_GUARD",
            "data": {
                "user_info": {"uname": "提督用户"},
                "guard_level": 2,
                "guard_num": 1,
                "price": 1998000,
                "msg_id": "open-guard-1",
            },
        },
    )

    assert len(received) == 1
    assert isinstance(received[0], GiftMessage)
    assert received[0].gift_name == "提督"
    assert received[0].gift_id == 10002


def test_start_reports_expired_keyring_login(monkeypatch):
    class FakeAuthManager:
        def load_auth_cookies(self):
            return {"SESSDATA": "expired"}, True

        async def validate_session(self, _cookies):
            return False

        def create_session_from_cookies(self, cookies):
            assert cookies == {}
            return FakeSession()

    class FakeBLiveClient:
        def __init__(self, _room_id, *, session):
            self.session = session
            self.running = False

        @property
        def is_running(self):
            return self.running

        def set_handler(self, _handler):
            pass

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        async def join(self):
            pass

        async def close(self):
            pass

    async def run_test():
        login_failures = []
        monkeypatch.setattr(danmaku_client, "AuthManager", FakeAuthManager)
        monkeypatch.setattr(danmaku_client.blivedm, "BLiveClient", FakeBLiveClient)

        client = DanmakuClient(7450109)
        client.set_login_failed_callback(login_failures.append)

        await client.start()
        await client.stop()

        assert login_failures == ["本地保存的登录信息已失效，请重新登录"]

    asyncio.run(run_test())


class FakeSession:
    def __init__(self, on_close=None):
        self.closed: bool = False
        self.close_calls: int = 0
        self._on_close = on_close
        self.cookie_jar: list[FakeCookie] = []

    async def close(self):
        self.close_calls += 1
        self.closed = True
        if self._on_close is not None:
            self._on_close()

    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> "FakeResponse":
        raise AssertionError(f"unexpected GET request: {url}, {params}, {headers}")

    def post(self, url: str, *, data: object | None = None) -> "FakeResponse":
        raise AssertionError(f"unexpected POST request: {url}, {data}")


class FakeResponse(HttpResponse, AbstractAsyncContextManager[HttpResponse]):
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload: object = payload
        self.status: int = status

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False

    async def json(self, *, content_type: str | None = None) -> object:
        return self.payload


class FakeCookie:
    def __init__(self, key: str, value: str) -> None:
        self.key: str = key
        self.value: str = value


class FakeHttpSession:
    def __init__(
        self,
        get_payload: object | None = None,
        get_payloads: list[object] | None = None,
        post_payload: object | None = None,
    ) -> None:
        self.get_payload: object = get_payload if get_payload is not None else {"code": 0, "data": {"data": []}}
        self.get_payloads: list[object] = list(get_payloads) if get_payloads is not None else []
        self.post_payload: object = post_payload if post_payload is not None else {"code": 0, "message": "0"}
        self.posted_data: object | None = None
        self.get_url: str = ""
        self.post_url: str = ""
        self.get_params: QueryParams | None = None
        self.get_headers: dict[str, str] | None = None
        self.get_calls: list[tuple[str, QueryParams | None, dict[str, str] | None]] = []
        self.cookie_jar: list[FakeCookie] = [FakeCookie("bili_jct", "csrf-token")]
        self.closed: bool = False

    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        self.get_url = url
        self.get_params = params
        self.get_headers = dict(headers) if headers is not None else None
        self.get_calls.append((url, self.get_params, self.get_headers))
        payload = self.get_payloads.pop(0) if self.get_payloads else self.get_payload
        return FakeResponse(payload)

    def post(self, url: str, *, data: object | None = None) -> FakeResponse:
        self.post_url = url
        self.posted_data = data
        return FakeResponse(self.post_payload)

    async def close(self) -> None:
        self.closed = True


def _form_data_fields(form_data):
    return {disposition["name"]: value for disposition, _, value in form_data._fields}


def _posted_mapping(value: object | None) -> dict[str, object]:
    """Narrow the text-message payload captured by the HTTP fake."""
    if not isinstance(value, dict):
        raise AssertionError("expected a mapping payload")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def test_fetch_audience_snapshot_uses_current_web_api_contract():
    async def run_test():
        client = DanmakuClient(7450109)
        session = FakeHttpSession(
            get_payloads=[
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "room_info": {"uid": 9001, "online": 21},
                        "popularity": {"popularity": 21},
                        "watched_show": {"num": 9},
                        "like_info_v3": {"total_likes": 543},
                    },
                },
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "count": 3,
                        "item": [
                            {
                                "uid": 1001,
                                "name": "用户A",
                                "score": 1,
                                "rank": 1,
                                "is_mystery": False,
                            }
                        ],
                    },
                },
            ]
        )
        client.session = session
        client.update_total_likes(600)

        snapshot = await client.fetch_audience_snapshot()

        assert snapshot.room_id == 7450109
        assert snapshot.popularity == 21
        assert snapshot.watched_count == 9
        assert snapshot.online_rank_count == 3
        assert snapshot.total_likes == 600
        assert snapshot.users[0].name == "用户A"
        assert snapshot.users[0].contribution == 1

        room_url, room_params, room_headers = session.get_calls[0]
        assert room_url.endswith("/xlive/web-room/v1/index/getInfoByRoom")
        assert room_params == {"room_id": 7450109}
        assert room_headers == {"Referer": "https://live.bilibili.com/7450109"}

        rank_url, rank_params, rank_headers = session.get_calls[1]
        assert rank_url.endswith("/xlive/general-interface/v1/rank/queryContributionRank")
        assert rank_params == {
            "ruid": 9001,
            "room_id": 7450109,
            "page": 1,
            "page_size": 100,
            "type": "online_rank",
            "switch": "contribution_rank",
            "platform": "web",
        }
        assert rank_headers == {"Referer": "https://live.bilibili.com/7450109"}

    asyncio.run(run_test())


def test_fetch_audience_snapshot_requires_initialized_session():
    async def run_test():
        client = DanmakuClient(7450109)

        with pytest.raises(RuntimeError, match="弹幕会话未初始化"):
            await client.fetch_audience_snapshot()

    asyncio.run(run_test())


def test_fetch_audience_snapshot_propagates_api_error_without_credentials():
    async def run_test():
        client = DanmakuClient(7450109)
        session = FakeHttpSession(
            get_payload={"code": -101, "message": "账号未登录", "data": None}
        )
        client.session = session

        with pytest.raises(ValueError, match="账号未登录"):
            await client.fetch_audience_snapshot()

    asyncio.run(run_test())


class FakeBLiveClient:
    def __init__(self, *, finish_on_stop=True):
        self.stop_calls = 0
        self.close_calls = 0
        self._done = asyncio.Event()
        self._finish_on_stop = finish_on_stop

    @property
    def is_running(self):
        return not self._done.is_set()

    def set_handler(self, handler: object) -> None:
        pass

    def start(self) -> None:
        self._done.clear()

    def stop(self):
        self.stop_calls += 1
        if self._finish_on_stop:
            self._done.set()

    async def join(self):
        await self._done.wait()

    async def close(self):
        self.close_calls += 1

    def finish(self):
        self._done.set()


class RaisingJoinBLiveClient(FakeBLiveClient):
    async def join(self):
        raise RuntimeError("join failed")


def test_stop_waits_for_blivedm_and_closes_session():
    async def run_test():
        client = DanmakuClient(1)
        fake_blive = FakeBLiveClient(finish_on_stop=True)
        fake_session = FakeSession()
        client.client = fake_blive
        client.session = fake_session

        await client.stop(normal_timeout=0.05, forced_timeout=0.05)

        assert fake_blive.stop_calls == 1
        assert fake_blive.close_calls == 1
        assert fake_session.close_calls == 1
        assert fake_session.closed is True
        assert fake_blive.is_running is False

    asyncio.run(run_test())


def test_stop_closes_resources_but_keeps_references_when_join_raises():
    async def run_test():
        fake_blive = RaisingJoinBLiveClient(finish_on_stop=False)
        fake_session = FakeSession()
        client = DanmakuClient(1)
        client.client = fake_blive
        client.session = fake_session

        with pytest.raises(RuntimeError, match="join failed"):
            await client.stop(normal_timeout=0.05, forced_timeout=0.05)

        assert fake_blive.stop_calls == 1
        assert fake_blive.close_calls == 1
        assert fake_session.close_calls == 1
        assert fake_session.closed is True
        assert client.client is fake_blive
        assert client.session is fake_session

    asyncio.run(run_test())


def test_stop_closes_session_to_force_blivedm_completion_after_timeout():
    async def run_test():
        fake_blive = FakeBLiveClient(finish_on_stop=False)
        fake_session = FakeSession(on_close=fake_blive.finish)
        client = DanmakuClient(1)
        client.client = fake_blive
        client.session = fake_session

        await client.stop(normal_timeout=0.01, forced_timeout=0.05)

        assert fake_blive.stop_calls == 1
        assert fake_session.close_calls == 1
        assert fake_session.closed is True
        assert fake_blive.close_calls == 1
        assert fake_blive.is_running is False

    asyncio.run(run_test())


def test_stop_raises_if_blivedm_task_survives_forced_session_close():
    async def run_test():
        fake_blive = FakeBLiveClient(finish_on_stop=False)
        fake_session = FakeSession()
        client = DanmakuClient(1)
        client.client = fake_blive
        client.session = fake_session

        with pytest.raises(DanmakuShutdownError):
            await client.stop(normal_timeout=0.01, forced_timeout=0.01)

        assert fake_blive.stop_calls == 1
        assert fake_session.close_calls == 1
        assert fake_session.closed is True
        assert fake_blive.close_calls == 1
        assert fake_blive.is_running is True

    asyncio.run(run_test())


def test_fetch_live_emoticons_uses_v2_api_and_existing_session():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(
            get_payload={
                "code": 0,
                "message": "0",
                "data": {
                    "data": [
                        {
                            "pkg_id": 100428,
                            "pkg_name": "房间专属表情",
                            "pkg_type": 2,
                            "pkg_perm": 1,
                            "emoticons": [
                                {
                                    "emoji": "AKIE的A",
                                    "url": "http://i0.hdslb.com/bfs/live/room.png",
                                    "width": 162,
                                    "height": 162,
                                    "perm": 1,
                                    "emoticon_unique": "room_870691_84455",
                                    "emoticon_id": 0,
                                }
                            ],
                        }
                    ]
                },
            }
        )
        client.session = session

        packages = await client.fetch_live_emoticons()

        assert packages[0].name == "房间专属表情"
        assert session.get_url.endswith("/xlive/web-ucenter/v2/emoticon/GetEmoticons")
        assert session.get_params == {"platform": "pc", "room_id": 870691}
        assert session.get_headers is not None
        assert session.get_headers["Referer"] == "https://live.bilibili.com/870691"

    asyncio.run(run_test())


def test_fetch_live_emoticons_uses_one_minute_cache(monkeypatch):
    now = 1000.0

    def current_time():
        return now

    async def run_test():
        nonlocal now
        client = DanmakuClient(870691)
        session = FakeHttpSession(
            get_payload={
                "code": 0,
                "message": "0",
                "data": {
                    "data": [
                        {
                            "pkg_id": 100428,
                            "pkg_name": "房间专属表情",
                            "pkg_type": 2,
                            "pkg_perm": 1,
                            "emoticons": [
                                {
                                    "emoji": "AKIE的A",
                                    "url": "http://i0.hdslb.com/bfs/live/room.png",
                                    "width": 162,
                                    "height": 162,
                                    "perm": 1,
                                    "emoticon_unique": "room_870691_84455",
                                    "emoticon_id": 0,
                                }
                            ],
                        }
                    ]
                },
            }
        )
        client.session = session

        first = await client.fetch_live_emoticons()
        second = await client.fetch_live_emoticons()
        now = 1061.0
        third = await client.fetch_live_emoticons()

        assert first is second
        assert third is not first
        assert len(session.get_calls) == 2

    monkeypatch.setattr("bilihud.danmaku.client.time.time", current_time)
    asyncio.run(run_test())


def test_fetch_live_emoticons_does_not_cache_failed_fetch(monkeypatch):
    now = 1000.0

    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(get_payload={"code": -101, "message": "账号未登录", "data": None})
        client.session = session

        with pytest.raises(ValueError, match="账号未登录"):
            await client.fetch_live_emoticons()

        session.get_payload = {"code": 0, "message": "0", "data": {"data": []}}
        packages = await client.fetch_live_emoticons()

        assert packages == []
        assert len(session.get_calls) == 2

    monkeypatch.setattr("bilihud.danmaku.client.time.time", lambda: now)
    asyncio.run(run_test())


def test_send_live_emoticon_posts_dm_type_payload():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(
            get_payload={
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/0123456789abcdef0123456789abcdef.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/fedcba9876543210fedcba9876543210.png",
                    }
                },
            },
            post_payload={"code": 0, "message": "0"},
        )
        client.session = session
        emoticon = LiveEmoticon(
            emoji="AKIE的A",
            url="http://i0.hdslb.com/bfs/live/room.png",
            width=162,
            height=162,
            perm=1,
            unique="room_870691_84455",
            emoticon_id=0,
            package_type=2,
        )

        success, message = await client.send_live_emoticon(emoticon)

        assert success is True
        assert message == "发送成功"
        assert session.post_url.startswith("https://api.live.bilibili.com/msg/send?")
        query = parse_qs(urlparse(session.post_url).query)
        assert query["web_location"] == ["444.8"]
        assert query["wts"]
        assert len(query["w_rid"][0]) == 32
        assert session.get_calls[0][0] == "https://api.bilibili.com/x/web-interface/nav"
        assert isinstance(session.posted_data, aiohttp.FormData)
        posted_data = session.posted_data
        assert posted_data.is_multipart is True
        posted_fields = _form_data_fields(posted_data)
        assert posted_fields["dm_type"] == "1"
        assert posted_fields["emoticonOptions"] == "[object Object]"
        assert posted_fields["data_extend"] == '{"trackid":"-99998"}'
        assert "emoticon_unique" not in posted_fields
        assert posted_fields["msg"] == "room_870691_84455"

    asyncio.run(run_test())


def test_send_live_emoticon_posts_dm_type_payload_for_official_common_package():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(
            get_payload={
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/0123456789abcdef0123456789abcdef.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/fedcba9876543210fedcba9876543210.png",
                    }
                },
            },
            post_payload={"code": 0, "message": "0"},
        )
        client.session = session
        emoticon = LiveEmoticon(
            emoji="啊",
            url="http://i0.hdslb.com/bfs/live/a.png",
            width=200,
            height=60,
            perm=1,
            unique="official_331",
            emoticon_id=331,
            package_type=1,
        )

        success, message = await client.send_live_emoticon(emoticon)

        assert success is True
        assert message == "发送成功"
        assert isinstance(session.posted_data, aiohttp.FormData)
        posted_data = session.posted_data
        assert posted_data.is_multipart is True
        posted_fields = _form_data_fields(posted_data)
        assert posted_fields["msg"] == "official_331"
        assert posted_fields["dm_type"] == "1"
        assert posted_fields["emoticonOptions"] == "[object Object]"
        assert "emoticon_unique" not in posted_fields

    asyncio.run(run_test())


def test_send_live_emoticon_sends_emoji_package_as_text_escape():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(post_payload={"code": 0, "message": "0"})
        client.session = session
        emoticon = LiveEmoticon(
            emoji="赞",
            url="http://i0.hdslb.com/bfs/live/thumb.png",
            width=64,
            height=64,
            perm=1,
            unique="emoji_like",
            emoticon_id=0,
            package_name="emoji",
        )

        success, message = await client.send_live_emoticon(emoticon)

        assert success is True
        assert message == "发送成功"
        assert session.post_url == "https://api.live.bilibili.com/msg/send"
        assert session.get_calls == []
        posted_data = _posted_mapping(session.posted_data)
        assert posted_data["msg"] == "[赞]"
        assert "dm_type" not in posted_data

    asyncio.run(run_test())


def test_send_live_emoticon_preserves_bracketed_emoji_text_escape():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession(post_payload={"code": 0, "message": "0"})
        client.session = session
        emoticon = LiveEmoticon(
            emoji="[dog]",
            url="http://i0.hdslb.com/bfs/live/dog.png",
            width=64,
            height=64,
            perm=1,
            unique="emoji_dog",
            emoticon_id=0,
            package_name="emoji",
        )

        success, message = await client.send_live_emoticon(emoticon)

        assert success is True
        assert message == "发送成功"
        posted_data = _posted_mapping(session.posted_data)
        assert posted_data["msg"] == "[dog]"
        assert "dm_type" not in posted_data

    asyncio.run(run_test())


def test_send_live_emoticon_rejects_locked_emoticon_without_posting():
    async def run_test():
        client = DanmakuClient(870691)
        session = FakeHttpSession()
        client.session = session
        emoticon = LiveEmoticon(
            emoji="疑惑",
            url="http://i0.hdslb.com/bfs/live/locked.png",
            width=162,
            height=162,
            perm=0,
            unique="room_870691_1154",
            emoticon_id=1154,
            unlock_label="舰长",
        )

        success, message = await client.send_live_emoticon(emoticon)

        assert success is False
        assert "未解锁" in message
        assert session.posted_data is None

    asyncio.run(run_test())
