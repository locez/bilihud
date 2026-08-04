import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from bilihud.app.mirror_coordinator import MirrorCoordinatorState
from bilihud.ui.settings.pages.mirror import MirrorSettingsPage


def test_mirror_settings_page_exposes_url_and_persistent_enable_controls():
    app = QApplication.instance() or QApplication([])

    parent = QWidget()
    page = MirrorSettingsPage(parent)
    state = MirrorCoordinatorState(
        enabled=True,
        running=True,
        port=8765,
        url="http://127.0.0.1:8765/bilihud-mirror",
    )
    page.set_state(state)

    assert page.enabled_checkbox.text() == "启用 BiliHUD Mirror"
    buttons = page.findChildren(QPushButton)
    assert [button.text() for button in buttons] == ["复制 URL"]
    assert page.url_input.isReadOnly()
    assert page.url_input.text() == state.url
    assert page.status_label.text() == "已启动"

    page.set_state(
        MirrorCoordinatorState(
            enabled=False,
            running=False,
            port=9000,
            url="http://127.0.0.1:9000/bilihud-mirror",
        )
    )

    assert page.enabled_checkbox.isChecked() is False
    assert page.status_label.text() == "未启动"
    assert page.url_input.text() == "http://127.0.0.1:9000/bilihud-mirror"

    page.close()
    parent.close()
    app.processEvents()
