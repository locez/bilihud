import asyncio
import logging
from typing import Any

import aiohttp
import qasync
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
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

from .auth import AuthManager
from .live_api import (
    LiveApiError,
    RoomInfo,
    StreamCredential,
    extract_qr_url,
    get_area_list,
    get_cookie_value,
    get_live_version,
    get_room_info,
    is_live_rate_limited_error,
    parse_stream_credentials,
    room_action_enabled_state,
    room_area_needs_update,
    room_title_needs_update,
    start_live,
    start_live_verification_url,
    stop_live,
    update_room_area,
    update_room_title,
)
from .obs_api import (
    ObsApiError,
    ObsWebSocketClient,
    is_obs_process_running,
    launch_obs,
    obs_check_button_state,
    pick_primary_credential,
)
from .utils import load_config, save_config, validate_room_id

logger = logging.getLogger(__name__)


def start_live_confirmation_needed(obs_streaming: bool | None) -> bool:
    return obs_streaming is True


def obs_cleanup_after_stop_state(obs_streaming: bool | None) -> tuple[bool, str]:
    if obs_streaming is True:
        return True, "streaming"
    if obs_streaming is False:
        return False, "not_streaming"
    return False, "unknown"


class LiveControlDialog(QDialog):
    live_status_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("直播控制")
        self.setMinimumSize(520, 540)

        self.auth_manager = AuthManager()
        self.session: aiohttp.ClientSession | None = None
        self.area_list: list[dict[str, Any]] = []
        self.credentials: list[StreamCredential] = []
        self.current_room_info: RoomInfo | None = None
        self.is_live_active = False
        self._initial_load_task: asyncio.Task[None] | None = None
        self._room_info_task: asyncio.Task[None] | None = None
        self._obs_write_task: asyncio.Task[None] | None = None
        self._load_generation = 0
        self._action_generation = 0
        self._session_cleanup_task: asyncio.Task[None] | None = None
        self._sessions_pending_close: list[aiohttp.ClientSession] = []
        self._busy = False
        self._obs_busy = False
        self._obs_connected = False
        self._obs_streaming_started = False

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
        config = load_config()
        room_id = config.get("room_id", "")
        self.room_id_input.setText(str(room_id) if room_id else "")
        self.title_input.setText(str(config.get("live_title", "")))
        self.obs_host_input.setText(str(config.get("obs_host", "127.0.0.1")))
        self.obs_port_input.setText(str(config.get("obs_port", "4455")))
        self.obs_password_input.setText(str(config.get("obs_password", "")))

    def set_room_id(self, room_id: int) -> None:
        if room_id > 0:
            self.room_id_input.setText(str(room_id))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._initial_load_task and not self._initial_load_task.done():
            return
        if self.session and not self.session.closed:
            self._update_action_state()
            return

        self._load_generation += 1
        self._initial_load_task = asyncio.create_task(self.load_initial_state(self._load_generation))
        self._initial_load_task.add_done_callback(self._consume_task_exception)

    def closeEvent(self, event) -> None:
        self._load_generation += 1
        self._action_generation += 1
        if self._initial_load_task and not self._initial_load_task.done():
            self._initial_load_task.cancel()
        if self._room_info_task and not self._room_info_task.done():
            self._room_info_task.cancel()
        if self._obs_write_task and not self._obs_write_task.done():
            self._obs_write_task.cancel()
        self._clear_credentials()
        self._schedule_session_cleanup(self.session)
        self.session = None
        self._busy = False
        self._update_action_state()
        super().closeEvent(event)

    async def load_initial_state(self, generation: int) -> None:
        self._set_busy(True, "正在加载登录状态和直播分区...")
        session: aiohttp.ClientSession | None = None
        try:
            session, _from_keyring = await self.auth_manager.create_authenticated_session()
            if generation != self._load_generation:
                self._schedule_session_cleanup(session)
                return

            self.session = session
            if self._has_csrf():
                self.set_status("登录状态可用。")
            else:
                self.set_status("未找到 CSRF Token，请先通过托盘菜单扫码登录。", error=True)

            area_list = await get_area_list(self.session)
            if generation != self._load_generation:
                return

            self.area_list = area_list
            self._populate_parent_areas()
            await self._load_room_info(generation, update_status=self._has_csrf())
        except asyncio.CancelledError:
            self._schedule_session_cleanup(session)
            raise
        except Exception as exc:
            if generation == self._load_generation:
                logger.exception("Failed to initialize live control dialog")
                self.set_status(f"初始化失败: {exc}", error=True)
        finally:
            if generation == self._load_generation:
                self._set_busy(False)

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unhandled live control dialog task error")

    def _schedule_session_cleanup(self, session: aiohttp.ClientSession | None) -> None:
        if session and not session.closed and session not in self._sessions_pending_close:
            self._sessions_pending_close.append(session)

        if self._sessions_pending_close and (
            self._session_cleanup_task is None or self._session_cleanup_task.done()
        ):
            self._session_cleanup_task = asyncio.create_task(self._close_pending_sessions())
            self._session_cleanup_task.add_done_callback(self._consume_task_exception)

    async def _close_pending_sessions(self) -> None:
        while self._sessions_pending_close:
            session = self._sessions_pending_close.pop(0)
            if session.closed:
                continue
            try:
                await session.close()
            except Exception:
                logger.exception("Failed to close live control session")

    def _populate_parent_areas(self) -> None:
        self.parent_area_combo.blockSignals(True)
        self.parent_area_combo.clear()
        for parent in self.area_list:
            self.parent_area_combo.addItem(str(parent.get("name") or ""), str(parent.get("id") or ""))
        self.parent_area_combo.blockSignals(False)
        self._on_parent_area_changed()

    async def _load_room_info(self, generation: int, update_status: bool = True) -> bool:
        room_id = self._room_id()
        if room_id is None or self.session is None:
            self.current_room_info = None
            self._restore_saved_area()
            return False

        try:
            room_info = await get_room_info(self.session, room_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Failed to load room info for %s: %s", room_id, exc)
            if generation == self._load_generation:
                self.current_room_info = None
                self._restore_saved_area()
            return False

        if generation != self._load_generation:
            return False

        self.current_room_info = room_info
        self._set_live_active(room_info.is_live)
        if room_info.title:
            self.title_input.setText(room_info.title)
        self._select_area(room_info.parent_area_id, room_info.area_id)
        if update_status:
            self.set_status("已加载直播间当前标题和分区。")
        return True

    @qasync.asyncSlot()
    async def reload_room_info(self) -> None:
        if self._busy or not self.area_list or not self.session or self.session.closed:
            return
        if self._room_id() is None:
            self.current_room_info = None
            self._restore_saved_area()
            self.set_status("房间号无效，无法加载直播间当前标题和分区。", error=True)
            self._update_action_state()
            return
        task = asyncio.current_task()
        if task is not None:
            self._room_info_task = task
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
        config = load_config()
        parent_id = str(config.get("live_parent_area_id", ""))
        area_id = str(config.get("live_area_id", ""))
        self._select_area(parent_id, area_id)

    def _remember_synced_title(self, room_id: int, title: str) -> None:
        current = self.current_room_info
        self.current_room_info = RoomInfo(
            room_id=room_id,
            title=title,
            parent_area_id=current.parent_area_id if current and current.room_id == room_id else "",
            area_id=current.area_id if current and current.room_id == room_id else "",
        )

    def _remember_synced_area(self, room_id: int, area_id: str) -> None:
        current = self.current_room_info
        self.current_room_info = RoomInfo(
            room_id=room_id,
            title=current.title if current and current.room_id == room_id else "",
            parent_area_id=self._selected_parent_area_id(),
            area_id=area_id,
        )

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
            (parent for parent in self.area_list if str(parent.get("id") or "") == current_parent_id),
            None,
        )

        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        if selected_parent:
            for area in selected_parent.get("list") or []:
                self.area_combo.addItem(str(area.get("name") or ""), str(area.get("id") or ""))
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

    def _obs_client(self) -> ObsWebSocketClient | None:
        port = self._obs_port()
        if port is None:
            self.set_status("OBS 端口无效。", error=True)
            return None
        return ObsWebSocketClient(
            host=self.obs_host_input.text().strip() or "127.0.0.1",
            port=port,
            password=self.obs_password_input.text(),
        )

    async def _current_obs_streaming(self) -> bool | None:
        client = self._obs_client()
        if client is None:
            return None
        try:
            streaming = await client.is_streaming()
        except ObsApiError as exc:
            logger.info("Failed to query OBS stream status: %s", exc)
            self._obs_connected = False
            return None
        except Exception:
            logger.exception("Unexpected OBS stream status failure")
            self._obs_connected = False
            return None
        self._obs_connected = True
        return streaming

    def _has_csrf(self) -> bool:
        return bool(self.session and not self.session.closed and get_cookie_value(self.session, "bili_jct"))

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

    def _save_form_config(self) -> None:
        room_id = self._room_id()
        save_config(
            {
                "room_id": room_id if room_id is not None else self.room_id_input.text().strip(),
                "live_title": self.title_input.text().strip(),
                "live_parent_area_id": self._selected_parent_area_id(),
                "live_area_id": self._selected_area_id(),
                "obs_host": self.obs_host_input.text().strip() or "127.0.0.1",
                "obs_port": self.obs_port_input.text().strip() or "4455",
                "obs_password": self.obs_password_input.text(),
            }
        )

    def _begin_action(self) -> int:
        self._action_generation += 1
        return self._action_generation

    def _is_current_action(self, generation: int, session: aiohttp.ClientSession) -> bool:
        return (
            generation == self._action_generation
            and self.isVisible()
            and self.session is session
            and not session.closed
        )

    async def _sync_room_before_start(
        self,
        session: aiohttp.ClientSession,
        room_id: int,
        title: str,
        area_id: str,
    ) -> None:
        if room_title_needs_update(self.current_room_info, room_id, title):
            await update_room_title(session, room_id, title)
            self._remember_synced_title(room_id, title)

        if room_area_needs_update(self.current_room_info, room_id, area_id):
            await update_room_area(session, room_id, area_id)
            self._remember_synced_area(room_id, area_id)

    async def _sync_room_before_start_lenient(
        self,
        session: aiohttp.ClientSession,
        room_id: int,
        title: str,
        area_id: str,
    ) -> None:
        try:
            await self._sync_room_before_start(session, room_id, title, area_id)
        except LiveApiError as exc:
            if is_live_rate_limited_error(exc):
                logger.info("Room update skipped before start because Bilibili rate limited it: %s", exc)
                self.set_status("直播间信息刚更新过，已跳过重复同步并继续开播...")
                return
            raise

    @qasync.asyncSlot()
    async def handle_update_title(self) -> None:
        session = self.session
        if not session:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        title = self.title_input.text().strip()
        if room_id is None or not title:
            self.set_status("房间号和标题不能为空。", error=True)
            return
        self._set_busy(True, "正在更新标题...")
        try:
            await update_room_title(session, room_id, title)
            if not self._is_current_action(action_generation, session):
                return
            self._remember_synced_title(room_id, title)
            self._save_form_config()
            self.set_status("直播间标题已更新。")
        except Exception as exc:
            if self._is_current_action(action_generation, session):
                logger.exception("Failed to update room title")
                self.set_status(f"更新标题失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation, session):
                self._set_busy(False)

    @qasync.asyncSlot()
    async def handle_update_area(self) -> None:
        session = self.session
        if not session:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        area_id = self._selected_area_id()
        if room_id is None or not area_id:
            self.set_status("房间号和分区不能为空。", error=True)
            return
        self._set_busy(True, "正在更新分区...")
        try:
            await update_room_area(session, room_id, area_id)
            if not self._is_current_action(action_generation, session):
                return
            self._remember_synced_area(room_id, area_id)
            self._save_form_config()
            self.set_status("直播间分区已更新。")
        except Exception as exc:
            if self._is_current_action(action_generation, session):
                logger.exception("Failed to update room area")
                self.set_status(f"更新分区失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation, session):
                self._set_busy(False)

    @qasync.asyncSlot()
    async def handle_start_live(self) -> None:
        session = self.session
        if not session:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        title = self.title_input.text().strip()
        area_id = self._selected_area_id()
        if room_id is None or not title or not area_id:
            self.set_status("请填写房间号、标题和分区。", error=True)
            return

        self._set_busy(True, "正在开始直播...")
        try:
            obs_streaming = await self._current_obs_streaming()
            if not self._is_current_action(action_generation, session):
                return
            if start_live_confirmation_needed(obs_streaming):
                self._set_busy(False)
                if not await self._confirm_switch_obs_stream():
                    self.set_status("已取消开播，OBS 推流保持不变。")
                    return
                if not self._is_current_action(action_generation, session):
                    return
                self._set_busy(True, "正在开始直播...")

            self._save_form_config()
            await self._sync_room_before_start_lenient(session, room_id, title, area_id)
            if not self._is_current_action(action_generation, session):
                return
            version = await get_live_version(session)
            if not self._is_current_action(action_generation, session):
                return
            result = await start_live(session, room_id, area_id, version.curr_version, str(version.build))
            if not self._is_current_action(action_generation, session):
                return
            self._handle_start_live_result(result.code, result.message, result.data)
        except LiveApiError as exc:
            if self._is_current_action(action_generation, session):
                logger.exception("Live API error while starting live")
                self.set_status(str(exc), error=True)
        except Exception as exc:
            if self._is_current_action(action_generation, session):
                logger.exception("Failed to start live")
                self.set_status(f"开始直播失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation, session):
                self._set_busy(False)

    def _handle_start_live_result(self, code: int, message: str, data: dict[str, Any]) -> None:
        if code == 0:
            self.credentials = parse_stream_credentials(data)
            self._render_credentials()
            self._set_live_active(True)
            if self.credentials:
                self.set_status("直播已开始，推流凭证已生成；正在尝试连接 OBS 自动推流。", success=True)
                self._obs_write_task = asyncio.create_task(self._write_obs_after_start())
                self._obs_write_task.add_done_callback(self._consume_task_exception)
            else:
                self.set_status("直播已开始，但接口未返回可识别的推流凭证。", error=True)
            return

        if code == 60024:
            self._show_qr_verification(start_live_verification_url(code, data, uid=None))
            self.set_status("本次开播需要扫码验证，完成后请重新点击开始直播。", error=True)
            return

        if code == 60043:
            uid = get_cookie_value(self.session, "DedeUserID") if self.session else None
            auth_url = start_live_verification_url(code, data, uid=uid)
            if auth_url:
                self._show_qr_verification(auth_url, title="人脸认证")
            else:
                self._show_text_dialog("人脸认证", "本次开播需要人脸认证，但当前会话缺少 DedeUserID。")
            self.set_status("本次开播需要人脸认证，完成后请重新点击开始直播。", error=True)
            return

        self.set_status(f"开始直播失败: {message or 'Unknown Error'} ({code})", error=True)

    @staticmethod
    def _extract_qr_url(data: dict[str, Any]) -> str:
        return extract_qr_url(data)

    @qasync.asyncSlot()
    async def handle_stop_live(self) -> None:
        session = self.session
        if not session:
            return
        action_generation = self._begin_action()
        room_id = self._room_id()
        if room_id is None:
            self.set_status("房间号无效。", error=True)
            return

        self._set_busy(True, "正在停止直播...")
        try:
            await stop_live(session, room_id)
            if not self._is_current_action(action_generation, session):
                return
            self._clear_credentials()
            self._set_live_active(False)
            obs_streaming = await self._current_obs_streaming()
            should_stop_obs, obs_state = obs_cleanup_after_stop_state(obs_streaming)
            obs_stopped = True
            if should_stop_obs:
                obs_stopped = await self.stop_obs_stream(auto=True)
                if not self._is_current_action(action_generation, session):
                    return
            self._obs_streaming_started = False
            if should_stop_obs and obs_stopped:
                self.set_status("直播已停止，OBS 推流已停止。")
            elif obs_state == "unknown" or (should_stop_obs and not obs_stopped):
                self.set_status("直播已停止；OBS 推流未能自动确认/停止，请在 OBS 中手动确认。", error=True)
            else:
                self.set_status("直播已停止。")
        except Exception as exc:
            if self._is_current_action(action_generation, session):
                logger.exception("Failed to stop live")
                self.set_status(f"停止直播失败: {exc}", error=True)
        finally:
            if self._is_current_action(action_generation, session):
                self._set_busy(False)

    async def _write_obs_after_start(self) -> None:
        await self.start_obs_stream(auto=True)

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
        client = self._obs_client()
        if client is None:
            return False

        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        if not auto:
            self.set_status("正在停止 OBS 推流...")
        try:
            await client.stop_stream()
            self._obs_streaming_started = False
            if not auto:
                self.set_status("OBS 推流已停止。", success=True)
            return True
        except ObsApiError as exc:
            logger.info("Failed to stop OBS stream: %s", exc)
            if not auto:
                self.set_status(f"停止 OBS 推流失败: {exc}", error=True)
            return False
        except Exception as exc:
            logger.exception("Unexpected OBS stop failure")
            if not auto:
                self.set_status(f"停止 OBS 推流失败: {exc}", error=True)
            return False
        finally:
            self._obs_busy = False
            self._update_action_state()

    @qasync.asyncSlot()
    async def handle_check_obs(self) -> None:
        client = self._obs_client()
        if client is None:
            return

        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        self.set_status("正在检查 OBS WebSocket...")
        try:
            try:
                await client.check_connection()
            except ObsApiError as exc:
                logger.info("OBS WebSocket check failed: %s", exc)
                self._obs_connected = False
            else:
                self._obs_connected = True
                self.set_status("OBS 已启动并且 WebSocket 可连接。点击“开始直播”会自动推流。", success=True)
                return

            try:
                if is_obs_process_running():
                    self._obs_connected = False
                    self.set_status("OBS 已启动，但 WebSocket 无法连接。请检查 OBS WebSocket 设置。", error=True)
                    return
                launch_obs()
                self._obs_connected = False
                self.set_status("已启动 OBS。请等待 OBS 完成加载，然后点击“开始直播”。", success=True)
            except ObsApiError as exc:
                self.set_status(f"启动 OBS 失败: {exc}", error=True)
            except Exception as exc:
                logger.exception("Unexpected OBS launch failure")
                self.set_status(f"启动 OBS 失败: {exc}", error=True)
        finally:
            self._obs_busy = False
            self._update_action_state()

    async def start_obs_stream(self, auto: bool = False) -> None:
        credential = pick_primary_credential(self.credentials)
        if credential is None:
            if not auto:
                self.set_status("没有可用于启动 OBS 推流的凭证。", error=True)
            return
        client = self._obs_client()
        if client is None:
            return

        self._save_form_config()
        self._obs_busy = True
        self._update_action_state()
        if not auto:
            self.set_status("正在填入 OBS 推流设置并启动推流...")
        try:
            try:
                obs_streaming = await client.is_streaming()
            except ObsApiError as exc:
                logger.info("Failed to query existing OBS stream before switch: %s", exc)
            else:
                if obs_streaming:
                    await client.stop_stream()
            await client.set_stream_service_settings_and_start(credential)
            self._obs_streaming_started = True
            self.set_status(f"已将 {credential.label.upper()} 填入 OBS 并启动推流。", success=True)
        except ObsApiError as exc:
            logger.info("Failed to write OBS stream settings: %s", exc)
            if not auto:
                self.set_status(f"启动 OBS 推流失败: {exc}", error=True)
            elif self.credentials:
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

    def _show_qr_verification(self, url: str, title: str = "开播验证") -> None:
        if not url:
            self._show_text_dialog(title, "本次开播需要扫码验证，但接口未返回二维码地址。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        prompt = QLabel("请使用哔哩哔哩 App 扫码完成验证，完成后重新点击开始直播。")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        bio = self.auth_manager.generate_qr_image(url)
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
        dialog.exec()

    def _show_text_dialog(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        copy_btn = box.addButton("复制", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() == copy_btn:
            self.copy_to_clipboard(text)
