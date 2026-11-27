#!/usr/bin/bash
# Structural ISO and read-only payload checks. This does not boot the ISO or
# mount any filesystem and is not a substitute for a VM installation test.
set -euo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

die() { printf 'check-image: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 3 ]] || die 'Usage: check-image.sh ISO RPM-MANIFEST REPORT-DIRECTORY'
iso=$(realpath -- "$1")
manifest=$(realpath -- "$2")
report_dir=$(realpath -- "$3")
build_info=$(realpath -- "$(dirname -- "$manifest")/build-info.json")
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $EUID -eq 0 ]] || die 'Root is required to extract and verify security.selinux xattrs.'
[[ -s $iso && -s $manifest && -s $build_info && -d $report_dir ]] || die 'ISO, manifest, build information or report directory is missing.'
temporary=$(mktemp -d /work/check-image.XXXXXXXX)
trap 'rm -rf -- "$temporary"' EXIT

xorriso -indev "$iso" -report_el_torito plain -report_system_area plain \
    > "$report_dir/iso-boot-report.txt" 2>&1
grep -Eq 'El Torito boot img.*BIOS' "$report_dir/iso-boot-report.txt" || die 'No BIOS El Torito image.'
grep -Eq 'El Torito boot img.*UEFI' "$report_dir/iso-boot-report.txt" || die 'No UEFI El Torito image.'
grep -Eq 'System area summary:.*MBR' "$report_dir/iso-boot-report.txt" || die 'No hybrid MBR.'
grep -Eq 'System area summary:.*GPT' "$report_dir/iso-boot-report.txt" || die 'No hybrid GPT.'

xorriso -osirrox on -indev "$iso" \
    -extract /boot/grub2/grub.cfg "$temporary/bios.cfg" \
    -extract /EFI/BOOT/grub.cfg "$temporary/uefi.cfg" \
    -extract /EFI/BOOT/BOOTX64.EFI "$temporary/BOOTX64.EFI" \
    -extract /LiveOS/squashfs.img "$temporary/payload.img" \
    -extract /images/pxeboot/initrd.img "$temporary/initrd.img" \
    > "$report_dir/iso-extract.log" 2>&1

python3 - "$temporary/bios.cfg" "$temporary/uefi.cfg" <<'PY'
from pathlib import Path
import re
import sys
for filename in sys.argv[1:]:
    entries = [line.split() for line in Path(filename).read_text().splitlines()
               if re.match(r'^\s*linux(?:efi|16)?\s+', line)]
    assert entries, f'No Linux boot entries in {filename}'
    for entry in entries:
        assert 'selinux=1' in entry and 'enforcing=1' in entry, f'Missing explicit SELinux Enforcing arguments in {filename}'
        assert not any(arg.startswith(('selinux=', 'enforcing=')) and arg not in ('selinux=1', 'enforcing=1')
                       for arg in entry), f'Conflicting SELinux arguments in {filename}'
        assert 'rd.live.image' in entry, f'Not a Fedora Live boot entry in {filename}'
        assert any(arg.startswith('root=live:') for arg in entry), f'Missing Live image root in {filename}'
PY
[[ -s $temporary/BOOTX64.EFI ]] || die 'UEFI fallback loader is empty.'
lsinitrd -m "$temporary/initrd.img" > "$report_dir/initrd-modules.txt"
grep -Eq '^[[:space:]]*dmsquash-live[[:space:]]*$' "$report_dir/initrd-modules.txt" || die 'The initrd lacks dmsquash-live.'

unsquashfs -s "$temporary/payload.img" > "$report_dir/payload-superblock.txt"
unsquashfs -l "$temporary/payload.img" > "$report_dir/payload-files.txt"
grep -Eq '/usr/lib/modules/[^/]+/vmlinuz$' "$report_dir/payload-files.txt" || die 'The payload lacks an installed kernel.'
if grep -Eq '/home/liveuser(/|$)' "$report_dir/payload-files.txt"; then
    die 'The temporary Live home directory is baked into the payload.'
fi
# Extract the critical binaries, underlying mountpoint directories and the
# image's complete file-context database (including .bin/.local/substitutions).
# Directory xattrs follow that persistent map, not mounted procfs/sysfs types.
label_paths=$(python3 "$script_dir/check-selinux.py" paths)
mapfile -t selinux_paths <<< "$label_paths"
unsquashfs -xattrs -no-progress -d "$temporary/root" "$temporary/payload.img" \
    etc/passwd etc/shadow etc/selinux/config \
    etc/fedora-dde-installer/install-profile.json \
    etc/yum.repos.d etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-dde-remix \
    etc/kernel/install.d etc/dracut.conf.d \
    usr/lib/os-release usr/lib/kernel/install.d \
    usr/lib/dracut/dracut.conf.d/02-rescue.conf \
    usr/lib/systemd/system/fedora-dde-live.service usr/libexec/fedora-dde-live \
    usr/libexec/fedora-dde-check-copr \
    usr/lib/systemd/system/ddm.service.d/20-fedora-kmscon.conf \
    usr/bin/systemd-cryptsetup \
    usr/lib/systemd/system-generators/systemd-cryptsetup-generator \
    usr/lib/sysimage/rpm \
    usr/share/fedora-dde-remix/rpm-manifest.txt \
    usr/share/fedora-dde-remix/build-info.json \
    usr/share/applications/fedora-dde-installer.desktop \
    "${selinux_paths[@]}" \
    > "$report_dir/payload-extract.log"
python3 "$script_dir/check-selinux.py" verify "$temporary/root" \
    | tee "$report_dir/selinux-labels.txt"
cmp "$script_dir/check-copr.py" "$temporary/root/usr/libexec/fedora-dde-check-copr"
python3 "$script_dir/check-copr.py" --root "$temporary/root" \
    | tee "$report_dir/copr-repository.json"

python3 - "$temporary/root" "$manifest" "$build_info" <<'PY'
from pathlib import Path
import json
import re
import subprocess
import sys
root, manifest, build_info = map(Path, sys.argv[1:])
def regular(relative):
    path = root / relative
    assert not path.is_symlink() and path.is_file(), f'Missing regular payload file: {relative}'
    return path
release = regular('usr/lib/os-release').read_text()
assert re.search(r'^ID=["\']?fedora["\']?$', release, re.M), 'Not a Fedora payload'
assert re.search(r'^VERSION_ID=["\']?45["\']?$', release, re.M), 'Not a Fedora 45 payload'
for name in ('passwd', 'shadow'):
    content = regular('etc/' + name).read_text()
    assert not re.search(r'^liveuser:', content, re.M), 'Live account is present in the read-only payload'
    if name == 'shadow':
        assert all(line.split(':')[1] for line in content.splitlines() if line), 'An image account has an empty password'
assert re.search(r'^SELINUX=enforcing$', regular('etc/selinux/config').read_text(), re.M), 'SELinux config mismatch'
profile = json.loads(regular('etc/fedora-dde-installer/install-profile.json').read_text())
assert type(profile.get('schema')) is int and profile == {'schema': 1, 'selinux': 'enforcing', 'pam': 'fedora'}, 'Installer profile mismatch'
service = regular('usr/lib/systemd/system/fedora-dde-live.service').read_text()
assert 'ConditionKernelCommandLine=rd.live.image' in service, 'Live service has no kernel condition'
assert 'ExecStart=/usr/libexec/fedora-dde-live boot' in service, 'Live service does not use the boot helper'
assert regular('usr/libexec/fedora-dde-live').stat().st_mode & 0o111, 'Live helper is not executable'
kmscon_path = 'usr/lib/systemd/system/ddm.service.d/20-fedora-kmscon.conf'
kmscon_dropin = regular(kmscon_path)
kmscon_lines = [line.strip() for line in kmscon_dropin.read_text().splitlines()
               if line.strip() and not line.lstrip().startswith(('#', ';'))]
assert kmscon_lines == ['[Unit]', 'After=kmsconvt@tty1.service',
                        'Conflicts=kmsconvt@tty1.service'], 'DDM does not reserve tty1 from kmscon'
assert kmscon_dropin.stat().st_uid == 0 and not kmscon_dropin.stat().st_mode & 0o022, 'Unsafe DDM drop-in ownership or permissions'
assert 'Exec=/usr/bin/fedora-dde-installer-launch' in regular('usr/share/applications/fedora-dde-installer.desktop').read_text()
for name in ('20-grub.install', '50-dracut.install', '51-dracut-rescue.install'):
    hook = regular('usr/lib/kernel/install.d/' + name)
    assert hook.stat().st_size and hook.stat().st_mode & 0o111, f'Disabled kernel hook: {name}'
    override = root / 'etc/kernel/install.d' / name
    if override.exists() or override.is_symlink():
        override = regular('etc/kernel/install.d/' + name)
        assert override.stat().st_size and override.stat().st_mode & 0o111, f'Masked kernel hook: {name}'
rescue = regular('usr/lib/dracut/dracut.conf.d/02-rescue.conf')
if (root / 'etc/dracut.conf.d/02-rescue.conf').exists():
    rescue = regular('etc/dracut.conf.d/02-rescue.conf')
assert re.search(r'''^\s*dracut_rescue_image\s*=\s*(["']?)yes\1\s*(?:#.*)?$''', rescue.read_text(), re.M), 'Rescue generation is disabled'
included = regular('usr/share/fedora-dde-remix/rpm-manifest.txt').read_bytes()
assert included == manifest.read_bytes(), 'The published manifest differs from the payload manifest'
provenance = regular('usr/share/fedora-dde-remix/build-info.json').read_bytes()
assert provenance == build_info.read_bytes(), 'The published build information differs from the payload'
data = json.loads(provenance)
expected = {'iso_repository': 'Fedora-DDE-Remix/ISO-Build',
            'installer_repository': 'Fedora-DDE-Remix/fedora-dde-installer',
            'fedora_release': '45', 'architecture': 'x86_64', 'selinux': 'enforcing',
            'copr': 'mozixun/Fedora-DDE-Remix', 'desktop_group': 'dde-desktop', 'live_login': 'manual'}
assert isinstance(data, dict) and all(data.get(k) == v for k, v in expected.items()), 'Unexpected build information'
assert all(re.fullmatch(r'[0-9a-f]{40}', data.get(k, '')) for k in ('iso_commit', 'installer_commit')), 'Invalid source commit'
# Query the extracted image database, never the builder's installed RPMs.
# The configuration package must own the actual drop-in and remain installed
# after the Live installer is removed from the target system.
regular('usr/lib/sysimage/rpm/rpmdb.sqlite')
owner = subprocess.check_output(
    ['rpm', '--root', str(root), '--dbpath', '/usr/lib/sysimage/rpm',
     '-qf', '/' + kmscon_path, '--qf',
     '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n'], text=True).strip().split('\t')
assert len(owner) == 5 and owner[0] == 'fedora-dde-remix-config' and owner[4] == 'noarch', 'DDM drop-in is not owned by the image configuration RPM'
assert owner[2] == data.get('image_version'), 'DDM configuration RPM version differs from the image provenance'
owner_manifest = f'{owner[0]}\t{owner[1]}:{owner[2]}-{owner[3]}\t{owner[4]}'
assert owner_manifest in included.decode().splitlines(), 'DDM configuration RPM owner is absent from the payload manifest'
for relative in ('usr/bin/systemd-cryptsetup',
                 'usr/lib/systemd/system-generators/systemd-cryptsetup-generator'):
    executable = regular(relative)
    assert executable.stat().st_mode & 0o111, f'Encryption boot component is not executable: {relative}'
    provider = subprocess.check_output(
        ['rpm', '--root', str(root), '--dbpath', '/usr/lib/sysimage/rpm',
         '-qf', '/' + relative, '--qf', '%{NAME}\n'], text=True).strip()
    assert provider == 'systemd-udev', f'Unexpected Fedora encryption component provider: {relative}: {provider}'
names = {line.split('\t')[0] for line in included.decode().splitlines()}
required = {'dde-desktop-comps', 'ddm', 'dde-session', 'dde-shell', 'treeland',
            'fedora-dde-installer', 'fedora-dde-remix-config', 'kernel-core',
            'dracut-live', 'dracut-config-rescue', 'grub2-pc-modules', 'grub2-efi-x64-cdboot',
            'ddm-selinux', 'dde-daemon-selinux', 'dde-api-selinux', 'deepin-system-monitor-selinux',
            'selinux-policy-targeted', 'policycoreutils', 'libselinux-utils',
            'cryptsetup', 'systemd-udev'}
assert required <= names, f'Required RPMs missing: {sorted(required - names)}'
for package in data['dfm_hotfix']['runtime_rpms']:
    expected_package = f"{package['name']}\t{package['epoch']}:{package['version']}-{package['release']}\t{package['arch']}"
    assert expected_package in included.decode().splitlines(), 'The payload lacks a pinned DFM hotfix RPM: ' + expected_package
assert 'systemd-homed' not in names, 'systemd-homed is not supported by this image'
print(f'Payload verified: Fedora 45, {len(names)} package names, no baked-in Live account.')
print(f'DDM tty1 conflict verified; payload RPM owner: {owner_manifest}')
PY
printf '%s\n' \
    'BIOS and UEFI hybrid ISO entries: present' \
    'All ISO Linux boot entries: rd.live.image, selinux=1 and enforcing=1' \
    'Payload: direct read-only SquashFS with dmsquash-live initrd' \
    'Actual payload SELinux xattrs: core system/DDM types and image-policy mountpoint contexts verified' \
    'DDM tty1 kmscon conflict: present and owned by the provenance-matched image configuration RPM' \
    'Persistent COPR repository: enabled, package-owned, verified key and RPM/TLS checks enabled' \
    'Encryption boot executable and generator: present, executable and owned by systemd-udev' \
    'Conventional kernel-install and rescue hooks: preserved' \
    'Temporary Live account and empty password entries: absent' \
    'Embedded and external RPM manifests: identical' \
    'Embedded and external build provenance JSON: validated and identical' \
    'Structural checks only; VM boot and installation still require separate verification.' \
    | tee "$report_dir/image-checks.txt"
