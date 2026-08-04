"""Owned async workflows used by the embedded live settings page."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from bilihud.app.lifecycle import TaskScope, cancel_task
from bilihud.live.models import (
    LiveControlOperationResult,
    LiveControlState,
    LiveVerificationKind,
    ObsCheckOutcome,
    ObsSettings,
    ObsStreamOutcome,
    SessionStatus,
    StartLiveOutcome,
    StartLiveStatus,
    StopLiveOutcome,
    StopLiveStatus,
)

logger = logging.getLogger(__name__)

LiveStartedHandler = Callable[[int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class LiveSettingsForm:
    """Normalized values collected from the live settings presentation."""

    room_id: int | None
    title: str
    parent_area_id: str
    area_id: str
    obs: ObsSettings | None


class LiveAction(StrEnum):
    """Identify the primary live action currently running in the page."""

    START = "start"
    STOP = "stop"


class LiveSettingsService(Protocol):
    """Application service contract required by the embedded live settings page."""

    @property
    def state(self) -> LiveControlState:
        """Return the latest immutable service snapshot."""
        ...

    async def initialize(self, room_id: int | None) -> LiveControlOperationResult:
        """Initialize the authenticated live session and load areas."""
        ...

    async def load_room_info(self, room_id: int | None) -> LiveControlOperationResult:
        """Load normalized room metadata."""
        ...

    async def update_title(self, room_id: int | None, title: str) -> LiveControlOperationResult:
        """Update the live-room title."""
        ...

    async def update_area(self, room_id: int | None, area_id: str) -> LiveControlOperationResult:
        """Update the live-room area."""
        ...

    async def start_live(
        self,
        room_id: int | None,
        title: str,
        area_id: str,
        obs_settings: ObsSettings | None,
        *,
        allow_obs_switch: bool = False,
    ) -> StartLiveOutcome:
        """Start Bilibili live and optionally switch an existing OBS stream."""
        ...

    async def stop_live(self, room_id: int | None, obs_settings: ObsSettings | None) -> StopLiveOutcome:
        """Stop Bilibili live and clean up OBS when possible."""
        ...

    async def check_obs(self, settings: ObsSettings | None) -> ObsCheckOutcome:
        """Check the configured OBS WebSocket endpoint."""
        ...

    async def stop_obs_stream(self, settings: ObsSettings | None) -> ObsStreamOutcome:
        """Stop the OBS stream through the configured endpoint."""
        ...

    async def shutdown(self) -> None:
        """Close the service-owned network session."""
        ...


class LiveSettingsView(Protocol):
    """Presentation boundary consumed by live-control workflows."""

    def form_values(self) -> LiveSettingsForm:
        """Return the current normalized form values."""
        ...

    def apply_service_state(self, state: LiveControlState) -> None:
        """Render one service state snapshot."""
        ...

    def set_busy(
        self,
        busy: bool,
        message: str | None = None,
        *,
        action: LiveAction | None = None,
    ) -> None:
        """Enable or disable controls around one workflow."""
        ...

    def set_status(self, message: str, *, error: bool = False, success: bool = False) -> None:
        """Render a user-facing workflow result."""
        ...

    def save_form_config(self) -> bool:
        """Persist the visible settings through the service boundary."""
        ...

    def show_verification(self, url: str, kind: LiveVerificationKind) -> None:
        """Show non-blocking verification UI when the service requires it."""
        ...

    async def confirm_obs_switch(self) -> bool:
        """Ask whether the current OBS stream may be stopped for the new stream."""
        ...

    def set_obs_busy(self, busy: bool) -> None:
        """Bind OBS operation progress to the presentation."""
        ...

    def set_obs_status(self, outcome: ObsCheckOutcome) -> None:
        """Render the normalized OBS check outcome."""
        ...

    def update_action_state(self) -> None:
        """Refresh control availability after a state transition."""
        ...


class LiveSettingsWorkflow:
    """Own cancellable live-control tasks without owning Qt widgets."""

    def __init__(
        self,
        service: LiveSettingsService | None,
        task_scope: TaskScope | None,
        view: LiveSettingsView,
        *,
        on_live_started: LiveStartedHandler | None = None,
    ) -> None:
        """Create a workflow owner with an explicit service and task scope."""
        self._service = service
        self._task_scope = task_scope
        self._view = view
        self._on_live_started = on_live_started
        self._tasks: set[asyncio.Task[None]] = set()
        self._initial_load_task: asyncio.Task[None] | None = None
        self._room_info_task: asyncio.Task[None] | None = None
        self._load_generation = 0
        self._shutting_down = False
        self._shutdown_complete = False

    def activate(self) -> asyncio.Task[None] | None:
        """Start service initialization once when the live tab becomes visible."""
        service = self._service
        if self._shutting_down or service is None:
            return None
        if self._initial_load_task is not None and not self._initial_load_task.done():
            return self._initial_load_task
        if service.state.session.status is not SessionStatus.CLOSED:
            self._view.apply_service_state(service.state)
            return None
        self._load_generation += 1
        self._initial_load_task = self._create_task(
            self._load_initial_state(self._load_generation),
            name="initialize-live-settings",
        )
        return self._initial_load_task

    def reload_room_info(self) -> asyncio.Task[None] | None:
        """Schedule a fresh room metadata request for the current form room."""
        if self._shutting_down or self._service is None:
            return None
        if self._room_info_task is not None and not self._room_info_task.done():
            return self._room_info_task
        self._room_info_task = self._create_task(self._reload_room_info(), name="reload-room-info")
        return self._room_info_task

    def update_title(self) -> asyncio.Task[None] | None:
        """Schedule the room-title update workflow."""
        return self._create_task(self._update_title(), name="update-title")

    def update_area(self) -> asyncio.Task[None] | None:
        """Schedule the room-area update workflow."""
        return self._create_task(self._update_area(), name="update-area")

    def start_live(self) -> asyncio.Task[None] | None:
        """Schedule the complete start-live workflow."""
        return self._create_task(self._start_live(), name="start-live")

    def stop_live(self) -> asyncio.Task[None] | None:
        """Schedule the complete stop-live workflow."""
        return self._create_task(self._stop_live(), name="stop-live")

    def check_obs(self) -> asyncio.Task[None] | None:
        """Schedule an OBS WebSocket check through the service boundary."""
        return self._create_task(self._check_obs(), name="check-obs")

    def stop_obs(self) -> asyncio.Task[None] | None:
        """Schedule a manual OBS stream stop."""
        return self._create_task(self._stop_obs(), name="stop-obs")

    async def shutdown(self) -> None:
        """Cancel page workflows without closing the shared application service."""
        if self._shutdown_complete:
            return
        self._shutting_down = True
        self._load_generation += 1
        await cancel_task(self._initial_load_task)
        await cancel_task(self._room_info_task)
        current = asyncio.current_task()
        pending = tuple(task for task in self._tasks if not task.done() and task is not current)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._shutdown_complete = True

    def _create_task(
        self,
        coroutine: Coroutine[object, object, None],
        *,
        name: str,
    ) -> asyncio.Task[None] | None:
        """Create one owned workflow and close it when no event loop is available."""
        if self._shutting_down or self._task_scope is None:
            coroutine.close()
            return None
        try:
            task = self._task_scope.create_task(coroutine, name=name)
        except RuntimeError:
            coroutine.close()
            return None
        self._tasks.add(task)
        task.add_done_callback(self._discard_task)
        return task

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        """Forget one completed workflow."""
        self._tasks.discard(task)

    async def _load_initial_state(self, generation: int) -> None:
        service = self._service
        if service is None:
            return
        self._view.set_busy(True, "正在加载登录状态和直播分区...")
        try:
            result = await service.initialize(self._view.form_values().room_id)
            if generation != self._load_generation:
                return
            self._view.apply_service_state(result.state)
            if result.error is not None:
                self._view.set_status(result.error.message, error=True)
            elif result.state.session.is_authenticated:
                self._view.set_status("登录状态可用。", success=True)
            else:
                self._view.set_status("请先扫码登录 Bilibili，再进行开播操作。", error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to initialize live settings")
            self._view.set_status(f"初始化失败: {exc}", error=True)
        finally:
            if generation == self._load_generation:
                self._view.set_busy(False)

    async def _reload_room_info(self) -> None:
        service = self._service
        if service is None:
            return
        values = self._view.form_values()
        if values.room_id is None:
            self._view.set_status("房间号无效。", error=True)
            return
        self._view.set_busy(True, "正在加载直播间信息...")
        try:
            result = await service.load_room_info(values.room_id)
            self._view.apply_service_state(result.state)
            if result.error is not None:
                self._view.set_status(result.error.message, error=True)
            else:
                self._view.set_status("直播间信息已更新。", success=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to load live room information")
            self._view.set_status(f"加载直播间信息失败: {exc}", error=True)
        finally:
            self._room_info_task = None
            self._view.set_busy(False)

    async def _update_title(self) -> None:
        service = self._service
        values = self._view.form_values()
        if service is None or values.room_id is None or not values.title:
            self._view.set_status("请填写有效的房间号和标题。", error=True)
            return
        self._view.set_busy(True, "正在更新标题...")
        try:
            result = await service.update_title(values.room_id, values.title)
            self._view.apply_service_state(result.state)
            if result.error is not None:
                self._view.set_status(result.error.message, error=True)
            elif self._view.save_form_config():
                self._view.set_status("直播间标题已更新。", success=True)
            else:
                self._view.set_status("标题已更新，但设置保存失败。", error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to update live room title")
            self._view.set_status(f"更新标题失败: {exc}", error=True)
        finally:
            self._view.set_busy(False)

    async def _update_area(self) -> None:
        service = self._service
        values = self._view.form_values()
        if service is None or values.room_id is None or not values.area_id:
            self._view.set_status("请填写有效的房间号和分区。", error=True)
            return
        self._view.set_busy(True, "正在更新分区...")
        try:
            result = await service.update_area(values.room_id, values.area_id)
            self._view.apply_service_state(result.state)
            if result.error is not None:
                self._view.set_status(result.error.message, error=True)
            elif self._view.save_form_config():
                self._view.set_status("直播间分区已更新。", success=True)
            else:
                self._view.set_status("分区已更新，但设置保存失败。", error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to update live room area")
            self._view.set_status(f"更新分区失败: {exc}", error=True)
        finally:
            self._view.set_busy(False)

    async def _start_live(self) -> None:
        service = self._service
        values = self._view.form_values()
        if service is None or values.room_id is None or not values.title or not values.area_id:
            self._view.set_status("请填写房间号、标题和分区。", error=True)
            return
        self._view.set_busy(True, "正在开始直播...", action=LiveAction.START)
        try:
            config_saved = self._view.save_form_config()
            outcome = await service.start_live(values.room_id, values.title, values.area_id, values.obs)
            if outcome.status is StartLiveStatus.OBS_SWITCH_REQUIRED:
                self._view.apply_service_state(outcome.state)
                self._view.set_busy(False)
                if not await self._view.confirm_obs_switch():
                    self._view.set_status("已取消开播。")
                    return
                self._view.set_busy(True, "正在切换 OBS 并开始直播...", action=LiveAction.START)
                outcome = await service.start_live(
                    values.room_id,
                    values.title,
                    values.area_id,
                    values.obs,
                    allow_obs_switch=True,
                )
            self._view.apply_service_state(outcome.state)
            hud_error = await self._connect_hud_after_start(outcome, values.room_id)
            self._present_start_outcome(outcome, config_saved=config_saved, hud_error=hud_error)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to start live")
            self._view.set_status(f"开始直播失败: {exc}", error=True)
        finally:
            self._view.set_busy(False)

    async def _stop_live(self) -> None:
        service = self._service
        values = self._view.form_values()
        if service is None or values.room_id is None:
            self._view.set_status("房间号无效。", error=True)
            return
        self._view.set_busy(True, "正在停止直播...", action=LiveAction.STOP)
        try:
            config_saved = self._view.save_form_config()
            outcome = await service.stop_live(values.room_id, values.obs)
            self._view.apply_service_state(outcome.state)
            if outcome.status is StopLiveStatus.STOPPED:
                if config_saved:
                    self._view.set_status("直播已停止。", success=True)
                else:
                    self._view.set_status("直播已停止，但设置保存失败。", error=True)
            else:
                message = outcome.error.message if outcome.error is not None else "停止直播失败。"
                self._view.set_status(message, error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to stop live")
            self._view.set_status(f"停止直播失败: {exc}", error=True)
        finally:
            self._view.set_busy(False)

    async def _connect_hud_after_start(
        self,
        outcome: StartLiveOutcome,
        room_id: int,
    ) -> str | None:
        """Connect the HUD only after Bilibili has accepted the live start."""
        if self._on_live_started is None or outcome.status not in (
            StartLiveStatus.STARTED,
            StartLiveStatus.STARTED_WITHOUT_CREDENTIALS,
        ):
            return None
        try:
            await self._on_live_started(room_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Failed to connect HUD after live started")
            return str(exc).strip() or "连接失败"
        return None

    def _present_start_outcome(
        self,
        outcome: StartLiveOutcome,
        *,
        config_saved: bool,
        hud_error: str | None = None,
    ) -> None:
        """Render every start-live state without turning partial success into success."""
        persistence_notice = "" if config_saved else "设置保存失败，请检查权限后重试。"
        hud_notice = f"HUD 连接失败: {hud_error}" if hud_error else ""
        if outcome.status is StartLiveStatus.VERIFICATION_REQUIRED:
            self._view.show_verification(outcome.verification_url, outcome.verification_kind)
            message = (
                "本次开播需要完成人脸认证，完成后请重新点击开始直播。"
                if outcome.verification_kind is LiveVerificationKind.FACE
                else "本次开播需要扫码验证，完成后请重新点击开始直播。"
            )
            self._view.set_status(
                self._join_messages(outcome.notice, message, persistence_notice),
                error=True,
            )
            return

        if outcome.status is StartLiveStatus.STARTED_WITHOUT_CREDENTIALS:
            message = outcome.error.message if outcome.error is not None else "接口未返回可识别的推流凭证。"
            self._view.set_status(
                self._join_messages(outcome.notice, f"直播已开始，但{message}", hud_notice, persistence_notice),
                error=True,
            )
            return

        if outcome.status is StartLiveStatus.STARTED:
            if outcome.error is not None:
                message = f"直播已开始，但 {outcome.error.message}"
                self._view.set_status(
                    self._join_messages(outcome.notice, message, hud_notice, persistence_notice),
                    error=True,
                )
            else:
                message = "直播已开始，OBS 推流已启动。" if outcome.obs_started else "直播已开始。"
                if persistence_notice or hud_notice:
                    self._view.set_status(
                        self._join_messages(outcome.notice, message, hud_notice, persistence_notice),
                        error=True,
                    )
                else:
                    self._view.set_status(self._join_messages(outcome.notice, message), success=True)
            return

        message = outcome.error.message if outcome.error is not None else "开始直播失败。"
        self._view.set_status(self._join_messages(outcome.notice, message, persistence_notice), error=True)

    @staticmethod
    def _join_messages(*messages: str) -> str:
        """Join non-empty notices while keeping the status label readable."""
        return "\n".join(message for message in messages if message)

    async def _check_obs(self) -> None:
        service = self._service
        settings = self._view.form_values().obs
        if service is None or settings is None:
            self._view.set_status("OBS 端口无效。", error=True)
            return
        self._view.set_obs_busy(True)
        self._view.set_status("正在检查 OBS WebSocket...")
        try:
            outcome = await service.check_obs(settings)
            self._view.apply_service_state(service.state)
            self._view.set_obs_status(outcome)
            if outcome.connected:
                self._view.set_status("OBS 已启动并且 WebSocket 可连接。", success=True)
            elif outcome.launched:
                self._view.set_status("已启动 OBS，请等待加载完成后重新检查。", success=True)
            elif outcome.error is not None:
                self._view.set_status(outcome.error.message, error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to check OBS")
            self._view.set_status(f"检查 OBS 失败: {exc}", error=True)
        finally:
            self._view.set_obs_busy(False)

    async def _stop_obs(self) -> None:
        service = self._service
        settings = self._view.form_values().obs
        if service is None or settings is None:
            self._view.set_status("OBS 端口无效。", error=True)
            return
        self._view.set_obs_busy(True)
        try:
            outcome = await service.stop_obs_stream(settings)
            self._view.apply_service_state(service.state)
            if outcome.success:
                self._view.set_status("OBS 推流已停止。", success=True)
            elif outcome.error is not None:
                self._view.set_status(outcome.error.message, error=True)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.exception("Failed to stop OBS stream")
            self._view.set_status(f"停止 OBS 推流失败: {exc}", error=True)
        finally:
            self._view.set_obs_busy(False)


__all__ = (
    "LiveAction",
    "LiveSettingsForm",
    "LiveSettingsService",
    "LiveSettingsView",
    "LiveStartedHandler",
    "LiveSettingsWorkflow",
)
