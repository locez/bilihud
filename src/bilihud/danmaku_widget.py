# -*- coding: utf-8 -*-
import asyncio
import ctypes
import html
import logging
import os
import sys
from ctypes import c_int, c_ulong, c_void_p
from typing import Optional

import blivedm.models.web as web_models
import PyQt6.sip as sip
import qasync
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QGuiApplication,
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

from .audience_widgets import AudiencePopup, AudienceStatusWidget
from .auth import AuthManager
from .danmaku_client import DanmakuClient
from .danmaku_format import (
    danmaku_author_badges_html,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
)
from .danmaku_logger import DanmakuLogger
from .mock_generator import MockMessageGenerator
from .layer_shell_loader import (
    LAYER_SHELL_LIBRARY_NAME,
    find_layer_shell_library,
    gaming_mode_available,
    should_disable_layer_shell,
)
from .live_api import get_anchor_live_room_id
from .live_audience import AudienceSnapshot
from .live_control_dialog import LiveControlDialog
from .live_emoticons import LiveEmoticon, LiveEmoticonPackage
from .mirror_server import MirrorServer
from .mirror_settings_dialog import MirrorSettingsDialog
from .mirror_state import MIRROR_DEFAULT_PORT, MIRROR_ROUTE, MirrorState
from .qr_login_dialog import QRLoginDialog
from .utils import load_config, save_config

logger = logging.getLogger(__name__)
AUDIENCE_REFRESH_INTERVAL_SECONDS = 30.0


class ModernInputWidget(QWidget):
    send_requested = pyqtSignal(str)
    emoticon_requested = pyqtSignal()

    def __init__(self, parent=None, placeholder="发送弹幕...", show_emoticon_button: bool = True):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)

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
    send_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(450, 60)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 30, 220);
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
        """)
        
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
        self.hide()
            
    def showEvent(self, event):
        super().showEvent(event)
        self.input_widget.setFocus()
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


class X11Helper:
    _x11 = None
    _xext = None
    
    @classmethod
    def init(cls):
        if cls._x11: return
        try:
            cls._x11 = ctypes.cdll.LoadLibrary('libX11.so.6')
            cls._xext = ctypes.cdll.LoadLibrary('libXext.so.6')
            
            cls._x11.XOpenDisplay.restype = c_void_p
            cls._x11.XOpenDisplay.argtypes = [c_void_p]
            cls._x11.XFlush.argtypes = [c_void_p]
            cls._x11.XCloseDisplay.argtypes = [c_void_p]
            
            cls._xext.XShapeCombineRectangles.argtypes = [
                c_void_p, c_ulong, c_int, c_int, c_int, c_void_p, c_int, c_int, c_int
            ]
            
            cls._xext.XShapeCombineMask.argtypes = [
                c_void_p, c_ulong, c_int, c_int, c_int, c_void_p, c_int
            ]
        except Exception as e:
            print(f"X11 init failed: {e}")

    @classmethod
    def set_click_through(cls, win_id, enabled):
        if sys.platform != 'linux': return
        
        cls.init()
        if not cls._x11 or not cls._xext: return
        
        display = cls._x11.XOpenDisplay(None)
        if not display:
            print("Failed to open X Display")
            return
        
        ShapeInput = 2
        ShapeSet = 0
        
        try:
            if enabled:
                cls._xext.XShapeCombineRectangles(
                    display, win_id, ShapeInput, 0, 0, None, 0, ShapeSet, 0
                )
            else:
                cls._xext.XShapeCombineMask(
                    display, win_id, ShapeInput, 0, 0, None, ShapeSet
                )
            cls._x11.XFlush(display)
        finally:
            cls._x11.XCloseDisplay(display)


class DanmakuDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}
        self._emoticon_cache: dict[str, QImage | None] = {}
        self._emoticon_docs: dict[str, list[QTextDocument]] = {}
        self._network_manager = QNetworkAccessManager(self)

    def _get_document(self, message, width, font):
        msg_id = id(message)

        cached = self._cache.get(msg_id)
        if cached is not None:
            cached_message, doc = cached
            if cached_message is message:
                if doc.textWidth() != width:
                    doc.setTextWidth(width)
                return doc

        html_content = self.get_html_for_message(message)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        doc.setHtml(html_content)
        doc.setTextWidth(width)
        self._attach_emoticon_resource(doc, message)

        self._cache[msg_id] = (message, doc)
        return doc

    def forget_message(self, message) -> None:
        msg_id = id(message)
        cached = self._cache.get(msg_id)
        if cached is not None and cached[0] is message:
            self._cache.pop(msg_id, None)

    def _attach_emoticon_resource(self, doc: QTextDocument, message) -> None:
        if not isinstance(message, web_models.DanmakuMessage):
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
        options = option
        self.initStyleOption(options, index)
        
        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not msg_data:
            return

        painter.save()
        width = options.rect.width()
        if width <= 0: width = 300
        
        doc = self._get_document(msg_data, width, options.font)
        painter.translate(options.rect.x(), options.rect.y() + 1)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not msg_data:
            return QSize(0, 0)
            
        width = option.rect.width()
        if width <= 0:
            if self.parent() and hasattr(self.parent(), 'viewport'):
                width = self.parent().viewport().width()
        if width <= 0: width = 300
             
        doc = self._get_document(msg_data, width, option.font)
        return QSize(width, int(doc.size().height()) + 2)

    def get_html_for_message(self, message) -> str:
        if isinstance(message, web_models.DanmakuMessage):
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
            <p>{badges_html}<span class="user">{html.escape(message.uname, quote=True)}</span><span class="colon"> : </span><span class="content">{content_html}</span></p>
            """
        elif isinstance(message, web_models.GiftMessage):
            return f"""
            <style>
                .user {{ color: #FFD700; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .action {{ color: #FF66CC; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .gift {{ color: #FF66CC; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{message.uname}</span>
            <span class="action"> {message.action} </span>
            <span class="gift">{message.gift_name} x{message.num}</span></p>
            """
        elif isinstance(message, web_models.InteractWordV2Message):
            msg_type_map = {1: '进入直播间', 2: '关注了主播', 3: '分享了直播间'}
            action_text = msg_type_map.get(message.msg_type, '进入直播间')
            return f"""
            <style>
                .user {{ color: #AAAAAA; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                .info {{ color: #AAAAAA; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{message.username}</span>
            <span class="info"> {action_text}</span></p>
            """
        if hasattr(message, "uname") and hasattr(message, "msg"):
            user_color = self.get_user_color(message)
            return f"""
            <style>
                .user {{ color: {user_color}; font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .colon {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                .content {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; font-weight: 500; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(str(message.uname), quote=True)}</span><span class="colon"> : </span><span class="content">{html.escape(str(message.msg), quote=True)}</span></p>
            """
        return ""

    def get_user_color(self, danmaku_msg) -> str:
        if getattr(danmaku_msg, 'is_system_error', False):
            return "#FF5555"
        elif getattr(danmaku_msg, 'is_system_info', False):
            return "#AAAAAA"
            
        if getattr(danmaku_msg, "privilege_type", 0) > 0:
            return "#FFD700"
        elif getattr(danmaku_msg, "vip", False) or getattr(danmaku_msg, "svip", False):
            return "#FF69B4"
        elif getattr(danmaku_msg, "admin", False):
            return "#FF4500"
        return "#66CCFF"


class CustomSizeGrip(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet("background-color: transparent;")
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
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(255, 255, 255, 100)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(10, 10, 3, 3)
        painter.drawEllipse(6, 10, 3, 3)
        painter.drawEllipse(10, 6, 3, 3)


class DanmakuWidget(QWidget):
    danmaku_received = pyqtSignal(web_models.DanmakuMessage)
    gift_received = pyqtSignal(web_models.GiftMessage)
    interact_received = pyqtSignal(web_models.InteractWordV2Message)

    def __init__(self, room_id: int = 0, sessdata: str = ''):
        super().__init__()
        self.room_id = room_id
        self.sessdata = sessdata
        self.danmaku_client: Optional[DanmakuClient] = None
        self._audience_refresh_task: asyncio.Task[None] | None = None
        self._audience_generation = 0
        self._audience_snapshot: AudienceSnapshot | None = None
        self.is_gaming_mode = False
        self.layer_shell_lib = None
        self.layer_shell_disabled_reason = ""
        config = load_config()
        self.mirror_state = MirrorState()
        self.danmaku_logger = DanmakuLogger()
        self.mirror_server: MirrorServer | None = None
        self.mirror_enabled = bool(config.get("mirror_enabled", False))
        self.mirror_error = ""
        self.mirror_port = int(config.get("mirror_port", MIRROR_DEFAULT_PORT))
        self.layer_pos = QPoint(0, 0)
        
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30)
        self._resize_timer.timeout.connect(self._delayed_adjust_height)
        
        self.load_layer_shell_lib()

        self.setup_window_properties()
        self.init_ui()
        self.setup_tray_icon()
        self.update_gaming_mode_availability()
        self.setup_danmaku_client()
        if self.mirror_enabled:
            asyncio.create_task(self.start_mirror_server())
        
        if 'room_id' in config:
            self.room_id = config['room_id']
        
        self.room_id_input.setText(str(self.room_id))
        QTimer.singleShot(100, self.activate_layer_shell)
    
    def _delayed_adjust_height(self):
        if not self.is_gaming_mode:
             self.danmaku_list.scheduleDelayedItemsLayout()

    def load_layer_shell_lib(self):
        try:
            platform_name = QGuiApplication.platformName()
            current_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
            if should_disable_layer_shell(platform_name, current_desktop):
                self.layer_shell_disabled_reason = (
                    "GNOME/Mutter Wayland does not support wlr-layer-shell; fullscreen overlay is unsupported."
                )
                print(f"Layer Shell disabled: {self.layer_shell_disabled_reason}")
                return

            package_dir = os.path.dirname(__file__)
            lib_path = find_layer_shell_library(package_dir)
            if lib_path:
                self.layer_shell_lib = ctypes.CDLL(lib_path)
                self.layer_shell_lib.make_overlay.argtypes = [ctypes.c_void_p]
                self.layer_shell_lib.set_passthrough.argtypes = [ctypes.c_void_p, ctypes.c_bool]
                self.layer_shell_lib.set_anchor_position.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                    self.layer_shell_lib.set_keyboard_interactivity.argtypes = [ctypes.c_void_p, ctypes.c_bool]
            else:
                print(f"Layer Shell library not found at: {os.path.join(package_dir, LAYER_SHELL_LIBRARY_NAME)}")
        except Exception as e:
            print(f"Failed to load Layer Shell library: {e}")

    def activate_layer_shell(self):
        if self.layer_shell_lib:
            try:
                self.winId()
                handle = self.windowHandle()
                if handle:
                    cpp_ptr = sip.unwrapinstance(handle)
                    self.layer_shell_lib.make_overlay(ctypes.c_void_p(cpp_ptr))
                    if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                        self.layer_shell_lib.set_keyboard_interactivity(ctypes.c_void_p(cpp_ptr), True)
                    if hasattr(self.layer_shell_lib, 'set_anchor_position'):
                        self.layer_shell_lib.set_anchor_position(ctypes.c_void_p(cpp_ptr), self.layer_pos.x(), self.layer_pos.y())
            except Exception as e:
                print(f"Error activating Layer Shell: {e}")

    def setup_window_properties(self):
        self.resize(300, 450)
        screen_geo = QApplication.primaryScreen().geometry()
        initial_x = screen_geo.width() - 330
        initial_y = 100
        self.move(screen_geo.x() + initial_x, screen_geo.y() + initial_y)
        self.layer_pos = QPoint(initial_x, initial_y)
        self.setWindowTitle("Danmaku Overlay")
        
        flags = (
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Window 
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        if not self.is_gaming_mode:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 8, 8)
            super().paintEvent(event)

    def init_ui(self):
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

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

        self.connect_button = QPushButton("连接")
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.setCheckable(True)
        self.connect_button.setStyleSheet(btn_style)
        self.connect_button.clicked.connect(self.toggle_connection)
        
        self.gaming_mode_btn = QPushButton("锁定穿透")
        self.gaming_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gaming_mode_btn.setCheckable(True)
        self.gaming_mode_btn.setStyleSheet(btn_style)
        self.gaming_mode_btn.clicked.connect(self.toggle_gaming_mode)

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

        self.header_layout.addWidget(self.title_label)
        self.header_layout.addWidget(self.live_status_dot)
        self.header_layout.addWidget(self.room_id_input)
        self.header_layout.addWidget(self.connect_button)
        self.header_layout.addWidget(self.gaming_mode_btn)
        self.header_layout.addStretch()
        self.header_layout.addWidget(close_btn)

        self.danmaku_list = QListWidget()
        self.danmaku_list.setItemDelegate(DanmakuDelegate(self.danmaku_list))
        self.danmaku_list.setStyleSheet("background: transparent; border: none;")
        self.danmaku_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.danmaku_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.danmaku_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.danmaku_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.danmaku_list.setResizeMode(QListView.ResizeMode.Adjust)

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

        self.input_area = ModernInputWidget(self)
        self.input_area.send_requested.connect(self.trigger_send)
        self.input_area.emoticon_requested.connect(self.open_emoticon_picker)
        self.emoticon_picker = EmoticonPickerPopup(self)
        self.emoticon_picker.emoticon_selected.connect(self.trigger_send_live_emoticon)
        self.audience_status = AudienceStatusWidget(self)
        self.audience_popup = AudiencePopup(self)
        self.audience_status.audience_requested.connect(self.open_audience_popup)

        self.main_layout.addWidget(self.header_widget)
        self.main_layout.addWidget(self.audience_status)
        self.main_layout.addWidget(self.danmaku_list)
        self.main_layout.addWidget(self.input_area)
        
        self.setLayout(self.main_layout)
        
        self.danmaku_received.connect(self.add_message)
        self.gift_received.connect(self.add_message)
        self.interact_received.connect(self.add_message)
        
        self.input_dialog = DanmakuInputDialog(None)
        self.input_dialog.send_message.connect(self.trigger_send)

        self._dragging = False
        self._drag_position = QPoint()
        self._message_buffer = []
        
        self.size_grip = CustomSizeGrip(self)
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: transparent;
                width: 16px; 
                height: 16px;
            }
        """)

    def adjust_list_items_height(self, target_width: int = None):
        pass

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        
        icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icon.png')
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)
        
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

        tray_menu.addSeparator()

        self.tray_mock_action = QAction("发射模拟测试弹幕", self)
        self.tray_mock_action.triggered.connect(self.trigger_mock_danmaku)
        tray_menu.addAction(self.tray_mock_action)

        self.tray_open_logs_action = QAction("打开弹幕日志目录", self)
        self.tray_open_logs_action.triggered.connect(self.open_log_directory)
        tray_menu.addAction(self.tray_open_logs_action)

        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_activated)

    def add_system_message(self, message: str, level: str = "info"):
        class SystemMessage:
            def __init__(self, msg, level):
                self.uname = " [系统]"
                self.msg = msg
                self.privilege_type = 0
                self.vip = False
                self.svip = False
                self.admin = False
                self.is_system_error = (level == "error")
                self.is_system_info = (level == "info")
        
        msg_obj = SystemMessage(message, level)
        self.add_message(msg_obj)

    def is_gaming_mode_available(self) -> bool:
        return gaming_mode_available(
            QGuiApplication.platformName(),
            has_layer_shell=self.layer_shell_lib is not None,
            layer_shell_disabled=bool(self.layer_shell_disabled_reason),
        )

    def update_gaming_mode_availability(self):
        available = self.is_gaming_mode_available()
        self.gaming_mode_btn.setEnabled(available)
        self.tray_gaming_action.setEnabled(available)
        if not available:
            self.gaming_mode_btn.setText("穿透不可用")
            self.gaming_mode_btn.setChecked(False)
            self.tray_gaming_action.setChecked(False)
            self.gaming_mode_btn.setToolTip("GNOME Wayland 不支持全屏浮窗/锁定穿透，也不保证普通窗口置顶")
            self.tray_gaming_action.setToolTip("GNOME Wayland 不支持全屏浮窗/锁定穿透，也不保证普通窗口置顶")

    async def _send_danmaku_task(self, text: str):
        if self.danmaku_client:
            success, msg = await self.danmaku_client.send_danmaku(text)
            if not success:
                self.add_system_message(f"发送失败: {msg}", "error")
        else:
            self.add_system_message("未连接直播间，无法发送", "error")

    def trigger_send(self, text: str):
        if not text: return
        asyncio.create_task(self._send_danmaku_task(text))

    @qasync.asyncSlot()
    async def open_emoticon_picker(self):
        if not self.danmaku_client or not self.danmaku_client.session:
            self.add_system_message("未连接直播间，无法加载表情", "error")
            return

        self.emoticon_picker.set_loading()
        button_pos = self.input_area.emoticon_btn.mapToGlobal(QPoint(0, 0))
        self.emoticon_picker.move(
            button_pos.x() - self.emoticon_picker.width() + self.input_area.emoticon_btn.width(),
            button_pos.y() - self.emoticon_picker.height() - 8,
        )
        self.emoticon_picker.show()
        try:
            packages = await self.danmaku_client.fetch_live_emoticons()
        except Exception as e:
            self.emoticon_picker.set_error(str(e))
            return
        self.emoticon_picker.set_packages(packages)

    def trigger_send_live_emoticon(self, emoticon: LiveEmoticon):
        asyncio.create_task(self._send_live_emoticon_task(emoticon))

    async def _send_live_emoticon_task(self, emoticon: LiveEmoticon):
        if not self.danmaku_client:
            self.add_system_message("未连接直播间，无法发送", "error")
            return
        success, msg = await self.danmaku_client.send_live_emoticon(emoticon)
        if not success:
            self.add_system_message(f"发送失败: {msg}", "error")

    def open_input_dialog(self):
        self.input_dialog.show()
        self.input_dialog.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    @qasync.asyncSlot()
    async def quit_app(self):
        await self._stop_audience_refresh()
        if self.mirror_server is not None:
            await self.shutdown_mirror_server()
        QApplication.quit()

    def toggle_gaming_mode_from_tray(self, checked):
        if checked and not self.is_gaming_mode_available():
            self.show_gaming_mode_unavailable_message()
            self.tray_gaming_action.setChecked(False)
            return

        if self.is_gaming_mode != checked:
            self.set_gaming_mode(checked)

    def toggle_gaming_mode(self):
        new_state = not self.is_gaming_mode
        if new_state and not self.is_gaming_mode_available():
            self.show_gaming_mode_unavailable_message()
            self.gaming_mode_btn.setChecked(False)
            return

        self.set_gaming_mode(new_state)

    def show_gaming_mode_unavailable_message(self):
        self.tray_icon.showMessage(
            "Danmaku Overlay",
            "GNOME Wayland 不支持全屏浮窗/锁定穿透，也不保证普通窗口置顶。\n当前仅支持普通窗口移动。",
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )

    def set_gaming_mode(self, enabled: bool):
        self.is_gaming_mode = enabled
        current_geo = self.geometry()
        
        self.tray_gaming_action.setChecked(enabled)
        self.gaming_mode_btn.setChecked(enabled)
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window
        has_layer_shell = (self.layer_shell_lib is not None)

        if enabled:
            is_wayland = QGuiApplication.platformName().startswith('wayland')
            if not has_layer_shell and not is_wayland:
                flags |= Qt.WindowType.X11BypassWindowManagerHint
            
            flags |= Qt.WindowType.WindowTransparentForInput
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus

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
            
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            
            self.tray_icon.showMessage(
                "Danmaku Overlay", 
                "已进入穿透模式 (游戏覆盖)\n弹幕将显示在最顶层，鼠标操作将穿透。", 
                QSystemTrayIcon.MessageIcon.Information, 
                2000
            )
        else:
            self.header_widget.show()
            self.input_area.show()
            self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.danmaku_list.setStyleSheet("background: transparent; border: none;")

            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        
        if has_layer_shell:
            try:
                cpp_ptr = sip.unwrapinstance(self.windowHandle())
                self.layer_shell_lib.set_passthrough(ctypes.c_void_p(cpp_ptr), enabled)
                if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                   self.layer_shell_lib.set_keyboard_interactivity(ctypes.c_void_p(cpp_ptr), not enabled)

                self.layout().activate()
                self.danmaku_list.update()
                self.update()
                
            except Exception as e:
                print(f"Failed to set Wayland passthrough: {e}")
                
        else:
            self.hide()
            self.setWindowFlags(flags)
            
            def restore_window_state():
                self.setGeometry(current_geo)
                self.show()
                self.raise_()
                if not enabled:
                    self.activateWindow()

                try:
                    if QGuiApplication.platformName() == 'xcb':
                        wid = int(self.winId())
                        if wid > 0:
                            X11Helper.set_click_through(wid, enabled)
                except Exception as e:
                    print(f"Failed to set platform settings: {e}")

            QTimer.singleShot(50, restore_window_state)

        self._sync_audience_visibility()

    def mousePressEvent(self, event):
        if not self.is_gaming_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.layer_shell_lib is None and QGuiApplication.platformName().startswith("wayland"):
                handle = self.windowHandle()
                if handle and hasattr(handle, "startSystemMove") and handle.startSystemMove():
                    event.accept()
                    return

            self._dragging = True
            self._drag_local_pos = event.position().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            local_pos = event.position().toPoint()
            diff = local_pos - self._drag_local_pos

            has_layer_shell = (self.layer_shell_lib is not None)

            if has_layer_shell:
                try:
                    cpp_ptr = sip.unwrapinstance(self.windowHandle())

                    current_pos = self.layer_pos
                    target_pos = current_pos + diff

                    current_screen = self.windowHandle().screen()
                    if current_screen:
                        s_geo = current_screen.geometry()

                        min_x = s_geo.x() - self.width() + 50
                        max_x = s_geo.x() + s_geo.width() - 50
                        min_y = s_geo.y() - 50
                        max_y = s_geo.y() + s_geo.height() - 50

                        clamped_x = max(min_x, min(target_pos.x(), max_x))
                        clamped_y = max(min_y, min(target_pos.y(), max_y))

                        target_pos = QPoint(clamped_x, clamped_y)

                    self.layer_pos = target_pos

                    self.layer_shell_lib.set_anchor_position(
                        ctypes.c_void_p(cpp_ptr),
                        self.layer_pos.x(),
                        self.layer_pos.y()
                    )

                except Exception as e:
                    print(f"Wayland drag error: {e}")
            else:
                new_pos = event.globalPosition().toPoint() - self._drag_local_pos
                self.move(new_pos)

            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        self.size_grip.move(
            rect.right() - self.size_grip.width(),
            rect.bottom() - self.size_grip.height()
        )
        if not self.is_gaming_mode:
            self._resize_timer.start()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        if hasattr(self, '_message_buffer') and self._message_buffer:
            for item_type, item_data in self._message_buffer:
                if item_type == 'msg':
                    self.add_message(item_data)
                elif item_type == 'gift':
                    self.gift_received.emit(item_data)
                elif item_type == 'interact':
                    self.interact_received.emit(item_data)
            self._message_buffer.clear()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, self.activate_layer_shell)
    
    def setup_danmaku_client(self):
        self.danmaku_client = None

    def open_audience_popup(self):
        if self._audience_snapshot is None or self.is_gaming_mode:
            return
        self.audience_popup.set_snapshot(self._audience_snapshot)
        self.audience_popup.show_below(self.audience_status.online_button, self)

    async def _refresh_audience_once(
        self,
        client: DanmakuClient,
        generation: int,
    ) -> bool:
        try:
            snapshot = await client.fetch_audience_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Failed to refresh room audience data: %s", exc)
            return False

        if (
            generation != self._audience_generation
            or self.danmaku_client is not client
            or self.room_id != snapshot.room_id
        ):
            return False

        self._audience_snapshot = snapshot
        self.audience_status.set_snapshot(snapshot)
        self.audience_popup.set_snapshot(snapshot)
        self._sync_audience_visibility()
        return True

    async def _audience_refresh_loop(
        self,
        client: DanmakuClient,
        generation: int,
    ) -> None:
        while True:
            await self._refresh_audience_once(client, generation)
            await asyncio.sleep(AUDIENCE_REFRESH_INTERVAL_SECONDS)

    async def _start_audience_refresh(self, client: DanmakuClient) -> None:
        await self._stop_audience_refresh()
        generation = self._audience_generation
        self._audience_refresh_task = asyncio.create_task(
            self._audience_refresh_loop(client, generation)
        )

    async def _stop_audience_refresh(self) -> None:
        self._audience_generation += 1
        task = self._audience_refresh_task
        self._audience_refresh_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _sync_audience_visibility(self) -> None:
        visible = (not self.is_gaming_mode) and (self._audience_snapshot is not None)
        self.audience_status.setVisible(visible)
        if not visible:
            self.audience_popup.hide()

    def on_danmaku_received(self, client, message: web_models.DanmakuMessage):
        if self.danmaku_client is not client:
            return
        if self._dragging:
            self._message_buffer.append(('msg', message))
        else:
            self.danmaku_received.emit(message)

    def on_gift_received(self, client, gift_msg: web_models.GiftMessage):
        if self.danmaku_client is not client:
            return
        if self._dragging:
            self._message_buffer.append(('gift', gift_msg))
        else:
            self.gift_received.emit(gift_msg)

    def on_interact_received(self, client, interact_msg: web_models.InteractWordV2Message):
        if self.danmaku_client is not client:
            return
        if self._dragging:
            self._message_buffer.append(('interact', interact_msg))
        else:
            self.interact_received.emit(interact_msg)

    def add_message(self, message, _from_buffer=False):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, message)
        self.danmaku_list.addItem(item)

        if self.danmaku_list.count() > 200:
            removed_item = self.danmaku_list.takeItem(0)
            if removed_item is not None:
                delegate = self.danmaku_list.itemDelegate()
                if hasattr(delegate, "forget_message"):
                    delegate.forget_message(removed_item.data(Qt.ItemDataRole.UserRole))

        self.danmaku_list.scrollToBottom()

        entry = self.mirror_state.add_message(message)
        if self.mirror_server is not None:
            self.mirror_server.publish_append(entry)

        if hasattr(self, "danmaku_logger") and self.danmaku_logger is not None:
            self.danmaku_logger.log_message(message)

    def trigger_mock_danmaku(self):
        mock_items = [
            MockMessageGenerator.create_mock_danmaku(),
            MockMessageGenerator.create_mock_danmaku(is_guard=True),
            MockMessageGenerator.create_mock_gift(),
            MockMessageGenerator.create_mock_interact(),
        ]
        for item in mock_items:
            self.add_message(item)
        self.add_system_message("已发射模拟测试弹幕与礼物效果", "info")

    def open_log_directory(self):
        if hasattr(self, "danmaku_logger") and self.danmaku_logger is not None:
            log_dir = self.danmaku_logger.log_dir
            log_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    async def _ensure_live_control_room(self) -> int:
        auth_manager = AuthManager()
        session = None
        try:
            session, _from_keyring = await auth_manager.create_authenticated_session()
            anchor_room_id = await get_anchor_live_room_id(session)
        finally:
            if session is not None and not session.closed:
                await session.close()

        await self._connect_to_room_id(anchor_room_id)
        return anchor_room_id

    @qasync.asyncSlot()
    async def open_live_control(self):
        try:
            anchor_room_id = await self._ensure_live_control_room()
        except Exception as e:
            self.add_system_message(f"无法打开直播控制: {e}", "error")
            print(f"Open live control failed: {e}")
            return

        if not hasattr(self, '_live_control_dialog'):
            self._live_control_dialog = LiveControlDialog(self)
            self._live_control_dialog.live_status_changed.connect(self.set_live_status_indicator)
        self._live_control_dialog.set_room_id(anchor_room_id)
        self._live_control_dialog.show()
        self._live_control_dialog.raise_()
        self._live_control_dialog.activateWindow()

    def open_mirror_settings(self):
        if not hasattr(self, '_mirror_settings_dialog'):
            self._mirror_settings_dialog = MirrorSettingsDialog(self)
        self._mirror_settings_dialog.refresh()
        self._mirror_settings_dialog.show()
        self._mirror_settings_dialog.raise_()
        self._mirror_settings_dialog.activateWindow()

    async def start_mirror_server(self):
        if self.mirror_server is not None:
            return
        server = MirrorServer(self.mirror_state, host="127.0.0.1", port=self.mirror_port)
        try:
            await server.start()
        except Exception as exc:
            self.mirror_error = str(exc)
            self.mirror_server = None
            logger.error("Failed to start BiliHUD Mirror server: %s", exc)
            return
        self.mirror_server = server
        self.mirror_port = server.port
        self.mirror_error = ""
        logger.info("BiliHUD Mirror started at %s", server.url)

    async def shutdown_mirror_server(self):
        if self.mirror_server is None:
            return
        server = self.mirror_server
        self.mirror_server = None
        await server.stop()
        logger.info("BiliHUD Mirror server stopped")

    def open_qr_login(self):
        dialog = QRLoginDialog(self)
        dialog.login_success.connect(self.on_login_success)
        dialog.exec()

    def on_login_success(self, sessdata: str):
        self.sessdata = sessdata
        self.add_system_message("登录成功，请尝试重新连接直播间以应用最新身份", "info")

    def save_room_id(self):
        try:
            new_room_id = int(self.room_id_input.text().strip())
            if new_room_id != self.room_id:
                self.room_id = new_room_id
                save_config({'room_id': self.room_id, 'mirror_enabled': self.mirror_enabled, 'mirror_port': self.mirror_port})
        except ValueError:
            self.room_id_input.setText(str(self.room_id))

    def toggle_connection(self, checked):
        if checked:
            try:
                room_id = int(self.room_id_input.text().strip())
                self.room_id = room_id
                save_config({'room_id': self.room_id, 'mirror_enabled': self.mirror_enabled, 'mirror_port': self.mirror_port})
                asyncio.create_task(self.connect_to_room())
            except ValueError:
                self.connect_button.setChecked(False)
        else:
            asyncio.create_task(self.disconnect_from_room())

    async def connect_to_room(self):
        await self._connect_to_room_id(self.room_id)

    async def _connect_to_room_id(self, target_room_id: int):
        if self.danmaku_client and self.danmaku_client.room_id == target_room_id and self.danmaku_client.is_running:
            return

        if self.danmaku_client:
            await self.disconnect_from_room()

        self.room_id = target_room_id
        self.room_id_input.setText(str(target_room_id))

        self.danmaku_client = DanmakuClient(
            self.room_id,
            on_danmaku=self.on_danmaku_received,
            on_gift=self.on_gift_received,
            on_interact=self.on_interact_received,
            sessdata=self.sessdata
        )

        success = await self.danmaku_client.start()
        if success:
            self.connect_button.setChecked(True)
            self.connect_button.setText("已连接")
            self.add_system_message(f"已成功连接至直播间 {self.room_id}")
            await self._start_audience_refresh(self.danmaku_client)
        else:
            self.connect_button.setChecked(False)
            self.connect_button.setText("连接")
            self.add_system_message(f"连接直播间 {self.room_id} 失败", "error")
            await self._stop_audience_refresh()
            self._audience_snapshot = None
            self._sync_audience_visibility()

    async def disconnect_from_room(self):
        if self.danmaku_client:
            client_to_stop = self.danmaku_client
            self.danmaku_client = None
            await self._stop_audience_refresh()
            await client_to_stop.stop()
            self._audience_snapshot = None
            self._sync_audience_visibility()
            self.connect_button.setChecked(False)
            self.connect_button.setText("连接")
            self.add_system_message("已断开连接")

    def set_live_status_indicator(self, is_live: bool):
        self.live_status_dot.setVisible(is_live)
