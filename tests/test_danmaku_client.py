import asyncio
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

from bilihud import danmaku_client
from bilihud.danmaku_client import DanmakuClient, DanmakuShutdownError
from bilihud.live_emoticons import LiveEmoticon


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

        @property
        def is_running(self):
            return self.start_calls > 0

        def set_handler(self, handler):
            self.handler = handler

        def start(self):
            self.start_calls += 1

    async def run_test():
        monkeypatch.setattr(danmaku_client, "AuthManager", FakeAuthManager)
        monkeypatch.setattr(danmaku_client.blivedm, "BLiveClient", FakeBLiveClient)

        client = DanmakuClient(7450109)
        login_failures = []
        client.set_login_failed_callback(login_failures.append)

        await client.start()

        assert client.client is not None
        assert client.client.start_calls == 1
        assert client.client.is_running is True
        assert login_failures == ["未找到有效登录信息，请扫码登录"]

    asyncio.run(run_test())


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
        self.closed = False
        self.close_calls = 0
        self._on_close = on_close

    async def close(self):
        self.close_calls += 1
        self.closed = True
        if self._on_close is not None:
            self._on_close()


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeCookie:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class FakeHttpSession:
    def __init__(self, get_payload=None, get_payloads=None, post_payload=None):
        self.get_payload = get_payload or {"code": 0, "data": {"data": []}}
        self.get_payloads = list(get_payloads or [])
        self.post_payload = post_payload or {"code": 0, "message": "0"}
        self.posted_data = None
        self.get_params = None
        self.get_headers = None
        self.get_calls = []
        self.cookie_jar = [FakeCookie("bili_jct", "csrf-token")]

    def get(self, url, params=None, headers=None):
        self.get_url = url
        self.get_params = params
        self.get_headers = headers
        self.get_calls.append((url, params, headers))
        payload = self.get_payloads.pop(0) if self.get_payloads else self.get_payload
        return FakeResponse(payload)

    def post(self, url, data=None):
        self.post_url = url
        self.posted_data = data
        return FakeResponse(self.post_payload)


def _form_data_fields(form_data):
    return {disposition["name"]: value for disposition, _, value in form_data._fields}


def test_fetch_audience_snapshot_uses_current_web_api_contract():
    async def run_test():
        client = DanmakuClient(7450109)
        client.session = FakeHttpSession(
            get_payloads=[
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "room_info": {"uid": 9001, "online": 21},
                        "popularity": {"popularity": 21},
                        "watched_show": {"num": 9},
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

        snapshot = await client.fetch_audience_snapshot()

        assert snapshot.room_id == 7450109
        assert snapshot.popularity == 21
        assert snapshot.watched_count == 9
        assert snapshot.online_rank_count == 3
        assert snapshot.users[0].name == "用户A"
        assert snapshot.users[0].contribution == 1

        room_url, room_params, room_headers = client.session.get_calls[0]
        assert room_url.endswith("/xlive/web-room/v1/index/getInfoByRoom")
        assert room_params == {"room_id": 7450109}
        assert room_headers == {"Referer": "https://live.bilibili.com/7450109"}

        rank_url, rank_params, rank_headers = client.session.get_calls[1]
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
        client.session = FakeHttpSession(
            get_payload={"code": -101, "message": "账号未登录", "data": None}
        )

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
        client.session = FakeHttpSession(
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

        packages = await client.fetch_live_emoticons()

        assert packages[0].name == "房间专属表情"
        assert client.session.get_url.endswith("/xlive/web-ucenter/v2/emoticon/GetEmoticons")
        assert client.session.get_params == {"platform": "pc", "room_id": 870691}
        assert client.session.get_headers["Referer"] == "https://live.bilibili.com/870691"

    asyncio.run(run_test())


def test_fetch_live_emoticons_uses_one_minute_cache(monkeypatch):
    now = 1000.0

    def current_time():
        return now

    async def run_test():
        nonlocal now
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(
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

        first = await client.fetch_live_emoticons()
        second = await client.fetch_live_emoticons()
        now = 1061.0
        third = await client.fetch_live_emoticons()

        assert first is second
        assert third is not first
        assert len(client.session.get_calls) == 2

    monkeypatch.setattr("bilihud.danmaku_client.time.time", current_time)
    asyncio.run(run_test())


def test_fetch_live_emoticons_does_not_cache_failed_fetch(monkeypatch):
    now = 1000.0

    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(get_payload={"code": -101, "message": "账号未登录", "data": None})

        with pytest.raises(ValueError, match="账号未登录"):
            await client.fetch_live_emoticons()

        client.session.get_payload = {"code": 0, "message": "0", "data": {"data": []}}
        packages = await client.fetch_live_emoticons()

        assert packages == []
        assert len(client.session.get_calls) == 2

    monkeypatch.setattr("bilihud.danmaku_client.time.time", lambda: now)
    asyncio.run(run_test())


def test_send_live_emoticon_posts_dm_type_payload():
    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(
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
        assert client.session.post_url.startswith("https://api.live.bilibili.com/msg/send?")
        query = parse_qs(urlparse(client.session.post_url).query)
        assert query["web_location"] == ["444.8"]
        assert query["wts"]
        assert len(query["w_rid"][0]) == 32
        assert client.session.get_calls[0][0] == "https://api.bilibili.com/x/web-interface/nav"
        assert isinstance(client.session.posted_data, aiohttp.FormData)
        assert client.session.posted_data.is_multipart is True
        posted_fields = _form_data_fields(client.session.posted_data)
        assert posted_fields["dm_type"] == "1"
        assert posted_fields["emoticonOptions"] == "[object Object]"
        assert posted_fields["data_extend"] == '{"trackid":"-99998"}'
        assert "emoticon_unique" not in posted_fields
        assert posted_fields["msg"] == "room_870691_84455"

    asyncio.run(run_test())


def test_send_live_emoticon_posts_dm_type_payload_for_official_common_package():
    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(
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
        assert isinstance(client.session.posted_data, aiohttp.FormData)
        assert client.session.posted_data.is_multipart is True
        posted_fields = _form_data_fields(client.session.posted_data)
        assert posted_fields["msg"] == "official_331"
        assert posted_fields["dm_type"] == "1"
        assert posted_fields["emoticonOptions"] == "[object Object]"
        assert "emoticon_unique" not in posted_fields

    asyncio.run(run_test())


def test_send_live_emoticon_sends_emoji_package_as_text_escape():
    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(post_payload={"code": 0, "message": "0"})
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
        assert client.session.post_url == "https://api.live.bilibili.com/msg/send"
        assert client.session.get_calls == []
        assert client.session.posted_data["msg"] == "[赞]"
        assert "dm_type" not in client.session.posted_data

    asyncio.run(run_test())


def test_send_live_emoticon_preserves_bracketed_emoji_text_escape():
    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession(post_payload={"code": 0, "message": "0"})
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
        assert client.session.posted_data["msg"] == "[dog]"
        assert "dm_type" not in client.session.posted_data

    asyncio.run(run_test())


def test_send_live_emoticon_rejects_locked_emoticon_without_posting():
    async def run_test():
        client = DanmakuClient(870691)
        client.session = FakeHttpSession()
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
        assert client.session.posted_data is None

    asyncio.run(run_test())
