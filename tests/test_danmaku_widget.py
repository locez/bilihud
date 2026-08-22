import asyncio
import os
from dataclasses import replace

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QApplication, QLabel, QListWidgetItem, QToolButton

from bilihud.app.menu import MenuCommand, TrayMenuState
from bilihud.app.services import create_default_services
from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftMessage,
    HudMessage,
    InteractionKind,
    InteractMessage,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    ReplySegment,
    TextSegment,
    make_system_message,
)
from bilihud.danmaku.mock import MOCK_CASTLE_GIFT_ID, MockGiftEffectId
from bilihud.live.emoticons import LiveEmoticon, LiveEmoticonPackage
from bilihud.mirror.state import MirrorEntry
from bilihud.platform.layer_shell import LayerShellAnchorDragStrategy
from bilihud.platform.overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayOperationResult,
    WindowPoint,
    WindowRectangle,
)
from bilihud.ui.hud import emoticon_picker, message_list
from bilihud.ui.hud import input as hud_input
from bilihud.ui.hud import window as danmaku_widget
from bilihud.ui.settings.models import SettingsPage
from bilihud.ui.tray.menu import TrayMenu

_QT_APP = None


def _app():
    global _QT_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_layer_shell_drag_updates_anchor_position():
    class FakeHost:
        def apply_window_policy(self, policy) -> None:
            del policy

        def native_window_pointer(self) -> int:
            return 123

        def native_window_id(self) -> int | None:
            return None

        def window_position(self) -> WindowPoint:
            return WindowPoint(100, 100)

        def geometry(self) -> WindowRectangle:
            return WindowRectangle(x=100, y=100, width=300, height=450)

        def screen_geometry(self) -> WindowRectangle:
            return WindowRectangle(x=0, y=0, width=1920, height=1080)

        def full_screen_overlay(self) -> bool:
            return False

        def set_geometry(self, geometry: WindowRectangle) -> None:
            del geometry

        def move_window(self, position: WindowPoint) -> None:
            del position

        def show_window(self) -> None:
            pass

        def hide_window(self) -> None:
            pass

        def raise_window(self) -> None:
            pass

        def activate_window(self) -> None:
            pass

        def start_system_move(self) -> bool:
            return False

        def refresh(self) -> None:
            pass

    class FakeLayerShell:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []

        def set_anchor_position(self, window_pointer: int, x: int, y: int) -> None:
            self.calls.append((window_pointer, x, y))

        def make_overlay(self, window_pointer: int, *, full_screen: bool = False) -> bool:
            del window_pointer, full_screen
            return True

        def set_passthrough(self, window_pointer: int, enabled: bool) -> None:
            del window_pointer, enabled

        def set_keyboard_interactivity(self, window_pointer: int, enabled: bool) -> None:
            del window_pointer, enabled

    layer_shell = FakeLayerShell()
    strategy = LayerShellAnchorDragStrategy(FakeHost(), layer_shell)

    assert strategy.synchronize_position().succeeded is True
    assert strategy.begin_drag(WindowPoint(10, 10), WindowPoint(110, 110)).mode is DragMode.MANUAL
    assert strategy.update_drag(WindowPoint(20, 20), WindowPoint(120, 120)).succeeded is True
    assert strategy.update_drag(WindowPoint(20, 20), WindowPoint(130, 130)).succeeded is True

    assert layer_shell.calls == [(123, 100, 100), (123, 110, 110), (123, 120, 120)]


def test_hud_opacity_maps_to_the_background_alpha_layer():
    assert danmaku_widget._opacity_to_alpha(40) == 102
    assert danmaku_widget._opacity_to_alpha(80) == 204
    assert danmaku_widget._opacity_to_alpha(100) == 255


def test_danmaku_widget_keeps_game_mode_controls_in_sync_with_fake_platform(tmp_path):
    class FakePlatform:
        capabilities = OverlayCapabilities(
            layer_shell=False,
            gaming_mode=True,
            click_through=True,
            drag=True,
        )

        def __init__(self) -> None:
            self.mode_calls: list[bool] = []

        def prepare(self) -> OverlayOperationResult:
            return OverlayOperationResult.success()

        def activate(self) -> OverlayOperationResult:
            return OverlayOperationResult.success()

        def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
            self.mode_calls.append(enabled)
            return OverlayOperationResult.success()

        def begin_drag(self, _local_position: WindowPoint, _global_position: WindowPoint) -> DragStartResult:
            return DragStartResult(DragMode.MANUAL)

        def update_drag(
            self,
            _local_position: WindowPoint,
            _global_position: WindowPoint,
        ) -> OverlayOperationResult:
            return OverlayOperationResult.success()

        def end_drag(self) -> None:
            pass

    _app()
    platform = FakePlatform()
    services = replace(
        create_default_services(tmp_path / "config.json"),
        overlay_platform_factory=lambda _host: platform,
    )
    widget = danmaku_widget.DanmakuWidget(services=services)
    try:
        assert widget.set_gaming_mode(True).succeeded is True
        assert widget.is_gaming_mode is True
        assert widget.gaming_mode_btn.isChecked() is True
        assert widget.tray_gaming_action.isChecked() is True

        assert widget.set_gaming_mode(False).succeeded is True
        assert widget.is_gaming_mode is False
        assert widget.gaming_mode_btn.isChecked() is False
        assert widget.tray_gaming_action.isChecked() is False
        assert platform.mode_calls == [True, False]

        widget.open_settings()
        settings_dialog = widget.settings_controller.dialog
        assert settings_dialog is not None
        assert settings_dialog.parentWidget() is None
        assert not settings_dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    finally:
        asyncio.run(widget.shutdown())


def test_tray_menu_emits_commands_and_renders_state():
    _app()
    menu = TrayMenu()
    commands = []
    menu.command_requested.connect(lambda command, checked: commands.append((command, checked)))
    menu.set_state(
        TrayMenuState(
            visible=True,
            gaming_mode=False,
            gaming_mode_available=True,
        )
    )

    assert menu.action_for(MenuCommand.OPEN_LIVE_SETTINGS).text() == "开播设置"
    assert menu.action_for(MenuCommand.OPEN_SETTINGS).text() == "设置"
    menu.action_for(MenuCommand.OPEN_SETTINGS).trigger()
    menu.action_for(MenuCommand.TOGGLE_GAMING_MODE).trigger()

    assert commands == [
        (MenuCommand.OPEN_SETTINGS, False),
        (MenuCommand.TOGGLE_GAMING_MODE, True),
    ]
    menu.close()


def test_danmaku_widget_injects_fixed_mock_messages_into_hud(monkeypatch):
    _app()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._shutting_down = False
    received: list[HudMessage] = []

    def receive_message(_widget: danmaku_widget.DanmakuWidget, message: HudMessage) -> None:
        received.append(message)

    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "add_message", receive_message)

    danmaku_widget.DanmakuWidget.trigger_danmaku_simulation(widget)

    assert len(received) == len(danmaku_widget.mock_message_batch())
    assert not any(
        isinstance(message, GiftMessage) and message.gift_id == MOCK_CASTLE_GIFT_ID
        for message in received
    )


def test_danmaku_widget_injects_one_selected_gift_effect_fixture(monkeypatch):
    _app()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._shutting_down = False
    received: list[HudMessage] = []

    def receive_message(_widget: danmaku_widget.DanmakuWidget, message: HudMessage) -> None:
        received.append(message)

    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "add_message", receive_message)

    danmaku_widget.DanmakuWidget.trigger_gift_effect_simulation(
        widget,
        MockGiftEffectId.CASTLE.value,
    )

    assert len(received) == 1
    castle = received[0]
    assert isinstance(castle, GiftMessage)
    assert castle.gift_id == MOCK_CASTLE_GIFT_ID
    assert castle.gift_effect_url.endswith(".mp4")
    assert castle.gift_animation_url.endswith(".gif")
    assert castle.gift_effect_layout is not None


def test_danmaku_widget_mirror_command_selects_unified_settings_tab(monkeypatch):
    calls: list[SettingsPage] = []
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._shutting_down = False

    def open_settings(_widget: danmaku_widget.DanmakuWidget, page: SettingsPage = SettingsPage.GENERAL) -> None:
        calls.append(page)

    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "open_settings", open_settings)

    danmaku_widget.DanmakuWidget.open_mirror_settings(widget)

    assert calls == [SettingsPage.MIRROR]


def test_danmaku_widget_live_tray_command_selects_unified_settings_tab(monkeypatch):
    calls: list[SettingsPage] = []
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)

    def open_settings(_widget: danmaku_widget.DanmakuWidget, page: SettingsPage = SettingsPage.GENERAL) -> None:
        calls.append(page)

    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "open_settings", open_settings)

    danmaku_widget.DanmakuWidget._handle_menu_command(
        widget,
        MenuCommand.OPEN_LIVE_SETTINGS,
    )

    assert calls == [SettingsPage.LIVE]


def test_emoticon_picker_requests_bilibili_headers(monkeypatch):
    class FakeRequest:
        class KnownHeaders:
            UserAgentHeader = "user-agent"

        def __init__(self, url):
            self.url = url
            self.raw_headers = {}
            self.headers = {}

        def setRawHeader(self, name, value):
            self.raw_headers[name] = value

        def setHeader(self, name, value):
            self.headers[name] = value

    class Reply(QNetworkReply):
        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)

    class NetworkManager:
        def __init__(self) -> None:
            self.requests: list[FakeRequest] = []

        def get(self, request: object) -> QNetworkReply:
            if not isinstance(request, FakeRequest):
                raise AssertionError("the test request adapter was not installed")
            self.requests.append(request)
            return Reply()

    _app()
    picker = emoticon_picker.EmoticonPickerPopup()
    manager = NetworkManager()
    picker._network_manager = manager
    monkeypatch.setattr(emoticon_picker, "QNetworkRequest", FakeRequest)

    picker._load_icon(QToolButton(), "https://i0.hdslb.com/bfs/live/emote.png")

    request = manager.requests[0]
    assert request.raw_headers == {b"Referer": b"https://live.bilibili.com/"}
    assert request.headers == {"user-agent": "Mozilla/5.0 BiliHUD"}


def test_danmaku_delegate_renders_local_system_messages():
    html = message_list.DanmakuDelegate().get_html_for_message(
        make_system_message("BiliHUD Mirror 已启动: <url>")
    )

    assert "BiliHUD Mirror 已启动" in html
    assert "&lt;url&gt;" in html
    assert html.strip()


def test_danmaku_delegate_applies_the_selected_hud_font():
    delegate = message_list.DanmakuDelegate()
    delegate.set_font_family("Noto Sans CJK SC")

    html = delegate.get_html_for_message(make_system_message("测试字体"))

    assert "font-family: 'Noto Sans CJK SC';" in html


def test_danmaku_delegate_renders_gift_and_interaction_variants():
    gift = GiftMessage(
        author=MessageAuthor(uid=1, name="送礼用户", color="#FFD700"),
        segments=(TextSegment("赠送 辣条 x2"),),
        action="赠送",
        gift_name="辣条",
        quantity=2,
    )
    interact = InteractMessage(
        author=MessageAuthor(uid=2, name="互动用户", color="#AAAAAA"),
        segments=(TextSegment("关注了主播"),),
        interaction=InteractionKind.FOLLOW,
    )
    delegate = message_list.DanmakuDelegate()

    gift_html = delegate.get_html_for_message(gift)
    interact_html = delegate.get_html_for_message(interact)

    assert "送礼用户" in gift_html
    assert "赠送" in gift_html
    assert "辣条 x2" in gift_html
    assert "互动用户" in interact_html
    assert "关注了主播" in interact_html


def test_danmaku_delegate_renders_compact_author_badges():
    message = DanmakuMessage(
        author=MessageAuthor(
            uid=1,
            name="Locez",
            color="#FFD700",
            badges=(
                MessageBadge(MessageBadgeKind.MEDAL, "小狐 26", "粉丝牌", "#FF79C6"),
                MessageBadge(MessageBadgeKind.WEALTH, "✦ 8", "财富等级", "#C9B6FF"),
                MessageBadge(MessageBadgeKind.PRIVILEGE, "⚓︎", "大航海", "#86C8FF"),
            ),
        ),
        segments=(TextSegment("测试"),),
    )

    html = message_list.DanmakuDelegate().get_html_for_message(message)

    assert "meta-badge medal-badge" in html
    assert "小狐 26" in html
    assert "小狐 26</span>&nbsp;<span" in html
    assert "meta-badge wealth-badge" in html
    assert "✦ 8" in html
    assert "✦ 8</span>&nbsp;<span" in html
    assert "meta-badge privilege-badge" in html
    assert "⚓︎" in html
    assert "⚓︎</span>&nbsp;<span class=\"user\"" in html
    assert "舰长" not in html
    assert "荣8" not in html
    assert html.index("小狐 26") < html.index("Locez")


def test_danmaku_delegate_renders_reply_target_prefix():
    message = DanmakuMessage(
        author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
        segments=(ReplySegment("@绚下的小恐龙 "), TextSegment("test")),
    )

    html = message_list.DanmakuDelegate().get_html_for_message(message)

    assert ".reply { color: #FF79C6;" in html
    assert '<span class="reply">@绚下的小恐龙&nbsp;</span>test' in html


def test_danmaku_delegate_does_not_reuse_document_for_reused_message_id(monkeypatch):
    _app()

    def message(text: str) -> DanmakuMessage:
        return DanmakuMessage(
            author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
            segments=(TextSegment(text),),
        )

    delegate = message_list.DanmakuDelegate()
    monkeypatch.setattr(message_list, "id", lambda _message: 7450109, raising=False)

    first_doc = delegate._get_document(message("旧消息"), 320, QFont())
    second_doc = delegate._get_document(message("新消息"), 320, QFont())

    assert "旧消息" in first_doc.toPlainText()
    assert "新消息" in second_doc.toPlainText()
    assert "旧消息" not in second_doc.toPlainText()


def test_danmaku_widget_prunes_history_before_scrolling_to_bottom():
    class FakeDelegate:
        def set_font_family(self, font_family: str) -> None:
            del font_family

        def forget_message(self, message: HudMessage) -> None:
            del message
            calls.append("forget")

    class FakeList:
        def __init__(self):
            self._count = 200

        def addItem(self, item: QListWidgetItem | None) -> None:
            del item
            calls.append("add")
            self._count += 1

        def count(self):
            return self._count

        def takeItem(self, row) -> QListWidgetItem | None:
            del row
            calls.append("take")
            self._count -= 1
            item = QListWidgetItem()
            item.setData(
                Qt.ItemDataRole.UserRole,
                DanmakuMessage(
                    author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
                    segments=(TextSegment("旧弹幕"),),
                ),
            )
            return item

        def scrollToBottom(self):
            calls.append("scroll")

        def scheduleDelayedItemsLayout(self) -> None:
            pass

    class MirrorCoordinator:
        def publish_message(self, message: HudMessage) -> MirrorEntry:
            calls.append(("mirror-add", message))
            return {
                "seq": 1,
                "kind": "danmaku",
                "user": "",
                "userColor": "",
                "segments": [],
            }

    calls = []
    class Widget:
        danmaku_list: danmaku_widget.DanmakuListPort
        _danmaku_delegate: danmaku_widget.DanmakuDelegatePort
        mirror_coordinator: danmaku_widget.DanmakuMessagePublisher

        def __init__(self) -> None:
            self.danmaku_list = FakeList()
            self._danmaku_delegate = FakeDelegate()
            self.mirror_coordinator = MirrorCoordinator()

    widget = Widget()
    message = DanmakuMessage(
        author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
        segments=(TextSegment("新弹幕"),),
    )

    danmaku_widget.append_hud_message(widget, message)

    assert calls.index("take") < calls.index("scroll")
    assert calls.index("scroll") < calls.index(("mirror-add", message))


def test_modern_input_widget_exposes_emoticon_button_signal():
    _app()
    widget = hud_input.ModernInputWidget()

    seen = []
    widget.emoticon_requested.connect(lambda: seen.append(True))
    widget.emoticon_btn.click()

    assert seen == [True]


def test_modern_input_widget_can_hide_emoticon_button():
    _app()
    widget = hud_input.ModernInputWidget(show_emoticon_button=False)

    assert widget.emoticon_btn.isHidden()


def test_emoticon_picker_does_not_emit_locked_emoticons():
    _app()
    picker = emoticon_picker.EmoticonPickerPopup()
    locked = LiveEmoticon(
        emoji="疑惑",
        url="http://i0.hdslb.com/bfs/live/locked.png",
        width=162,
        height=162,
        perm=0,
        unique="room_870691_1154",
        emoticon_id=1154,
        unlock_label="舰长",
        unlock_color="#FF6699",
    )
    package = LiveEmoticonPackage(
        package_id=428,
        name="UP主大表情",
        package_type=2,
        package_perm=1,
        emoticons=(locked,),
    )
    emitted = []
    picker.emoticon_selected.connect(emitted.append)

    picker.set_packages([package])
    cell = picker._emoticon_buttons[0]
    cell.click()

    assert emitted == []
    assert "舰长" in cell.toolTip()
    assert "#FF6699" in cell.styleSheet()
    assert not cell.isEnabled()


def test_emoticon_picker_hides_after_available_emoticon_click():
    app = _app()
    picker = emoticon_picker.EmoticonPickerPopup()
    emoticon = LiveEmoticon(
        emoji="啊",
        url="http://i0.hdslb.com/bfs/live/a.png",
        width=200,
        height=60,
        perm=1,
        unique="official_331",
        emoticon_id=331,
    )
    package = LiveEmoticonPackage(1, "通用表情", 1, 1, (emoticon,))
    emitted = []
    picker.emoticon_selected.connect(emitted.append)
    picker.set_packages([package])
    picker.show()
    app.processEvents()

    picker._emoticon_buttons[0].click()

    assert emitted == [emoticon]
    assert not picker.isVisible()


def test_emoticon_picker_deletes_old_tab_pages_when_refreshing():
    app = _app()
    picker = emoticon_picker.EmoticonPickerPopup()

    for _ in range(5):
        picker.set_loading()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    labels = [label.text() for label in picker.findChildren(QLabel)]

    assert labels == ["加载中..."]


def test_emoticon_picker_keeps_one_tab_per_package():
    _app()
    picker = emoticon_picker.EmoticonPickerPopup()
    emoticon = LiveEmoticon(
        emoji="啊",
        url="http://i0.hdslb.com/bfs/live/a.png",
        width=200,
        height=60,
        perm=1,
        unique="official_331",
        emoticon_id=331,
    )
    packages = [
        LiveEmoticonPackage(1, "通用表情", 1, 1, (emoticon,)),
        LiveEmoticonPackage(2, "UP主大表情", 2, 1, (emoticon,)),
    ]

    picker.set_packages(packages)

    assert picker.tabs.count() == 2
    assert [picker.tabs.tabText(index) for index in range(picker.tabs.count())] == ["通用表情", "UP主大表情"]


def test_danmaku_widget_sends_selected_live_emoticon(monkeypatch):
    class Controller:
        def __init__(self) -> None:
            self.sent: list[LiveEmoticon] = []

        async def send_live_emoticon(self, emoticon: LiveEmoticon) -> None:
            self.sent.append(emoticon)

    async def run_test():
        controller = Controller()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        monkeypatch.setattr(danmaku_widget.DanmakuWidget, "hud_controller", controller, raising=False)
        emoticon = LiveEmoticon(
            emoji="啊",
            url="https://i0.hdslb.com/bfs/live/a.png",
            width=100,
            height=100,
            perm=1,
            unique="official_331",
            emoticon_id=331,
        )

        await danmaku_widget.DanmakuWidget._send_live_emoticon_task(widget, emoticon)

        assert controller.sent == [emoticon]

    asyncio.run(run_test())
