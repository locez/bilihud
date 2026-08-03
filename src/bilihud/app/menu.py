"""Typed command and visible-state contracts for the application tray menu."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MenuCommand(StrEnum):
    """Identify a user command that can be requested by a menu surface."""

    SEND_DANMAKU = "send_danmaku"
    TOGGLE_VISIBILITY = "toggle_visibility"
    TOGGLE_GAMING_MODE = "toggle_gaming_mode"
    OPEN_LOGIN = "open_login"
    OPEN_LIVE_SETTINGS = "open_live_settings"
    OPEN_SETTINGS = "open_settings"
    QUIT = "quit"


class AccountStatus(StrEnum):
    """Describe the latest account knowledge without forcing a credential lookup."""

    UNKNOWN = "unknown"
    LOGGED_IN = "logged_in"
    LOGIN_EXPIRED = "login_expired"
    LOGGED_OUT = "logged_out"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MenuActionState:
    """Describe one rendered tray action without depending on Qt."""

    command: MenuCommand
    label: str
    enabled: bool = True
    checkable: bool = False
    checked: bool = False
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        if self.enabled and self.disabled_reason is not None:
            raise ValueError("可用菜单项不能包含禁用原因")
        if not self.checkable and self.checked:
            raise ValueError("不可勾选的菜单项不能处于选中状态")


@dataclass(frozen=True, slots=True)
class TrayMenuState:
    """Immutable application snapshot rendered by the tray menu."""

    visible: bool
    gaming_mode: bool
    gaming_mode_available: bool
    gaming_mode_reason: str | None = None


def tray_action_states(state: TrayMenuState) -> tuple[MenuActionState, ...]:
    """Map one application snapshot to the complete set of tray action states."""
    gaming_reason = state.gaming_mode_reason
    if state.gaming_mode_available:
        gaming_reason = None
    elif gaming_reason is None:
        gaming_reason = "当前平台不支持游戏模式"

    return (
        MenuActionState(MenuCommand.SEND_DANMAKU, "发送弹幕"),
        MenuActionState(
            MenuCommand.OPEN_LIVE_SETTINGS,
            "开播设置",
        ),
        MenuActionState(
            MenuCommand.TOGGLE_VISIBILITY,
            "隐藏窗口" if state.visible else "显示窗口",
        ),
        MenuActionState(
            MenuCommand.TOGGLE_GAMING_MODE,
            "解除穿透" if state.gaming_mode else "锁定穿透",
            enabled=state.gaming_mode_available,
            checkable=True,
            checked=state.gaming_mode,
            disabled_reason=gaming_reason,
        ),
        MenuActionState(MenuCommand.OPEN_LOGIN, "扫码登录"),
        MenuActionState(MenuCommand.OPEN_SETTINGS, "设置"),
        MenuActionState(MenuCommand.QUIT, "退出程序"),
    )


__all__ = (
    "AccountStatus",
    "MenuActionState",
    "MenuCommand",
    "TrayMenuState",
    "tray_action_states",
)
