"""Embedded live-control page for the unified settings window."""

from __future__ import annotations

import asyncio

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.app.lifecycle import TaskScope
from bilihud.app.live_control_service import LiveControlService
from bilihud.config.store import DEFAULT_OBS_HOST, DEFAULT_OBS_PORT
from bilihud.live.models import (
    LiveAreaGroup,
    LiveControlSettings,
    LiveControlState,
    LiveVerificationKind,
    ObsCheckOutcome,
    ObsSettings,
    RoomInfo,
    StreamCredential,
)
from bilihud.live.validation import validate_room_id
from bilihud.ui.settings.pages.live.credentials import LiveCredentials
from bilihud.ui.settings.pages.live.verification import LiveVerificationDialog
from bilihud.ui.settings.pages.live.warning import LiveWarningDialog
from bilihud.ui.settings.pages.live.workflow import (
    LiveAction,
    LiveSettingsForm,
    LiveSettingsWorkflow,
    LiveStartedHandler,
)
from bilihud.ui.settings.style import ModernComboBox


class LiveSettingsPage(QWidget):
    """Render live-room and OBS controls while delegating workflows to the service."""

    live_status_changed = pyqtSignal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        service: LiveControlService | None = None,
        task_scope: TaskScope | None = None,
        on_live_started: LiveStartedHandler | None = None,
    ) -> None:
        """Create the embedded form with explicit service and task ownership."""
        super().__init__(parent)
        self.live_control_service = service
        self._area_groups: tuple[LiveAreaGroup, ...] = ()
        self._room_info: RoomInfo | None = None
        self._credentials: tuple[StreamCredential, ...] = ()
        self._is_live = False
        self._busy = False
        self._busy_action: LiveAction | None = None
        self._obs_busy = False
        self._obs_connected = False
        self._shutting_down = False
        self._verification_dialog: QDialog | None = None
        self._confirmation_dialog: QMessageBox | None = None
        self._warning_dialog: LiveWarningDialog | None = None
        self._workflow = LiveSettingsWorkflow(
            service,
            task_scope,
            self,
            on_live_started=on_live_started,
        )
        self._init_ui()
        self._load_form_values()
        self.update_action_state()

    def _init_ui(self) -> None:
        """Build the compact settings cards and bind controls to workflow commands."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 8, 8)
        page_layout.setSpacing(14)

        self.status_label = QLabel("打开此页面后加载登录状态和直播分区。", self)
        self.status_label.setObjectName("status_label")
        self.status_label.setWordWrap(True)
        page_layout.addWidget(self.status_label)

        room_card, room_layout = self._new_card("直播间")
        room_form = QFormLayout()
        room_form.setHorizontalSpacing(18)
        room_form.setVerticalSpacing(10)

        room_row = QHBoxLayout()
        room_row.setContentsMargins(0, 0, 0, 0)
        self.room_id_input = QLineEdit(room_card)
        self.room_id_input.setPlaceholderText("直播间 ID")
        self.room_id_input.textChanged.connect(self.update_action_state)
        self.room_id_input.editingFinished.connect(self.reload_room_info)
        room_row.addWidget(self.room_id_input, 1)
        self.refresh_room_button = QPushButton("刷新信息", room_card)
        self.refresh_room_button.clicked.connect(self.reload_room_info)
        room_row.addWidget(self.refresh_room_button)
        room_form.addRow("房间号", room_row)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title_input = QLineEdit(room_card)
        self.title_input.setPlaceholderText("直播标题")
        self.title_input.textChanged.connect(self.update_action_state)
        title_row.addWidget(self.title_input, 1)
        self.update_title_button = QPushButton("更新标题", room_card)
        self.update_title_button.clicked.connect(self.handle_update_title)
        title_row.addWidget(self.update_title_button)
        room_form.addRow("标题", title_row)

        self.parent_area_combo = ModernComboBox(room_card)
        self.parent_area_combo.currentIndexChanged.connect(self._on_parent_area_changed)
        room_form.addRow("分类", self.parent_area_combo)

        area_row = QHBoxLayout()
        area_row.setContentsMargins(0, 0, 0, 0)
        self.area_combo = ModernComboBox(room_card)
        self.area_combo.currentIndexChanged.connect(self.update_action_state)
        area_row.addWidget(self.area_combo, 1)
        self.update_area_button = QPushButton("更新分区", room_card)
        self.update_area_button.clicked.connect(self.handle_update_area)
        area_row.addWidget(self.update_area_button)
        room_form.addRow("分区", area_row)
        room_layout.addLayout(room_form)

        actions_frame = QFrame(room_card)
        actions_frame.setObjectName("live_actions")
        live_actions = QHBoxLayout(actions_frame)
        live_actions.setContentsMargins(0, 12, 0, 0)
        live_actions.setSpacing(8)
        self.start_button = QPushButton("开始直播", room_card)
        self.start_button.setProperty("accent", True)
        self.start_button.setMinimumWidth(128)
        self.start_button.clicked.connect(self.handle_start_live)
        self.stop_button = QPushButton("停止直播", room_card)
        self.stop_button.setMinimumWidth(112)
        self.stop_button.clicked.connect(self.handle_stop_live)
        live_actions.addStretch(1)
        live_actions.addWidget(self.start_button)
        live_actions.addWidget(self.stop_button)
        room_layout.addWidget(actions_frame)
        page_layout.addWidget(room_card)

        obs_card, obs_layout = self._new_card("OBS 推流")
        obs_form = QFormLayout()
        obs_form.setHorizontalSpacing(18)
        obs_form.setVerticalSpacing(10)
        endpoint_row = QHBoxLayout()
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        self.obs_host_input = QLineEdit(obs_card)
        self.obs_host_input.setPlaceholderText(DEFAULT_OBS_HOST)
        self.obs_host_input.textChanged.connect(self._mark_obs_unchecked)
        endpoint_row.addWidget(self.obs_host_input, 1)
        self.obs_port_input = QLineEdit(obs_card)
        self.obs_port_input.setPlaceholderText(str(DEFAULT_OBS_PORT))
        self.obs_port_input.setFixedWidth(92)
        self.obs_port_input.textChanged.connect(self._mark_obs_unchecked)
        endpoint_row.addWidget(self.obs_port_input)
        obs_form.addRow("WebSocket", endpoint_row)

        password_row = QHBoxLayout()
        password_row.setContentsMargins(0, 0, 0, 0)
        self.obs_password_input = QLineEdit(obs_card)
        self.obs_password_input.setPlaceholderText("可留空")
        self.obs_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.obs_password_input.textChanged.connect(self._mark_obs_unchecked)
        password_row.addWidget(self.obs_password_input, 1)
        self.check_obs_button = QPushButton("检查 OBS", obs_card)
        self.check_obs_button.clicked.connect(self.handle_check_obs)
        password_row.addWidget(self.check_obs_button)
        self.stop_obs_button = QPushButton("停止推流", obs_card)
        self.stop_obs_button.clicked.connect(self.handle_stop_obs)
        password_row.addWidget(self.stop_obs_button)
        obs_form.addRow("密码", password_row)
        obs_layout.addLayout(obs_form)
        self.obs_status_label = QLabel("未检查连接", obs_card)
        self.obs_status_label.setObjectName("muted_label")
        obs_layout.addWidget(self.obs_status_label)
        page_layout.addWidget(obs_card)

        credentials_card, credentials_layout = self._new_card("推流凭证")
        self.credentials_panel = LiveCredentials(credentials_card)
        self.credentials_panel.copy_requested.connect(self._on_credential_copied)
        credentials_layout.addWidget(self.credentials_panel)
        page_layout.addWidget(credentials_card)
        page_layout.addStretch(1)
        self.credentials_panel.set_credentials(())

    @staticmethod
    def _new_card(title: str) -> tuple[QFrame, QVBoxLayout]:
        """Create one framed settings section with a stable content layout."""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title_label = QLabel(title, card)
        title_label.setObjectName("card_title")
        layout.addWidget(title_label)
        return card, layout

    def _load_form_values(self) -> None:
        """Load persisted form values and the secure OBS password."""
        service = self.live_control_service
        if service is None:
            self.set_status("直播服务尚未连接。", error=True)
            return
        settings = service.load_settings()
        self.room_id_input.setText(str(settings.room_id) if settings.room_id is not None else "")
        self.title_input.setText(settings.live_title)
        self.obs_host_input.setText(settings.obs_host)
        self.obs_port_input.setText(str(settings.obs_port))
        self.obs_password_input.setText(settings.obs_password)

    def showEvent(self, a0: QShowEvent | None) -> None:
        """Start one service initialization when the live tab becomes visible."""
        super().showEvent(a0)
        if not self._shutting_down:
            self._workflow.activate()

    async def shutdown(self) -> None:
        """Cancel page workflows and close the shared live-control service."""
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._confirmation_dialog is not None:
            self._confirmation_dialog.close()
        if self._warning_dialog is not None:
            self._warning_dialog.close()
        if self._verification_dialog is not None:
            self._verification_dialog.close()
        await self._workflow.shutdown()

    def apply_service_state(self, state: LiveControlState) -> None:
        """Bind one immutable application snapshot to the embedded controls."""
        previous_live = self._is_live
        self._area_groups = state.areas
        self._room_info = state.room_info
        self._credentials = state.credentials
        self._obs_connected = state.obs_connected
        self._populate_area_combos()
        if state.room_info is not None:
            self._is_live = state.room_info.is_live
            self.room_id_input.setText(str(state.room_info.room_id))
            self.title_input.setText(state.room_info.title)
            self._select_area(state.room_info.parent_area_id, state.room_info.area_id)
        else:
            self._is_live = False
        if previous_live != self._is_live:
            self.live_status_changed.emit(self._is_live)
        self.credentials_panel.set_credentials(state.credentials)
        self.update_action_state()

    def _populate_area_combos(self) -> None:
        parent_id = self._room_info.parent_area_id if self._room_info is not None else ""
        area_id = self._room_info.area_id if self._room_info is not None else ""
        self.parent_area_combo.blockSignals(True)
        self.parent_area_combo.clear()
        for group in self._area_groups:
            self.parent_area_combo.addItem(group.name, group.parent_area_id)
        self.parent_area_combo.blockSignals(False)
        self._on_parent_area_changed()
        self._select_area(parent_id, area_id)

    def _select_area(self, parent_id: str, area_id: str) -> None:
        parent_index = self.parent_area_combo.findData(parent_id)
        if parent_index >= 0:
            self.parent_area_combo.setCurrentIndex(parent_index)
        area_index = self.area_combo.findData(area_id)
        if area_index >= 0:
            self.area_combo.setCurrentIndex(area_index)

    def _on_parent_area_changed(self) -> None:
        selected_parent = self._selected_combo_data(self.parent_area_combo)
        group = next((item for item in self._area_groups if item.parent_area_id == selected_parent), None)
        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        if group is not None:
            for area in group.areas:
                self.area_combo.addItem(area.name, area.area_id)
        self.area_combo.blockSignals(False)
        self.update_action_state()

    @staticmethod
    def _selected_combo_data(combo: QComboBox) -> str:
        """Return a validated string ID from a combo box data role."""
        value = combo.currentData()
        return value if isinstance(value, str) else ""

    def _room_id(self) -> int | None:
        text = self.room_id_input.text().strip()
        if not validate_room_id(text):
            return None
        return int(text)

    def _obs_port(self) -> int | None:
        try:
            value = int(self.obs_port_input.text().strip())
        except ValueError:
            return None
        return value if 1 <= value <= 65535 else None

    def _obs_settings(self) -> ObsSettings | None:
        port = self._obs_port()
        if port is None:
            return None
        host = self.obs_host_input.text().strip()
        return ObsSettings(host or DEFAULT_OBS_HOST, port, self.obs_password_input.text())

    def form_values(self) -> LiveSettingsForm:
        """Return normalized values for the workflow boundary."""
        return LiveSettingsForm(
            room_id=self._room_id(),
            title=self.title_input.text().strip(),
            parent_area_id=self._selected_combo_data(self.parent_area_combo),
            area_id=self._selected_combo_data(self.area_combo),
            obs=self._obs_settings(),
        )

    def save_form_config(self) -> bool:
        """Persist the visible form through the service's typed boundary."""
        service = self.live_control_service
        if service is None:
            return False
        current = service.load_settings()
        values = self.form_values()
        port = self._obs_port()
        settings = LiveControlSettings(
            room_id=values.room_id,
            live_title=values.title,
            live_parent_area_id=values.parent_area_id,
            live_area_id=values.area_id,
            obs_host=self.obs_host_input.text().strip() or current.obs_host,
            obs_port=port if port is not None else current.obs_port,
            obs_password=self.obs_password_input.text(),
        )
        return service.save_settings(settings).success

    def update_action_state(self) -> None:
        """Refresh action availability from current form, service, and OBS state."""
        service = self.live_control_service
        authenticated = service is not None and service.state.session.is_authenticated
        values = self.form_values()
        enabled = not self._busy
        can_start = values.room_id is not None and bool(values.title) and bool(values.area_id) and authenticated
        can_stop = values.room_id is not None and authenticated
        self.refresh_room_button.setEnabled(enabled and values.room_id is not None)
        self.update_title_button.setEnabled(
            enabled and values.room_id is not None and bool(values.title) and authenticated
        )
        self.update_area_button.setEnabled(
            enabled and values.room_id is not None and bool(values.area_id) and authenticated
        )
        start_busy = self._busy_action is LiveAction.START
        stop_busy = self._busy_action is LiveAction.STOP
        self._set_action_button(
            self.start_button,
            "正在开始..." if start_busy else "开始直播",
            enabled and can_start and not self._is_live,
            busy=start_busy,
        )
        self._set_action_button(
            self.stop_button,
            "正在停止..." if stop_busy else "停止直播",
            enabled and can_stop and self._is_live,
            busy=stop_busy,
        )
        obs_available = values.obs is not None and not self._obs_busy
        self.check_obs_button.setEnabled(enabled and obs_available)
        self.check_obs_button.setText("重新检查" if self._obs_connected else "检查 OBS")
        self.stop_obs_button.setEnabled(enabled and self._obs_connected)

    def set_busy(
        self,
        busy: bool,
        message: str | None = None,
        *,
        action: LiveAction | None = None,
    ) -> None:
        """Enable or disable all mutable controls around one workflow."""
        self._busy = busy
        self._busy_action = action if busy else None
        for widget in (
            self.room_id_input,
            self.title_input,
            self.parent_area_combo,
            self.area_combo,
            self.refresh_room_button,
            self.update_title_button,
            self.update_area_button,
            self.start_button,
            self.stop_button,
            self.obs_host_input,
            self.obs_port_input,
            self.obs_password_input,
            self.check_obs_button,
            self.stop_obs_button,
        ):
            widget.setEnabled(not busy)
        if message is not None:
            self.set_status(message)
        self.update_action_state()

    @staticmethod
    def _set_action_button(button: QPushButton, text: str, enabled: bool, *, busy: bool) -> None:
        """Keep action text, disabled state, and busy styling synchronized."""
        button.setText(text)
        button.setProperty("busy", busy)
        button.setEnabled(enabled)
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)

    def set_obs_busy(self, busy: bool) -> None:
        """Bind OBS operation progress to the local control state."""
        self._obs_busy = busy
        self.update_action_state()

    def set_obs_status(self, outcome: ObsCheckOutcome) -> None:
        """Render the normalized result of an OBS connectivity check."""
        if outcome.connected:
            self.obs_status_label.setText("OBS 已连接")
        elif outcome.launched:
            self.obs_status_label.setText("OBS 已启动，等待连接")
        else:
            self.obs_status_label.setText("OBS 未连接")

    def set_status(self, message: str, *, error: bool = False, success: bool = False) -> None:
        """Render a workflow message in the live page status region."""
        self.status_label.setText(message)
        level = "error" if error else "success" if success else "info"
        self.status_label.setProperty("level", level)
        style = self.status_label.style()
        if style is not None:
            style.unpolish(self.status_label)
            style.polish(self.status_label)

    def show_verification(self, url: str, kind: LiveVerificationKind) -> None:
        """Show the verification UI matching the live-start requirement."""
        current = self._verification_dialog
        if current is not None:
            current.close()
        service = self.live_control_service
        image_bytes = service.generate_qr_image(url) if service is not None and url else None
        dialog = LiveVerificationDialog(self, url, kind, image_bytes)
        self._verification_dialog = dialog
        dialog.finished.connect(lambda _result: self._clear_verification_dialog(dialog))
        dialog.open()

    def show_warning(self, title: str, message: str, details: str) -> None:
        """Show one non-blocking warning while keeping the page status available underneath."""
        current = self._warning_dialog
        if current is not None:
            current.close()

        dialog = LiveWarningDialog(self, title, message, details)
        dialog.finished.connect(lambda _result: self._clear_warning_dialog(dialog))
        self._warning_dialog = dialog
        dialog.open()

    async def confirm_obs_switch(self) -> bool:
        """Ask asynchronously before stopping an existing OBS stream."""
        loop = asyncio.get_running_loop()
        result: asyncio.Future[bool] = loop.create_future()
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("切换 OBS 推流")
        dialog.setText("OBS 当前正在推流。")
        dialog.setInformativeText("继续开播会停止当前推流，并切换到新的 B 站推流地址。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        continue_button = dialog.button(QMessageBox.StandardButton.Yes)
        cancel_button = dialog.button(QMessageBox.StandardButton.No)
        if continue_button is not None:
            continue_button.setText("继续开播")
        if cancel_button is not None:
            cancel_button.setText("取消")

        def finish(value: int) -> None:
            if self._confirmation_dialog is dialog:
                self._confirmation_dialog = None
            if not result.done():
                result.set_result(value == int(QMessageBox.StandardButton.Yes))

        dialog.finished.connect(finish)
        self._confirmation_dialog = dialog
        dialog.open()
        try:
            return await result
        except asyncio.CancelledError:
            dialog.close()
            raise

    def _clear_verification_dialog(self, dialog: QDialog) -> None:
        """Release the latest verification window after it closes."""
        if self._verification_dialog is dialog:
            self._verification_dialog = None

    def _clear_warning_dialog(self, dialog: LiveWarningDialog) -> None:
        """Release the latest warning window after it closes."""
        if self._warning_dialog is dialog:
            self._warning_dialog = None

    def _mark_obs_unchecked(self) -> None:
        self._obs_connected = False
        self.update_action_state()

    @pyqtSlot()
    def reload_room_info(self) -> asyncio.Task[None] | None:
        """Forward a room refresh request to the workflow owner."""
        return self._workflow.reload_room_info()

    @pyqtSlot()
    def handle_update_title(self) -> asyncio.Task[None] | None:
        """Forward a title update request to the workflow owner."""
        return self._workflow.update_title()

    @pyqtSlot()
    def handle_update_area(self) -> asyncio.Task[None] | None:
        """Forward an area update request to the workflow owner."""
        return self._workflow.update_area()

    @pyqtSlot()
    def handle_start_live(self) -> asyncio.Task[None] | None:
        """Forward a start-live request to the workflow owner."""
        return self._workflow.start_live()

    @pyqtSlot()
    def handle_stop_live(self) -> asyncio.Task[None] | None:
        """Forward a stop-live request to the workflow owner."""
        return self._workflow.stop_live()

    @pyqtSlot()
    def handle_check_obs(self) -> asyncio.Task[None] | None:
        """Forward an OBS check request to the workflow owner."""
        return self._workflow.check_obs()

    @pyqtSlot()
    def handle_stop_obs(self) -> asyncio.Task[None] | None:
        """Forward a stop-OBS request to the workflow owner."""
        return self._workflow.stop_obs()

    def _on_credential_copied(self) -> None:
        """Report a local copy action without exposing the credential value."""
        self.set_status("已复制到剪贴板。", success=True)


__all__ = ("LiveSettingsPage",)
