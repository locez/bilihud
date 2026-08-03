import os

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from bilihud.audience_widgets import AudiencePopup, AudienceStatusWidget
from bilihud.live.audience import AudienceSnapshot, AudienceUser

_QT_APP = None


def app():
    global _QT_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def snapshot(*, online_count=3, users=None):
    return AudienceSnapshot(
        room_id=7450109,
        popularity=21,
        watched_count=9,
        online_rank_count=online_count,
        users=users
        if users is not None
        else (AudienceUser(1001, "用户A", 1, 1, False),),
    )


def test_status_widget_formats_metrics_and_emits_only_from_online_button():
    app()
    widget = AudienceStatusWidget()
    requested = []
    widget.audience_requested.connect(lambda: requested.append(True))

    assert widget.isHidden()

    widget.set_snapshot(snapshot())

    assert widget.popularity_label.text() == "21 人气"
    assert widget.watched_label.text() == "9 人看过"
    assert widget.online_button.text() == "在线榜 3"
    assert widget.online_button.cursor().shape() == Qt.CursorShape.PointingHandCursor

    widget.online_button.click()
    assert requested == [True]

    widget.clear()
    assert widget.isHidden()


def test_popup_maps_each_username_to_its_contribution():
    app()
    popup = AudiencePopup()
    popup.set_snapshot(
        snapshot(
            users=(
                AudienceUser(1001, "用户A", 1, 1, False),
                AudienceUser(1002, "用户B", 4, 2, False),
            )
        )
    )

    assert popup.summary_label.text() == "可见 2 / 共 3"
    assert popup.tree.topLevelItemCount() == 2
    assert popup.tree.topLevelItem(0).text(0) == "用户A"
    assert popup.tree.topLevelItem(0).text(1) == "1"
    assert popup.tree.topLevelItem(1).text(0) == "用户B"
    assert popup.tree.topLevelItem(1).text(1) == "4"
    assert popup.footer_label.text() == "还有 1 位用户未公开"
    assert popup.footer_label.isHidden() is False


def test_popup_shows_empty_visible_list_without_inventing_users():
    app()
    popup = AudiencePopup()
    popup.set_snapshot(snapshot(online_count=2, users=()))

    assert popup.tree.isHidden()
    assert popup.empty_label.text() == "暂无可见用户"
    assert popup.empty_label.isHidden() is False
    assert popup.footer_label.text() == "还有 2 位用户未公开"


def test_popup_escape_closes_popup():
    qt_app = app()
    popup = AudiencePopup()
    popup.set_snapshot(snapshot())
    popup.show()
    qt_app.processEvents()

    QTest.keyClick(popup, Qt.Key.Key_Escape)
    qt_app.processEvents()

    assert popup.isHidden()


def test_popup_constrains_long_list_to_internal_scroll_area():
    qt_app = app()
    popup = AudiencePopup()
    users = tuple(
        AudienceUser(1000 + index, f"用户{index}", index, index, False)
        for index in range(120)
    )
    popup.set_snapshot(snapshot(online_count=120, users=users))
    popup.show()
    qt_app.processEvents()

    assert popup.tree.topLevelItemCount() == 120
    assert popup.height() <= 260
    assert popup.tree.verticalScrollBar().maximum() > 0


def test_popup_keeps_compact_width_for_long_usernames():
    qt_app = app()
    popup = AudiencePopup()
    long_name = "一个较长的匿名用户名示例"
    popup.set_snapshot(
        snapshot(users=(AudienceUser(1001, long_name, 1, 1, False),))
    )
    popup.show()
    qt_app.processEvents()

    assert popup.width() == 240
    assert popup.tree.topLevelItem(0).toolTip(0) == long_name
