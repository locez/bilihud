"""Stable application identity and distribution metadata for presentation surfaces."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

GITHUB_URL = "https://github.com/locez/bilihud"
BILIBILI_LIVE_RECORD_URL = "https://link.bilibili.com/p/center/index#/my-room/live-record"
LICENSE_NAME = "MIT License"


def application_version() -> str:
    """Return the installed package version, with a clear source-tree fallback."""
    try:
        return version("bilihud")
    except PackageNotFoundError:
        return "开发版本"


__all__ = ("BILIBILI_LIVE_RECORD_URL", "GITHUB_URL", "LICENSE_NAME", "application_version")
