import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, Protocol

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QSystemTrayIcon, QWidget

from bilihud.app.account_controller import AccountState
from bilihud.app.application_controller import ApplicationController
from bilihud.app.hud import HudEvent, HudState
from bilihud.app.lifecycle import TaskScope, TaskSupervisor
from bilihud.app.menu import AccountStatus, MenuCommand, TrayMenuState
from bilihud.app.mirror_coordinator import MirrorCoordinatorPort, MirrorOperationResult
from bilihud.app.services import ApplicationServices
from bilihud.auth.service import AccountProfile
from bilihud.danmaku.messages import (
    GiftMessage,
    HudMessage,
    SystemMessageLevel,
    make_system_message,
)
from bilihud.danmaku.mock import mock_gift_effect_message, mock_message_batch
from bilihud.live.emoticons import LiveEmoticon
from bilihud.mirror.state import MirrorEntry
from bilihud.platform.overlay_contracts import (
    OverlayOperationResult,
    OverlayPlatform,
    WindowPoint,
)
from bilihud.ui.hud.account_controller import AccountSurfaceController
from bilihud.ui.hud.gift_effect import GiftEffectWindow
from bilihud.ui.hud.input import ModernInputWidget
from bilihud.ui.hud.layout import build_hud_widgets
from bilihud.ui.hud.mirror_controller import MirrorController
from bilihud.ui.hud.state_view import HudStateRenderer
from bilihud.ui.hud.window_mode import WindowModeController
from bilihud.ui.settings.controller import SettingsController
from bilihud.ui.settings.models import SettingsPage
from bilihud.ui.tray.controller import TrayController
from bilihud.ui.window_host import QtWindowHost

logger = logging.getLogger(__name__)


class DanmakuListPort(Protocol):
    """List operations needed by the message history update."""

    def addItem(self, item: QListWidgetItem | None) -> None:
        """Append one prepared Qt list item."""
        ...

    def count(self) -> int:
        """Return the current history size."""
        ...

    def takeItem(self, row: int) -> QListWidgetItem | None:
        """Remove and return one history item."""
        ...

    def scrollToBottom(self) -> None:
        """Scroll the visible history to its newest item."""
        ...

    def scheduleDelayedItemsLayout(self) -> None:
        """Schedule one layout pass after history changes."""
        ...


class DanmakuDelegatePort(Protocol):
    """Delegate operation needed when an old history item is removed."""

    def set_font_family(self, font_family: str) -> None:
        """Apply the selected HUD font to rendered documents."""
        ...

    def forget_message(self, message: HudMessage) -> None:
        """Forget cached rendering data for one removed message."""
        ...


class DanmakuMessagePublisher(Protocol):
    """Mirror capability needed by the message history update."""

    def publish_message(self, message: HudMessage) -> MirrorEntry:
        """Publish one normalized message."""
        ...


class DanmakuMessageTarget(Protocol):
    """Minimal state needed to append one normalized message to the HUD."""

    @property
    def danmaku_list(self) -> DanmakuListPort:
        """Return the message list surface."""
        ...

    @property
    def _danmaku_delegate(self) -> DanmakuDelegatePort:
        """Return the delegate cache owner."""
        ...

    @property
    def mirror_coordinator(self) -> DanmakuMessagePublisher:
        """Return the Mirror message publisher."""
        ...


def append_hud_message(target: DanmakuMessageTarget, message: HudMessage) -> None:
    """Append a message to history, trim old entries, and publish it to Mirror."""
    item = QListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, message)

    target.danmaku_list.addItem(item)

    if target.danmaku_list.count() > 200:
        removed_item = target.danmaku_list.takeItem(0)
        if removed_item is not None:
            removed_message = removed_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(removed_message, HudMessage):
                target._danmaku_delegate.forget_message(removed_message)

    target.danmaku_list.scrollToBottom()
    target.mirror_coordinator.publish_message(message)


def _opacity_to_alpha(opacity: int) -> int:
    """Convert a validated percentage into the HUD background alpha channel."""
    return max(0, min(255, round(255 * opacity / 100)))


class DanmakuWidget(QWidget):
    """Compose the HUD presentation and bind it to application-owned state."""

    message_received = pyqtSignal(object)
    settings_controller: SettingsController
    _danmaku_delegate: DanmakuDelegatePort
    danmaku_list: QListWidget
    mirror_coordinator: MirrorCoordinatorPort

    def __init__(
        self,
        room_id: int = 0,
        sessdata: str = "",
        *,
        application: ApplicationController | None = None,
        services: ApplicationServices | None = None,
        task_supervisor: TaskSupervisor | None = None,
    ) -> None:
        """Create the widget from an application controller and saved configuration.

        ``services`` remains accepted for direct construction by older callers. The
        runtime injects ``application`` so application workflow ownership stays out
        of the Qt presentation layer.
        """
        super().__init__()
        self._task_supervisor = task_supervisor if task_supervisor is not None else TaskSupervisor()
        self._owns_task_supervisor = task_supervisor is None
        self._task_scope: TaskScope = self._task_supervisor.create_scope("danmaku-widget")
        self._action_tasks: set[asyncio.Task[Any]] = set()  # Qt-triggered workflows owned by this widget.
        self._shutting_down = False  # Prevent new work from starting during application shutdown.
        self._shutdown_complete = False  # Makes repeated application stop requests idempotent.
        self.room_id = room_id  # Current room displayed and used by the client.
        self.sessdata = sessdata  # Optional session override supplied by the caller.
        if application is None:
            if services is None:
                raise TypeError("application 或 services 必须提供一个")
            # TODO(issue #30): remove this direct-construction path after callers inject ApplicationController.
            config = services.config_store.load()
            application = ApplicationController(
                room_id=room_id,
                sessdata=sessdata,
                services=services,
                config=config,
                task_scope=self._task_supervisor.create_scope("application"),
            )
        elif services is not None and services is not application.services:
            raise ValueError("application 与 services 必须来自同一个服务图")

        self.application = application
        self.services = application.services
        self.mirror_coordinator: MirrorCoordinatorPort = application.mirror_coordinator
        self.is_gaming_mode: bool = False
        account_state = self.application.account_controller.state
        self._account_status: AccountStatus = account_state.status
        self._account_profile: AccountProfile | None = account_state.profile
        self._window_host: QtWindowHost = QtWindowHost(self)
        self.popup_parent: QWidget = self
        self.overlay_platform: OverlayPlatform = self.services.overlay_platform_factory(self._window_host)
        self.gift_effect_window = GiftEffectWindow(
            self,
            platform_factory=self.services.overlay_platform_factory,
        )
        config = self.application.config
        self._hud_background_alpha = _opacity_to_alpha(config.window_opacity)
        self.settings_controller = SettingsController(
            self,
            application=self.application,
            task_scope=self._task_scope.child("settings"),
            on_mirror_toggle=self._schedule_mirror_toggle,
            on_live_status=self.set_live_status_indicator,
            on_live_started=self.application.hud_controller.connect,
            on_login=self.open_qr_login,
            on_logout=self.logout_account,
            on_simulation=self.trigger_danmaku_simulation,
            on_gift_effect_simulation=self.trigger_gift_effect_simulation,
            on_opacity_changed=self._apply_hud_opacity,
            on_hud_font_changed=self._apply_hud_font,
        )
        self.mirror_controller = MirrorController(
            self,
            task_factory=lambda coroutine, name: self._create_action_task(coroutine, name=name),
            is_shutting_down=lambda: self._shutting_down,
        )
        if config.room_id is not None:
            self.room_id = config.room_id
        self._hud_state: HudState = HudState(room_id=self.room_id)

        # [Performance] Resize Debounce Timer
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30) # 30ms Debounce
        self._resize_timer.timeout.connect(self._delayed_adjust_height)

        self.setup_window_properties()
        prepare_result = self.overlay_platform.prepare()
        if not prepare_result.succeeded:
            logger.warning("Platform window preparation failed: %s", prepare_result.reason)
        self.init_ui()
        self._apply_hud_font(config.hud_font_family)
        self.setup_tray_icon()
        self.window_mode_controller = WindowModeController(self, self.overlay_platform)
        self.update_gaming_mode_availability()
        self.account_surface_controller = AccountSurfaceController(
            self,
            parent=self,
            task_scope=self._task_scope.child("account-ui"),
            task_factory=lambda coroutine, name: self._create_action_task(coroutine, name=name),
            is_shutting_down=lambda: self._shutting_down,
            on_login_success=self.on_login_success,
        )

        self.hud_controller = self.application.hud_controller
        self._hud_state = self.hud_controller.state
        self.hud_state_renderer = HudStateRenderer(self)
        self.hud_controller.subscribe(self._on_hud_event)
        self.application.account_controller.subscribe(self._on_account_state)

        # 初始化房间号
        self.room_id_input.setText(str(self.room_id))
        self._bind_hud_state(self._hud_state)

        # Try to activate Layer Shell initially
        QTimer.singleShot(100, self.activate_layer_shell)

    async def start(self) -> None:
        """Start application workflows after construction is complete."""
        if self._shutting_down:
            return
        result = await self.application.start()
        self._apply_mirror_result(result)

    def _create_action_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        """Create and retain one Qt-triggered workflow under the widget owner."""
        task = self._task_scope.create_task(coroutine, name=name)
        self._action_tasks.add(task)
        task.add_done_callback(self._discard_action_task)
        return task

    def _discard_action_task(self, task: asyncio.Task[Any]) -> None:
        """Remove a completed Qt-triggered workflow from the widget registry."""
        self._action_tasks.discard(task)

    def _on_account_state(self, state: AccountState) -> None:
        """Bind the application account snapshot to settings and tray surfaces."""
        self._account_status = state.status
        self._account_profile = state.profile
        self._publish_account_state()

    def _publish_account_state(self) -> None:
        """Push the normalized account state to every presentation surface."""
        self.settings_controller.set_account_state(
            AccountState(self._account_status, self._account_profile)
        )

    async def _cancel_action_tasks(self) -> None:
        """Cancel and await Qt-triggered workflows before closing their resources."""
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

    def _delayed_adjust_height(self) -> None:
        """Run the debounced list layout update outside resize-event handling."""
        if not self.is_gaming_mode:
            # With Delegate + ResizeMode.Adjust, poking the layout is sufficient.
            self.danmaku_list.scheduleDelayedItemsLayout()

    def activate_layer_shell(self) -> OverlayOperationResult:
        """Activate the injected platform adapter after the Qt surface is mapped."""
        return self.window_mode_controller.activate_layer_shell()

    def setup_window_properties(self) -> None:
        """设置基本的窗口属性"""
        self.resize(300, 450)
        # 居中屏幕
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geo = screen.geometry()

            # Initialize position relative to primary screen top-left
            initial_x = screen_geo.width() - 330
            initial_y = 100

            # Qt move expects global coordinates.
            self._window_host.move_window(WindowPoint(screen_geo.x() + initial_x, screen_geo.y() + initial_y))
        self.setWindowTitle("Danmaku Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _apply_hud_opacity(self, opacity: int) -> None:
        """Apply the configured opacity to the HUD background layer."""
        self._hud_background_alpha = _opacity_to_alpha(opacity)
        self.update()

    def _apply_hud_font(self, font_family: str) -> None:
        """Apply the configured font to desktop HUD text and fallback effects."""
        self._danmaku_delegate.set_font_family(font_family)
        self.gift_effect_window.set_font_family(font_family)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """自定义绘制背景，实现轻微的渐变面板效果 (非穿透模式下)"""
        if not self.is_gaming_mode:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            painter.setBrush(QBrush(QColor(0, 0, 0, self._hud_background_alpha)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 8, 8)
            super().paintEvent(a0)

    def init_ui(self) -> None:
        """Compose the HUD controls from the dedicated layout builder."""
        widgets = build_hud_widgets(
            self,
            room_id=self.room_id,
            save_room_id=self.save_room_id,
            toggle_connection=self.toggle_connection,
            toggle_gaming_mode=self.toggle_gaming_mode,
            send_requested=self.trigger_send,
            emoticon_requested=self.open_emoticon_picker,
            emoticon_selected=self.trigger_send_live_emoticon,
            audience_requested=self.open_audience_popup,
            close_requested=self.hide,
        )
        self.main_layout = widgets.main_layout
        self.header_widget = widgets.header_widget
        self.live_status_dot = widgets.live_status_dot
        self.room_id_input = widgets.room_id_input
        self.connect_button = widgets.connect_button
        self.gaming_mode_btn = widgets.gaming_mode_btn
        self.danmaku_list = widgets.danmaku_list
        self._danmaku_delegate = widgets.danmaku_delegate
        self.input_area: ModernInputWidget = widgets.input_area
        self.emoticon_picker = widgets.emoticon_picker
        self.audience_status = widgets.audience_status
        self.audience_popup = widgets.audience_popup
        self.input_dialog = widgets.input_dialog
        self.size_grip = widgets.size_grip
        self.message_received.connect(self.add_message)
        self.dragging = False
        self._message_buffer: list[HudMessage] = []

    def setup_tray_icon(self) -> None:
        """Create the tray surface and bind it to typed command requests."""
        self.tray_controller = TrayController(
            self,
            state_provider=self._tray_menu_state,
            command_handler=self._handle_menu_command,
            activation_handler=self.on_tray_activated,
        )
        self.tray_icon = self.tray_controller.icon
        self.tray_menu = self.tray_controller.menu
        self.tray_send_action = self.tray_controller.action_for(MenuCommand.SEND_DANMAKU)
        self.tray_toggle_action = self.tray_controller.action_for(MenuCommand.TOGGLE_VISIBILITY)
        self.tray_gaming_action = self.tray_controller.action_for(MenuCommand.TOGGLE_GAMING_MODE)
        self.tray_login_action = self.tray_controller.action_for(MenuCommand.OPEN_LOGIN)
        self.tray_live_settings_action = self.tray_controller.action_for(MenuCommand.OPEN_LIVE_SETTINGS)
        self.tray_settings_action = self.tray_controller.action_for(MenuCommand.OPEN_SETTINGS)
        self.update_tray_menu_state()

    def _tray_menu_state(self) -> TrayMenuState:
        """Build the complete tray snapshot from current presentation and coordinator state."""
        capabilities = self.overlay_platform.capabilities
        return TrayMenuState(
            visible=self.isVisible(),
            gaming_mode=self.is_gaming_mode,
            gaming_mode_available=capabilities.gaming_mode,
            gaming_mode_reason=capabilities.unavailable_reason,
        )

    def update_tray_menu_state(self) -> None:
        """Refresh tray labels and check states from one immutable application snapshot."""
        self.tray_controller.refresh()
        self.settings_controller.set_mirror_status(self.mirror_coordinator.state.status_text)

    def _handle_menu_command(self, command: MenuCommand, checked: bool = False) -> None:
        """Route a tray command to an existing owner method without UI-side business logic."""
        if command is MenuCommand.SEND_DANMAKU:
            self.open_input_dialog()
        elif command is MenuCommand.TOGGLE_VISIBILITY:
            self.toggle_visibility()
        elif command is MenuCommand.TOGGLE_GAMING_MODE:
            self.toggle_gaming_mode_from_tray(checked)
        elif command is MenuCommand.OPEN_LOGIN:
            self.open_qr_login()
        elif command is MenuCommand.OPEN_LIVE_SETTINGS:
            self.open_settings(SettingsPage.LIVE)
        elif command is MenuCommand.OPEN_SETTINGS:
            self.open_settings(SettingsPage.GENERAL)
        elif command is MenuCommand.QUIT:
            self.quit_app()

    def add_system_message(
        self,
        message: str,
        level: SystemMessageLevel = SystemMessageLevel.INFO,
    ) -> None:
        """Add a locally generated system message to the shared message stream."""
        self.add_message(make_system_message(message, level))

    def is_gaming_mode_available(self) -> bool:
        """Return whether the selected platform can provide gaming mode."""
        return self.overlay_platform.capabilities.gaming_mode

    def update_gaming_mode_availability(self) -> None:
        """Bind platform capability state to both the window and tray controls."""
        self.window_mode_controller.update_availability()

    async def _send_danmaku_task(self, text: str) -> None:
        """Execute a text-send command through the application controller."""
        await self.hud_controller.send_danmaku(text)

    def trigger_send(self, text: str) -> None:
        """处理发送弹幕请求"""
        if not text or self._shutting_down:
            return
        self._task_scope.create_task(self._send_danmaku_task(text), name="send-danmaku")

    @pyqtSlot()
    def open_emoticon_picker(self) -> asyncio.Task[None] | None:
        """Schedule the emoticon loading workflow under the widget owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(
            self._open_emoticon_picker(),
            name="open-emoticon-picker",
        )

    async def _open_emoticon_picker(self) -> None:
        if not self.hud_controller.state.is_connected:
            self.add_system_message("未连接直播间，无法加载表情", SystemMessageLevel.ERROR)
            return

        self.emoticon_picker.set_loading()
        button_pos = self.input_area.emoticon_btn.mapToGlobal(QPoint(0, 0))
        self.emoticon_picker.move(
            button_pos.x() - self.emoticon_picker.width() + self.input_area.emoticon_btn.width(),
            button_pos.y() - self.emoticon_picker.height() - 8,
        )
        self.emoticon_picker.show()
        try:
            packages = await self.hud_controller.fetch_live_emoticons()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.emoticon_picker.set_error(str(exc))
            return
        self.emoticon_picker.set_packages(packages)

    def trigger_send_live_emoticon(self, emoticon: LiveEmoticon) -> None:
        if self._shutting_down:
            return
        self._task_scope.create_task(
            self._send_live_emoticon_task(emoticon),
            name="send-live-emoticon",
        )

    async def _send_live_emoticon_task(self, emoticon: LiveEmoticon) -> None:
        """Execute a live-emoticon send command through the application controller."""
        await self.hud_controller.send_live_emoticon(emoticon)

    def open_input_dialog(self) -> None:
        """打开全局输入框"""
        self.input_dialog.show()
        self.input_dialog.activateWindow()

    def trigger_danmaku_simulation(self) -> None:
        """Inject the standard fixed message batch into the normal HUD path."""
        if self._shutting_down:
            return
        for message in mock_message_batch():
            self.add_message(message)

    def trigger_gift_effect_simulation(self, effect_id: str) -> None:
        """Inject one selected advanced gift-effect fixture into the HUD path."""
        if self._shutting_down:
            return
        message = mock_gift_effect_message(effect_id)
        if message is None:
            logger.warning("Unknown developer gift effect fixture: %s", effect_id)
            return
        self.add_message(message)

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()
        self.update_tray_menu_state()

    async def shutdown(self) -> None:
        """Stop presentation workflows before handing shared resources to the app owner."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        shutdown_errors: list[Exception] = []
        try:
            await self._cancel_action_tasks()
            self.hud_controller.unsubscribe(self._on_hud_event)
            self.application.account_controller.unsubscribe(self._on_account_state)

            try:
                await self.settings_controller.shutdown()
            except Exception as exc:
                logger.exception("Failed to close settings dialog")
                shutdown_errors.append(exc)

            try:
                await self.account_surface_controller.shutdown()
            except Exception as exc:
                logger.exception("Failed to close QR login dialog")
                shutdown_errors.append(exc)

            self.gift_effect_window.close()
            self.tray_controller.close()

            try:
                await self._task_scope.cancel_all()
            except Exception as exc:
                logger.exception("Failed to cancel widget tasks")
                shutdown_errors.append(exc)

            try:
                await self.application.shutdown()
            except Exception as exc:
                logger.exception("Failed to close application workflows")
                shutdown_errors.append(exc)
        finally:
            if self._owns_task_supervisor:
                try:
                    await self._task_supervisor.shutdown()
                except Exception as exc:
                    logger.exception("Failed to close widget task supervisor")
                    shutdown_errors.append(exc)

        if shutdown_errors:
            raise shutdown_errors[0]
        self._shutdown_complete = True

    @pyqtSlot()
    def quit_app(self) -> asyncio.Task[None] | None:
        """Schedule resource cleanup before requesting the Qt process exit."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._quit_app(), name="quit-app")

    async def _quit_app(self) -> None:
        """Close application resources before requesting the Qt process exit."""
        await self.shutdown()
        QApplication.quit()

    def toggle_gaming_mode_from_tray(self, checked):
        """从托盘切换游戏模式"""
        self.window_mode_controller.toggle_from_tray(checked)

    def toggle_gaming_mode(self):
        """切换鼠标穿透/游戏模式"""
        self.window_mode_controller.toggle()

    def show_gaming_mode_unavailable_message(self, reason: str | None = None) -> None:
        """Explain a platform capability limitation without preventing normal use."""
        self.window_mode_controller.show_unavailable_message(reason)

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Apply a platform mode transition and then update the presentation state."""
        return self.window_mode_controller.set_gaming_mode(enabled)

    # --- 鼠标拖拽移动窗口逻辑 ---
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        self.window_mode_controller.mouse_press(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        self.window_mode_controller.mouse_move(a0)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)

        # 1. 更新SizeGrip位置
        rect = self.rect()
        self.size_grip.move(
            rect.right() - self.size_grip.width(),
            rect.bottom() - self.size_grip.height()
        )

        # 2. Debounced Layout Update
        if not self.is_gaming_mode:
            self._resize_timer.start()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        del a0
        self.window_mode_controller.mouse_release()

        # [Message Buffering]
        # Process all types of messages
        if self._message_buffer:
            for message in self._message_buffer:
                self.message_received.emit(message)
            self._message_buffer.clear()





    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self.update_tray_menu_state()
        # Re-activate Layer Shell when shown to ensure overlay/input works
        # Delayed to ensure window is mapped
        QTimer.singleShot(100, self.activate_layer_shell)

    def open_audience_popup(self):
        self.hud_state_renderer.open_audience_popup()

    def sync_audience_visibility(self) -> None:
        self.hud_state_renderer.sync_audience_visibility()

    def _on_hud_event(self, event: HudEvent) -> None:
        """Bind typed controller events to Qt rendering and user notifications."""
        self.hud_state_renderer.handle_event(event)

    def _bind_hud_state(self, state: HudState) -> None:
        """Render one complete controller snapshot without reading network objects."""
        self.hud_state_renderer.bind_state(state)

    @pyqtSlot()
    def toggle_connection(self) -> asyncio.Task[None] | None:
        """Schedule the room connection workflow under the widget owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._toggle_connection(), name="toggle-connection")

    async def _toggle_connection(self) -> None:
        """Convert the room input into a typed controller toggle command."""
        if self._shutting_down:
            return
        try:
            room_id = int(self.room_id_input.text().strip())
        except ValueError:
            self.add_system_message("直播间号无效", SystemMessageLevel.ERROR)
            return
        try:
            await self.hud_controller.toggle_connection(room_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def save_room_id(self):
        try:
            self.room_id = int(self.room_id_input.text())
        except ValueError:
            self.room_id_input.setText(str(self.room_id))

    def on_message_received(self, message: HudMessage) -> None:
        """Queue or display a message that has already crossed the blivedm boundary."""
        if self.dragging:
            self._message_buffer.append(message)
        else:
            self.message_received.emit(message)

    def add_message(self, message: HudMessage) -> None:
        """Add one normalized message to Qt history and the optional Mirror stream."""
        append_hud_message(self, message)
        if isinstance(message, GiftMessage) and self.application.config.overlay_gift_effects_enabled:
            self.gift_effect_window.show_gift(message)

    def open_settings(self, page: SettingsPage = SettingsPage.GENERAL) -> None:
        """Open the unified settings window on the requested detail page."""
        if self._shutting_down:
            return
        self.settings_controller.open(page)

    @pyqtSlot()
    def open_live_control(self) -> None:
        """Keep the historical command as an alias for the unified live settings tab."""
        self.open_settings(SettingsPage.LIVE)

    def open_mirror_settings(self) -> None:
        """Keep the historical command as an alias for the unified Mirror settings tab."""
        self.open_settings(SettingsPage.MIRROR)

    @property
    def mirror_url(self) -> str:
        """Return the endpoint exposed by the application-owned coordinator."""
        return self.mirror_coordinator.state.url

    @property
    def mirror_enabled(self) -> bool:
        """Return the persisted startup preference for compatibility with callers."""
        return self.mirror_coordinator.state.enabled

    @property
    def mirror_port(self) -> int:
        """Return the configured local Mirror port."""
        return self.mirror_coordinator.state.port

    @property
    def mirror_error(self) -> str:
        """Return the latest coordinator-reported startup or cleanup error."""
        return self.mirror_coordinator.state.error

    @pyqtSlot()
    def toggle_mirror_server(self) -> asyncio.Task[None] | None:
        """Schedule the Mirror toggle workflow under the widget owner."""
        return self.mirror_controller.toggle()

    def _schedule_mirror_toggle(self, enabled: bool) -> None:
        """Schedule a Mirror settings request from the presentation signal."""
        self.mirror_controller.schedule_toggle(enabled)

    async def set_mirror_enabled(self, enabled: bool) -> MirrorOperationResult:
        """Delegate the Mirror preference and lifecycle transition to the coordinator."""
        return await self.mirror_controller.set_enabled(enabled)

    def refresh_mirror_settings(self) -> None:
        """Refresh the settings view from a coordinator-owned state snapshot."""
        self.mirror_controller.refresh_settings()

    def mirror_status_text(self) -> str:
        """Return the localized status exposed by the coordinator state."""
        return self.mirror_controller.status_text

    async def start_mirror_server(self) -> MirrorOperationResult:
        """Delegate server startup to the application-owned coordinator."""
        return await self.mirror_controller.start()

    async def stop_mirror_server(self) -> MirrorOperationResult:
        """Disable Mirror through the coordinator and retain the resulting state."""
        return await self.set_mirror_enabled(False)

    async def shutdown_mirror_server(self) -> MirrorOperationResult:
        """Stop the coordinator-owned server during widget shutdown."""
        return await self.mirror_controller.shutdown()

    def _apply_mirror_result(self, result: MirrorOperationResult) -> None:
        """Render coordinator notices through the existing normalized HUD path."""
        self.mirror_controller.apply_result(result)

    def set_live_status_indicator(self, is_live: bool):
        """显示或隐藏标题栏直播状态点。"""
        self.live_status_dot.setVisible(is_live)

    def open_qr_login(self):
        """Open the QR-login window without blocking the application event loop."""
        self.account_surface_controller.open_qr_login()

    def on_login_success(self) -> None:
        """Record QR-login success, then resolve the new account identity."""
        self.application.account_controller.mark_login_succeeded()
        self.tray_icon.showMessage(
            "登录成功",
            "B站账号已登录，将在下次连接时生效。",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
        self.add_system_message("登录成功！请断开并重新连接以应用新的登录信息。")

    def on_login_failed(self, message: str) -> None:
        """Mark the shared account as expired when a HUD session reports failure."""
        self.application.account_controller.mark_login_expired()
        self.tray_icon.showMessage(
            "登录失效",
            message,
            QSystemTrayIcon.MessageIcon.Warning,
            5000
        )
        self.add_system_message(message, SystemMessageLevel.ERROR)

    @pyqtSlot()
    def logout_account(self) -> asyncio.Task[None] | None:
        """Schedule account logout and release all app-owned authenticated sessions."""
        if self._shutting_down:
            return None
        return self._create_action_task(
            self.account_surface_controller.logout(),
            name="logout-account",
        )

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """覆盖关闭事件：最小化到系统托盘，而不是退出程序"""
        if a0 is None:
            return
        a0.ignore()
        self.hide()
        self.update_tray_menu_state()

        # Reminder for user
        self.tray_icon.showMessage(
            "Bilibili Danmaku",
            "程序已最小化到托盘运行",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
