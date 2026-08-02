import asyncio
import os

import pytest
from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from bilihud import danmaku_widget
from bilihud.config import AppConfig
from bilihud.live_audience import AudienceSnapshot, AudienceUser
from bilihud.live_emoticons import LiveEmoticon, LiveEmoticonPackage

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
    widget.quit_app = lambda: events.append("quit")
    monkeypatch.setattr(danmaku_widget, "QAction", Action)
    monkeypatch.setattr(danmaku_widget, "QMenu", Menu)
    monkeypatch.setattr(danmaku_widget, "QSystemTrayIcon", TrayIcon)
    monkeypatch.setattr(danmaku_widget.os.path, "exists", lambda _path: False)

    danmaku_widget.DanmakuWidget.setup_tray_icon(widget)

    assert widget.tray_mirror_action.text == "BiliHUD Mirror"
    widget.tray_mirror_action.triggered.emit()
    assert events == ["mirror"]


def test_danmaku_widget_opens_single_mirror_settings_dialog(monkeypatch):
    class FakeDialog:
        instances = []

        def __init__(self, owner):
            self.owner = owner
            self.calls = []
            self.instances.append(self)

        def refresh(self):
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
    class FakeServer:
        def __init__(self):
            self.stop_calls = 0

        async def stop(self):
            self.stop_calls += 1

    async def run_test():
        server = FakeServer()
        events = []
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.mirror_server = server
        widget.mirror_enabled = True
        widget.refresh_mirror_settings = lambda: events.append("refresh")

        await danmaku_widget.DanmakuWidget.shutdown_mirror_server(widget)

        assert server.stop_calls == 1
        assert widget.mirror_server is None
        assert widget.mirror_enabled is True
        assert events == ["refresh"]

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
    class SystemMessage:
        uname = " [系统]"
        msg = "BiliHUD Mirror 已启动: <url>"
        is_system_info = True
        is_system_error = False
        privilege_type = 0
        vip = False
        svip = False
        admin = False

    html = danmaku_widget.DanmakuDelegate().get_html_for_message(SystemMessage())

    assert "BiliHUD Mirror 已启动" in html
    assert "&lt;url&gt;" in html
    assert html.strip()


def test_danmaku_delegate_renders_compact_author_badges():
    message = danmaku_widget.web_models.DanmakuMessage(
        uname="Locez",
        msg="测试",
        medal_name="小狐",
        medal_level=26,
        mcolor=0x2FB6E8,
        wealth_level=8,
        privilege_type=3,
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
    message = danmaku_widget.web_models.DanmakuMessage(
        uname="Locez",
        msg="test",
        mode_info={
            "extra": {
                "show_reply": True,
                "reply_uname": "绚下的小恐龙",
            }
        },
    )

    html = danmaku_widget.DanmakuDelegate().get_html_for_message(message)

    assert ".reply { color: #FF79C6;" in html
    assert '<span class="reply">@绚下的小恐龙&nbsp;</span>test' in html


def test_danmaku_delegate_does_not_reuse_document_for_reused_message_id(monkeypatch):
    _app()

    class Message:
        privilege_type = 0
        vip = False
        svip = False
        admin = False

        def __init__(self, text: str):
            self.uname = "Locez"
            self.msg = text

    delegate = danmaku_widget.DanmakuDelegate()
    monkeypatch.setattr(danmaku_widget, "id", lambda _message: 7450109, raising=False)

    first_doc = delegate._get_document(Message("旧消息"), 320, QFont())
    second_doc = delegate._get_document(Message("新消息"), 320, QFont())

    assert "旧消息" in first_doc.toPlainText()
    assert "新消息" in second_doc.toPlainText()
    assert "旧消息" not in second_doc.toPlainText()


def test_danmaku_widget_prunes_history_before_scrolling_to_bottom():
    class Message:
        uname = "Locez"
        msg = "新弹幕"
        privilege_type = 0
        vip = False
        svip = False
        admin = False

    class RemovedItem:
        def data(self, _role):
            return Message()

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

    class MirrorState:
        def add_message(self, message):
            calls.append(("mirror-add", message))
            return {"seq": 1}

    class MirrorServer:
        def publish_append(self, entry):
            calls.append(("mirror-publish", entry))

    calls = []
    class Widget:
        pass

    widget = Widget()
    widget.danmaku_list = FakeList()
    widget.mirror_state = MirrorState()
    widget.mirror_server = MirrorServer()
    message = Message()

    danmaku_widget.DanmakuWidget.add_message(widget, message)

    assert calls.index("take") < calls.index("scroll")
    assert calls.index("scroll") < calls.index(("mirror-add", message))
    assert ("mirror-publish", {"seq": 1}) in calls


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
    class Client:
        def __init__(self):
            self.sent = []

        async def send_live_emoticon(self, emoticon):
            self.sent.append(emoticon)
            return False, "没有发送权限"

    async def run_test():
        client = Client()
        errors = []
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.danmaku_client = client
        widget.add_system_message = lambda message, level: errors.append((message, level))
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

        assert client.sent == [emoticon]
        assert errors == [("发送失败: 没有发送权限", "error")]

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

        async def connect_to_room(room_id):
            connected_rooms.append(room_id)

        widget._connect_to_room_id = connect_to_room
        monkeypatch.setattr(danmaku_widget, "get_anchor_live_room_id", get_anchor_room)

        room_id = await danmaku_widget.DanmakuWidget._ensure_live_control_room(widget)

        assert room_id == 998877
        assert connected_rooms == [998877]
        assert auth_manager.session.close_calls == 1

    auth_manager = None
    asyncio.run(run_test())


def test_connect_to_room_replaces_stale_same_room_client(monkeypatch):
    events = []

    class RoomInput:
        def __init__(self):
            self.text = ""

        def setText(self, text):
            self.text = text

    class StaleBLiveClient:
        is_running = False

    class StaleDanmakuClient:
        client = StaleBLiveClient()

    class NewDanmakuClient:
        instances = []

        def __init__(self, room_id, sessdata, auth_service=None):
            self.room_id = room_id
            self.sessdata = sessdata
            self.auth_service = auth_service
            self.client = None
            self.started = False
            NewDanmakuClient.instances.append(self)

        async def start(self):
            self.started = True
            self.client = type("RunningBLiveClient", (), {"is_running": True})()

    async def run_test():
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.room_id = 7450109
        widget.sessdata = "sess"
        widget.auth_service = object()
        widget.mirror_port = 2233
        widget.config_store = type(
            "ConfigStore",
            (),
            {
                "load": lambda _self: AppConfig(),
                "save": lambda _self, config: events.append(("save", config)) or True,
            },
        )()
        widget.room_id_input = RoomInput()
        widget.danmaku_client = StaleDanmakuClient()

        async def disconnect_current_room():
            events.append("disconnect")
            widget.danmaku_client = None

        widget._disconnect_current_room = disconnect_current_room
        widget._wire_danmaku_client = lambda client: events.append(("wire", client.room_id))
        widget._set_connecting_ui = lambda: events.append("connecting")
        widget._set_connected_ui = lambda: events.append("connected")
        widget._set_disconnected_ui = lambda: events.append("disconnected")

        async def start_audience_refresh(client):
            events.append(("audience-start", client.room_id))

        widget._start_audience_refresh = start_audience_refresh

        monkeypatch.setattr(danmaku_widget, "DanmakuClient", NewDanmakuClient)

        await danmaku_widget.DanmakuWidget._connect_to_room_id(widget, 7450109)

        assert events[0] == "disconnect"
        assert widget.room_id == 7450109
        assert widget.room_id_input.text == "7450109"
        assert widget.danmaku_client is NewDanmakuClient.instances[0]
        assert widget.danmaku_client.started is True
        assert events[-2:] == ["connected", ("audience-start", 7450109)]

    asyncio.run(run_test())


def test_disconnect_current_room_stops_client_and_clears_connection():
    class Button:
        def __init__(self):
            self.enabled = True

        def setEnabled(self, enabled):
            self.enabled = enabled

    class Client:
        def __init__(self):
            self.stop_calls = 0

        async def stop(self):
            self.stop_calls += 1

    async def run_test():
        events = []
        client = Client()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.connect_button = Button()
        widget.danmaku_client = client
        widget._audience_snapshot = None

        async def stop_audience_refresh():
            events.append("audience-stop")

        widget._stop_audience_refresh = stop_audience_refresh
        widget._set_disconnected_ui = lambda: events.append("disconnected")

        await danmaku_widget.DanmakuWidget._disconnect_current_room(widget)

        assert client.stop_calls == 1
        assert widget.danmaku_client is None
        assert widget.connect_button.enabled is False
        assert events == ["audience-stop", "disconnected"]

    asyncio.run(run_test())


def audience_snapshot(room_id=7450109):
    return AudienceSnapshot(
        room_id=room_id,
        popularity=21,
        watched_count=9,
        online_rank_count=3,
        users=(AudienceUser(1001, "用户A", 1, 1, False),),
    )


def test_refresh_audience_once_applies_only_current_room_and_generation():
    class Client:
        room_id = 7450109

        async def fetch_audience_snapshot(self):
            return audience_snapshot()

    class Status:
        def set_snapshot(self, snapshot):
            applied.append(snapshot)

        def setVisible(self, visible):
            visibility.append(visible)

    class Popup:
        def set_snapshot(self, snapshot):
            popup_applied.append(snapshot)

        def hide(self):
            popup_hidden.append(True)

    async def run_test():
        client = Client()
        class Widget:
            pass

        widget = Widget()
        widget.danmaku_client = client
        widget.room_id = 7450109
        widget._audience_generation = 4
        widget._audience_snapshot = None
        widget.is_gaming_mode = False
        widget.audience_status = Status()
        widget.audience_popup = Popup()
        widget._sync_audience_visibility = lambda: (
            danmaku_widget.DanmakuWidget._sync_audience_visibility(widget)
        )

        updated = await danmaku_widget.DanmakuWidget._refresh_audience_once(widget, client, 4)
        stale = await danmaku_widget.DanmakuWidget._refresh_audience_once(widget, client, 3)

        assert updated is True
        assert stale is False
        assert widget._audience_snapshot == audience_snapshot()
        assert applied == [audience_snapshot()]
        assert popup_applied == [audience_snapshot()]
        assert visibility == [True]
        assert popup_hidden == []

    applied = []
    popup_applied = []
    popup_hidden = []
    visibility = []
    asyncio.run(run_test())


def test_refresh_audience_once_keeps_last_snapshot_after_failure():
    previous = audience_snapshot()

    class Client:
        room_id = 7450109

        async def fetch_audience_snapshot(self):
            raise RuntimeError("temporary failure")

    async def run_test():
        client = Client()
        class Widget:
            pass

        widget = Widget()
        widget.danmaku_client = client
        widget.room_id = 7450109
        widget._audience_generation = 2
        widget._audience_snapshot = previous

        updated = await danmaku_widget.DanmakuWidget._refresh_audience_once(widget, client, 2)

        assert updated is False
        assert widget._audience_snapshot is previous

    asyncio.run(run_test())


def test_stop_audience_refresh_cancels_task_and_clears_widgets():
    class Status:
        def clear(self):
            calls.append("status-clear")

    class Popup:
        def hide(self):
            calls.append("popup-hide")

    async def run_test():
        started = asyncio.Event()

        async def forever():
            started.set()
            await asyncio.Event().wait()

        class Widget:
            pass

        widget = Widget()
        widget._audience_generation = 1
        widget._audience_snapshot = audience_snapshot()
        widget.audience_status = Status()
        widget.audience_popup = Popup()
        widget._audience_refresh_task = asyncio.create_task(forever())
        await started.wait()

        await danmaku_widget.DanmakuWidget._stop_audience_refresh(widget)

        assert widget._audience_refresh_task is None
        assert widget._audience_snapshot is None
        assert calls == ["popup-hide", "status-clear"]

    calls = []
    asyncio.run(run_test())


def test_disconnect_failure_restores_last_audience_snapshot():
    previous = audience_snapshot()

    class Client:
        async def stop(self):
            raise RuntimeError("temporary failure")

    class Button:
        def setEnabled(self, enabled):
            calls.append(("button", enabled))

    class Status:
        def set_snapshot(self, snapshot):
            calls.append(("status", snapshot))

    class Popup:
        def set_snapshot(self, snapshot):
            calls.append(("popup", snapshot))

    async def run_test():
        class Widget:
            pass

        widget = Widget()
        widget.connect_button = Button()
        widget.danmaku_client = Client()
        widget._audience_snapshot = previous
        widget.audience_status = Status()
        widget.audience_popup = Popup()
        widget._set_connected_ui = lambda: calls.append("connected")
        widget._sync_audience_visibility = lambda: calls.append("visibility")
        widget.add_system_message = lambda message, level: calls.append((level, message))

        async def stop_refresh():
            widget._audience_snapshot = None

        async def start_refresh(client):
            calls.append(("refresh", client))

        widget._stop_audience_refresh = stop_refresh
        widget._start_audience_refresh = start_refresh

        with pytest.raises(RuntimeError, match="temporary failure"):
            await danmaku_widget.DanmakuWidget._disconnect_current_room(widget)

        assert widget._audience_snapshot is previous
        assert ("status", previous) in calls
        assert ("popup", previous) in calls
        assert "visibility" in calls

    calls = []
    asyncio.run(run_test())


def test_sync_audience_visibility_hides_status_and_popup_in_gaming_mode():
    calls = []

    class Status:
        def setVisible(self, visible):
            calls.append(("visible", visible))

    class Popup:
        def hide(self):
            calls.append(("popup", False))

    class Widget:
        pass

    widget = Widget()
    widget._audience_snapshot = audience_snapshot()
    widget.is_gaming_mode = True
    widget.audience_status = Status()
    widget.audience_popup = Popup()

    danmaku_widget.DanmakuWidget._sync_audience_visibility(widget)

    assert calls == [("visible", False), ("popup", False)]


def test_audience_refresh_loop_waits_thirty_seconds(monkeypatch):
    class Client:
        room_id = 7450109

    async def run_test():
        class Widget:
            pass

        widget = Widget()

        async def refresh_once(client, generation):
            calls.append(("refresh", client.room_id, generation))
            return True

        async def fake_sleep(delay):
            calls.append(("sleep", delay))
            raise asyncio.CancelledError

        widget._refresh_audience_once = refresh_once
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await danmaku_widget.DanmakuWidget._audience_refresh_loop(widget, Client(), 7)

    calls = []
    asyncio.run(run_test())

    assert calls == [
        ("refresh", 7450109, 7),
        ("sleep", danmaku_widget.AUDIENCE_REFRESH_INTERVAL_SECONDS),
    ]
    assert danmaku_widget.AUDIENCE_REFRESH_INTERVAL_SECONDS == 30.0
