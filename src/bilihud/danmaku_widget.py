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
from .live_api import (
    AnchorLiveInfo,
    AreaInfo,
    LiveEmoticon,
    LiveStatus,
    fetch_anchor_live_info,
    fetch_area_list,
    get_anchor_live_room_id,
    start_live,
    stop_live,
    update_live_info,
)
from .live_audience import AUDIENCE_REFRESH_INTERVAL_SECONDS, AudienceSnapshot
from .live_control_dialog import LiveControlDialog
from .mirror_server import MirrorServer
from .mirror_settings_dialog import MirrorSettingsDialog
from .mirror_state import (
    MIRROR_DEFAULT_PORT,
    MirrorState,
)
from .obs_api import OBSController
from .qr_login_dialog import QRLoginDialog
from .utils import X11Helper, load_config, save_config

logger = logging.getLogger(__name__)


class CustomSizeGrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._resizing = False
        self._drag_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = True
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().bottomRight()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._resizing:
            new_bottom_right = event.globalPosition().toPoint() - self._drag_pos
            window = self.window()
            new_width = max(window.minimumWidth(), new_bottom_right.x() - window.x())
            new_height = max(window.minimumHeight(), new_bottom_right.y() - window.y())
            window.resize(new_width, new_height)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            event.accept()


class DanmakuDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc_cache = {}
        self._doc_access = {}
        self._access_counter = 0
        self.max_cache_size = 300

    def forget_message(self, message):
        key = id(message)
        self._doc_cache.pop(key, None)
        self._doc_access.pop(key, None)

    def _trim_cache_if_needed(self):
        if len(self._doc_cache) <= self.max_cache_size:
            return
        sorted_keys = sorted(self._doc_access.items(), key=lambda x: x[1])
        remove_count = len(self._doc_cache) - self.max_cache_size
        for key, _ in sorted_keys[:remove_count]:
            self._doc_cache.pop(key, None)
            self._doc_access.pop(key, None)

    def _get_document(self, option, index):
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return None

        key = id(message)
        self._access_counter += 1
        self._doc_access[key] = self._access_counter

        content_width = option.rect.width()
        if content_width <= 0:
            content_width = 300

        doc = self._doc_cache.get(key)
        if doc is None:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            
            badges_html = danmaku_author_badges_html(message)
            content_html = danmaku_message_content_html(message)
            
            if isinstance(message, web_models.DanmakuMessage):
                color = "#66CCFF"
                if getattr(message, "privilege_type", 0) > 0:
                    color = "#FFD700"
                elif getattr(message, "vip", False) or getattr(message, "svip", False):
                    color = "#FF69B4"
                elif getattr(message, "admin", False):
                    color = "#FF4500"
                
                uname = html.escape(message.uname)
                full_html = f"""
                <div style="font-family: sans-serif; font-size: 13px; line-height: 1.3; color: white; word-wrap: break-word;">
                    {badges_html}<span style="color: {color}; font-weight: bold;">{uname}</span>: {content_html}
                </div>
                """
            elif isinstance(message, web_models.GiftMessage):
                uname = html.escape(message.uname)
                gift_name = html.escape(message.gift_name)
                action = html.escape(message.action)
                full_html = f"""
                <div style="font-family: sans-serif; font-size: 13px; line-height: 1.3; color: #FFD700; font-weight: bold; background: rgba(255, 215, 0, 0.15); padding: 4px; border-radius: 4px;">
                    🎁 感谢 {uname} {action} {gift_name} x{message.num}
                </div>
                """
            elif isinstance(message, web_models.InteractWordV2Message):
                uname = html.escape(message.username)
                action_text = "进入直播间"
                if message.msg_type == 2:
                    action_text = "关注了主播"
                elif message.msg_type == 3:
                    action_text = "分享了直播间"
                full_html = f"""
                <div style="font-family: sans-serif; font-size: 11px; line-height: 1.2; color: rgba(255, 255, 255, 0.6);">
                    ✨ {uname} {action_text}
                </div>
                """
            else:
                msg_text = html.escape(getattr(message, 'msg', str(message)))
                color = "#AAAAAA"
                if getattr(message, 'is_system_error', False):
                    color = "#FF5555"
                full_html = f"""
                <div style="font-family: sans-serif; font-size: 12px; line-height: 1.3; color: {color}; font-style: italic;">
                    {msg_text}
                </div>
                """

            doc.setHtml(full_html)
            self._doc_cache[key] = doc
            self._trim_cache_if_needed()

        doc.setTextWidth(content_width)
        return doc

    def sizeHint(self, option, index):
        doc = self._get_document(option, index)
        if doc:
            return QSize(int(doc.idealWidth()), int(doc.size().height()) + 4)
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        doc = self._get_document(option, index)
        if doc:
            painter.save()
            painter.translate(option.rect.topLeft())
            doc.drawContents(painter)
            painter.restore()
        else:
            super().paint(painter, option, index)


class ModernInputWidget(QWidget):
    send_requested = pyqtSignal(str)
    emoticon_requested = pyqtSignal()

    def __init__(self, parent=None, placeholder="发送弹幕...", show_emoticon_button: bool = True):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setStyleSheet("""
            QLineEdit {
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 6px;
                padding: 4px 8px;
                background: rgba(0, 0, 0, 80);
                color: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: rgba(102, 204, 255, 200);
            }
        """)
        self.input.returnPressed.connect(self._on_send)
        layout.addWidget(self.input)

        if show_emoticon_button:
            self.emoticon_btn = QToolButton()
            self.emoticon_btn.setText("😀")
            self.emoticon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.emoticon_btn.setStyleSheet("""
                QToolButton {
                    border: 1px solid rgba(255, 255, 255, 40);
                    border-radius: 6px;
                    background: rgba(0, 0, 0, 80);
                    color: white;
                    font-size: 14px;
                    padding: 2px 6px;
                }
                QToolButton:hover {
                    background: rgba(255, 255, 255, 30);
                }
            """)
            self.emoticon_btn.clicked.connect(self.emoticon_requested.emit)
            layout.addWidget(self.emoticon_btn)

        self.send_btn = QPushButton("发送")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #00A1D6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #00B5E5;
            }
            QPushButton:pressed {
                background: #008CB8;
            }
        """)
        self.send_btn.clicked.connect(self._on_send)
        layout.addWidget(self.send_btn)

    def _on_send(self):
        text = self.input.text().strip()
        if text:
            self.send_requested.emit(text)
            self.input.clear()


class EmoticonPickerPopup(QDialog):
    emoticon_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(320, 240)
        self.setStyleSheet("""
            QDialog {
                background: #222222;
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        self.status_label = QLabel("加载表情包中...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 10);
                color: #CCCCCC;
                padding: 4px 8px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #00A1D6;
                color: white;
            }
        """)
        self.tab_widget.hide()
        layout.addWidget(self.tab_widget)

    def set_loading(self):
        self.tab_widget.hide()
        self.status_label.setText("加载表情包中...")
        self.status_label.show()

    def set_error(self, message: str):
        self.tab_widget.hide()
        self.status_label.setText(f"加载失败: {message}")
        self.status_label.show()

    def set_packages(self, packages: list):
        self.status_label.hide()
        self.tab_widget.clear()
        
        if not packages:
            self.status_label.setText("当前直播间暂无可用表情包")
            self.status_label.show()
            return

        for pkg in packages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("background: transparent; border: none;")
            
            container = QWidget()
            grid = QGridLayout(container)
            grid.setContentsMargins(4, 4, 4, 4)
            grid.setSpacing(6)
            
            row, col = 0, 0
            for emoticon in pkg.emoticons:
                btn = QToolButton()
                btn.setFixedSize(36, 36)
                btn.setToolTip(emoticon.emoji)
                
                if emoticon.url:
                    btn.setText("")
                    # Simple text fallback if image not loaded dynamically here
                    btn.setText(emoticon.emoji)
                else:
                    btn.setText(emoticon.emoji)
                    
                if emoticon.is_locked:
                    btn.setEnabled(False)
                    btn.setToolTip(f"{emoticon.emoji} (未解锁)")
                    btn.setStyleSheet("opacity: 0.4;")
                else:
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.clicked.connect(lambda _, e=emoticon: self._on_select(e))

                grid.addWidget(btn, row, col)
                col += 1
                if col >= 6:
                    col = 0
                    row += 1

            scroll.setWidget(container)
            self.tab_widget.addTab(scroll, pkg.pkg_name)

        self.tab_widget.show()

    def _on_select(self, emoticon):
        self.emoticon_selected.emit(emoticon)
        self.hide()


class DanmakuInputDialog(QDialog):
    send_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("发送直播弹幕")
        self.setFixedSize(360, 100)
        
        layout = QVBoxLayout(self)
        self.input_widget = ModernInputWidget(self, placeholder="输入弹幕内容发送到直播间...")
        self.input_widget.send_requested.connect(self._on_send)
        layout.addWidget(self.input_widget)

    def _on_send(self, text: str):
        self.send_message.emit(text)
        self.hide()


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
