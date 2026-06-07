# -*- coding: utf-8 -*-
import sys
import os

# [Security] Prevent accidental loading of PyQt5 which causes conflicts
sys.modules["PyQt5"] = None

# [Environment] Force Qt6
os.environ["QT_API"] = "pyqt6"

import signal
import asyncio
import qasync
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from .danmaku_widget import DanmakuWidget

async def main(app, room_id: int):
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    # Create Danmaku Widget directly as top-level
    danmaku_widget = DanmakuWidget(room_id)
    
    # Try to activate Layer Shell BEFORE showing
    # This ensures the window is mapped as a Layer Shell surface from the start
    danmaku_widget.activate_layer_shell()

    # Show window
    danmaku_widget.show()

    await app_close_event.wait()

async def cancel_pending_tasks(loop, exclude=None):
    exclude = set(exclude or ())
    current_task = asyncio.current_task(loop=loop)
    if current_task is not None:
        exclude.add(current_task)
    pending = [task for task in asyncio.all_tasks(loop) if task not in exclude and not task.done()]
    if not pending:
        return

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)

def entry_point():
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
    _main_task = loop.create_task(main(app, args.room_id))
    
    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(cancel_pending_tasks(loop))
        loop.close()

if __name__ == "__main__":
    entry_point()
