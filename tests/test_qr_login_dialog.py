import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QToolButton

from bilihud.config.store import ThemeMode
from bilihud.ui.appearance import resolve_appearance
from bilihud.ui.auth.qr_login import QRLoginDialog, _qr_status_presentation


def test_qr_login_protocol_statuses_keep_unscanned_and_scanned_distinct() -> None:
    assert _qr_status_presentation(86101) == ("请使用哔哩哔哩手机客户端扫码", "info")
    assert _qr_status_presentation(86090) == ("已扫码，请在手机上确认登录", "warning")


def test_qr_login_dialog_uses_unified_settings_visual_language() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None

    class FakeAuthService:
        pass

    dialog = QRLoginDialog(
        auth_service=FakeAuthService(),
        appearance=resolve_appearance(ThemeMode.LIGHT),
    )

    assert dialog.windowTitle() == "扫码登录"
    assert dialog.qr_label.objectName() == "qr_code"
    assert dialog.qr_label.width() == 240
    assert dialog.refresh_btn.text() == "刷新二维码"
    assert dialog.findChild(QToolButton, "window_close") is None
    assert "QFrame#qr_card" in dialog.styleSheet()

    dialog.close()
    asyncio.run(dialog.shutdown())
