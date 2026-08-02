import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from urllib.parse import urlencode, urlparse

import aiohttp
import blivedm
import blivedm.clients.ws_base as ws_base
import blivedm.models.web as web_models

from .auth import AuthenticationService, AuthManager
from .domain.messages import HudMessage
from .infrastructure.blivedm_adapter import to_hud_message_or_system
from .live_audience import AudienceSnapshot, parse_anchor_uid, parse_audience_snapshot
from .live_emoticons import (
    LiveEmoticon,
    LiveEmoticonPackage,
    build_live_emoticon_payload,
    parse_live_emoticon_packages,
)

WBI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
LIVE_MSG_SEND_URL = "https://api.live.bilibili.com/msg/send"
LIVE_ROOM_INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
LIVE_AUDIENCE_RANK_URL = (
    "https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank"
)
LIVE_WEB_LOCATION = "444.8"
LIVE_EMOTICON_CACHE_TTL_SECONDS = 60.0
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
        auth_service: AuthenticationService | None = None,
    ) -> None:
        """Create a client for one room with an optional injected auth service."""
        self.room_id = room_id
        self.sessdata = sessdata  # Optional one-off SESSDATA override for this connection.
        self.auth_service = auth_service  # Shared authentication boundary from the app.
        self.session: aiohttp.ClientSession | None = None  # Owned and closed by this client.
        self.client: blivedm.BLiveClient | None = None  # Underlying blivedm lifecycle handle.
        self.handler: DanmakuHandler | None = None  # Callback bridge owned by the client.
        self.on_message_received: Callable[[HudMessage], None] | None = None
        self.on_login_failed: Callable[[str], None] | None = None # callback(message)
        self._wbi_mixin_key: str | None = None  # Cached signing key for authenticated sends.
        self._live_emoticon_cache: list[LiveEmoticonPackage] | None = None  # Short-lived room cache.
        self._live_emoticon_cache_at = 0.0  # Monotonic timestamp for the emoticon cache.

    @property
    def is_running(self) -> bool:
        """Report the underlying BLive connection state through this client boundary."""
        client = self.client
        return client is not None and client.is_running

    def set_message_callback(self, callback: Callable[[HudMessage], None]) -> None:
        """设置接收已转换为领域模型的直播消息回调。"""
        self.on_message_received = callback

    def set_login_failed_callback(self, callback: Callable[[str], None]) -> None:
        """设置登录失效回调"""
        self.on_login_failed = callback

    async def start(self) -> None:
        """Load authentication, create owned network resources, and start receiving messages."""
        loop = asyncio.get_running_loop()
        auth_manager = self.auth_service if self.auth_service is not None else AuthManager()
        login_failure_message: str | None = None

        try:
            loaded_cookies, is_keyring = await loop.run_in_executor(None, auth_manager.load_auth_cookies)
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

        self.session = auth_manager.create_session_from_cookies(loaded_cookies)

        # 创建客户端和处理器
        self.client = blivedm.BLiveClient(self.room_id, session=self.session)
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
        for cookie in self.session.cookie_jar:
            if cookie.key == 'bili_jct':
                csrf_token = cookie.value
                break

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
                json_data = await res.json()
                if json_data['code'] == 0:
                    return True, "发送成功"
                else:
                    print(f"Send danmaku failed: {json_data['message']}")
                    return False, f"发送失败: {json_data['message']}"
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
            room_payload = await response.json(content_type=None)

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
            rank_payload = await response.json(content_type=None)

        return parse_audience_snapshot(self.room_id, room_payload, rank_payload)

    async def fetch_live_emoticons(self):
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
            payload = await res.json(content_type=None)
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
        for cookie in self.session.cookie_jar:
            if cookie.key == "bili_jct":
                csrf_token = cookie.value
                break
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
                json_data = await res.json()
                if json_data["code"] == 0:
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
            payload = await res.json(content_type=None)

        if payload.get("code") != 0:
            message = payload.get("message") or payload.get("msg") or "获取WBI key失败"
            raise RuntimeError(str(message))

        wbi_img = (payload.get("data") or {}).get("wbi_img") or {}
        mixin_key = _build_wbi_mixin_key(str(wbi_img.get("img_url") or ""), str(wbi_img.get("sub_url") or ""))
        if not mixin_key:
            raise RuntimeError("获取WBI key失败")
        self._wbi_mixin_key = mixin_key
        return mixin_key

    async def stop(self, normal_timeout: float = 3.0, forced_timeout: float = 3.0):
        """Stop the underlying client and close all network resources it owns."""
        client = self.client
        session = self.session
        join_task: asyncio.Task | None = None
        stop_error: BaseException | None = None

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

    def _emit_message(self, message: object) -> None:
        """Convert a raw callback payload before handing it to application consumers."""
        danmaku_client = self.danmaku_client
        if danmaku_client is None:
            return
        callback = danmaku_client.on_message_received
        if callback is not None:
            callback(to_hud_message_or_system(message))

    def _on_danmaku(self, client: ws_base.WebSocketClientBase, message: web_models.DanmakuMessage) -> None:
        """处理弹幕消息"""
        self._emit_message(message)

    def _on_gift(self, client: ws_base.WebSocketClientBase, message: web_models.GiftMessage) -> None:
        """处理礼物消息"""
        self._emit_message(message)

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
