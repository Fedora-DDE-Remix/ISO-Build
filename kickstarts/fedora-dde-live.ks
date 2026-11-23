# Fedora 45 x86_64 Live image, composed only with livemedia-creator --no-virt.
# The single partition supplies the size of LMC's temporary filesystem image.
# No physical disk names or disk-clearing commands belong in this Kickstart.
lang en_US.UTF-8
keyboard us
timezone Etc/UTC --utc
rootpw --lock
selinux --disabled
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
grub2-pc
grub2-pc-modules
grub2-tools
grub2-tools-extra
grub2-efi-x64
grub2-efi-x64-cdboot
shim-x64
efibootmgr
policycoreutils
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
install -d -m 0700 /mnt/sysimage/root/compose-rpms
shopt -s nullglob
rpms=(/work/rpms/*.rpm)
(( ${#rpms[@]} > 0 ))
install -m 0600 "${rpms[@]}" /mnt/sysimage/root/compose-rpms/
%end

%post --erroronfail --interpreter=/usr/bin/bash --log=/var/log/fedora-dde-remix-compose.log
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
    rm -f /root/.fedora-dde-iso-build /root/check-pam.py /root/configure-live.sh
    rm -rf /root/compose-rpms
    # Leave the %post log intact on both successful and failed installs.
    exit "$status"
}
trap cleanup EXIT

# The comps RPM enables its local file:// repository. It must be installed in
# an earlier transaction than the group, so that the next DNF process can load
# the new group metadata. Keep the maintainer's prescribed order.
dnf -y copr enable mozixun/Fedora-DDE-Remix
dnf -y install dde-desktop-comps
dnf -y --exclude=systemd-homed group install dde-desktop
dnf -y --exclude=systemd-homed install /root/compose-rpms/*.rpm

/root/configure-live.sh image
install -m 0600 /dev/null /root/.fedora-dde-iso-build
python3 /root/check-pam.py
%end

%post --nochroot --erroronfail --interpreter=/usr/bin/bash --log=/output/logs/save-manifest.log
set -euo pipefail
mountpoint -q /mnt/sysimage
install -m 0644 /mnt/sysimage/usr/share/fedora-dde-remix/rpm-manifest.txt /output/rpm-manifest.txt
cmp /work/build-info.json /mnt/sysimage/usr/share/fedora-dde-remix/build-info.json
install -m 0644 /mnt/sysimage/usr/share/fedora-dde-remix/build-info.json /output/build-info.json
install -m 0644 /mnt/sysimage/var/log/fedora-dde-remix-compose.log /output/logs/image-config.log
test ! -e /mnt/sysimage/root/.fedora-dde-iso-build
test ! -e /mnt/sysimage/root/compose-rpms
test ! -e /mnt/sysimage/root/compose-resolv.conf
test ! -L /mnt/sysimage/root/compose-resolv.conf
test ! -e /mnt/sysimage/root/compose-resolv.conf.absent
if grep -q '^liveuser:' /mnt/sysimage/etc/passwd; then
    echo 'Refusing to publish an image with a baked-in Live account.' >&2
    exit 1
fi
%end
