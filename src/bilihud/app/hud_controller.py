"""Application coordination for the HUD room and message workflows."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from ..auth.service import DanmakuAuthenticationService
from ..config.store import ConfigStore
from ..danmaku.messages import HudMessage
from ..live.audience import AudienceSnapshot
from ..live.emoticons import LiveEmoticon, LiveEmoticonPackage
from ..live.validation import validate_room_id
from .hud import (
    HudConnectionStatus,
    HudEvent,
    HudEventListener,
    HudLoginFailed,
    HudMessageReceived,
    HudOperation,
    HudOperationFailed,
    HudSendResult,
    HudState,
    HudStateChanged,
)
from .hud_client import HudClient, HudClientFactory
from .lifecycle import TaskScope, TaskSupervisor, cancel_task

logger = logging.getLogger(__name__)
AUDIENCE_REFRESH_INTERVAL_SECONDS = 30.0

class HudController:
    """Own HUD connection, room switching, audience refresh, and send commands."""

    def __init__(
        self,
        *,
        initial_room_id: int,
        sessdata: str,
        auth_service: DanmakuAuthenticationService,
        client_factory: HudClientFactory,
        config_store: ConfigStore | None = None,
        task_scope: TaskScope | None = None,
    ) -> None:
        """Create a controller with explicit infrastructure and task ownership."""
        self._sessdata = sessdata  # Optional one-off session override for new connections.
        self._auth_service = auth_service  # Shared authentication boundary from the composition root.
        self._client_factory = client_factory  # Infrastructure capability injected by the composition root.
        self._config_store = config_store  # Optional persistence for the last selected room.
        if task_scope is None:
            task_supervisor = TaskSupervisor()
            self._task_supervisor: TaskSupervisor | None = task_supervisor
            self._owns_task_supervisor = True
            self._task_scope = task_supervisor.create_scope("hud-controller")
        else:
            self._task_supervisor = None
            self._owns_task_supervisor = False
            self._task_scope = task_scope

        room_id = initial_room_id if initial_room_id > 0 else None
        self._state = HudState(room_id=room_id)
        self._client: HudClient | None = None  # Current client and its network resources.
        self._generation = 0  # Invalidates callbacks and refresh results from old rooms.
        self._audience_task: asyncio.Task[None] | None = None  # Owned periodic audience workflow.
        self._listeners: list[HudEventListener] = []  # Typed presentation subscribers.
        self._operation_lock = asyncio.Lock()  # Serializes room changes and outbound sends.
        self._shutting_down = False
        self._shutdown_complete = False

    @property
    def state(self) -> HudState:
        """Return the latest immutable state snapshot for presentation binding."""
        return self._state

    def subscribe(self, listener: HudEventListener) -> None:
        """Register one typed event listener until it is explicitly removed."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: HudEventListener) -> None:
        """Remove a previously registered event listener when it is still present."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def connect(self, room_id: int) -> None:
        """Connect to a room, replacing stale or different active connections."""
        if not validate_room_id(room_id):
            raise ValueError("直播间号无效")
        async with self._operation_lock:
            self._ensure_open()
            await self._connect_locked(room_id)

    async def disconnect(self) -> None:
        """Disconnect the current room and clear its audience workflow."""
        async with self._operation_lock:
            self._ensure_open()
            await self._disconnect_locked()

    async def toggle_connection(self, room_id: int) -> None:
        """Toggle the connection or connect to the supplied room when disconnected."""
        if not validate_room_id(room_id):
            raise ValueError("直播间号无效")
        async with self._operation_lock:
            self._ensure_open()
            client = self._client
            if (
                self._state.connection is HudConnectionStatus.CONNECTED
                and client is not None
                and client.is_running
            ):
                await self._disconnect_locked()
            else:
                await self._connect_locked(room_id)

    async def send_danmaku(self, message: str) -> HudSendResult:
        """Send one text message through the current room-owned client."""
        if not message.strip():
            result = HudSendResult(False, "消息为空")
            self._record_operation_failure(HudOperation.SEND_DANMAKU, result.message)
            return result

        async with self._operation_lock:
            self._ensure_open()
            unavailable_message = "未连接直播间，无法发送"
            client = self._connected_client(HudOperation.SEND_DANMAKU, unavailable_message)
            if client is None:
                return HudSendResult(False, unavailable_message)
            try:
                success, response = await client.send_danmaku(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = self._exception_message(exc, "发送异常")
                result = HudSendResult(False, response)
            else:
                result = HudSendResult(success, response)

            if result.success:
                self._clear_error()
            else:
                self._record_operation_failure(HudOperation.SEND_DANMAKU, result.message)
            return result

    async def fetch_live_emoticons(self) -> list[LiveEmoticonPackage]:
        """Fetch live emoticons through the current room-owned client."""
        async with self._operation_lock:
            self._ensure_open()
            unavailable_message = "未连接直播间，无法加载表情"
            client = self._connected_client(HudOperation.FETCH_EMOTICONS, unavailable_message)
            if client is None:
                raise RuntimeError(unavailable_message)
            try:
                return await client.fetch_live_emoticons()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = self._exception_message(exc, "获取直播间表情失败")
                self._record_operation_failure(HudOperation.FETCH_EMOTICONS, message)
                raise

    async def send_live_emoticon(self, emoticon: LiveEmoticon) -> HudSendResult:
        """Send one live emoticon through the current room-owned client."""
        async with self._operation_lock:
            self._ensure_open()
            unavailable_message = "未连接直播间，无法发送"
            client = self._connected_client(HudOperation.SEND_EMOTICON, unavailable_message)
            if client is None:
                return HudSendResult(False, unavailable_message)
            try:
                success, response = await client.send_live_emoticon(emoticon)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = self._exception_message(exc, "发送异常")
                result = HudSendResult(False, response)
            else:
                result = HudSendResult(success, response)

            if result.success:
                self._clear_error()
            else:
                self._record_operation_failure(HudOperation.SEND_EMOTICON, result.message)
            return result

    async def shutdown(self) -> None:
        """Stop the connection, cancel owned refresh work, and release task ownership."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        shutdown_error: BaseException | None = None
        try:
            async with self._operation_lock:
                if self._client is not None:
                    await self._disconnect_locked()
                else:
                    await self._stop_audience_refresh()
                    self._generation += 1
                    self._publish_state(
                        HudConnectionStatus.DISCONNECTED,
                        self._state.room_id,
                        None,
                        None,
                    )
                await self._task_scope.cancel_all()
        except BaseException as exc:
            shutdown_error = exc
        finally:
            if self._owns_task_supervisor and self._task_supervisor is not None:
                try:
                    await self._task_supervisor.shutdown()
                except BaseException as exc:
                    if shutdown_error is None:
                        shutdown_error = exc

        if shutdown_error is not None:
            raise shutdown_error
        self._shutdown_complete = True

    async def _connect_locked(self, room_id: int) -> None:
        """Connect while the operation lock prevents competing room transitions."""
        client = self._client
        if (
            self._state.connection is HudConnectionStatus.CONNECTED
            and client is not None
            and client.is_running
            and self._state.room_id == room_id
        ):
            if self._audience_task is None:
                await self._start_audience_refresh(client)
            return

        if client is not None:
            await self._disconnect_locked()

        self._generation += 1
        generation = self._generation
        self._persist_room_id(room_id)
        self._publish_state(HudConnectionStatus.CONNECTING, room_id, None, None)

        try:
            client = self._client_factory(room_id, self._sessdata, self._auth_service)
        except Exception as exc:
            message = self._exception_message(exc, "创建弹幕连接失败")
            self._publish_state(HudConnectionStatus.DISCONNECTED, room_id, None, message)
            self._emit(HudOperationFailed(HudOperation.CONNECT, message))
            raise

        self._client = client
        self._wire_client(client, generation)
        try:
            await client.start()
        except asyncio.CancelledError:
            await self._cleanup_failed_client(client)
            self._publish_state(HudConnectionStatus.DISCONNECTED, room_id, None, "连接已取消")
            raise
        except Exception as exc:
            message = self._exception_message(exc, "连接失败")
            await self._cleanup_failed_client(client)
            self._publish_state(HudConnectionStatus.DISCONNECTED, room_id, None, message)
            self._emit(HudOperationFailed(HudOperation.CONNECT, message))
            raise

        self._publish_state(
            HudConnectionStatus.CONNECTED,
            room_id,
            None,
            self._state.error,
        )
        await self._start_audience_refresh(client)

    async def _disconnect_locked(self) -> None:
        """Disconnect while retaining enough state to restore a failed close."""
        client = self._client
        room_id = self._state.room_id
        if client is None:
            await self._stop_audience_refresh()
            self._generation += 1
            self._publish_state(HudConnectionStatus.DISCONNECTED, room_id, None, None)
            return

        previous_snapshot = self._state.audience_snapshot
        self._generation += 1
        generation = self._generation
        self._publish_state(HudConnectionStatus.DISCONNECTING, room_id, None, None)
        await self._stop_audience_refresh()

        try:
            await client.stop()
        except asyncio.CancelledError:
            await self._restore_after_disconnect_failure(client, generation, previous_snapshot, "断开已取消")
            raise
        except Exception as exc:
            message = self._exception_message(exc, "断开失败")
            await self._restore_after_disconnect_failure(client, generation, previous_snapshot, message)
            self._emit(HudOperationFailed(HudOperation.DISCONNECT, message))
            raise

        self._client = None
        self._publish_state(HudConnectionStatus.DISCONNECTED, room_id, None, None)

    async def _start_audience_refresh(self, client: HudClient) -> None:
        """Start one generation-bound audience task for the current client."""
        await self._stop_audience_refresh()
        generation = self._generation
        self._audience_task = self._task_scope.create_task(
            self._audience_refresh_loop(client, generation),
            name="audience-refresh",
        )

    async def _stop_audience_refresh(self) -> None:
        """Cancel the old audience task before a room or client can change."""
        task = self._audience_task
        self._audience_task = None
        await cancel_task(task)

    async def _audience_refresh_loop(self, client: HudClient, generation: int) -> None:
        """Refresh audience state until cancellation or client generation changes."""
        while True:
            try:
                snapshot = await client.fetch_audience_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = self._exception_message(exc, "获取观众数据失败")
                logger.info("Failed to refresh audience data: %s", message)
                if self._is_current(client, generation):
                    self._publish_state(
                        HudConnectionStatus.CONNECTED,
                        self._state.room_id,
                        self._state.audience_snapshot,
                        message,
                    )
            else:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise asyncio.CancelledError
                if self._is_current(client, generation) and snapshot.room_id == self._state.room_id:
                    self._publish_state(
                        HudConnectionStatus.CONNECTED,
                        self._state.room_id,
                        snapshot,
                        self._state.error,
                    )
            await asyncio.sleep(AUDIENCE_REFRESH_INTERVAL_SECONDS)

    def _wire_client(self, client: HudClient, generation: int) -> None:
        """Bind callbacks with client identity and generation guards."""
        client.set_message_callback(
            lambda message: self._on_message(client, generation, message)
        )
        client.set_total_likes_callback(
            lambda total_likes: self._on_total_likes(client, generation, total_likes)
        )
        client.set_login_failed_callback(
            lambda message: self._on_login_failed(client, generation, message)
        )

    def _on_message(self, client: HudClient, generation: int, message: HudMessage) -> None:
        """Forward only messages from the current room generation."""
        if self._is_current(client, generation, allow_connecting=True):
            self._emit(HudMessageReceived(message))

    def _on_total_likes(self, client: HudClient, generation: int, total_likes: int) -> None:
        """Apply a current-room like total without turning it into a message-list entry."""
        if not self._is_current(client, generation, allow_connecting=True):
            return
        snapshot = self._state.audience_snapshot
        if snapshot is None or snapshot.total_likes == total_likes:
            return
        self._publish_state(
            HudConnectionStatus.CONNECTED,
            self._state.room_id,
            replace(snapshot, total_likes=total_likes),
            self._state.error,
        )

    def _on_login_failed(self, client: HudClient, generation: int, message: str) -> None:
        """Forward only login warnings belonging to the current room generation."""
        if not self._is_current(client, generation, allow_connecting=True):
            return
        self._publish_state(
            self._state.connection,
            self._state.room_id,
            self._state.audience_snapshot,
            message,
        )
        self._emit(HudLoginFailed(message))

    def _is_current(
        self,
        client: HudClient,
        generation: int,
        *,
        allow_connecting: bool = False,
    ) -> bool:
        """Check client identity and generation before accepting async callbacks."""
        valid_statuses = (HudConnectionStatus.CONNECTED,)
        if allow_connecting:
            valid_statuses = (HudConnectionStatus.CONNECTING, HudConnectionStatus.CONNECTED)
        return (
            self._client is client
            and self._generation == generation
            and self._state.connection in valid_statuses
        )

    def _connected_client(self, operation: HudOperation, unavailable_message: str) -> HudClient | None:
        """Return the active client or record a typed failure for the caller."""
        client = self._client
        if (
            client is not None
            and self._state.connection is HudConnectionStatus.CONNECTED
            and client.is_running
        ):
            return client
        self._record_operation_failure(operation, unavailable_message)
        return None

    async def _restore_after_disconnect_failure(
        self,
        client: HudClient,
        generation: int,
        previous_snapshot: AudienceSnapshot | None,
        message: str,
    ) -> None:
        """Restore the live connection contract after a failed close attempt."""
        self._client = client
        self._wire_client(client, generation)
        self._publish_state(HudConnectionStatus.CONNECTED, self._state.room_id, previous_snapshot, message)
        await self._start_audience_refresh(client)

    async def _cleanup_failed_client(self, client: HudClient) -> bool:
        """Close a partially started client and report whether ownership was released."""
        try:
            await client.stop()
        except BaseException as exc:
            logger.error(
                "Failed to clean up HUD client after connection failure",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return False
        else:
            if self._client is client:
                self._client = None
            return True

    def _record_operation_failure(self, operation: HudOperation, message: str) -> None:
        """Publish one stateful operation failure to typed consumers."""
        self._publish_state(
            self._state.connection,
            self._state.room_id,
            self._state.audience_snapshot,
            message,
        )
        self._emit(HudOperationFailed(operation, message))

    def _clear_error(self) -> None:
        if self._state.error is None:
            return
        self._publish_state(
            self._state.connection,
            self._state.room_id,
            self._state.audience_snapshot,
            None,
        )

    def _publish_state(
        self,
        connection: HudConnectionStatus,
        room_id: int | None,
        audience_snapshot: AudienceSnapshot | None,
        error: str | None,
    ) -> None:
        """Publish a complete immutable state value without implicit defaults."""
        state = HudState(
            connection=connection,
            room_id=room_id,
            audience_snapshot=audience_snapshot,
            error=error,
        )
        if state == self._state:
            return
        self._state = state
        self._emit(HudStateChanged(state))

    def _emit(self, event: HudEvent) -> None:
        """Deliver one event while isolating listener failures from application state."""
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                logger.exception("HUD event listener failed")

    def _persist_room_id(self, room_id: int) -> None:
        """Persist the selected room without making configuration failure break a connection."""
        if self._config_store is None:
            return
        try:
            current = self._config_store.load()
            updated = replace(current, room_id=room_id)
            if not self._config_store.save(updated):
                logger.warning("Failed to persist HUD room id %s", room_id)
        except Exception as exc:
            logger.warning("Failed to persist HUD room id %s: %s", room_id, exc)

    def _ensure_open(self) -> None:
        if self._shutting_down:
            raise RuntimeError("HUD 控制器已关闭")

    @staticmethod
    def _exception_message(error: BaseException, fallback: str) -> str:
        """Return a useful stable message even when an exception has no text."""
        message = str(error).strip()
        if not message:
            return fallback
        return message
