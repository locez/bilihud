"""Platform-specific certificate trust configuration for packaged runtimes."""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from .system import PlatformKind, platform_kind


def configure_macos_ca_bundle(
    platform_name: str | None = None,
    *,
    environment: MutableMapping[str, str] | None = None,
    ca_bundle_path: str | None = None,
) -> None:
    """Provide a bundled CA file when macOS OpenSSL has no usable default.

    The existing ``SSL_CERT_FILE`` setting remains authoritative. On macOS,
    an unset setting is populated from the supplied bundled CA file so aiohttp
    can create verified HTTPS connections before application imports.
    """
    selected_platform = sys.platform if platform_name is None else platform_name
    selected_environment = os.environ if environment is None else environment
    if platform_kind(selected_platform) is not PlatformKind.MACOS:
        return
    if "SSL_CERT_FILE" in selected_environment:
        return

    if ca_bundle_path is None:
        raise RuntimeError("macOS CA bundle path was not supplied")
    bundle = Path(ca_bundle_path)
    if not bundle.is_file():
        raise RuntimeError(f"macOS CA bundle is unavailable: {bundle}")
    selected_environment["SSL_CERT_FILE"] = str(bundle)


__all__ = ("configure_macos_ca_bundle",)
