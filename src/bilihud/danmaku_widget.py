import asyncio
import html
import logging
import os
from collections.abc import Coroutine
from typing import Any

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
    QTextDocument,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .app.hud import (
    HudConnectionStatus,
    HudEvent,
    HudLoginFailed,
    HudMessageReceived,
    HudOperationFailed,
    HudState,
    HudStateChanged,
)
from .app.hud_controller import HudController
from .app.lifecycle import TaskScope, TaskSupervisor
from .app.mirror_coordinator import MirrorCoordinator, MirrorOperationResult
from .app.services import AppServices, create_default_services
from .audience_widgets import AudiencePopup, AudienceStatusWidget
from .auth.service import AuthenticationService
from .config.store import ConfigStore
from .danmaku.format import (
    danmaku_author_badges_html,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
)
from .danmaku.messages import (
    DanmakuMessage,
    GiftMessage,
    HudMessage,
    InteractMessage,
    SystemMessage,
    SystemMessageLevel,
    make_system_message,
)
from .danmaku.mock import mock_message_batch
from .live.api import get_anchor_live_room_id
from .live.emoticons import LiveEmoticon, LiveEmoticonPackage
from .live_control_dialog import LiveControlDialog
from .mirror_settings_dialog import MirrorSettingsDialog
from .platform.overlay_contracts import DragMode, OverlayOperationResult, OverlayPlatform, WindowPoint
from .qr_login_dialog import QRLoginDialog
from .qt_window_host import QtWindowHost

logger = logging.getLogger(__name__)


class ModernInputWidget(QWidget):
    """
    一个现代化的输入框组件，包含圆形输入框和发送按钮
    """
    send_requested = pyqtSignal(str)
    emoticon_requested = pyqtSignal()

    def __init__(self, parent=None, placeholder="发送弹幕...", show_emoticon_button: bool = True):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)

        # 输入框
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(placeholder)
        self.input_edit.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 30);
                color: white;
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 13px;
                padding: 4px 10px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
                font-size: 12px;
                selection-background-color: rgba(255, 255, 255, 100);
            }
            QLineEdit:focus {
                background-color: rgba(255, 255, 255, 50);
                border: 1px solid rgba(255, 255, 255, 150);
            }
        """)
        self.input_edit.returnPressed.connect(self.on_send)

        self.emoticon_btn = QPushButton("☻")
        self.emoticon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.emoticon_btn.setFixedSize(28, 26)
        self.emoticon_btn.setToolTip("发送表情")
        self.emoticon_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 35);
                color: white;
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 13px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 60);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 80);
            }
        """)
        self.emoticon_btn.clicked.connect(self.emoticon_requested.emit)
        self.emoticon_btn.setVisible(show_emoticon_button)

        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(46, 26)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4FacFe, stop:1 #00f2fe);
                color: white;
                border: none;
                border-radius: 13px;
                font-weight: bold;
                font-size: 11px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #66b5ff, stop:1 #33f5ff);
            }
            QPushButton:pressed {
                background: #00bcd4;
            }
        """)
        self.send_btn.clicked.connect(self.on_send)

        self.layout.addWidget(self.input_edit)
        self.layout.addWidget(self.emoticon_btn)
        self.layout.addWidget(self.send_btn)

    def on_send(self):
        text = self.input_edit.text().strip()
        if text:
            self.send_requested.emit(text)
            self.input_edit.clear()

    def setFocus(self):
        self.input_edit.setFocus()


class EmoticonPickerPopup(QDialog):
    """直播间表情选择弹窗。"""
    emoticon_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(330, 260)
        self._network_manager = QNetworkAccessManager(self)
        self._image_cache: dict[str, QPixmap] = {}
        self._button_by_url: dict[str, list[QToolButton]] = {}
        self._emoticon_buttons: list[QToolButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: rgba(22, 24, 28, 235);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
            }
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 24);
                color: white;
                padding: 5px 9px;
                margin-right: 4px;
                border-radius: 5px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: rgba(79, 172, 254, 150);
            }
            QToolButton {
                background: rgba(255, 255, 255, 18);
                border: 1px solid rgba(255, 255, 255, 22);
                border-radius: 6px;
                color: white;
                padding: 2px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 40);
            }
            QToolButton:disabled {
                background: rgba(255, 255, 255, 10);
                color: rgba(255, 255, 255, 110);
            }
        """)
        outer.addWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget(self.container)
        layout.addWidget(self.tabs)

    def set_loading(self):
        self._clear_tabs()
        label = QLabel("加载中...", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: rgba(255, 255, 255, 180);")
        self.tabs.addTab(label, "表情")

    def set_error(self, message: str):
        self._clear_tabs()
        label = QLabel(message, self)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: rgba(255, 255, 255, 180);")
        self.tabs.addTab(label, "表情")

    def set_packages(self, packages: list[LiveEmoticonPackage]):
        self._clear_tabs()
        if not packages:
            self.set_error("没有可显示的直播间表情")
            return

        for package in packages:
            page = QWidget(self)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 4, 0, 0)
            scroll = QScrollArea(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            grid_host = QWidget(scroll)
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)

            for index, emoticon in enumerate(package.emoticons):
                button = self._create_emoticon_button(emoticon)
                row, col = divmod(index, 5)
                grid.addWidget(button, row, col)
                self._emoticon_buttons.append(button)

            scroll.setWidget(grid_host)
            page_layout.addWidget(scroll)
            self.tabs.addTab(page, package.name)

    def _clear_tabs(self):
        self._emoticon_buttons.clear()
        self._button_by_url.clear()
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if page is not None:
                page.deleteLater()

    def _create_emoticon_button(self, emoticon: LiveEmoticon) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(52, 52)
        button.setIconSize(QSize(42, 42))
        label = emoticon.unlock_label
        button.setToolTip(emoticon.emoji if not label else f"{emoticon.emoji} - {label}")
        if not emoticon.is_available:
            button.setEnabled(False)
            if label:
                button.setText(label)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                color = emoticon.unlock_color if emoticon.unlock_color.startswith("#") else "rgba(255, 255, 255, 140)"
                button.setStyleSheet(
                    f"""
                    QToolButton:disabled {{
                        background: rgba(255, 255, 255, 10);
                        color: {color};
                    }}
                    """
                )
        else:
            button.clicked.connect(lambda _checked=False, emoticon=emoticon: self._select_emoticon(emoticon))

        self._load_icon(button, emoticon.url)
        return button

    def _select_emoticon(self, emoticon: LiveEmoticon):
        self.emoticon_selected.emit(emoticon)
        self.hide()

    def _load_icon(self, button: QToolButton, url: str):
        cached = self._image_cache.get(url)
        if cached:
            button.setIcon(QIcon(cached))
            return

        self._button_by_url.setdefault(url, []).append(button)
        if len(self._button_by_url[url]) > 1:
            return

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        reply.finished.connect(lambda reply=reply, url=url: self._on_icon_loaded(reply, url))

    def _on_icon_loaded(self, reply, url: str):
        pixmap = QPixmap()
        pixmap.loadFromData(reply.readAll())
        reply.deleteLater()
        buttons = self._button_by_url.pop(url, [])
        if pixmap.isNull():
            return
        self._image_cache[url] = pixmap
        icon = QIcon(pixmap)
        for button in buttons:
            button.setIcon(icon)


class DanmakuInputDialog(QDialog):
    """全局弹幕输入框 (用于游戏模式/快捷唤起)"""

    send_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(450, 60)

        # 整体布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 背景容器 (实现Glass效果)
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 30, 220);
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
        """)

        # 加阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.container.setGraphicsEffect(shadow)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(10, 8, 10, 8)

        self.input_widget = ModernInputWidget(self, placeholder="输入弹幕... [ESC关闭]", show_emoticon_button=False)
        self.input_widget.send_requested.connect(self.on_send)

        container_layout.addWidget(self.input_widget)
        layout.addWidget(self.container)

    def on_send(self, text):
        self.send_message.emit(text)
        self.hide() # 发送后隐藏

    def showEvent(self, event):
        super().showEvent(event)
        self.input_widget.setFocus()
        # 居中显示在屏幕下方
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() // 2 - self.width() // 2,
            int(screen.height() * 0.8)
        )
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        super().keyPressEvent(event)

class DanmakuDelegate(QStyledItemDelegate):
    """
    High-performance delegate with Caching.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[int, tuple[HudMessage, QTextDocument]] = {}
        self._emoticon_cache: dict[str, QImage | None] = {}
        self._emoticon_docs: dict[str, list[QTextDocument]] = {}
        self._network_manager = QNetworkAccessManager(self)
        # We need to invalidate cache if width changes, but updating width on existing doc is cheap.

    def _get_document(self, message: HudMessage, width: int, font: QFont) -> QTextDocument:
        """Retrieve or create cached document."""
        msg_id = id(message)

        cached = self._cache.get(msg_id)
        if cached is not None:
            cached_message, doc = cached
            if cached_message is message:
                # Update width if changed (Resize event)
                if doc.textWidth() != width:
                    doc.setTextWidth(width)
                # Update font if changed? Usually constant.
                return doc

        # Cache Miss - Create new
        html_content = self.get_html_for_message(message)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        doc.setHtml(html_content)
        doc.setTextWidth(width)
        self._attach_emoticon_resource(doc, message)

        self._cache[msg_id] = (message, doc)

        # Pruned from DanmakuWidget.add_message when QListWidget drops old items.
        return doc

    def forget_message(self, message: HudMessage) -> None:
        msg_id = id(message)
        cached = self._cache.get(msg_id)
        if cached is not None and cached[0] is message:
            self._cache.pop(msg_id, None)

    def _attach_emoticon_resource(self, doc: QTextDocument, message: HudMessage) -> None:
        if not isinstance(message, DanmakuMessage):
            return

        for url in danmaku_message_emoticon_urls(message):
            qurl = QUrl(url)
            cached = self._emoticon_cache.get(url)
            if cached:
                doc.addResource(QTextDocument.ResourceType.ImageResource, qurl, cached)
                continue
            if url not in self._emoticon_cache:
                self._emoticon_cache[url] = None
                request = QNetworkRequest(qurl)
                request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
                request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
                reply = self._network_manager.get(request)
                reply.finished.connect(lambda reply=reply, url=url: self._on_emoticon_loaded(reply, url))

            self._emoticon_docs.setdefault(url, []).append(doc)

    def _on_emoticon_loaded(self, reply, url: str) -> None:
        image = QImage.fromData(reply.readAll())
        reply.deleteLater()
        docs = self._emoticon_docs.pop(url, [])
        if image.isNull():
            self._emoticon_cache.pop(url, None)
            return

        self._emoticon_cache[url] = image
        qurl = QUrl(url)
        for doc in docs:
            doc.addResource(QTextDocument.ResourceType.ImageResource, qurl, image)

        parent = self.parent()
        if parent is not None and hasattr(parent, "viewport"):
            parent.viewport().update()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint the item content directly."""
        options = option
        self.initStyleOption(options, index)

        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not msg_data:
            return

        painter.save()

        # Get width
        width = options.rect.width()
        if width <= 0: width = 300

        doc = self._get_document(msg_data, width, options.font)

        # Translate painter to the correct position
        painter.translate(options.rect.x(), options.rect.y() + 1) # +1 Top Margin

        # Draw the document
        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        """Calculate the size of the item."""
        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not msg_data:
            return QSize(0, 0)

        width = option.rect.width()
        if width <= 0:
            if self.parent() and hasattr(self.parent(), 'viewport'):
                width = self.parent().viewport().width()
        if width <= 0: width = 300

        doc = self._get_document(msg_data, width, option.font)

        return QSize(width, int(doc.size().height()) + 2) # +2 for margins

    def get_html_for_message(self, message: HudMessage) -> str:
        """Construct HTML content based on message type."""
        if isinstance(message, DanmakuMessage):
            user_color = self.get_user_color(message)
            badges_html = danmaku_author_badges_html(message)
            content_html = danmaku_message_content_html(message)
            return f"""
            <style>
                .meta-badge {{
                    display: inline-block;
                    padding: 0 4px;
                    font-family: 'Segoe UI', 'Microsoft YaHei';
                    font-size: 10px;
                    line-height: 13px;
                    font-weight: 700;
                    color: white;
                    vertical-align: 1px;
                }}
                .medal-badge {{
                    letter-spacing: 0;
                }}
                .wealth-badge {{
                    color: #C9B6FF;
                }}
                .privilege-badge {{
                    color: #FFD700;
                    min-width: 13px;
                    text-align: center;
                }}
                .user {{ color: {user_color}; font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .colon {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .content {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; font-weight: 500; }}
                .reply {{ color: #FF79C6; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; font-weight: 700; }}
                .emoticon {{ vertical-align: middle; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }} 
            </style>
            <p>{badges_html}<span class="user">{html.escape(message.author.name, quote=True)}</span><span class="colon"> : </span><span class="content">{content_html}</span></p>
            """
        elif isinstance(message, GiftMessage):
            return f"""
            <style>
                .user {{ color: #FFD700; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .action {{ color: #FF66CC; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .gift {{ color: #FF66CC; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="action"> {html.escape(message.action, quote=True)} </span>
            <span class="gift">{html.escape(message.gift_name, quote=True)} x{message.quantity}</span></p>
            """
        elif isinstance(message, InteractMessage):
            return f"""
            <style>
                .user {{ color: #AAAAAA; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                .info {{ color: #AAAAAA; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="info"> {html.escape(message.interaction.text, quote=True)}</span></p>
            """
        elif isinstance(message, SystemMessage):
            return f"""
            <style>
                .user {{ color: {message.author.color}; font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .colon {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .content {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; font-weight: 500; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span><span class="colon"> : </span><span class="content">{html.escape(message.text, quote=True)}</span></p>
            """
        return ""

    def get_user_color(self, message: HudMessage) -> str:
        """Return the author color normalized at the infrastructure boundary."""
        return message.author.color


class CustomSizeGrip(QWidget):
    """
    自定义大小调整手柄，解决 LayerShell 模式下 QSizeGrip 失效的问题
    通过手动计算鼠标位移并调用 resize() 来实现窗口调整
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet("""
            background-color: transparent;
        """)
        self._resizing = False
        self._start_mouse_pos = None
        self._start_size = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = True
            self._start_mouse_pos = event.globalPosition().toPoint()
            self._start_size = self.parent().size()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._start_mouse_pos
            new_width = max(self.parent().minimumWidth(), self._start_size.width() + delta.x())
            new_height = max(self.parent().minimumHeight(), self._start_size.height() + delta.y())

            self.parent().resize(new_width, new_height)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._resizing = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制 resize grip 的外观 (例如右下角的小三角点)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(255, 255, 255, 100)
        painter.setBrush(QBrush(color))

        # 绘制几个小点
        painter.drawEllipse(10, 10, 3, 3)
        painter.drawEllipse(6, 10, 3, 3)
        painter.drawEllipse(10, 6, 3, 3)


class DanmakuWidget(QWidget):
    """Presentation shell for danmaku, Mirror, login, and live-control workflows."""

    message_received = pyqtSignal(object)

    def __init__(
        self,
        room_id: int = 0,
        sessdata: str = "",
        services: AppServices | None = None,
        task_supervisor: TaskSupervisor | None = None,
    ) -> None:
        """Create the widget and load its shared typed services and saved settings."""
        super().__init__()
        self._task_supervisor = task_supervisor if task_supervisor is not None else TaskSupervisor()
        self._owns_task_supervisor = task_supervisor is None
        self._task_scope: TaskScope = self._task_supervisor.create_scope("danmaku-widget")
        self._action_tasks: set[asyncio.Task[Any]] = set()  # Qt-triggered workflows owned by this widget.
        self._shutting_down = False  # Prevent new work from starting during application shutdown.
        self._shutdown_complete = False  # Makes repeated application stop requests idempotent.
        self.room_id = room_id  # Current room displayed and used by the client.
        self.sessdata = sessdata  # Optional session override supplied by the caller.
        self.services = services if services is not None else create_default_services()
        self.config_store: ConfigStore = self.services.config_store  # Typed settings boundary.
        self.auth_service: AuthenticationService = self.services.auth_service  # Shared auth boundary.
        self.mirror_coordinator: MirrorCoordinator = self.services.mirror_coordinator
        self._live_control_dialog: LiveControlDialog | None = None  # Reused live-control dialog owner.
        self._mirror_settings_dialog: MirrorSettingsDialog | None = None  # Reused Mirror settings owner.
        self._qr_login_dialog: QRLoginDialog | None = None  # Active modal QR-login dialog, if any.
        self.is_gaming_mode = False
        self._window_host: QtWindowHost = QtWindowHost(self)
        self.overlay_platform: OverlayPlatform = self.services.overlay_platform_factory(self._window_host)
        prepare_result = self.overlay_platform.prepare()
        if not prepare_result.succeeded:
            logger.warning("Platform window preparation failed: %s", prepare_result.reason)
        config = self.config_store.load()
        self.mirror_coordinator.apply_config(config)

        # [Performance] Resize Debounce Timer
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30) # 30ms Debounce
        self._resize_timer.timeout.connect(self._delayed_adjust_height)

        self.setup_window_properties()
        self.init_ui()
        self.setup_tray_icon()
        self.update_gaming_mode_availability()

        # 加载保存的配置
        if config.room_id is not None:
            self.room_id = config.room_id

        self.hud_controller: HudController = HudController(
            initial_room_id=self.room_id,
            sessdata=self.sessdata,
            auth_service=self.auth_service,
            client_factory=self.services.hud_client_factory,
            config_store=self.config_store,
            task_scope=self._task_scope.child("hud-controller"),
        )
        self._hud_state: HudState = self.hud_controller.state
        self.hud_controller.subscribe(self._on_hud_event)

        # 初始化房间号
        self.room_id_input.setText(str(self.room_id))
        self._bind_hud_state(self._hud_state)

        # Try to activate Layer Shell initially
        QTimer.singleShot(100, self.activate_layer_shell)

    async def start(self) -> None:
        """Start application workflows after construction is complete."""
        if self._shutting_down:
            return
        result = await self.mirror_coordinator.start()
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

    def _delayed_adjust_height(self):
        """Debounced execution of item layout update"""
        if not self.is_gaming_mode:
             # With Delegate + ResizeMode.Adjust, we just need to poke the layout
             self.danmaku_list.scheduleDelayedItemsLayout()

    def activate_layer_shell(self) -> OverlayOperationResult:
        """Activate the injected platform adapter after the Qt surface is mapped."""
        result = self.overlay_platform.activate()
        self.update_gaming_mode_availability()
        if not result.succeeded:
            logger.warning("Platform window activation failed: %s", result.reason)
        return result

    def setup_window_properties(self):
        """设置基本的窗口属性"""
        self.resize(300, 450)
        # 居中屏幕
        screen_geo = QApplication.primaryScreen().geometry()

        # Initialize position relative to primary screen top-left
        initial_x = screen_geo.width() - 330
        initial_y = 100

        # Qt move expects global coordinates.
        self._window_host.move_window(WindowPoint(screen_geo.x() + initial_x, screen_geo.y() + initial_y))
        self.setWindowTitle("Danmaku Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        """自定义绘制背景，实现轻微的渐变面板效果 (非穿透模式下)"""
        if not self.is_gaming_mode:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 使用半透明黑色背景
            painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 8, 8)
            super().paintEvent(event)

    def init_ui(self):
        """初始化UI界面"""
        # 主布局
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        # --- 控制栏 (Header) ---
        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

        # 标题
        self.title_label = QLabel("BILIHUD")
        self.title_label.setStyleSheet("""
            color: rgba(255, 255, 255, 200); 
            font-weight: 900; 
            font-family: 'Arial Black';
            font-size: 12px;
            letter-spacing: 0.5px;
        """)

        self.live_status_dot = QLabel()
        self.live_status_dot.setFixedSize(8, 8)
        self.live_status_dot.setToolTip("直播中")
        self.live_status_dot.setStyleSheet("""
            QLabel {
                background-color: #ff2d55;
                border: 1px solid rgba(255, 255, 255, 180);
                border-radius: 4px;
            }
        """)
        self.live_status_dot.hide()

        # 房间号输入
        self.room_id_input = QLineEdit(str(self.room_id))
        self.room_id_input.setPlaceholderText("ID")
        self.room_id_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.room_id_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 4px;
                padding: 2px 4px;
                background: rgba(0, 0, 0, 50);
                color: #ddd;
                font-weight: bold;
                max-width: 70px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: rgba(255, 255, 255, 100);
            }
        """)
        self.room_id_input.editingFinished.connect(self.save_room_id)

        # 按钮样式
        btn_style = """
            QPushButton {
                color: white;
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 40);
            }
            QPushButton:checked {
                background-color: rgba(76, 175, 80, 150);
                border-color: rgba(76, 175, 80, 200);
            }
            QPushButton:disabled {
                color: rgba(255, 255, 255, 90);
                background-color: rgba(255, 255, 255, 8);
                border-color: rgba(255, 255, 255, 15);
            }
        """

        # 连接按钮
        self.connect_button = QPushButton("连接")
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.setCheckable(True)
        self.connect_button.setStyleSheet(btn_style)
        self.connect_button.clicked.connect(self.toggle_connection)

        # 游戏模式切换按钮
        self.gaming_mode_btn = QPushButton("锁定穿透")
        self.gaming_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gaming_mode_btn.setCheckable(True)
        self.gaming_mode_btn.setStyleSheet(btn_style)
        self.gaming_mode_btn.clicked.connect(self.toggle_gaming_mode)

        # 关闭按钮 (右上角小圆点)
        close_btn = QPushButton("×")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,150);
                background: transparent;
                border: 1px solid rgba(255,0,0,50);
                border-radius: 10px;
                font-weight: bold;
                font-size: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background: rgba(255, 0, 0, 180);
                color: white;
                border-color: transparent;
            }
        """)
        close_btn.clicked.connect(self.hide)

        # 组装 Header
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addWidget(self.live_status_dot)
        self.header_layout.addWidget(self.room_id_input)
        self.header_layout.addWidget(self.connect_button)
        self.header_layout.addWidget(self.gaming_mode_btn)
        self.header_layout.addStretch()
        self.header_layout.addWidget(close_btn)

        # --- 弹幕列表 ---
        self.danmaku_list = QListWidget()
        self.danmaku_list.setItemDelegate(DanmakuDelegate(self.danmaku_list)) # Set High Perf Delegate
        self.danmaku_list.setStyleSheet("background: transparent; border: none;")
        self.danmaku_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.danmaku_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.danmaku_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.danmaku_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.danmaku_list.setResizeMode(QListView.ResizeMode.Adjust) # Trigger layout on resize

        # 滚动条样式美化
        self.danmaku_list.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                border: none;
                background: rgba(0, 0, 0, 0);
                width: 4px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 50);
                min-height: 20px;
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        # --- 底部输入区域 (新) ---
        self.input_area = ModernInputWidget(self)
        self.input_area.send_requested.connect(self.trigger_send)
        self.input_area.emoticon_requested.connect(self.open_emoticon_picker)
        self.emoticon_picker = EmoticonPickerPopup(self)
        self.emoticon_picker.emoticon_selected.connect(self.trigger_send_live_emoticon)
        self.audience_status = AudienceStatusWidget(self)
        self.audience_popup = AudiencePopup(self)
        self.audience_status.audience_requested.connect(self.open_audience_popup)

        # 组装 Main
        self.main_layout.addWidget(self.header_widget)
        self.main_layout.addWidget(self.audience_status)
        self.main_layout.addWidget(self.danmaku_list)
        self.main_layout.addWidget(self.input_area) # 放在底部

        self.setLayout(self.main_layout)

        # 信号连接
        self.message_received.connect(self.add_message)

        # 初始化全局输入框
        self.input_dialog = DanmakuInputDialog(None)
        self.input_dialog.send_message.connect(self.trigger_send)

        # 拖拽移动相关变量
        self._dragging = False
        self._drag_position = QPoint()
        self._message_buffer: list[HudMessage] = [] # [Optimization] Buffer

        # 大小调整手柄
        self.size_grip = CustomSizeGrip(self)
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: transparent;
                width: 16px; 
                height: 16px;
            }
        """)

    # [Old resizeEvent removed - replaced by instrumented version below]

    def adjust_list_items_height(self, target_width: int = None):
        """
        Deprecated. Layout is handled by QStyledItemDelegate + ResizeMode.Adjust.
        Kept as dummy to prevent debris crashes if referenced.
        """
        pass

    def setup_tray_icon(self):
        """初始化系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self)

        # 加载图标
        icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icon.png')
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)
        else:
            print(f"Icon not found at {icon_path}")

        # 创建托盘菜单
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #3d3d3d;
            }
        """)

        self.tray_send_action = QAction("发送弹幕", self)
        self.tray_send_action.triggered.connect(self.open_input_dialog)
        tray_menu.addAction(self.tray_send_action)

        tray_menu.addSeparator()

        self.tray_toggle_action = QAction("显示/隐藏", self)
        self.tray_toggle_action.triggered.connect(self.toggle_visibility)
        tray_menu.addAction(self.tray_toggle_action)

        self.tray_gaming_action = QAction("锁定穿透 (游戏模式)", self)
        self.tray_gaming_action.setCheckable(True)
        self.tray_gaming_action.triggered.connect(self.toggle_gaming_mode_from_tray)
        tray_menu.addAction(self.tray_gaming_action)

        tray_menu.addSeparator()

        self.tray_login_action = QAction("扫码登录", self)
        self.tray_login_action.triggered.connect(self.open_qr_login)
        tray_menu.addAction(self.tray_login_action)

        self.tray_live_control_action = QAction("直播控制", self)
        self.tray_live_control_action.triggered.connect(self.open_live_control)
        tray_menu.addAction(self.tray_live_control_action)

        self.tray_mirror_action = QAction("BiliHUD Mirror", self)
        self.tray_mirror_action.triggered.connect(self.open_mirror_settings)
        tray_menu.addAction(self.tray_mirror_action)

        self.tray_mock_action = QAction("弹幕模拟", self)
        self.tray_mock_action.triggered.connect(self.trigger_danmaku_simulation)
        tray_menu.addAction(self.tray_mock_action)

        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.tray_icon.activated.connect(self.on_tray_activated)

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
        available = self.is_gaming_mode_available()
        self.gaming_mode_btn.setEnabled(available)
        self.tray_gaming_action.setEnabled(available)
        if not available:
            self.gaming_mode_btn.setText("穿透不可用")
            self.gaming_mode_btn.setChecked(False)
            self.tray_gaming_action.setChecked(False)
            reason = self.overlay_platform.capabilities.unavailable_reason
            if reason is None:
                reason = "当前平台不支持"
            tooltip = f"游戏模式不可用: {reason}\n当前仍可使用普通窗口模式。"
            self.gaming_mode_btn.setToolTip(tooltip)
            self.tray_gaming_action.setToolTip(tooltip)

    async def _send_danmaku_task(self, text: str):
        """Execute a text-send command through the application controller."""
        await self.hud_controller.send_danmaku(text)

    def trigger_send(self, text: str):
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

    def trigger_send_live_emoticon(self, emoticon: LiveEmoticon):
        if self._shutting_down:
            return
        self._task_scope.create_task(
            self._send_live_emoticon_task(emoticon),
            name="send-live-emoticon",
        )

    async def _send_live_emoticon_task(self, emoticon: LiveEmoticon):
        """Execute a live-emoticon send command through the application controller."""
        await self.hud_controller.send_live_emoticon(emoticon)

    def open_input_dialog(self):
        """打开全局输入框"""
        self.input_dialog.show()
        self.input_dialog.activateWindow()

    def trigger_danmaku_simulation(self) -> None:
        """Inject the complete fixed message batch into the normal HUD path."""
        if self._shutting_down:
            return
        for message in mock_message_batch():
            self.add_message(message)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    async def shutdown(self) -> None:
        """Stop widget-owned workflows and release their network resources."""
        if self._shutdown_complete:
            return

        self._shutting_down = True
        shutdown_errors: list[Exception] = []
        try:
            await self._cancel_action_tasks()

            live_control_dialog = self._live_control_dialog
            if live_control_dialog is not None:
                try:
                    await live_control_dialog.shutdown()
                    live_control_dialog.close()
                except Exception as exc:
                    logger.exception("Failed to close live control dialog")
                    shutdown_errors.append(exc)

            qr_login_dialog = self._qr_login_dialog
            if qr_login_dialog is not None:
                try:
                    await qr_login_dialog.shutdown()
                    qr_login_dialog.close()
                except Exception as exc:
                    logger.exception("Failed to close QR login dialog")
                    shutdown_errors.append(exc)
                else:
                    self._qr_login_dialog = None

            mirror_settings_dialog = self._mirror_settings_dialog
            if mirror_settings_dialog is not None:
                mirror_settings_dialog.close()

            try:
                await self.hud_controller.shutdown()
            except Exception as exc:
                logger.exception("Failed to close HUD controller")
                shutdown_errors.append(exc)
            try:
                await self._task_scope.cancel_all()
            except Exception as exc:
                logger.exception("Failed to cancel widget tasks")
                shutdown_errors.append(exc)

            try:
                await self.shutdown_mirror_server()
            except Exception as exc:
                logger.exception("Failed to close Mirror server")
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
        if checked and not self.is_gaming_mode_available():
            self.show_gaming_mode_unavailable_message()
            self.tray_gaming_action.setChecked(False)
            return

        # 避免递归更新
        if self.is_gaming_mode != checked:
            self.set_gaming_mode(checked)

    def toggle_gaming_mode(self):
        """切换鼠标穿透/游戏模式"""
        new_state = not self.is_gaming_mode
        if new_state and not self.is_gaming_mode_available():
            self.show_gaming_mode_unavailable_message()
            self.gaming_mode_btn.setChecked(False)
            return

        self.set_gaming_mode(new_state)

    def show_gaming_mode_unavailable_message(self, reason: str | None = None) -> None:
        """Explain a platform capability limitation without preventing normal use."""
        limitation = reason
        if limitation is None:
            limitation = self.overlay_platform.capabilities.unavailable_reason
        if limitation is None:
            limitation = "当前平台不支持游戏模式"
        self.tray_icon.showMessage(
            "Danmaku Overlay",
            f"{limitation}\n当前仍可使用普通窗口模式。",
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Apply a platform mode transition and then update the presentation state."""
        previous_state = self.is_gaming_mode
        result = self.overlay_platform.set_gaming_mode(enabled)
        if not result.succeeded:
            self.gaming_mode_btn.setChecked(previous_state)
            self.tray_gaming_action.setChecked(previous_state)
            logger.warning("Gaming mode transition failed: %s", result.reason)
            self.show_gaming_mode_unavailable_message(result.reason)
            return result

        self.is_gaming_mode = enabled
        self.tray_gaming_action.setChecked(enabled)
        self.gaming_mode_btn.setChecked(enabled)

        if enabled:
            self.header_widget.hide()
            self.input_area.hide()
            self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.danmaku_list.setStyleSheet("""
                QListWidget {
                    background: transparent;
                    border: 2px dashed rgba(255, 255, 255, 30);
                    border-radius: 8px;
                }
            """)
            self.tray_icon.showMessage(
                "Danmaku Overlay",
                "已进入穿透模式 (游戏覆盖)\n弹幕将显示在最顶层，鼠标操作将穿透。",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            self.header_widget.show()
            self.input_area.show()
            self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.danmaku_list.setStyleSheet("background: transparent; border: none;")

        self._sync_audience_visibility()
        return result

    # --- 鼠标拖拽移动窗口逻辑 ---
    def mousePressEvent(self, event) -> None:
        if not self.is_gaming_mode and event.button() == Qt.MouseButton.LeftButton:
            local_position = event.position().toPoint()
            global_position = event.globalPosition().toPoint()
            result = self.overlay_platform.begin_drag(
                WindowPoint(local_position.x(), local_position.y()),
                WindowPoint(global_position.x(), global_position.y()),
            )
            if result.mode is DragMode.UNAVAILABLE:
                logger.warning("Window drag unavailable: %s", result.reason)
                return
            self._dragging = result.mode is DragMode.MANUAL
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            local_position = event.position().toPoint()
            global_position = event.globalPosition().toPoint()
            result = self.overlay_platform.update_drag(
                WindowPoint(local_position.x(), local_position.y()),
                WindowPoint(global_position.x(), global_position.y()),
            )
            if not result.succeeded:
                logger.warning("Window drag update failed: %s", result.reason)
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # 1. 更新SizeGrip位置
        rect = self.rect()
        self.size_grip.move(
            rect.right() - self.size_grip.width(),
            rect.bottom() - self.size_grip.height()
        )

        # 2. Debounced Layout Update
        if not self.is_gaming_mode:
            self._resize_timer.start()

    def mouseReleaseEvent(self, event) -> None:
        self.overlay_platform.end_drag()
        self._dragging = False

        # [Message Buffering]
        # Process all types of messages
        if self._message_buffer:
            for message in self._message_buffer:
                self.message_received.emit(message)
            self._message_buffer.clear()





    def showEvent(self, event):
        super().showEvent(event)
        # Re-activate Layer Shell when shown to ensure overlay/input works
        # Delayed to ensure window is mapped
        QTimer.singleShot(100, self.activate_layer_shell)

    def open_audience_popup(self):
        snapshot = self._hud_state.audience_snapshot
        if snapshot is None or self.is_gaming_mode:
            return
        self.audience_popup.set_snapshot(snapshot)
        self.audience_popup.show_below(self.audience_status.online_button, self)

    def _sync_audience_visibility(self) -> None:
        visible = self._hud_state.audience_snapshot is not None and not self.is_gaming_mode
        self.audience_status.setVisible(visible)
        if not visible:
            self.audience_popup.hide()

    def _on_hud_event(self, event: HudEvent) -> None:
        """Bind typed controller events to Qt rendering and user notifications."""
        if isinstance(event, HudStateChanged):
            self._bind_hud_state(event.state)
        elif isinstance(event, HudMessageReceived):
            self.on_message_received(event.message)
        elif isinstance(event, HudLoginFailed):
            self.on_login_failed(event.message)
        elif isinstance(event, HudOperationFailed):
            self.add_system_message(event.message, SystemMessageLevel.ERROR)

    def _bind_hud_state(self, state: HudState) -> None:
        """Render one complete controller snapshot without reading network objects."""
        previous_room_id = self._hud_state.room_id
        self._hud_state = state
        if state.room_id is not None and state.room_id != previous_room_id:
            self.room_id = state.room_id
            self.room_id_input.setText(str(state.room_id))

        if state.connection is HudConnectionStatus.CONNECTING:
            self._set_connecting_ui()
        elif state.connection is HudConnectionStatus.DISCONNECTING:
            self._set_disconnecting_ui()
        elif state.connection is HudConnectionStatus.CONNECTED:
            self._set_connected_ui()
        else:
            self._set_disconnected_ui()

        snapshot = state.audience_snapshot
        if snapshot is None:
            self.audience_popup.hide()
            self.audience_status.clear()
        else:
            self.audience_status.set_snapshot(snapshot)
            self.audience_popup.set_snapshot(snapshot)
        self._sync_audience_visibility()

    def _set_connecting_ui(self):
        self.connect_button.setText("连接中...")
        self.connect_button.setEnabled(False)

    def _set_disconnecting_ui(self):
        self.connect_button.setText("断开中...")
        self.connect_button.setChecked(True)
        self.connect_button.setEnabled(False)

    def _set_connected_ui(self):
        self.connect_button.setText("断开")
        self.connect_button.setChecked(True)
        self.connect_button.setEnabled(True)
        self.connect_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(244, 67, 54, 150);
                color: white;
                border: 1px solid rgba(244, 67, 54, 200);
                border-radius: 6px; padding: 4px 10px;
            }
            QPushButton:hover { background-color: rgba(244, 67, 54, 200); }
        """)

    def _set_disconnected_ui(self):
        self.connect_button.setText("连接")
        self.connect_button.setChecked(False)
        self.connect_button.setEnabled(True)
        self.connect_button.setStyleSheet("""
            QPushButton {
                color: white;
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 40); }
            QPushButton:checked { background-color: rgba(76, 175, 80, 150); }
        """)

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
        if self._dragging:
            self._message_buffer.append(message)
        else:
            self.message_received.emit(message)

    def add_message(self, message: HudMessage, _from_buffer: bool = False) -> None:
        """Add one normalized message to Qt history and the optional Mirror stream."""
        # [Delegate Architecture]
        # Just create an item and set data. Paint/Layout is handled by DanmakuDelegate.
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, message)

        self.danmaku_list.addItem(item)

        # [Optimization] Reduce max history to 200 to prevent render lag
        if self.danmaku_list.count() > 200:
            removed_item = self.danmaku_list.takeItem(0)
            if removed_item is not None:
                delegate = self.danmaku_list.itemDelegate()
                if hasattr(delegate, "forget_message"):
                    delegate.forget_message(removed_item.data(Qt.ItemDataRole.UserRole))

        self.danmaku_list.scrollToBottom()

        self.mirror_coordinator.publish_message(message)

    async def _ensure_live_control_room(self) -> int:
        """Resolve the authenticated anchor room and close the temporary session."""
        session = None
        try:
            session, _from_keyring = await self.auth_service.create_authenticated_session()
            anchor_room_id = await get_anchor_live_room_id(session)
        finally:
            if session is not None and not session.closed:
                await session.close()

        await self.hud_controller.connect(anchor_room_id)
        return anchor_room_id

    @pyqtSlot()
    def open_live_control(self) -> asyncio.Task[None] | None:
        """Schedule opening the live control dialog under the widget owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(
            self._open_live_control(),
            name="open-live-control",
        )

    async def _open_live_control(self) -> None:
        """打开直播控制窗口"""
        if self._shutting_down:
            return
        try:
            anchor_room_id = await self._ensure_live_control_room()
        except Exception as e:
            self.add_system_message(f"无法打开直播控制: {e}", SystemMessageLevel.ERROR)
            print(f"Open live control failed: {e}")
            return
        if self._shutting_down:
            return

        if self._live_control_dialog is None:
            self._live_control_dialog = LiveControlDialog(
                self,
                services=self.services,
                task_scope=self._task_scope.child("live-control"),
            )
            self._live_control_dialog.live_status_changed.connect(self.set_live_status_indicator)
        dialog = self._live_control_dialog
        if dialog is None:
            return
        dialog.set_room_id(anchor_room_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_mirror_settings(self):
        """Open the Mirror settings view and bind the current application state."""
        if self._shutting_down:
            return
        if self._mirror_settings_dialog is None:
            self._mirror_settings_dialog = MirrorSettingsDialog(self)
            self._mirror_settings_dialog.mirror_enabled_requested.connect(
                self._schedule_mirror_toggle
            )
        dialog = self._mirror_settings_dialog
        dialog.refresh(self.mirror_coordinator.state)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
        if self._shutting_down:
            return None
        return self._create_action_task(
            self._toggle_mirror_server(),
            name="toggle-mirror-server",
        )

    async def _toggle_mirror_server(self) -> None:
        await self.set_mirror_enabled(not self.mirror_coordinator.state.enabled)

    def _schedule_mirror_toggle(self, enabled: bool) -> None:
        """Schedule a Mirror settings request from the presentation signal."""
        if self._shutting_down:
            return
        self._create_action_task(
            self.set_mirror_enabled(enabled),
            name="toggle-mirror-settings",
        )

    async def set_mirror_enabled(self, enabled: bool) -> MirrorOperationResult:
        """Delegate the Mirror preference and lifecycle transition to the coordinator."""
        result = await self.mirror_coordinator.set_enabled(enabled)
        self._apply_mirror_result(result)
        return result

    def refresh_mirror_settings(self) -> None:
        """Refresh the settings view from a coordinator-owned state snapshot."""
        if self._mirror_settings_dialog is not None:
            self._mirror_settings_dialog.refresh(self.mirror_coordinator.state)

    def mirror_status_text(self) -> str:
        """Return the localized status exposed by the coordinator state."""
        return self.mirror_coordinator.state.status_text

    async def start_mirror_server(self) -> MirrorOperationResult:
        """Delegate server startup to the application-owned coordinator."""
        result = await self.mirror_coordinator.start()
        self._apply_mirror_result(result)
        return result

    async def stop_mirror_server(self) -> MirrorOperationResult:
        """Disable Mirror through the coordinator and retain the resulting state."""
        return await self.set_mirror_enabled(False)

    async def shutdown_mirror_server(self) -> MirrorOperationResult:
        """Stop the coordinator-owned server during widget shutdown."""
        result = await self.mirror_coordinator.shutdown()
        self.refresh_mirror_settings()
        return result

    def _apply_mirror_result(self, result: MirrorOperationResult) -> None:
        """Render coordinator notices through the existing normalized HUD path."""
        for notice in result.notices:
            self.add_system_message(notice.text, notice.level)
        self.refresh_mirror_settings()

    def set_live_status_indicator(self, is_live: bool):
        """显示或隐藏标题栏直播状态点。"""
        self.live_status_dot.setVisible(is_live)

    def open_qr_login(self):
        """Open the QR-login window without blocking the application event loop."""
        if self._shutting_down:
            return
        dialog = self._qr_login_dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = QRLoginDialog(
            self,
            auth_service=self.auth_service,
            task_scope=self._task_scope.child("qr-login"),
        )
        dialog.login_success.connect(self.on_login_success)
        dialog.finished.connect(lambda _result: self._finish_qr_login(dialog))
        self._qr_login_dialog = dialog
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _finish_qr_login(self, dialog: QRLoginDialog) -> None:
        """Release a completed QR-login dialog through the widget task owner."""
        if self._shutting_down:
            return
        self._create_action_task(
            self._close_qr_login(dialog),
            name="close-qr-login",
        )

    async def _close_qr_login(self, dialog: QRLoginDialog) -> None:
        """Await QR-login task cancellation before deleting its presentation object."""
        await dialog.shutdown()
        if self._qr_login_dialog is dialog:
            self._qr_login_dialog = None
        dialog.deleteLater()

    def on_login_success(self):
        """登录成功，提醒用户重连"""
        self.tray_icon.showMessage(
            "登录成功",
            "B站账号已登录，将在下次连接时生效。",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
        self.add_system_message("登录成功！请断开并重新连接以应用新的登录信息。")

    def on_login_failed(self, msg: str):
        """登录失效回调"""
        self.tray_icon.showMessage(
            "登录失效",
            msg,
            QSystemTrayIcon.MessageIcon.Warning,
            5000
        )
        self.add_system_message(msg, SystemMessageLevel.ERROR)

    def closeEvent(self, event: QCloseEvent):
        """覆盖关闭事件：最小化到系统托盘，而不是退出程序"""
        event.ignore()
        self.hide()

        # Reminder for user
        self.tray_icon.showMessage(
            "Bilibili Danmaku",
            "程序已最小化到托盘运行",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
