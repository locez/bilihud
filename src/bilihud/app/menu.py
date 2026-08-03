"""Typed command and visible-state contracts for the application tray menu."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .hud import HudConnectionStatus


class MenuCommand(StrEnum):
    """Identify a user command that can be requested by a menu surface."""

    SEND_DANMAKU = "send_danmaku"
    TOGGLE_VISIBILITY = "toggle_visibility"
    TOGGLE_GAMING_MODE = "toggle_gaming_mode"
    OPEN_LOGIN = "open_login"
    OPEN_LIVE_SETTINGS = "open_live_settings"
    OPEN_MIRROR_SETTINGS = "open_mirror_settings"
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

    command: MenuCommand | None
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
    hud_connection: HudConnectionStatus
    gaming_mode: bool
    gaming_mode_available: bool
    gaming_mode_reason: str | None = None
    mirror_status: str = "未启动"
    account_status: AccountStatus = AccountStatus.UNKNOWN


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
            None,
            _hud_status_label(state.hud_connection),
            enabled=False,
        ),
        MenuActionState(
            None,
            _account_status_label(state.account_status),
            enabled=False,
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
        MenuActionState(
            None,
            f"Mirror：{state.mirror_status}",
            enabled=False,
        ),
        MenuActionState(MenuCommand.OPEN_LOGIN, "扫码登录"),
        MenuActionState(MenuCommand.OPEN_LIVE_SETTINGS, "开播设置"),
        MenuActionState(MenuCommand.OPEN_MIRROR_SETTINGS, "Mirror 设置"),
        MenuActionState(MenuCommand.OPEN_SETTINGS, "设置"),
        MenuActionState(MenuCommand.QUIT, "退出程序"),
    )


def _hud_status_label(connection: HudConnectionStatus) -> str:
    labels = {
        HudConnectionStatus.DISCONNECTED: "连接：未连接",
        HudConnectionStatus.CONNECTING: "连接：连接中",
        HudConnectionStatus.CONNECTED: "连接：已连接",
        HudConnectionStatus.DISCONNECTING: "连接：断开中",
    }
    return labels[connection]


def _account_status_label(status: AccountStatus) -> str:
    labels = {
        AccountStatus.UNKNOWN: "账号：检查中",
        AccountStatus.LOGGED_IN: "账号：已登录",
        AccountStatus.LOGIN_EXPIRED: "账号：登录失效",
        AccountStatus.LOGGED_OUT: "账号：未登录",
        AccountStatus.UNAVAILABLE: "账号：暂时无法获取",
    }
    return labels[status]


__all__ = (
    "AccountStatus",
    "MenuActionState",
    "MenuCommand",
    "TrayMenuState",
    "tray_action_states",
)
