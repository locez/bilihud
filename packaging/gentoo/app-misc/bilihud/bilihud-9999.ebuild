# Copyright 2025-2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DISTUTILS_USE_PEP517=scikit-build-core
PYTHON_COMPAT=( python3_{13..14} )

inherit distutils-r1 desktop

DESCRIPTION="B站弹幕阅读器 - 一个可以在游戏全屏时显示弹幕的Qt应用程序"
HOMEPAGE="https://github.com/locez/bilihud"

if [[ ${PV} == 9999 ]]; then
	inherit git-r3
	EGIT_REPO_URI="https://github.com/locez/bilihud.git"
	EGIT_SUBMODULES=( '*' )
else
	inherit pypi
	KEYWORDS="~amd64 ~x86"
fi

distutils_enable_tests pytest

LICENSE="MIT"
SLOT="0"

RDEPEND="
	dev-libs/wayland
	dev-qt/qtbase:6[gui,wayland]
	dev-qt/qtwayland:6
	kde-plasma/layer-shell-qt
	dev-python/pyqt6[${PYTHON_USEDEP}]
	dev-python/aiohttp[${PYTHON_USEDEP}]
	dev-python/qasync[${PYTHON_USEDEP}]
	app-arch/brotli[python,${PYTHON_USEDEP}]
	dev-python/pure-protobuf[${PYTHON_USEDEP}]
	dev-python/qrcode[${PYTHON_USEDEP}]
	dev-python/keyring[${PYTHON_USEDEP}]
	dev-python/pillow[${PYTHON_USEDEP}]
"

DEPEND="
	dev-libs/wayland
	dev-qt/qtbase:6[gui,wayland]
	kde-plasma/layer-shell-qt
"

BDEPEND="
	dev-build/cmake
	dev-build/ninja
	dev-python/scikit-build-core[${PYTHON_USEDEP}]
	virtual/pkgconfig
"

python_configure_all() {
	DISTUTILS_ARGS=(
		-DBILIHUD_INSTALL_DIR=bilihud
		-DBILIHUD_LAYER_SHELL=ON
	)
}

python_install_all() {
	distutils-r1_python_install_all
	domenu bilihud.desktop
	newicon src/bilihud/assets/icon.png bilihud.png
}
