import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .app.lifecycle import TaskScope, TaskSupervisor, cancel_task
from .app.live_control_service import LiveControlService
from .app.services import AppServices, create_default_services
from .live.models import (
    LiveAreaGroup,
    LiveControlErrorCode,
    LiveControlSettings,
    LiveControlState,
    ObsSettings,
    RoomInfo,
    SessionStatus,
    StartLiveOutcome,
    StartLiveStatus,
    StopLiveStatus,
    StreamCredential,
    obs_check_button_state,
    room_action_enabled_state,
)
from .live.models import (
    obs_cleanup_after_stop_state as _obs_cleanup_after_stop_state,
)
from .live.models import (
    start_live_confirmation_needed as _start_live_confirmation_needed,
)
from .live.validation import validate_room_id

logger = logging.getLogger(__name__)


# TODO: remove these compatibility exports after callers import the service helpers directly.
def start_live_confirmation_needed(obs_streaming: bool | None) -> bool:
    """Keep the historical pure helper available to existing callers."""
    return _start_live_confirmation_needed(obs_streaming)


def obs_cleanup_after_stop_state(obs_streaming: bool | None) -> tuple[bool, str]:
    """Keep the historical pure helper available to existing callers."""
    return _obs_cleanup_after_stop_state(obs_streaming)


class LiveControlDialog(QDialog):
    """Coordinate live-room controls and OBS integration through injected services."""

    live_status_changed = pyqtSignal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        services: AppServices | None = None,
        task_scope: TaskScope | None = None,
    ) -> None:
        """Create the dialog with shared configuration and authentication boundaries."""
        super().__init__(parent)
        self.setWindowTitle("直播控制")
        self.setMinimumSize(520, 540)

        self.services = services if services is not None else create_default_services()
        self.live_control_service: LiveControlService = self.services.live_control_service
        if task_scope is None:
            task_supervisor = TaskSupervisor()
            self._task_supervisor: TaskSupervisor | None = task_supervisor
            self._owns_task_supervisor = True
            self._task_scope = task_supervisor.create_scope("live-control")
        else:
            self._task_supervisor = None
            self._owns_task_supervisor = False
            self._task_scope = task_scope
        self.area_list: tuple[LiveAreaGroup, ...] = ()
        self.credentials: list[StreamCredential] = []
        self.current_room_info: RoomInfo | None = None
        self.is_live_active = False
        self._initial_load_task: asyncio.Task[None] | None = None  # Canceled when the dialog closes.
        self._room_info_task: asyncio.Task[None] | None = None  # Latest room-info request.
        self._load_generation = 0
        self._action_generation = 0
        self._service_close_task: asyncio.Task[None] | None = None  # Deferred reusable-service cleanup.
        self._busy = False
        self._obs_busy = False
        self._obs_connected = False
        self._action_tasks: set[asyncio.Task[Any]] = set()  # Qt-triggered workflows owned by this dialog.
        self._shutting_down = False  # Blocks new dialog work during application shutdown.
        self._shutdown_complete = False  # Makes application shutdown idempotent.

        self._init_ui()
        self._load_config_values()
        self._update_action_state()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(10)

        self.status_label = QLabel("打开后会加载登录状态和直播分区。")
        self.status_label.setWordWrap(True)
        self._set_status_style("info")
        main_layout.addWidget(self.status_label)

        form = QFrame(self)
        form.setStyleSheet(
            """
            QFrame {
                background: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
            }
            QLabel {
                color: #eeeeee;
                border: none;
            }
            QLineEdit, QComboBox {
                color: #eeeeee;
                background: #1f1f1f;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 5px 7px;
            }
            QComboBox QAbstractItemView {
                color: #eeeeee;
                background: #2b2b2b;
                selection-color: #111111;
                selection-background-color: #ff6ab3;
                border: 1px solid #4a4a4a;
                outline: none;
            }
            QPushButton {
                color: #ffffff;
                background: #00a1d6;
                border: none;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QPushButton:disabled {
                color: #888888;
                background: #3a3a3a;
            }
            QPushButton:hover:!disabled {
                background: #00b5e5;
            }
            """
        )
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(10)
        form_layout.setColumnStretch(1, 1)

        self.room_id_input = QLineEdit()
        self.room_id_input.setPlaceholderText("直播间 ID")
        self.room_id_input.textChanged.connect(self._update_action_state)
        self.room_id_input.editingFinished.connect(self.reload_room_info)
        form_layout.addWidget(QLabel("房间号"), 0, 0)
        form_layout.addWidget(self.room_id_input, 0, 1, 1, 2)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("直播标题")
        self.title_input.textChanged.connect(self._update_action_state)
        form_layout.addWidget(QLabel("标题"), 1, 0)
        form_layout.addWidget(self.title_input, 1, 1)

        self.update_title_btn = QPushButton("更新标题")
        self.update_title_btn.setMinimumWidth(90)
        self.update_title_btn.clicked.connect(self.handle_update_title)
        form_layout.addWidget(self.update_title_btn, 1, 2)

        self.parent_area_combo = QComboBox()
        self._setup_searchable_combo(self.parent_area_combo, "搜索分类")
        self.parent_area_combo.lineEdit().textEdited.connect(lambda _text: self._on_parent_area_changed())
        self.parent_area_combo.currentIndexChanged.connect(self._on_parent_area_changed)
        form_layout.addWidget(QLabel("分类"), 2, 0)
        form_layout.addWidget(self.parent_area_combo, 2, 1, 1, 2)

        self.area_combo = QComboBox()
        self._setup_searchable_combo(self.area_combo, "搜索分区")
        self.area_combo.currentIndexChanged.connect(self._update_action_state)
        form_layout.addWidget(QLabel("分区"), 3, 0)
        form_layout.addWidget(self.area_combo, 3, 1)

        self.update_area_btn = QPushButton("更新分区")
        self.update_area_btn.setMinimumWidth(90)
        self.update_area_btn.clicked.connect(self.handle_update_area)
        form_layout.addWidget(self.update_area_btn, 3, 2)

        action_row = QHBoxLayout()
        self.start_btn = QPushButton("开始直播")
        self.start_btn.clicked.connect(self.handle_start_live)
        self.stop_btn = QPushButton("停止直播")
        self.stop_btn.clicked.connect(self.handle_stop_live)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.stop_btn)
        form_layout.addLayout(action_row, 4, 0, 1, 3)

        self.obs_host_input = QLineEdit()
        self.obs_host_input.setPlaceholderText("127.0.0.1")
        self.obs_host_input.textChanged.connect(self._update_action_state)
        self.obs_host_input.textEdited.connect(self._mark_obs_unchecked)
        self.obs_port_input = QLineEdit()
        self.obs_port_input.setPlaceholderText("4455")
        self.obs_port_input.setFixedWidth(72)
        self.obs_port_input.textChanged.connect(self._update_action_state)
        self.obs_port_input.textEdited.connect(self._mark_obs_unchecked)
        obs_endpoint_row = QHBoxLayout()
        obs_endpoint_row.setContentsMargins(0, 0, 0, 0)
        obs_endpoint_row.setSpacing(8)
        obs_endpoint_row.addWidget(self.obs_host_input)
        obs_endpoint_row.addWidget(self.obs_port_input)
        form_layout.addWidget(QLabel("OBS"), 5, 0)
        form_layout.addLayout(obs_endpoint_row, 5, 1, 1, 2)

        self.obs_password_input = QLineEdit()
        self.obs_password_input.setPlaceholderText("OBS WebSocket 密码，可留空")
        self.obs_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.obs_password_input.textChanged.connect(self._update_action_state)
        self.obs_password_input.textEdited.connect(self._mark_obs_unchecked)
        self.write_obs_btn = QPushButton("检查 OBS")
        self.write_obs_btn.setMinimumWidth(90)
        self.write_obs_btn.clicked.connect(self.handle_check_obs)
        form_layout.addWidget(QLabel("密码"), 6, 0)
        form_layout.addWidget(self.obs_password_input, 6, 1)
        form_layout.addWidget(self.write_obs_btn, 6, 2)
        main_layout.addWidget(form)

        credentials_title = QLabel("推流凭证")
        credentials_title.setStyleSheet("font-weight: bold; color: #eeeeee;")
        main_layout.addWidget(credentials_title)

        self.credentials_scroll = QScrollArea(self)
        self.credentials_scroll.setWidgetResizable(True)
        self.credentials_scroll.setStyleSheet(
            """
            QScrollArea {
                background: #1f1f1f;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
            }
            """
        )
        self.credentials_container = QWidget()
        self.credentials_layout = QVBoxLayout(self.credentials_container)
        self.credentials_layout.setContentsMargins(8, 8, 8, 8)
        self.credentials_layout.setSpacing(8)
        self.credentials_scroll.setWidget(self.credentials_container)
        main_layout.addWidget(self.credentials_scroll, 1)

        self._render_credentials()

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        close_row.addWidget(self.close_btn)
        main_layout.addLayout(close_row)

    def _setup_searchable_combo(self, combo: QComboBox, placeholder: str) -> None:
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMaxVisibleItems(18)
        combo.setMinimumContentsLength(14)
        combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.lineEdit().setPlaceholderText(placeholder)
        combo.lineEdit().textEdited.connect(self._update_action_state)
        popup_style = """
            QListView, QAbstractItemView {
                color: #eeeeee;
                background: #2b2b2b;
                selection-color: #111111;
                selection-background-color: #ff6ab3;
                border: 1px solid #4a4a4a;
                outline: none;
            }
        """
        combo.view().setStyleSheet(popup_style)
        combo.completer().popup().setStyleSheet(popup_style)

    def _load_config_values(self) -> None:
        """Load typed settings and the OBS password from their separate boundaries."""
        settings = self.live_control_service.load_settings()
        self.room_id_input.setText(str(settings.room_id) if settings.room_id else "")
        self.title_input.setText(settings.live_title)
        self.obs_host_input.setText(settings.obs_host)
        self.obs_port_input.setText(str(settings.obs_port))
        self.obs_password_input.setText(settings.obs_password)

    def set_room_id(self, room_id: int) -> None:
        if room_id > 0:
            self.room_id_input.setText(str(room_id))

    def _create_action_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        """Create and retain one dialog action under the dialog task owner."""
        task = self._task_scope.create_task(coroutine, name=name)
        self._action_tasks.add(task)
        task.add_done_callback(self._discard_action_task)
        return task

    def _discard_action_task(self, task: asyncio.Task[Any]) -> None:
        """Remove a completed dialog action from the local registry."""
        self._action_tasks.discard(task)

    async def _cancel_action_tasks(self) -> None:
        """Cancel and await every Qt-triggered dialog action."""
        current_task = asyncio.current_task()
        pending = tuple(
            task
            for task in self._action_tasks
            if not task.done() and task is not current_task
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        if self._shutting_down:
            return
        if self._initial_load_task and not self._initial_load_task.done():
            return
        if (
            self.live_control_service.state.session.status is not SessionStatus.CLOSED
            and (self._service_close_task is None or self._service_close_task.done())
        ):
            self._update_action_state()
            return

        self._load_generation += 1
        self._initial_load_task = self._task_scope.create_task(
            self.load_initial_state(self._load_generation),
            name="initial-load",
        )

    def closeEvent(self, event: QCloseEvent | None) -> None:
        """Cancel owned work and schedule reusable service cleanup."""
        self._load_generation += 1
        self._action_generation += 1
        if self._initial_load_task and not self._initial_load_task.done():
            self._initial_load_task.cancel()
        if self._room_info_task and not self._room_info_task.done():
            self._room_info_task.cancel()
        for task in tuple(self._action_tasks):
            if not task.done():
                task.cancel()
        self._clear_credentials()
        if self._service_close_task is None or self._service_close_task.done():
            self._service_close_task = self._task_scope.create_task(
                self.live_control_service.close(),
                name="close-live-control-service",
            )
        self._busy = False
        self._update_action_state()
        super().closeEvent(event)

    async def shutdown(self) -> None:
        """Cancel dialog work and await cleanup of the service-owned resources."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        self._load_generation += 1
        self._action_generation += 1
        await cancel_task(self._initial_load_task)
        await cancel_task(self._room_info_task)
        await cancel_task(self._service_close_task)
        await self._cancel_action_tasks()
        self._clear_credentials()
        try:
            await self.live_control_service.shutdown()
        except Exception as exc:
            logger.exception("Failed to shut down live-control service")
            raise exc
        try:
            await self._task_scope.cancel_all()
            self._busy = False
            self._update_action_state()
        finally:
            if self._owns_task_supervisor and self._task_supervisor is not None:
                await self._task_supervisor.shutdown()
        self._shutdown_complete = True

    async def load_initial_state(self, generation: int) -> None:
        """Load the service snapshot and discard it when the dialog load is stale."""
        self._set_busy(True, "正在加载登录状态和直播分区...")
        try:
            result = await self.live_control_service.initialize(self._room_id())
            if generation != self._load_generation:
                return
            self._apply_service_state(result.state)
            if result.error is not None:
                if result.error.code is LiveControlErrorCode.LOGIN_EXPIRED:
                    self.set_status("保存的登录状态已过期，请先通过托盘菜单重新扫码登录。", error=True)
                else:
                    self.set_status(result.error.message, error=True)
            elif self._has_csrf():
                self.set_status("登录状态可用。")
            else:
                self.set_status("未找到 CSRF Token，请先通过托盘菜单扫码登录。", error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if generation == self._load_generation:
                logger.exception("Failed to initialize live control dialog")
                self.set_status(f"初始化失败: {exc}", error=True)
        finally:
            if generation == self._load_generation:
                self._set_busy(False)

    def _populate_parent_areas(self) -> None:
        self.parent_area_combo.blockSignals(True)
        self.parent_area_combo.clear()
        for parent in self.area_list:
            self.parent_area_combo.addItem(parent.name, parent.parent_area_id)
        self.parent_area_combo.blockSignals(False)
        self._on_parent_area_changed()

    def _apply_service_state(self, state: LiveControlState) -> None:
        """Bind one immutable service snapshot to the dialog's presentation fields."""
        self.area_list = state.areas
        self.credentials = list(state.credentials)
        self.current_room_info = state.room_info
        self._obs_connected = state.obs_connected
        self._populate_parent_areas()
        if state.room_info is not None:
            self._set_live_active(state.room_info.is_live)
            if state.room_info.title:
                self.title_input.setText(state.room_info.title)
            self._select_area(state.room_info.parent_area_id, state.room_info.area_id)
        else:
            self._set_live_active(False)
        self._render_credentials()

    async def _load_room_info(self, generation: int, update_status: bool = True) -> bool:
        room_id = self._room_id()
        if room_id is None:
            self.current_room_info = None
            self._restore_saved_area()
            return False
        result = await self.live_control_service.load_room_info(room_id)
        if generation != self._load_generation:
            return False
        self._apply_service_state(result.state)
        if result.error is not None:
            self.current_room_info = None
            self._restore_saved_area()
            logger.info("Failed to load room info for %s: %s", room_id, result.error.message)
            return False
        if update_status:
            self.set_status("已加载直播间当前标题和分区。")
        return True

    @pyqtSlot()
    def reload_room_info(self) -> asyncio.Task[None] | None:
        """Schedule a room-info refresh under the dialog task owner."""
        if self._shutting_down:
            return None
        if self._room_info_task is not None and not self._room_info_task.done():
            return self._room_info_task
        task = self._create_action_task(self._reload_room_info(), name="reload-room-info")
        self._room_info_task = task
        return task

    async def _reload_room_info(self) -> None:
        if self._shutting_down:
            return
        if (
            self._busy
            or not self.area_list
            or self.live_control_service.state.session.status is SessionStatus.CLOSED
        ):
            return
        if self._room_id() is None:
            self.current_room_info = None
            self._restore_saved_area()
            self.set_status("房间号无效，无法加载直播间当前标题和分区。", error=True)
            self._update_action_state()
            return
        task = asyncio.current_task()
        has_csrf = self._has_csrf()
        if has_csrf:
            self.set_status("正在加载直播间当前标题和分区...")
        try:
            loaded = await self._load_room_info(self._load_generation, update_status=has_csrf)
            if not has_csrf:
                self.set_status("未找到 CSRF Token，请先通过托盘菜单扫码登录。", error=True)
            elif not loaded and self.isVisible():
                self.set_status("未能加载直播间当前标题和分区，已使用保存的分区。", error=True)
        finally:
            if self._room_info_task is task:
                self._room_info_task = None
            self._update_action_state()

    def _restore_saved_area(self) -> None:
        settings = self.live_control_service.load_settings()
        self._select_area(settings.live_parent_area_id, settings.live_area_id)

    def _select_area(self, parent_id: str, area_id: str) -> None:
        if parent_id:
            parent_index = self.parent_area_combo.findData(parent_id)
            if parent_index >= 0:
                self.parent_area_combo.setCurrentIndex(parent_index)
        if area_id:
            area_index = self.area_combo.findData(area_id)
            if area_index >= 0:
                self.area_combo.setCurrentIndex(area_index)

    def _on_parent_area_changed(self) -> None:
        current_parent_id = self._selected_parent_area_id()
        selected_parent = next(
            (parent for parent in self.area_list if parent.parent_area_id == current_parent_id),
            None,
        )

        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        if selected_parent:
            for area in selected_parent.areas:
                self.area_combo.addItem(area.name, area.area_id)
        self.area_combo.blockSignals(False)
        self._update_action_state()

    def _room_id(self) -> int | None:
        text = self.room_id_input.text().strip()
        if not validate_room_id(text):
            return None
        return int(text)

    def _selected_area_id(self) -> str:
        return self._selected_combo_data(self.area_combo)

    def _selected_parent_area_id(self) -> str:
        return self._selected_combo_data(self.parent_area_combo)

    @staticmethod
    def _selected_combo_data(combo: QComboBox) -> str:
        current_text = combo.currentText()
        current_index = combo.currentIndex()
        if current_index < 0 or current_text != combo.itemText(current_index):
            current_index = combo.findText(current_text, Qt.MatchFlag.MatchFixedString)
        if current_index < 0:
            return ""
        return str(combo.itemData(current_index) or "")

    def _obs_port(self) -> int | None:
        try:
            port = int(self.obs_port_input.text().strip() or "4455")
        except ValueError:
            return None
        return port if 1 <= port <= 65535 else None

    def _obs_settings(self) -> ObsSettings | None:
        port = self._obs_port()
        if port is None:
            return None
        host = self.obs_host_input.text().strip()
        return ObsSettings(
            host=host if host else "127.0.0.1",
            port=port,
            password=self.obs_password_input.text(),
        )

    def _has_csrf(self) -> bool:
        return self.live_control_service.state.session.is_authenticated

    def _update_action_state(self) -> None:
        if self._busy:
            return
        has_room = self._room_id() is not None
        has_title = bool(self.title_input.text().strip())
        has_area = bool(self._selected_area_id())
        has_csrf = self._has_csrf()
        self.update_title_btn.setEnabled(has_room and has_title and has_csrf)
        self.update_area_btn.setEnabled(has_room and has_area and has_csrf)
        can_start = has_room and has_title and has_area and has_csrf
        can_stop = has_room and has_csrf
        start_enabled, stop_enabled = room_action_enabled_state(can_start, can_stop, self.is_live_active)
        self.start_btn.setEnabled(start_enabled)
        self.stop_btn.setEnabled(stop_enabled)
        obs_enabled, obs_text = obs_check_button_state(
            port_valid=self._obs_port() is not None,
            checking=self._obs_busy,
            connected=self._obs_connected,
        )
        self.write_obs_btn.setEnabled(obs_enabled)
        self.write_obs_btn.setText(obs_text)

    def _mark_obs_unchecked(self) -> None:
        self._obs_connected = False
        self._update_action_state()

    def _set_live_active(self, is_live: bool) -> None:
        if self.is_live_active == is_live:
            return
        self.is_live_active = is_live
        self.live_status_changed.emit(is_live)
        self._update_action_state()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = busy
        for widget in (
            self.room_id_input,
            self.title_input,
            self.parent_area_combo,
            self.area_combo,
            self.update_title_btn,
            self.update_area_btn,
            self.start_btn,
            self.stop_btn,
            self.obs_host_input,
            self.obs_port_input,
            self.obs_password_input,
            self.write_obs_btn,
        ):
            widget.setEnabled(not busy)
        if message:
            self.set_status(message)
        if not busy:
            self._update_action_state()

    def _set_status_style(self, level: str) -> None:
        colors = {
            "info": ("#102534", "#49c8f5", "#d9f6ff"),
            "success": ("#13311f", "#44d17a", "#e2ffe9"),
            "error": ("#3a1717", "#ff6b6b", "#ffe0e0"),
        }
        background, border, foreground = colors.get(level, colors["info"])
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {foreground};
                background: {background};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 7px 10px;
                font-weight: 700;
            }}
            """
        )

    def set_status(self, message: str, error: bool = False, success: bool = False) -> None:
        self.status_label.setText(message)
        self._set_status_style("error" if error else "success" if success else "info")

    def _save_form_config(self) -> bool:
        """Persist form settings and save or clear the OBS password securely."""
        current = self.live_control_service.load_settings()
        port = self._obs_port()
        settings = LiveControlSettings(
            room_id=self._room_id(),
            live_title=self.title_input.text().strip(),
            live_parent_area_id=self._selected_parent_area_id(),
            live_area_id=self._selected_area_id(),
            obs_host=self.obs_host_input.text().strip() or current.obs_host,
            obs_port=port if port is not None else current.obs_port,
            obs_password=self.obs_password_input.text(),
        )
        return self.live_control_service.save_settings(settings).success

    def _begin_action(self) -> int:
        self._action_generation += 1
        return self._action_generation

    def _is_current_action(self, generation: int) -> bool:
        return (
            generation == self._action_generation
            and self.isVisible()
        )

    @pyqtSlot()
    def handle_update_title(self) -> asyncio.Task[None] | None:
        """Schedule the title update workflow under the dialog task owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._handle_update_title(), name="update-title")

    async def _handle_update_title(self) -> None:
        if self._shutting_down:
            return
        if self.live_control_service.state.session.status is SessionStatus.CLOSED:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        title = self.title_input.text().strip()
        if room_id is None or not title:
            self.set_status("房间号和标题不能为空。", error=True)
            return
        self._set_busy(True, "正在更新标题...")
        try:
            result = await self.live_control_service.update_title(room_id, title)
            if not self._is_current_action(action_generation):
                return
            self._apply_service_state(result.state)
            if result.error is not None:
                self.set_status(result.error.message, error=True)
                return
            self._save_form_config()
            self.set_status("直播间标题已更新。")
        except Exception as exc:
            if self._is_current_action(action_generation):
                logger.exception("Failed to update room title")
                self.set_status(f"更新标题失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation):
                self._set_busy(False)

    @pyqtSlot()
    def handle_update_area(self) -> asyncio.Task[None] | None:
        """Schedule the area update workflow under the dialog task owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._handle_update_area(), name="update-area")

    async def _handle_update_area(self) -> None:
        if self._shutting_down:
            return
        if self.live_control_service.state.session.status is SessionStatus.CLOSED:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        area_id = self._selected_area_id()
        if room_id is None or not area_id:
            self.set_status("房间号和分区不能为空。", error=True)
            return
        self._set_busy(True, "正在更新分区...")
        try:
            result = await self.live_control_service.update_area(room_id, area_id)
            if not self._is_current_action(action_generation):
                return
            self._apply_service_state(result.state)
            if result.error is not None:
                self.set_status(result.error.message, error=True)
                return
            self._save_form_config()
            self.set_status("直播间分区已更新。")
        except Exception as exc:
            if self._is_current_action(action_generation):
                logger.exception("Failed to update room area")
                self.set_status(f"更新分区失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation):
                self._set_busy(False)

    @pyqtSlot()
    def handle_start_live(self) -> asyncio.Task[None] | None:
        """Schedule the start-live workflow under the dialog task owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._handle_start_live(), name="start-live")

    async def _handle_start_live(self) -> None:
        if self._shutting_down:
            return
        if self.live_control_service.state.session.status is SessionStatus.CLOSED:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        title = self.title_input.text().strip()
        area_id = self._selected_area_id()
        if room_id is None or not title or not area_id:
            self.set_status("请填写房间号、标题和分区。", error=True)
            return

        self._set_busy(True, "正在开始直播...")
        obs_settings = self._obs_settings()
        try:
            self._save_form_config()
            outcome = await self.live_control_service.start_live(
                room_id,
                title,
                area_id,
                obs_settings,
            )
            if not self._is_current_action(action_generation):
                return
            if outcome.status is StartLiveStatus.OBS_SWITCH_REQUIRED:
                self._set_busy(False)
                if not await self._confirm_switch_obs_stream():
                    self.set_status("已取消开播，OBS 推流保持不变。")
                    return
                if not self._is_current_action(action_generation):
                    return
                self._set_busy(True, "正在开始直播...")
                outcome = await self.live_control_service.start_live(
                    room_id,
                    title,
                    area_id,
                    obs_settings,
                    allow_obs_switch=True,
                )
                if not self._is_current_action(action_generation):
                    return
            self._apply_service_state(outcome.state)
            await self._present_start_outcome(outcome)
        except Exception as exc:
            if self._is_current_action(action_generation):
                logger.exception("Failed to start live")
                self.set_status(f"开始直播失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation):
                self._set_busy(False)

    async def _present_start_outcome(self, outcome: StartLiveOutcome) -> None:
        """Render a typed service outcome and open verification UI when required."""
        if outcome.status is StartLiveStatus.VERIFICATION_REQUIRED:
            title = "人脸认证" if "face-auth" in outcome.verification_url else "开播验证"
            await self._show_qr_verification(outcome.verification_url, title=title)
            message = "本次开播需要验证，完成后请重新点击开始直播。"
            self.set_status(self._with_start_notice(outcome, message), error=True)
            return
        if outcome.status is StartLiveStatus.STARTED_WITHOUT_CREDENTIALS:
            message = outcome.error.message if outcome.error else "直播已开始，但未生成推流凭证。"
            self.set_status(self._with_start_notice(outcome, message), error=True)
            return
        if outcome.status is StartLiveStatus.STARTED:
            if outcome.error is not None and outcome.error.code is LiveControlErrorCode.OBS_FAILURE:
                message = "直播已开始，RTMP 凭证已生成；OBS 自动推流失败，可手动复制地址和密钥。"
                self.set_status(self._with_start_notice(outcome, message), error=True)
            elif outcome.obs_started:
                message = "直播已开始，推流凭证已生成，OBS 已自动开始推流。"
                self.set_status(self._with_start_notice(outcome, message), success=True)
            else:
                message = "直播已开始，推流凭证已生成。"
                self.set_status(self._with_start_notice(outcome, message), success=True)
            return
        message = outcome.error.message if outcome.error is not None else "开始直播失败。"
        self.set_status(self._with_start_notice(outcome, message), error=True)

    @staticmethod
    def _with_start_notice(outcome: StartLiveOutcome, message: str) -> str:
        """Preserve non-fatal room-sync notices alongside the final start result."""
        return f"{outcome.notice}\n{message}" if outcome.notice else message

    @pyqtSlot()
    def handle_stop_live(self) -> asyncio.Task[None] | None:
        """Schedule the stop-live workflow under the dialog task owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._handle_stop_live(), name="stop-live")

    async def _handle_stop_live(self) -> None:
        if self._shutting_down:
            return
        if self.live_control_service.state.session.status is SessionStatus.CLOSED:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        if room_id is None:
            self.set_status("房间号无效。", error=True)
            return

        self._set_busy(True, "正在停止直播...")
        try:
            self._save_form_config()
            outcome = await self.live_control_service.stop_live(room_id, self._obs_settings())
            if not self._is_current_action(action_generation):
                return
            self._apply_service_state(outcome.state)
            if outcome.status is StopLiveStatus.STOPPED and outcome.obs_stopped:
                self.set_status("直播已停止，OBS 推流已停止。")
            elif outcome.status is StopLiveStatus.STOPPED:
                self.set_status("直播已停止。")
            else:
                self.set_status(
                    outcome.error.message if outcome.error is not None else "停止直播失败。",
                    error=True,
                )
        except Exception as exc:
            if self._is_current_action(action_generation):
                logger.exception("Failed to stop live")
                self.set_status(f"停止直播失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation):
                self._set_busy(False)

    async def _confirm_switch_obs_stream(self) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        box = QMessageBox(self)
        box.setWindowTitle("OBS 正在推流")
        box.setText("OBS 当前正在推流。继续开播会停止当前 OBS 推流，并切换到新的 B 站推流地址。")
        box.setInformativeText("取消将不会开播，也不会修改 OBS。")
        box.setWindowModality(Qt.WindowModality.WindowModal)
        continue_btn = box.addButton("继续开播", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)

        def finish() -> None:
            if not future.done():
                future.set_result(box.clickedButton() == continue_btn)
            box.deleteLater()

        box.finished.connect(lambda _result: finish())
        box.open()
        return await future

    async def stop_obs_stream(self, auto: bool = False) -> bool:
        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        if not auto:
            self.set_status("正在停止 OBS 推流...")
        try:
            outcome = await self.live_control_service.stop_obs_stream(self._obs_settings())
            self._apply_service_state(self.live_control_service.state)
            if not outcome.success:
                if not auto and outcome.error is not None:
                    self.set_status(outcome.error.message, error=True)
                return False
            if not auto:
                self.set_status("OBS 推流已停止。", success=True)
            return True
        except Exception as exc:
            logger.exception("Unexpected OBS stop failure")
            if not auto:
                self.set_status(f"停止 OBS 推流失败: {exc}", error=True)
            return False
        finally:
            self._obs_busy = False
            self._update_action_state()

    @pyqtSlot()
    def handle_check_obs(self) -> asyncio.Task[None] | None:
        """Schedule the OBS check workflow under the dialog task owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._handle_check_obs(), name="check-obs")

    async def _handle_check_obs(self) -> None:
        if self._shutting_down:
            return
        settings = self._obs_settings()
        if settings is None:
            self.set_status("OBS 端口无效。", error=True)
            return

        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        self.set_status("正在检查 OBS WebSocket...")
        try:
            outcome = await self.live_control_service.check_obs(settings)
            self._apply_service_state(self.live_control_service.state)
            if outcome.connected:
                self.set_status("OBS 已启动并且 WebSocket 可连接。点击“开始直播”会自动推流。", success=True)
                return
            if outcome.launched:
                self.set_status("已启动 OBS。请等待 OBS 完成加载，然后点击“开始直播”。", success=True)
            elif outcome.error is not None:
                self.set_status(outcome.error.message, error=True)
        finally:
            self._obs_busy = False
            self._update_action_state()

    async def start_obs_stream(self, auto: bool = False) -> None:
        settings = self._obs_settings()
        if settings is None:
            if not auto:
                self.set_status("OBS 端口无效。", error=True)
            return

        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        if not auto:
            self.set_status("正在填入 OBS 推流设置并启动推流...")
        try:
            outcome = await self.live_control_service.start_obs_stream(settings)
            self._apply_service_state(self.live_control_service.state)
            if outcome.success:
                credential = self.credentials[0] if self.credentials else None
                label = credential.label.upper() if credential is not None else "RTMP"
                self.set_status(f"已将 {label} 填入 OBS 并启动推流。", success=True)
            elif not auto and outcome.error is not None:
                self.set_status(outcome.error.message, error=True)
            elif auto and self.credentials:
                self.set_status("直播已开始，RTMP 凭证已生成；OBS 自动推流失败，可手动复制地址和密钥。", error=True)
        except Exception as exc:
            logger.exception("Unexpected OBS write failure")
            if not auto:
                self.set_status(f"启动 OBS 推流失败: {exc}", error=True)
            elif self.credentials:
                self.set_status("直播已开始，RTMP 凭证已生成；OBS 自动推流失败，可手动复制地址和密钥。", error=True)
        finally:
            self._obs_busy = False
            self._update_action_state()

    def _clear_credentials(self) -> None:
        """Clear only the transient stream credentials shown by this dialog."""
        self.credentials = []
        self._render_credentials()

    def _render_credentials(self) -> None:
        while self.credentials_layout.count():
            item = self.credentials_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self.credentials:
            empty_label = QLabel("开播成功后会在这里显示 RTMP/SRT 地址和密钥。")
            empty_label.setWordWrap(True)
            empty_label.setStyleSheet("color: #aaaaaa;")
            self.credentials_layout.addWidget(empty_label)
            self.credentials_layout.addStretch()
            return

        for credential in self.credentials:
            self.credentials_layout.addWidget(self._credential_row(credential))
        self.credentials_layout.addStretch()

    def _credential_row(self, credential: StreamCredential) -> QWidget:
        row = QFrame(self)
        row.setStyleSheet(
            """
            QFrame {
                background: #292929;
                border: 1px solid #3f3f3f;
                border-radius: 6px;
            }
            QLabel {
                color: #eeeeee;
                border: none;
            }
            QLineEdit {
                color: #eeeeee;
                background: #1f1f1f;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 5px 7px;
            }
            QPushButton {
                color: #ffffff;
                background: #555555;
                border: none;
                border-radius: 4px;
                padding: 5px 8px;
            }
            QPushButton:hover {
                background: #666666;
            }
            """
        )
        layout = QGridLayout(row)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        title = QLabel(credential.label.upper())
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title, 0, 0, 1, 3)

        address = QLineEdit(credential.address)
        address.setReadOnly(True)
        copy_address = QPushButton("复制地址")
        copy_address.clicked.connect(lambda _checked=False, text=credential.address: self.copy_to_clipboard(text))
        layout.addWidget(QLabel("地址"), 1, 0)
        layout.addWidget(address, 1, 1)
        layout.addWidget(copy_address, 1, 2)

        key = QLineEdit(credential.key)
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.EchoMode.Password)
        copy_key = QPushButton("复制密钥")
        copy_key.clicked.connect(lambda _checked=False, text=credential.key: self.copy_to_clipboard(text))
        layout.addWidget(QLabel("密钥"), 2, 0)
        layout.addWidget(key, 2, 1)
        layout.addWidget(copy_key, 2, 2)
        return row

    def copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.set_status("已复制到剪贴板。")

    async def _show_qr_verification(self, url: str, title: str = "开播验证") -> None:
        if not url:
            await self._show_text_dialog(title, "本次开播需要扫码验证，但接口未返回二维码地址。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        prompt = QLabel("请使用哔哩哔哩 App 扫码完成验证，完成后重新点击开始直播。")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        bio = self.live_control_service.generate_qr_image(url)
        if bio:
            image = QImage.fromData(bio.getvalue())
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    220,
                    220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(label)
        else:
            layout.addWidget(QLabel(url))

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        await self._open_dialog(dialog)

    async def _show_text_dialog(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        copy_btn = box.addButton("复制", QMessageBox.ButtonRole.ActionRole)
        await self._open_dialog(box)
        if box.clickedButton() == copy_btn:
            self.copy_to_clipboard(text)

    async def _open_dialog(self, dialog: QDialog) -> int:
        """Open a modal dialog asynchronously and close it when its owner is canceled."""
        loop = asyncio.get_running_loop()
        finished: asyncio.Future[int] = loop.create_future()

        def complete(result: int) -> None:
            if not finished.done():
                finished.set_result(result)

        dialog.finished.connect(complete)
        dialog.open()
        try:
            return await finished
        except asyncio.CancelledError:
            dialog.close()
            raise
        finally:
            dialog.deleteLater()
