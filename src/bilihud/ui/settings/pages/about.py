"""About page for the unified settings window."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from bilihud.app_metadata import GITHUB_URL, LICENSE_NAME, application_version


class AboutSettingsPage(QWidget):
    """Present concise product, version, license, and source information."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the about page without network or file-system side effects."""
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        """Build one compact information card without repeating shell copy."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 8, 8)
        page_layout.setSpacing(14)

        card = QFrame(self)
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(14)

        summary = QLabel("B站弹幕 HUD 与直播控制工具", card)
        summary.setObjectName("about_summary")
        card_layout.addWidget(summary)

        details = QFormLayout()
        details.setHorizontalSpacing(28)
        details.setVerticalSpacing(10)
        self.version_label = QLabel(f"v{application_version()}", card)
        self.version_label.setObjectName("about_value")
        self.license_label = QLabel(LICENSE_NAME, card)
        self.license_label.setObjectName("about_value")
        details.addRow("版本", self.version_label)
        details.addRow("许可证", self.license_label)
        card_layout.addLayout(details)

        project_row = QHBoxLayout()
        project_row.setSpacing(12)
        project_label = QLabel("项目主页", card)
        project_label.setObjectName("about_summary")
        project_row.addWidget(project_label)
        self.github_button = QPushButton("GitHub", card)
        self.github_button.setProperty("link", True)
        self.github_button.setToolTip(GITHUB_URL)
        self.github_button.clicked.connect(self._open_github)
        project_row.addWidget(self.github_button)
        project_row.addStretch(1)
        card_layout.addLayout(project_row)

        page_layout.addWidget(card)
        page_layout.addStretch(1)

    def _open_github(self) -> None:
        """Open the canonical project page in the user's default browser."""
        QDesktopServices.openUrl(QUrl(GITHUB_URL))


__all__ = ("AboutSettingsPage",)
