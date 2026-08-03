import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from bilihud.app.mirror_coordinator import MirrorCoordinatorState
from bilihud.mirror_settings_dialog import MirrorSettingsDialog


def test_mirror_settings_dialog_exposes_url_and_persistent_enable_controls():
    app = QApplication.instance() or QApplication([])

    parent = QWidget()
    dialog = MirrorSettingsDialog(parent)
    state = MirrorCoordinatorState(
        enabled=True,
        running=True,
        port=8765,
        url="http://127.0.0.1:8765/bilihud-mirror",
    )
    dialog.refresh(state)

    assert dialog.enabled_checkbox.text() == "启用 BiliHUD Mirror"
    buttons = dialog.findChildren(QPushButton)
    assert [button.text() for button in buttons] == ["复制 URL", "关闭"]
    assert dialog.url_input.isReadOnly()
    assert dialog.url_input.text() == state.url
    assert dialog.status_label.text() == "已启动"

    dialog.set_mirror_state(False, "未启动", "http://127.0.0.1:9000/bilihud-mirror")

    assert dialog.enabled_checkbox.isChecked() is False
    assert dialog.status_label.text() == "未启动"
    assert dialog.url_input.text() == "http://127.0.0.1:9000/bilihud-mirror"

    dialog.close()
    parent.close()
    app.processEvents()
