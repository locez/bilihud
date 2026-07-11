from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .live_audience import AudienceSnapshot


class AudienceStatusWidget(QWidget):
    audience_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.popularity_label = QLabel()
        self.watched_label = QLabel()
        first_separator = QLabel("·")
        second_separator = QLabel("·")
        self.online_button = QToolButton()
        self.online_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.online_button.setToolTip("查看在线榜用户")
        self.online_button.clicked.connect(lambda _checked=False: self.audience_requested.emit())

        neutral_style = "color: rgba(255, 255, 255, 170); font-size: 11px;"
        separator_style = "color: rgba(255, 255, 255, 80); font-size: 11px;"
        self.popularity_label.setStyleSheet(neutral_style)
        self.watched_label.setStyleSheet(neutral_style)
        first_separator.setStyleSheet(separator_style)
        second_separator.setStyleSheet(separator_style)
        self.online_button.setStyleSheet(
            """
            QToolButton {
                color: #67c7ff;
                background: transparent;
                border: none;
                border-bottom: 1px dotted rgba(103, 199, 255, 160);
                padding: 0;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton:hover { color: #9bdcff; }
            """
        )

        layout.addWidget(self.popularity_label)
        layout.addWidget(first_separator)
        layout.addWidget(self.watched_label)
        layout.addWidget(second_separator)
        layout.addWidget(self.online_button)
        layout.addStretch()
        self.hide()

    def set_snapshot(self, snapshot: AudienceSnapshot) -> None:
        self.popularity_label.setText(f"{snapshot.popularity} 人气")
        self.watched_label.setText(f"{snapshot.watched_count} 人看过")
        self.online_button.setText(f"在线榜 {snapshot.online_rank_count}")
        self.show()

    def clear(self) -> None:
        self.popularity_label.clear()
        self.watched_label.clear()
        self.online_button.setText("在线榜 0")
        self.hide()


class AudiencePopup(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("audiencePopup")
        self.setFixedWidth(240)
        self.setMaximumHeight(260)
        self.setStyleSheet(
            """
            QFrame#audiencePopup {
                background: rgba(32, 36, 42, 245);
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 6px;
            }
            QLabel { color: rgba(255, 255, 255, 210); font-size: 11px; }
            QTreeWidget {
                color: rgba(255, 255, 255, 220);
                background: transparent;
                border: none;
                outline: none;
                font-size: 11px;
            }
            QHeaderView::section {
                color: rgba(255, 255, 255, 120);
                background: #2b3038;
                border: none;
                padding: 3px 4px;
                font-size: 10px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(9, 8, 9, 8)
        outer.setSpacing(5)

        header = QHBoxLayout()
        title = QLabel("在线榜")
        title.setStyleSheet("font-weight: 700; color: white;")
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary_label.setStyleSheet("color: rgba(255, 255, 255, 120); font-size: 10px;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.summary_label)
        outer.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["用户名", "贡献值"])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header_view = self.tree.header()
        assert header_view is not None
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.tree)

        self.empty_label = QLabel("暂无可见用户")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: rgba(255, 255, 255, 110); padding: 12px;")
        outer.addWidget(self.empty_label)

        self.footer_label = QLabel()
        self.footer_label.setStyleSheet("color: rgba(255, 255, 255, 110); font-size: 10px;")
        outer.addWidget(self.footer_label)
        self.hide()

    def set_snapshot(self, snapshot: AudienceSnapshot) -> None:
        self.summary_label.setText(f"可见 {len(snapshot.users)} / 共 {snapshot.online_rank_count}")
        self.tree.clear()
        for user in snapshot.users:
            item = QTreeWidgetItem([user.name, str(user.contribution)])
            item.setToolTip(0, user.name)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)

        has_users = bool(snapshot.users)
        self.tree.setVisible(has_users)
        self.empty_label.setVisible(not has_users)

        hidden_count = snapshot.hidden_user_count
        self.footer_label.setText(f"还有 {hidden_count} 位用户未公开")
        self.footer_label.setVisible(hidden_count > 0)

    def show_below(self, anchor: QWidget, host: QWidget) -> None:
        self.adjustSize()
        host_left = host.mapToGlobal(QPoint(0, 0)).x()
        host_right = host_left + host.width()
        anchor_bottom_right = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + 4))
        x = max(host_left, min(anchor_bottom_right.x() - self.width(), host_right - self.width()))
        y = anchor_bottom_right.y()

        screen = anchor.screen()
        if screen is not None and y + self.height() > screen.availableGeometry().bottom():
            y = anchor.mapToGlobal(QPoint(0, -self.height() - 4)).y()

        self.move(x, y)
        self.show()
        self.raise_()

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            self.hide()
            a0.accept()
            return
        super().keyPressEvent(a0)
