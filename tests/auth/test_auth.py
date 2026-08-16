import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import keyring

from bilihud.auth.service import (
    QR_LOGIN_STATUS_NAMES,
    AccountLookupStatus,
    AuthManager,
    BilibiliAuthService,
    KeyringSessionStore,
)


@dataclass
class FakeSessionCookie:
    key: str
    value: str


class FakeResponse:
    def __init__(self, payload: Mapping[str, object]):
        self.payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self) -> Mapping[str, object]:
        return self.payload


class FakeSession:
    def __init__(
        self,
        payload: Mapping[str, object],
        responses: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        self.cookie_jar = [
            FakeSessionCookie("SESSDATA", "qr-sess"),
            FakeSessionCookie("bili_jct", "qr-csrf"),
            FakeSessionCookie("unrelated", "ignored"),
        ]
        self.payload = payload
        self.responses: Mapping[str, Mapping[str, object]] = responses if responses is not None else {}

    def get(
        self,
        _url: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        if params == {"qrcode_key": "qr-key"}:
            assert params == {"qrcode_key": "qr-key"}
        if _url in self.responses:
            return FakeResponse(self.responses[_url])
        if params is not None and params != {"qrcode_key": "qr-key"}:
            return FakeResponse(self.payload)
        if params is not None:
            assert params == {"qrcode_key": "qr-key"}
        return FakeResponse(self.payload)

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_load_auth_cookies_prefers_keyring(monkeypatch):
    manager = AuthManager()
    monkeypatch.setattr(manager, "load_cookies", lambda: {"SESSDATA": "keyring-sess", "bili_jct": "csrf"})

    cookies, from_keyring = manager.load_auth_cookies()

    assert cookies == {"SESSDATA": "keyring-sess", "bili_jct": "csrf"}
    assert from_keyring is True


def test_load_auth_cookies_returns_empty_state_without_keyring_cookies(monkeypatch):
    manager = AuthManager()
    monkeypatch.setattr(manager, "load_cookies", lambda: None)

    cookies, from_keyring = manager.load_auth_cookies()

    assert cookies == {}
    assert from_keyring is False


def test_keyring_cookies_can_be_saved_loaded_and_cleared(monkeypatch):
    stored: dict[tuple[str, str], str] = {}

    def set_password(service: str, username: str, value: str) -> None:
        stored[(service, username)] = value

    def get_password(service: str, username: str) -> str | None:
        return stored.get((service, username))

    def delete_password(service: str, username: str) -> None:
        stored.pop((service, username), None)

    monkeypatch.setattr(keyring, "set_password", set_password)
    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "delete_password", delete_password)

    manager = AuthManager()
    cookies = {"SESSDATA": "saved-sess", "bili_jct": "saved-csrf"}

    assert manager.save_cookies(cookies) is True
    assert manager.load_cookies() == cookies

    manager.clear_cookies()

    assert manager.load_cookies() is None


def test_keyring_cookie_clear_reports_storage_failure(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda _service, _username: "session")

    def delete_password(_service: str, _username: str) -> None:
        raise OSError("keyring unavailable")

    monkeypatch.setattr(keyring, "delete_password", delete_password)

    assert KeyringSessionStore().clear_cookies() is False


def test_qr_login_poll_returns_session_cookies(monkeypatch):
    payload = {"code": 0, "data": {"code": 0, "message": "登录成功"}}
    monkeypatch.setattr("bilihud.auth.service.aiohttp.ClientSession", lambda **_kwargs: FakeSession(payload))

    code, message, cookies = asyncio.run(AuthManager().poll_status("qr-key"))

    assert (code, message) == (0, "登录成功")
    assert cookies == {"SESSDATA": "qr-sess", "bili_jct": "qr-csrf"}


def test_account_lookup_returns_normalized_identity(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "isLogin": True,
            "mid": 12345,
            "uname": "测试用户",
            "face": "https://i0.hdslb.com/avatar.png",
        },
    }
    monkeypatch.setattr(
        "bilihud.auth.service.aiohttp.ClientSession",
        lambda **_kwargs: FakeSession(payload),
    )
    manager = AuthManager()
    monkeypatch.setattr(manager, "load_auth_cookies", lambda: ({"SESSDATA": "session"}, True))

    result = asyncio.run(manager.lookup_account())

    assert result.status is AccountLookupStatus.AUTHENTICATED
    assert result.profile is not None
    assert result.profile.user_id == "12345"
    assert result.profile.username == "测试用户"
    assert result.profile.avatar_url == "https://i0.hdslb.com/avatar.png"


def test_account_lookup_includes_relations_and_live_room(monkeypatch):
    nav_payload = {
        "code": 0,
        "data": {
            "isLogin": True,
            "mid": 12345,
            "uname": "测试用户",
            "face": "https://i0.hdslb.com/avatar.png",
        },
    }
    session = FakeSession(
        nav_payload,
        responses={
            BilibiliAuthService.RELATION_URL: {
                "code": 0,
                "data": {"following": 12, "follower": 345},
            },
            BilibiliAuthService.LIVE_INFO_URL: {
                "code": 0,
                "data": {"room_id": 778899},
            },
        },
    )
    monkeypatch.setattr("bilihud.auth.service.aiohttp.ClientSession", lambda **_kwargs: session)
    manager = AuthManager()
    monkeypatch.setattr(manager, "load_auth_cookies", lambda: ({"SESSDATA": "session"}, True))

    result = asyncio.run(manager.lookup_account())

    assert result.profile is not None
    assert result.profile.following_count == 12
    assert result.profile.follower_count == 345
    assert result.profile.live_room_id == 778899
    assert result.profile.space_url == "https://space.bilibili.com/12345"
    assert result.profile.live_room_url == "https://live.bilibili.com/778899"


def test_qr_login_status_codes_have_protocol_names():
    assert QR_LOGIN_STATUS_NAMES == {
        0: "Success",
        86101: "Not Scanned",
        86090: "Scanned",
        86038: "Expired",
    }


def test_auth_service_uses_replaceable_session_store():
    class FakeSessionStore:
        def __init__(self):
            self.cookies = None
            self.obs_password = None

        def load_cookies(self):
            return self.cookies

        def save_cookies(self, cookies):
            self.cookies = dict(cookies)
            return True

        def clear_cookies(self):
            self.cookies = None
            return True

        def load_obs_password(self):
            return self.obs_password

        def save_obs_password(self, password):
            self.obs_password = password
            return True

        def clear_obs_password(self):
            self.obs_password = None

    store = FakeSessionStore()
    service = BilibiliAuthService(store)

    assert service.save_cookies({"SESSDATA": "session"}) is True
    assert service.load_auth_cookies() == ({"SESSDATA": "session"}, True)
    assert service.save_obs_password("obs-secret") is True
    assert service.load_obs_password() == "obs-secret"

    assert service.logout() is True

    assert service.load_auth_cookies() == ({}, False)
    assert service.load_obs_password() == "obs-secret"

    service.clear_credentials()

    assert service.load_auth_cookies() == ({}, False)
    assert service.load_obs_password() is None
