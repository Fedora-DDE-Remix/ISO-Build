Name:           fedora-dde-remix-config
Version:        45.20261123
Release:        1%{?dist}
Summary:        Configuration for the Fedora DDE Remix development Live ISO
License:        GPL-3.0-or-later
URL:            https://github.com/Fedora-DDE-Remix/ISO-Build
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
Requires:       fedora-dde-installer >= 0.2.1
Requires:       ddm >= 0.5.0-5
Requires:       authselect
Requires:       pam
Requires:       systemd-pam
Requires:       shadow-utils
Requires:       sudo
Requires:       xdg-user-dirs
Requires:       python3

%description
Release-specific configuration for the Fedora 45 DDE Remix development ISO.
It explicitly selects the SELinux-disabled installation profile, provides a
Fedora system-login PAM bridge for the unchanged DDM package, and prepares a
temporary password-authenticated Live user only when booting Live media.
DDM's own PAM files and the maintained DDE packages are not replaced.

%prep
%setup -q

%build

%install
install -Dm644 config/install-profile.json %{buildroot}%{_sysconfdir}/fedora-dde-installer/install-profile.json
install -Dm644 config/pam-system-login %{buildroot}%{_sysconfdir}/pam.d/system-login
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
%config(noreplace) %{_sysconfdir}/pam.d/system-login
%{_unitdir}/fedora-dde-live.service
%{_libexecdir}/fedora-dde-live

%changelog
* Mon Nov 23 2026 Fedora DDE Remix contributors - 45.20261123-1
- Select the explicit SELinux-disabled profile for this development ISO.
- Bridge normal DDM password login to Fedora PAM without replacing DDM files.
- Create the temporary Live user only during Live-media boot.

