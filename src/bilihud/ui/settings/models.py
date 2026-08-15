"""Typed navigation and save contracts shared by the settings surface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bilihud.config.store import AppConfig


class SettingsPage(StrEnum):
    """Identify a page in the unified settings window."""

    GENERAL = "general"
    PANEL = "panel"
    LIVE = "live"
    MIRROR = "mirror"
    ACCOUNT = "account"
    ABOUT = "about"
    DEVELOPER = "developer"


@dataclass(frozen=True, slots=True)
class SettingsSaveRequest:
    """Carry form values from the settings view to the owning application shell."""

    config: AppConfig
    close_after_save: bool


PAGE_DEFINITIONS: tuple[tuple[SettingsPage, str, str], ...] = (
    (SettingsPage.GENERAL, "通用", "通用设置"),
    (SettingsPage.PANEL, "面板", "面板设置"),
    (SettingsPage.LIVE, "直播", "开播设置"),
    (SettingsPage.MIRROR, "显示", "显示与特效"),
    (SettingsPage.ACCOUNT, "账号", "账号设置"),
    (SettingsPage.ABOUT, "关于", "关于 BiliHUD"),
    (SettingsPage.DEVELOPER, "开发者", "开发者功能"),
)


__all__ = ("PAGE_DEFINITIONS", "SettingsPage", "SettingsSaveRequest")
