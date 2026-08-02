import asyncio
from collections.abc import Coroutine
from io import BytesIO
from typing import Any

from bilihud.config import AppConfig
from bilihud.domain.live_control import (
    LiveArea,
    LiveAreaGroup,
    LiveControlErrorCode,
    LiveSessionInfo,
    LiveStartResponse,
    LiveVersion,
    ObsSettings,
    RoomInfo,
    SessionStatus,
    StartLiveStatus,
    StreamCredential,
)
from bilihud.live_control_service import LiveControlService


class FakeLiveApi:
    def __init__(
        self,
        *,
        session: LiveSessionInfo | None = None,
        room_info: RoomInfo | None = None,
        start_response: LiveStartResponse | None = None,
    ) -> None:
        self.session = session if session is not None else LiveSessionInfo(SessionStatus.AUTHENTICATED)
        self.room_info = room_info if room_info is not None else RoomInfo(7450109, "旧标题", "9", "371")
        self.start_response = start_response if start_response is not None else LiveStartResponse(0, "ok")
        self.start_calls = 0
        self.updated_titles: list[str] = []
        self.updated_areas: list[str] = []
        self.version_started: asyncio.Event | None = None
        self.version_release: asyncio.Event | None = None
        self.closed = False

    async def open_session(self) -> LiveSessionInfo:
        return self.session

    async def close_session(self) -> None:
        self.closed = True

    async def load_area_groups(self) -> tuple[LiveAreaGroup, ...]:
        return (LiveAreaGroup("9", "游戏", (LiveArea("371", "主机游戏"),)),)

    async def get_room_info(self, room_id: int) -> RoomInfo:
        return self.room_info

    async def update_room_title(self, room_id: int, title: str) -> None:
        self.updated_titles.append(title)

    async def update_room_area(self, room_id: int, area_id: str) -> None:
        self.updated_areas.append(area_id)

    async def get_live_version(self) -> LiveVersion:
        if self.version_started is not None:
            self.version_started.set()
        if self.version_release is not None:
            await self.version_release.wait()
        return LiveVersion("1.0", 1)

    async def start_live(self, room_id: int, area_id: str, version: LiveVersion) -> LiveStartResponse:
        self.start_calls += 1
        return self.start_response

    async def stop_live(self, room_id: int) -> None:
        return None


class FakeObs:
    def __init__(self, streaming: bool = False) -> None:
        self.streaming = streaming
        self.start_calls: list[StreamCredential] = []
        self.stop_calls = 0

    async def check_connection(self, settings: ObsSettings) -> None:
        return None

    async def is_streaming(self, settings: ObsSettings) -> bool:
        return self.streaming

    async def stop_stream(self, settings: ObsSettings) -> None:
        self.stop_calls += 1
        self.streaming = False

    async def set_stream_service_settings_and_start(
        self,
        settings: ObsSettings,
        credential: StreamCredential,
    ) -> None:
        self.start_calls.append(credential)
        self.streaming = True

    def is_process_running(self) -> bool:
        return False

    def launch(self) -> None:
        return None


class FakeConfigStore:
    def __init__(self) -> None:
        self.config = AppConfig()

    def load(self) -> AppConfig:
        return self.config

    def save(self, config: AppConfig) -> bool:
        self.config = config
        return True


class FakeSecrets:
    def __init__(self) -> None:
        self.password: str | None = None

    def load_obs_password(self) -> str | None:
        return self.password

    def save_obs_password(self, password: str) -> bool:
        self.password = password
        return True

    def clear_obs_password(self) -> None:
        self.password = None

    def generate_qr_image(self, url: str) -> BytesIO | None:
        return None


def make_service(api: FakeLiveApi, obs: FakeObs) -> LiveControlService:
    return LiveControlService(
        api=api,
        obs=obs,
        config_store=FakeConfigStore(),
        secrets=FakeSecrets(),
    )


def run(coroutine: Coroutine[Any, Any, object]) -> object:
    return asyncio.run(coroutine)


def test_start_live_syncs_room_starts_obs_and_returns_credentials_without_qt() -> None:
    credential = StreamCredential("rtmp-1", "rtmp://server", "key")
    api = FakeLiveApi(start_response=LiveStartResponse(0, "ok", (credential,)))
    obs = FakeObs()
    service = make_service(api, obs)

    async def scenario() -> None:
        await service.initialize(7450109)
        outcome = await service.start_live(
            7450109,
            "新标题",
            "372",
            ObsSettings("127.0.0.1", 4455, ""),
        )

        assert outcome.status is StartLiveStatus.STARTED
        assert outcome.success
        assert outcome.obs_started

    run(scenario())
    assert api.updated_titles == ["新标题"]
    assert api.updated_areas == ["372"]
    assert api.start_calls == 1
    assert obs.start_calls == [credential]
    assert service.state.room_info is not None
    assert service.state.room_info.is_live


def test_start_live_reports_missing_credentials_after_bilibili_accepts_request() -> None:
    api = FakeLiveApi(start_response=LiveStartResponse(0, "ok", ()))
    service = make_service(api, FakeObs())

    async def scenario() -> None:
        await service.initialize(7450109)
        outcome = await service.start_live(7450109, "标题", "371", None)

        assert outcome.status is StartLiveStatus.STARTED_WITHOUT_CREDENTIALS
        assert outcome.success
        assert outcome.error is not None
        assert outcome.error.code is LiveControlErrorCode.CREDENTIALS_MISSING

    run(scenario())
    assert api.start_calls == 1


def test_expired_saved_login_blocks_start_before_api_mutation() -> None:
    api = FakeLiveApi(
        session=LiveSessionInfo(SessionStatus.ANONYMOUS, from_saved_session=True),
    )
    service = make_service(api, FakeObs())

    async def scenario() -> None:
        await service.initialize(7450109)
        outcome = await service.start_live(7450109, "标题", "371", None)

        assert outcome.error is not None
        assert outcome.error.code is LiveControlErrorCode.LOGIN_EXPIRED

    run(scenario())
    assert api.start_calls == 0


def test_duplicate_start_returns_operation_in_progress_without_second_api_call() -> None:
    api = FakeLiveApi()
    api.version_started = asyncio.Event()
    api.version_release = asyncio.Event()
    service = make_service(api, FakeObs())

    async def scenario() -> None:
        await service.initialize(7450109)
        first = asyncio.create_task(service.start_live(7450109, "标题", "371", None))
        assert api.version_started is not None
        await api.version_started.wait()

        second = await service.start_live(7450109, "标题", "371", None)

        assert second.error is not None
        assert second.error.code is LiveControlErrorCode.OPERATION_IN_PROGRESS
        assert api.version_release is not None
        api.version_release.set()
        await first

    run(scenario())
    assert api.start_calls == 1
