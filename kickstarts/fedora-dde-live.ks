# Fedora 45 x86_64 Live image, composed only with livemedia-creator --no-virt.
# The single partition supplies the size of LMC's temporary filesystem image.
# No physical disk names or disk-clearing commands belong in this Kickstart.
lang en_US.UTF-8
keyboard us
timezone Etc/UTC --utc
network --bootproto=dhcp --device=link --activate
rootpw --lock
selinux --enforcing
firewall --enabled --service=mdns
bootloader --location=none
part / --size=24576 --fstype=ext4
shutdown

url --url=https://dl.fedoraproject.org/pub/fedora/linux/releases/45/Everything/x86_64/os/
repo --name=updates --baseurl=https://dl.fedoraproject.org/pub/fedora/linux/updates/45/Everything/x86_64/

%packages
@core
fedora-release
fedora-repos
dnf5
dnf5-plugins
ca-certificates
authselect
shadow-utils
sudo
NetworkManager
kernel
kernel-modules
kernel-modules-extra
dracut
dracut-live
dracut-network
dracut-config-generic
dracut-config-rescue
cryptsetup
grub2-pc
grub2-pc-modules
grub2-tools
grub2-tools-extra
grub2-efi-x64
grub2-efi-x64-cdboot
shim-x64
efibootmgr
policycoreutils
libselinux-utils
selinux-policy-targeted
zram-generator-defaults
systemd-udev
tar
rsync
python3
xdg-user-dirs
glibc-langpack-en
glibc-langpack-zh
xorg-x11-server-Xwayland
-systemd-homed
-initial-setup
-gnome-initial-setup
%end

# Anaconda's directory-install mode does not supply a system resolver to
# chrooted %post scripts. Copy it, the reviewed scripts and the local RPMs into
# the filesystem that LMC mounted, without mounting the builder's root there.
%post --nochroot --erroronfail --interpreter=/usr/bin/bash --log=/output/logs/stage-files.log
set -euo pipefail
mountpoint -q /mnt/sysimage
test -d /mnt/sysimage/etc
test -d /mnt/sysimage/root
test ! -L /mnt/sysimage/root
test ! -e /mnt/sysimage/root/compose-resolv.conf
test ! -L /mnt/sysimage/root/compose-resolv.conf
test ! -e /mnt/sysimage/root/compose-resolv.conf.absent
stage_failure() {
    local status=$?
    trap - EXIT
    if (( status != 0 )); then
        set +e
        if [[ -e /mnt/sysimage/root/compose-resolv.conf || -L /mnt/sysimage/root/compose-resolv.conf ]]; then
            rm -f /mnt/sysimage/etc/resolv.conf
            mv /mnt/sysimage/root/compose-resolv.conf /mnt/sysimage/etc/resolv.conf
        elif [[ -f /mnt/sysimage/root/compose-resolv.conf.absent ]]; then
            rm -f /mnt/sysimage/etc/resolv.conf /mnt/sysimage/root/compose-resolv.conf.absent
        fi
    fi
    exit "$status"
}
trap stage_failure EXIT
# Moving, rather than dereferencing, preserves the original symlink and its
# target verbatim. The chroot cleanup restores it after the last network use.
if [[ -e /mnt/sysimage/etc/resolv.conf || -L /mnt/sysimage/etc/resolv.conf ]]; then
    mv /mnt/sysimage/etc/resolv.conf /mnt/sysimage/root/compose-resolv.conf
else
    install -m 0600 /dev/null /mnt/sysimage/root/compose-resolv.conf.absent
fi
install -m 0644 /etc/resolv.conf /mnt/sysimage/etc/resolv.conf
install -d -m 0755 /mnt/sysimage/usr/share/fedora-dde-remix
install -m 0644 /work/build-info.json /mnt/sysimage/usr/share/fedora-dde-remix/build-info.json
install -m 0700 /workspace/scripts/configure-live.sh /mnt/sysimage/root/configure-live.sh
install -m 0700 /workspace/scripts/check-pam.py /mnt/sysimage/root/check-pam.py
install -m 0700 /workspace/scripts/check-comps.py /mnt/sysimage/root/check-comps.py
install -m 0700 /workspace/scripts/check-selinux.py /mnt/sysimage/root/check-selinux.py
install -m 0644 /workspace/config/fedora-dde-remix.repo /mnt/sysimage/root/compose-copr.repo
install -d -m 0700 /mnt/sysimage/root/compose-rpms
shopt -s nullglob
rpms=(/work/rpms/*.rpm)
(( ${#rpms[@]} > 0 ))
install -m 0600 "${rpms[@]}" /mnt/sysimage/root/compose-rpms/
install -d -m 0700 /mnt/sysimage/root/compose-comps
comps_rpms=(/work/comps-bootstrap/*.rpm)
(( ${#comps_rpms[@]} == 1 ))
install -m 0600 "${comps_rpms[@]}" /work/comps-bootstrap/pubkey.gpg \
    /work/comps-bootstrap/SHA256SUMS /mnt/sysimage/root/compose-comps/
%end

%post --nochroot --erroronfail --interpreter=/usr/bin/bash --log=/output/logs/image-config.log
# Keep DNF/PAM errors outside the image as well, even if Anaconda aborts and
# unmounts the image before the final manifest-saving script can run.
set -euo pipefail
chroot /mnt/sysimage /usr/bin/bash -s <<'DDE_IMAGE_POST'
set -euo pipefail
umask 022
restore_resolver() {
    if [[ -e /root/compose-resolv.conf || -L /root/compose-resolv.conf ]]; then
        rm -f /etc/resolv.conf && mv /root/compose-resolv.conf /etc/resolv.conf
    elif [[ -f /root/compose-resolv.conf.absent ]]; then
        rm -f /etc/resolv.conf /root/compose-resolv.conf.absent
    else
        echo 'The saved image resolver state is missing.' >&2
        return 1
    fi
}
cleanup() {
    local status=$?
    trap - EXIT
    set +e
    restore_resolver || status=1
    rm -f /root/.fedora-dde-iso-build /root/check-pam.py /root/check-comps.py /root/check-selinux.py /root/configure-live.sh /root/compose-copr.repo
    rm -rf /root/compose-rpms /root/compose-comps
    # Leave the %post log intact on both successful and failed installs.
    exit "$status"
}
trap cleanup EXIT

# The comps RPM enables its local file:// repository. It must be installed in
# an earlier transaction than the group, so that the next DNF process can load
# the new group metadata. Keep the maintainer's prescribed order, using the
# exact comps RPM already downloaded and verified by the builder.
dnf -y copr enable mozixun/Fedora-DDE-Remix
(cd /root/compose-comps && sha256sum --check SHA256SUMS)
# Normalize only this project's freshly generated repository before the
# configuration RPM adopts the identical file. Keep the standard COPR filename
# so normal `dnf copr disable/enable` operations continue to work.
install -Dm0644 /root/compose-comps/pubkey.gpg /etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-dde-remix
install -m0644 /root/compose-copr.repo /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix.repo
rpmkeys --import /root/compose-comps/pubkey.gpg
rpmkeys --checksig --verbose /root/compose-comps/*.rpm
dnf -y --setopt=localpkg_gpgcheck=1 install /root/compose-comps/*.rpm
dnf -y --exclude=systemd-homed group install dde-desktop
# Do not overwrite a newer maintainer build with this temporary package.
# This specific hotfix was reviewed against 6.6.7-9; changed COPR input needs
# a new comparison before composing another image.
python3 - <<'PY'
import hashlib, json, subprocess
from pathlib import Path
build_info = json.loads(Path('/usr/share/fedora-dde-remix/build-info.json').read_text())
hotfix = build_info['dfm_hotfix']
for package in hotfix['runtime_rpms']:
    actual = subprocess.check_output(['rpm', '-q', '--qf', '%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}', package['name']], text=True).split('\t')
    assert actual == ['0', hotfix['base_version'], hotfix['base_release'], 'x86_64'], 'Maintainer DFM input changed; review it before applying the temporary hotfix: ' + package['name']
# The schema repair joins the ordinary local-RPM transaction below. Require
# its exact reviewed input and successful native strict check before any upgrade.
schemas = build_info['schemas_hotfix']
assert (schemas['name'], schemas['version'], schemas['base_release'], schemas['release']) == (
    'deepin-desktop-schemas', '6.0.13', '1.fc45', '1.1.remix1.fc45'), 'Unexpected schema repair identity'
assert schemas.get('build_success') is True and schemas['strict_schema_check'].get('success') is True \
    and schemas['strict_schema_check'].get('command') == 'glib-compile-schemas --strict --dry-run', 'The schema repair did not pass its native strict build check'
old_schemas = subprocess.check_output(['rpm', '-q', '--qf', '%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}', schemas['name']], text=True).split('\t')
assert old_schemas == ['0', schemas['version'], schemas['base_release'], 'noarch'], 'Maintainer schema input changed; review it before the temporary repair'
schemas_filename = schemas['binary_rpm']['filename']
assert schemas_filename == 'deepin-desktop-schemas-6.0.13-1.1.remix1.fc45.noarch.rpm'
schemas_rpm = Path('/root/compose-rpms') / schemas_filename
assert schemas_rpm.is_file() and not schemas_rpm.is_symlink()
with schemas_rpm.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == schemas['binary_rpm']['sha256'], 'The local schema RPM digest changed'
# DSysInfo's distribution file is a new Remix-owned path. Stop if another
# package begins providing it, including an owned-but-missing file; never
# replace an existing maintainer configuration to repair the image's logo.
import os
distribution = '/usr/share/deepin/distribution.info'
assert not os.path.lexists(distribution), 'Existing distribution.info needs a fresh ownership review'
owner = subprocess.run(['rpm', '-qf', distribution, '--qf', '%{NAME}\n'], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert owner.returncode == 1, 'Another RPM owns distribution.info; review before installing Remix defaults'
# The maintainer base-data package hard-depends on the primary Fedora logo
# package. First apply the pinned dependency-only noarch rebuild, then perform
# one explicit artwork substitution. Refuse any additional package removal.
base = build_info['desktop_base_hotfix']
assert (base['name'], base['version'], base['base_release'], base['release']) == (
    'deepin-desktop-base', '2026.10.28', '1.fc45', '1.1.remix1.fc45')
old = subprocess.check_output(['rpm', '-q', '--qf', '%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}', base['name']], text=True).split('\t')
assert old == ['0', base['version'], base['base_release'], 'noarch'], 'Maintainer desktop-base input changed; review before the temporary dependency adaptation'
filename = base['binary_rpm']['filename']
assert filename == 'deepin-desktop-base-2026.10.28-1.1.remix1.fc45.noarch.rpm'
local_rpm = Path('/root/compose-rpms') / filename
assert local_rpm.is_file() and not local_rpm.is_symlink()
with local_rpm.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == base['binary_rpm']['sha256']
subprocess.run(['dnf', '-y', 'install', str(local_rpm)], check=True)
def package_names():
    return set(subprocess.check_output(['rpm', '-qa', '--qf', '%{NAME}\n'], text=True).splitlines())
before = package_names()
assert 'fedora-logos' in before
subprocess.run(['dnf', '-y', 'swap', 'fedora-logos', 'generic-logos'], check=True)
after = package_names()
assert before - after == {'fedora-logos'} and 'generic-logos' in after, 'The artwork substitution removed packages outside its explicit scope'
print('PASS targeted artwork substitution: only fedora-logos removed; all desktop packages retained')
PY
dnf -y --exclude=systemd-homed install /root/compose-rpms/*.rpm
python3 /root/check-comps.py
glib-compile-schemas --strict /usr/share/glib-2.0/schemas
/usr/libexec/fedora-dde-check-desktop-assets

/root/configure-live.sh image
install -m 0600 /dev/null /root/.fedora-dde-iso-build
python3 /root/check-pam.py
DDE_IMAGE_POST
%end

%post --nochroot --erroronfail --interpreter=/usr/bin/bash --log=/output/logs/save-manifest.log
set -euo pipefail
mountpoint -q /mnt/sysimage
install -m 0644 /mnt/sysimage/usr/share/fedora-dde-remix/rpm-manifest.txt /output/rpm-manifest.txt
cmp /work/build-info.json /mnt/sysimage/usr/share/fedora-dde-remix/build-info.json
install -m 0644 /mnt/sysimage/usr/share/fedora-dde-remix/build-info.json /output/build-info.json
install -m 0644 /output/logs/image-config.log /mnt/sysimage/var/log/fedora-dde-remix-compose.log
test ! -e /mnt/sysimage/root/.fedora-dde-iso-build
test ! -e /mnt/sysimage/root/compose-rpms
test ! -e /mnt/sysimage/root/compose-comps
test ! -e /mnt/sysimage/root/compose-copr.repo
test ! -e /mnt/sysimage/root/compose-resolv.conf
test ! -L /mnt/sysimage/root/compose-resolv.conf
test ! -e /mnt/sysimage/root/compose-resolv.conf.absent
if grep -q '^liveuser:' /mnt/sysimage/etc/passwd; then
    echo 'Refusing to publish an image with a baked-in Live account.' >&2
    exit 1
fi
# Label after all final writes with the image's compiled Fedora/DDE policy.
# Lorax also runs setfiles, but does not propagate its return code. This gate
# makes a labeling failure fatal and checks actual security.selinux xattrs.
python3 /workspace/scripts/check-selinux.py label /mnt/sysimage
%end
