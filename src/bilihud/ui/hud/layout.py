"""HUD window layout construction kept separate from workflow and state binding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.live.emoticons import LiveEmoticon
from bilihud.ui.hud.audience import AudiencePopup, AudienceStatusWidget
from bilihud.ui.hud.emoticon_picker import EmoticonPickerPopup
from bilihud.ui.hud.icons import later_icon, lock_icon, settings_icon
from bilihud.ui.hud.input import DanmakuInputDialog, ModernInputWidget
from bilihud.ui.hud.message_list import DanmakuDelegate
from bilihud.ui.hud.resize import CustomSizeGrip


@dataclass(frozen=True, slots=True)
class HudWidgets:
    """Qt controls required by the HUD state and command bindings."""

    main_layout: QVBoxLayout
    header_widget: QWidget
    live_status_dot: QLabel
    room_id_input: QLineEdit
    connect_button: QToolButton
    gaming_mode_btn: QToolButton
    settings_button: QToolButton
    danmaku_list: QListWidget
    danmaku_delegate: DanmakuDelegate
    input_area: ModernInputWidget
    emoticon_picker: EmoticonPickerPopup
    audience_status: AudienceStatusWidget
    audience_popup: AudiencePopup
    input_dialog: DanmakuInputDialog
    size_grip: CustomSizeGrip


def build_hud_widgets(
    parent: QWidget,
    *,
    room_id: int,
    save_room_id: Callable[[], object],
    toggle_connection: Callable[[], object],
    toggle_gaming_mode: Callable[[], object],
    send_requested: Callable[[str], object],
    emoticon_requested: Callable[[], object],
    emoticon_selected: Callable[[LiveEmoticon], object],
    audience_requested: Callable[[], object],
    settings_requested: Callable[[], object],
    close_requested: Callable[[], object],
) -> HudWidgets:
    """Build the HUD controls and connect only presentation command signals."""
    main_layout = QVBoxLayout()
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(8)

    header_widget = QWidget(parent)
    header_layout = QHBoxLayout(header_widget)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    title_label = QLabel("BILIHUD", header_widget)
    title_label.setStyleSheet(
        """
        color: rgba(255, 255, 255, 200);
        font-weight: 900;
        font-family: 'Arial Black';
        font-size: 12px;
        letter-spacing: 0.5px;
        """
    )

    live_status_dot = QLabel(header_widget)
    live_status_dot.setFixedSize(8, 8)
    live_status_dot.setToolTip("直播中")
    live_status_dot.setStyleSheet(
        """
        QLabel {
            background-color: #ff2d55;
            border: 1px solid rgba(255, 255, 255, 180);
            border-radius: 4px;
        }
        """
    )
    live_status_dot.hide()

    room_id_input = QLineEdit(str(room_id), header_widget)
    room_id_input.setPlaceholderText("ID")
    room_id_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
    room_id_input.setStyleSheet(
        """
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
        QLineEdit:focus { border-color: rgba(255, 255, 255, 100); }
        """
    )
    room_id_input.editingFinished.connect(save_room_id)

    button_style = """
        QToolButton {
            background: rgba(255, 255, 255, 28);
            color: rgba(255, 255, 255, 210);
            border: none;
            border-radius: 15px;
            font-size: 13px;
        }
        QToolButton:hover { background: rgba(255, 255, 255, 60); }
        QToolButton:pressed { background: rgba(255, 255, 255, 90); }
        QToolButton:checked { background: rgba(76, 175, 80, 150); }
        QToolButton:disabled { background: rgba(255, 255, 255, 12); }
        """
    connect_button = QToolButton(header_widget)
    connect_button.setObjectName("connect_button")
    connect_button.setIcon(later_icon())
    connect_button.setIconSize(QSize(13, 13))
    connect_button.setFixedSize(30, 30)
    connect_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    connect_button.setToolTip("连接直播间")
    connect_button.setAccessibleName("连接直播间")
    connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
    connect_button.setCheckable(True)
    connect_button.setStyleSheet(button_style)
    connect_button.clicked.connect(toggle_connection)

    gaming_mode_btn = QToolButton(header_widget)
    gaming_mode_btn.setObjectName("gaming_mode_button")
    gaming_mode_btn.setIcon(lock_icon(False))
    gaming_mode_btn.setIconSize(QSize(13, 13))
    gaming_mode_btn.setFixedSize(30, 30)
    gaming_mode_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    gaming_mode_btn.setToolTip("开启穿透模式")
    gaming_mode_btn.setAccessibleName("锁定穿透")
    gaming_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gaming_mode_btn.setCheckable(True)
    gaming_mode_btn.setStyleSheet(button_style)
    gaming_mode_btn.clicked.connect(toggle_gaming_mode)

    settings_button = QToolButton(header_widget)
    settings_button.setObjectName("settings_button")
    settings_button.setIcon(settings_icon())
    settings_button.setIconSize(QSize(13, 13))
    settings_button.setFixedSize(30, 30)
    settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    settings_button.setToolTip("打开设置")
    settings_button.setAccessibleName("打开设置")
    settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
    settings_button.setStyleSheet(
        button_style
    )
    settings_button.clicked.connect(settings_requested)

    close_button = QPushButton("×", header_widget)
    close_button.setCursor(Qt.CursorShape.PointingHandCursor)
    close_button.setFixedSize(20, 20)
    close_button.setStyleSheet(
        """
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
        """
    )
    close_button.clicked.connect(close_requested)

    for widget in (title_label, live_status_dot, room_id_input, connect_button, gaming_mode_btn):
        header_layout.addWidget(widget)
    header_layout.addStretch()
    header_layout.addWidget(settings_button)
    header_layout.addWidget(close_button)

    danmaku_list = QListWidget(parent)
    danmaku_delegate = DanmakuDelegate(danmaku_list)
    danmaku_list.setItemDelegate(danmaku_delegate)
    danmaku_list.setStyleSheet("background: transparent; border: none;")
    danmaku_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    danmaku_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    danmaku_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    danmaku_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    danmaku_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    danmaku_list.setResizeMode(QListView.ResizeMode.Adjust)
    scroll_bar = danmaku_list.verticalScrollBar()
    if scroll_bar is not None:
        scroll_bar.setStyleSheet(
            """
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
            """
        )

    input_area = ModernInputWidget(parent)
    input_area.send_requested.connect(send_requested)
    input_area.emoticon_requested.connect(emoticon_requested)
    emoticon_picker = EmoticonPickerPopup(parent)
    emoticon_picker.emoticon_selected.connect(emoticon_selected)
    audience_status = AudienceStatusWidget(parent)
    audience_popup = AudiencePopup(parent)
    audience_status.audience_requested.connect(audience_requested)

    for widget in (header_widget, audience_status, danmaku_list, input_area):
        main_layout.addWidget(widget)
    parent.setLayout(main_layout)

    input_dialog = DanmakuInputDialog(None)
    input_dialog.send_message.connect(send_requested)
    size_grip = CustomSizeGrip(parent)
    size_grip.setStyleSheet(
        """
        QSizeGrip {
            background-color: transparent;
            width: 16px;
            height: 16px;
        }
        """
    )

    return HudWidgets(
        main_layout=main_layout,
        header_widget=header_widget,
        live_status_dot=live_status_dot,
        room_id_input=room_id_input,
        connect_button=connect_button,
        gaming_mode_btn=gaming_mode_btn,
        settings_button=settings_button,
        danmaku_list=danmaku_list,
        danmaku_delegate=danmaku_delegate,
        input_area=input_area,
        emoticon_picker=emoticon_picker,
        audience_status=audience_status,
        audience_popup=audience_popup,
        input_dialog=input_dialog,
        size_grip=size_grip,
    )


__all__ = ("HudWidgets", "build_hud_widgets")
