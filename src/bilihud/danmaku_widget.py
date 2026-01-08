# -*- coding: utf-8 -*-
import sys
import os
import asyncio
import qasync
import ctypes
from ctypes import c_void_p, c_int, c_ulong
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu,
    QDialog, QSizePolicy, QAbstractItemView, QSizeGrip
)
from PyQt6.QtGui import (
    QCloseEvent, QFont, QColor, QPalette, QIcon, QCursor, 
    QLinearGradient, QBrush, QPainter, QAction
)
from PyQt6.QtCore import (
    QTimer, Qt, pyqtSignal, QSize, QPoint, QRect
)

import blivedm.models.web as web_models
from .danmaku_client import DanmakuClient
from .utils import load_config, save_config
from .qr_login_dialog import QRLoginDialog
from .auth import AuthManager

class ModernInputWidget(QWidget):
    """
    一个现代化的输入框组件，包含圆形输入框和发送按钮
    """
    send_requested = pyqtSignal(str)

    def __init__(self, parent=None, placeholder="发送弹幕..."):
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
        self.layout.addWidget(self.send_btn)

    def on_send(self):
        text = self.input_edit.text().strip()
        if text:
            self.send_requested.emit(text)
            self.input_edit.clear()

    def setFocus(self):
        self.input_edit.setFocus()


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
        
        self.input_widget = ModernInputWidget(self, placeholder="输入弹幕... [ESC关闭]")
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


class DanmakuItemWidget(QFrame):
    """单个弹幕项的自定义控件"""

    def __init__(self, message: web_models.DanmakuMessage | web_models.GiftMessage | web_models.InteractWordV2Message, parent=None):
        super().__init__(parent)
        
        if isinstance(message, web_models.DanmakuMessage):
            self.setup_danmaku_ui(message)
        elif isinstance(message, web_models.GiftMessage):
            self.setup_gift_ui(message)
        elif isinstance(message, web_models.InteractWordV2Message):
            self.setup_interact_ui(message)

    def setup_danmaku_ui(self, danmaku_msg: web_models.DanmakuMessage):
        # 设置框架样式 - 透明背景
        self.setStyleSheet("background-color: transparent;")

        # 主布局
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(5, 2, 5, 2)
        main_layout.setSpacing(4)

        # 文字阴影效果
        def create_shadow_effect(color=QColor(0, 0, 0, 200)):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(2)
            shadow.setOffset(1, 1)
            shadow.setColor(color)
            return shadow

        # 用户名标签
        username_label = QLabel(danmaku_msg.uname)
        username_label.setGraphicsEffect(create_shadow_effect())
        username_label.setStyleSheet(f"""
            QLabel {{
                color: {self.get_user_color(danmaku_msg)};
                font-weight: bold;
                font-size: 12px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }}
        """)

        # 冒号标签
        colon_label = QLabel(":")
        colon_label.setGraphicsEffect(create_shadow_effect())
        colon_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
        """)

        # 弹幕内容标签
        content_label = QLabel(danmaku_msg.msg)
        content_label.setGraphicsEffect(create_shadow_effect())
        content_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
        """)
        content_label.setWordWrap(True)

        # 添加控件到布局
        main_layout.addWidget(username_label)
        main_layout.addWidget(colon_label)
        main_layout.addWidget(content_label, 1) # content stretches

        self.setLayout(main_layout)

    def get_user_color(self, danmaku_msg: web_models.DanmakuMessage) -> str:
        """根据用户等级获取用户名颜色"""
        if getattr(danmaku_msg, 'is_system_error', False):
            return "#FF5555"  # 红色 (系统错误)
        elif getattr(danmaku_msg, 'is_system_info', False):
            return "#AAAAAA"  # 灰色 (系统信息)
            
        if danmaku_msg.privilege_type > 0:
            return "#FFD700"  # 金色 (舰队)
        elif danmaku_msg.vip or danmaku_msg.svip:
            return "#FF69B4"  # 粉色 (VIP)
        elif danmaku_msg.admin:
            return "#FF4500"  # 红橙色 (房管)
        return "#66CCFF"  # 天蓝色 (普通)

    def setup_gift_ui(self, gift_msg: web_models.GiftMessage):
        """设置礼物消息样式"""
        self.setStyleSheet("background-color: transparent;")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 2, 5, 2)
        main_layout.setSpacing(4)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(2); shadow.setOffset(1, 1); shadow.setColor(QColor(0,0,0,200))

        # 用户名
        user_label = QLabel(gift_msg.uname)
        user_label.setGraphicsEffect(shadow)
        user_label.setStyleSheet("color: #FFD700; font-weight: bold; font-size: 12px; font-family: 'Microsoft YaHei';")
        
        # 动作
        action_label = QLabel(f" {gift_msg.action} ")
        action_label.setStyleSheet("color: #FF66CC; font-size: 12px;")
        
        # 礼物名
        gift_label = QLabel(f"{gift_msg.gift_name} x{gift_msg.num}")
        gift_label.setStyleSheet("color: #FF66CC; font-weight: bold; font-size: 12px;")
        
        main_layout.addWidget(user_label)
        main_layout.addWidget(action_label)
        main_layout.addWidget(gift_label)
        main_layout.addStretch()

    def setup_interact_ui(self, interact_msg: web_models.InteractWordV2Message):
        """设置互动消息样式 (进房/关注)"""
        self.setStyleSheet("background-color: transparent;")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 2, 5, 2)
        main_layout.setSpacing(4)
        
        user_label = QLabel(interact_msg.username)
        user_label.setStyleSheet("color: #AAAAAA; font-size: 11px; font-weight: bold;")
        
        msg_type_map = {1: '进入直播间', 2: '关注了主播', 3: '分享了直播间'}
        action_text = msg_type_map.get(interact_msg.msg_type, '进入直播间')
        
        info_label = QLabel(f" {action_text}")
        info_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        
        main_layout.addWidget(user_label)
        main_layout.addWidget(info_label)
        main_layout.addStretch()


class DanmakuWidget(QWidget):
    """弹幕显示窗口"""

    danmaku_received = pyqtSignal(web_models.DanmakuMessage)
    gift_received = pyqtSignal(web_models.GiftMessage)
    interact_received = pyqtSignal(web_models.InteractWordV2Message)

    def __init__(self, room_id: int = 0, sessdata: str = ''):
        super().__init__()
        self.room_id = room_id
        self.sessdata = sessdata
        self.danmaku_client: Optional[DanmakuClient] = None
        self.is_gaming_mode = False
        
        self.setup_window_properties()
        self.init_ui()
        self.setup_tray_icon()
        self.setup_danmaku_client()
        
        # 加载保存的配置
        config = load_config()
        if 'room_id' in config:
            self.room_id = config['room_id']
        
        # 初始化房间号
        self.room_id_input.setText(str(self.room_id))

    def setup_window_properties(self):
        """设置基本的窗口属性"""
        self.resize(300, 450)
        # 居中屏幕
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(
            screen_geo.width() - 330, # 默认靠右一些
            100
        )
        self.setWindowTitle("Danmaku Overlay")
        
        # 基础无边框和置顶设置
        # REMOVED: Qt.X11BypassWindowManagerHint to fix input focus
        flags = (
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Window # Using Window instead of Tool
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
        close_btn.clicked.connect(self.close)

        # 组装 Header
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addWidget(self.room_id_input)
        self.header_layout.addWidget(self.connect_button)
        self.header_layout.addWidget(self.gaming_mode_btn)
        self.header_layout.addStretch()
        self.header_layout.addWidget(close_btn)

        # --- 弹幕列表 ---
        self.danmaku_list = QListWidget()
        self.danmaku_list.setStyleSheet("background: transparent; border: none;")
        self.danmaku_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.danmaku_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.danmaku_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.danmaku_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)

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

        # 组装 Main
        self.main_layout.addWidget(self.header_widget)
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
        
        # 大小调整手柄
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: transparent;
                width: 16px; 
                height: 16px;
            }
        """)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # 1. 更新SizeGrip位置
        rect = self.rect()
        self.size_grip.move(
            rect.right() - self.size_grip.width(),
            rect.bottom() - self.size_grip.height()
        )
        
        # 2. 在非穿透模式下，根据宽度动态调整列表项高度以支持换行
        if not self.is_gaming_mode:
            self.adjust_list_items_height()

    def adjust_list_items_height(self):
        """重新计算所有列表项的高度"""
        # 获取列表视口宽度（减去滚动条可能的宽度，虽然我们隐藏了滚动条）
        width = self.danmaku_list.viewport().width()
        if width <= 0: return

        count = self.danmaku_list.count()
        for i in range(count):
            item = self.danmaku_list.item(i)
            widget = self.danmaku_list.itemWidget(item)
            if widget:
                # 临时固定宽度以计算正确的高度
                widget.setFixedWidth(width)
                size_hint = widget.sizeHint()
                # 恢复宽度限制
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(16777215) 
                
                # 如果高度变化了，更新Item
                if item.sizeHint().height() != size_hint.height():
                    item.setSizeHint(size_hint)


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
        if not text: return
        asyncio.create_task(self._send_danmaku_task(text))

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

    def quit_app(self):
        QApplication.quit()

    def toggle_gaming_mode_from_tray(self, checked):
        """从托盘切换游戏模式"""
        # 避免递归更新
        if self.is_gaming_mode != checked:
            self.set_gaming_mode(checked)

    def toggle_gaming_mode(self):
        """切换鼠标穿透/游戏模式"""
        new_state = not self.is_gaming_mode
        self.set_gaming_mode(new_state)

    def set_gaming_mode(self, enabled: bool):
        self.is_gaming_mode = enabled
        
        # 保存当前位置和大小
        current_geo = self.geometry()
        
        # 同步各按钮状态
        self.tray_gaming_action.setChecked(enabled)
        self.gaming_mode_btn.setChecked(enabled)
        
        # [Critical Fix] 重新构建Flags
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window

        if enabled:
            # --- 开启穿透模式 (Gaming Mode) ---
            
            # 1. 穿透模式核心Flags
            # X11BypassWindowManagerHint: 绕过WM，确保能在全屏游戏之上显示
            flags |= Qt.WindowType.X11BypassWindowManagerHint
            # WindowTransparentForInput: 输入事件穿透 (配合XShape)
            flags |= Qt.WindowType.WindowTransparentForInput
            # WindowDoesNotAcceptFocus: 拒绝焦点，防止抢占游戏输入
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus

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
            # 只是普通置顶无边框窗口
            
            # 2. UI调整
            self.header_widget.show()
            self.input_area.show()
            self.danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.danmaku_list.setStyleSheet("background: transparent; border: none;")

            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        
        # 1. 先进行销毁操作 (Hide & Set Flags)
        self.hide()
        self.setWindowFlags(flags)
        
        # 2. [Defer Fix] 延迟执行显示操作
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
                
            # XShape 穿透
            try:
                wid = int(self.winId())
                if wid > 0:
                    X11Helper.set_click_through(wid, enabled)
            except Exception as e:
                print(f"Failed to set X11 settings: {e}")

        # 使用 50ms 延时确保事件循环处理完窗口销毁
        QTimer.singleShot(50, restore_window_state)

    # --- 鼠标拖拽移动窗口逻辑 ---
    def mousePressEvent(self, event):
        if not self.is_gaming_mode and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    # --- 客户端逻辑 ---
    
    def setup_danmaku_client(self):
        self.danmaku_client = None

    @qasync.asyncSlot()
    async def toggle_connection(self):
        """切换连接状态"""
        if self.danmaku_client is None or not self.danmaku_client.client:
            # 连接
            try:
                self.room_id = int(self.room_id_input.text())
                self.room_id_input.setText(str(self.room_id))
                
                self.danmaku_client = DanmakuClient(self.room_id, self.sessdata)
                self.danmaku_client.set_danmaku_callback(self.on_danmaku_received)
                self.danmaku_client.set_gift_callback(self.on_gift_received)
                self.danmaku_client.set_interact_callback(self.on_interact_received)
                self.danmaku_client.set_login_failed_callback(self.on_login_failed)
                
                # 保存房间号
                save_config({'room_id': self.room_id})
                
                # Update UI to connecting state
                self.connect_button.setText("连接中...")
                self.connect_button.setEnabled(False)
                
                await self.danmaku_client.start()
                
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
            except Exception as e:
                self.connect_button.setText("连接")
                self.connect_button.setEnabled(True)
                print(f"Connection failed: {e}")
        else:
            # 断开
            if self.danmaku_client is not None:
                await self.danmaku_client.stop()
            self.danmaku_client = None
            self.connect_button.setText("连接")
            self.connect_button.setChecked(False)
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
            
    def save_room_id(self):
        try:
            self.room_id = int(self.room_id_input.text())
        except ValueError:
            self.room_id_input.setText(str(self.room_id))

    def on_danmaku_received(self, danmaku_msg: web_models.DanmakuMessage):
        self.danmaku_received.emit(danmaku_msg)

    def on_gift_received(self, gift_msg: web_models.GiftMessage):
        self.gift_received.emit(gift_msg)

    def on_interact_received(self, interact_msg: web_models.InteractWordV2Message):
        self.interact_received.emit(interact_msg)

    def add_message(self, message):
        """通用添加消息方法"""
        item_widget = DanmakuItemWidget(message)
        
        # Pre-calculate height based on current viewport width
        width = self.danmaku_list.viewport().width()
        if width > 0:
            item_widget.setFixedWidth(width)
            size = item_widget.sizeHint()
            item_widget.setMinimumWidth(0)
            item_widget.setMaximumWidth(16777215)
        else:
            size = item_widget.sizeHint()

        item = QListWidgetItem()
        item.setSizeHint(size)
        
        self.danmaku_list.addItem(item)
        self.danmaku_list.setItemWidget(item, item_widget)
        self.danmaku_list.scrollToBottom()

        if self.danmaku_list.count() > 500:
            self.danmaku_list.takeItem(0)

    def open_qr_login(self):
        """打开扫码登录窗口"""
        dialog = QRLoginDialog(self)
        dialog.login_success.connect(self.on_login_success)
        dialog.exec()

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

    @qasync.asyncClose
    async def closeEvent(self, event: QCloseEvent):
        if self.danmaku_client:
            await self.danmaku_client.stop()
        event.accept()
