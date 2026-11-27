#!/usr/bin/bash
# Build the pinned data-only branding dependency adaptation during ISO compose.
set -Eeuo pipefail
umask 022

if [[ ${FEDORA_DDE_ISO_BUILD:-} != 1 || ! -f /.dockerenv || $EUID -ne 0 ]]; then
    echo 'Run this helper through the disposable Fedora ISO compose container.' >&2
    exit 2
fi
[[ $(rpm --eval '%{fedora}') == 45 && $(uname -m) == x86_64 ]]
[[ $iso_ref =~ ^[0-9a-f]{40}$ ]]

base_packaging=/workspace/packaging/hotfix/deepin-desktop-base
base_work_dir=$(mktemp -d /work/desktop-base-hotfix.XXXXXX)
base_top=$base_work_dir/rpmbuild
base_evidence=/output/rpms/desktop-base-hotfix-provenance
base_upstream_commit=63c52c9387a350df684bb5043dd836d86f862092
base_maintainer_commit=adcd681b0b9e68cacbf9daa33bede62a253a3315
base_source_name=deepin-desktop-base-2026.10.28.tar.gz
mkdir -p "$base_top"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "$base_evidence/sources/maintainer" /work/rpms /output/rpms /output/logs

python3 - "$base_packaging" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
lock = json.loads((root / 'sources.lock.json').read_text())
expected = {
    'schema': 1,
    'maintainer_repository': 'Fedora-DDE-Remix/Deepin-Desktop-Environment',
    'maintainer_commit': 'adcd681b0b9e68cacbf9daa33bede62a253a3315',
    'upstream_repository': 'linuxdeepin/deepin-desktop-base',
    'upstream_tag': '2026.10.28',
    'upstream_tag_object': 'f918a51224a6767103a3044a7595ff2602ee5826',
    'upstream_commit': '63c52c9387a350df684bb5043dd836d86f862092',
    'version': '2026.10.28',
    'base_release': '1.fc45',
    'release': '1.1.remix1.fc45',
}
if any(lock.get(key) != value for key, value in expected.items()):
    raise SystemExit('Unexpected desktop-base source identity')
names = {'deepin-desktop-base.spec', 'maintainer/deepin-desktop-base.spec',
         'maintainer/LICENSE', 'README.md'}
if set(lock['files']) != names:
    raise SystemExit('Unexpected desktop-base source file set')
for name in sorted(names):
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit('Missing regular source input: ' + name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock['files'][name]:
        raise SystemExit('Pinned desktop-base input changed: ' + name)
original = (root / 'maintainer/deepin-desktop-base.spec').read_text()
if original.count('Release:        1%{?dist}\n') != 1 or original.count('Requires:       fedora-logos\n') != 1:
    raise SystemExit('The reviewed maintainer spec has changed')
adapted = original.replace('Release:        1%{?dist}\n',
                           'Release:        1.1.remix1%{?dist}\n')
adapted = adapted.replace('Requires:       fedora-logos\n',
                          'Requires:       system-logos\n')
if (root / 'deepin-desktop-base.spec').read_text() != adapted:
    raise SystemExit('Only the approved dependency and Release adaptation is allowed')
PY

# Compare against the immutable maintainer revision, never a moving branch.
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://raw.githubusercontent.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/$base_maintainer_commit/deepin-desktop-base/deepin-desktop-base.spec" \
    --output "$base_work_dir/maintainer.spec" 2> /output/logs/desktop-base-source-fetch.log
cmp "$base_packaging/maintainer/deepin-desktop-base.spec" "$base_work_dir/maintainer.spec"
cp "$base_packaging/deepin-desktop-base.spec" "$base_packaging/sources.lock.json" \
   "$base_packaging/README.md" "$base_evidence/sources/"
cp "$base_packaging/maintainer/"* "$base_evidence/sources/maintainer/"
cp /workspace/scripts/build-desktop-base-hotfix.sh "$base_evidence/sources/"

git init "$base_work_dir/upstream" > /output/logs/desktop-base-git-source.log 2>&1
git -C "$base_work_dir/upstream" fetch --depth=1 \
    https://github.com/linuxdeepin/deepin-desktop-base.git "$base_upstream_commit" \
    >> /output/logs/desktop-base-git-source.log 2>&1
[[ $(git -C "$base_work_dir/upstream" rev-parse FETCH_HEAD) == "$base_upstream_commit" ]]
git -C "$base_work_dir/upstream" checkout --detach "$base_upstream_commit" \
    >> /output/logs/desktop-base-git-source.log 2>&1
[[ $(git -C "$base_work_dir/upstream" rev-parse HEAD) == "$base_upstream_commit" ]]
git -C "$base_work_dir/upstream" show --no-patch --format=fuller HEAD \
    > "$base_evidence/upstream-commit.txt"
git -C "$base_work_dir/upstream" ls-tree -r HEAD > "$base_evidence/upstream-tree.txt"
python3 - "$base_evidence/upstream-tree.txt" <<'PY'
from pathlib import Path
import sys
if any(line.startswith('160000 ') for line in Path(sys.argv[1]).read_text().splitlines()):
    raise SystemExit('Unexpected desktop-base submodules need a reviewed source manifest')
PY
git -C "$base_work_dir/upstream" archive --format=tar \
    --prefix=deepin-desktop-base-2026.10.28/ HEAD \
    | gzip -n > "$base_top/SOURCES/$base_source_name"
git -C "$base_work_dir/upstream" show HEAD:LICENSE \
    > "$base_evidence/sources/UPSTREAM-LICENSE"
cp "$base_top/SOURCES/$base_source_name" "$base_evidence/sources/"
cp "$base_packaging/deepin-desktop-base.spec" "$base_top/SPECS/"

dnf -y builddep "$base_top/SPECS/deepin-desktop-base.spec" \
    2>&1 | tee /output/logs/desktop-base-builddep.log
rpmspec --parse "$base_top/SPECS/deepin-desktop-base.spec" \
    > "$base_evidence/expanded.spec"
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' \
    | LC_ALL=C sort > "$base_evidence/build-packages.txt"
rpmbuild --define "_topdir $base_top" -ba "$base_top/SPECS/deepin-desktop-base.spec" \
    2>&1 | tee /output/logs/desktop-base-rpmbuild.log

python3 - "$base_top" "$base_evidence" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

top, evidence = map(Path, sys.argv[1:])
name = 'deepin-desktop-base'
version = '2026.10.28'
release = '1.1.remix1.fc45'

def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def run(*args):
    result = subprocess.run(args, text=True, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()

def inspect(directory, source):
    paths = sorted(directory.rglob('*.rpm'))
    if len(paths) != 1:
        raise SystemExit('Expected exactly one desktop-base RPM in ' + str(directory))
    path = paths[0]
    if path.is_symlink() or not path.is_file():
        raise SystemExit('RPM output is not a regular file')
    suffix = 'src' if source else 'noarch'
    if path.name != f'{name}-{version}-{release}.{suffix}.rpm' or ':' in path.name:
        raise SystemExit('Unexpected desktop-base RPM filename')
    run('rpm', '--checksig', '--nosignature', str(path))
    fields = run('rpm', '-qp', '--qf',
                 '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{SOURCEPACKAGE}\n',
                 str(path)).split('\t')
    if len(fields) != 7 or fields[:4] != [name, '0', version, release]:
        raise SystemExit('Unexpected desktop-base RPM header identity')
    header_arch, source_rpm, source_flag = fields[4:]
    if source:
        if source_flag != '1' or header_arch not in {'src', 'noarch', 'x86_64'}:
            raise SystemExit('The matching source RPM is missing')
    elif header_arch != 'noarch' or source_flag not in {'0', '(none)'}:
        raise SystemExit('The desktop-base binary must be noarch')
    return path, {'filename': path.name, 'sha256': digest(path), 'name': name,
                  'epoch': 0, 'version': version, 'release': release,
                  'arch': suffix, 'header_arch': header_arch,
                  'source_rpm': source_rpm,
                  'nevra': f'{name}-0:{version}-{release}.{suffix}'}

binary, binary_info = inspect(top / 'RPMS', False)
source, source_info = inspect(top / 'SRPMS', True)
if binary_info['source_rpm'] != source.name:
    raise SystemExit('Desktop-base binary does not identify its matching SRPM')
requirements = run('rpm', '-qp', '--qf', '[%{REQUIRENAME}\n]', str(binary)).splitlines()
provides = run('rpm', '-qp', '--qf', '[%{PROVIDENAME}\n]', str(binary)).splitlines()
if 'system-logos' not in requirements or 'fedora-logos' in requirements:
    raise SystemExit('The desktop-base runtime dependency was not adapted')
if set(provides) & {'fedora-logos', 'generic-logos', 'system-logos'}:
    raise SystemExit('Desktop-base must not impersonate a logo provider')

archive = evidence / 'sources/deepin-desktop-base-2026.10.28.tar.gz'
manifest = {
    'schema': 1, 'repository': 'Fedora-DDE-Remix/ISO-Build',
    'build_commit': os.environ['iso_ref'],
    'maintainer_repository': 'Fedora-DDE-Remix/Deepin-Desktop-Environment',
    'maintainer_commit': 'adcd681b0b9e68cacbf9daa33bede62a253a3315',
    'upstream_repository': 'linuxdeepin/deepin-desktop-base',
    'upstream_tag': '2026.10.28',
    'upstream_tag_object': 'f918a51224a6767103a3044a7595ff2602ee5826',
    'upstream_commit': '63c52c9387a350df684bb5043dd836d86f862092',
    'name': name, 'version': version, 'release': release, 'base_release': '1.fc45',
    'dependency_change': {'from': 'fedora-logos', 'to': 'system-logos'},
    'source_archive': archive.name, 'source_archive_format': 'git-archive+gzip-n',
    'source_archive_sha256': digest(archive),
    'maintainer_spec_sha256': digest(evidence / 'sources/maintainer/deepin-desktop-base.spec'),
    'spec_sha256': digest(evidence / 'sources/deepin-desktop-base.spec'),
    'binary_rpm': binary_info, 'source_rpm': source_info,
    'requirements': requirements, 'provides': provides,
    'build_success': True,
}
shutil.copy2(binary, Path('/work/rpms') / binary.name)
shutil.copy2(source, Path('/output/rpms') / source.name)
rendered = json.dumps(manifest, indent=2) + '\n'
for destination in (Path('/work/desktop-base-hotfix-input.json'),
                    Path('/output/desktop-base-hotfix-input.json'),
                    evidence / 'desktop-base-hotfix-input.json'):
    destination.write_text(rendered)
with (evidence / 'SHA256SUMS').open('w') as output:
    for path in sorted(evidence.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            relative = path.relative_to(evidence).as_posix()
            if ':' in relative:
                raise SystemExit('Colon in desktop-base evidence filename')
            output.write(f'{digest(path)}  {relative}\n')
print(f'Verified temporary {binary_info["nevra"]} and matching SRPM.')
PY
