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

dnf -y install dnf5-plugins /usr/bin/curl python3 diffutils
dnf -y copr enable mozixun/Fedora-DDE-Remix

# Use the maintainer's published repository and reuse the exact verified
# comps RPM bytes inside the image before installing its desktop group.
bash /workspace/scripts/prepare-comps.sh
install -m644 /work/comps-input.json /output/comps-input.json
cp -a /work/comps-bootstrap/*.rpm /output/rpms/
install -m644 /work/comps-bootstrap/pubkey.gpg /output/rpms/comps-pubkey.gpg
cmp /work/comps-bootstrap/pubkey.gpg /workspace/config/RPM-GPG-KEY-fedora-dde-remix
dnf group info dde-desktop | tee /output/dde-desktop-group.txt
rpm -q dde-desktop-comps | tee /output/comps-version.txt

dnf -y install git rpm-build \
    lorax-lmc-novirt systemd-rpm-macros tar gzip python3 libselinux-utils

actual_ref=$(git -c safe.directory=/installer -C /installer rev-parse HEAD)
[[ $actual_ref == "$INSTALLER_REF" ]]
iso_ref=$(git -c safe.directory=/workspace -C /workspace rev-parse HEAD)
export INSTALLER_REF FEDORA_RELEASE TARGET_ARCH CONFIG_VERSION iso_ref
python3 /workspace/scripts/prepare-dfm-hotfix.py
bash /workspace/scripts/build-desktop-base-hotfix.sh
bash /workspace/scripts/build-schemas-hotfix.sh

# The workflow checks the pinned archive digest and Actions run before making
# this directory available read-only. No credentials enter this container.
installer_input_mode=$(python3 - <<'PY'
import json, os, re, sys
from pathlib import Path

marker = Path('/installer-rpms/verified-input.json')
approved = {
    'schema': 1,
    'commit': 'bd06acc59908771c726b907d65c92bc84b9f807d',
    'run_id': 46001067422,
    'artifact_id': 15198317588,
    'sha256': '4f74da31a87cc93bdd5285d4ce15fb6033f5683d77bb5e0ae670c4441778098f',
}

def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate verification-marker field')
        value[key] = item
    return value

try:
    info = {'mode': 'source-build', 'commit': os.environ['INSTALLER_REF']}
    if marker.is_symlink():
        raise ValueError('verification marker must not be a symlink')
    if marker.exists():
        if not marker.is_file() or marker.stat().st_size > 4096:
            raise ValueError('verification marker is not a small regular file')
        value = json.loads(marker.read_text(), object_pairs_hook=unique_keys)
        if (not isinstance(value, dict) or type(value.get('schema')) is not int
                or value['schema'] != 1 or not isinstance(value.get('commit'), str)
                or not re.fullmatch(r'[0-9a-f]{40}', value['commit'])):
            raise ValueError('verification marker has an invalid schema or commit')
        if value['commit'] != os.environ['INSTALLER_REF']:
            info['fallback_reason'] = 'verified input belongs to another installer commit'
        else:
            if (value != approved or type(value.get('run_id')) is not int
                    or type(value.get('artifact_id')) is not int):
                raise ValueError('verification marker does not match the approved Actions artifact')
            info = {'mode': 'verified-ci-rpms', **value}
    else:
        info['fallback_reason'] = 'no verified installer artifact was supplied'
    Path('/work/installer-input.json').write_text(json.dumps(info, indent=2) + '\n')
    print(info['mode'])
except (OSError, ValueError) as error:
    print(f'Invalid verified installer input: {error}', file=sys.stderr)
    sys.exit(1)
PY
)

if [[ $installer_input_mode == source-build ]]; then
    echo 'Building the pinned installer from source, including its RPM tests.'
    dnf -y install cmake gcc-c++ ninja-build
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
    installer_input_dir=$installer_top
else
    python3 - <<'PY'
import json
from pathlib import Path
info = json.loads(Path('/work/installer-input.json').read_text())
print(f'Reusing installer RPMs from verified Actions run {info["run_id"]}.')
PY
    installer_input_dir=/installer-rpms
fi

# Both branches must supply one matching binary/SRPM pair with valid RPM
# digests. The archive provenance authenticates CI inputs; those RPMs need not
# carry a COPR signing key. Never disable payload/header digest checks.
python3 - "$installer_input_dir" <<'PY'
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

def run(*args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(f'{args[0]} verification failed (exit {result.returncode}): {result.stderr.strip()}')
    return result.stdout.strip()

def one_rpm(directory, pattern, root):
    matches = sorted(directory.rglob(pattern))
    if len(matches) != 1:
        raise ValueError(f'expected exactly one {pattern}, found {len(matches)}')
    path = matches[0]
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('installer RPM must be a regular file inside its input directory')
    return path

def inspect(path, expected, source):
    run('rpm', '--checksig', '--nosignature', str(path))
    values = run('rpm', '-qp', '--qf',
                 '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCEPACKAGE}\t%{SOURCERPM}\n',
                 str(path)).split('\t')
    if len(values) != 7 or values[:4] != expected:
        raise ValueError(f'{path.name} does not match the pinned installer spec')
    name, epoch, version, release, arch, source_package, source_rpm = values
    if source:
        # SRPM headers may retain the build architecture; SOURCEPACKAGE, not
        # the filename suffix or ARCH alone, identifies an actual source RPM.
        if source_package != '1' or arch not in {'src', 'noarch', os.environ['TARGET_ARCH']}:
            raise ValueError(f'{path.name} is not the expected source RPM')
        suffix = 'src'
    else:
        if arch != os.environ['TARGET_ARCH'] or source_package not in {'(none)', '0'}:
            raise ValueError(f'{path.name} is not the expected binary architecture')
        suffix = arch
    if path.name != f'{name}-{version}-{release}.{suffix}.rpm':
        raise ValueError('installer RPM filename does not match its header')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'filename': path.name, 'sha256': digest,
            'nevra': f'{name}-{epoch}:{version}-{release}.{suffix}', 'source_rpm': source_rpm}

try:
    info_path = Path('/work/installer-input.json')
    info = json.loads(info_path.read_text())
    root = Path(sys.argv[1]).resolve(strict=True)
    reuse = info['mode'] == 'verified-ci-rpms'
    binary_root = root if reuse else root / 'RPMS' / os.environ['TARGET_ARCH']
    source_root = root if reuse else root / 'SRPMS'
    binary = one_rpm(binary_root, 'fedora-dde-installer-[0-9]*.x86_64.rpm', root)
    source = one_rpm(source_root, 'fedora-dde-installer-[0-9]*.src.rpm', root)
    expected = run('rpmspec', '--query', '--srpm', '--qf',
                   '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\n',
                   '/installer/packaging/fedora-dde-installer.spec').split('\t')
    if len(expected) != 4 or expected[0] != 'fedora-dde-installer':
        raise ValueError('cannot determine the pinned installer spec identity')
    if reuse and expected[2] != '0.3.0':
        raise ValueError('the approved installer artifact must match version 0.3.0')
    binary_info = inspect(binary, expected, False)
    source_info = inspect(source, expected, True)
    if binary_info['source_rpm'] != source.name:
        raise ValueError('installer binary does not identify the supplied matching SRPM')
    shutil.copy2(binary, Path('/work/rpms') / binary.name)
    shutil.copy2(source, Path('/output/rpms') / source.name)
    info.update(binary_rpm=binary_info, source_rpm=source_info)
    info_path.write_text(json.dumps(info, indent=2) + '\n')
    print(f'Validated installer binary and source RPMs ({info["mode"]}).')
except (OSError, ValueError, KeyError) as error:
    print(f'Installer RPM input verification failed: {error}', file=sys.stderr)
    sys.exit(1)
PY

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
    'selinux': 'enforcing',
    'pam': 'fedora',
    'image_version': os.environ['CONFIG_VERSION'],
    'copr': 'mozixun/Fedora-DDE-Remix',
    'desktop_group': 'dde-desktop',
    'comps': json.loads(Path('/work/comps-input.json').read_text()),
    'installer_input': json.loads(Path('/work/installer-input.json').read_text()),
    'dfm_hotfix': json.loads(Path('/work/dfm-hotfix-input.json').read_text()),
    'desktop_base_hotfix': json.loads(Path('/work/desktop-base-hotfix-input.json').read_text()),
    'schemas_hotfix': json.loads(Path('/work/schemas-hotfix-input.json').read_text()),
    'live_login': 'manual',
    'built_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
for path in ('/work/build-info.json', '/output/build-info.json'):
    Path(path).write_text(json.dumps(data, indent=2) + '\n')
PY

config_top=/work/config-rpmbuild
config_source=/work/config-sources/fedora-dde-remix-config-$CONFIG_VERSION
mkdir -p "$config_top"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} "$config_source"/{config,scripts}
install -m644 /workspace/LICENSE /workspace/README.md "$config_source/"
install -m644 /workspace/config/{install-profile.json,fedora-dde-live.service,ddm-kmscon.conf,fedora-dde-remix.repo,RPM-GPG-KEY-fedora-dde-remix} "$config_source/config/"
install -m644 /workspace/config/{treeland-background.json,appearance-background.json,99-fedora-dde-remix-background.gschema.override,distribution.info} "$config_source/config/"
install -m755 /workspace/scripts/configure-live.sh "$config_source/scripts/"
install -m755 /workspace/scripts/check-copr.py "$config_source/scripts/"
install -m755 /workspace/scripts/check-desktop-assets.py "$config_source/scripts/"
tar -C /work/config-sources -czf "$config_top/SOURCES/fedora-dde-remix-config-$CONFIG_VERSION.tar.gz" \
    "fedora-dde-remix-config-$CONFIG_VERSION"
rpmbuild --define "_topdir $config_top" -ba /workspace/packaging/fedora-dde-remix-config.spec \
    2>&1 | tee /output/logs/config-rpmbuild.log
cp -a "$config_top"/RPMS/noarch/*.rpm /work/rpms/
cp -a "$config_top"/SRPMS/*.rpm /output/rpms/
cp -a /work/rpms/*.rpm /output/rpms/
(cd /output/rpms && sha256sum ./*.rpm > SHA256SUMS)

bash /workspace/scripts/compose.sh

