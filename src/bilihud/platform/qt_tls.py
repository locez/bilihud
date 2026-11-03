"""Select the platform TLS implementation before Qt creates network resources."""

from __future__ import annotations

import sys

from PyQt6.QtNetwork import QSslSocket

from .system import PlatformKind, platform_kind


def configure_qt_tls(platform_name: str | None = None) -> None:
    """Use native Windows TLS, or leave the other platforms' defaults unchanged.

    Call after creating the Qt application and before using any Qt SSL classes
    or network managers. Schannel keeps Qt HTTPS independent of the OpenSSL
    DLLs bundled alongside Python while retaining Windows certificate checks.
    A missing/unselectable backend is a startup error, never an OpenSSL fallback.
    """
    selected_platform = sys.platform if platform_name is None else platform_name
    if platform_kind(selected_platform) is not PlatformKind.WINDOWS:
        return

    # Querying the default backend first can initialize the OpenSSL path that
    # crashes in the Windows release (#67). Select Schannel before any TLS use.
    if not QSslSocket.setActiveBackend("schannel"):
        raise RuntimeError(
            "Qt Schannel TLS backend could not be selected. "
            "The Windows package must include qschannelbackend.dll and select it before any Qt TLS use."
        )


__all__ = ("configure_qt_tls",)
