"""Embedded Bilibili account page for the unified settings window."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .app.menu import AccountStatus
from .auth.service import AccountProfile


class AccountSettingsPage(QWidget):
    """Render account identity, session status, login, and logout actions."""

    _MAX_AVATAR_BYTES = 2 * 1024 * 1024

    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the account page without performing network or keyring work."""
        super().__init__(parent)
        self._profile: AccountProfile | None = None
        self._avatar_generation = 0
        self._avatar_reply: QNetworkReply | None = None
        self._network_manager = QNetworkAccessManager(self)
        self.setObjectName("settings_page")
        self._init_ui()
        self.set_account_state(AccountStatus.UNKNOWN, None)

    def _init_ui(self) -> None:
        """Build the account card and bind presentation signals."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 8, 8)
        page_layout.setSpacing(14)

        card = QFrame(self)
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title = QLabel("Bilibili 账号", card)
        title.setObjectName("card_title")
        layout.addWidget(title)

        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 2, 0, 2)
        profile_row.setSpacing(12)
        self.account_avatar = QLabel("B", card)
        self.account_avatar.setObjectName("account_avatar")
        self.account_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.account_avatar.setFixedSize(48, 48)
        profile_row.addWidget(self.account_avatar)

        identity = QVBoxLayout()
        identity.setSpacing(3)
        self.account_name_label = QLabel("正在读取账号信息...", card)
        self.account_name_label.setObjectName("account_name")
        self.account_id_label = QLabel("", card)
        self.account_id_label.setObjectName("account_id")
        identity.addWidget(self.account_name_label)
        identity.addWidget(self.account_id_label)
        profile_row.addLayout(identity)
        profile_row.addStretch(1)
        layout.addLayout(profile_row)

        self.account_status_label = QLabel("检查中...", card)
        self.account_status_label.setObjectName("status_label")
        layout.addWidget(self.account_status_label)

        self.account_stats = QFrame(card)
        self.account_stats.setObjectName("account_stats")
        stats_layout = QHBoxLayout(self.account_stats)
        stats_layout.setContentsMargins(0, 8, 0, 2)
        stats_layout.setSpacing(28)
        self.following_value = self._add_stat(stats_layout, "关注")
        self.follower_value = self._add_stat(stats_layout, "粉丝")
        stats_layout.addStretch(1)
        layout.addWidget(self.account_stats)

        self.account_links = QHBoxLayout()
        self.account_links.setSpacing(6)
        self.space_button = QPushButton("个人空间", card)
        self.space_button.setProperty("link", True)
        self.space_button.clicked.connect(self._open_space)
        self.live_room_button = QPushButton("直播间", card)
        self.live_room_button.setProperty("link", True)
        self.live_room_button.clicked.connect(self._open_live_room)
        self.account_links.addWidget(self.space_button)
        self.account_links.addWidget(self.live_room_button)
        self.account_links.addStretch(1)
        layout.addLayout(self.account_links)

        self.login_button = QPushButton("扫码登录", card)
        self.login_button.clicked.connect(self.login_requested.emit)
        self.logout_button = QPushButton("登出", card)
        self.logout_button.setProperty("destructive", True)
        self.logout_button.clicked.connect(self.logout_requested.emit)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        actions.addWidget(self.login_button)
        actions.addWidget(self.logout_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        page_layout.addWidget(card)
        page_layout.addStretch(1)

    @staticmethod
    def _add_stat(layout: QHBoxLayout, label: str) -> QLabel:
        """Add one compact relation statistic and return its value label."""
        block = QVBoxLayout()
        block.setSpacing(1)
        value = QLabel("—")
        value.setObjectName("account_stat_value")
        caption = QLabel(label)
        caption.setObjectName("account_stat_label")
        block.addWidget(value)
        block.addWidget(caption)
        layout.addLayout(block)
        return value

    def set_account_state(self, status: AccountStatus, profile: AccountProfile | None) -> None:
        """Render one normalized identity and session snapshot from the application owner."""
        labels = {
            AccountStatus.UNKNOWN: "检查中...",
            AccountStatus.LOGGED_IN: "已登录",
            AccountStatus.LOGIN_EXPIRED: "登录失效",
            AccountStatus.LOGGED_OUT: "未登录",
            AccountStatus.UNAVAILABLE: "暂时无法获取",
        }
        self.account_status_label.setText(labels[status])
        self.account_status_label.setProperty(
            "level",
            "success"
            if status is AccountStatus.LOGGED_IN
            else "error"
            if status is AccountStatus.LOGIN_EXPIRED
            else "",
        )
        style = self.account_status_label.style()
        if style is not None:
            style.unpolish(self.account_status_label)
            style.polish(self.account_status_label)

        self._profile = profile if status is AccountStatus.LOGGED_IN else None
        if self._profile is None:
            self._avatar_generation += 1
            self._cancel_avatar_request()
            name = "未登录" if status is AccountStatus.LOGGED_OUT else "Bilibili 账号"
            self.account_name_label.setText(name)
            self.account_id_label.clear()
            self._set_avatar_fallback("B")
            self.account_stats.setVisible(False)
            self.space_button.setVisible(False)
            self.live_room_button.setVisible(False)
        else:
            self.account_name_label.setText(self._profile.username)
            self.account_id_label.setText(f"UID {self._profile.user_id}")
            self.following_value.setText(_count_text(self._profile.following_count))
            self.follower_value.setText(_count_text(self._profile.follower_count))
            self.account_stats.setVisible(True)
            self.space_button.setVisible(True)
            self.space_button.setToolTip(self._profile.space_url)
            self.live_room_button.setVisible(self._profile.live_room_url is not None)
            self.live_room_button.setToolTip(self._profile.live_room_url or "")
            self._load_avatar(self._profile)
        self.login_button.setVisible(status is not AccountStatus.LOGGED_IN)
        self.logout_button.setVisible(status in (AccountStatus.LOGGED_IN, AccountStatus.LOGIN_EXPIRED))

    def _load_avatar(self, profile: AccountProfile) -> None:
        """Load the remote avatar asynchronously and keep the initials fallback ready."""
        self._avatar_generation += 1
        generation = self._avatar_generation
        self._cancel_avatar_request()
        self._set_avatar_fallback(profile.username[:1] or "B")
        avatar_url = profile.avatar_url
        if avatar_url is None:
            return
        request = QNetworkRequest(QUrl(avatar_url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        if reply is None:
            return
        self._avatar_reply = reply
        reply.setReadBufferSize(self._MAX_AVATAR_BYTES + 1)
        reply.downloadProgress.connect(
            lambda received, _total: self._abort_oversized_avatar(reply, received)
        )
        reply.finished.connect(lambda: self._avatar_finished(reply, generation))

    def _cancel_avatar_request(self) -> None:
        """Abort the previous avatar request before starting a newer account lookup."""
        reply = self._avatar_reply
        self._avatar_reply = None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _avatar_finished(self, reply: QNetworkReply, generation: int) -> None:
        """Apply a valid bounded image only when it belongs to the current account."""
        if self._avatar_reply is reply:
            self._avatar_reply = None
        error = reply.error()
        if generation != self._avatar_generation or error is not QNetworkReply.NetworkError.NoError:
            reply.deleteLater()
            return
        if reply.size() > self._MAX_AVATAR_BYTES:
            reply.deleteLater()
            return
        payload = reply.readAll().data()
        reply.deleteLater()
        if not payload or len(payload) > self._MAX_AVATAR_BYTES:
            return
        image = QImage.fromData(payload)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.account_avatar.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.account_avatar.setPixmap(self._round_pixmap(pixmap))
        self.account_avatar.setText("")

    def _abort_oversized_avatar(self, reply: QNetworkReply, received: int) -> None:
        """Stop an avatar download before an unknown-size response grows unbounded."""
        if self._avatar_reply is reply and received > self._MAX_AVATAR_BYTES:
            reply.abort()

    @staticmethod
    def _round_pixmap(pixmap: QPixmap) -> QPixmap:
        """Clip a downloaded avatar into the same circular shape as the fallback."""
        result = QPixmap(pixmap.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(QRectF(result.rect()))
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return result

    def _set_avatar_fallback(self, text: str) -> None:
        """Restore the lightweight initials avatar while a remote image is unavailable."""
        self.account_avatar.setPixmap(QPixmap())
        self.account_avatar.setText(text)

    def _open_space(self) -> None:
        """Open the account's public personal-space page."""
        if self._profile is not None:
            QDesktopServices.openUrl(QUrl(self._profile.space_url))

    def _open_live_room(self) -> None:
        """Open the account's public live-room page when one is available."""
        if self._profile is not None and self._profile.live_room_url is not None:
            QDesktopServices.openUrl(QUrl(self._profile.live_room_url))


def _count_text(value: int | None) -> str:
    """Render optional relation counts without inventing a zero value."""
    return "—" if value is None else str(value)


__all__ = ("AccountSettingsPage",)
