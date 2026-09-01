"""Modern sidebar settings window for presentation-owned application preferences."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent, QRegion, QResizeEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.app.lifecycle import TaskScope
from bilihud.app.menu import AccountStatus
from bilihud.app.mirror_coordinator import MirrorCoordinatorState
from bilihud.app.services import ApplicationServices
from bilihud.auth.service import AccountProfile
from bilihud.config.store import (
    DEFAULT_WINDOW_OPACITY,
    MAX_WINDOW_OPACITY,
    MIN_WINDOW_OPACITY,
    AppConfig,
    ThemeMode,
)
from bilihud.danmaku.mock import mock_gift_effect_options
from bilihud.ui.appearance import Appearance, resolve_appearance
from bilihud.ui.settings.models import PAGE_DEFINITIONS as _PAGE_DEFINITIONS
from bilihud.ui.settings.models import SettingsPage, SettingsSaveRequest
from bilihud.ui.settings.pages.about import AboutSettingsPage
from bilihud.ui.settings.pages.account import AccountSettingsPage
from bilihud.ui.settings.pages.live.page import LiveSettingsPage
from bilihud.ui.settings.pages.live.workflow import LiveStartedHandler
from bilihud.ui.settings.pages.mirror import MirrorSettingsPage
from bilihud.ui.settings.stack import AdaptiveStackedWidget
from bilihud.ui.settings.style import ModernComboBox, ModernSpinBox, settings_stylesheet


class SettingsDialog(QDialog):
    """Render one frameless settings surface with embedded feature pages."""

    _DRAG_REGION_HEIGHT = 92
    _CLOSE_REGION_WIDTH = 48
    _CLOSE_BUTTON_SIZE = 32
    _CLOSE_BUTTON_MARGIN = 8
    _SIDEBAR_WIDTH = 188
    _SIDEBAR_DRAG_HEIGHT = _DRAG_REGION_HEIGHT

    settings_requested = pyqtSignal(object)
    mirror_enabled_requested = pyqtSignal(bool)
    live_status_changed = pyqtSignal(bool)
    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    simulation_requested = pyqtSignal()
    gift_effect_simulation_requested = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget | None,
        config: AppConfig,
        *,
        services: ApplicationServices | None = None,
        task_scope: TaskScope | None = None,
        on_live_started: LiveStartedHandler | None = None,
    ) -> None:
        """Create a reusable settings window with explicitly injected feature owners."""
        super().__init__(parent)
        self._config_snapshot = config
        self._active_page = SettingsPage.GENERAL
        self._services = services
        self._task_scope = task_scope
        self._on_live_started = on_live_started
        self._live_page: LiveSettingsPage | None = None
        self._mirror_page: MirrorSettingsPage | None = None
        self._account_page: AccountSettingsPage | None = None
        self._header_frame: QFrame | None = None
        self._close_button: QToolButton | None = None
        self._header_drag_targets: tuple[QObject, ...] = ()
        self._drag_overlay: QWidget | None = None
        self._drag_offset: QPoint | None = None
        self._system_dragging = False
        self.opacity_error_label: QLabel | None = None
        self.simulation_button: QPushButton | None = None
        self.gift_effect_combo: ModernComboBox | None = None
        self.setWindowTitle("BiliHUD 设置")
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(760, 540)
        self.resize(900, 620)
        self._init_ui()
        self.set_config(config)

    def _init_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(188)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 14, 18)
        sidebar_layout.setSpacing(18)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        brand_icon = QLabel()
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
        brand_icon.setPixmap(QIcon(str(icon_path)).pixmap(28, 28))
        brand_row.addWidget(brand_icon)
        brand_label = QLabel("BiliHUD 设置")
        brand_label.setObjectName("brand_label")
        brand_row.addWidget(brand_label)
        brand_row.addStretch(1)
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(self._DRAG_REGION_HEIGHT - 68)

        self.navigation = QListWidget(sidebar)
        self.navigation.setObjectName("navigation")
        self.navigation.setSpacing(3)
        self.navigation.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for _page, label, _title in _PAGE_DEFINITIONS:
            self.navigation.addItem(label)
        self.navigation.currentRowChanged.connect(self._change_page)
        sidebar_layout.addWidget(self.navigation, 1)

        sidebar_note = QLabel("BiliHUD\nSettings")
        sidebar_note.setObjectName("sidebar_note")
        sidebar_layout.addWidget(sidebar_note)
        root.addWidget(sidebar)

        content = QFrame(self)
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 18, 12, 0)
        content_layout.setSpacing(16)

        header_frame = QFrame(content)
        header_frame.setObjectName("settings_header")
        header_frame.installEventFilter(self)
        self._header_frame = header_frame
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.page_title = QLabel()
        self.page_title.setObjectName("page_title")
        self.page_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        heading.addWidget(self.page_title)
        header.addLayout(heading)
        header.addStretch(1)
        close_button = QToolButton(self)
        close_button.setObjectName("window_close")
        close_button.setText("×")
        close_button.setFixedSize(self._CLOSE_BUTTON_SIZE, self._CLOSE_BUTTON_SIZE)
        close_button.setToolTip("关闭设置")
        close_button.clicked.connect(self.close)
        self._close_button = close_button
        self._header_drag_targets = (header_frame, self.page_title)
        for target in self._header_drag_targets:
            target.installEventFilter(self)
        header_frame.setCursor(Qt.CursorShape.OpenHandCursor)
        content_layout.addWidget(header_frame)

        self.page_stack = AdaptiveStackedWidget(content)
        self.page_stack.setObjectName("page_stack")
        self._pages: tuple[QWidget, ...] = (
            self._create_general_page(),
            self._create_panel_page(),
            self._create_live_page(),
            self._create_mirror_page(),
            self._create_account_page(),
            self._create_about_page(),
            self._create_developer_page(),
        )
        for page in self._pages:
            self.page_stack.addWidget(page)

        scroll = QScrollArea(content)
        scroll.setObjectName("page_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.page_stack)
        self.page_scroll = scroll
        content_layout.addWidget(scroll, 1)

        action_bar = QFrame(content)
        action_bar.setObjectName("action_bar")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 14, 0, 14)
        action_layout.setSpacing(9)
        self.reset_button = QPushButton("重置本页", action_bar)
        self.reset_button.clicked.connect(self._reset_current_page)
        action_layout.addWidget(self.reset_button)
        self.feedback_label = QLabel(action_bar)
        self.feedback_label.setObjectName("feedback_label")
        action_layout.addWidget(self.feedback_label)
        action_layout.addStretch(1)
        self.cancel_button = QPushButton("取消", action_bar)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = QPushButton("应用", action_bar)
        self.apply_button.clicked.connect(lambda: self._request_save(False))
        self.ok_button = QPushButton("确定", action_bar)
        self.ok_button.setProperty("accent", True)
        self.ok_button.clicked.connect(lambda: self._request_save(True))
        action_layout.addWidget(self.cancel_button)
        action_layout.addWidget(self.apply_button)
        action_layout.addWidget(self.ok_button)
        content_layout.addWidget(action_bar)
        root.addWidget(content, 1)

        drag_overlay = QWidget(self)
        drag_overlay.setObjectName("window_drag_region")
        drag_overlay.installEventFilter(self)
        drag_overlay.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_overlay = drag_overlay
        self._header_drag_targets = (header_frame, self.page_title, drag_overlay)
        drag_overlay.raise_()
        self._update_drag_region()

        self.navigation.setCurrentRow(0)

    def _create_general_page(self) -> QWidget:
        page = self._new_page()
        card, layout = self._new_card("外观", "")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        self.language_combo = ModernComboBox(card)
        self.language_combo.addItem("简体中文")
        self.language_combo.setEnabled(False)
        self.theme_combo = ModernComboBox(card)
        self.theme_combo.addItem("跟随系统", ThemeMode.SYSTEM)
        self.theme_combo.addItem("浅色", ThemeMode.LIGHT)
        self.theme_combo.addItem("深色", ThemeMode.DARK)
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        form.addRow("语言", self.language_combo)
        form.addRow("主题", self.theme_combo)
        layout.addLayout(form)
        page_layout = self._page_layout(page)
        page_layout.addWidget(card)
        page_layout.addStretch(1)
        return page

    def _create_panel_page(self) -> QWidget:
        page = self._new_page()
        card, layout = self._new_card("HUD 外观", "")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        self.opacity_spinbox = ModernSpinBox(card)
        self.opacity_spinbox.setRange(0, MAX_WINDOW_OPACITY)
        self.opacity_spinbox.setSuffix(" %")
        self.opacity_spinbox.setSingleStep(5)
        self.opacity_spinbox.editingFinished.connect(self._validate_opacity)
        form.addRow("HUD 背景不透明度", self.opacity_spinbox)
        layout.addLayout(form)
        self.opacity_error_label = QLabel(card)
        self.opacity_error_label.setObjectName("field_error")
        self.opacity_error_label.setWordWrap(True)
        self.opacity_error_label.setVisible(False)
        layout.addWidget(self.opacity_error_label)
        page_layout = self._page_layout(page)
        page_layout.addWidget(card)
        page_layout.addStretch(1)
        return page

    def _create_live_page(self) -> QWidget:
        service = None if self._services is None else self._services.live_control_service
        task_scope = None if self._task_scope is None else self._task_scope.child("live-settings")
        page = LiveSettingsPage(
            self.page_stack,
            service=service,
            task_scope=task_scope,
            on_live_started=self._on_live_started,
        )
        page.setObjectName("settings_page")
        page.live_status_changed.connect(self.live_status_changed.emit)
        self._live_page = page
        return page

    def _create_mirror_page(self) -> QWidget:
        page = MirrorSettingsPage(self.page_stack)
        page.setObjectName("settings_page")
        page.enabled_requested.connect(self.mirror_enabled_requested.emit)
        self._mirror_page = page
        return page

    def _create_account_page(self) -> QWidget:
        page = AccountSettingsPage(self.page_stack)
        page.login_requested.connect(self.login_requested.emit)
        page.logout_requested.connect(self.logout_requested.emit)
        self._account_page = page
        return page

    def _create_about_page(self) -> QWidget:
        page = AboutSettingsPage(self.page_stack)
        page.setObjectName("settings_page")
        return page

    def _create_developer_page(self) -> QWidget:
        page = self._new_page()
        card, layout = self._new_card("开发工具", "")
        description = QLabel("用于验证消息渲染和界面状态的本地工具。", card)
        description.setObjectName("muted_label")
        self.simulation_button = QPushButton("弹幕模拟", card)
        self.simulation_button.clicked.connect(self.simulation_requested.emit)
        effect_row = QHBoxLayout()
        effect_label = QLabel("高级礼物特效", card)
        self.gift_effect_combo = ModernComboBox(card)
        self.gift_effect_combo.setObjectName("gift_effect_simulation")
        self.gift_effect_combo.setMinimumWidth(220)
        self.gift_effect_combo.setToolTip("选择后立即注入一条对应的测试礼物")
        self.gift_effect_combo.addItem("选择测试礼物", "")
        for option in mock_gift_effect_options():
            self.gift_effect_combo.addItem(option.title, option.effect_id.value)
        self.gift_effect_combo.currentIndexChanged.connect(self._on_gift_effect_simulation_changed)
        effect_row.addWidget(effect_label)
        effect_row.addWidget(self.gift_effect_combo, 1)
        layout.addWidget(description)
        layout.addWidget(self.simulation_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(effect_row)
        page_layout = self._page_layout(page)
        page_layout.addWidget(card)
        page_layout.addStretch(1)
        return page

    def _on_gift_effect_simulation_changed(self, index: int) -> None:
        """Emit one selected fixture and reset the picker for repeatable checks."""
        combo = self.gift_effect_combo
        if combo is None or index <= 0:
            return
        effect_id = combo.itemData(index)
        if not isinstance(effect_id, str) or not effect_id:
            return
        blocker = QSignalBlocker(combo)
        combo.setCurrentIndex(0)
        del blocker
        self.gift_effect_simulation_requested.emit(effect_id)

    def _new_page(self) -> QWidget:
        page = QWidget(self.page_stack)
        page.setObjectName("settings_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)
        return page

    @staticmethod
    def _page_layout(page: QWidget) -> QVBoxLayout:
        """Return the layout created by ``_new_page`` through an explicit type boundary."""
        layout = page.layout()
        if not isinstance(layout, QVBoxLayout):
            raise RuntimeError("设置页布局未初始化")
        return layout

    def _new_card(self, title: str, _description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title_label = QLabel(title, card)
        title_label.setObjectName("card_title")
        layout.addWidget(title_label)
        return card, layout

    def _change_page(self, index: int) -> None:
        if not 0 <= index < len(_PAGE_DEFINITIONS):
            return
        self._active_page = _PAGE_DEFINITIONS[index][0]
        self.page_stack.setCurrentIndex(index)
        self._reset_page_scroll()
        self.page_title.setText(_PAGE_DEFINITIONS[index][2])
        self._clear_feedback_state()

    def _reset_page_scroll(self) -> None:
        """Start each settings page at its title instead of reusing another page's offset."""
        scrollbar = self.page_scroll.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.minimum())

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Allow the frameless window to move from its custom header region."""
        if a0 in self._header_drag_targets and isinstance(a1, QMouseEvent):
            if a1.type() is QEvent.Type.MouseButtonPress and a1.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = None
                window_handle = self.windowHandle()
                self._system_dragging = window_handle is not None and window_handle.startSystemMove()
                if not self._system_dragging:
                    self._drag_offset = a1.globalPosition().toPoint() - self.frameGeometry().topLeft()
                if self._header_frame is not None:
                    self._header_frame.setCursor(Qt.CursorShape.ClosedHandCursor)
                if self._drag_overlay is not None:
                    self._drag_overlay.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if a1.type() is QEvent.Type.MouseMove and self._system_dragging:
                return True
            if a1.type() is QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(a1.globalPosition().toPoint() - self._drag_offset)
                return True
            if a1.type() is QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                self._system_dragging = False
                if self._header_frame is not None:
                    self._header_frame.setCursor(Qt.CursorShape.OpenHandCursor)
                if self._drag_overlay is not None:
                    self._drag_overlay.setCursor(Qt.CursorShape.OpenHandCursor)
                return True
        return super().eventFilter(a0, a1)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        """Keep the top drag region aligned with the frameless window bounds."""
        super().resizeEvent(a0)
        self._update_drag_region()

    def _update_drag_region(self) -> None:
        """Cover the full top chrome while leaving the close-button column interactive."""
        overlay = self._drag_overlay
        if overlay is None:
            return
        window_width = max(0, self.width() - self._CLOSE_REGION_WIDTH)
        drag_height = min(self._DRAG_REGION_HEIGHT, self.height())
        overlay.setGeometry(0, 0, window_width, drag_height)
        content_width = max(0, window_width - self._SIDEBAR_WIDTH)
        sidebar_height = min(self._SIDEBAR_DRAG_HEIGHT, drag_height)
        mask = QRegion(QRect(0, 0, self._SIDEBAR_WIDTH, sidebar_height))
        if content_width > 0:
            mask |= QRegion(QRect(self._SIDEBAR_WIDTH, 0, content_width, drag_height))
        overlay.setMask(mask)
        close_button = self._close_button
        if close_button is not None:
            close_button.setGeometry(
                max(0, self.width() - self._CLOSE_BUTTON_SIZE - self._CLOSE_BUTTON_MARGIN),
                self._CLOSE_BUTTON_MARGIN,
                self._CLOSE_BUTTON_SIZE,
                self._CLOSE_BUTTON_SIZE,
            )
            close_button.raise_()

    def select_page(self, page: SettingsPage) -> None:
        """Select a detail page without opening a second settings implementation."""
        for index, definition in enumerate(_PAGE_DEFINITIONS):
            if definition[0] is page:
                already_selected = self.navigation.currentRow() == index
                self.navigation.setCurrentRow(index)
                if already_selected:
                    self._change_page(index)
                return

    def set_config(self, config: AppConfig) -> None:
        """Refresh editable controls from the owning configuration snapshot."""
        self._config_snapshot = config
        theme_index = self.theme_combo.findData(config.theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.theme_combo.blockSignals(False)
        self.opacity_spinbox.setValue(config.window_opacity)
        if self._mirror_page is not None:
            self._mirror_page.set_config(config)
        self._clear_feedback_state()
        self._preview_theme()

    def set_mirror_status(self, status: str) -> None:
        """Render a status update supplied by the lifecycle-owning coordinator."""
        if self._mirror_page is not None:
            self._mirror_page.set_status_text(status)

    def set_mirror_state(self, state: MirrorCoordinatorState) -> None:
        """Bind a typed Mirror coordinator snapshot to the embedded page."""
        if self._mirror_page is None:
            return
        self._mirror_page.set_state(state)

    def refresh_live_state(self) -> None:
        """Refresh the embedded live page after an account session transition."""
        if self._live_page is not None and self._services is not None:
            self._live_page.apply_service_state(self._services.live_control_service.state)

    async def shutdown(self) -> None:
        """Stop embedded asynchronous feature work before application shutdown."""
        if self._live_page is not None:
            await self._live_page.shutdown()

    def set_account_state(self, status: AccountStatus, profile: AccountProfile | None) -> None:
        """Render normalized account identity through the embedded account page."""
        if self._account_page is not None:
            self._account_page.set_account_state(status, profile)

    def report_save_result(self, request: SettingsSaveRequest, success: bool, message: str = "") -> None:
        """Complete one save request after the application owner reports its result."""
        if not success:
            self.feedback_label.setText(message or "设置保存失败")
            return
        self._config_snapshot = request.config
        self.feedback_label.setText("已应用")
        if request.close_after_save:
            self.accept()

    def _request_save(self, close_after_save: bool) -> None:
        if not self._validate_opacity():
            return
        request = SettingsSaveRequest(self._current_config(), close_after_save)
        self.settings_requested.emit(request)

    def _validate_opacity(self) -> bool:
        """Reject HUD opacity values that would make the background effectively unusable."""
        value = self.opacity_spinbox.value()
        if MIN_WINDOW_OPACITY <= value <= MAX_WINDOW_OPACITY:
            if self.opacity_error_label is not None:
                self.opacity_error_label.clear()
                self.opacity_error_label.setVisible(False)
            return True
        if self._active_page is not SettingsPage.PANEL:
            self.select_page(SettingsPage.PANEL)
        if self.opacity_error_label is not None:
            self.opacity_error_label.setText("HUD 背景不透明度需在 20% 到 100% 之间")
            self.opacity_error_label.setVisible(True)
        self.opacity_spinbox.setFocus(Qt.FocusReason.OtherFocusReason)
        return False

    def _clear_feedback_state(self) -> None:
        """Clear transient save feedback and inline validation before a fresh view."""
        self.feedback_label.clear()
        if self.opacity_error_label is not None:
            self.opacity_error_label.clear()
            self.opacity_error_label.setVisible(False)

    def _current_config(self) -> AppConfig:
        """Build an immutable application configuration from the visible controls."""
        value = self.theme_combo.currentData()
        theme = value if isinstance(value, ThemeMode) else ThemeMode.SYSTEM
        mirror_page = self._mirror_page
        if mirror_page is None:
            mirror_gift_effects, overlay_gift_effects, show_user_avatars, hud_font_family = (
                self._config_snapshot.mirror_gift_effects_enabled,
                self._config_snapshot.overlay_gift_effects_enabled,
                self._config_snapshot.show_user_avatars,
                self._config_snapshot.hud_font_family,
            )
            danmaku_x = self._config_snapshot.mirror_danmaku_x
            danmaku_y = self._config_snapshot.mirror_danmaku_y
        else:
            (
                mirror_gift_effects,
                overlay_gift_effects,
                show_user_avatars,
                hud_font_family,
                danmaku_x,
                danmaku_y,
            ) = mirror_page.config_values()
        return replace(
            self._config_snapshot,
            theme=theme,
            window_opacity=self.opacity_spinbox.value(),
            mirror_gift_effects_enabled=mirror_gift_effects,
            overlay_gift_effects_enabled=overlay_gift_effects,
            show_user_avatars=show_user_avatars,
            hud_font_family=hud_font_family,
            mirror_danmaku_x=danmaku_x,
            mirror_danmaku_y=danmaku_y,
        )

    def _reset_current_page(self) -> None:
        if self._active_page is SettingsPage.GENERAL:
            self.theme_combo.setCurrentIndex(0)
        elif self._active_page is SettingsPage.PANEL:
            self.opacity_spinbox.setValue(DEFAULT_WINDOW_OPACITY)
        elif self._active_page is SettingsPage.MIRROR and self._mirror_page is not None:
            self._mirror_page.reset_config()
        else:
            self.feedback_label.setText("本页暂无可重置的保存项")

    def _preview_theme(self) -> None:
        value = self.theme_combo.currentData()
        theme = value if isinstance(value, ThemeMode) else ThemeMode.SYSTEM
        self._apply_theme(resolve_appearance(theme))

    def _apply_theme(self, appearance: Appearance) -> None:
        """Apply the restrained light/dark palette to every settings surface."""
        self.setStyleSheet(settings_stylesheet(appearance))


__all__ = ("SettingsDialog", "SettingsPage", "SettingsSaveRequest")
