#!/usr/bin/bash
# Installed by fedora-dde-remix-config as /usr/libexec/fedora-dde-live.
# The image mode runs in the compose chroot; boot mode only changes the Live
# overlay. No temporary account or password entry is saved in the base image.
set -euo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

die() { printf 'fedora-dde-live: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $# -eq 1 ]] || die 'Usage: fedora-dde-live {image|boot}, as root.'

verify_profile() {
    python3 - <<'PY'
import json
from pathlib import Path
import stat
p = Path('/etc/fedora-dde-installer/install-profile.json')
assert not p.is_symlink() and p.is_file(), 'Missing image installation profile'
s = p.stat()
assert s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o644, 'Incorrect profile ownership/mode'
profile = json.loads(p.read_text())
assert type(profile.get('schema')) is int and profile == {'schema': 1, 'selinux': 'disabled', 'pam': 'ddm-system-login'}, 'Unexpected image profile'
PY
}

configure_image() {
    source /etc/os-release
    [[ $ID == fedora && $VERSION_ID == 45 ]] || die 'Only Fedora 45 images are supported.'
    verify_profile
    python3 - <<'PY'
import json
from pathlib import Path
import re
import subprocess
p = Path('/usr/share/fedora-dde-remix/build-info.json')
assert not p.is_symlink() and p.is_file(), 'Missing build provenance JSON'
data = json.loads(p.read_text())
expected = {'iso_repository': 'Fedora-DDE-Remix/ISO-Build',
            'installer_repository': 'Fedora-DDE-Remix/fedora-dde-installer',
            'fedora_release': '45', 'architecture': 'x86_64', 'selinux': 'disabled',
            'copr': 'mozixun/Fedora-DDE-Remix', 'desktop_group': 'dde-desktop', 'live_login': 'manual'}
assert isinstance(data, dict) and all(data.get(k) == v for k, v in expected.items()), 'Unexpected build provenance'
assert all(re.fullmatch(r'[0-9a-f]{40}', data.get(k, '')) for k in ('iso_commit', 'installer_commit')), 'Invalid source commit'
comps = data.get('comps', {})
installed_comps = subprocess.check_output(
    ['rpm', '-q', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', 'dde-desktop-comps'],
    text=True)
assert comps.get('nevra') == installed_comps, 'Comps input differs from the installed RPM'
assert re.fullmatch(r'[0-9a-f]{64}', comps.get('sha256', '')), 'Missing comps RPM digest'
PY
    [[ -s /etc/pam.d/system-login ]] || die 'The Fedora system-login compatibility stack is missing.'
    [[ -x /usr/libexec/fedora-dde-live ]] || die 'The packaged Live helper is missing.'
    [[ -f /usr/lib/systemd/system/fedora-dde-live.service ]] || die 'The Live service is missing.'
    [[ -x /usr/bin/fedora-dde-installer-launch ]] || die 'The graphical installer launcher is missing.'
    [[ -s /usr/share/applications/fedora-dde-installer.desktop ]] || die 'The installer desktop entry is missing.'
    [[ -f /usr/lib/systemd/system/ddm.service ]] || die 'DDM is missing.'
    if rpm -q systemd-homed >/dev/null 2>&1; then
        die 'systemd-homed must not be installed in this image.'
    fi
    if grep -q '^liveuser:' /etc/passwd || [[ -e /home/liveuser ]]; then
        die 'The read-only image must not contain the temporary Live account.'
    fi
    authselect check
    usermod --lock root

    # Preserve the Fedora policy packages and PAM files. This particular image
    # explicitly boots with SELinux disabled; its installer profile carries the
    # same decision into the installed system.
    if grep -q '^SELINUX=' /etc/selinux/config; then
        sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config
    else
        printf '\nSELINUX=disabled\n' >> /etc/selinux/config
    fi
    for hook in 20-grub.install 50-dracut.install 51-dracut-rescue.install; do
        [[ -s /usr/lib/kernel/install.d/$hook && -x /usr/lib/kernel/install.d/$hook ]] ||
            die "Missing conventional kernel-install hook: $hook"
        if [[ -e /etc/kernel/install.d/$hook || -L /etc/kernel/install.d/$hook ]]; then
            [[ -s /etc/kernel/install.d/$hook && -x /etc/kernel/install.d/$hook ]] ||
                die "A kernel-install hook is masked: $hook"
        fi
    done
    [[ -s /usr/lib/dracut/dracut.conf.d/02-rescue.conf ]] || die 'dracut-config-rescue is missing.'

    # The custom service supplies a password-protected account at Live boot.
    # Disable other first-run helpers that could create an empty-password user
    # or replace the normal DDM login configuration.
    for unit in livesys.service livesys-late.service initial-setup.service initial-setup-graphical.service; do
        if [[ -e /usr/lib/systemd/system/$unit || -L /etc/systemd/system/$unit ]]; then
            systemctl disable "$unit"
        fi
    done
    systemctl enable NetworkManager.service fedora-dde-live.service fedora-dde-installer.service
    systemctl enable --force ddm.service
    systemctl set-default graphical.target

    # A new machine identity is generated in the writable overlay at boot.
    rm -f /etc/machine-id /var/lib/dbus/machine-id
    install -m 0444 /dev/null /etc/machine-id
    ln -s /etc/machine-id /var/lib/dbus/machine-id
    rm -f /var/lib/systemd/random-seed /var/lib/systemd/credential.secret /etc/ssh/ssh_host_*
    dnf -y clean all
    install -d -m 0755 /usr/share/fedora-dde-remix
    rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' |
        LC_ALL=C sort -u > /usr/share/fedora-dde-remix/rpm-manifest.txt
    awk -F: '$2 == "" { bad=1 } END { exit bad }' /etc/shadow || die 'The image contains an empty password entry.'
    printf '%s\n' 'Image configuration complete; the Live user will be created at boot.'
}

configure_boot() {
    # A second guard is intentional: the service and executable both require
    # a Live boot. An installed target must never acquire a temporary account.
    local argument is_live=0
    local -a arguments
    read -r -a arguments < /proc/cmdline
    for argument in "${arguments[@]}"; do
        if [[ $argument == rd.live.image ]]; then
            is_live=1
        fi
    done
    (( is_live == 1 )) || exit 0
    [[ ! -e /etc/fedora-dde-installer-target ]] || exit 0
    verify_profile

    if ! getent passwd liveuser >/dev/null; then
        useradd --create-home --user-group --groups wheel --shell /bin/bash --comment 'Live User' liveuser
        # This is the public, temporary Live login. Never use an empty password
        # and never reset a user's password if the service is started again.
        printf '%s:%s\n' liveuser liveuser | chpasswd
    fi
    [[ $(id -u liveuser) -ge 1000 && $(getent passwd liveuser | cut -d: -f6) == /home/liveuser ]] ||
        die 'An unexpected account occupies the Live username.'
    usermod --append --groups wheel liveuser
    install -d -m 0755 -o liveuser -g liveuser /home/liveuser/Desktop /home/liveuser/.config
    install -m 0755 -o liveuser -g liveuser /usr/share/applications/fedora-dde-installer.desktop \
        /home/liveuser/Desktop/fedora-dde-installer.desktop
    if [[ ! -e /home/liveuser/.config/user-dirs.dirs ]]; then
        printf '%s\n' 'XDG_DESKTOP_DIR="$HOME/Desktop"' > /home/liveuser/.config/user-dirs.dirs
        chown liveuser:liveuser /home/liveuser/.config/user-dirs.dirs
    fi
    install -d -m 0755 /run/issue.d
    printf '\nFedora DDE Remix Live: username liveuser, password liveuser.\n' > /run/issue.d/90-fedora-dde-live.issue
    printf '%s\n' 'Live account prepared. Sign in through DDM as liveuser.'
}

case $1 in
    image) configure_image ;;
    boot) configure_boot ;;
    *) die 'Expected image or boot.' ;;
esac
