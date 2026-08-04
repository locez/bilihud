"""Modern, cancellable Bilibili QR-login presentation."""

from __future__ import annotations

import asyncio
import logging

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QImage, QMouseEvent, QPixmap, QShowEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.app.lifecycle import TaskScope, TaskSupervisor, cancel_task, run_owned_blocking
from bilihud.auth.service import QR_LOGIN_STATUS_NAMES, AuthenticationService
from bilihud.config.store import ThemeMode
from bilihud.ui.appearance import Appearance, resolve_appearance
from bilihud.ui.settings.style import settings_stylesheet

logger = logging.getLogger(__name__)


def _qr_status_presentation(code: int) -> tuple[str, str]:
    """Map Bilibili QR-login protocol codes to visible text and status level."""
    if code == 86090:
        return "已扫码，请在手机上确认登录", "warning"
    if code == 86101:
        return "请使用哔哩哔哩手机客户端扫码", "info"
    return "登录状态暂时无法确认，正在重试...", "warning"


class QRLoginDialog(QDialog):
    """Display and own the complete Bilibili QR-login workflow."""

    login_success = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        auth_service: AuthenticationService,
        task_scope: TaskScope | None = None,
        appearance: Appearance | None = None,
    ) -> None:
        """Create the login surface without starting network work before it is shown."""
        super().__init__(parent)
        self.setObjectName("qr_login_dialog")
        self.setWindowTitle("扫码登录")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(420, 560)
        self.resize(420, 600)
        self._appearance = appearance if appearance is not None else resolve_appearance(ThemeMode.SYSTEM)
        self.setStyleSheet(
            settings_stylesheet(self._appearance)
            + f"""
                QDialog#qr_login_dialog {{ background: {self._appearance.window}; }}
                QFrame#qr_login_header {{ background: transparent; }}
                QFrame#qr_card {{
                    background: {self._appearance.surface};
                    border: 1px solid {self._appearance.border};
                    border-radius: 8px;
                }}
                QLabel#qr_instruction {{ color: {self._appearance.muted_text}; font-size: 13px; }}
                QLabel#qr_code {{
                    background: #ffffff;
                    border: 1px solid {self._appearance.border};
                    border-radius: 10px;
                    color: {self._appearance.muted_text};
                    font-size: 13px;
                }}
                QLabel#qr_hint {{ color: {self._appearance.muted_text}; font-size: 13px; }}
                QLabel#status_label[level="warning"] {{ color: #d68b35; }}
            """,
        )

        self.auth_service = auth_service
        if task_scope is None:
            task_supervisor = TaskSupervisor()
            self._task_supervisor: TaskSupervisor | None = task_supervisor
            self._owns_task_supervisor = True
            self._task_scope = task_supervisor.create_scope("qr-login")
        else:
            self._task_supervisor = None
            self._owns_task_supervisor = False
            self._task_scope = task_scope

        self.qrcode_key: str | None = None
        self._load_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._refresh_generation = 0
        self._shutting_down = False
        self._shutdown_complete = False
        self._drag_offset: QPoint | None = None
        self._system_dragging = False
        self._drag_targets: tuple[QObject, ...] = ()

        self._init_ui()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(2000)
        self.poll_timer.timeout.connect(self.check_status)

    def _init_ui(self) -> None:
        """Build a focused login surface using the settings window visual language."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        header = QFrame(self)
        header.setObjectName("qr_login_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("扫码登录", header)
        title.setObjectName("page_title")
        subtitle = QLabel("使用 Bilibili 手机客户端登录账号", header)
        subtitle.setObjectName("muted_label")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header_layout.addLayout(heading)
        header_layout.addStretch(1)
        self._drag_targets = (header, title, subtitle)
        for target in self._drag_targets:
            target.installEventFilter(self)
        header.setCursor(Qt.CursorShape.OpenHandCursor)
        root.addWidget(header)

        card = QFrame(self)
        card.setObjectName("qr_card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)
        card_layout.setSpacing(12)

        instruction = QLabel("打开哔哩哔哩手机客户端，扫描下方二维码", card)
        instruction.setObjectName("qr_instruction")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setWordWrap(True)
        card_layout.addWidget(instruction)

        self.qr_label = QLabel("二维码准备中", card)
        self.qr_label.setObjectName("qr_code")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(240, 240)
        self.qr_label.setWordWrap(True)
        card_layout.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("正在获取二维码...", card)
        self.status_label.setObjectName("status_label")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        hint = QLabel("二维码仅用于本次登录，登录凭证会保存到系统安全存储。", card)
        hint.setObjectName("qr_hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        card_layout.addWidget(hint)
        root.addWidget(card)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(9)
        actions.addStretch(1)
        self.refresh_btn = QPushButton("刷新二维码", self)
        self.refresh_btn.setObjectName("qr_refresh")
        self.refresh_btn.setProperty("accent", True)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setVisible(False)
        self.refresh_btn.clicked.connect(self.refresh_qrcode)
        actions.addWidget(self.refresh_btn)
        close_button_bottom = QPushButton("取消", self)
        close_button_bottom.clicked.connect(self.reject)
        actions.addWidget(close_button_bottom)
        root.addLayout(actions)

    # PyQt6 stubs name override parameters a0/a1; matching them keeps ty's override check sound.
    def showEvent(self, a0: QShowEvent | None) -> None:
        """Request a fresh login code each time the dialog becomes visible."""
        super().showEvent(a0)
        if not self._shutting_down:
            self.refresh_qrcode()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Stop polling and cancel in-flight requests before the dialog closes."""
        self.poll_timer.stop()
        self._refresh_generation += 1
        self.qrcode_key = None
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
        super().closeEvent(a0)

    async def shutdown(self) -> None:
        """Cancel QR requests and release the dialog-owned task supervisor."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        self.poll_timer.stop()
        self._refresh_generation += 1
        self.qrcode_key = None
        await cancel_task(self._load_task)
        await cancel_task(self._poll_task)
        try:
            await self._task_scope.cancel_all()
        finally:
            if self._owns_task_supervisor and self._task_supervisor is not None:
                await self._task_supervisor.shutdown()
        self._shutdown_complete = True

    def refresh_qrcode(self) -> None:
        """Cancel stale login work and request one fresh QR code."""
        if self._shutting_down:
            return
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._set_status("正在获取二维码...", level="info")
        self.qr_label.setText("二维码准备中")
        self.qr_label.clearFocus()
        self.refresh_btn.setVisible(False)
        self.refresh_btn.setEnabled(False)
        self.poll_timer.stop()
        self.qrcode_key = None
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
        self._load_task = self._task_scope.create_task(
            self._load_qrcode(generation),
            name="load-qrcode",
        )

    async def _load_qrcode(self, generation: int) -> None:
        """Fetch, render, and activate polling for one current QR code."""
        try:
            url, key = await self.auth_service.get_qrcode()
            if not self._is_current_generation(generation):
                return
            if not url or not key:
                self._show_qr_failure("无法获取二维码，请检查网络后重试。")
                return

            image_bytes = await run_owned_blocking(
                lambda: self.auth_service.generate_qr_image(url),
                thread_name="bilihud-qr",
            )
            if not self._is_current_generation(generation):
                return
            if image_bytes is None:
                self._show_qr_failure("二维码生成失败，请重试。")
                return

            image = QImage.fromData(image_bytes.getvalue())
            if image.isNull():
                self._show_qr_failure("二维码图像无效，请重试。")
                return
            self.qr_label.setText("")
            self.qr_label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    224,
                    224,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.qrcode_key = key
            self._set_status("请使用哔哩哔哩手机客户端扫码", level="info")
            self.poll_timer.start()
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.warning("Failed to load QR login code: %s", exc)
            if self._is_current_generation(generation):
                self._show_qr_failure("获取二维码失败，请检查网络后重试。")

    def check_status(self) -> None:
        """Schedule one owned status poll while the current code is active."""
        key = self.qrcode_key
        if not key or self._shutting_down:
            return
        if self._poll_task is not None and not self._poll_task.done():
            return
        self._poll_task = self._task_scope.create_task(
            self._poll_status(key),
            name="poll-qrcode",
        )

    async def _poll_status(self, qrcode_key: str) -> None:
        """Render protocol states and persist cookies only after a real success."""
        try:
            code, message, cookies = await self.auth_service.poll_status(qrcode_key)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.warning("Failed to poll QR login status: %s", exc)
            if qrcode_key == self.qrcode_key:
                self._set_status("网络暂时不可用，正在重试...", level="warning")
            return

        if qrcode_key != self.qrcode_key or self._shutting_down:
            return
        status_name = QR_LOGIN_STATUS_NAMES.get(code, "Unknown")
        logger.info("QR login poll status: code=%s (%s), message=%s", code, status_name, message)

        if code == 0:
            if not cookies:
                self.poll_timer.stop()
                self._show_qr_failure("登录未返回有效会话，请刷新二维码后重试。")
                return
            if not self.auth_service.save_cookies(cookies):
                self.poll_timer.stop()
                self._show_qr_failure("登录成功，但凭证保存失败，请重试。")
                return
            self._set_status("登录成功", level="success")
            self.poll_timer.stop()
            self.login_success.emit()
            self.accept()
        elif code in (86101, 86090):
            status_text, status_level = _qr_status_presentation(code)
            self._set_status(status_text, level=status_level)
        elif code == 86038:
            self.poll_timer.stop()
            self._show_qr_failure("二维码已过期，请刷新后重试。")
        else:
            status_text, status_level = _qr_status_presentation(code)
            self._set_status(status_text, level=status_level)

    def _set_status(self, text: str, *, level: str) -> None:
        """Set one status label and refresh its stylesheet property."""
        self.status_label.setText(text)
        self.status_label.setProperty("level", level)
        style = self.status_label.style()
        if style is not None:
            style.unpolish(self.status_label)
            style.polish(self.status_label)

    def _show_qr_failure(self, message: str) -> None:
        """Render a recoverable QR error without leaving stale login imagery visible."""
        self.qrcode_key = None
        self.qr_label.clear()
        self.qr_label.setText("二维码暂不可用")
        self._set_status(message, level="error")
        self.refresh_btn.setVisible(True)
        self.refresh_btn.setEnabled(True)

    def _is_current_generation(self, generation: int) -> bool:
        """Return whether an async result still belongs to the visible QR request."""
        return generation == self._refresh_generation and not self._shutting_down

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Allow the header to move this frameless dialog without blocking its close button."""
        if a0 in self._drag_targets and isinstance(a1, QMouseEvent):
            if a1.type() is QEvent.Type.MouseButtonPress and a1.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = None
                window_handle = self.windowHandle()
                self._system_dragging = window_handle is not None and window_handle.startSystemMove()
                if not self._system_dragging:
                    self._drag_offset = a1.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if a1.type() is QEvent.Type.MouseMove and self._system_dragging:
                return True
            if a1.type() is QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(a1.globalPosition().toPoint() - self._drag_offset)
                return True
            if a1.type() is QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                self._system_dragging = False
                return True
        return super().eventFilter(a0, a1)


__all__ = ("QRLoginDialog",)
