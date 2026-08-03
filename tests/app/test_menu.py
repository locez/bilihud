from bilihud.app.menu import MenuCommand, TrayMenuState, tray_action_states


def test_tray_menu_state_maps_compact_action_order() -> None:
    state = TrayMenuState(
        visible=True,
        gaming_mode=False,
        gaming_mode_available=False,
        gaming_mode_reason="当前桌面不支持穿透",
    )

    actions = tray_action_states(state)
    command_actions = {action.command: action for action in actions}

    assert [action.command for action in actions] == [
        MenuCommand.SEND_DANMAKU,
        MenuCommand.OPEN_LIVE_SETTINGS,
        MenuCommand.TOGGLE_VISIBILITY,
        MenuCommand.TOGGLE_GAMING_MODE,
        MenuCommand.OPEN_LOGIN,
        MenuCommand.OPEN_SETTINGS,
        MenuCommand.QUIT,
    ]
    assert [action.label for action in actions] == [
        "发送弹幕",
        "开播设置",
        "隐藏窗口",
        "锁定穿透",
        "扫码登录",
        "设置",
        "退出程序",
    ]
    assert command_actions[MenuCommand.TOGGLE_GAMING_MODE].enabled is False
    assert command_actions[MenuCommand.TOGGLE_GAMING_MODE].disabled_reason == "当前桌面不支持穿透"


def test_tray_menu_state_keeps_gaming_mode_checkable_and_in_sync() -> None:
    state = TrayMenuState(
        visible=False,
        gaming_mode=True,
        gaming_mode_available=True,
    )

    gaming_action = next(
        action for action in tray_action_states(state) if action.command is MenuCommand.TOGGLE_GAMING_MODE
    )

    assert gaming_action.label == "解除穿透"
    assert gaming_action.checkable is True
    assert gaming_action.checked is True
