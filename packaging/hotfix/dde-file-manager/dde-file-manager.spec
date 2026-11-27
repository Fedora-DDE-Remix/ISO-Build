%global commit bdd0f409316054d136eeb8eb7a132a977e4915f7
%global packaging_commit adcd681b0b9e68cacbf9daa33bede62a253a3315

Name:           dde-file-manager
Version:        6.6.7
Release:        9.1.remix1%{?dist}
Summary:        File manager for the Deepin desktop environment
License:        GPL-3.0-or-later
URL:            https://github.com/linuxdeepin/dde-file-manager
Source0:        %{url}/archive/%{commit}/dde-file-manager-%{commit}.tar.gz
Patch0:         https://raw.githubusercontent.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/%{packaging_commit}/dde-file-manager/01-fedora-disable-appimage-qt611.patch
Patch1:         https://raw.githubusercontent.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/%{packaging_commit}/dde-file-manager/02-pc-remove-libappimage.patch
Patch2:         0001-dpf-centralize-event-converter.patch

BuildRequires:  cmake
BuildRequires:  gcc-c++
BuildRequires:  ninja-build
BuildRequires:  extra-cmake-modules
BuildRequires:  cmake(Qt6Core)
BuildRequires:  cmake(Qt6Gui)
BuildRequires:  cmake(Qt6Widgets)
BuildRequires:  cmake(Qt6DBus)
BuildRequires:  cmake(Qt6Concurrent)
BuildRequires:  cmake(Qt6Svg)
BuildRequires:  boost-devel
BuildRequires:  pkgconfig(libcryptsetup)
BuildRequires:  deepin-service-manager-devel
BuildRequires:  pkgconfig(xcb)
BuildRequires:  pkgconfig(xcb-ewmh)
BuildRequires:  cmake(Qt6Network)
BuildRequires:  cmake(Qt6Sql)
BuildRequires:  cmake(Qt6Multimedia)
BuildRequires:  cmake(Qt6LinguistTools)
BuildRequires:  cmake(Qt6GuiPrivate)
BuildRequires:  cmake(Qt6CorePrivate)
BuildRequires:  cmake(Qt6WidgetsPrivate)
BuildRequires:  cmake(Dtk6Core)
BuildRequires:  cmake(Dtk6Gui)
BuildRequires:  cmake(Dtk6Widget)
BuildRequires:  cmake(DDEShell)
BuildRequires:  cmake(deepin-pdfium)
BuildRequires:  cmake(udisks2-qt6)
BuildRequires:  cmake(dfm6-io)
BuildRequires:  cmake(dfm6-mount)
BuildRequires:  cmake(dfm6-burn)
BuildRequires:  cmake(dfm6-search)
BuildRequires:  cmake(KF6SyntaxHighlighting)
BuildRequires:  pkgconfig(dde-dock)
BuildRequires:  pkgconfig(gio-2.0)
BuildRequires:  pkgconfig(gio-unix-2.0)
BuildRequires:  pkgconfig(glib-2.0)
BuildRequires:  pkgconfig(icu-uc)
BuildRequires:  pkgconfig(icu-i18n)
BuildRequires:  pkgconfig(icu-io)
BuildRequires:  pkgconfig(libheif)
BuildRequires:  pkgconfig(mount)
BuildRequires:  pkgconfig(libsecret-1)
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(minizip)
BuildRequires:  pkgconfig(polkit-qt6-1)
BuildRequires:  pkgconfig(taglib)
BuildRequires:  pkgconfig(x11)
BuildRequires:  pkgconfig(zlib)
BuildRequires:  poppler-cpp-devel
BuildRequires:  polkit-devel
BuildRequires:  openssl-devel

Requires:       dde-shell
Requires:       dde-tray-loader
Requires:       deepin-pdfium
Requires:       udisks2-qt6
Requires:       util-dfm-io
Requires:       util-dfm-mount
Requires:       util-dfm-burn
Requires:       util-dfm-search
Requires:       gvfs
Requires:       gvfs-fuse
Requires:       polkit
Requires:       cryfs
Requires:       fuse

%description
dde-file-manager is the Deepin file manager and desktop.  It provides the
file manager application, desktop icons, disk mount integration, file
previews and the Treeland desktop plugin.

%package        libs
Summary:        Shared libraries for %{name}
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description    libs
This package contains the dde-file-manager shared libraries.

%package        devel
Summary:        Development files for %{name}
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

%description    devel
This package contains the DFM6 base/framework and dfm-extension development
files.

%package        services-plugins
Summary:        deepin-service-manager plugins for %{name}
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       deepin-service-manager

%description    services-plugins
This package contains the disk encryption, mount, share and USB repair
plugins loaded by deepin-service-manager.

%package        desktop
Summary:        Desktop icons for %{name}
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       dde-shell
Requires:       dde-tray-loader

%description    desktop
This package contains the Treeland desktop plugin and the Computer, Trash and
Home desktop entries.

%prep
%autosetup -n dde-file-manager-%{commit} -p1

%build
%cmake -GNinja \
  -DOPT_ENABLE_BUILD_UT=OFF \
  -DOPT_ENABLE_BUILD_TESTS=OFF \
  -DBUILD_TESTING=OFF
%cmake_build

%install
%cmake_install
if [ -d %{buildroot}%{_prefix}/etc ]; then
  cp -a %{buildroot}%{_prefix}/etc/. %{buildroot}%{_sysconfdir}/
  rm -rf %{buildroot}%{_prefix}/etc
fi

%files
%license LICENSE
%doc README.md
%{_bindir}/dde-file-manager
%{_bindir}/dde-file-manager-daemon
%{_bindir}/dde-file-manager-pkexec
%{_bindir}/dde-property-dialog
%{_bindir}/dde-file-dialog
%{_bindir}/dde-select-dialog-x11
%{_bindir}/dde-select-dialog-wayland
%{_bindir}/deepin-diskencrypt-service
%{_bindir}/dde-usb-repair-dialog
%{_bindir}/file-manager.sh
%{_libexecdir}/dde-file-manager
%{_libexecdir}/dde-file-manager-preview
%{_libdir}/dde-file-manager/plugins/filemanager-core/
%{_libdir}/dde-file-manager/plugins/previews/
%{_libdir}/dde-file-manager/plugins/common-core/
%{_prefix}/lib/dde-dock/plugins/system-trays/libdde-disk-mount-plugin.so
%{_libdir}/dde-file-manager/tools/
%{_datadir}/applications/dde-file-manager.desktop
%{_datadir}/applications/dde-open.desktop
%{_datadir}/applications/dfm-reencrypt.desktop
%{_datadir}/dde-file-manager/
%{_datadir}/applications/context-menus/.readme
%{_datadir}/dsg/configs/org.deepin.dde.dock/
%{_datadir}/deepin/dde-file-manager/
%{_datadir}/deepin-manual/manual-assets/application/
%{_datadir}/deepin-debug-config/deepin-debug-config.d/
%{_datadir}/deepin-log-viewer/deepin-log.conf.d/
%{_datadir}/dbus-1/interfaces/
%{_datadir}/dbus-1/services/
%{_datadir}/dbus-1/system.d/
%{_datadir}/dbus-1/system-services/
%{_datadir}/polkit-1/actions/
%{_datadir}/polkit-1/rules.d/
%{_datadir}/dsg/configs/org.deepin.dde.file-manager/
%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.app/
%{_datadir}/mime/packages/dtk-dci.xml
%config(noreplace) %{_sysconfdir}/X11/Xsession.d/99dfm-dlnfs-automount
%config(noreplace) %{_sysconfdir}/deepin/dde-file-manager/dfm-dlnfs-automount
%config(noreplace) %{_sysconfdir}/udev/rules.d/
%{_userunitdir}/dde-file-manager.service
%{_userunitdir}/dde-session-initialized.target.wants/dde-file-manager.service

%files libs
%{_libdir}/libdde-file-manager.so.1*
%{_libdir}/libdfm6-base.so.1*
%{_libdir}/libdfm6-framework.so.1*
%{_libdir}/libdfm-extension.so.1*

%files devel
%{_includedir}/dfm-base/
%{_includedir}/dfm-framework/
%{_includedir}/dfm-extension/
%{_libdir}/libdde-file-manager.so
%{_libdir}/libdfm6-base.so
%{_libdir}/libdfm6-framework.so
%{_libdir}/libdfm-extension.so
%{_libdir}/pkgconfig/dfm6-base.pc
%{_libdir}/pkgconfig/dfm6-framework.pc
%{_libdir}/pkgconfig/dfm-extension.pc
%{_libdir}/cmake/dfm6-base/
%{_libdir}/cmake/dfm6-framework/
%{_libdir}/cmake/dfm-extension/

%files services-plugins
%{_libdir}/deepin-service-manager/libdde-filemanager-*.so
%{_datadir}/deepin-service-manager/system/dde-filemanager-*.json
%{_datadir}/deepin-service-manager/other/deepin-diskencrypt-service.json
%{_unitdir}/deepin-service-plugin@org.deepin.Filemanager.*.service.d/
%{_unitdir}/deepin-filemanager-diskencrypt.service
%{_tmpfilesdir}/deepin-diskencrypt-tmpfiles.conf
%config(noreplace) %{_sysconfdir}/systemd/system/deepin-service-group@.service.d/dde-file-manage-service-override.conf

%files desktop
%{_libdir}/dde-file-manager/plugins/desktop-core/
%{_libdir}/dde-shell/org.deepin.ds.desktop.so
%{_datadir}/dde-shell/org.deepin.ds.desktop/
%{_datadir}/applications/dde-computer.desktop
%{_datadir}/applications/dde-trash.desktop
%{_datadir}/applications/dde-home.desktop
%{_bindir}/dfm-trash.sh
%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.app/dde-computer/
%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.app/dde-home/
%{_datadir}/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.app/dde-trash/

%changelog
* Fri Nov 27 2026 Fedora DDE Remix <fedora-dde-remix@users.noreply.github.com> - 6.6.7-9.1.remix1
- Temporarily centralize the DPF event converter in the shared framework.
- Rebuild every DFM plugin with the external callback declaration.
- Keep Fedora build flags, SELinux policy and the maintainer's two patches.

* Tue Nov 24 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-9
- Require cryfs and fuse so the vault plugin is usable out of the box.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-8
- Add xcb and xcb-ewmh for the desktop plugins.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-7
- Add deepin-service-manager-devel for the disk encryption service.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-6
- Add libcryptsetup for the vault plugin.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-5
- Add boost-devel for the file manager libraries.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-4
- Add Qt6Svg for the canvas desktop plugin.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-3
- Add cmake(Qt6CorePrivate), required by Qt6 private components.

* Sun Nov 22 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-2
- Use Fedora's pkgconfig(mount) name.
- Drop libappimage from dfm6-base.pc now that the AppImage code is disabled.

* Sat Nov 21 2026 mozixun <mozixun@fedoraproject.org> - 6.6.7-1
- Initial Fedora package.
