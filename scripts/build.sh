#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -Eeuo pipefail
umask 022

if [[ ${FEDORA_DDE_ISO_BUILD:-} != 1 || ! -f /.dockerenv || $EUID -ne 0 ]]; then
    echo 'Run this builder in the documented disposable privileged Fedora container.' >&2
    exit 2
fi

source /workspace/config/build.env
[[ $FEDORA_RELEASE == 45 && $TARGET_ARCH == x86_64 ]]
[[ $INSTALLER_REF =~ ^[0-9a-f]{40}$ ]]
[[ $(rpm -E '%{fedora}') == "$FEDORA_RELEASE" && $(uname -m) == "$TARGET_ARCH" ]]
[[ -d /installer/.git && -d /workspace/.git ]]
mkdir -p /work/rpms /output/logs /output/rpms

dnf -y install dnf5-plugins /usr/bin/curl python3
dnf -y copr enable mozixun/Fedora-DDE-Remix

# Prefer the normal repository. When its metadata has not caught up, consume
# only the signed, completed comps build; keep all desktop packages on the
# normal repository. Reuse these exact verified RPM bytes inside the image.
bash /workspace/scripts/prepare-comps.sh
install -m644 /work/comps-input.json /output/comps-input.json
cp -a /work/comps-bootstrap/*.rpm /output/rpms/
install -m644 /work/comps-bootstrap/pubkey.gpg /output/rpms/comps-pubkey.gpg
dnf group info dde-desktop | tee /output/dde-desktop-group.txt
rpm -q dde-desktop-comps | tee /output/comps-version.txt

dnf -y install git rpm-build cmake gcc-c++ ninja-build \
    lorax-lmc-novirt systemd-rpm-macros tar gzip python3

actual_ref=$(git -c safe.directory=/installer -C /installer rev-parse HEAD)
[[ $actual_ref == "$INSTALLER_REF" ]]
iso_ref=$(git -c safe.directory=/workspace -C /workspace rev-parse HEAD)
export INSTALLER_REF FEDORA_RELEASE TARGET_ARCH iso_ref
python3 - <<'PY'
import datetime, json, os
from pathlib import Path
data = {
    'iso_repository': 'Fedora-DDE-Remix/ISO-Build',
    'iso_commit': os.environ['iso_ref'],
    'installer_repository': 'Fedora-DDE-Remix/fedora-dde-installer',
    'installer_commit': os.environ['INSTALLER_REF'],
    'fedora_release': os.environ['FEDORA_RELEASE'],
    'architecture': os.environ['TARGET_ARCH'],
    'selinux': 'disabled',
    'copr': 'mozixun/Fedora-DDE-Remix',
    'desktop_group': 'dde-desktop',
    'comps': json.loads(Path('/work/comps-input.json').read_text()),
    'live_login': 'manual',
    'built_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
for path in ('/work/build-info.json', '/output/build-info.json'):
    Path(path).write_text(json.dumps(data, indent=2) + '\n')
PY

installer_top=/work/installer-rpmbuild
mkdir -p "$installer_top"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
git -c safe.directory=/installer -C /installer archive \
    --format=tar --prefix=fedora-dde-installer-main/ HEAD |
    gzip -n > "$installer_top/SOURCES/fedora-dde-installer-main.tar.gz"
dnf -y builddep /installer/packaging/fedora-dde-installer.spec
export CMAKE_BUILD_PARALLEL_LEVEL=2
rpmbuild --define "_topdir $installer_top" --define '_smp_mflags -j2' \
    -ba /installer/packaging/fedora-dde-installer.spec 2>&1 |
    tee /output/logs/installer-rpmbuild.log

shopt -s nullglob
installer_rpms=("$installer_top"/RPMS/x86_64/fedora-dde-installer-[0-9]*.rpm)
[[ ${#installer_rpms[@]} == 1 ]]
cp -a "${installer_rpms[@]}" /work/rpms/
cp -a "$installer_top"/SRPMS/*.rpm /output/rpms/

config_top=/work/config-rpmbuild
config_source=/work/config-sources/fedora-dde-remix-config-$CONFIG_VERSION
mkdir -p "$config_top"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} "$config_source"/{config,scripts}
install -m644 /workspace/LICENSE /workspace/README.md "$config_source/"
install -m644 /workspace/config/{install-profile.json,pam-system-login,fedora-dde-live.service} "$config_source/config/"
install -m755 /workspace/scripts/configure-live.sh "$config_source/scripts/"
tar -C /work/config-sources -czf "$config_top/SOURCES/fedora-dde-remix-config-$CONFIG_VERSION.tar.gz" \
    "fedora-dde-remix-config-$CONFIG_VERSION"
rpmbuild --define "_topdir $config_top" -ba /workspace/packaging/fedora-dde-remix-config.spec \
    2>&1 | tee /output/logs/config-rpmbuild.log
cp -a "$config_top"/RPMS/noarch/*.rpm /work/rpms/
cp -a "$config_top"/SRPMS/*.rpm /output/rpms/
cp -a /work/rpms/*.rpm /output/rpms/
(cd /output/rpms && sha256sum ./*.rpm > SHA256SUMS)

bash /workspace/scripts/compose.sh

