from pathlib import Path

import pytest

from bilihud.platform.certificates import configure_macos_ca_bundle


def test_macos_ca_bundle_is_added_when_no_override_exists(tmp_path: Path) -> None:
    ca_bundle = tmp_path / "cacert.pem"
    ca_bundle.write_text("test CA bundle", encoding="ascii")
    environment: dict[str, str] = {}

    configure_macos_ca_bundle(
        "darwin",
        environment=environment,
        ca_bundle_path=str(ca_bundle),
    )

    assert environment == {"SSL_CERT_FILE": str(ca_bundle)}


def test_existing_ca_override_is_preserved(tmp_path: Path) -> None:
    ca_bundle = tmp_path / "cacert.pem"
    ca_bundle.write_text("test CA bundle", encoding="ascii")
    environment = {"SSL_CERT_FILE": "/custom/ca.pem"}

    configure_macos_ca_bundle(
        "darwin",
        environment=environment,
        ca_bundle_path=str(ca_bundle),
    )

    assert environment == {"SSL_CERT_FILE": "/custom/ca.pem"}


@pytest.mark.parametrize("platform_name", ("linux", "win32"))
def test_non_macos_platforms_keep_their_environment(platform_name: str, tmp_path: Path) -> None:
    ca_bundle = tmp_path / "cacert.pem"
    ca_bundle.write_text("test CA bundle", encoding="ascii")
    environment: dict[str, str] = {}

    configure_macos_ca_bundle(
        platform_name,
        environment=environment,
        ca_bundle_path=str(ca_bundle),
    )

    assert environment == {}


def test_missing_macos_ca_bundle_fails_explicitly(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="macOS CA bundle is unavailable"):
        configure_macos_ca_bundle(
            "darwin",
            environment={},
            ca_bundle_path=str(tmp_path / "missing.pem"),
        )
