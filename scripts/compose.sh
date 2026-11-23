#!/usr/bin/bash
# Run only inside the disposable, privileged Fedora 45 compose container.
set -euo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8
unset ANACONDA_ROOT_PATH

die() { printf 'compose: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $# -eq 0 ]] || die 'Run as root without arguments.'
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 45 && $(uname -m) == x86_64 ]] ||
    die 'The compose environment must be Fedora 45 x86_64.'
for directory in /workspace /work /output; do
    [[ -d $directory && ! -L $directory ]] || die "Missing real directory: $directory"
done
[[ -f /workspace/kickstarts/fedora-dde-live.ks ]] || die 'Kickstart is missing.'
[[ -f /workspace/scripts/check-pam.py ]] || die 'PAM smoke check is missing.'
[[ -s /work/build-info.json && ! -L /work/build-info.json ]] || die 'The build provenance JSON is missing.'
[[ ! -e /work/compose-result ]] || die '/work/compose-result already exists; use a fresh compose workspace.'
[[ ! -e /output/Fedora-DDE-Remix-45-x86_64.iso ]] || die 'The output ISO already exists.'

shopt -s nullglob
rpms=(/work/rpms/*.rpm)
(( ${#rpms[@]} > 0 )) || die 'No locally built installer/configuration RPMs in /work/rpms.'
names=$(rpm -qp --qf '%{NAME}\n' "${rpms[@]}")
grep -qx fedora-dde-installer <<< "$names" || die 'The installer RPM is missing.'
grep -qx fedora-dde-remix-config <<< "$names" || die 'The ISO configuration RPM is missing.'

# This Fedora metapackage supplies Anaconda's no-virt runtime and Lorax's
# xorriso, squashfs, loop/filesystem and Kickstart dependencies.
dnf -y install lorax-lmc-novirt dnf5-plugins
for command in livemedia-creator ksflatten ksvalidator xorriso unsquashfs lsinitrd; do
    command -v "$command" >/dev/null || die "Required command not found: $command"
done
losetup --find >/dev/null || die 'The container cannot allocate a loop device.'

install -d -m 0755 /work/compose-tmp /output/logs
ksflatten --config /workspace/kickstarts/fedora-dde-live.ks -o /work/fedora-dde-live-flat.ks
ksvalidator --version F45 /work/fedora-dde-live-flat.ks
install -m 0644 /work/fedora-dde-live-flat.ks /output/build.ks
rpm -q lorax anaconda-core anaconda-tui python3-kickstart > /output/logs/compose-tool-versions.txt

livemedia-creator \
    --make-iso --no-virt \
    --ks /work/fedora-dde-live-flat.ks \
    --releasever 45 --project 'Fedora DDE Remix' \
    --volid Fedora-DDE-45-x86_64 \
    --rootfs-type squashfs --nomacboot \
    --extra-boot-args 'selinux=0' \
    --iso-only --iso-name Fedora-DDE-Remix-45-x86_64.iso \
    --tmp /work/compose-tmp --resultdir /work/compose-result \
    --logfile /output/logs/lmc.log

iso=/work/compose-result/Fedora-DDE-Remix-45-x86_64.iso
[[ -s $iso ]] || die 'LMC did not produce the expected ISO.'
/usr/bin/bash /workspace/scripts/check-image.sh "$iso" /output/rpm-manifest.txt /output/logs
install -m 0644 "$iso" /output/Fedora-DDE-Remix-45-x86_64.iso
(
    cd /output
    sha256sum Fedora-DDE-Remix-45-x86_64.iso > CHECKSUM
)
printf 'Verified ISO: %s\n' /output/Fedora-DDE-Remix-45-x86_64.iso
