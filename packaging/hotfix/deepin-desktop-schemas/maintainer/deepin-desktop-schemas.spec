Name:           deepin-desktop-schemas
Version:        6.0.13
Release:        1%{?dist}
Summary:        GSettings schemas for the Deepin desktop environment
License:        CC-BY-4.0 AND CC0-1.0 AND GPL-3.0-only AND GPL-3.0-or-later
URL:            https://github.com/linuxdeepin/deepin-desktop-schemas
Source0:        %{url}/archive/%{version}/deepin-desktop-schemas-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  golang
BuildRequires:  make
BuildRequires:  glib2

Requires:       dconf
Requires:       deepin-gtk-theme
Requires:       deepin-icon-theme
Requires:       deepin-sound-theme

%description
deepin-desktop-schemas contains the GSettings schemas and default overrides
shared by the Deepin desktop components.

%prep
%autosetup -n deepin-desktop-schemas-%{version} -p1
sed -i 's|python|python3|' Makefile tools/overrides.py
sed -i "s#/usr/share/backgrounds/default_background.jpg#/usr/share/backgrounds/deepin/desktop.jpg#" \
  overrides/common/com.deepin.wrap.gnome.desktop.override \
  schemas/com.deepin.dde.appearance.gschema.xml

%build
export GO111MODULE=on
export GOFLAGS="-mod=mod"
export GOPATH=%{_builddir}/gopath
%make_build

%install
%make_install

%post
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :

%postun
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :

%files
%license LICENSE
%doc CHANGELOG.md README.md
%{_datadir}/glib-2.0/schemas/
%{_datadir}/deepin-desktop-schemas/
%{_datadir}/deepin-appstore/
%{_datadir}/deepin-app-store/

%changelog
* Sat Nov 21 2026 mozixun <mozixun@fedoraproject.org> - 6.0.13-1
- Initial Fedora package.
