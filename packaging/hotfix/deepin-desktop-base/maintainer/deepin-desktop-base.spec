%global _deepin_version 25

Name:           deepin-desktop-base
Version:        2026.10.28
Release:        1%{?dist}
Summary:        Base data files for the Deepin desktop environment
License:        GPL-3.0-or-later
URL:            https://github.com/linuxdeepin/deepin-desktop-base
Source0:        %{url}/archive/%{version}/deepin-desktop-base-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make

Requires:       fedora-logos

%description
This package provides the Deepin desktop version files, language metadata,
Plymouth logo and application store metadata.  It does not ship
/etc/lsb-release; Fedora owns that file.

%prep
%autosetup -n deepin-desktop-base-%{version} -p1
sed -i 's|/usr/lib|%{_datadir}|' Makefile

%build
VERSION=%{_deepin_version}
RELEASE=
sed -e "s|@@VERSION@@|$VERSION|g" -e "s|@@RELEASE@@|$RELEASE|g" files/lsb-release.in > files/lsb-release
sed -e "s|@@VERSION@@|$VERSION|g" -e "s|@@RELEASE@@|$RELEASE|g" files/desktop-version.in > files/desktop-version

%install
%make_install
rm -f %{buildroot}%{_sysconfdir}/lsb-release
rm -rf %{buildroot}%{_sysconfdir}/systemd
ln -s %{_datadir}/deepin/desktop-version %{buildroot}%{_sysconfdir}/deepin-version
install -Dm644 files/os-version-amd %{buildroot}%{_sysconfdir}/dde-version
rm -rf %{buildroot}%{_datadir}/python-apt
rm -rf %{buildroot}%{_datadir}/distro-info

%files
%license LICENSE
%doc README.md
%config(noreplace) %{_sysconfdir}/appstore.json
%{_sysconfdir}/deepin-version
%{_sysconfdir}/dde-version
%{_datadir}/deepin/
%{_datadir}/i18n/i18n_dependent.json
%{_datadir}/i18n/language_info.json
%{_datadir}/plymouth/deepin-logo.png

%changelog
* Sat Nov 21 2026 mozixun <mozixun@fedoraproject.org> - 2026.10.28-1
- Initial Fedora package.
