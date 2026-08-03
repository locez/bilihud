"""Application orchestration for Bilibili live-room and OBS controls."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from io import BytesIO

from ..config.store import ConfigStore
from ..live.models import (
    LiveControlError,
    LiveControlErrorCode,
    LiveControlOperationResult,
    LiveControlSettings,
    LiveControlState,
    LiveSessionInfo,
    ObsCheckOutcome,
    ObsSettings,
    ObsStreamOutcome,
    RoomInfo,
    SessionStatus,
    SettingsSaveOutcome,
    StartLiveOutcome,
    StartLiveStatus,
    StopLiveOutcome,
    StopLiveStatus,
    obs_cleanup_after_stop_state,
    pick_primary_credential,
    room_area_needs_update,
    room_title_needs_update,
    start_live_confirmation_needed,
)
from ..live.validation import validate_room_id
from .live_control_ports import (
    LiveControlApi,
    LiveControlApiError,
    LiveControlSecrets,
    ObsAdapter,
    ObsAdapterError,
)

logger = logging.getLogger(__name__)


class LiveControlService:
    """Own live-control session lifecycle and coordinate typed external ports."""

    def __init__(
        self,
        *,
        api: LiveControlApi,
        obs: ObsAdapter,
        config_store: ConfigStore,
        secrets: LiveControlSecrets,
    ) -> None:
        """Create a service whose network, OBS, and secret ownership is explicit."""
        self._api = api
        self._obs = obs
        self._config_store = config_store
        self._secrets = secrets
        self._state = LiveControlState()
        self._generation = 0
        self._operation_gate = asyncio.Lock()
        self._active_operation: str | None = None
        self._operation_finished = asyncio.Event()
        self._operation_finished.set()
        self._close_gate = asyncio.Lock()
        self._close_finished = asyncio.Event()
        self._close_finished.set()
        self._closing = False
        self._shutting_down = False
        self._shutdown_complete = False

    @property
    def state(self) -> LiveControlState:
        """Return the latest immutable state snapshot for presentation binding."""
        return self._state

    def load_settings(self) -> LiveControlSettings:
        """Load typed form defaults and the OBS password through their boundaries."""
        config = self._config_store.load()
        password = self._secrets.load_obs_password()
        return LiveControlSettings(
            room_id=config.room_id,
            live_title=config.live_title,
            live_parent_area_id=config.live_parent_area_id,
            live_area_id=config.live_area_id,
            obs_host=config.obs_host,
            obs_port=config.obs_port,
            obs_password=password if password is not None else "",
        )

    def save_settings(self, settings: LiveControlSettings) -> SettingsSaveOutcome:
        """Persist form settings and the OBS password, reporting partial failures."""
        current = self._config_store.load()
        config = replace(
            current,
            room_id=settings.room_id,
            live_title=settings.live_title,
            live_parent_area_id=settings.live_parent_area_id,
            live_area_id=settings.live_area_id,
            obs_host=settings.obs_host,
            obs_port=settings.obs_port,
        )
        config_saved = self._config_store.save(config)
        if settings.obs_password:
            secret_saved = self._secrets.save_obs_password(settings.obs_password)
        else:
            self._secrets.clear_obs_password()
            secret_saved = True
        if config_saved and secret_saved:
            return SettingsSaveOutcome(success=True)
        return SettingsSaveOutcome(
            success=False,
            error=LiveControlError(
                LiveControlErrorCode.PERSISTENCE_FAILURE,
                "直播控制设置保存失败。",
            ),
        )

    def generate_qr_image(self, url: str) -> BytesIO | None:
        """Generate verification QR bytes through the injected secret boundary."""
        return self._secrets.generate_qr_image(url)

    async def initialize(self, room_id: int | None) -> LiveControlOperationResult:
        """Open the session, load areas, and optionally load the selected room."""
        operation_error = await self._claim_operation("initialize")
        if operation_error is not None:
            return LiveControlOperationResult(self._state, operation_error)

        generation = self._begin_generation()
        try:
            session_info = await self._api.open_session()
            if not self._is_current(generation):
                return LiveControlOperationResult(self._state)
            self._state = replace(
                self._state,
                session=session_info,
                areas=(),
                room_info=None,
                credentials=(),
                obs_connected=False,
                obs_streaming=None,
            )

            areas = await self._api.load_area_groups()
            if not self._is_current(generation):
                return LiveControlOperationResult(self._state)
            self._state = replace(self._state, areas=areas)

            if room_id is not None and not validate_room_id(room_id):
                return LiveControlOperationResult(
                    self._state,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            if room_id is not None:
                result = await self._load_room_info(generation, room_id)
                if result.error is not None:
                    return result
            return LiveControlOperationResult(self._state)
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            return LiveControlOperationResult(self._state, self._api_error(exc))
        finally:
            await self._release_operation("initialize")

    async def load_room_info(self, room_id: int | None) -> LiveControlOperationResult:
        """Load room metadata while invalidating stale concurrent loads."""
        operation_error = await self._claim_operation("load-room-info")
        if operation_error is not None:
            return LiveControlOperationResult(self._state, operation_error)

        generation = self._begin_generation()
        try:
            if room_id is None or not validate_room_id(room_id):
                self._state = replace(self._state, room_info=None, credentials=())
                return LiveControlOperationResult(
                    self._state,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            return await self._load_room_info(generation, room_id)
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            self._state = replace(self._state, room_info=None, credentials=())
            return LiveControlOperationResult(self._state, self._api_error(exc))
        finally:
            await self._release_operation("load-room-info")

    async def update_title(self, room_id: int | None, title: str) -> LiveControlOperationResult:
        """Update a room title and reflect it in the service state."""
        operation_error = await self._claim_operation("update-title")
        if operation_error is not None:
            return LiveControlOperationResult(self._state, operation_error)

        generation = self._begin_generation()
        try:
            validation_error = self._validate_authenticated_room(room_id, title=title)
            if validation_error is not None:
                return LiveControlOperationResult(self._state, validation_error)
            if room_id is None:
                return LiveControlOperationResult(
                    self._state,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            await self._api.update_room_title(room_id, title.strip())
            if not self._is_current(generation):
                return LiveControlOperationResult(self._state)
            current = self._state.room_info
            self._state = replace(
                self._state,
                room_info=RoomInfo(
                    room_id=room_id,
                    title=title.strip(),
                    parent_area_id=current.parent_area_id if current and current.room_id == room_id else "",
                    area_id=current.area_id if current and current.room_id == room_id else "",
                    is_live=current.is_live if current and current.room_id == room_id else False,
                ),
            )
            return LiveControlOperationResult(self._state)
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            return LiveControlOperationResult(self._state, self._api_error(exc))
        finally:
            await self._release_operation("update-title")

    async def update_area(self, room_id: int | None, area_id: str) -> LiveControlOperationResult:
        """Update a room area and reflect it in the service state."""
        operation_error = await self._claim_operation("update-area")
        if operation_error is not None:
            return LiveControlOperationResult(self._state, operation_error)

        generation = self._begin_generation()
        try:
            validation_error = self._validate_authenticated_room(room_id, area_id=area_id)
            if validation_error is not None:
                return LiveControlOperationResult(self._state, validation_error)
            if room_id is None:
                return LiveControlOperationResult(
                    self._state,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            await self._api.update_room_area(room_id, area_id)
            if not self._is_current(generation):
                return LiveControlOperationResult(self._state)
            current = self._state.room_info
            self._state = replace(
                self._state,
                room_info=RoomInfo(
                    room_id=room_id,
                    title=current.title if current and current.room_id == room_id else "",
                    parent_area_id=self._parent_area_for(area_id),
                    area_id=area_id,
                    is_live=current.is_live if current and current.room_id == room_id else False,
                ),
            )
            return LiveControlOperationResult(self._state)
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            return LiveControlOperationResult(self._state, self._api_error(exc))
        finally:
            await self._release_operation("update-area")

    async def start_live(
        self,
        room_id: int | None,
        title: str,
        area_id: str,
        obs_settings: ObsSettings | None,
        *,
        allow_obs_switch: bool = False,
    ) -> StartLiveOutcome:
        """Run the complete start-live workflow without touching HUD ownership."""
        operation_error = await self._claim_operation("start-live")
        if operation_error is not None:
            return self._start_failure(StartLiveStatus.FAILED, operation_error)

        generation = self._begin_generation()
        try:
            validation_error = self._validate_authenticated_room(room_id, title=title, area_id=area_id)
            if validation_error is not None:
                return self._start_failure(StartLiveStatus.FAILED, validation_error)
            if room_id is None:
                return self._start_failure(
                    StartLiveStatus.FAILED,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            current = self._state.room_info
            if current is not None and current.room_id == room_id and current.is_live:
                error = LiveControlError(LiveControlErrorCode.ALREADY_LIVE, "当前直播间已经在直播。")
                return self._start_failure(StartLiveStatus.ALREADY_LIVE, error)

            obs_streaming = await self._read_obs_state(obs_settings, generation)
            if not self._is_current(generation):
                return self._stale_start_result()
            if start_live_confirmation_needed(obs_streaming):
                if not allow_obs_switch:
                    error = LiveControlError(
                        LiveControlErrorCode.OBS_SWITCH_REQUIRED,
                        "OBS 当前正在推流，需要确认后才能切换。",
                    )
                    return StartLiveOutcome(
                        StartLiveStatus.OBS_SWITCH_REQUIRED,
                        self._state,
                        error=error,
                    )
                if obs_settings is not None:
                    try:
                        await self._obs.stop_stream(obs_settings)
                    except ObsAdapterError as exc:
                        return self._start_failure(
                            StartLiveStatus.FAILED,
                            LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"停止 OBS 推流失败: {exc}"),
                        )

            notice = await self._sync_room_before_start(room_id, title, area_id, generation)
            if not self._is_current(generation):
                return self._stale_start_result()
            version = await self._api.get_live_version()
            if not self._is_current(generation):
                return self._stale_start_result()
            response = await self._api.start_live(room_id, area_id, version)
            if not self._is_current(generation):
                return self._stale_start_result()
            if response.code == 60024 or response.code == 60043:
                error = LiveControlError(
                    LiveControlErrorCode.VERIFICATION_REQUIRED,
                    response.message or "本次开播需要验证。",
                )
                return StartLiveOutcome(
                    StartLiveStatus.VERIFICATION_REQUIRED,
                    self._state,
                    error=error,
                    verification_url=response.verification_url,
                    notice=notice,
                )
            if response.code != 0:
                return self._start_failure(
                    StartLiveStatus.FAILED,
                    LiveControlError(
                        LiveControlErrorCode.API_FAILURE,
                        f"开始直播失败: {response.message or 'Unknown Error'} ({response.code})",
                    ),
                )

            self._state = replace(
                self._state,
                room_info=RoomInfo(
                    room_id=room_id,
                    title=title.strip(),
                    parent_area_id=self._parent_area_for(area_id),
                    area_id=area_id,
                    is_live=True,
                ),
                credentials=response.credentials,
            )
            credentials_error: LiveControlError | None = None
            if not response.credentials:
                credentials_error = LiveControlError(
                    LiveControlErrorCode.CREDENTIALS_MISSING,
                    "直播已开始，但接口未返回可识别的推流凭证。",
                )

            obs_started = False
            obs_error: LiveControlError | None = None
            primary = pick_primary_credential(response.credentials)
            if primary is not None and obs_settings is not None and obs_settings.is_valid:
                try:
                    await self._obs.set_stream_service_settings_and_start(obs_settings, primary)
                except ObsAdapterError as exc:
                    obs_error = LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"启动 OBS 推流失败: {exc}")
                    self._state = replace(self._state, obs_connected=False, obs_streaming=None)
                else:
                    obs_started = True
                    self._state = replace(self._state, obs_connected=True, obs_streaming=True)

            error = credentials_error if credentials_error is not None else obs_error
            status = (
                StartLiveStatus.STARTED_WITHOUT_CREDENTIALS
                if credentials_error is not None
                else StartLiveStatus.STARTED
            )
            return StartLiveOutcome(
                status,
                self._state,
                error=error,
                obs_started=obs_started,
                notice=notice,
            )
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            return self._start_failure(StartLiveStatus.FAILED, self._api_error(exc))
        finally:
            await self._release_operation("start-live")

    async def stop_live(self, room_id: int | None, obs_settings: ObsSettings | None) -> StopLiveOutcome:
        """Stop Bilibili live and best-effort clean up a known OBS stream."""
        operation_error = await self._claim_operation("stop-live")
        if operation_error is not None:
            return StopLiveOutcome(StopLiveStatus.FAILED, self._state, operation_error)

        generation = self._begin_generation()
        try:
            validation_error = self._validate_authenticated_room(room_id)
            if validation_error is not None:
                return StopLiveOutcome(StopLiveStatus.FAILED, self._state, validation_error)
            if room_id is None:
                return StopLiveOutcome(
                    StopLiveStatus.FAILED,
                    self._state,
                    LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。"),
                )
            current = self._state.room_info
            if current is not None and current.room_id == room_id and not current.is_live:
                return StopLiveOutcome(
                    StopLiveStatus.NOT_LIVE,
                    self._state,
                    LiveControlError(LiveControlErrorCode.NOT_LIVE, "当前直播间没有在直播。"),
                )
            await self._api.stop_live(room_id)
            if not self._is_current(generation):
                return StopLiveOutcome(StopLiveStatus.STOPPED, self._state)

            self._state = replace(
                self._state,
                room_info=(
                    replace(current, is_live=False)
                    if current is not None and current.room_id == room_id
                    else current
                ),
                credentials=(),
            )
            obs_streaming = await self._read_obs_state(obs_settings, generation)
            should_stop_obs, obs_state = obs_cleanup_after_stop_state(obs_streaming)
            if not should_stop_obs or obs_settings is None:
                if obs_state == "unknown":
                    error = LiveControlError(
                        LiveControlErrorCode.OBS_FAILURE,
                        "直播已停止；OBS 推流未能自动确认，请在 OBS 中手动确认。",
                    )
                    return StopLiveOutcome(
                        StopLiveStatus.STOPPED_WITH_OBS_FAILURE,
                        self._state,
                        error=error,
                        obs_was_streaming=obs_streaming,
                    )
                return StopLiveOutcome(StopLiveStatus.STOPPED, self._state, obs_was_streaming=obs_streaming)

            try:
                await self._obs.stop_stream(obs_settings)
            except ObsAdapterError as exc:
                error = LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"停止 OBS 推流失败: {exc}")
                return StopLiveOutcome(
                    StopLiveStatus.STOPPED_WITH_OBS_FAILURE,
                    self._state,
                    error=error,
                    obs_was_streaming=obs_streaming,
                )
            self._state = replace(self._state, obs_streaming=False, obs_connected=True)
            return StopLiveOutcome(
                StopLiveStatus.STOPPED,
                self._state,
                obs_was_streaming=obs_streaming,
                obs_stopped=True,
            )
        except asyncio.CancelledError:
            raise
        except LiveControlApiError as exc:
            return StopLiveOutcome(StopLiveStatus.FAILED, self._state, self._api_error(exc))
        finally:
            await self._release_operation("stop-live")

    async def check_obs(self, settings: ObsSettings | None) -> ObsCheckOutcome:
        """Check OBS and launch it when absent, without exposing process APIs to UI."""
        if settings is None or not settings.is_valid:
            return ObsCheckOutcome(
                connected=False,
                process_running=False,
                error=LiveControlError(LiveControlErrorCode.INVALID_INPUT, "OBS 设置无效。"),
            )
        operation_error = await self._claim_operation("check-obs")
        if operation_error is not None:
            return ObsCheckOutcome(False, False, error=operation_error)
        try:
            try:
                await self._obs.check_connection(settings)
            except ObsAdapterError as exc:
                self._state = replace(self._state, obs_connected=False, obs_streaming=None)
                try:
                    running = self._obs.is_process_running()
                except ObsAdapterError as process_exc:
                    return ObsCheckOutcome(
                        False,
                        False,
                        error=LiveControlError(LiveControlErrorCode.OBS_FAILURE, str(process_exc)),
                    )
                if running:
                    return ObsCheckOutcome(
                        False,
                        True,
                        error=LiveControlError(
                            LiveControlErrorCode.OBS_FAILURE,
                            f"OBS 已启动，但 WebSocket 无法连接: {exc}",
                        ),
                    )
                try:
                    self._obs.launch()
                except ObsAdapterError as launch_exc:
                    return ObsCheckOutcome(
                        False,
                        False,
                        error=LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"启动 OBS 失败: {launch_exc}"),
                    )
                return ObsCheckOutcome(False, True, launched=True)
            else:
                self._state = replace(self._state, obs_connected=True)
                return ObsCheckOutcome(True, True)
        finally:
            await self._release_operation("check-obs")

    async def start_obs_stream(self, settings: ObsSettings | None) -> ObsStreamOutcome:
        """Start OBS with the currently stored primary stream credential."""
        if settings is None or not settings.is_valid:
            return ObsStreamOutcome(
                False,
                LiveControlError(LiveControlErrorCode.INVALID_INPUT, "OBS 设置无效。"),
            )
        credential = pick_primary_credential(self._state.credentials)
        if credential is None:
            return ObsStreamOutcome(
                False,
                LiveControlError(LiveControlErrorCode.CREDENTIALS_MISSING, "没有可用于启动 OBS 推流的凭证。"),
            )
        operation_error = await self._claim_operation("start-obs")
        if operation_error is not None:
            return ObsStreamOutcome(False, operation_error)
        try:
            await self._obs.set_stream_service_settings_and_start(settings, credential)
            self._state = replace(self._state, obs_connected=True, obs_streaming=True)
            return ObsStreamOutcome(True)
        except asyncio.CancelledError:
            raise
        except ObsAdapterError as exc:
            self._state = replace(self._state, obs_connected=False, obs_streaming=None)
            return ObsStreamOutcome(
                False,
                LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"启动 OBS 推流失败: {exc}"),
            )
        finally:
            await self._release_operation("start-obs")

    async def stop_obs_stream(self, settings: ObsSettings | None) -> ObsStreamOutcome:
        """Stop OBS through the injected adapter and report its result."""
        if settings is None or not settings.is_valid:
            return ObsStreamOutcome(
                False,
                LiveControlError(LiveControlErrorCode.INVALID_INPUT, "OBS 设置无效。"),
            )
        operation_error = await self._claim_operation("stop-obs")
        if operation_error is not None:
            return ObsStreamOutcome(False, operation_error)
        try:
            await self._obs.stop_stream(settings)
            self._state = replace(self._state, obs_connected=True, obs_streaming=False)
            return ObsStreamOutcome(True)
        except asyncio.CancelledError:
            raise
        except ObsAdapterError as exc:
            return ObsStreamOutcome(
                False,
                LiveControlError(LiveControlErrorCode.OBS_FAILURE, f"停止 OBS 推流失败: {exc}"),
            )
        finally:
            await self._release_operation("stop-obs")

    async def close(self) -> None:
        """Invalidate in-flight work and close the service-owned API session."""
        async with self._close_gate:
            self._begin_generation()
            self._closing = True
            self._close_finished.clear()
            try:
                await self._operation_finished.wait()
                await self._api.close_session()
                self._state = replace(
                    self._state,
                    session=LiveSessionInfo(),
                    room_info=None,
                    credentials=(),
                    obs_connected=False,
                    obs_streaming=None,
                )
            finally:
                self._closing = False
                self._close_finished.set()

    async def shutdown(self) -> None:
        """Close the service permanently and make repeated shutdown calls harmless."""
        if self._shutdown_complete:
            return
        self._shutting_down = True
        await self.close()
        self._shutdown_complete = True

    async def _load_room_info(self, generation: int, room_id: int) -> LiveControlOperationResult:
        """Load a room for an already claimed operation and guard stale responses."""
        try:
            room_info = await self._api.get_room_info(room_id)
        except LiveControlApiError as exc:
            self._state = replace(self._state, room_info=None, credentials=())
            return LiveControlOperationResult(self._state, self._api_error(exc))
        if not self._is_current(generation):
            return LiveControlOperationResult(
                self._state,
                LiveControlError(LiveControlErrorCode.STALE, "直播间信息已过期。"),
            )
        self._state = replace(self._state, room_info=room_info, credentials=())
        return LiveControlOperationResult(self._state)

    async def _sync_room_before_start(
        self,
        room_id: int,
        title: str,
        area_id: str,
        generation: int,
    ) -> str:
        """Synchronize changed room fields while preserving the rate-limit behavior."""
        notice = ""
        current = self._state.room_info
        if room_title_needs_update(current, room_id, title):
            try:
                await self._api.update_room_title(room_id, title.strip())
            except LiveControlApiError as exc:
                if not _is_rate_limited(exc):
                    raise
                logger.info("Room title update skipped because Bilibili rate limited it: %s", exc)
                notice = "直播间信息刚更新过，已跳过重复同步并继续开播..."
            if self._is_current(generation) and not notice:
                current = self._state.room_info
                self._state = replace(
                    self._state,
                    room_info=RoomInfo(
                        room_id=room_id,
                        title=title.strip(),
                        parent_area_id=current.parent_area_id if current and current.room_id == room_id else "",
                        area_id=current.area_id if current and current.room_id == room_id else "",
                        is_live=current.is_live if current and current.room_id == room_id else False,
                    ),
                )

        current = self._state.room_info
        if room_area_needs_update(current, room_id, area_id):
            try:
                await self._api.update_room_area(room_id, area_id)
            except LiveControlApiError as exc:
                if not _is_rate_limited(exc):
                    raise
                logger.info("Room area update skipped because Bilibili rate limited it: %s", exc)
                notice = "直播间信息刚更新过，已跳过重复同步并继续开播..."
            if self._is_current(generation) and not notice:
                current = self._state.room_info
                self._state = replace(
                    self._state,
                    room_info=RoomInfo(
                        room_id=room_id,
                        title=current.title if current and current.room_id == room_id else title.strip(),
                        parent_area_id=self._parent_area_for(area_id),
                        area_id=area_id,
                        is_live=current.is_live if current and current.room_id == room_id else False,
                    ),
                )
        return notice

    async def _read_obs_state(self, settings: ObsSettings | None, generation: int) -> bool | None:
        """Read OBS state without turning an unavailable optional integration into API failure."""
        if settings is None or not settings.is_valid:
            return None
        try:
            streaming = await self._obs.is_streaming(settings)
        except ObsAdapterError as exc:
            logger.info("Failed to query OBS stream status: %s", exc)
            if self._is_current(generation):
                self._state = replace(self._state, obs_connected=False, obs_streaming=None)
            return None
        if self._is_current(generation):
            self._state = replace(self._state, obs_connected=True, obs_streaming=streaming)
        return streaming

    def _validate_authenticated_room(
        self,
        room_id: int | None,
        *,
        title: str | None = None,
        area_id: str | None = None,
    ) -> LiveControlError | None:
        """Validate common room inputs and turn missing login into an explicit result."""
        if room_id is None or not validate_room_id(room_id):
            return LiveControlError(LiveControlErrorCode.INVALID_ROOM, "房间号无效。")
        if title is not None and not title.strip():
            return LiveControlError(LiveControlErrorCode.INVALID_INPUT, "直播标题不能为空。")
        if area_id is not None and not area_id.strip():
            return LiveControlError(LiveControlErrorCode.INVALID_INPUT, "直播分区不能为空。")
        if self._state.session.status is SessionStatus.AUTHENTICATED:
            return None
        code = (
            LiveControlErrorCode.LOGIN_EXPIRED
            if self._state.session.from_saved_session
            else LiveControlErrorCode.AUTHENTICATION_REQUIRED
        )
        message = (
            "保存的登录状态已过期，请先重新扫码登录。"
            if code is LiveControlErrorCode.LOGIN_EXPIRED
            else "请先通过托盘菜单扫码登录。"
        )
        return LiveControlError(code, message)

    def _parent_area_for(self, area_id: str) -> str:
        """Find the normalized parent ID for a selected sub-area."""
        for group in self._state.areas:
            for area in group.areas:
                if area.area_id == area_id:
                    return group.parent_area_id
        return ""

    def _api_error(self, exc: LiveControlApiError) -> LiveControlError:
        """Convert an infrastructure API error into the application error contract."""
        return LiveControlError(LiveControlErrorCode.API_FAILURE, str(exc))

    def _start_failure(self, status: StartLiveStatus, error: LiveControlError) -> StartLiveOutcome:
        """Build a failed start result using the current immutable state."""
        return StartLiveOutcome(status, self._state, error=error)

    def _stale_start_result(self) -> StartLiveOutcome:
        """Build a result for a start request invalidated by close or a newer operation."""
        return self._start_failure(
            StartLiveStatus.FAILED,
            LiveControlError(LiveControlErrorCode.STALE, "开始直播操作已过期。"),
        )

    def _begin_generation(self) -> int:
        """Invalidate callbacks from all previous workflows and return the new token."""
        self._generation += 1
        return self._generation

    def _is_current(self, generation: int) -> bool:
        """Return whether a workflow still owns the current generation."""
        return generation == self._generation and not self._shutting_down

    async def _claim_operation(self, name: str) -> LiveControlError | None:
        """Claim one operation slot so duplicate requests return a typed result."""
        while True:
            async with self._operation_gate:
                if self._shutting_down or self._shutdown_complete:
                    return LiveControlError(LiveControlErrorCode.CLOSED, "直播控制服务已关闭。")
                if self._closing:
                    close_finished = self._close_finished
                else:
                    if self._active_operation is not None:
                        return LiveControlError(
                            LiveControlErrorCode.OPERATION_IN_PROGRESS,
                            "已有直播控制操作正在进行，请稍候。",
                        )
                    self._active_operation = name
                    self._operation_finished.clear()
                    return None
            await close_finished.wait()

    async def _release_operation(self, name: str) -> None:
        """Release the operation slot only when it is still owned by this workflow."""
        async with self._operation_gate:
            if self._active_operation == name:
                self._active_operation = None
                self._operation_finished.set()


def _is_rate_limited(exc: LiveControlApiError) -> bool:
    """Recognize Bilibili's duplicate room-update response at the adapter boundary."""
    return exc.code == -1 and "操作太频繁" in str(exc)


__all__ = ("LiveControlService",)
