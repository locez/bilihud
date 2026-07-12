import ast
import asyncio
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QFont, QImage
from PyQt6.QtWidgets import QApplication, QLabel

from bilihud import danmaku_widget
from bilihud.live_audience import AudienceSnapshot, AudienceUser
from bilihud.live_emoticons import LiveEmoticon, LiveEmoticonPackage

_QT_APP = None


def _app():
    global _QT_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_danmaku_widget_does_not_manually_process_qt_events():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "QApplication.processEvents()" not in source


def test_layer_shell_drag_does_not_force_widget_repaint():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_source = None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DanmakuWidget":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "mouseMoveEvent":
                    method_source = ast.get_source_segment(source, item)
                    break

    assert method_source is not None
    assert "set_anchor_position" in method_source
    assert "self.update()" not in method_source


def test_layer_shell_anchor_position_commits_surface():
    source = Path("src/bilihud/layer_shell_bridge.cpp").read_text(encoding="utf-8")
    function_start = source.index("void set_anchor_position")
    function_end = source.index("void set_keyboard_interactivity", function_start)
    function_source = source[function_start:function_end]

    assert "ls_window->setMargins(margins);" in function_source
    assert "nativeResourceForWindow(\"surface\", window)" in function_source
    assert "wl_surface_commit(surface);" in function_source


def test_danmaku_widget_imports_qimage_for_emoticon_loader():
    assert danmaku_widget.QImage is QImage


def test_danmaku_widget_imports_mirror_components():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "from .mirror_state import MIRROR_DEFAULT_PORT, MIRROR_ROUTE, MirrorState" in source
    assert "from .mirror_server import MirrorServer" in source
    assert "from .mirror_settings_dialog import MirrorSettingsDialog" in source


def test_danmaku_widget_add_message_publishes_to_mirror():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "entry = self.mirror_state.add_message(message)" in source
    assert "self.mirror_server.publish_append(entry)" in source


def test_danmaku_widget_exposes_bilihud_mirror_tray_action():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert 'QAction("BiliHUD Mirror", self)' in source
    assert source.count('QAction("BiliHUD Mirror", self)') == 1
    assert "open_mirror_settings" in source
    assert "MIRROR_ROUTE" in source
    assert "显示 Mirror URL" not in source
    assert "启动 BiliHUD Mirror" not in source
    assert "停止 BiliHUD Mirror" not in source
    assert "obs-mirror" not in source
    assert "obs-danmaku" not in source


def test_danmaku_widget_opens_single_mirror_settings_dialog():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "def open_mirror_settings(self):" in source
    assert "MirrorSettingsDialog(self)" in source
    assert "_mirror_settings_dialog" in source


def test_danmaku_widget_keeps_mirror_enabled_config_when_quitting():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "await self.shutdown_mirror_server()" in source
    assert "def mirror_status_text(self)" in source
    assert "self.mirror_error" in source
    assert 'return f"启动失败: {self.mirror_error}"' in source
    assert "async def set_mirror_enabled(self, enabled: bool)" in source
    assert source.index("async def shutdown_mirror_server") > source.index("async def stop_mirror_server")
    shutdown_body = source.split("async def shutdown_mirror_server", 1)[1]
    assert 'save_config({"mirror_enabled": False' not in shutdown_body


def test_danmaku_widget_emoticon_requests_include_bilibili_headers():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert 'request.setRawHeader(b"Referer", b"https://live.bilibili.com/")' in source
    assert "https://live.bilibili.com/" in source
    assert "QNetworkRequest.KnownHeaders.UserAgentHeader" in source


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
        def add_message(self, _message):
            return {"seq": 1}

    calls = []
    class Widget:
        pass

    widget = Widget()
    widget.danmaku_list = FakeList()
    widget.mirror_state = MirrorState()
    widget.mirror_server = None

    danmaku_widget.DanmakuWidget.add_message(widget, Message())

    assert calls.index("take") < calls.index("scroll")


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


def test_danmaku_widget_source_wires_emoticon_picker_to_client_methods():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "self.input_area.emoticon_requested.connect(self.open_emoticon_picker)" in source
    assert "await self.danmaku_client.fetch_live_emoticons()" in source
    assert "await self.danmaku_client.send_live_emoticon(emoticon)" in source


def test_live_control_uses_anchor_room_and_connects_hud_when_opened_source():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "get_anchor_live_room_id" in source
    assert "async def open_live_control(self):" in source
    assert "anchor_room_id = await self._ensure_live_control_room()" in source
    assert "self._live_control_dialog.set_room_id(anchor_room_id)" in source
    assert "self._live_control_dialog.set_room_id(self.room_id)" not in source
    assert "await self._connect_to_room_id(anchor_room_id)" in source
    assert "set_ensure_hud_room_callback" not in source


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

        def __init__(self, room_id, sessdata):
            self.room_id = room_id
            self.sessdata = sessdata
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
        monkeypatch.setattr(danmaku_widget, "save_config", lambda data: events.append(("save", data)))

        await danmaku_widget.DanmakuWidget._connect_to_room_id(widget, 7450109)

        assert events[0] == "disconnect"
        assert widget.room_id == 7450109
        assert widget.room_id_input.text == "7450109"
        assert widget.danmaku_client is NewDanmakuClient.instances[0]
        assert widget.danmaku_client.started is True
        assert events[-2:] == ["connected", ("audience-start", 7450109)]

    asyncio.run(run_test())


def test_live_control_start_live_does_not_manage_hud_connection():
    source = Path("src/bilihud/live_control_dialog.py").read_text(encoding="utf-8")

    assert "_ensure_hud_room_callback" not in source
    assert "set_ensure_hud_room_callback" not in source
    assert "_ensure_hud_room" not in source


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
