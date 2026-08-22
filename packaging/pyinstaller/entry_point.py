"""PyInstaller entry point for the installed BiliHUD application."""

import sys

from bilihud.platform.certificates import configure_macos_ca_bundle


def main() -> None:
    """Configure packaged platform resources before importing the application."""
    ca_bundle_path: str | None = None
    if sys.platform == "darwin":
        import certifi

        ca_bundle_path = certifi.where()
    configure_macos_ca_bundle(ca_bundle_path=ca_bundle_path)
    from bilihud.main import entry_point

    entry_point()


if __name__ == "__main__":
    main()
