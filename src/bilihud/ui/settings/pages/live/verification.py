"""Live-control verification dialog shared by QR and face-auth outcomes."""

from __future__ import annotations

from io import BytesIO

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from bilihud.live.models import LiveVerificationKind


class LiveVerificationDialog(QDialog):
    """Render one non-blocking live verification request in the settings visual language."""

    def __init__(
        self,
        parent: QWidget,
        url: str,
        kind: LiveVerificationKind,
        image_bytes: BytesIO | None,
    ) -> None:
        """Create a frameless verification card without owning network work."""
        super().__init__(parent)
        is_face_auth = kind is LiveVerificationKind.FACE
        self.setObjectName("verification_dialog")
        self.setWindowTitle("人脸认证" if is_face_auth else "开播验证")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(420, 540)
        self.resize(420, 580)
        self._drag_offset: QPoint | None = None
        self._system_dragging = False
        self._drag_targets: tuple[QObject, ...] = ()
        self._init_ui(url, is_face_auth, image_bytes)

    def _init_ui(self, url: str, is_face_auth: bool, image_bytes: BytesIO | None) -> None:
        """Build the title region, QR card, and explicit recovery action."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        header = QFrame(self)
        header.setObjectName("verification_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("人脸认证" if is_face_auth else "开播验证", header)
        title.setObjectName("page_title")
        subtitle = QLabel("开播前安全验证", header)
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
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(12)
        card_title = QLabel("扫码完成认证" if is_face_auth else "扫码完成验证", card)
        card_title.setObjectName("card_title")
        card_layout.addWidget(card_title)
        prompt_text = (
            "请使用哔哩哔哩手机客户端扫码并完成人脸认证，完成后返回此页面重新点击“开始直播”。"
            if is_face_auth
            else "请使用哔哩哔哩手机客户端扫码完成验证，完成后返回此页面重新点击“开始直播”。"
        )
        prompt = QLabel(prompt_text, card)
        prompt.setObjectName("verification_prompt")
        prompt.setWordWrap(True)
        card_layout.addWidget(prompt)

        qr_label = QLabel("二维码暂不可用", card)
        qr_label.setObjectName("verification_qr")
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setFixedSize(240, 240)
        qr_label.setWordWrap(True)
        if image_bytes is not None:
            image = QImage.fromData(image_bytes.getvalue())
            if not image.isNull():
                qr_label.setText("")
                qr_label.setPixmap(
                    QPixmap.fromImage(image).scaled(
                        224,
                        224,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        card_layout.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        if url and qr_label.text():
            url_label = QLabel(url, card)
            url_label.setObjectName("verification_url")
            url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            url_label.setWordWrap(True)
            card_layout.addWidget(url_label)
        root.addWidget(card)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        root.addLayout(actions)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Allow the title region to move this frameless dialog."""
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


__all__ = ("LiveVerificationDialog",)
