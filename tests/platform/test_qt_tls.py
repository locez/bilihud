"""Cover platform TLS selection and verified image requests across both clients."""

from __future__ import annotations

import asyncio
import os
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import web

from bilihud.platform import qt_tls


@pytest.mark.parametrize("platform_name", ("win32", "cygwin", "msys"))
def test_windows_requires_native_tls(platform_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows must select Schannel even when OpenSSL is also installed."""
    selected: list[str] = []

    def select(backend: str) -> bool:
        selected.append(backend)
        return backend == "schannel"

    monkeypatch.setattr(qt_tls.QSslSocket, "setActiveBackend", select)
    qt_tls.configure_qt_tls(platform_name)

    assert selected == ["schannel"]


def test_missing_native_tls_fails_without_falling_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken Windows package must not silently reenter the crashing TLS path."""
    monkeypatch.setattr(qt_tls.QSslSocket, "setActiveBackend", lambda _backend: False)

    with pytest.raises(RuntimeError, match="Schannel TLS backend could not be selected"):
        qt_tls.configure_qt_tls("win32")


@pytest.mark.parametrize("platform_name", ("linux", "darwin", "freebsd"))
def test_other_platforms_keep_their_tls_backend(platform_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native Windows TLS must not affect the Linux or macOS network configuration."""
    def unexpected_selection(_backend: str) -> bool:
        pytest.fail("TLS selection must remain unchanged on this platform")

    monkeypatch.setattr(qt_tls.QSslSocket, "setActiveBackend", unexpected_selection)
    qt_tls.configure_qt_tls(platform_name)


def test_python_and_qt_https_keep_certificate_validation(tmp_path: Path) -> None:
    """Login-style HTTPS followed by repeated image downloads must work with peer checks."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required to generate a temporary local HTTPS certificate")
    certificate = tmp_path / "localhost.pem"
    private_key = tmp_path / "localhost.key"
    subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    image = Path(__file__).parents[2] / "src" / "bilihud" / "assets" / "icon.png"
    image_bytes = image.read_bytes()

    async def serve_image(_request: web.Request) -> web.Response:
        return web.Response(body=image_bytes, content_type="image/png")

    async def run_probe() -> None:
        application = web.Application()
        application.router.add_get("/avatar.png", serve_image)
        runner = web.AppRunner(application)
        await runner.setup()
        process: asyncio.subprocess.Process | None = None
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
            await site.start()
            url = f"https://127.0.0.1:{site.port}/avatar.png"
            probe = Path(__file__).with_name("qt_tls_probe.py")
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(probe), url, str(certificate),
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, (stdout + stderr).decode(errors="replace")
        finally:
            try:
                if process is not None and process.returncode is None:
                    process.kill()
                    await asyncio.wait_for(process.communicate(), timeout=5)
            finally:
                await runner.cleanup()

    asyncio.run(run_probe())
