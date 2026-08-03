import os
import sys

# [Security] Prevent accidental loading of PyQt5 which causes conflicts
sys.modules["PyQt5"] = None

# [Environment] Force Qt6
os.environ["QT_API"] = "pyqt6"

import asyncio
import logging
import signal
from collections.abc import Iterable
from typing import Any

import qasync
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from .app.lifecycle import TaskSupervisor
from .app.services import AppServices, create_default_services
from .danmaku_widget import DanmakuWidget


def configure_logging() -> None:
    """Send application diagnostics to the terminal without enabling noisy modules."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    for logger_name in (
        "bilihud.platform.window_platform",
        "bilihud.platform.layer_shell",
    ):
        logging.getLogger(logger_name).setLevel(logging.INFO)


class ApplicationRuntime:
    """Own the top-level widget and the application-wide async lifecycle."""

    def __init__(
        self,
        app: QApplication,
        room_id: int,
        services: AppServices | None = None,
        task_supervisor: TaskSupervisor | None = None,
    ) -> None:
        """Create a runtime that will assemble and own one application window."""
        self.app = app
        self.room_id = room_id
        self.services = services
        self.task_supervisor = task_supervisor if task_supervisor is not None else TaskSupervisor()
        self.widget: DanmakuWidget | None = None
        self._stop_lock = asyncio.Lock()
        self._stopped = False

    async def start(self) -> None:
        """Create, configure, and show the top-level window exactly once."""
        if self._stopped:
            raise RuntimeError("应用运行时已关闭")
        if self.widget is not None:
            return

        widget = DanmakuWidget(
            self.room_id,
            services=self.services,
            task_supervisor=self.task_supervisor,
        )
        self.widget = widget
        try:
            widget.activate_layer_shell()
            widget.show()
            await widget.start()
        except BaseException:
            try:
                await widget.shutdown()
            finally:
                await self.task_supervisor.shutdown()
            raise

    async def stop(self) -> None:
        """Stop the window-owned workflows and await all supervised tasks."""
        async with self._stop_lock:
            if self._stopped:
                return
            try:
                if self.widget is not None:
                    await self.widget.shutdown()
            finally:
                await self.task_supervisor.shutdown()
            self._stopped = True


async def main(
    app: QApplication,
    room_id: int,
    services: AppServices | None = None,
) -> None:
    """Run the top-level widget until Qt requests application shutdown."""
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    app_services = services if services is not None else create_default_services()
    runtime = ApplicationRuntime(app, room_id, services=app_services)
    try:
        await runtime.start()
        await app_close_event.wait()
    finally:
        await runtime.stop()


async def cancel_pending_tasks(
    loop: asyncio.AbstractEventLoop,
    exclude: Iterable[asyncio.Task[Any]] | None = None,
) -> None:
    """Cancel and await outstanding asyncio tasks during application shutdown."""
    excluded_tasks = set(exclude or ())
    current_task = asyncio.current_task(loop=loop)
    if current_task is not None:
        excluded_tasks.add(current_task)
    pending = [task for task in asyncio.all_tasks(loop) if task not in excluded_tasks and not task.done()]
    if not pending:
        return

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)

def entry_point():
    """Parse CLI options, start the Qt/asyncio event loop, and shut it down cleanly."""
    configure_logging()
    import argparse

    parser = argparse.ArgumentParser(description="B station Danmaku Reader")
    parser.add_argument("--room-id", "-r", type=int, default=7450109, help="Room ID")
    args = parser.parse_args()

    # High DPI scaling settings
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"

    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, 'PassThrough'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    # Handle SIGINT
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("bilihud")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    main_task = loop.create_task(main(app, args.room_id), name="application-main")

    try:
        loop.run_forever()
    finally:
        try:
            if not main_task.done():
                loop.run_until_complete(main_task)
        finally:
            # ApplicationRuntime performs the owned shutdown first; this is the last-resort fallback.
            loop.run_until_complete(cancel_pending_tasks(loop, exclude={main_task}))
            loop.close()

if __name__ == "__main__":
    entry_point()
