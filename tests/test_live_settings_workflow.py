import asyncio
from collections.abc import Awaitable, Callable

from bilihud.app.lifecycle import TaskSupervisor
from bilihud.live.models import (
    LiveControlError,
    LiveControlErrorCode,
    LiveControlOperationResult,
    LiveControlState,
    LiveSessionInfo,
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
from bilihud.ui.settings.pages.live.workflow import LiveAction, LiveSettingsForm, LiveSettingsWorkflow


class FakeLiveService:
    def __init__(
        self,
        outcomes: list[StartLiveOutcome],
        *,
        stop_outcome: StopLiveOutcome | None = None,
    ) -> None:
        self.state = LiveControlState(
            session=LiveSessionInfo(status=SessionStatus.AUTHENTICATED),
        )
        self._outcomes = outcomes
        self._stop_outcome = stop_outcome if stop_outcome is not None else StopLiveOutcome(
            StopLiveStatus.STOPPED,
            self.state,
        )
        self.start_calls: list[bool] = []

    async def initialize(self, room_id: int | None) -> LiveControlOperationResult:
        del room_id
        raise AssertionError("not used in this test")

    async def load_room_info(self, room_id: int | None) -> LiveControlOperationResult:
        del room_id
        raise AssertionError("not used in this test")

    async def update_title(self, room_id: int | None, title: str) -> LiveControlOperationResult:
        del room_id, title
        raise AssertionError("not used in this test")

    async def update_area(self, room_id: int | None, area_id: str) -> LiveControlOperationResult:
        del room_id, area_id
        raise AssertionError("not used in this test")

    async def start_live(
        self,
        room_id: int | None,
        title: str,
        area_id: str,
        obs_settings: ObsSettings | None,
        *,
        allow_obs_switch: bool = False,
    ) -> StartLiveOutcome:
        del room_id, title, area_id, obs_settings
        self.start_calls.append(allow_obs_switch)
        return self._outcomes.pop(0)

    async def stop_live(self, room_id: int | None, obs_settings: ObsSettings | None) -> StopLiveOutcome:
        del room_id, obs_settings
        return self._stop_outcome

    async def check_obs(self, settings: ObsSettings | None) -> ObsCheckOutcome:
        del settings
        raise AssertionError("not used in this test")

    async def stop_obs_stream(self, settings: ObsSettings | None) -> ObsStreamOutcome:
        del settings
        raise AssertionError("not used in this test")

    async def shutdown(self) -> None:
        pass


class FakeLiveView:
    def __init__(self, *, confirm_switch: bool = True, save_success: bool = True) -> None:
        self._confirm_switch = confirm_switch
        self._save_success = save_success
        self.busy_actions: list[LiveAction | None] = []
        self.statuses: list[tuple[str, bool, bool]] = []
        self.warnings: list[tuple[str, str, str]] = []
        self.verifications: list[tuple[str, LiveVerificationKind]] = []
        self.confirmation_count = 0

    def form_values(self) -> LiveSettingsForm:
        return LiveSettingsForm(7450109, "测试直播", "1", "371", None)

    def apply_service_state(self, state: LiveControlState) -> None:
        del state
        pass

    def set_busy(
        self,
        busy: bool,
        message: str | None = None,
        *,
        action: LiveAction | None = None,
    ) -> None:
        del busy, message
        self.busy_actions.append(action)

    def set_status(self, message: str, *, error: bool = False, success: bool = False) -> None:
        self.statuses.append((message, error, success))

    def save_form_config(self) -> bool:
        return self._save_success

    def show_verification(self, url: str, kind: LiveVerificationKind) -> None:
        self.verifications.append((url, kind))

    def show_warning(self, title: str, message: str, details: str) -> None:
        self.warnings.append((title, message, details))

    async def confirm_obs_switch(self) -> bool:
        self.confirmation_count += 1
        return self._confirm_switch

    def set_obs_busy(self, busy: bool) -> None:
        del busy
        pass

    def set_obs_status(self, outcome: ObsCheckOutcome) -> None:
        del outcome
        pass

    def update_action_state(self) -> None:
        pass


def _started_outcome() -> StartLiveOutcome:
    return StartLiveOutcome(StartLiveStatus.STARTED, LiveControlState())


def _run_start_sync(
    service: FakeLiveService,
    view: FakeLiveView,
    *,
    on_live_started: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    """Run one public workflow command to completion in an isolated supervisor."""

    async def run() -> None:
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("live-settings-test")
        workflow = LiveSettingsWorkflow(service, scope, view, on_live_started=on_live_started)
        task = workflow.start_live()
        if task is None:
            raise AssertionError("start workflow was not scheduled")
        await task
        await workflow.shutdown()
        await supervisor.shutdown()

    asyncio.run(run())


def _run_stop_sync(service: FakeLiveService, view: FakeLiveView) -> None:
    """Run one public stop workflow to completion in an isolated supervisor."""

    async def run() -> None:
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("live-settings-test")
        workflow = LiveSettingsWorkflow(service, scope, view)
        task = workflow.stop_live()
        if task is None:
            raise AssertionError("stop workflow was not scheduled")
        await task
        await workflow.shutdown()
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_live_connects_hud_to_the_started_room() -> None:
    connected_rooms: list[int] = []

    async def connect_hud(room_id: int) -> None:
        connected_rooms.append(room_id)

    _run_start_sync(FakeLiveService([_started_outcome()]), FakeLiveView(), on_live_started=connect_hud)

    assert connected_rooms == [7450109]


def test_start_live_confirms_obs_switch_and_retries_with_explicit_permission() -> None:
    service = FakeLiveService(
        [
            StartLiveOutcome(
                StartLiveStatus.OBS_SWITCH_REQUIRED,
                LiveControlState(),
                LiveControlError(LiveControlErrorCode.OBS_SWITCH_REQUIRED, "OBS 正在推流"),
            ),
            _started_outcome(),
        ]
    )
    view = FakeLiveView()

    _run_start_sync(service, view)

    assert service.start_calls == [False, True]
    assert view.confirmation_count == 1
    assert view.statuses[-1] == ("直播已开始。", False, True)


def test_start_live_does_not_report_missing_credentials_as_full_success() -> None:
    outcome = StartLiveOutcome(
        StartLiveStatus.STARTED_WITHOUT_CREDENTIALS,
        LiveControlState(),
        LiveControlError(LiveControlErrorCode.CREDENTIALS_MISSING, "未返回推流凭证"),
    )
    service = FakeLiveService([outcome])
    view = FakeLiveView(save_success=False)

    _run_start_sync(service, view)

    message, error, success = view.statuses[-1]
    assert "直播已开始" in message
    assert "设置保存失败" in message
    assert error is True
    assert success is False


def test_start_live_surfaces_obs_failure_in_a_warning_dialog() -> None:
    outcome = StartLiveOutcome(
        StartLiveStatus.STARTED,
        LiveControlState(),
        LiveControlError(LiveControlErrorCode.OBS_FAILURE, "OBS WebSocket 连接失败"),
    )
    view = FakeLiveView()

    _run_start_sync(FakeLiveService([outcome]), view)

    assert view.warnings == [
        (
            "OBS 推流未启动",
            "Bilibili 直播已开始，但 OBS 推流未成功启动。",
            "OBS WebSocket 连接失败\n\n请检查 OBS 是否已启动以及 WebSocket 配置。",
        )
    ]


def test_stop_live_surfaces_unconfirmed_obs_state_in_a_warning_dialog() -> None:
    outcome = StopLiveOutcome(
        StopLiveStatus.STOPPED_WITH_OBS_FAILURE,
        LiveControlState(),
        LiveControlError(LiveControlErrorCode.OBS_FAILURE, "OBS 推流未能自动确认"),
    )
    view = FakeLiveView()

    _run_stop_sync(FakeLiveService([], stop_outcome=outcome), view)

    assert view.warnings == [
        (
            "OBS 推流状态未确认",
            "Bilibili 直播已停止，但 OBS 推流未能自动确认。",
            "请打开 OBS 手动确认推流状态。",
        )
    ]


def test_start_live_presents_face_auth_and_requires_retry_after_verification() -> None:
    outcome = StartLiveOutcome(
        StartLiveStatus.VERIFICATION_REQUIRED,
        LiveControlState(),
        LiveControlError(LiveControlErrorCode.VERIFICATION_REQUIRED, "需要人脸认证"),
        verification_url="https://verify.example/face",
        verification_kind=LiveVerificationKind.FACE,
    )
    service = FakeLiveService([outcome])
    view = FakeLiveView()

    _run_start_sync(service, view)

    assert view.verifications == [("https://verify.example/face", LiveVerificationKind.FACE)]
    assert "人脸认证" in view.statuses[-1][0]
    assert "重新点击开始直播" in view.statuses[-1][0]
    assert view.statuses[-1][1] is True
