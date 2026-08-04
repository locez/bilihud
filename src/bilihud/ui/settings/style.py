"""Theme stylesheet builder for the unified settings window."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPen, QWheelEvent
from PyQt6.QtWidgets import QComboBox, QListView, QSpinBox, QWidget

from bilihud.ui.appearance import Appearance


class ModernComboBox(QComboBox):
    """Render a compact combo box with a consistent chevron on every platform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a combo box with a stylesheet-friendly popup view."""
        super().__init__(parent)
        popup_view = QListView(self)
        popup_view.setUniformItemSizes(True)
        self.setView(popup_view)

    def showPopup(self) -> None:
        """Style the transient option list before opening it."""
        view = self.view()
        if view is None:
            super().showPopup()
            return
        palette = view.palette()
        surface = palette.color(QPalette.ColorRole.Base).name()
        text = palette.color(QPalette.ColorRole.Text).name()
        border = "#3a3f49" if QColor(surface).lightness() < 128 else "#dfe3ea"
        accent = palette.color(QPalette.ColorRole.Highlight).name()
        accent_text = palette.color(QPalette.ColorRole.HighlightedText).name()
        view.setStyleSheet(
            f"""
            QAbstractItemView {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px 0;
                outline: none;
            }}
            QAbstractItemView::item {{
                padding: 6px 12px;
                min-height: 28px;
                border-radius: 4px;
            }}
            QAbstractItemView::item:hover {{
                background: {accent};
                color: {accent_text};
            }}
            QAbstractItemView::item:selected {{
                background: {accent};
                color: {accent_text};
            }}
            """,
        )
        super().showPopup()

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        """Keep a closed combo stable; scrolling is only meaningful in its popup."""
        if e is None:
            return
        view = self.view()
        if view is not None and view.isVisible():
            super().wheelEvent(e)
            return
        e.ignore()

    def paintEvent(self, e: QPaintEvent | None) -> None:
        """Keep native popup behavior while replacing platform-specific arrow chrome."""
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        color = self.palette().color(group, QPalette.ColorRole.Text)
        pen = QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = float(self.width() - 17)
        center_y = float(self.height() // 2)
        painter.drawLine(QPointF(center_x - 4, center_y - 2), QPointF(center_x, center_y + 2))
        painter.drawLine(QPointF(center_x, center_y + 2), QPointF(center_x + 4, center_y - 2))


class ModernSpinBox(QSpinBox):
    """Render a numeric stepper with quiet custom chevrons and native input behavior."""

    def paintEvent(self, e: QPaintEvent | None) -> None:
        """Keep native stepping while replacing platform-specific button chrome."""
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        color = self.palette().color(group, QPalette.ColorRole.Text)
        pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = float(self.width() - 14)
        center_y = float(self.height() // 2)
        painter.drawLine(QPointF(center_x - 3, center_y - 5), QPointF(center_x, center_y - 8))
        painter.drawLine(QPointF(center_x, center_y - 8), QPointF(center_x + 3, center_y - 5))
        painter.drawLine(QPointF(center_x - 3, center_y + 5), QPointF(center_x, center_y + 8))
        painter.drawLine(QPointF(center_x, center_y + 8), QPointF(center_x + 3, center_y + 5))


def settings_stylesheet(appearance: Appearance) -> str:
    """Return the palette stylesheet shared by every embedded settings page."""
    return f"""
        QDialog {{ background: {appearance.window}; color: {appearance.text}; }}
        QFrame#sidebar {{ background: {appearance.surface}; border-right: 1px solid {appearance.border}; }}
        QFrame#content {{ background: {appearance.window}; }}
        QFrame#settings_header {{ background: transparent; }}
        QFrame#action_bar {{ border-top: 1px solid {appearance.border}; }}
        QFrame#live_actions {{ border-top: 1px solid {appearance.border}; }}
        QStackedWidget#page_stack {{ background: {appearance.window}; }}
        QWidget#settings_page {{ background: {appearance.window}; }}
        QAbstractScrollArea#page_scroll {{ background: {appearance.window}; }}
        QFrame#card {{
            background: {appearance.surface};
            border: 1px solid {appearance.border};
            border-radius: 8px;
        }}
        QLabel {{ color: {appearance.text}; }}
        QLabel#brand_label {{ font-size: 15px; font-weight: 700; }}
        QLabel#page_title {{ font-size: 24px; font-weight: 700; }}
        QLabel#muted_label,
        QLabel#sidebar_note, QLabel#feedback_label {{ color: {appearance.muted_text}; }}
        QLabel#field_error {{ color: #c94b5b; font-size: 12px; font-weight: 600; }}
        QLabel#about_summary {{ color: {appearance.muted_text}; font-size: 14px; }}
        QLabel#about_value {{ color: {appearance.text}; font-weight: 600; }}
        QLabel#account_avatar {{
            color: #ffffff;
            background: {appearance.accent};
            border-radius: 24px;
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel#account_name {{ font-size: 16px; font-weight: 700; }}
        QLabel#account_id {{ color: {appearance.muted_text}; }}
        QFrame#account_stats {{ border-top: 1px solid {appearance.border}; }}
        QLabel#account_stat_value {{ font-size: 16px; font-weight: 700; }}
        QLabel#account_stat_label {{ color: {appearance.muted_text}; font-size: 12px; }}
        QLabel#card_title, QLabel#about_title {{ font-size: 15px; font-weight: 700; }}
        QLabel#status_label {{ color: {appearance.accent}; font-weight: 600; }}
        QLabel#status_label[level="error"] {{ color: #df5b68; }}
        QLabel#status_label[level="success"] {{ color: #3fa36c; }}
        QLabel#verification_prompt {{ color: {appearance.muted_text}; font-size: 13px; }}
        QLabel#verification_qr {{ background: #ffffff; border: 1px solid {appearance.border}; border-radius: 10px; }}
        QLabel#verification_url {{ color: {appearance.muted_text}; }}
        QFrame#verification_header {{ background: transparent; }}
        QListWidget#navigation {{
            background: transparent;
            border: none;
            outline: none;
            color: {appearance.muted_text};
        }}
        QListWidget#navigation::item {{ padding: 10px 12px; border-radius: 6px; }}
        QListWidget#navigation::item:hover {{ background: {appearance.surface_alt}; color: {appearance.text}; }}
        QListWidget#navigation::item:selected {{
            background: {appearance.accent_soft};
            color: {appearance.accent};
            font-weight: 700;
        }}
        QComboBox, QSpinBox {{
            min-height: 34px;
            padding: 0 10px;
            color: {appearance.text};
            background: {appearance.surface_alt};
            border: 1px solid {appearance.border};
            border-radius: 6px;
        }}
        QComboBox:focus, QSpinBox:focus {{ border-color: {appearance.accent}; }}
        QComboBox:hover, QSpinBox:hover {{ border-color: {appearance.muted_text}; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border: none;
            background: transparent;
        }}
        QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border;
            width: 26px;
            border: none;
            background: transparent;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {appearance.accent_soft}; }}
        QSpinBox::up-arrow, QSpinBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
        QLineEdit {{
            min-height: 34px;
            padding: 0 10px;
            color: {appearance.text};
            background: {appearance.surface_alt};
            border: 1px solid {appearance.border};
            border-radius: 6px;
        }}
        QLineEdit:focus {{ border-color: {appearance.accent}; }}
        QCheckBox {{ color: {appearance.text}; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {appearance.border};
            border-radius: 4px;
            background: {appearance.surface_alt};
        }}
        QCheckBox::indicator:checked {{ background: {appearance.accent}; border-color: {appearance.accent}; }}
        QComboBox QAbstractItemView {{
            color: {appearance.text};
            background: {appearance.surface};
            selection-color: {appearance.text};
            selection-background-color: {appearance.accent_soft};
            border: 1px solid {appearance.border};
        }}
        QPushButton {{
            min-height: 34px;
            padding: 0 15px;
            color: {appearance.text};
            background: {appearance.surface_alt};
            border: 1px solid {appearance.border};
            border-radius: 6px;
        }}
        QPushButton:hover {{ border-color: {appearance.accent}; background: {appearance.accent_soft}; }}
        QPushButton[accent="true"] {{
            color: #ffffff;
            background: {appearance.accent};
            border-color: {appearance.accent};
            font-weight: 700;
        }}
        QPushButton[accent="true"]:hover {{ background: #d94183; }}
        QPushButton:disabled {{
            color: {appearance.muted_text};
            background: {appearance.surface_alt};
            border-color: {appearance.border};
        }}
        QPushButton[busy="true"] {{
            color: {appearance.accent};
            background: {appearance.accent_soft};
            border-color: {appearance.accent};
            font-weight: 700;
        }}
        QPushButton[accent="true"][busy="true"] {{
            color: #ffffff;
            background: {appearance.accent};
            border-color: {appearance.accent};
        }}
        QPushButton[destructive="true"] {{ color: #c94b5b; }}
        QPushButton[destructive="true"]:hover {{ color: #ffffff; background: #c94b5b; border-color: #c94b5b; }}
        QPushButton[link="true"] {{
            min-height: 28px;
            padding: 0 5px;
            color: {appearance.accent};
            background: transparent;
            border: none;
            border-radius: 4px;
        }}
        QPushButton[link="true"]:hover {{ background: {appearance.accent_soft}; }}
        QToolButton#window_close {{
            min-width: 32px;
            min-height: 32px;
            color: {appearance.muted_text};
            background: transparent;
            border: none;
            border-radius: 6px;
            font-size: 22px;
        }}
        QToolButton#window_close:hover {{ color: {appearance.text}; background: {appearance.surface_alt}; }}
        QFrame#credential_row {{
            background: {appearance.surface_alt};
            border: 1px solid {appearance.border};
            border-radius: 6px;
        }}
        QScrollArea#credentials_scroll {{ background: transparent; border: none; min-height: 88px; }}
        QScrollArea#page_scroll {{ background: transparent; border: none; }}
        QAbstractScrollArea#page_scroll QScrollBar:vertical {{
            width: 9px;
            margin: 2px 1px 2px 0;
            background: transparent;
            border: none;
        }}
        QAbstractScrollArea#page_scroll QScrollBar::handle:vertical {{
            min-height: 42px;
            margin: 1px 0;
            background: {appearance.border};
            border-radius: 4px;
        }}
        QAbstractScrollArea#page_scroll QScrollBar::handle:vertical:hover {{ background: {appearance.muted_text}; }}
        QAbstractScrollArea#page_scroll QScrollBar::add-line:vertical,
        QAbstractScrollArea#page_scroll QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
        QAbstractScrollArea#page_scroll QScrollBar::add-page:vertical,
        QAbstractScrollArea#page_scroll QScrollBar::sub-page:vertical {{ background: transparent; }}
        QAbstractScrollArea#page_scroll QScrollBar:horizontal {{ height: 0; background: transparent; border: none; }}
    """


__all__ = ("ModernComboBox", "ModernSpinBox", "settings_stylesheet")
