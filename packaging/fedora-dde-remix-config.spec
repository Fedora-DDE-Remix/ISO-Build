Name:           fedora-dde-remix-config
Version:        45.20261126
Release:        1%{?dist}
Summary:        Configuration for the Fedora DDE Remix Live ISO
License:        GPL-3.0-or-later
URL:            https://github.com/Fedora-DDE-Remix/ISO-Build
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
# The installer is installed explicitly by the Live recipe and removed from
# the installed system. This configuration package must survive that removal.
Requires:       ddm >= 0.5.0-8
Requires:       ddm-selinux >= 1:1.0.0-3
Requires:       dde-daemon-selinux >= 1:1.0.0-4
Requires:       dde-api-selinux >= 1:1.0.0-2
Requires:       deepin-system-monitor-selinux >= 1:1.0.0-2
Requires:       authselect
Requires:       pam
Requires:       systemd-pam
Requires:       shadow-utils
Requires:       sudo
Requires:       xdg-user-dirs
Requires:       python3
Requires:       policycoreutils
Requires:       libselinux-utils

%description
Release-specific configuration for the Fedora 45 DDE Remix ISO.
It selects the Fedora PAM and SELinux Enforcing installation profile, requires
the maintainer's DDM and DDE SELinux policy packages, and prepares a temporary
password-authenticated Live user only when booting Live media.

%prep
%setup -q

%build

%install
install -Dm644 config/install-profile.json %{buildroot}%{_sysconfdir}/fedora-dde-installer/install-profile.json
install -Dm644 config/fedora-dde-live.service %{buildroot}%{_unitdir}/fedora-dde-live.service
install -Dm755 scripts/configure-live.sh %{buildroot}%{_libexecdir}/fedora-dde-live

%post
%systemd_post fedora-dde-live.service

%preun
%systemd_preun fedora-dde-live.service

%postun
%systemd_postun_with_restart fedora-dde-live.service

%files
%license LICENSE
%doc README.md
%dir %{_sysconfdir}/fedora-dde-installer
%config(noreplace) %{_sysconfdir}/fedora-dde-installer/install-profile.json
%{_unitdir}/fedora-dde-live.service
%{_libexecdir}/fedora-dde-live

%changelog
* Thu Nov 26 2026 Fedora DDE Remix contributors - 45.20261126-1
- Enable SELinux Enforcing for the Live image and installed system.
- Use the maintainer's Fedora PAM configuration and DDE SELinux policies.
- Allow removal of the Live installer from the configured target system.

* Mon Nov 23 2026 Fedora DDE Remix contributors - 45.20261123-1
- Select the explicit SELinux-disabled profile for this development ISO.
- Bridge normal DDM password login to Fedora PAM without replacing DDM files.
- Create the temporary Live user only during Live-media boot.

