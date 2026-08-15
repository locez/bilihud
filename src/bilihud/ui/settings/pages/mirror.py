"""Display and effect settings page used by the unified settings window."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QClipboard, QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.app.mirror_coordinator import MirrorCoordinatorState
from bilihud.config.store import (
    DEFAULT_HUD_FONT_FAMILY,
    DEFAULT_MIRROR_DANMAKU_X,
    DEFAULT_MIRROR_DANMAKU_Y,
    AppConfig,
)
from bilihud.ui.settings.style import ModernComboBox, ModernSpinBox


class MirrorSettingsPage(QWidget):
    """Present browser, desktop, and shared HUD display settings."""

    enabled_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the embedded Mirror form without owning the server lifecycle."""
        super().__init__(parent)
        self._state: MirrorCoordinatorState | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)

        browser_card = QFrame(self)
        browser_card.setObjectName("card")
        browser_layout = QVBoxLayout(browser_card)
        browser_layout.setContentsMargins(18, 16, 18, 18)
        browser_layout.setSpacing(14)

        title = QLabel("浏览器同步", browser_card)
        title.setObjectName("card_title")
        browser_layout.addWidget(title)

        self.enabled_checkbox = QCheckBox("启用 BiliHUD Mirror", browser_card)
        self.enabled_checkbox.setObjectName("mirror_enabled")
        self.enabled_checkbox.toggled.connect(self.enabled_requested.emit)
        browser_layout.addWidget(self.enabled_checkbox)

        self.mirror_gift_effects_checkbox = QCheckBox("Mirror 礼物特效", browser_card)
        self.mirror_gift_effects_checkbox.setObjectName("mirror_gift_effects")
        browser_layout.addWidget(self.mirror_gift_effects_checkbox)

        self.status_label = QLabel("未启动", browser_card)
        self.status_label.setObjectName("status_label")
        browser_layout.addWidget(self.status_label)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.url_input = QLineEdit(browser_card)
        self.url_input.setObjectName("mirror_url")
        self.url_input.setReadOnly(True)
        self.url_input.setCursorPosition(0)
        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.addWidget(self.url_input, 1)
        self.copy_button = QPushButton("复制 URL", browser_card)
        self.copy_button.clicked.connect(self.copy_url)
        url_row.addWidget(self.copy_button)
        form.addRow("访问地址", url_row)

        self.danmaku_x_spinbox = ModernSpinBox(browser_card)
        self.danmaku_x_spinbox.setObjectName("mirror_danmaku_x")
        self.danmaku_x_spinbox.setRange(0, 100)
        self.danmaku_x_spinbox.setSuffix(" %")
        self.danmaku_y_spinbox = ModernSpinBox(browser_card)
        self.danmaku_y_spinbox.setObjectName("mirror_danmaku_y")
        self.danmaku_y_spinbox.setRange(0, 100)
        self.danmaku_y_spinbox.setSuffix(" %")
        form.addRow("弹幕左侧位置", self.danmaku_x_spinbox)
        form.addRow("弹幕顶部位置", self.danmaku_y_spinbox)
        browser_layout.addLayout(form)

        hint = QLabel("Mirror 页面会铺满浏览器源；弹幕位置和 Mirror 内礼物特效可单独控制。", browser_card)
        hint.setObjectName("muted_label")
        hint.setWordWrap(True)
        browser_layout.addWidget(hint)

        desktop_card = QFrame(self)
        desktop_card.setObjectName("card")
        desktop_layout = QVBoxLayout(desktop_card)
        desktop_layout.setContentsMargins(18, 16, 18, 18)
        desktop_layout.setSpacing(12)

        desktop_title = QLabel("桌面显示", desktop_card)
        desktop_title.setObjectName("card_title")
        desktop_layout.addWidget(desktop_title)

        self.overlay_gift_effects_checkbox = QCheckBox("桌面全屏礼物特效", desktop_card)
        self.overlay_gift_effects_checkbox.setObjectName("overlay_gift_effects")
        desktop_layout.addWidget(self.overlay_gift_effects_checkbox)

        desktop_hint = QLabel("在主播桌面上播放全屏穿透动画，不影响浏览器源中的 Mirror 特效。", desktop_card)
        desktop_hint.setObjectName("muted_label")
        desktop_hint.setWordWrap(True)
        desktop_layout.addWidget(desktop_hint)

        font_card = QFrame(self)
        font_card.setObjectName("card")
        font_layout = QVBoxLayout(font_card)
        font_layout.setContentsMargins(18, 16, 18, 18)
        font_layout.setSpacing(12)

        font_title = QLabel("HUD 字体", font_card)
        font_title.setObjectName("card_title")
        font_layout.addWidget(font_title)

        font_form = QFormLayout()
        font_form.setHorizontalSpacing(18)
        font_form.setVerticalSpacing(10)
        self.font_family_combo = ModernComboBox(font_card)
        self.font_family_combo.setObjectName("hud_font_family")
        self.font_family_combo.setMinimumWidth(260)
        self.font_family_combo.addItem("系统默认", DEFAULT_HUD_FONT_FAMILY)
        for family in sorted(QFontDatabase.families(), key=str.casefold):
            if family:
                self.font_family_combo.addItem(family, family)
        font_form.addRow("消息字体", self.font_family_combo)
        font_layout.addLayout(font_form)

        font_hint = QLabel("同时应用于桌面 HUD 和 Mirror 浏览器源中的消息文字。", font_card)
        font_hint.setObjectName("muted_label")
        font_hint.setWordWrap(True)
        font_layout.addWidget(font_hint)

        layout.addWidget(browser_card)
        layout.addWidget(desktop_card)
        layout.addWidget(font_card)
        layout.addStretch(1)

    def set_state(self, state: MirrorCoordinatorState) -> None:
        """Render one coordinator-owned Mirror snapshot."""
        self._state = state
        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(state.enabled)
        self.enabled_checkbox.blockSignals(False)
        self.status_label.setText(state.status_text)
        self.url_input.setText(state.url)
        self.url_input.setCursorPosition(0)

    def set_config(self, config: AppConfig) -> None:
        """Render the persisted Mirror display and effect preferences."""
        self.mirror_gift_effects_checkbox.setChecked(config.mirror_gift_effects_enabled)
        self.overlay_gift_effects_checkbox.setChecked(config.overlay_gift_effects_enabled)
        font_index = self.font_family_combo.findData(config.hud_font_family)
        self.font_family_combo.setCurrentIndex(font_index if font_index >= 0 else 0)
        self.danmaku_x_spinbox.setValue(config.mirror_danmaku_x)
        self.danmaku_y_spinbox.setValue(config.mirror_danmaku_y)

    def config_values(self) -> tuple[bool, bool, str, int, int]:
        """Return the editable display values for the settings save contract."""
        font_value = self.font_family_combo.currentData()
        font_family = font_value if isinstance(font_value, str) else DEFAULT_HUD_FONT_FAMILY
        return (
            self.mirror_gift_effects_checkbox.isChecked(),
            self.overlay_gift_effects_checkbox.isChecked(),
            font_family,
            self.danmaku_x_spinbox.value(),
            self.danmaku_y_spinbox.value(),
        )

    def reset_config(self) -> None:
        """Restore display switches, the system font, and the default browser position."""
        self.mirror_gift_effects_checkbox.setChecked(False)
        self.overlay_gift_effects_checkbox.setChecked(False)
        self.font_family_combo.setCurrentIndex(0)
        self.danmaku_x_spinbox.setValue(DEFAULT_MIRROR_DANMAKU_X)
        self.danmaku_y_spinbox.setValue(DEFAULT_MIRROR_DANMAKU_Y)

    def set_status_text(self, status: str) -> None:
        """Update only the status text while the owning coordinator state is unchanged."""
        self.status_label.setText(status)

    def copy_url(self) -> None:
        """Copy the currently rendered Mirror endpoint to the desktop clipboard."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.url_input.text(), mode=QClipboard.Mode.Clipboard)
            self.status_label.setText("URL 已复制")


__all__ = ("MirrorSettingsPage",)
