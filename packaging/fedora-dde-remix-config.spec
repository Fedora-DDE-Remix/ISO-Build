Name:           fedora-dde-remix-config
Version:        45.20261127.3
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
Requires:       rpm
Requires:       policycoreutils
Requires:       libselinux-utils
Requires:       deepin-desktop-schemas >= 6.0.13-1.1.remix1
Requires:       desktop-backgrounds-basic
Requires:       generic-logos
Requires:       fedora-remix-logos
# Fedora's glib2 file triggers compile GSettings schema overrides on changes.
Requires:       glib2

%description
Release-specific configuration for the Fedora 45 DDE Remix ISO.
It selects the Fedora PAM and SELinux Enforcing installation profile, requires
the maintainer's DDM and DDE SELinux policy packages, and prepares a temporary
password-authenticated Live user only when booting Live media. It also reserves
DDM's tty1 from the Fedora kmscon console to avoid competing DRM owners.
The maintained Fedora DDE Remix COPR repository remains enabled after installation,
with its verified project signing key and normal RPM signature checks.
The desktop and lockscreen defaults reference Fedora-packaged backgrounds and
Fedora Remix logos through Treeland, DDE appearance, GSettings and DSysInfo
configuration. Generic system logos replace the restricted Fedora branding.

%prep
%setup -q

%build

%install
install -Dm644 config/install-profile.json %{buildroot}%{_sysconfdir}/fedora-dde-installer/install-profile.json
install -Dm644 config/fedora-dde-live.service %{buildroot}%{_unitdir}/fedora-dde-live.service
install -Dm644 config/ddm-kmscon.conf %{buildroot}%{_unitdir}/ddm.service.d/20-fedora-kmscon.conf
install -Dm755 scripts/configure-live.sh %{buildroot}%{_libexecdir}/fedora-dde-live
install -Dm755 scripts/check-copr.py %{buildroot}%{_libexecdir}/fedora-dde-check-copr
install -Dm755 scripts/check-desktop-assets.py %{buildroot}%{_libexecdir}/fedora-dde-check-desktop-assets
install -Dm644 config/fedora-dde-remix.repo %{buildroot}%{_sysconfdir}/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
install -Dm644 config/RPM-GPG-KEY-fedora-dde-remix %{buildroot}%{_sysconfdir}/pki/rpm-gpg/RPM-GPG-KEY-fedora-dde-remix
install -Dm644 config/treeland-background.json %{buildroot}%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.user/90-fedora-dde-remix-background.json
install -Dm644 config/appearance-background.json %{buildroot}%{_datadir}/dsg/configs/overrides/org.deepin.dde.appearance/org.deepin.dde.appearance/90-fedora-dde-remix-background.json
install -Dm644 config/99-fedora-dde-remix-background.gschema.override %{buildroot}%{_datadir}/glib-2.0/schemas/99-fedora-dde-remix-background.gschema.override
install -Dm644 config/distribution.info %{buildroot}%{_datadir}/deepin/distribution.info

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
%dir %{_unitdir}/ddm.service.d
%{_unitdir}/ddm.service.d/20-fedora-kmscon.conf
%{_libexecdir}/fedora-dde-live
%{_libexecdir}/fedora-dde-check-copr
%{_libexecdir}/fedora-dde-check-desktop-assets
%config(noreplace) %{_sysconfdir}/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
%{_sysconfdir}/pki/rpm-gpg/RPM-GPG-KEY-fedora-dde-remix
%dir %{_datadir}/dsg
%dir %{_datadir}/dsg/configs
%dir %{_datadir}/dsg/configs/overrides
%dir %{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland
%dir %{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.user
%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.user/90-fedora-dde-remix-background.json
%dir %{_datadir}/dsg/configs/overrides/org.deepin.dde.appearance
%dir %{_datadir}/dsg/configs/overrides/org.deepin.dde.appearance/org.deepin.dde.appearance
%{_datadir}/dsg/configs/overrides/org.deepin.dde.appearance/org.deepin.dde.appearance/90-fedora-dde-remix-background.json
%{_datadir}/glib-2.0/schemas/99-fedora-dde-remix-background.gschema.override
%dir %{_datadir}/deepin
%{_datadir}/deepin/distribution.info

%changelog
* Fri Nov 27 2026 Fedora DDE Remix contributors - 45.20261127.3-1
- Require the strictly validated desktop schema repair and Fedora background defaults.
- Verify the installed mediakey schema and compiled XF86Away binding.

* Fri Nov 27 2026 Fedora DDE Remix contributors - 45.20261127.2-1
- Select Fedora-packaged JPEG backgrounds and permitted Fedora Remix logos.
- Keep existing user wallpaper settings and maintainer-owned defaults intact.
- Ship the desktop asset verifier for image and installed-system checks.

* Fri Nov 27 2026 Fedora DDE Remix contributors - 45.20261127.1-1
- Own and retain the enabled Remix COPR repository and verified signing key.
- Verify the persistent repository in the image and after disk installation.

* Fri Nov 27 2026 Fedora DDE Remix contributors - 45.20261127-1
- Order DDM after, and conflict it with, the Fedora kmscon console on tty1.
- Keep other virtual consoles, Fedora PAM and SELinux Enforcing unchanged.

* Thu Nov 26 2026 Fedora DDE Remix contributors - 45.20261126-1
- Enable SELinux Enforcing for the Live image and installed system.
- Use the maintainer's Fedora PAM configuration and DDE SELinux policies.
- Allow removal of the Live installer from the configured target system.

* Mon Nov 23 2026 Fedora DDE Remix contributors - 45.20261123-1
- Select the explicit SELinux-disabled profile for this development ISO.
- Bridge normal DDM password login to Fedora PAM without replacing DDM files.
- Create the temporary Live user only during Live-media boot.

