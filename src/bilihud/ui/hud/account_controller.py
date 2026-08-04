"""Qt account surfaces for QR login and application-owned logout results."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

from bilihud.app.account_controller import AccountLogoutIssue, AccountLogoutResult
from bilihud.app.application_controller import ApplicationController
from bilihud.app.lifecycle import TaskScope
from bilihud.danmaku.messages import SystemMessageLevel
from bilihud.ui.appearance import resolve_appearance
from bilihud.ui.auth.qr_login import QRLoginDialog
from bilihud.ui.settings.controller import SettingsController


class AccountView(Protocol):
    """Presentation callbacks required by the account surface controller."""

    application: ApplicationController
    settings_controller: SettingsController
    tray_icon: QSystemTrayIcon

    def add_system_message(
        self,
        message: str,
        level: SystemMessageLevel = SystemMessageLevel.INFO,
    ) -> None:
        """Render a local account notice in the HUD message stream."""
        ...


AccountTaskFactory = Callable[[Coroutine[Any, Any, None], str], asyncio.Task[None]]


class AccountSurfaceController:
    """Own QR dialog cleanup and translate logout results into presentation feedback."""

    def __init__(
        self,
        view: AccountView,
        *,
        parent: QWidget,
        task_scope: TaskScope,
        task_factory: AccountTaskFactory,
        is_shutting_down: Callable[[], bool],
        on_login_success: Callable[[], None],
    ) -> None:
        """Create the account surface bridge with explicit task and event ownership."""
        self._view = view
        self._parent = parent
        self._task_scope = task_scope
        self._task_factory = task_factory
        self._is_shutting_down = is_shutting_down
        self._on_login_success = on_login_success
        self._dialog: QRLoginDialog | None = None

    @property
    def dialog(self) -> QRLoginDialog | None:
        """Return the active QR dialog, if one exists."""
        return self._dialog

    def open_qr_login(self) -> None:
        """Open or focus the non-blocking QR login dialog."""
        if self._is_shutting_down():
            return
        dialog = self._dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = QRLoginDialog(
            self._parent,
            auth_service=self._view.application.auth_service,
            task_scope=self._task_scope.child("qr-login"),
            appearance=resolve_appearance(self._view.application.config.theme),
        )
        dialog.login_success.connect(self._on_login_success)
        dialog.finished.connect(lambda _result: self._finish_dialog(dialog))
        self._dialog = dialog
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    async def shutdown(self) -> None:
        """Cancel QR polling and release the dialog during application shutdown."""
        dialog = self._dialog
        if dialog is None:
            return
        await dialog.shutdown()
        dialog.close()
        self._dialog = None

    async def logout(self) -> None:
        """Run application logout and render its typed cleanup result."""
        result = await self._view.application.logout()
        if not result.session_cleared:
            self._view.add_system_message(
                "登出失败，B站登录会话仍可能保存在 keyring 中，请重试。",
                SystemMessageLevel.ERROR,
            )
            return

        self._view.settings_controller.refresh_live_state()
        if result.issues:
            message = "B站登录会话已清除，但部分连接关闭失败，请重启应用后确认。"
            icon = QSystemTrayIcon.MessageIcon.Warning
        else:
            message = "B站登录会话已从 keyring 清除。"
            icon = QSystemTrayIcon.MessageIcon.Information
        self._view.tray_icon.showMessage("已登出", message, icon, 2000)
        if result.issues:
            self._view.add_system_message(
                f"账号已登出，但清理连接时出现问题：{self._issue_text(result)}",
                SystemMessageLevel.ERROR,
            )
        else:
            self._view.add_system_message("已登出 B站账号。")

    def _finish_dialog(self, dialog: QRLoginDialog) -> None:
        """Schedule cancellation before releasing a completed QR dialog."""
        if self._is_shutting_down():
            return
        self._task_factory(self._close_dialog(dialog), "close-qr-login")

    async def _close_dialog(self, dialog: QRLoginDialog) -> None:
        """Await QR task cleanup before deleting the dialog object."""
        await dialog.shutdown()
        if self._dialog is dialog:
            self._dialog = None
        dialog.deleteLater()

    @staticmethod
    def _issue_text(result: AccountLogoutResult) -> str:
        """Translate application cleanup issue codes into localized feedback."""
        labels = {
            AccountLogoutIssue.HUD_DISCONNECT: "弹幕连接关闭失败",
            AccountLogoutIssue.LIVE_SESSION_CLOSE: "直播服务关闭失败",
            AccountLogoutIssue.SESSION_CLEAR: "登录会话清除失败",
        }
        return "；".join(labels[issue] for issue in result.issues)


__all__ = ("AccountSurfaceController", "AccountView")
