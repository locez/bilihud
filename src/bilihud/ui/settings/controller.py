"""Qt settings-window bridge for application-owned configuration and workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from PyQt6.QtWidgets import QWidget

from bilihud.app.account_controller import AccountState
from bilihud.app.application_controller import ApplicationController
from bilihud.app.lifecycle import TaskScope
from bilihud.ui.settings.dialog import SettingsDialog
from bilihud.ui.settings.models import SettingsPage, SettingsSaveRequest
from bilihud.ui.settings.pages.live.workflow import LiveStartedHandler

UiCommandResult = asyncio.Task[None] | None


class SettingsController:
    """Own the settings dialog and translate its signals into application commands."""

    def __init__(
        self,
        parent: QWidget,
        *,
        application: ApplicationController,
        task_scope: TaskScope,
        on_mirror_toggle: Callable[[bool], None],
        on_live_status: Callable[[bool], None],
        on_login: Callable[[], UiCommandResult],
        on_logout: Callable[[], UiCommandResult],
        on_simulation: Callable[[], None],
        on_opacity_changed: Callable[[int], None],
        on_live_started: LiveStartedHandler | None = None,
    ) -> None:
        """Create a lazy settings owner with explicit application and UI callbacks."""
        self._parent = parent
        self._application = application
        self._task_scope = task_scope
        self._on_mirror_toggle = on_mirror_toggle
        self._on_opacity_changed = on_opacity_changed
        self._dialog: SettingsDialog | None = None
        self._live_status_callback = on_live_status
        self._login_callback = on_login
        self._logout_callback = on_logout
        self._simulation_callback = on_simulation
        self._live_started_callback = on_live_started

    @property
    def dialog(self) -> SettingsDialog | None:
        """Return the lazily created settings dialog, if it is open or retained."""
        return self._dialog

    def open(self, page: SettingsPage) -> None:
        """Open the unified settings surface on one requested page."""
        dialog = self._ensure_dialog()
        dialog.set_config(self._application.config)
        dialog.set_mirror_state(self._application.mirror_coordinator.state)
        dialog.set_account_state(
            self._application.account_controller.state.status,
            self._application.account_controller.state.profile,
        )
        dialog.select_page(page)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def set_account_state(self, state: AccountState) -> None:
        """Render one application-owned account snapshot when the dialog exists."""
        if self._dialog is not None:
            self._dialog.set_account_state(state.status, state.profile)

    def set_mirror_state(self) -> None:
        """Refresh the Mirror page from the application coordinator snapshot."""
        if self._dialog is not None:
            self._dialog.set_mirror_state(self._application.mirror_coordinator.state)

    def set_mirror_status(self, status: str) -> None:
        """Render a short Mirror status in the retained settings surface."""
        if self._dialog is not None:
            self._dialog.set_mirror_status(status)

    def refresh_live_state(self) -> None:
        """Refresh live controls after an account session transition."""
        if self._dialog is not None:
            self._dialog.refresh_live_state()

    async def shutdown(self) -> None:
        """Close the retained dialog and cancel its embedded presentation tasks."""
        dialog = self._dialog
        if dialog is None:
            return
        await dialog.shutdown()
        dialog.close()

    def _ensure_dialog(self) -> SettingsDialog:
        """Create the dialog once and connect all presentation commands."""
        if self._dialog is not None:
            return self._dialog
        dialog = SettingsDialog(
            self._parent,
            self._application.config,
            services=self._application.services,
            task_scope=self._task_scope,
            on_live_started=self._live_started_callback,
        )
        dialog.settings_requested.connect(self._save_settings)
        dialog.mirror_enabled_requested.connect(self._on_mirror_toggle)
        dialog.live_status_changed.connect(self._live_status_callback)
        dialog.login_requested.connect(self._login_callback)
        dialog.logout_requested.connect(self._logout_callback)
        dialog.simulation_requested.connect(self._simulation_callback)
        self._dialog = dialog
        return dialog

    def _save_settings(self, request: SettingsSaveRequest) -> None:
        """Persist one validated settings request through the application owner."""
        dialog = self._dialog
        if dialog is None:
            return
        result = self._application.save_config(request.config)
        if not result.succeeded:
            dialog.report_save_result(request, False, "设置保存失败")
            return
        self._on_opacity_changed(result.config.window_opacity)
        dialog.report_save_result(request, True)


__all__ = ("SettingsController",)
