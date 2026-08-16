import asyncio
import os
from collections.abc import Mapping
from io import BytesIO

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QToolButton

from bilihud.auth.service import AuthCookies
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
        async def get_qrcode(self) -> tuple[str | None, str | None]:
            raise AssertionError("QR login is not started in this test")

        def generate_qr_image(self, url: str) -> BytesIO | None:
            del url
            raise AssertionError("QR login is not started in this test")

        async def poll_status(self, qrcode_key: str) -> tuple[int, str, AuthCookies | None]:
            del qrcode_key
            raise AssertionError("QR login is not started in this test")

        def save_cookies(self, cookies: Mapping[str, str]) -> bool:
            del cookies
            raise AssertionError("QR login is not started in this test")

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
