import asyncio
import logging

import pytest
from PyQt6.QtWidgets import QApplication

from bilihud import main as main_module
from bilihud.app.lifecycle import TaskSupervisor
from bilihud.danmaku_widget import DanmakuWidget
from bilihud.main import ApplicationRuntime
from bilihud.qr_login_dialog import QRLoginDialog


def test_task_supervisor_cancels_owned_tasks_and_is_idempotent():
    async def run_test():
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("test-owner")
        started = asyncio.Event()
        cleanup_seen = False

        async def wait_forever():
            nonlocal cleanup_seen
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_seen = True
                raise

        task = scope.create_task(wait_forever(), name="wait-forever")
        await started.wait()

        await supervisor.shutdown()
        await supervisor.shutdown()
        await asyncio.sleep(0)

        assert task.cancelled()
        assert cleanup_seen is True
        assert supervisor.pending_tasks() == ()

    asyncio.run(run_test())


def test_task_supervisor_logs_unhandled_task_failure(caplog):
    async def run_test():
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("test-owner")

        async def fail():
            raise RuntimeError("background failure")

        scope.create_task(fail(), name="failing-task")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await supervisor.shutdown()

    with caplog.at_level(logging.ERROR, logger="bilihud.app.lifecycle"):
        asyncio.run(run_test())

    assert "后台任务失败: owner=test-owner task=failing-task" in caplog.text
    assert "background failure" in caplog.text


def test_task_supervisor_rejects_new_work_after_shutdown():
    async def run_test():
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("test-owner")
        await supervisor.shutdown()

        async def never_started():
            await asyncio.Event().wait()

        with pytest.raises(RuntimeError, match="任务监督器已关闭"):
            scope.create_task(never_started(), name="late-task")

    asyncio.run(run_test())


def test_application_runtime_stops_widget_and_supervised_tasks(monkeypatch):
    events = []
    pending_task = None

    class FakeWidget:
        def __init__(self, _room_id, *, services, task_supervisor):
            nonlocal pending_task
            events.append(("create", services))
            scope = task_supervisor.create_scope("fake-widget")

            async def wait_forever():
                await asyncio.Event().wait()

            pending_task = scope.create_task(wait_forever(), name="owned-task")

        def activate_layer_shell(self):
            events.append("activate")

        def show(self):
            events.append("show")

        async def start(self):
            events.append("start")

        async def shutdown(self):
            events.append("widget-shutdown")

    monkeypatch.setattr(main_module, "DanmakuWidget", FakeWidget)

    async def run_test():
        runtime = ApplicationRuntime(object(), 7450109, services="services")
        await runtime.start()
        await runtime.start()
        await runtime.stop()
        await runtime.stop()
        assert pending_task is not None
        assert pending_task.cancelled()

    asyncio.run(run_test())

    assert events == [("create", "services"), "activate", "show", "start", "widget-shutdown"]


def test_application_runtime_can_retry_after_widget_shutdown_failure(monkeypatch):
    class FakeWidget:
        shutdown_calls = 0

        def __init__(self, _room_id, *, services, task_supervisor):
            pass

        def activate_layer_shell(self):
            pass

        def show(self):
            pass

        async def start(self):
            pass

        async def shutdown(self):
            self.shutdown_calls += 1
            if self.shutdown_calls == 1:
                raise RuntimeError("close failed")

    monkeypatch.setattr(main_module, "DanmakuWidget", FakeWidget)

    async def run_test():
        runtime = ApplicationRuntime(object(), 7450109)
        await runtime.start()

        with pytest.raises(RuntimeError, match="close failed"):
            await runtime.stop()
        assert runtime._stopped is False

        await runtime.stop()
        assert runtime._stopped is True
        assert runtime.widget is not None
        assert runtime.widget.shutdown_calls == 2

    asyncio.run(run_test())


def test_danmaku_widget_shutdown_cancels_work_before_closing_resources():
    async def run_test():
        supervisor = TaskSupervisor()
        scope = supervisor.create_scope("danmaku-widget")
        started = asyncio.Event()
        events = []

        async def wait_for_send():
            started.set()
            await asyncio.Event().wait()

        class HudController:
            async def shutdown(self):
                events.append("client-stop")

        widget = DanmakuWidget.__new__(DanmakuWidget)
        widget._task_supervisor = supervisor
        widget._owns_task_supervisor = False
        widget._task_scope = scope
        widget._action_tasks = set()
        widget._mirror_start_task = None
        widget._settings_dialog = None
        widget._qr_login_dialog = None
        widget._shutdown_complete = False
        widget._shutting_down = False
        widget.hud_controller = HudController()

        send_task = DanmakuWidget._create_action_task(
            widget,
            wait_for_send(),
            name="send-danmaku",
        )
        await started.wait()

        async def shutdown_mirror_server():
            events.append("mirror-stop")

        widget.shutdown_mirror_server = shutdown_mirror_server

        await DanmakuWidget.shutdown(widget)
        await DanmakuWidget.shutdown(widget)

        assert send_task.cancelled()
        assert events == ["client-stop", "mirror-stop"]

    asyncio.run(run_test())


def test_qr_login_dialog_shutdown_cancels_polling_work():
    class FakeAuthService:
        pass

    app = QApplication.instance() or QApplication([])
    assert app is not None
    dialog = QRLoginDialog(auth_service=FakeAuthService())

    async def run_test():
        started = asyncio.Event()

        async def wait_for_poll():
            started.set()
            await asyncio.Event().wait()

        dialog._load_task = dialog._task_scope.create_task(wait_for_poll(), name="load-qrcode")
        await started.wait()

        await dialog.shutdown()
        await dialog.shutdown()

        assert dialog._load_task.cancelled()
        assert dialog._shutdown_complete is True

    asyncio.run(run_test())
    dialog.deleteLater()
