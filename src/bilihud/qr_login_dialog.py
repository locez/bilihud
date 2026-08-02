import asyncio
import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QDialog, QGraphicsDropShadowEffect, QLabel, QPushButton, QVBoxLayout, QWidget

from .auth import QR_LOGIN_STATUS_NAMES, AuthenticationService
from .lifecycle import TaskScope, TaskSupervisor, cancel_task
from .services import create_default_services

logger = logging.getLogger(__name__)


class QRLoginDialog(QDialog):
    """Display the Bilibili QR-login flow through an injected auth service."""

    login_success = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        auth_service: AuthenticationService | None = None,
        task_scope: TaskScope | None = None,
    ) -> None:
        """Create the dialog and start polling only after it becomes visible."""
        super().__init__(parent)
        self.setWindowTitle("扫码登录 Bilibili")
        self.setFixedSize(320, 400)

        # Modern window styling
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.auth_service = (  # Shared authentication boundary supplied by the app.
            auth_service if auth_service is not None else create_default_services().auth_service
        )
        if task_scope is None:
            task_supervisor = TaskSupervisor()
            self._task_supervisor: TaskSupervisor | None = task_supervisor
            self._owns_task_supervisor = True
            self._task_scope = task_supervisor.create_scope("qr-login")
        else:
            self._task_supervisor = None
            self._owns_task_supervisor = False
            self._task_scope = task_scope
        self.qrcode_key: str | None = None  # Key associated with the currently displayed QR code.
        self._load_task: asyncio.Task[None] | None = None  # Current QR image request.
        self._poll_task: asyncio.Task[None] | None = None  # Current QR status request.
        self._shutting_down = False  # Prevent new requests after application shutdown.
        self._shutdown_complete = False  # Makes application shutdown idempotent.

        self.init_ui()

        # Timer for polling
        self.poll_timer = QTimer(self)  # Owned by the dialog and stopped on close.
        self.poll_timer.setInterval(2000) # Poll every 2 seconds
        self.poll_timer.timeout.connect(self.check_status)

    def init_ui(self):
        """Build the frameless QR-login presentation and its status controls."""
        # Main layout with background container
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                border-radius: 12px;
                border: 1px solid #3d3d3d;
            }
        """)

        # Add shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel("扫码登录")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #ffffff;
            font-family: 'Microsoft YaHei';
        """)
        layout.addWidget(title_label)

        # QR Code Display
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setStyleSheet("background-color: white; border-radius: 4px;")
        layout.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Status Label
        self.status_label = QLabel("正在加载二维码...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            font-size: 14px;
            color: #aaaaaa;
            font-family: 'Microsoft YaHei';
        """)
        layout.addWidget(self.status_label)

        # Refresh Button
        self.refresh_btn = QPushButton("刷新二维码")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setVisible(False)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #00a1d6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #00b5e5;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_qrcode)
        layout.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # Close Button
        close_btn = QPushButton("取消")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #ffffff;
                text-decoration: underline;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self.container)

    def showEvent(self, event):
        """Refresh the QR code whenever the dialog is shown."""
        super().showEvent(event)
        if self._shutting_down:
            return
        self.refresh_qrcode()

    def closeEvent(self, event):
        """Stop status polling before the dialog is destroyed or hidden."""
        self.poll_timer.stop()
        self.qrcode_key = None
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
        super().closeEvent(event)

    async def shutdown(self) -> None:
        """Cancel QR requests and await their completion before application exit."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        self.poll_timer.stop()
        self.qrcode_key = None
        await cancel_task(self._load_task)
        await cancel_task(self._poll_task)
        try:
            await self._task_scope.cancel_all()
        finally:
            if self._owns_task_supervisor and self._task_supervisor is not None:
                await self._task_supervisor.shutdown()
        self._shutdown_complete = True

    def refresh_qrcode(self):
        """Start one asynchronous QR-code request and reset stale polling state."""
        if self._shutting_down:
            return
        self.status_label.setText("正在获取二维码...")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.refresh_btn.setVisible(False)
        self.poll_timer.stop()
        self.qrcode_key = None
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()

        self._load_task = self._task_scope.create_task(self._load_qrcode(), name="load-qrcode")

    async def _load_qrcode(self):
        """Fetch a QR URL, render it, and start polling after a successful render."""
        url, key = await self.auth_service.get_qrcode()
        if url and key:
            self.qrcode_key = key

            # Generate Image
            # Note: generate_qr_image is synchronous but fast
            loop = asyncio.get_event_loop()
            bio = await loop.run_in_executor(None, self.auth_service.generate_qr_image, url)

            if bio:
                top_img = QImage.fromData(bio.getvalue())
                pixmap = QPixmap.fromImage(top_img)
                self.qr_label.setPixmap(
                    pixmap.scaled(
                        180,
                        180,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.status_label.setText("请使用 哔哩哔哩手机客户端 扫码")
                self.poll_timer.start()
            else:
                self.status_label.setText("生成二维码失败")
                self.refresh_btn.setVisible(True)
        else:
            self.status_label.setText("无法连接到服务器")
            self.refresh_btn.setVisible(True)

    def check_status(self):
        """Schedule one status poll when a QR-login key is available."""
        if not self.qrcode_key or self._shutting_down:
            return
        if self._poll_task is not None and not self._poll_task.done():
            return
        self._poll_task = self._task_scope.create_task(
            self._poll_status(self.qrcode_key),
            name="poll-qrcode",
        )

    async def _poll_status(self, qrcode_key: str) -> None:
        """Persist cookies after successful scanning and update visible failure states."""
        code, msg, cookies = await self.auth_service.poll_status(qrcode_key)
        status_name = QR_LOGIN_STATUS_NAMES.get(code, "Unknown")
        logger.info("QR login poll status: code=%s (%s), message=%s", code, status_name, msg)

        if code == 0:
            # Success
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self.poll_timer.stop()

            # Save cookies
            if cookies:
                self.auth_service.save_cookies(cookies)
                self.login_success.emit()
                self.accept()

        elif code == 86101:
            # Scanned
            # User requested to keep text fixed and avoid "false positive" updates
            # self.status_label.setText("扫描成功，请在手机上确认")
            # self.status_label.setStyleSheet("color: #ff9800;")
            pass

        elif code == 86038:
            # Expired
            self.status_label.setText("二维码已过期")
            self.status_label.setStyleSheet("color: #ff5555;")
            self.poll_timer.stop()
            self.refresh_btn.setVisible(True)

        elif code == 86090:
            # Not scanned yet, do nothing
            pass

        else:
            # Other error
            pass

    # Support dragging the frameless window
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
