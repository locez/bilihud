import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStyle,
    QStyleOptionSpinBox,
    QToolButton,
    QWidget,
)

from bilihud.app.menu import AccountStatus
from bilihud.app_metadata import BILIBILI_LIVE_RECORD_URL, GITHUB_URL, application_version
from bilihud.auth.service import AccountProfile
from bilihud.config.store import AppConfig, ThemeMode
from bilihud.live.models import LiveVerificationKind
from bilihud.ui.settings.dialog import SettingsDialog
from bilihud.ui.settings.models import SettingsPage, SettingsSaveRequest
from bilihud.ui.settings.pages import account as account_page
from bilihud.ui.settings.pages.about import AboutSettingsPage
from bilihud.ui.settings.pages.account import AccountSettingsPage
from bilihud.ui.settings.pages.live.page import LiveSettingsPage
from bilihud.ui.settings.pages.live.workflow import LiveAction
from bilihud.ui.settings.pages.mirror import MirrorSettingsPage

_QT_APP: QApplication | None = None


def _app() -> QApplication:
    global _QT_APP
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        _QT_APP = instance
    else:
        _QT_APP = QApplication([])
    return _QT_APP


def test_settings_dialog_exposes_sidebar_pages_and_theme_choices() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig(theme=ThemeMode.DARK, window_opacity=65))

    labels: list[str] = []
    for index in range(dialog.navigation.count()):
        item = dialog.navigation.item(index)
        assert item is not None
        labels.append(item.text())
    assert labels == [
        "通用",
        "面板",
        "直播",
        "显示",
        "账号",
        "关于",
        "开发者",
    ]
    assert [dialog.theme_combo.itemData(index) for index in range(dialog.theme_combo.count())] == [
        ThemeMode.SYSTEM,
        ThemeMode.LIGHT,
        ThemeMode.DARK,
    ]
    assert dialog.theme_combo.currentData() is ThemeMode.DARK
    assert dialog.opacity_spinbox.value() == 65
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint

    dialog.select_page(SettingsPage.LIVE)
    assert dialog.navigation.currentRow() == 2
    assert dialog.page_title.text() == "开播设置"
    live_page = dialog.page_stack.currentWidget()
    assert isinstance(live_page, LiveSettingsPage)
    assert {button.text() for button in live_page.findChildren(QPushButton)} >= {
        "开始直播",
        "停止直播",
        "检查 OBS",
    }
    assert live_page.room_id_input.isReadOnly() is True

    dialog.select_page(SettingsPage.MIRROR)
    assert dialog.page_title.text() == "显示与特效"
    mirror_page = dialog.page_stack.currentWidget()
    assert isinstance(mirror_page, MirrorSettingsPage)
    assert mirror_page.findChild(QCheckBox, "mirror_enabled") is not None
    assert mirror_page.findChild(QLineEdit, "mirror_url") is not None
    assert mirror_page.findChild(QCheckBox, "show_user_avatars") is not None

    dialog.select_page(SettingsPage.DEVELOPER)
    assert dialog.navigation.currentRow() == 6
    simulation_button = dialog.simulation_button
    assert simulation_button is not None
    assert simulation_button.text() == "弹幕模拟"
    assert dialog.gift_effect_combo is not None
    assert [
        dialog.gift_effect_combo.itemText(index)
        for index in range(dialog.gift_effect_combo.count())
    ] == ["选择测试礼物", "总督开通", "提督开通", "舰长开通", "浪漫城堡"]

    selected_effects: list[str] = []
    dialog.gift_effect_simulation_requested.connect(selected_effects.append)
    dialog.gift_effect_combo.setCurrentIndex(4)
    dialog.gift_effect_combo.setCurrentIndex(4)
    assert selected_effects == ["castle", "castle"]
    assert dialog.gift_effect_combo.currentIndex() == 0

    dialog.select_page(SettingsPage.ABOUT)
    about_page = dialog.page_stack.currentWidget()
    assert isinstance(about_page, AboutSettingsPage)
    assert about_page.version_label.text() == f"v{application_version()}"
    assert about_page.github_button.toolTip() == GITHUB_URL
    assert about_page.github_button.isEnabled() is True

    dialog.select_page(SettingsPage.ACCOUNT)
    dialog.set_account_state(
        AccountStatus.LOGGED_IN,
        AccountProfile("123", "测试用户", following_count=12, follower_count=34, live_room_id=456),
    )
    account_page = dialog.page_stack.currentWidget()
    assert isinstance(account_page, AccountSettingsPage)
    assert account_page.account_name_label.text() == "测试用户"
    assert account_page.account_id_label.text() == "UID 123"
    assert account_page.following_value.text() == "12"
    assert account_page.follower_value.text() == "34"
    assert account_page.space_button.isHidden() is False
    assert account_page.live_room_button.isHidden() is False
    assert account_page.live_room_copy_button is not None
    assert account_page.live_room_copy_button.isHidden() is False
    assert account_page.live_room_copy_button.toolTip() == "复制直播间地址"
    assert account_page.live_record_button.isHidden() is False
    assert account_page.live_record_button.toolTip() == BILIBILI_LIVE_RECORD_URL
    assert account_page.login_button.isHidden() is True
    assert account_page.logout_button.isHidden() is False

    dialog.set_account_state(AccountStatus.LOGGED_OUT, None)
    assert account_page.account_name_label.text() == "未登录"
    assert account_page.login_button.isHidden() is False
    assert account_page.logout_button.isHidden() is True
    assert account_page.live_record_button.isHidden() is False

    dialog.close()


def test_settings_dialog_uses_a_rounded_translucent_surface() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    dialog.show()
    app.processEvents()

    mask = dialog.mask()
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not mask.isEmpty()
    assert not mask.contains(QPoint(0, 0))
    assert not mask.contains(QPoint(dialog.width() - 1, 0))
    assert not mask.contains(QPoint(0, dialog.height() - 1))
    assert not mask.contains(QPoint(dialog.width() - 1, dialog.height() - 1))
    assert mask.contains(QPoint(dialog.width() // 2, dialog.height() // 2))

    dialog.close()


def test_account_page_opens_bilibili_live_record_url(monkeypatch) -> None:
    _app()
    page = AccountSettingsPage()
    opened_urls: list[QUrl] = []

    class DesktopServices:
        @staticmethod
        def openUrl(url: QUrl) -> bool:
            opened_urls.append(url)
            return True

    monkeypatch.setattr(account_page, "QDesktopServices", DesktopServices)
    page.live_record_button.click()

    assert [url.toString() for url in opened_urls] == [BILIBILI_LIVE_RECORD_URL]
    page.close()


def test_account_page_copies_live_room_url_from_icon_button() -> None:
    app = _app()
    page = AccountSettingsPage()
    page.resize(520, 360)
    page.show()
    page.set_account_state(
        AccountStatus.LOGGED_IN,
        AccountProfile("123", "测试用户", live_room_id=456),
    )
    app.processEvents()

    copy_button = page.live_room_copy_button
    assert copy_button is not None
    live_room_gap = (
        copy_button.geometry().left()
        - page.live_room_button.geometry().right()
        - 1
    )
    assert live_room_gap == 0
    copy_button.click()

    clipboard = app.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "https://live.bilibili.com/456"
    assert page.account_status_label.text() == "直播间地址已复制"

    page.set_account_state(AccountStatus.LOGGED_OUT, None)
    assert copy_button.isHidden() is True
    page.close()


def test_settings_dialog_emits_typed_apply_and_confirm_requests() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig())
    requests: list[SettingsSaveRequest] = []
    dialog.settings_requested.connect(requests.append)

    dialog.theme_combo.setCurrentIndex(2)
    dialog.opacity_spinbox.setValue(20)
    dialog.apply_button.click()

    assert len(requests) == 1
    assert requests[0].config.theme is ThemeMode.DARK
    assert requests[0].config.window_opacity == 20
    assert requests[0].close_after_save is False

    dialog.ok_button.click()
    assert len(requests) == 2
    assert requests[1].close_after_save is True

    dialog.close()


def test_settings_dialog_saves_both_gift_effect_switches_and_mirror_position() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig())
    requests: list[SettingsSaveRequest] = []
    dialog.settings_requested.connect(requests.append)

    dialog.select_page(SettingsPage.MIRROR)
    mirror_page = dialog.page_stack.currentWidget()
    assert isinstance(mirror_page, MirrorSettingsPage)
    mirror_page.mirror_gift_effects_checkbox.setChecked(True)
    mirror_page.overlay_gift_effects_checkbox.setChecked(True)
    mirror_page.show_user_avatars_checkbox.setChecked(True)
    font_index = 1 if mirror_page.font_family_combo.count() > 1 else 0
    mirror_page.font_family_combo.setCurrentIndex(font_index)
    expected_font = mirror_page.font_family_combo.currentData()
    assert isinstance(expected_font, str)
    mirror_page.danmaku_x_spinbox.setValue(28)
    mirror_page.danmaku_y_spinbox.setValue(74)
    dialog.apply_button.click()

    assert len(requests) == 1
    assert requests[0].config.mirror_gift_effects_enabled is True
    assert requests[0].config.overlay_gift_effects_enabled is True
    assert requests[0].config.show_user_avatars is True
    assert requests[0].config.hud_font_family == expected_font
    assert requests[0].config.mirror_danmaku_x == 28
    assert requests[0].config.mirror_danmaku_y == 74
    dialog.close()


def test_settings_dialog_rejects_opacity_below_twenty_with_feedback() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig())
    requests: list[SettingsSaveRequest] = []
    dialog.settings_requested.connect(requests.append)

    dialog.opacity_spinbox.setValue(10)
    dialog.apply_button.click()

    assert requests == []
    assert dialog.feedback_label.text() == ""
    assert dialog.navigation.currentRow() == 1
    assert dialog.opacity_error_label is not None
    assert dialog.opacity_error_label.text() == "HUD 背景不透明度需在 20% 到 100% 之间"
    assert dialog.opacity_error_label.isHidden() is False
    dialog.close()


def test_settings_dialog_header_moves_frameless_window() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    dialog.show()
    app.processEvents()
    dialog.move(120, 140)
    app.processEvents()
    initial_position = dialog.pos()
    initial_frame = dialog.frameGeometry().topLeft()

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(initial_frame.x() + 10, initial_frame.y() + 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(60, 40),
        QPointF(60, 40),
        QPointF(initial_frame.x() + 60, initial_frame.y() + 40),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(60, 40),
        QPointF(60, 40),
        QPointF(initial_frame.x() + 60, initial_frame.y() + 40),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    drag_region = dialog.findChild(QWidget, "window_drag_region")
    assert drag_region is not None
    close_button = dialog.findChild(QToolButton, "window_close")
    assert close_button is not None
    close_origin = close_button.mapTo(dialog, QPoint(0, 0))
    assert drag_region.geometry().right() < close_origin.x()
    assert close_origin.x() + close_button.width() == dialog.width() - 8
    assert close_origin.y() == 8
    assert dialog.eventFilter(drag_region, press) is True
    assert dialog.eventFilter(drag_region, move) is True
    assert dialog.pos() == initial_position + QPoint(50, 30)
    assert dialog.eventFilter(drag_region, release) is True

    dialog.select_page(SettingsPage.ACCOUNT)
    dialog.navigation.setCurrentRow(0)
    assert dialog.navigation.currentRow() == 0
    dialog.close()


def test_settings_dialog_clears_save_feedback_when_switching_pages() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig())
    request = SettingsSaveRequest(AppConfig(), close_after_save=False)

    dialog.report_save_result(request, True)
    assert dialog.feedback_label.text() == "已应用"
    dialog.select_page(SettingsPage.LIVE)
    assert dialog.feedback_label.text() == ""
    dialog.report_save_result(request, True)
    dialog.select_page(SettingsPage.LIVE)
    assert dialog.feedback_label.text() == ""
    dialog.close()


def test_modern_combo_does_not_change_from_a_closed_wheel_event() -> None:
    _app()
    dialog = SettingsDialog(None, AppConfig())
    combo = dialog.theme_combo
    combo.setCurrentIndex(0)
    wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    combo.wheelEvent(wheel)

    assert combo.currentIndex() == 0
    assert wheel.isAccepted() is False
    dialog.close()


def test_modern_combo_popup_separates_options() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    combo = dialog.theme_combo
    combo.show()
    app.processEvents()
    combo.showPopup()
    app.processEvents()

    view = combo.view()
    assert isinstance(view, QListView)
    assert view.spacing() == 4
    model = view.model()
    if model is None:
        raise AssertionError("theme combo popup has no model")
    first_item = view.visualRect(model.index(0, 0))
    second_item = view.visualRect(model.index(1, 0))
    assert second_item.top() - first_item.bottom() - 1 >= view.spacing()

    combo.hidePopup()
    dialog.close()


def test_settings_spinbox_buttons_receive_clicks_across_their_full_hit_area() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig(window_opacity=50))
    dialog.select_page(SettingsPage.PANEL)
    dialog.show()
    app.processEvents()

    spinbox = dialog.opacity_spinbox
    option = QStyleOptionSpinBox()
    option.initFrom(spinbox)
    option.frame = spinbox.hasFrame()
    option.buttonSymbols = spinbox.buttonSymbols()
    option.stepEnabled = spinbox.stepEnabled()
    style = spinbox.style()
    if style is None:
        raise AssertionError("opacity spinbox has no style")

    for subcontrol, expected_value in (
        (QStyle.SubControl.SC_SpinBoxUp, 55),
        (QStyle.SubControl.SC_SpinBoxDown, 45),
    ):
        button_rect = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            subcontrol,
            spinbox,
        )
        spinbox.setValue(50)
        point = QPoint(button_rect.left() + 1, button_rect.center().y())
        target = spinbox.childAt(point)
        if target is None:
            target = spinbox
        target_point = target.mapFrom(spinbox, point)
        global_point = spinbox.mapToGlobal(point)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(target_point),
            QPointF(target_point),
            QPointF(global_point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(target_point),
            QPointF(target_point),
            QPointF(global_point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, press)
        QApplication.sendEvent(target, release)
        app.processEvents()

        assert target is not spinbox.lineEdit()
        assert spinbox.value() == expected_value

    dialog.close()


def test_settings_dialog_hides_scrollbar_for_short_page() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    dialog.show()
    app.processEvents()

    scrollbar = dialog.page_scroll.verticalScrollBar()
    assert scrollbar is not None
    assert scrollbar.isVisible() is False

    dialog.close()


def test_settings_dialog_resets_scroll_when_switching_to_live_page() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    dialog.show()
    app.processEvents()

    dialog.select_page(SettingsPage.LIVE)
    app.processEvents()
    scrollbar = dialog.page_scroll.verticalScrollBar()
    assert scrollbar is not None
    scrollbar.setValue(scrollbar.maximum())
    assert scrollbar.value() > 0

    dialog.select_page(SettingsPage.GENERAL)
    dialog.select_page(SettingsPage.LIVE)
    app.processEvents()

    assert scrollbar.value() == scrollbar.minimum()
    dialog.close()


def test_live_action_buttons_show_owned_busy_state() -> None:
    _app()
    page = LiveSettingsPage()

    page.set_busy(True, "正在开始直播...", action=LiveAction.START)

    assert page.start_button.text() == "正在开始..."
    assert page.start_button.isEnabled() is False
    assert page.start_button.property("busy") is True
    assert page.stop_button.text() == "停止直播"

    page.set_busy(False)

    assert page.start_button.text() == "开始直播"
    assert page.start_button.property("busy") is False


def test_live_form_leaves_space_between_compound_controls() -> None:
    app = _app()
    dialog = SettingsDialog(None, AppConfig())
    dialog.select_page(SettingsPage.LIVE)
    dialog.show()
    app.processEvents()

    page = dialog.page_stack.currentWidget()
    assert isinstance(page, LiveSettingsPage)

    def horizontal_gap(left: QWidget, right: QWidget) -> int:
        return right.geometry().left() - left.geometry().right() - 1

    assert horizontal_gap(page.room_id_input, page.refresh_room_button) == 8
    assert horizontal_gap(page.title_input, page.update_title_button) == 8
    assert horizontal_gap(page.area_combo, page.update_area_button) == 8
    assert horizontal_gap(page.obs_host_input, page.obs_port_input) == 8
    assert horizontal_gap(page.obs_password_input, page.check_obs_button) == 8
    assert horizontal_gap(page.check_obs_button, page.stop_obs_button) == 8

    dialog.close()


def test_live_face_verification_uses_face_auth_copy() -> None:
    _app()
    page = LiveSettingsPage()

    page.show_verification("", LiveVerificationKind.FACE)
    dialog = page.findChild(QDialog, "verification_dialog")

    assert dialog is not None
    assert dialog.windowTitle() == "人脸认证"
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    card_title = dialog.findChild(QLabel, "card_title")
    prompt = dialog.findChild(QLabel, "verification_prompt")
    qr = dialog.findChild(QLabel, "verification_qr")
    assert card_title is not None
    assert prompt is not None
    assert qr is not None
    assert dialog.findChild(QToolButton, "window_close") is None
    assert card_title.text() == "扫码完成认证"
    assert "完成人脸认证" in prompt.text()
    assert "重新点击“开始直播”" in prompt.text()
    dialog.close()


def test_live_warning_uses_the_settings_visual_language() -> None:
    _app()
    page = LiveSettingsPage()

    page.show_warning(
        "OBS 推流状态未确认",
        "Bilibili 直播已停止，但 OBS 推流未能自动确认。",
        "请打开 OBS 手动确认推流状态。",
    )
    dialog = page.findChild(QDialog, "live_warning_dialog")

    assert dialog is not None
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    title = dialog.findChild(QLabel, "warning_title")
    message = dialog.findChild(QLabel, "warning_message")
    details = dialog.findChild(QLabel, "warning_details")
    assert title is not None
    assert message is not None
    assert details is not None
    assert title.text() == "OBS 推流状态未确认"
    assert "Bilibili 直播已停止" in message.text()
    assert details.text() == "请打开 OBS 手动确认推流状态。"

    dialog.close()
    page.close()
