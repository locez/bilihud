import base64
import hashlib
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aiohttp

from .live_api import StreamCredential

OBS_WEBSOCKET_RPC_VERSION = 1


class ObsApiError(RuntimeError):
    pass


def is_obs_process_name(command: str) -> bool:
    name = Path(command).name
    return name in {"obs", "obs-studio"}


def obs_check_button_state(port_valid: bool, checking: bool, connected: bool) -> tuple[bool, str]:
    if checking:
        return False, "检查中"
    return port_valid, "重新检查" if connected else "检查 OBS"


def is_obs_process_running(proc_root: str = "/proc") -> bool:
    proc_path = Path(proc_root)
    if not proc_path.exists():
        return False

    for entry in proc_path.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "comm").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if is_obs_process_name(command):
            return True
    return False


def find_obs_executable() -> str | None:
    for command in ("obs", "obs-studio"):
        executable = shutil.which(command)
        if executable:
            return executable
    return None


def launch_obs() -> subprocess.Popen[Any]:
    executable = find_obs_executable()
    if not executable:
        raise ObsApiError("未找到 OBS 可执行文件，请先安装 OBS 或确认命令 obs/obs-studio 在 PATH 中。")
    return subprocess.Popen(
        [executable],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def compute_obs_auth(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


def build_set_stream_service_request(server: str, key: str) -> dict[str, Any]:
    return {
        "requestType": "SetStreamServiceSettings",
        "requestId": "set-bilihud-stream-service",
        "requestData": {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {
                "server": server,
                "key": key,
            },
        },
    }


def build_start_stream_request() -> dict[str, Any]:
    return {
        "requestType": "StartStream",
        "requestId": "start-bilihud-stream",
    }


def build_stop_stream_request() -> dict[str, Any]:
    return {
        "requestType": "StopStream",
        "requestId": "stop-bilihud-stream",
    }


def obs_start_stream_requests(credential: StreamCredential) -> list[dict[str, Any]]:
    return [
        build_set_stream_service_request(credential.address, credential.key),
        build_start_stream_request(),
    ]


def pick_primary_credential(credentials: Sequence[StreamCredential]) -> StreamCredential | None:
    for credential in credentials:
        if credential.label == "rtmp-1":
            return credential
    for credential in credentials:
        if credential.label.lower().startswith("rtmp"):
            return credential
    return credentials[0] if credentials else None


class ObsWebSocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 4455, password: str = "", timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def set_stream_service_settings(self, credential: StreamCredential) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(self.url, timeout=self.timeout) as ws:
                    await self._identify(ws)
                    await self._send_request(ws, build_set_stream_service_request(credential.address, credential.key))
            except TimeoutError as exc:
                raise ObsApiError("连接 OBS WebSocket 超时。") from exc
            except aiohttp.ClientError as exc:
                raise ObsApiError(f"无法连接 OBS WebSocket: {exc}") from exc

    async def check_connection(self) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(self.url, timeout=self.timeout) as ws:
                    await self._identify(ws)
            except TimeoutError as exc:
                raise ObsApiError("连接 OBS WebSocket 超时。") from exc
            except aiohttp.ClientError as exc:
                raise ObsApiError(f"无法连接 OBS WebSocket: {exc}") from exc

    async def set_stream_service_settings_and_start(self, credential: StreamCredential) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(self.url, timeout=self.timeout) as ws:
                    await self._identify(ws)
                    for request in obs_start_stream_requests(credential):
                        await self._send_request(ws, request)
            except TimeoutError as exc:
                raise ObsApiError("连接 OBS WebSocket 超时。") from exc
            except aiohttp.ClientError as exc:
                raise ObsApiError(f"无法连接 OBS WebSocket: {exc}") from exc

    async def stop_stream(self) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(self.url, timeout=self.timeout) as ws:
                    await self._identify(ws)
                    await self._send_request(ws, build_stop_stream_request())
            except TimeoutError as exc:
                raise ObsApiError("连接 OBS WebSocket 超时。") from exc
            except aiohttp.ClientError as exc:
                raise ObsApiError(f"无法连接 OBS WebSocket: {exc}") from exc

    async def _identify(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        hello = await self._receive_json(ws)
        if hello.get("op") != 0:
            raise ObsApiError("OBS WebSocket 未返回 Hello。")

        hello_data = dict(hello.get("d") or {})
        identify_data: dict[str, Any] = {
            "rpcVersion": min(int(hello_data.get("rpcVersion") or OBS_WEBSOCKET_RPC_VERSION), OBS_WEBSOCKET_RPC_VERSION)
        }
        authentication = hello_data.get("authentication")
        if authentication:
            if not self.password:
                raise ObsApiError("OBS WebSocket 需要密码，请在直播控制窗口填写。")
            identify_data["authentication"] = compute_obs_auth(
                self.password,
                str(authentication.get("salt") or ""),
                str(authentication.get("challenge") or ""),
            )

        await ws.send_json({"op": 1, "d": identify_data})
        identified = await self._receive_json(ws)
        if identified.get("op") != 2:
            raise ObsApiError("OBS WebSocket 认证失败。")

    async def _send_request(self, ws: aiohttp.ClientWebSocketResponse, request: dict[str, Any]) -> dict[str, Any]:
        request = {**request, "requestId": f"{request['requestId']}-{uuid.uuid4().hex}"}
        await ws.send_json({"op": 6, "d": request})
        while True:
            message = await self._receive_json(ws)
            if message.get("op") != 7:
                continue
            response = dict(message.get("d") or {})
            if response.get("requestId") != request["requestId"]:
                continue
            status = dict(response.get("requestStatus") or {})
            if not status.get("result"):
                raise ObsApiError(str(status.get("comment") or "OBS WebSocket 请求失败。"))
            return response

    async def _receive_json(self, ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
        message = await ws.receive(timeout=self.timeout)
        if message.type == aiohttp.WSMsgType.TEXT:
            data = message.json()
            if isinstance(data, dict):
                return data
        if message.type == aiohttp.WSMsgType.ERROR:
            raise ObsApiError("OBS WebSocket 连接异常。")
        raise ObsApiError("OBS WebSocket 连接已关闭。")
