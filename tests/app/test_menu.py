from bilihud.app.hud import HudConnectionStatus
from bilihud.app.menu import AccountStatus, MenuCommand, TrayMenuState, tray_action_states


def test_tray_menu_state_maps_high_frequency_actions_and_statuses() -> None:
    state = TrayMenuState(
        visible=True,
        hud_connection=HudConnectionStatus.CONNECTED,
        account_status=AccountStatus.LOGGED_IN,
        gaming_mode=False,
        gaming_mode_available=False,
        gaming_mode_reason="当前桌面不支持穿透",
        mirror_status="已启动",
    )

    actions = tray_action_states(state)
    command_actions = {action.command: action for action in actions if action.command is not None}
    status_labels = [action.label for action in actions if action.command is None]

    assert command_actions[MenuCommand.SEND_DANMAKU].label == "发送弹幕"
    assert command_actions[MenuCommand.TOGGLE_VISIBILITY].label == "隐藏窗口"
    assert command_actions[MenuCommand.OPEN_LIVE_SETTINGS].label == "开播设置"
    assert command_actions[MenuCommand.OPEN_LOGIN].label == "扫码登录"
    assert command_actions[MenuCommand.OPEN_MIRROR_SETTINGS].label == "Mirror 设置"
    assert command_actions[MenuCommand.TOGGLE_GAMING_MODE].enabled is False
    assert command_actions[MenuCommand.TOGGLE_GAMING_MODE].disabled_reason == "当前桌面不支持穿透"
    assert status_labels == ["连接：已连接", "账号：已登录", "Mirror：已启动"]


def test_tray_menu_state_keeps_gaming_mode_checkable_and_in_sync() -> None:
    state = TrayMenuState(
        visible=False,
        hud_connection=HudConnectionStatus.DISCONNECTED,
        account_status=AccountStatus.UNKNOWN,
        gaming_mode=True,
        gaming_mode_available=True,
    )

    gaming_action = next(
        action for action in tray_action_states(state) if action.command is MenuCommand.TOGGLE_GAMING_MODE
    )

    assert gaming_action.label == "解除穿透"
    assert gaming_action.checkable is True
    assert gaming_action.checked is True


def test_tray_menu_state_exposes_logged_out_instead_of_pending_verification() -> None:
    state = TrayMenuState(
        visible=True,
        hud_connection=HudConnectionStatus.DISCONNECTED,
        account_status=AccountStatus.LOGGED_OUT,
        gaming_mode=False,
        gaming_mode_available=True,
    )

    account_label = next(
        action.label
        for action in tray_action_states(state)
        if action.command is None and action.label.startswith("账号")
    )

    assert account_label == "账号：未登录"
