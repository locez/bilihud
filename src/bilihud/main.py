# -*- coding: utf-8 -*-
import sys
import os
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
    
    try:
        loop.run_until_complete(main(app, args.room_id))
    finally:
        loop.close()

if __name__ == "__main__":
    entry_point()
