import asyncio
import os

import pytest
from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from bilihud import danmaku_widget
from bilihud.domain.messages import (
    DanmakuMessage,
    GiftMessage,
    InteractionKind,
    InteractMessage,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    ReplySegment,
    TextSegment,
    make_system_message,
)
from bilihud.live_emoticons import LiveEmoticon, LiveEmoticonPackage
from bilihud.mirror_coordinator import MirrorCoordinatorState, MirrorOperationResult

_QT_APP = None


def _app():
    global _QT_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_layer_shell_drag_updates_anchor_position(monkeypatch):
    class FakeGeometry:
        def x(self):
            return 0

        def y(self):
            return 0

        def width(self):
            return 1920

        def height(self):
            return 1080

    class FakeScreen:
        def geometry(self):
            return FakeGeometry()

    class FakeWindow:
        def screen(self):
            return FakeScreen()

    class FakeLayerShell:
        def __init__(self):
            self.calls = []

        def set_anchor_position(self, pointer, x, y):
            self.calls.append((pointer, x, y))

    class FakePosition:
        def toPoint(self):
            return QPoint(20, 20)

    class FakeEvent:
        def position(self):
            return FakePosition()

        def accept(self):
            pass

    layer_shell = FakeLayerShell()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._dragging = True
    widget._drag_local_pos = QPoint(10, 10)
    widget.layer_pos = QPoint(100, 100)
    widget.layer_shell_lib = layer_shell

    monkeypatch.setattr(danmaku_widget.sip, "unwrapinstance", lambda _window: 123)
    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "windowHandle", lambda _self: FakeWindow())
    monkeypatch.setattr(danmaku_widget.DanmakuWidget, "width", lambda _self: 300)

    danmaku_widget.DanmakuWidget.mouseMoveEvent(widget, FakeEvent())

    assert widget.layer_pos == QPoint(110, 110)
    pointer, x, y = layer_shell.calls[0]
    assert pointer.value == 123
    assert (x, y) == (110, 110)


def test_danmaku_widget_exposes_bilihud_mirror_tray_action(monkeypatch):
    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in self.callbacks:
                callback(*args)

    class Action:
        def __init__(self, text, _parent):
            self.text = text
            self.triggered = Signal()

        def setCheckable(self, _checkable):
            pass

    class Menu:
        def setStyleSheet(self, _style):
            pass

        def addAction(self, _action):
            pass

        def addSeparator(self):
            pass

    class TrayIcon:
        def __init__(self, _parent):
            self.activated = Signal()

        def setContextMenu(self, _menu):
            pass

        def show(self):
            pass

    events = []
    _app()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget.open_input_dialog = lambda: events.append("input")
    widget.toggle_visibility = lambda: events.append("visibility")
    widget.toggle_gaming_mode_from_tray = lambda checked: events.append(("gaming", checked))
    widget.open_qr_login = lambda: events.append("login")
    widget.open_live_control = lambda: events.append("live-control")
    widget.open_mirror_settings = lambda: events.append("mirror")
    widget.trigger_danmaku_simulation = lambda: events.append("mock")
    widget.quit_app = lambda: events.append("quit")
    monkeypatch.setattr(danmaku_widget, "QAction", Action)
    monkeypatch.setattr(danmaku_widget, "QMenu", Menu)
    monkeypatch.setattr(danmaku_widget, "QSystemTrayIcon", TrayIcon)
    monkeypatch.setattr(danmaku_widget.os.path, "exists", lambda _path: False)

    danmaku_widget.DanmakuWidget.setup_tray_icon(widget)

    assert widget.tray_mirror_action.text == "BiliHUD Mirror"
    widget.tray_mirror_action.triggered.emit()
    assert events == ["mirror"]
    assert widget.tray_mock_action.text == "弹幕模拟"
    widget.tray_mock_action.triggered.emit()
    assert events == ["mirror", "mock"]


def test_danmaku_widget_injects_fixed_mock_messages_into_hud(monkeypatch):
    _app()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._shutting_down = False
    received = []
    widget.add_message = received.append

    danmaku_widget.DanmakuWidget.trigger_danmaku_simulation(widget)

    assert len(received) == len(danmaku_widget.mock_message_batch())


def test_danmaku_widget_opens_single_mirror_settings_dialog(monkeypatch):
    class Signal:
        def connect(self, _callback):
            pass

    class FakeDialog:
        instances = []

        def __init__(self, owner):
            self.owner = owner
            self.calls = []
            self.mirror_enabled_requested = Signal()
            self.instances.append(self)

        def refresh(self, _state):
            self.calls.append("refresh")

        def show(self):
            self.calls.append("show")

        def raise_(self):
            self.calls.append("raise")

        def activateWindow(self):
            self.calls.append("activate")

    _app()
    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    QWidget.__init__(widget)
    widget._shutting_down = False
    widget._mirror_settings_dialog = None
    widget.mirror_coordinator = type(
        "Coordinator",
        (),
        {"state": MirrorCoordinatorState(False, False, 2233, "http://127.0.0.1:2233/bilihud-mirror")},
    )()
    monkeypatch.setattr(danmaku_widget, "MirrorSettingsDialog", FakeDialog)

    danmaku_widget.DanmakuWidget.open_mirror_settings(widget)
    danmaku_widget.DanmakuWidget.open_mirror_settings(widget)

    assert len(FakeDialog.instances) == 1
    assert FakeDialog.instances[0].calls == [
        "refresh",
        "show",
        "raise",
        "activate",
        "refresh",
        "show",
        "raise",
        "activate",
    ]


def test_danmaku_widget_keeps_mirror_enabled_config_when_shutting_down():
    class FakeCoordinator:
        def __init__(self):
            self.shutdown_calls = 0
            self.state = MirrorCoordinatorState(True, True, 2233, "http://127.0.0.1:2233/bilihud-mirror")

        async def shutdown(self):
            self.shutdown_calls += 1
            self.state = MirrorCoordinatorState(True, False, 2233, "http://127.0.0.1:2233/bilihud-mirror")
            return MirrorOperationResult(self.state)

    async def run_test():
        coordinator = FakeCoordinator()
        events = []
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.mirror_coordinator = coordinator
        widget.refresh_mirror_settings = lambda: events.append("refresh")

        await danmaku_widget.DanmakuWidget.shutdown_mirror_server(widget)

        assert coordinator.shutdown_calls == 1
        assert coordinator.state.enabled is True
        assert coordinator.state.running is False
        assert events == ["refresh"]

    asyncio.run(run_test())


def test_danmaku_widget_keeps_mirror_reference_when_stop_fails():
    class FakeCoordinator:
        def __init__(self):
            self.shutdown_calls = 0
            self.state = MirrorCoordinatorState(True, True, 2233, "http://127.0.0.1:2233/bilihud-mirror")

        async def shutdown(self):
            self.shutdown_calls += 1
            if self.shutdown_calls == 1:
                raise RuntimeError("mirror close failed")
            self.state = MirrorCoordinatorState(True, False, 2233, "http://127.0.0.1:2233/bilihud-mirror")
            return MirrorOperationResult(self.state)

    async def run_test():
        coordinator = FakeCoordinator()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.mirror_coordinator = coordinator
        widget.refresh_mirror_settings = lambda: None

        with pytest.raises(RuntimeError, match="mirror close failed"):
            await danmaku_widget.DanmakuWidget.shutdown_mirror_server(widget)
        assert coordinator.state.running is True

        await danmaku_widget.DanmakuWidget.shutdown_mirror_server(widget)
        assert coordinator.state.running is False
        assert coordinator.shutdown_calls == 2

    asyncio.run(run_test())


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

    class Signal:
        def connect(self, _callback):
            pass

    class Reply:
        finished = Signal()

    class NetworkManager:
        def __init__(self):
            self.requests = []

        def get(self, request):
            self.requests.append(request)
            return Reply()

    class Button:
        pass

    _app()
    picker = danmaku_widget.EmoticonPickerPopup()
    manager = NetworkManager()
    picker._network_manager = manager
    monkeypatch.setattr(danmaku_widget, "QNetworkRequest", FakeRequest)

    picker._load_icon(Button(), "https://i0.hdslb.com/bfs/live/emote.png")

    request = manager.requests[0]
    assert request.raw_headers == {b"Referer": b"https://live.bilibili.com/"}
    assert request.headers == {"user-agent": "Mozilla/5.0 BiliHUD"}


def test_danmaku_delegate_renders_local_system_messages():
    html = danmaku_widget.DanmakuDelegate().get_html_for_message(
        make_system_message("BiliHUD Mirror 已启动: <url>")
    )

    assert "BiliHUD Mirror 已启动" in html
    assert "&lt;url&gt;" in html
    assert html.strip()


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
    delegate = danmaku_widget.DanmakuDelegate()

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

    html = danmaku_widget.DanmakuDelegate().get_html_for_message(message)

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

    html = danmaku_widget.DanmakuDelegate().get_html_for_message(message)

    assert ".reply { color: #FF79C6;" in html
    assert '<span class="reply">@绚下的小恐龙&nbsp;</span>test' in html


def test_danmaku_delegate_does_not_reuse_document_for_reused_message_id(monkeypatch):
    _app()

    def message(text: str) -> DanmakuMessage:
        return DanmakuMessage(
            author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
            segments=(TextSegment(text),),
        )

    delegate = danmaku_widget.DanmakuDelegate()
    monkeypatch.setattr(danmaku_widget, "id", lambda _message: 7450109, raising=False)

    first_doc = delegate._get_document(message("旧消息"), 320, QFont())
    second_doc = delegate._get_document(message("新消息"), 320, QFont())

    assert "旧消息" in first_doc.toPlainText()
    assert "新消息" in second_doc.toPlainText()
    assert "旧消息" not in second_doc.toPlainText()


def test_danmaku_widget_prunes_history_before_scrolling_to_bottom():
    class RemovedItem:
        def data(self, _role):
            return DanmakuMessage(
                author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
                segments=(TextSegment("旧弹幕"),),
            )

    class FakeDelegate:
        def forget_message(self, _message):
            calls.append("forget")

    class FakeList:
        def __init__(self):
            self._count = 200

        def addItem(self, _item):
            calls.append("add")
            self._count += 1

        def count(self):
            return self._count

        def takeItem(self, _row):
            calls.append("take")
            self._count -= 1
            return RemovedItem()

        def itemDelegate(self):
            return FakeDelegate()

        def scrollToBottom(self):
            calls.append("scroll")

    class MirrorCoordinator:
        def publish_message(self, message):
            calls.append(("mirror-add", message))
            return {"seq": 1}

    calls = []
    class Widget:
        pass

    widget = Widget()
    widget.danmaku_list = FakeList()
    widget.mirror_coordinator = MirrorCoordinator()
    message = DanmakuMessage(
        author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
        segments=(TextSegment("新弹幕"),),
    )

    danmaku_widget.DanmakuWidget.add_message(widget, message)

    assert calls.index("take") < calls.index("scroll")
    assert calls.index("scroll") < calls.index(("mirror-add", message))


def test_modern_input_widget_exposes_emoticon_button_signal():
    _app()
    widget = danmaku_widget.ModernInputWidget()

    seen = []
    widget.emoticon_requested.connect(lambda: seen.append(True))
    widget.emoticon_btn.click()

    assert seen == [True]


def test_modern_input_widget_can_hide_emoticon_button():
    _app()
    widget = danmaku_widget.ModernInputWidget(show_emoticon_button=False)

    assert widget.emoticon_btn.isHidden()


def test_emoticon_picker_does_not_emit_locked_emoticons():
    _app()
    picker = danmaku_widget.EmoticonPickerPopup()
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
    picker = danmaku_widget.EmoticonPickerPopup()
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
    picker = danmaku_widget.EmoticonPickerPopup()

    for _ in range(5):
        picker.set_loading()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    labels = [label.text() for label in picker.findChildren(QLabel)]

    assert labels == ["加载中..."]


def test_emoticon_picker_keeps_one_tab_per_package():
    _app()
    picker = danmaku_widget.EmoticonPickerPopup()
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


def test_danmaku_widget_sends_selected_live_emoticon():
    class Controller:
        def __init__(self):
            self.sent = []

        async def send_live_emoticon(self, emoticon):
            self.sent.append(emoticon)
            return None

    async def run_test():
        controller = Controller()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.hud_controller = controller
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


def test_live_control_uses_authenticated_anchor_room(monkeypatch):
    class Session:
        def __init__(self):
            self.closed = False
            self.close_calls = 0

        async def close(self):
            self.closed = True
            self.close_calls += 1

    class AuthManager:
        def __init__(self):
            self.session = Session()

        async def create_authenticated_session(self):
            return self.session, True

    async def get_anchor_room(session):
        assert session is auth_manager.session
        return 998877

    async def run_test():
        nonlocal auth_manager
        auth_manager = AuthManager()
        connected_rooms = []
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.auth_service = auth_manager

        class Controller:
            async def connect(self, room_id):
                connected_rooms.append(room_id)

        widget.hud_controller = Controller()
        monkeypatch.setattr(danmaku_widget, "get_anchor_live_room_id", get_anchor_room)

        room_id = await danmaku_widget.DanmakuWidget._ensure_live_control_room(widget)

        assert room_id == 998877
        assert connected_rooms == [998877]
        assert auth_manager.session.close_calls == 1

    auth_manager = None
    asyncio.run(run_test())
