Name:           deepin-desktop-schemas
Version:        6.0.13
Release:        1.1.remix1%{?dist}
Summary:        GSettings schemas for the Deepin desktop environment
License:        CC-BY-4.0 AND CC0-1.0 AND GPL-3.0-only AND GPL-3.0-or-later
URL:            https://github.com/linuxdeepin/deepin-desktop-schemas
Source0:        %{url}/archive/%{version}/deepin-desktop-schemas-%{version}.tar.gz
Patch0:         0001-fix-duplicate-mediakey-metadata.patch
BuildArch:      noarch

BuildRequires:  golang
BuildRequires:  make
BuildRequires:  glib2

Requires:       dconf
Requires:       glib2
Requires:       desktop-backgrounds-basic
Requires:       deepin-gtk-theme
Requires:       deepin-icon-theme
Requires:       deepin-sound-theme

%description
deepin-desktop-schemas contains the GSettings schemas and default overrides
shared by the Deepin desktop components.

%prep
%autosetup -n deepin-desktop-schemas-%{version} -p1
sed -i 's|python|python3|' Makefile tools/overrides.py
sed -i "s#/usr/share/backgrounds/default_background.jpg#/usr/share/backgrounds/images/earth_from_space.jpg#" \
  overrides/common/com.deepin.wrap.gnome.desktop.override \
  schemas/com.deepin.dde.appearance.gschema.xml

%build
export GO111MODULE=on
export GOFLAGS="-mod=mod"
export GOPATH=%{_builddir}/gopath
%make_build

%install
%make_install

%check
# Validate the complete installed output, including the generated x86 override.
# Fedora glib2 file triggers compile/remove the live system cache on transactions.
glib-compile-schemas --strict --dry-run %{buildroot}%{_datadir}/glib-2.0/schemas

%files
%license LICENSE
%doc CHANGELOG.md README.md
%{_datadir}/glib-2.0/schemas/
%{_datadir}/deepin-desktop-schemas/
%{_datadir}/deepin-appstore/
%{_datadir}/deepin-app-store/

%changelog
* Fri Nov 27 2026 Fedora DDE Remix contributors - 6.0.13-1.1.remix1
- Remove duplicate mediakey metadata rejected by strict GLib schema compilation.
- Use the Fedora-packaged JPEG background for both appearance schema defaults.
- Check all installed schemas and generated overrides during the RPM build.
- Use Fedora glib2 schema file triggers instead of ignoring compilation failures.

* Sat Nov 21 2026 mozixun <mozixun@fedoraproject.org> - 6.0.13-1
- Initial Fedora package.
