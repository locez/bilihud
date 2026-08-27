import asyncio
import hashlib
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Protocol
from urllib.parse import urlencode, urlparse

import aiohttp
import blivedm
import blivedm.clients.ws_base as ws_base
import blivedm.models.open_live as open_models
import blivedm.models.web as web_models

from ..app.lifecycle import run_owned_blocking
from ..auth.service import AuthManager, DanmakuAuthenticationService
from ..http_contracts import HttpCookie, HttpSession
from ..live.audience import AudienceSnapshot, parse_anchor_uid, parse_audience_snapshot
from ..live.emoticons import (
    LiveEmoticon,
    LiveEmoticonPackage,
    build_live_emoticon_payload,
    parse_live_emoticon_packages,
)
from ..live.gift_effects import (
    GiftEffectCatalog,
    GiftEffectLookupError,
    normalize_official_resource_url,
)
from .blivedm_adapter import (
    GuardPurchase,
    guard_purchase_from_guard_buy,
    guard_purchase_from_open_guard,
    guard_purchase_from_user_toast,
    parse_guard_purchase,
    parse_open_guard_purchase,
    to_hud_gift_message,
    to_hud_guard_message,
    to_hud_like_message,
    to_hud_message_or_system,
    to_hud_total_likes,
    to_hud_voice_report_like_messages,
)
from .messages import GiftEffectLayout, HudMessage

NetworkSession = aiohttp.ClientSession | HttpSession

WBI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
LIVE_MSG_SEND_URL = "https://api.live.bilibili.com/msg/send"
LIVE_ROOM_INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
LIVE_AUDIENCE_RANK_URL = (
    "https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank"
)
LIVE_WEB_LOCATION = "444.8"
LIVE_EMOTICON_CACHE_TTL_SECONDS = 60.0
GUARD_EVENT_DEDUP_TTL_SECONDS = 5.0
WBI_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
)

logger = logging.getLogger(__name__)


class DanmakuLiveClient(Protocol):
    """Lifecycle capability consumed from the vendored blivedm client."""

    @property
    def is_running(self) -> bool:
        """Return whether the underlying websocket task is active."""
        ...

    def set_handler(self, handler: "DanmakuHandler") -> None:
        """Attach the normalized message handler."""
        ...

    def start(self) -> None:
        """Start receiving messages."""
        ...

    def stop(self) -> None:
        """Request websocket shutdown."""
        ...

    async def join(self) -> None:
        """Wait for the websocket task to finish."""
        ...

    async def close(self) -> None:
        """Release websocket-owned resources."""
        ...


class DanmakuClient:
    """Receive and send live-room messages through one owned network session.

    Authentication is supplied through ``auth_service`` when the application
    composition root is available. The client owns the session created during
    ``start`` and closes it during ``stop``.
    """

    def __init__(
        self,
        room_id: int,
        sessdata: str = "",
        auth_service: DanmakuAuthenticationService | None = None,
    ) -> None:
        """Create a client for one room with an optional injected auth service."""
        self.room_id = room_id
        self.sessdata = sessdata  # Optional one-off SESSDATA override for this connection.
        self.auth_service = auth_service  # Shared authentication boundary from the app.
        self.session: NetworkSession | None = None  # Owned and closed by this client.
        self.client: DanmakuLiveClient | None = None  # Underlying blivedm lifecycle handle.
        self.handler: DanmakuHandler | None = None  # Callback bridge owned by the client.
        self.on_message_received: Callable[[HudMessage], None] | None = None
        self.on_login_failed: Callable[[str], None] | None = None # callback(message)
        self.on_total_likes_received: Callable[[int], None] | None = None
        self._total_likes: int | None = None  # Latest websocket value, owned by this room client.
        self._wbi_mixin_key: str | None = None  # Cached signing key for authenticated sends.
        self._live_emoticon_cache: list[LiveEmoticonPackage] | None = None  # Short-lived room cache.
        self._live_emoticon_cache_at = 0.0  # Monotonic timestamp for the emoticon cache.
        self._gift_effect_catalog: GiftEffectCatalog | None = None  # Room-scoped official asset cache.
        self._gift_effect_tasks: set[asyncio.Task[None]] = set()  # Tasks owned and cancelled by stop().
        self._recent_guard_events: dict[tuple[int, int, int, int, int, str], float] = {}

    @property
    def is_running(self) -> bool:
        """Report the underlying BLive connection state through this client boundary."""
        client = self.client
        return client is not None and client.is_running

    def set_message_callback(self, callback: Callable[[HudMessage], None]) -> None:
        """设置接收已转换为领域模型的直播消息回调。"""
        self.on_message_received = callback

    def set_total_likes_callback(self, callback: Callable[[int], None]) -> None:
        """Register the callback for room-wide like-count updates."""
        self.on_total_likes_received = callback

    def update_total_likes(self, total_likes: int) -> None:
        """Store and publish one normalized room-wide like-count update."""
        normalized = max(0, total_likes)
        if self._total_likes == normalized:
            return
        self._total_likes = normalized
        callback = self.on_total_likes_received
        if callback is not None:
            callback(normalized)

    def set_login_failed_callback(self, callback: Callable[[str], None]) -> None:
        """设置登录失效回调"""
        self.on_login_failed = callback

    async def start(self) -> None:
        """Load authentication, create owned network resources, and start receiving messages."""
        self._total_likes = None
        auth_manager = self.auth_service if self.auth_service is not None else AuthManager()
        login_failure_message: str | None = None

        try:
            loaded_cookies, is_keyring = await run_owned_blocking(
                auth_manager.load_auth_cookies,
                thread_name="bilihud-auth",
            )
            if is_keyring:
                if not await auth_manager.validate_session(loaded_cookies):
                    logger.info("Keyring cookies expired")
                    login_failure_message = "本地保存的登录信息已失效，请重新登录"
                    loaded_cookies = {}

        except Exception:
            logger.exception("Failed to load authentication cookies")
            loaded_cookies = {}
            login_failure_message = "读取登录信息失败，请扫码登录"

        if self.sessdata:
            loaded_cookies["SESSDATA"] = self.sessdata
        elif not loaded_cookies and login_failure_message is None:
            login_failure_message = "未找到有效登录信息，请扫码登录"

        if login_failure_message and self.on_login_failed:
            self.on_login_failed(login_failure_message)

        session = auth_manager.create_session_from_cookies(loaded_cookies)
        self.session = session
        self._gift_effect_catalog = GiftEffectCatalog(self.session, self.room_id)

        # 创建客户端和处理器
        self.client = blivedm.BLiveClient(self.room_id, session=session)
        self.handler = DanmakuHandler()
        self.handler.set_danmaku_client(self)
        self.client.set_handler(self.handler)

        self.client.start()

    async def send_danmaku(self, message: str) -> tuple[bool, str]:
        """发送弹幕"""
        if not self.session or not message:
            return False, "会话未初始化或消息为空"

        url = 'https://api.live.bilibili.com/msg/send'

        # 从cookie中获取csrf token (bili_jct)
        csrf_token = ''
        csrf_token = _csrf_token(self.session)

        if not csrf_token:
            # print("Error: No csrf_token found in cookies")
            return False, "未找到CSRF Token，请重新连接或检查Cookie"

        data = {
            'bubble': '0',
            'msg': message,
            'color': '16777215',
            'mode': '1',
            'fontsize': '25',
            'rnd': str(int(time.time())),
            'roomid': self.room_id,
            'csrf': csrf_token,
            'csrf_token': csrf_token,
        }

        try:
            async with self.session.post(url, data=data) as res:
                if res.status != 200:
                    print(f"Send danmaku HTTP error: {res.status}")
                    return False, f"HTTP错误: {res.status}"
                json_data = _json_mapping(await res.json())
                if json_data.get("code") == 0:
                    return True, "发送成功"
                else:
                    message = _json_string(json_data.get("message"))
                    if not message:
                        message = _json_string(json_data.get("msg"))
                    if not message:
                        message = "未知错误"
                    print(f"Send danmaku failed: {message}")
                    return False, f"发送失败: {message}"
        except Exception as e:
            print(f"Send danmaku exception: {e}")
            return False, f"发送异常: {str(e)}"

    async def fetch_audience_snapshot(self) -> AudienceSnapshot:
        """Fetch and normalize the room's current audience and ranking state."""
        if not self.session:
            raise RuntimeError("弹幕会话未初始化")

        headers = {"Referer": f"https://live.bilibili.com/{self.room_id}"}
        async with self.session.get(
            LIVE_ROOM_INFO_URL,
            params={"room_id": self.room_id},
            headers=headers,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"直播间信息 HTTP错误: {response.status}")
            room_payload = _json_mapping(await response.json(content_type=None))

        anchor_uid = parse_anchor_uid(room_payload)
        rank_params = {
            "ruid": anchor_uid,
            "room_id": self.room_id,
            "page": 1,
            "page_size": 100,
            "type": "online_rank",
            "switch": "contribution_rank",
            "platform": "web",
        }
        async with self.session.get(
            LIVE_AUDIENCE_RANK_URL,
            params=rank_params,
            headers=headers,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"在线榜 HTTP错误: {response.status}")
            rank_payload = _json_mapping(await response.json(content_type=None))

        snapshot = parse_audience_snapshot(self.room_id, room_payload, rank_payload)
        if self._total_likes is not None:
            return replace(snapshot, total_likes=self._total_likes)
        return snapshot

    async def fetch_live_emoticons(self) -> list[LiveEmoticonPackage]:
        """Fetch room-specific live emoticon packages."""
        if not self.session:
            raise RuntimeError("弹幕会话未初始化")
        now = time.time()
        if (
            self._live_emoticon_cache is not None
            and now - self._live_emoticon_cache_at < LIVE_EMOTICON_CACHE_TTL_SECONDS
        ):
            return self._live_emoticon_cache

        url = "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons"
        params = {"platform": "pc", "room_id": self.room_id}
        headers = {"Referer": f"https://live.bilibili.com/{self.room_id}"}
        async with self.session.get(url, params=params, headers=headers) as res:
            if res.status != 200:
                raise RuntimeError(f"HTTP错误: {res.status}")
            payload = _json_mapping(await res.json(content_type=None))
        packages = parse_live_emoticon_packages(payload)
        self._live_emoticon_cache = packages
        self._live_emoticon_cache_at = now
        return packages

    async def send_live_emoticon(self, emoticon: LiveEmoticon) -> tuple[bool, str]:
        """Send a pure live emoticon."""
        if not self.session:
            return False, "会话未初始化"
        if not emoticon.is_available:
            label = emoticon.unlock_label or "当前账号"
            return False, f"表情未解锁: {label}"

        csrf_token = ""
        csrf_token = _csrf_token(self.session)
        if not csrf_token:
            return False, "未找到CSRF Token，请重新连接或检查Cookie"

        if _is_text_escape_emoticon(emoticon):
            return await self.send_danmaku(_text_escape_message(emoticon.emoji))

        data = build_live_emoticon_payload(
            room_id=self.room_id,
            csrf_token=csrf_token,
            rnd=str(int(time.time())),
            emoticon=emoticon,
        )

        try:
            send_url = await self._signed_live_msg_send_url()
            async with self.session.post(send_url, data=_multipart_form_data(data)) as res:
                if res.status != 200:
                    return False, f"HTTP错误: {res.status}"
                json_data = _json_mapping(await res.json())
                if json_data.get("code") == 0:
                    return True, "发送成功"
                code = json_data.get("code")
                message = json_data.get("message") or json_data.get("msg") or "未知错误"
                return False, f"发送失败: {message} (code={code})"
        except Exception as e:
            return False, f"发送异常: {str(e)}"

    async def _signed_live_msg_send_url(self) -> str:
        mixin_key = await self._get_wbi_mixin_key()
        wts = str(int(time.time()))
        signed_params = _sign_wbi_params({"web_location": LIVE_WEB_LOCATION}, mixin_key, wts)
        query = urlencode(
            {
                "web_location": signed_params["web_location"],
                "w_rid": signed_params["w_rid"],
                "wts": signed_params["wts"],
            }
        )
        return f"{LIVE_MSG_SEND_URL}?{query}"

    async def _get_wbi_mixin_key(self) -> str:
        if self._wbi_mixin_key:
            return self._wbi_mixin_key
        if not self.session:
            raise RuntimeError("弹幕会话未初始化")

        async with self.session.get(WBI_NAV_URL) as res:
            if res.status != 200:
                raise RuntimeError(f"WBI key HTTP错误: {res.status}")
            payload = _json_mapping(await res.json(content_type=None))

        if payload.get("code") != 0:
            message = payload.get("message") or payload.get("msg") or "获取WBI key失败"
            raise RuntimeError(str(message))

        raw_data = payload.get("data")
        data = _json_mapping(raw_data) if isinstance(raw_data, dict) else {}
        raw_wbi_img = data.get("wbi_img")
        wbi_img = _json_mapping(raw_wbi_img) if isinstance(raw_wbi_img, dict) else {}
        mixin_key = _build_wbi_mixin_key(str(wbi_img.get("img_url") or ""), str(wbi_img.get("sub_url") or ""))
        if not mixin_key:
            raise RuntimeError("获取WBI key失败")
        self._wbi_mixin_key = mixin_key
        return mixin_key

    def schedule_gift_message(self, data: Mapping[str, object]) -> None:
        """Resolve an optional official effect before delivering one raw gift event."""
        catalog = self._gift_effect_catalog
        if catalog is None:
            self._emit_raw_gift(data)
            return
        task = asyncio.create_task(
            self._resolve_and_emit_gift(data, catalog),
            name=f"bilihud-gift-effect-{self.room_id}",
        )
        self._gift_effect_tasks.add(task)
        task.add_done_callback(self._gift_effect_task_done)

    def schedule_guard_purchase(self, purchase: GuardPurchase) -> None:
        """Resolve and publish one guard purchase while suppressing duplicate wire events."""
        if not self._claim_guard_event(purchase):
            return
        catalog = self._gift_effect_catalog
        if catalog is None:
            self._deliver_message(to_hud_guard_message(purchase))
            return
        task = asyncio.create_task(
            self._resolve_and_emit_guard(purchase, catalog),
            name=f"bilihud-guard-effect-{self.room_id}",
        )
        self._gift_effect_tasks.add(task)
        task.add_done_callback(self._gift_effect_task_done)

    async def _resolve_and_emit_gift(
        self,
        data: Mapping[str, object],
        catalog: GiftEffectCatalog,
    ) -> None:
        """Fetch a gift asset without blocking the WebSocket callback thread."""
        try:
            raw_message = web_models.GiftMessage.from_command(dict(data))
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("Failed to parse raw gift message: %s", error)
            self._deliver_message(to_hud_message_or_system(dict(data)))
            return

        effect_asset = None
        try:
            effect_asset = await catalog.resolve(raw_message.gift_id)
        except GiftEffectLookupError as error:
            logger.info("Official gift effect unavailable for gift_id=%s: %s", raw_message.gift_id, error)

        self._deliver_gift(
            raw_message,
            gift_effect_url="" if effect_asset is None else effect_asset.full_screen_url,
            gift_animation_url=(
                _raw_gift_animation_url(data)
                if effect_asset is None or not effect_asset.animation_url
                else effect_asset.animation_url
            ),
            gift_effect_layout=None if effect_asset is None else effect_asset.layout,
        )

    async def _resolve_and_emit_guard(
        self,
        purchase: GuardPurchase,
        catalog: GiftEffectCatalog,
    ) -> None:
        """Fetch the Bilibili full-screen guard effect before publishing the purchase."""
        effect_asset = None
        try:
            effect_asset = await catalog.resolve_special_effect(purchase.effect_id)
        except GiftEffectLookupError as error:
            logger.info(
                "Official guard effect unavailable for effect_id=%s: %s",
                purchase.effect_id,
                error,
            )
        self._deliver_message(
            to_hud_guard_message(
                purchase,
                gift_effect_url="" if effect_asset is None else effect_asset.full_screen_url,
                gift_effect_layout=None if effect_asset is None else effect_asset.layout,
            )
        )

    def _emit_raw_gift(self, data: Mapping[str, object]) -> None:
        """Deliver a gift immediately when the optional catalog is not running."""
        try:
            raw_message = web_models.GiftMessage.from_command(dict(data))
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("Failed to parse raw gift message: %s", error)
            self._deliver_message(to_hud_message_or_system(dict(data)))
            return
        self._deliver_gift(raw_message, gift_animation_url=_raw_gift_animation_url(data))

    def _deliver_gift(
        self,
        raw_message: web_models.GiftMessage,
        *,
        gift_effect_url: str = "",
        gift_animation_url: str = "",
        gift_effect_layout: GiftEffectLayout | None = None,
    ) -> None:
        """Convert and publish one gift with its optional normalized resources."""
        self._deliver_message(
            to_hud_gift_message(
                raw_message,
                gift_effect_url=gift_effect_url,
                gift_animation_url=gift_animation_url,
                gift_effect_layout=gift_effect_layout,
            )
        )

    def _claim_guard_event(self, purchase: GuardPurchase) -> bool:
        """Accept one purchase key for a short window shared by GUARD_BUY and toast events."""
        now = time.monotonic()
        expired = tuple(
            key
            for key, timestamp in self._recent_guard_events.items()
            if now - timestamp >= GUARD_EVENT_DEDUP_TTL_SECONDS
        )
        for key in expired:
            del self._recent_guard_events[key]
        event_key = (
            purchase.uid,
            purchase.guard_level,
            purchase.gift_id,
            purchase.quantity,
            purchase.unit_price,
            purchase.event_id if purchase.uid <= 0 else "",
        )
        if event_key in self._recent_guard_events:
            return False
        self._recent_guard_events[event_key] = now
        return True

    def _deliver_message(self, message: HudMessage) -> None:
        """Invoke the application callback when one is registered."""
        callback = self.on_message_received
        if callback is not None:
            callback(message)

    def _gift_effect_task_done(self, task: asyncio.Task[None]) -> None:
        """Remove a completed lookup task and surface unexpected task failures."""
        self._gift_effect_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Gift effect task failed", exc_info=(type(error), error, error.__traceback__))

    async def _cancel_gift_effect_tasks(self) -> None:
        """Cancel and await all gift lookup tasks before closing their HTTP session."""
        tasks = tuple(self._gift_effect_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._gift_effect_tasks.clear()

    async def stop(self, normal_timeout: float = 3.0, forced_timeout: float = 3.0) -> None:
        """Stop the underlying client and close all network resources it owns."""
        client = self.client
        session = self.session
        join_task: asyncio.Task | None = None
        stop_error: BaseException | None = None

        await self._cancel_gift_effect_tasks()

        if client:
            try:
                if client.is_running:
                    client.stop()
                    join_task = asyncio.create_task(client.join())
                    try:
                        await asyncio.wait_for(asyncio.shield(join_task), timeout=normal_timeout)
                    except TimeoutError:
                        if session and not session.closed:
                            await session.close()
                        try:
                            await asyncio.wait_for(asyncio.shield(join_task), timeout=forced_timeout)
                        except TimeoutError as exc:
                            stop_error = DanmakuShutdownError(
                                f"弹幕连接未能在强制关闭后停止，room_id={self.room_id}"
                            )
                            stop_error.__cause__ = exc
                            join_task.cancel()
                            await asyncio.gather(join_task, return_exceptions=True)
                    except Exception as exc:
                        stop_error = exc
            finally:
                try:
                    await client.close()
                except Exception as exc:
                    if stop_error is None:
                        stop_error = exc

        if session and not session.closed:
            await session.close()
        if stop_error is None:
            self.client = None
            self.session = None
            self.handler = None
            self._gift_effect_catalog = None
            self._recent_guard_events.clear()

        if stop_error is not None:
            raise stop_error


class DanmakuShutdownError(RuntimeError):
    """Raised when the underlying danmaku client ignores forced shutdown."""
    pass


def _wbi_key_from_url(url: str) -> str:
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    return filename.split(".", 1)[0]


def _build_wbi_mixin_key(img_url: str, sub_url: str) -> str:
    raw_key = _wbi_key_from_url(img_url) + _wbi_key_from_url(sub_url)
    if len(raw_key) < max(WBI_MIXIN_KEY_ENC_TAB) + 1:
        return ""
    return "".join(raw_key[index] for index in WBI_MIXIN_KEY_ENC_TAB)[:32]


def _sign_wbi_params(params: dict[str, str], mixin_key: str, wts: str) -> dict[str, str]:
    signed_params = {key: str(value) for key, value in params.items()}
    signed_params["wts"] = wts
    safe_params = {
        key: "".join(ch for ch in value if ch not in "!'()*")
        for key, value in signed_params.items()
    }
    query = urlencode(sorted(safe_params.items()))
    signed_params["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
    return signed_params


def _csrf_token(session: NetworkSession) -> str:
    """Read the CSRF cookie through the small third-party session boundary."""
    cookie_jar = session.cookie_jar
    if not isinstance(cookie_jar, Iterable):
        return ""
    for cookie in cookie_jar:
        if isinstance(cookie, HttpCookie) and cookie.key == "bili_jct":
            return cookie.value
    return ""


def _json_mapping(payload: object) -> dict[str, object]:
    """Validate one JSON object before code reads its protocol fields."""
    if not isinstance(payload, dict):
        raise ValueError("B站接口返回的数据格式无效")
    normalized: dict[str, object] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError("B站接口返回的数据格式无效")
        normalized[key] = value
    return normalized


def _json_string(value: object) -> str:
    """Normalize one optional API message field to a displayable string."""
    return value if isinstance(value, str) else ""


def _multipart_form_data(data: dict[str, str | int]) -> aiohttp.FormData:
    form_data = aiohttp.FormData(default_to_multipart=True)
    for key, value in data.items():
        form_data.add_field(key, str(value))
    return form_data


def _is_text_escape_emoticon(emoticon: LiveEmoticon) -> bool:
    return emoticon.package_name.strip().casefold() == "emoji"


def _text_escape_message(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    return f"[{stripped}]"


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕处理器"""

    def __init__(self) -> None:
        super().__init__()
        self.danmaku_client: DanmakuClient | None = None

    def set_danmaku_client(self, client: DanmakuClient) -> None:
        self.danmaku_client = client

    def handle(self, client: ws_base.WebSocketClientBase, command: dict[str, object]) -> object:
        """Intercept gifts and guard events so official resources resolve asynchronously."""
        command_name = command.get("cmd", "")
        if isinstance(command_name, str):
            command_name = command_name.split(":", 1)[0]
        if command_name == "SEND_GIFT":
            raw_data = command.get("data")
            danmaku_client = self.danmaku_client
            if danmaku_client is not None and isinstance(raw_data, Mapping):
                danmaku_client.schedule_gift_message(_string_mapping(raw_data))
                return None
        if command_name in {"GUARD_BUY", "USER_TOAST_MSG", "USER_TOAST_MSG_V2"}:
            raw_data = command.get("data")
            danmaku_client = self.danmaku_client
            if danmaku_client is not None and isinstance(raw_data, Mapping):
                purchase = parse_guard_purchase(_string_mapping(raw_data))
                if purchase is not None:
                    danmaku_client.schedule_guard_purchase(purchase)
                return None
        if command_name == "LIVE_OPEN_PLATFORM_GUARD":
            raw_data = command.get("data")
            danmaku_client = self.danmaku_client
            if danmaku_client is not None and isinstance(raw_data, Mapping):
                purchase = parse_open_guard_purchase(_string_mapping(raw_data))
                if purchase is not None:
                    danmaku_client.schedule_guard_purchase(purchase)
                return None
        if command_name == "LIKE_INFO_V3_CLICK":
            raw_data = command.get("data")
            if isinstance(raw_data, Mapping):
                self._emit_normalized_message(to_hud_like_message(_string_mapping(raw_data)))
            return None
        if command_name == "LIKE_INFO_V3_UPDATE":
            raw_data = command.get("data")
            danmaku_client = self.danmaku_client
            if danmaku_client is not None and isinstance(raw_data, Mapping):
                danmaku_client.update_total_likes(to_hud_total_likes(_string_mapping(raw_data)))
            return None
        if command_name == "VOICE_REPORT_LIKE":
            raw_data = command.get("data")
            if isinstance(raw_data, Mapping):
                for message in to_hud_voice_report_like_messages(_string_mapping(raw_data)):
                    self._emit_normalized_message(message)
            return None
        return super().handle(client, command)

    def _emit_normalized_message(self, message: HudMessage) -> None:
        """Deliver one already-normalized message to the application callback."""
        danmaku_client = self.danmaku_client
        if danmaku_client is None:
            return
        callback = danmaku_client.on_message_received
        if callback is not None:
            callback(message)

    def _emit_message(self, message: object) -> None:
        """Convert a raw callback payload before handing it to application consumers."""
        self._emit_normalized_message(to_hud_message_or_system(message))

    def _on_danmaku(self, client: ws_base.WebSocketClientBase, message: web_models.DanmakuMessage) -> None:
        """处理弹幕消息"""
        self._emit_message(message)

    def _on_gift(self, client: ws_base.WebSocketClientBase, message: web_models.GiftMessage) -> None:
        """处理礼物消息"""
        self._emit_message(message)

    def _on_buy_guard(
        self,
        client: ws_base.WebSocketClientBase,
        message: web_models.GuardBuyMessage,
    ) -> None:
        """处理旧版上舰消息并复用官方全屏特效链路。"""
        danmaku_client = self.danmaku_client
        if danmaku_client is not None:
            danmaku_client.schedule_guard_purchase(guard_purchase_from_guard_buy(message))

    def _on_user_toast_v2(
        self,
        client: ws_base.WebSocketClientBase,
        message: web_models.UserToastV2Message,
    ) -> None:
        """处理新版上舰庆祝消息，过滤 B 站发送的赠送副本。"""
        purchase = guard_purchase_from_user_toast(message)
        danmaku_client = self.danmaku_client
        if purchase is not None and danmaku_client is not None:
            danmaku_client.schedule_guard_purchase(purchase)

    def _on_open_live_buy_guard(
        self,
        client: ws_base.WebSocketClientBase,
        message: open_models.GuardBuyMessage,
    ) -> None:
        """处理开放平台上舰消息并使用默认官方等级特效。"""
        danmaku_client = self.danmaku_client
        if danmaku_client is not None:
            danmaku_client.schedule_guard_purchase(guard_purchase_from_open_guard(message))

    def _on_interact_word_v2(
        self,
        client: ws_base.WebSocketClientBase,
        message: web_models.InteractWordV2Message,
    ) -> None:
        """处理进入房间/关注"""
        self._emit_message(message)

    def _on_super_chat(self, client: ws_base.WebSocketClientBase, message: web_models.SuperChatMessage) -> None:
        """处理醒目留言"""
        # 可以在这里处理醒目留言
        pass


def _raw_gift_animation_url(data: Mapping[str, object]) -> str:
    """Extract the legacy official GIF as a fast fallback while detail loads."""
    gift_info = data.get("gift_info")
    if not isinstance(gift_info, Mapping):
        return ""
    value = gift_info.get("gif")
    if not isinstance(value, str):
        return ""
    return normalize_official_resource_url(value)


def _string_mapping(value: object) -> dict[str, object]:
    """Normalize an incoming command payload before passing it to a typed parser."""
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}
