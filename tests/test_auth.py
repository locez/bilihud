import asyncio
from dataclasses import dataclass

import keyring

from bilihud.auth import AuthManager


@dataclass
class FakeSessionCookie:
    key: str
    value: str


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload: dict[str, object]):
        self.cookie_jar = [
            FakeSessionCookie("SESSDATA", "qr-sess"),
            FakeSessionCookie("bili_jct", "qr-csrf"),
            FakeSessionCookie("unrelated", "ignored"),
        ]
        self.payload = payload

    def get(self, _url, *, params):
        assert params == {"qrcode_key": "qr-key"}
        return FakeResponse(self.payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
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


def test_qr_login_poll_returns_session_cookies(monkeypatch):
    payload = {"code": 0, "data": {"code": 0, "message": "登录成功"}}
    monkeypatch.setattr("bilihud.auth.aiohttp.ClientSession", lambda **_kwargs: FakeSession(payload))

    code, message, cookies = asyncio.run(AuthManager().poll_status("qr-key"))

    assert (code, message) == (0, "登录成功")
    assert cookies == {"SESSDATA": "qr-sess", "bili_jct": "qr-csrf"}
