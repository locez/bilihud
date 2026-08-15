"""Compose the standalone Mirror browser page from focused templates."""

from __future__ import annotations

import json

from .page_script import render_page_script
from .page_shell import render_page_shell
from .state import MIRROR_EVENTS_ROUTE, MirrorDisplaySettings, mirror_settings_payload


def mirror_html(
    events_route: str = MIRROR_EVENTS_ROUTE,
    settings: MirrorDisplaySettings | None = None,
) -> str:
    """Render the browser page that subscribes to the Mirror event stream."""
    display_settings = settings if settings is not None else MirrorDisplaySettings()
    settings_json = json.dumps(
        mirror_settings_payload(display_settings),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return render_page_shell() + render_page_script(events_route, settings_json)


__all__ = ("mirror_html",)
