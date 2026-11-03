"""Exercise application TLS startup in a fresh process with a local HTTPS peer."""

from __future__ import annotations

import asyncio
import ssl
import sys
from pathlib import Path

import aiohttp
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QSslCertificate,
    QSslConfiguration,
    QSslSocket,
)

from bilihud.main import create_qt_application


async def _qt_image_request(url: str, *, trust_certificate: Path | None) -> QNetworkReply.NetworkError:
    """Download an image with normal peer checks and own the reply until completion."""
    manager = QNetworkAccessManager()
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(5000)
    if trust_certificate is not None:
        configuration = request.sslConfiguration()
        certificates = QSslCertificate.fromPath(str(trust_certificate))
        assert len(certificates) == 1
        configuration.setCaCertificates(certificates)
        request.setSslConfiguration(configuration)
    reply = manager.get(request)
    assert reply is not None
    finished: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def complete() -> None:
        if not finished.done():
            finished.set_result(None)

    reply.finished.connect(complete)
    try:
        await asyncio.wait_for(finished, timeout=10)
        error = reply.error()
        if error == QNetworkReply.NetworkError.NoError:
            assert not QImage.fromData(reply.readAll()).isNull()
        return error
    finally:
        reply.finished.disconnect(complete)
        if not reply.isFinished():
            reply.abort()
        reply.deleteLater()
        manager.deleteLater()


async def _probe(url: str, certificate: Path) -> None:
    """Verify Python HTTPS, Qt image downloads, and rejection of an untrusted peer."""
    if sys.platform == "win32":
        assert QSslSocket.activeBackend() == "schannel"
    assert QSslConfiguration.defaultConfiguration().peerVerifyMode() == QSslSocket.PeerVerifyMode.AutoVerifyPeer

    # Exercise Python's OpenSSL before Qt, matching login followed by settings.
    context = ssl.create_default_context(cafile=str(certificate))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        async with session.get(url, ssl=context) as response:
            assert response.status == 200
            assert not QImage.fromData(await response.read()).isNull()

    # Reopening settings must still download the avatar without switching TLS stacks.
    for _ in range(2):
        assert await _qt_image_request(url, trust_certificate=certificate) == QNetworkReply.NetworkError.NoError
    assert (
        await _qt_image_request(url, trust_certificate=None)
        == QNetworkReply.NetworkError.SslHandshakeFailedError
    )
    if sys.platform == "win32":
        assert QSslSocket.activeBackend() == "schannel"


def main() -> None:
    """Create the real startup resources and run only the isolated network probe."""
    import qasync

    url, certificate = sys.argv[1:]
    app = create_qt_application([sys.argv[0]])
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_probe(url, Path(certificate)))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    main()
