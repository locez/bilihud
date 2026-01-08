# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QWidget, 
    QGraphicsDropShadowEffect
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor
import qasync
import asyncio
from .auth import AuthManager

class QRLoginDialog(QDialog):
    login_success = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫码登录 Bilibili")
        self.setFixedSize(320, 400)
        
        # Modern window styling
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.auth_manager = AuthManager()
        self.qrcode_key = None
        
        self.init_ui()
        
        # Timer for polling
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(2000) # Poll every 2 seconds
        self.poll_timer.timeout.connect(self.check_status)
        
    def init_ui(self):
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
        super().showEvent(event)
        self.refresh_qrcode()
        
    def closeEvent(self, event):
        self.poll_timer.stop()
        super().closeEvent(event)
        
    def refresh_qrcode(self):
        self.status_label.setText("正在获取二维码...")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.refresh_btn.setVisible(False)
        self.poll_timer.stop()
        
        # Async call to get QR code
        asyncio.create_task(self._load_qrcode())
        
    async def _load_qrcode(self):
        url, key = await self.auth_manager.get_qrcode()
        if url and key:
            self.qrcode_key = key
            
            # Generate Image
            # Note: generate_qr_image is synchronous but fast
            loop = asyncio.get_event_loop()
            bio = await loop.run_in_executor(None, self.auth_manager.generate_qr_image, url)
            
            if bio:
                top_img = QImage.fromData(bio.getvalue())
                pixmap = QPixmap.fromImage(top_img)
                self.qr_label.setPixmap(pixmap.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.status_label.setText("请使用 哔哩哔哩手机客户端 扫码")
                self.poll_timer.start()
            else:
                self.status_label.setText("生成二维码失败")
                self.refresh_btn.setVisible(True)
        else:
            self.status_label.setText("无法连接到服务器")
            self.refresh_btn.setVisible(True)

    def check_status(self):
        if not self.qrcode_key:
            return
        asyncio.create_task(self._poll_status())
            
    async def _poll_status(self):
        code, msg, cookies = await self.auth_manager.poll_status(self.qrcode_key)
        print(f"Poll Status: {code}, Msg: {msg}") 
        
        if code == 0:
            # Success
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self.poll_timer.stop()
            
            # Save cookies
            if cookies:
                self.auth_manager.save_cookies(cookies)
                self.login_success.emit()
                # Wait a bit before closing
                await asyncio.sleep(1)
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
