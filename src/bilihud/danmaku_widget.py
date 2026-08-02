# -*- coding: utf-8 -*-
import asyncio
import ctypes
import html
import logging
import os
import sys
from collections.abc import Coroutine
from ctypes import c_int, c_ulong, c_void_p
from dataclasses import replace
from typing import Any, Optional

import blivedm.models.web as web_models
import PyQt6.sip as sip
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
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
from .auth import AuthenticationService
from .config import AppConfig, ConfigStore
from .danmaku_client import DanmakuClient
from .danmaku_format import (
    danmaku_author_badges_html,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
)
from .layer_shell_loader import (
    LAYER_SHELL_LIBRARY_NAME,
    find_layer_shell_library,
    gaming_mode_available,
    should_disable_layer_shell,
)
from .lifecycle import TaskScope, TaskSupervisor, cancel_task
from .live_api import get_anchor_live_room_id
from .live_audience import AudienceSnapshot
from .live_control_dialog import LiveControlDialog
from .live_emoticons import LiveEmoticon, LiveEmoticonPackage
from .mirror_server import MirrorServer
from .mirror_settings_dialog import MirrorSettingsDialog
from .mirror_state import MIRROR_ROUTE, MirrorState
from .qr_login_dialog import QRLoginDialog
from .services import AppServices, create_default_services

logger = logging.getLogger(__name__)
AUDIENCE_REFRESH_INTERVAL_SECONDS = 30.0


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

class X11Helper:
    """X11辅助类，用于直接调用XShape扩展实现点击穿透"""
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
            
            # XShapeCombineRectangles(display, dest, dest_kind, x_off, y_off, rectangles, n_rects, op, ordering)
            cls._xext.XShapeCombineRectangles.argtypes = [
                c_void_p, c_ulong, c_int, c_int, c_int, c_void_p, c_int, c_int, c_int
            ]
            
            # XShapeCombineMask(display, dest, dest_kind, x_off, y_off, src, op)
            cls._xext.XShapeCombineMask.argtypes = [
                c_void_p, c_ulong, c_int, c_int, c_int, c_void_p, c_int
            ]
        except Exception as e:
            print(f"X11 init failed: {e}")

    @classmethod
    def set_click_through(cls, win_id, enabled):
        """设置窗口是否通过Input Shape完全穿透"""
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
                # 设置输入形状为空（0个矩形），使窗口对输入事件完全透明
                cls._xext.XShapeCombineRectangles(
                    display, win_id, ShapeInput, 0, 0, None, 0, ShapeSet, 0
                )
            else:
                # 恢复默认输入形状（重置为None Mask），允许接收输入
                cls._xext.XShapeCombineMask(
                    display, win_id, ShapeInput, 0, 0, None, ShapeSet
                )
            cls._x11.XFlush(display)
        finally:
            cls._x11.XCloseDisplay(display)


class DanmakuDelegate(QStyledItemDelegate):
    """
    High-performance delegate with Caching.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {} # Map[id(message), (message, QTextDocument)]
        self._emoticon_cache: dict[str, QImage | None] = {}
        self._emoticon_docs: dict[str, list[QTextDocument]] = {}
        self._network_manager = QNetworkAccessManager(self)
        # We need to invalidate cache if width changes, but updating width on existing doc is cheap.

    def _get_document(self, message, width, font):
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

    def get_html_for_message(self, message) -> str:
        """Construct HTML content based on message type."""
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
        """根据用户等级获取用户名颜色"""
        if getattr(danmaku_msg, 'is_system_error', False):
            return "#FF5555"
        elif getattr(danmaku_msg, 'is_system_info', False):
            return "#AAAAAA"
            
        if danmaku_msg.privilege_type > 0:
            return "#FFD700"
        elif danmaku_msg.vip or danmaku_msg.svip:
            return "#FF69B4"
        elif danmaku_msg.admin:
            return "#FF4500"
        return "#66CCFF"


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

    danmaku_received = pyqtSignal(web_models.DanmakuMessage)
    gift_received = pyqtSignal(web_models.GiftMessage)
    interact_received = pyqtSignal(web_models.InteractWordV2Message)

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
        self._mirror_start_task: asyncio.Task[None] | None = None  # Startup task canceled before server cleanup.
        self._action_tasks: set[asyncio.Task[Any]] = set()  # Qt-triggered workflows owned by this widget.
        self._shutting_down = False  # Prevent new work from starting during application shutdown.
        self._shutdown_complete = False  # Makes repeated application stop requests idempotent.
        self.room_id = room_id  # Current room displayed and used by the client.
        self.sessdata = sessdata  # Optional session override supplied by the caller.
        self.services = services if services is not None else create_default_services()
        self.config_store: ConfigStore = self.services.config_store  # Typed settings boundary.
        self.auth_service: AuthenticationService = self.services.auth_service  # Shared auth boundary.
        self.danmaku_client: Optional[DanmakuClient] = None  # Client owned by this widget.
        self._audience_refresh_task: asyncio.Task[None] | None = None  # Cancelled on disconnect.
        self._audience_generation = 0
        self._audience_snapshot: AudienceSnapshot | None = None
        self._live_control_dialog: LiveControlDialog | None = None  # Reused live-control dialog owner.
        self._mirror_settings_dialog: MirrorSettingsDialog | None = None  # Reused Mirror settings owner.
        self._qr_login_dialog: QRLoginDialog | None = None  # Active modal QR-login dialog, if any.
        self.is_gaming_mode = False
        self.layer_shell_lib = None
        self.layer_shell_disabled_reason = ""
        config = self.config_store.load()
        self.mirror_state = MirrorState()
        self.mirror_server: MirrorServer | None = None  # Server lifecycle is owned by the widget.
        self.mirror_enabled = config.mirror_enabled  # Persisted startup preference.
        self.mirror_error = ""
        self.mirror_port = config.mirror_port  # Local port used by the Mirror server.
        # Track Layer Shell position manually because Qt frameGeometry() is unreliable (returns 0,0)
        self.layer_pos = QPoint(0, 0)
        
        # [Performance] Resize Debounce Timer
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30) # 30ms Debounce
        self._resize_timer.timeout.connect(self._delayed_adjust_height)
        
        # Load Layer Shell Library
        self.load_layer_shell_lib()

        self.setup_window_properties()
        self.init_ui()
        self.setup_tray_icon()
        self.update_gaming_mode_availability()
        self.setup_danmaku_client()
        
        # 加载保存的配置
        if config.room_id is not None:
            self.room_id = config.room_id
        
        # 初始化房间号
        self.room_id_input.setText(str(self.room_id))
        
        # Try to activate Layer Shell initially
        QTimer.singleShot(100, self.activate_layer_shell)

    async def start(self) -> None:
        """Start widget-owned background workflows after construction is complete."""
        if self._shutting_down or not self.mirror_enabled:
            return
        if self._mirror_start_task is None or self._mirror_start_task.done():
            self._mirror_start_task = self._task_scope.create_task(
                self.start_mirror_server(),
                name="mirror-startup",
            )

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
                
                # Define argument types for safety
                self.layer_shell_lib.make_overlay.argtypes = [ctypes.c_void_p]
                self.layer_shell_lib.set_passthrough.argtypes = [ctypes.c_void_p, ctypes.c_bool]
                self.layer_shell_lib.set_anchor_position.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                
                # Check if new function exists (for backward compatibility during dev)
                if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                    self.layer_shell_lib.set_keyboard_interactivity.argtypes = [ctypes.c_void_p, ctypes.c_bool]
            else:
                print(f"Layer Shell library not found at: {os.path.join(package_dir, LAYER_SHELL_LIBRARY_NAME)}")
        except OSError as e:
            err_msg = str(e)
            if "version" in err_msg and "Qt" in err_msg and "not found" in err_msg:
                print("\n" + "="*60)
                print("CRITICAL ERROR: Qt Version Mismatch Detected!")
                print(f"Error details: {e}")
                print("-" * 60)
                print("It seems you are using a pip-installed PyQt6 which conflicts with the system LayerShellQt library.")
                print("Solution: Please use the system's PyQt6 package instead.")
                print("  Fedora: sudo dnf install python3-pyqt6")
                print("  Ubuntu/Debian: sudo apt install python3-pyqt6")
                print("  Arch: sudo pacman -S python-pyqt6")
                print("Then recreate your venv with: python3 -m venv --system-site-packages .venv")
                print("="*60 + "\n")
            else:
                print(f"Failed to load Layer Shell library: {e}")
        except Exception as e:
            print(f"Failed to load Layer Shell library: {e}")

    def activate_layer_shell(self):
        """Invoke C++ bridge to promote window to Layer Shell Overlay"""
        if self.layer_shell_lib:
            try:
                self.winId() # Ensure handle created
                handle = self.windowHandle()
                if handle:
                    cpp_ptr = sip.unwrapinstance(handle)
                    self.layer_shell_lib.make_overlay(ctypes.c_void_p(cpp_ptr))
                    
                    # Ensure interactivity is enabled by default (for Normal Mode)
                    if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                        self.layer_shell_lib.set_keyboard_interactivity(ctypes.c_void_p(cpp_ptr), True)


                    # [Fix] Sync initial position to bridge immediately
                    # Because setAnchor(Top|Left) defaults to 0,0 margins if we don't set them
                    if hasattr(self.layer_shell_lib, 'set_anchor_position'):
                        # Important: layer_pos is relative to the screen we are on.
                        # We assume initial setup put us on primary screen consistent with layer_pos
                        self.layer_shell_lib.set_anchor_position(ctypes.c_void_p(cpp_ptr), self.layer_pos.x(), self.layer_pos.y())
                    

            except Exception as e:
                print(f"Error activating Layer Shell: {e}")

    def setup_window_properties(self):
        """设置基本的窗口属性"""
        self.resize(300, 450)
        # 居中屏幕
        screen_geo = QApplication.primaryScreen().geometry()
        
        # Initialize position relative to primary screen top-left
        initial_x = screen_geo.width() - 330
        initial_y = 100
        
        # Qt move expects global coordinates
        self.move(
            screen_geo.x() + initial_x, 
            screen_geo.y() + initial_y
        )
        self.layer_pos = QPoint(initial_x, initial_y)
        self.setWindowTitle("Danmaku Overlay")
        
        # 基础无边框和置顶设置
        flags = (
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Window 
        )
            
        self.setWindowFlags(flags)
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
        self.danmaku_received.connect(self.add_message)
        self.gift_received.connect(self.add_message)
        self.interact_received.connect(self.add_message)
        
        # 初始化全局输入框
        self.input_dialog = DanmakuInputDialog(None)
        self.input_dialog.send_message.connect(self.trigger_send)

        # 拖拽移动相关变量
        self._dragging = False
        self._drag_position = QPoint()
        self._message_buffer = [] # [Optimization] Buffer
        
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
        
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.tray_icon.activated.connect(self.on_tray_activated)

    def add_system_message(self, message: str, level: str = "info"):
        """添加系统消息到列表"""
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
        """实际执行发送弹幕的Task"""
        if self.danmaku_client:
            success, msg = await self.danmaku_client.send_danmaku(text)
            if success:
                # print(f"弹幕发送成功: {text}")
                # 可选：发送成功也显示一条本地回显，或者直接等服务器下发
                pass 
            else:
                self.add_system_message(f"发送失败: {msg}", "error")
                print(f"弹幕发送失败: {msg}")
        else:
              self.add_system_message("未连接直播间，无法发送", "error")
              print("未连接，无法发送")

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
        if self._shutting_down:
            return
        self._task_scope.create_task(
            self._send_live_emoticon_task(emoticon),
            name="send-live-emoticon",
        )

    async def _send_live_emoticon_task(self, emoticon: LiveEmoticon):
        if not self.danmaku_client:
            self.add_system_message("未连接直播间，无法发送", "error")
            return
        success, msg = await self.danmaku_client.send_live_emoticon(emoticon)
        if not success:
            self.add_system_message(f"发送失败: {msg}", "error")

    def open_input_dialog(self):
        """打开全局输入框"""
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
                await cancel_task(self._mirror_start_task)
            except Exception as exc:
                logger.exception("Failed to cancel Mirror startup")
                shutdown_errors.append(exc)
            self._mirror_start_task = None
            try:
                await self._stop_audience_refresh()
            except Exception as exc:
                logger.exception("Failed to stop audience refresh")
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

            client = self.danmaku_client
            if client is not None:
                try:
                    await client.stop()
                except Exception as exc:
                    logger.exception("Failed to close danmaku client")
                    shutdown_errors.append(exc)
                else:
                    self.danmaku_client = None
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

    def show_gaming_mode_unavailable_message(self):
        self.tray_icon.showMessage(
            "Danmaku Overlay",
            "GNOME Wayland 不支持全屏浮窗/锁定穿透，也不保证普通窗口置顶。\n当前仅支持普通窗口移动。",
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )

    def set_gaming_mode(self, enabled: bool):
        self.is_gaming_mode = enabled
        
        # 保存当前位置和大小
        current_geo = self.geometry()
        
        # 同步各按钮状态
        self.tray_gaming_action.setChecked(enabled)
        self.gaming_mode_btn.setChecked(enabled)
        
        # [Critical Fix] 重新构建Flags
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window

        # Check if we are using Layer Shell
        has_layer_shell = (self.layer_shell_lib is not None)

        if enabled:
            # --- 开启穿透模式 (Gaming Mode) ---
            
            # 1. 穿透模式核心Flags
            # X11BypassWindowManagerHint: 绕过WM，确保能在全屏游戏之上显示
            # ONLY use this if NOT using Layer Shell (i.e. on X11)
            # AND strictly ensure we are NOT on Wayland (setting this on Wayland causes crash)
            is_wayland = QGuiApplication.platformName().startswith('wayland')
            if not has_layer_shell and not is_wayland:
                flags |= Qt.WindowType.X11BypassWindowManagerHint
            
            # WindowTransparentForInput: 输入事件穿透 (配合XShape)
            # On Wayland with LayerShell, we use the bridge to set mask.
            # On X11, we use XShape. 
            flags |= Qt.WindowType.WindowTransparentForInput
            # WindowDoesNotAcceptFocus: 拒绝焦点，防止抢占游戏输入
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
            
            # For Layer Shell, we rely on setLayer(Overlay) which is done in activate_layer_shell

            # 2. UI调整
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
            
            # 3. 属性设置
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True) # 防止show()时触发activate导致日志警告
            
            self.tray_icon.showMessage(
                "Danmaku Overlay", 
                "已进入穿透模式 (游戏覆盖)\n弹幕将显示在最顶层，鼠标操作将穿透。", 
                QSystemTrayIcon.MessageIcon.Information, 
                2000
            )
        else:
            # --- 关闭穿透模式 (Normal Mode) ---
            
            # 1. Normal Mode Flags
            # 不需要 X11Bypass，也不需要 TransparentForInput
            # 普通无边框窗口；在 GNOME Wayland 上，置顶 hint 可能被 compositor 忽略。
            
            # 2. UI调整
            self.header_widget.show()
            self.input_area.show()
            self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.danmaku_list.setStyleSheet("background: transparent; border: none;")

            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        
        if has_layer_shell:
            # --- Wayland Layer Shell Mode ---
            # Do NOT call setWindowFlags or hide() as it recreates the window surface
            # and breaks the Layer Shell integration.
            
            # Apply native input region changes
            try:
                cpp_ptr = sip.unwrapinstance(self.windowHandle())
                self.layer_shell_lib.set_passthrough(ctypes.c_void_p(cpp_ptr), enabled)
                
                # Toggle keyboard interactivity
                # Enabled (Gaming Mode) -> No keyboard
                # Disabled (Normal Mode) -> OnDemand keyboard
                if hasattr(self.layer_shell_lib, 'set_keyboard_interactivity'):
                   self.layer_shell_lib.set_keyboard_interactivity(ctypes.c_void_p(cpp_ptr), not enabled)

                # Force visual update since we skipped setWindowFlags/hide/show
                # This ensures the dashed border stylesheet and layout changes (hidden header) are applied immediately
                self.layout().activate()
                self.danmaku_list.update()
                self.update()
                
            except Exception as e:
                print(f"Failed to set Wayland passthrough: {e}")
                
        else:
            # --- X11 / Standard Mode ---
            # Recreate window to apply flags (necessary for X11Bypass etc on XCB)
            self.hide()
            self.setWindowFlags(flags)
            
            # 延迟执行显示操作
            # 切换 BypassWindowManagerHint 会导致 Native Window 销毁重建
            # 如果同步执行 show()，可能导致 X11 状态未同步而无法映射窗口
            def restore_window_state():
                # 恢复位置 (在窗口重建后应用)
                self.setGeometry(current_geo)
                
                # 显示并置顶
                self.show()
                self.raise_()
                
                if not enabled:
                    self.activateWindow()

                # 平台相关穿透逻辑 (X11)
                try:
                    if QGuiApplication.platformName() == 'xcb':
                        wid = int(self.winId())
                        if wid > 0:
                            X11Helper.set_click_through(wid, enabled)
                except Exception as e:
                    print(f"Failed to set platform settings: {e}")

            # 这里的延时是必须的
            QTimer.singleShot(50, restore_window_state)

        self._sync_audience_visibility()

    # --- 鼠标拖拽移动窗口逻辑 (Simple & Robust) ---
    def mousePressEvent(self, event):
        if not self.is_gaming_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.layer_shell_lib is None and QGuiApplication.platformName().startswith("wayland"):
                handle = self.windowHandle()
                if handle and hasattr(handle, "startSystemMove") and handle.startSystemMove():
                    event.accept()
                    return

            self._dragging = True
            # [Simple Local Drag]
            # Just track the local position. 1:1 feel.
            self._drag_local_pos = event.position().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            # Local Drag
            local_pos = event.position().toPoint()
            diff = local_pos - self._drag_local_pos

            # [Spike Filter]
            # Ignore massive jumps > 100px.
            #if diff.manhattanLength() > 100:
            #    return

            has_layer_shell = (self.layer_shell_lib is not None)

            if has_layer_shell:
                try:
                    cpp_ptr = sip.unwrapinstance(self.windowHandle())

                    current_pos = self.layer_pos
                    target_pos = current_pos + diff

                    # [Screen Bounds Clamping]
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
        
        # 1. 更新SizeGrip位置
        rect = self.rect()
        self.size_grip.move(
            rect.right() - self.size_grip.width(),
            rect.bottom() - self.size_grip.height()
        )
        
        # 2. Debounced Layout Update
        if not self.is_gaming_mode:
            self._resize_timer.start()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        
        # [Message Buffering]
        # Process all types of messages
        if self._message_buffer:
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
        # Re-activate Layer Shell when shown to ensure overlay/input works
        # Delayed to ensure window is mapped
        QTimer.singleShot(100, self.activate_layer_shell)
    
    def setup_danmaku_client(self):
        self.danmaku_client = None

    def _persist_config(self, config: AppConfig) -> bool:
        """Persist one complete typed configuration value through the injected store."""
        return self.config_store.save(config)

    def _update_persisted_config(self, *, room_id: int | None = None, mirror_enabled: bool | None = None) -> bool:
        """Update room or Mirror settings without dropping unrelated saved fields."""
        current = self.config_store.load()
        updated = replace(
            current,
            room_id=current.room_id if room_id is None else room_id,
            mirror_enabled=current.mirror_enabled if mirror_enabled is None else mirror_enabled,
            mirror_port=self.mirror_port,
        )
        return self._persist_config(updated)

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
        self._audience_refresh_task = self._task_scope.create_task(
            self._audience_refresh_loop(client, generation),
            name="audience-refresh",
        )

    async def _stop_audience_refresh(self) -> None:
        self._audience_generation += 1
        task = self._audience_refresh_task
        self._audience_refresh_task = None
        if task is not None:
            await cancel_task(task)
        self._audience_snapshot = None
        self.audience_popup.hide()
        self.audience_status.clear()

    def _sync_audience_visibility(self) -> None:
        visible = self._audience_snapshot is not None and not self.is_gaming_mode
        self.audience_status.setVisible(visible)
        if not visible:
            self.audience_popup.hide()

    def _wire_danmaku_client(self, client: DanmakuClient):
        client.set_danmaku_callback(self.on_danmaku_received)
        client.set_gift_callback(self.on_gift_received)
        client.set_interact_callback(self.on_interact_received)
        client.set_login_failed_callback(self.on_login_failed)

    def _set_connecting_ui(self):
        self.connect_button.setText("连接中...")
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

    def _has_active_danmaku_connection(self) -> bool:
        client = self.danmaku_client
        return client is not None and client.is_running

    async def _connect_to_room_id(self, room_id: int):
        if room_id <= 0:
            raise ValueError("直播间号无效")

        if self._has_active_danmaku_connection() and self.room_id == room_id:
            self.room_id_input.setText(str(room_id))
            self._set_connected_ui()
            client = self.danmaku_client
            if client is None:
                return
            if self._audience_refresh_task is None:
                await self._start_audience_refresh(client)
            return

        if self.danmaku_client is not None and self.danmaku_client.client:
            await self._disconnect_current_room()

        self.room_id = room_id
        self.room_id_input.setText(str(room_id))
        client = DanmakuClient(room_id, self.sessdata, auth_service=self.auth_service)
        self.danmaku_client = client
        self._wire_danmaku_client(client)
        self._update_persisted_config(room_id=room_id)
        self._set_connecting_ui()
        try:
            await client.start()
        except BaseException:
            try:
                await client.stop()
            except BaseException:
                logger.exception("Failed to clean up danmaku client after connection failure")
            else:
                if self.danmaku_client is client:
                    self.danmaku_client = None
            self._set_disconnected_ui()
            raise
        self._set_connected_ui()
        await self._start_audience_refresh(client)

    async def _disconnect_current_room(self):
        self.connect_button.setEnabled(False)
        client = self.danmaku_client
        previous_snapshot = self._audience_snapshot
        await self._stop_audience_refresh()
        try:
            if client is not None:
                await client.stop()
        except Exception as e:
            self._set_connected_ui()
            if client is not None:
                await self._start_audience_refresh(client)
            if previous_snapshot is not None:
                self._audience_snapshot = previous_snapshot
                self.audience_status.set_snapshot(previous_snapshot)
                self.audience_popup.set_snapshot(previous_snapshot)
                self._sync_audience_visibility()
            self.add_system_message(f"断开失败: {e}", "error")
            print(f"Disconnect failed: {e}")
            raise
        self.danmaku_client = None
        self._set_disconnected_ui()

    @pyqtSlot()
    def toggle_connection(self) -> asyncio.Task[None] | None:
        """Schedule the room connection workflow under the widget owner."""
        if self._shutting_down:
            return None
        return self._create_action_task(self._toggle_connection(), name="toggle-connection")

    async def _toggle_connection(self) -> None:
        """切换连接状态"""
        if self._shutting_down:
            return
        if not self._has_active_danmaku_connection():
            # 连接
            try:
                await self._connect_to_room_id(int(self.room_id_input.text()))
            except Exception as e:
                self._set_disconnected_ui()
                print(f"Connection failed: {e}")
        else:
            # 断开
            try:
                await self._disconnect_current_room()
            except Exception:
                return
            
    def save_room_id(self):
        try:
            self.room_id = int(self.room_id_input.text())
        except ValueError:
            self.room_id_input.setText(str(self.room_id))

    def on_danmaku_received(self, danmaku_msg: web_models.DanmakuMessage):
        if self._dragging:
            self._message_buffer.append(('msg', danmaku_msg))
        else:
            self.danmaku_received.emit(danmaku_msg)

    def on_gift_received(self, gift_msg: web_models.GiftMessage):
        if self._dragging:
            self._message_buffer.append(('gift', gift_msg))
        else:
            self.gift_received.emit(gift_msg)

    def on_interact_received(self, interact_msg: web_models.InteractWordV2Message):
        if self._dragging:
            self._message_buffer.append(('interact', interact_msg))
        else:
            self.interact_received.emit(interact_msg)

    def add_message(self, message, _from_buffer=False):
        """通用添加消息方法 (Delegate Version)"""
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

        entry = self.mirror_state.add_message(message)
        if self.mirror_server is not None:
            self.mirror_server.publish_append(entry)

    async def _ensure_live_control_room(self) -> int:
        """Resolve the authenticated anchor room and close the temporary session."""
        session = None
        try:
            session, _from_keyring = await self.auth_service.create_authenticated_session()
            anchor_room_id = await get_anchor_live_room_id(session)
        finally:
            if session is not None and not session.closed:
                await session.close()

        await self._connect_to_room_id(anchor_room_id)
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
            self.add_system_message(f"无法打开直播控制: {e}", "error")
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
        if self._shutting_down:
            return
        if self._mirror_settings_dialog is None:
            self._mirror_settings_dialog = MirrorSettingsDialog(self)
            self._mirror_settings_dialog.mirror_enabled_requested.connect(
                self._schedule_mirror_toggle
            )
        dialog = self._mirror_settings_dialog
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @property
    def mirror_url(self) -> str:
        return f"http://127.0.0.1:{self.mirror_port}{MIRROR_ROUTE}"

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
        await self.set_mirror_enabled(self.mirror_server is None)
        self.refresh_mirror_settings()

    def _schedule_mirror_toggle(self, enabled: bool) -> None:
        """Schedule a Mirror settings request from the presentation signal."""
        if self._shutting_down:
            return
        self._create_action_task(
            self.set_mirror_enabled(enabled),
            name="toggle-mirror-settings",
        )

    async def set_mirror_enabled(self, enabled: bool):
        if enabled:
            self.mirror_enabled = True
            self.mirror_error = ""
            self._update_persisted_config(mirror_enabled=True)
            await self.start_mirror_server()
        else:
            self.mirror_enabled = False
            self.mirror_error = ""
            self._update_persisted_config(mirror_enabled=False)
            await cancel_task(self._mirror_start_task)
            self._mirror_start_task = None
            await self.shutdown_mirror_server()
            self.add_system_message("BiliHUD Mirror 已停止。")
        self.refresh_mirror_settings()

    def refresh_mirror_settings(self):
        if self._mirror_settings_dialog is not None:
            self._mirror_settings_dialog.refresh()

    def mirror_status_text(self) -> str:
        if self.mirror_server is not None:
            return "已启动"
        if self.mirror_error:
            return f"启动失败: {self.mirror_error}"
        if self.mirror_enabled:
            return "已启用，当前未启动"
        return "未启动"

    async def start_mirror_server(self) -> None:
        if self._shutting_down:
            return

        startup_task = self._mirror_start_task
        if startup_task is not None and startup_task is not asyncio.current_task() and not startup_task.done():
            await startup_task
            return
        if self.mirror_server is not None:
            self.refresh_mirror_settings()
            return

        server = MirrorServer(self.mirror_state, port=self.mirror_port)
        try:
            await server.start()
        except OSError as exc:
            self.mirror_error = str(exc)
            self.add_system_message(f"BiliHUD Mirror 启动失败: {exc}", "error")
            self.refresh_mirror_settings()
            return

        self.mirror_server = server
        self.mirror_error = ""
        self.refresh_mirror_settings()
        self.add_system_message(f"BiliHUD Mirror 已启动: {server.url}")

    async def stop_mirror_server(self) -> None:
        await self.set_mirror_enabled(False)

    async def shutdown_mirror_server(self) -> None:
        if self.mirror_server is None:
            return

        server = self.mirror_server
        await server.stop()
        self.mirror_server = None
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
        
        # 自动重连逻辑 (如果已连接)
        if self.danmaku_client and self.danmaku_client.session:
            # 简单处理：提示用户
            pass

    def on_login_failed(self, msg: str):
        """登录失效回调"""
        self.tray_icon.showMessage(
            "登录失效", 
            msg, 
            QSystemTrayIcon.MessageIcon.Warning, 
            5000
        )
        self.add_system_message(msg, "error")

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
