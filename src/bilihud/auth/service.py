from __future__ import annotations

import http.cookies
import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from io import BytesIO
from typing import Protocol

import aiohttp
import keyring
import keyring.errors as keyring_errors
import qrcode

from .account import (
    AccountLookupResult,
    AccountLookupStatus,
    account_count,
    account_room_id,
    fetch_optional_account_data,
    parse_account_profile,
)
from .account import (
    AccountProfile as AccountProfile,
)

logger = logging.getLogger(__name__)

SERVICE_ID = "bilihud"
USERNAME_KEY = "bilibili_cookies"
OBS_PASSWORD_KEY = "obs_websocket_password"
COMMON_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ESSENTIAL_COOKIE_KEYS = frozenset({"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"})
AuthCookies = dict[str, str]  # Normalized cookie names and values kept in secure storage.
QR_LOGIN_STATUS_NAMES: Mapping[int, str] = {
    0: "Success",
    86101: "Not Scanned",
    86090: "Scanned",
    86038: "Expired",
}


class SessionStore(Protocol):
    """Secure storage boundary for authentication and OBS credentials."""

    def load_cookies(self) -> AuthCookies | None:
        """Load saved Bilibili cookies, or return ``None`` when no session exists."""
        ...

    def save_cookies(self, cookies: Mapping[str, str]) -> bool:
        """Persist normalized Bilibili cookies without exposing them to callers."""
        ...

    def clear_cookies(self) -> bool:
        """Remove the saved Bilibili session and report secure-storage success."""
        ...

    def load_obs_password(self) -> str | None:
        """Load the OBS WebSocket password, or return ``None`` when absent."""
        ...

    def save_obs_password(self, password: str) -> bool:
        """Persist the OBS WebSocket password in secure storage."""
        ...

    def clear_obs_password(self) -> None:
        """Remove the saved OBS WebSocket password from secure storage."""
        ...


class AuthenticationService(Protocol):
    """Authentication use cases exposed to application and presentation code."""

    async def get_qrcode(self) -> tuple[str | None, str | None]:
        """Request a Bilibili QR-login URL and its polling key."""
        ...

    def generate_qr_image(self, url: str) -> BytesIO | None:
        """Render a QR-login URL into PNG bytes for the presentation layer."""
        ...

    async def poll_status(self, qrcode_key: str) -> tuple[int, str, AuthCookies | None]:
        """Poll QR-login state and return an authenticated cookie set on success.

        Returns:
            ``(code, message, cookies_dict)``. ``code`` follows Bilibili's QR-login
            protocol: ``0`` means Success, ``86101`` means Not Scanned, ``86090``
            means Scanned, and ``86038`` means Expired. ``cookies_dict`` is
            populated only after a successful login.
        """
        ...

    def save_cookies(self, cookies: Mapping[str, str]) -> bool:
        """Store cookies obtained from a successful login."""
        ...

    def load_auth_cookies(self) -> tuple[AuthCookies, bool]:
        """Load cookies and indicate whether they came from secure storage."""
        ...

    def create_session_from_cookies(self, cookies: Mapping[str, str]) -> aiohttp.ClientSession:
        """Create an aiohttp session whose caller owns and closes the resource."""
        ...

    async def create_authenticated_session(self, validate_keyring: bool = True) -> tuple[aiohttp.ClientSession, bool]:
        """Create a session from saved cookies, optionally validating the stored login."""
        ...

    async def validate_session(self, cookies: Mapping[str, str]) -> bool:
        """Check whether a Bilibili cookie set still represents a logged-in user."""
        ...

    async def lookup_account(self) -> AccountLookupResult:
        """Resolve the saved session into a normalized account identity."""
        ...

    def logout(self) -> bool:
        """Remove the saved Bilibili session and report whether it was cleared."""
        ...

    def load_obs_password(self) -> str | None:
        """Load the OBS password through the same secure boundary as Bilibili auth."""
        ...

    def save_obs_password(self, password: str) -> bool:
        """Save the OBS password without involving ordinary configuration storage."""
        ...

    def clear_obs_password(self) -> None:
        """Clear the stored OBS password."""
        ...

    def clear_credentials(self) -> None:
        """Clear both Bilibili cookies and the OBS password."""
        ...


class KeyringSessionStore:
    """Keyring-backed implementation of the authentication storage boundary."""

    def __init__(self, service_id: str = SERVICE_ID) -> None:
        """Create a keyring adapter under the given service namespace."""
        self.service_id = service_id  # Shared keyring namespace for all credential kinds.

    def load_cookies(self) -> AuthCookies | None:
        """Load and validate the JSON-encoded Bilibili cookie set from keyring."""
        try:
            cookie_json = keyring.get_password(self.service_id, USERNAME_KEY)
            if not cookie_json:
                return None
            stored_cookies = json.loads(cookie_json)
            if not isinstance(stored_cookies, dict):
                logger.error("Stored keyring cookies are not a JSON object")
                return None
            if not all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in stored_cookies.items()
            ):
                logger.error("Stored keyring cookies contain invalid values")
                return None
            return dict(stored_cookies)
        except (keyring_errors.KeyringError, OSError, TypeError, ValueError) as exc:
            logger.error("Failed to load cookies from keyring: %s", exc)
            return None

    def save_cookies(self, cookies: Mapping[str, str]) -> bool:
        """Validate and save Bilibili cookies as one keyring entry."""
        if not all(isinstance(name, str) and isinstance(value, str) for name, value in cookies.items()):
            logger.error("Refusing to save invalid authentication cookies")
            return False
        try:
            keyring.set_password(self.service_id, USERNAME_KEY, json.dumps(dict(cookies)))
            return True
        except (keyring_errors.KeyringError, OSError, TypeError, ValueError) as exc:
            logger.error("Failed to save cookies to keyring: %s", exc)
            return False

    def clear_cookies(self) -> bool:
        """Delete the Bilibili cookie entry when it exists and report failures."""
        try:
            if keyring.get_password(self.service_id, USERNAME_KEY) is None:
                return True
            keyring.delete_password(self.service_id, USERNAME_KEY)
            return True
        except (keyring_errors.KeyringError, OSError) as exc:
            logger.error("Failed to delete cookies from keyring: %s", exc)
            return False

    def load_obs_password(self) -> str | None:
        """Load the OBS WebSocket password from keyring."""
        try:
            password = keyring.get_password(self.service_id, OBS_PASSWORD_KEY)
            return password if password else None
        except (keyring_errors.KeyringError, OSError, TypeError) as exc:
            logger.error("Failed to load OBS credentials from keyring: %s", exc)
            return None

    def save_obs_password(self, password: str) -> bool:
        """Save a non-empty OBS password or clear it when empty."""
        if not password:
            self.clear_obs_password()
            return True
        try:
            keyring.set_password(self.service_id, OBS_PASSWORD_KEY, password)
            return True
        except (keyring_errors.KeyringError, OSError, TypeError, ValueError) as exc:
            logger.error("Failed to save OBS credentials to keyring: %s", exc)
            return False

    def clear_obs_password(self) -> None:
        """Delete the OBS password entry when it exists."""
        try:
            keyring.delete_password(self.service_id, OBS_PASSWORD_KEY)
        except (keyring_errors.KeyringError, OSError) as exc:
            logger.info("Failed to delete OBS credentials from keyring: %s", exc)


class BilibiliAuthService:
    """Bilibili QR authentication and authenticated-session service."""

    BASE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
    RELATION_URL = "https://api.bilibili.com/x/relation/stat"
    LIVE_INFO_URL = "https://api.live.bilibili.com/xlive/web-ucenter/user/live_info"

    def __init__(self, session_store: SessionStore | None = None) -> None:
        """Create the service with an injectable secure storage adapter."""
        self.session_store = (
            session_store if session_store is not None else KeyringSessionStore()
        )  # Owns credential access; returned network sessions remain caller-owned.

    async def get_qrcode(self) -> tuple[str | None, str | None]:
        """Request a fresh QR-login URL and polling key from Bilibili."""
        headers = {"User-Agent": COMMON_USER_AGENT}
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(self.BASE_URL) as response:
                    payload = _as_mapping(await response.json())
                    if _int_value(payload.get("code")) == 0:
                        data = _as_mapping(payload.get("data"))
                        return _string_or_none(data.get("url")), _string_or_none(data.get("qrcode_key"))
                    logger.error("Failed to get QR code: %s", payload)
                    return None, None
            except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
                logger.error("Exception requesting QR code: %s", exc)
                return None, None

    def generate_qr_image(self, url: str) -> BytesIO | None:
        """Generate PNG bytes for a QR-login URL, returning ``None`` on failure."""
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)

            image = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            image.save(bio, format="PNG")
            bio.seek(0)
            return bio
        except (OSError, TypeError, ValueError) as exc:
            logger.error("Failed to generate QR image: %s", exc)
            return None

    async def poll_status(self, qrcode_key: str) -> tuple[int, str, AuthCookies | None]:
        """Poll QR-login state and extract only the cookies needed by the app.

        Returns:
            ``(code, message, cookies_dict)``. ``code`` follows Bilibili's QR-login
            protocol: ``0`` means Success, ``86101`` means Not Scanned, ``86090``
            means Scanned, and ``86038`` means Expired. ``cookies_dict`` is
            populated only after a successful login.
        """
        headers = {"User-Agent": COMMON_USER_AGENT}
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(self.POLL_URL, params={"qrcode_key": qrcode_key}) as response:
                    payload = _as_mapping(await response.json())
                    if _int_value(payload.get("code")) != 0:
                        return -1, f"API Error: {payload.get('code')}", None

                    data = _as_mapping(payload.get("data"))
                    code = _int_value(data.get("code"), default=-1)
                    message = _string_or_none(data.get("message")) or ""
                    if code != 0:
                        return code, message, None

                    cookies = {
                        cookie.key: cookie.value
                        for cookie in session.cookie_jar
                        if cookie.key in ESSENTIAL_COOKIE_KEYS
                    }
                    return 0, "登录成功", cookies
            except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
                logger.error("Exception polling status: %s", exc)
                return -1, str(exc), None

    def save_cookies(self, cookies: Mapping[str, str]) -> bool:
        """Persist cookies through the injected secure storage adapter."""
        return self.session_store.save_cookies(cookies)

    def load_cookies(self) -> AuthCookies | None:
        """Load cookies through the injected secure storage adapter."""
        return self.session_store.load_cookies()

    def clear_cookies(self) -> bool:
        """Clear Bilibili cookies through the injected secure storage adapter."""
        return self.session_store.clear_cookies()

    def load_auth_cookies(self) -> tuple[AuthCookies, bool]:
        """Return saved cookies and whether a secure saved session was available."""
        saved_cookies = self.load_cookies()
        if saved_cookies:
            return dict(saved_cookies), True
        return {}, False

    def create_session_from_cookies(self, cookies: Mapping[str, str]) -> aiohttp.ClientSession:
        """Create a session; the caller owns and must close the returned session."""
        cookie_jar = http.cookies.SimpleCookie()
        for name, value in cookies.items():
            cookie_jar[name] = value

        if "SESSDATA" in cookie_jar:
            cookie_jar["SESSDATA"]["domain"] = "bilibili.com"

        session = aiohttp.ClientSession(headers={"User-Agent": COMMON_USER_AGENT})
        session.cookie_jar.update_cookies(cookie_jar)
        return session

    async def create_authenticated_session(
        self, validate_keyring: bool = True
    ) -> tuple[aiohttp.ClientSession, bool]:
        """Create a caller-owned session from saved cookies and optional validation."""
        cookies, from_keyring = self.load_auth_cookies()
        if from_keyring and validate_keyring and not await self.validate_session(cookies):
            logger.info("Keyring cookies expired")
            cookies = {}

        return self.create_session_from_cookies(cookies), from_keyring

    async def validate_session(self, cookies: Mapping[str, str]) -> bool:
        """Validate a cookie set using Bilibili's logged-in navigation endpoint."""
        headers = {"User-Agent": COMMON_USER_AGENT}
        try:
            async with aiohttp.ClientSession(cookies=cookies, headers=headers) as session:
                async with session.get(self.NAV_URL) as response:
                    payload = _as_mapping(await response.json())
                    if _int_value(payload.get("code")) != 0:
                        return False
                    data = _as_mapping(payload.get("data"))
                    return data.get("isLogin") is True
        except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
            logger.error("Session validation failed: %s", exc)
            return False

    async def lookup_account(self) -> AccountLookupResult:
        """Fetch and normalize the saved Bilibili account identity."""
        cookies, _from_keyring = self.load_auth_cookies()
        if not cookies:
            return AccountLookupResult(AccountLookupStatus.NO_SESSION)

        headers = {"User-Agent": COMMON_USER_AGENT}
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(
                cookies=cookies,
                headers=headers,
                timeout=timeout,
            ) as session:
                async with session.get(self.NAV_URL) as response:
                    payload = _as_mapping(await response.json())
                    if _int_value(payload.get("code")) != 0:
                        return AccountLookupResult(AccountLookupStatus.INVALID)
                    data = _as_mapping(payload.get("data"))
                    if data.get("isLogin") is not True:
                        return AccountLookupResult(AccountLookupStatus.INVALID)
                    profile = parse_account_profile(data)
                    if profile is None:
                        logger.error("Bilibili account response omitted identity fields")
                        return AccountLookupResult(
                            AccountLookupStatus.UNAVAILABLE,
                            message="账号资料格式无效",
                        )
                    relation_data = await fetch_optional_account_data(
                        session,
                        self.RELATION_URL,
                        params={"vmid": profile.user_id},
                    )
                    live_data = await fetch_optional_account_data(session, self.LIVE_INFO_URL)
                    profile = replace(
                        profile,
                        following_count=account_count(relation_data.get("following")),
                        follower_count=account_count(relation_data.get("follower")),
                        live_room_id=account_room_id(live_data.get("room_id")),
                    )
                    return AccountLookupResult(AccountLookupStatus.AUTHENTICATED, profile)
        except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
            logger.error("Account lookup failed: %s", exc)
            return AccountLookupResult(AccountLookupStatus.UNAVAILABLE, message=str(exc))

    def logout(self) -> bool:
        """Clear only the saved Bilibili session, retaining unrelated OBS credentials."""
        return self.clear_cookies()

    def load_obs_password(self) -> str | None:
        """Load the OBS password through secure storage."""
        return self.session_store.load_obs_password()

    def save_obs_password(self, password: str) -> bool:
        """Save the OBS password through secure storage."""
        return self.session_store.save_obs_password(password)

    def clear_obs_password(self) -> None:
        """Clear the OBS password through secure storage."""
        self.session_store.clear_obs_password()

    def clear_credentials(self) -> None:
        """Clear all credentials owned by the application."""
        self.clear_cookies()
        self.clear_obs_password()


def _as_mapping(value: object) -> Mapping[str, object]:
    """Convert an external JSON object to a string-keyed mapping."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _int_value(value: object, default: int = -1) -> int:
    """Read an integer API field without accepting booleans as integers."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _string_or_none(value: object) -> str | None:
    """Return a string API field or ``None`` when its type is unexpected."""
    return value if isinstance(value, str) else None


# TODO: remove these legacy aliases after downstream callers migrate to the protocol names.
# Public aliases keep the boundary name concise while preserving the legacy manager name.
AuthSessionStore = SessionStore
AuthService = AuthenticationService
AuthManager = BilibiliAuthService
