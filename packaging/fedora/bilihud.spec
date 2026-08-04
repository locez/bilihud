%global debug_package %{nil}

Name:           bilihud
Version:        0.3.0
Release:        1%{?dist}
Summary:        Bilibili Danmaku HUD for Linux

License:        MIT
URL:            https://github.com/locez/bilihud
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel >= 3.13
BuildRequires:  python3-scikit-build-core
BuildRequires:  cmake
BuildRequires:  ninja-build
BuildRequires:  gcc-c++
BuildRequires:  pkgconf-pkg-config
BuildRequires:  qt6-qtbase-devel
BuildRequires:  qt6-qtbase-private-devel
BuildRequires:  layer-shell-qt-devel
BuildRequires:  wayland-devel

Requires:       python3 >= 3.13
Requires:       python3-pyqt6
Requires:       layer-shell-qt

%description
A desktop widget that displays Bilibili live danmaku (comments) on your screen,
designed for Linux with Wayland support via Layer Shell.

%prep
%autosetup

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files bilihud
install -p -D -m 644 bilihud.desktop %{buildroot}%{_datadir}/applications/bilihud.desktop
install -p -D -m 644 src/bilihud/assets/icon.png %{buildroot}%{_datadir}/pixmaps/bilihud.png

%files -f %{pyproject_files}
%{_bindir}/bilihud
%{_datadir}/applications/bilihud.desktop
%{_datadir}/pixmaps/bilihud.png
