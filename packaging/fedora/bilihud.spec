
Name:           bilihud
Version:        0.3.0
Release:        1%{?dist}
Summary:        Bilibili Danmaku HUD for Linux

License:        MIT
URL:            https://github.com/locez/bilihud
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-hatchling
BuildRequires:  python3-hatch-build-scripts
BuildRequires:  gcc-c++
BuildRequires:  qt6-qtbase-devel
BuildRequires:  layer-shell-qt-devel
BuildRequires:  wayland-devel

Requires:       python3
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

%files -f %{pyproject_files}
%{_bindir}/bilihud
