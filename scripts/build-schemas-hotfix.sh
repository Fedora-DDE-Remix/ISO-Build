#!/usr/bin/bash
# Build the pinned schema repair with the real Fedora Go and RPM toolchain.
set -Eeuo pipefail
umask 022

if [[ ${FEDORA_DDE_ISO_BUILD:-} != 1 || ! -f /.dockerenv || $EUID -ne 0 ]]; then
    echo 'Run this helper through the disposable Fedora ISO compose container.' >&2
    exit 2
fi
[[ $(rpm --eval '%{fedora}') == 45 && $(uname -m) == x86_64 ]]
[[ ${iso_ref:-} =~ ^[0-9a-f]{40}$ ]]

schemas_packaging=/workspace/packaging/hotfix/deepin-desktop-schemas
schemas_work_dir=$(mktemp -d /work/schemas-hotfix.XXXXXX)
schemas_top=$schemas_work_dir/rpmbuild
schemas_evidence=/output/rpms/schemas-hotfix-provenance
schemas_upstream_commit=00a92111f8f0cc7bcba8af9ae2a9950c7f02ae4e
schemas_maintainer_commit=adcd681b0b9e68cacbf9daa33bede62a253a3315
schemas_source_name=deepin-desktop-schemas-6.0.13.tar.gz
mkdir -p "$schemas_top"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "$schemas_evidence/sources/maintainer" "$schemas_evidence/logs" /work/rpms /output/rpms /output/logs

python3 - "$schemas_packaging" <<'PY'
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
    'upstream_repository': 'linuxdeepin/deepin-desktop-schemas',
    'upstream_tag': '6.0.13',
    'upstream_tag_object': 'ddeeb4848a07a55f0d843027466b4dcb12e732b6',
    'upstream_commit': '00a92111f8f0cc7bcba8af9ae2a9950c7f02ae4e',
    'version': '6.0.13',
    'base_release': '1.fc45',
    'release': '1.1.remix1.fc45',
}
if any(lock.get(key) != value for key, value in expected.items()):
    raise SystemExit('Unexpected schemas source identity')
names = {'deepin-desktop-schemas.spec', 'maintainer/deepin-desktop-schemas.spec',
         'maintainer/LICENSE', 'README.md', '0001-fix-duplicate-mediakey-metadata.patch'}
if set(lock['files']) != names:
    raise SystemExit('Unexpected schemas source file set')
for name in sorted(names):
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit('Missing regular source input: ' + name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock['files'][name]:
        raise SystemExit('Pinned schemas input changed: ' + name)
original = (root / 'maintainer/deepin-desktop-schemas.spec').read_text()
if original.count('Release:        1%{?dist}\n') != 1 or original.count('Requires:       dconf\n') != 1:
    raise SystemExit('The reviewed maintainer spec has changed')
adapted = original.replace('Release:        1%{?dist}\n',
                           'Release:        1.1.remix1%{?dist}\n')
adapted = adapted.replace('BuildArch:      noarch\n',
                          'Patch0:         0001-fix-duplicate-mediakey-metadata.patch\nBuildArch:      noarch\n')
adapted = adapted.replace('Requires:       dconf\n',
                          'Requires:       dconf\nRequires:       glib2\nRequires:       desktop-backgrounds-basic\n')
adapted = adapted.replace('/usr/share/backgrounds/deepin/desktop.jpg',
                          '/usr/share/backgrounds/images/earth_from_space.jpg')
old_scripts = ('%post\nglib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :\n\n'
               '%postun\nglib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :\n')
if original.count(old_scripts) != 1:
    raise SystemExit('The reviewed schema scriptlets have changed')
adapted = adapted.replace(old_scripts,
    '%check\n'
    '# Validate the complete installed output, including the generated x86 override.\n'
    '# Fedora glib2 file triggers compile/remove the live system cache on transactions.\n'
    'glib-compile-schemas --strict --dry-run %{buildroot}%{_datadir}/glib-2.0/schemas\n')
adapted = adapted.replace('%changelog\n',
    '%changelog\n'
    '* Fri Nov 27 2026 Fedora DDE Remix contributors - 6.0.13-1.1.remix1\n'
    '- Remove duplicate mediakey metadata rejected by strict GLib schema compilation.\n'
    '- Use the Fedora-packaged JPEG background for both appearance schema defaults.\n'
    '- Check all installed schemas and generated overrides during the RPM build.\n'
    '- Use Fedora glib2 schema file triggers instead of ignoring compilation failures.\n\n')
if (root / 'deepin-desktop-schemas.spec').read_text() != adapted:
    raise SystemExit('The schema recipe differs from the reviewed patch, defaults and strict check changes')
if lock['files']['0001-fix-duplicate-mediakey-metadata.patch'] != 'c0e06ede2bfef58227a2dff6cbb2292800b721ef6ac98150cb5fd9323d9ff709':
    raise SystemExit('The reviewed two-line schema repair changed')
PY

# Compare against the immutable maintainer revision, never a moving branch.
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://raw.githubusercontent.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/$schemas_maintainer_commit/deepin-desktop-schemas/deepin-desktop-schemas.spec" \
    --output "$schemas_work_dir/maintainer.spec" 2> "$schemas_evidence/logs/source-fetch.log"
cmp "$schemas_packaging/maintainer/deepin-desktop-schemas.spec" "$schemas_work_dir/maintainer.spec"
cp "$schemas_packaging/deepin-desktop-schemas.spec" "$schemas_packaging/sources.lock.json" \
   "$schemas_packaging/README.md" "$schemas_packaging/0001-fix-duplicate-mediakey-metadata.patch" \
   "$schemas_evidence/sources/"
cp "$schemas_packaging/maintainer/"* "$schemas_evidence/sources/maintainer/"
cp /workspace/scripts/build-schemas-hotfix.sh "$schemas_evidence/sources/"

git init "$schemas_work_dir/upstream" > "$schemas_evidence/logs/git-source.log" 2>&1
git -C "$schemas_work_dir/upstream" fetch --depth=1 \
    https://github.com/linuxdeepin/deepin-desktop-schemas.git "$schemas_upstream_commit" \
    >> "$schemas_evidence/logs/git-source.log" 2>&1
[[ $(git -C "$schemas_work_dir/upstream" rev-parse FETCH_HEAD) == "$schemas_upstream_commit" ]]
git -C "$schemas_work_dir/upstream" checkout --detach "$schemas_upstream_commit" \
    >> "$schemas_evidence/logs/git-source.log" 2>&1
[[ $(git -C "$schemas_work_dir/upstream" rev-parse HEAD) == "$schemas_upstream_commit" ]]
git -C "$schemas_work_dir/upstream" show --no-patch --format=fuller HEAD \
    > "$schemas_evidence/upstream-commit.txt"
git -C "$schemas_work_dir/upstream" ls-tree -r HEAD > "$schemas_evidence/upstream-tree.txt"
python3 - "$schemas_evidence/upstream-tree.txt" <<'PY'
from pathlib import Path
import sys
if any(line.startswith('160000 ') for line in Path(sys.argv[1]).read_text().splitlines()):
    raise SystemExit('Unexpected schemas submodules need a reviewed source manifest')
PY
git -C "$schemas_work_dir/upstream" archive --format=tar \
    --prefix=deepin-desktop-schemas-6.0.13/ HEAD \
    | gzip -n > "$schemas_top/SOURCES/$schemas_source_name"
git -C "$schemas_work_dir/upstream" show HEAD:LICENSE \
    > "$schemas_evidence/sources/UPSTREAM-LICENSE"
cp "$schemas_top/SOURCES/$schemas_source_name" "$schemas_evidence/sources/"
cp "$schemas_packaging/0001-fix-duplicate-mediakey-metadata.patch" "$schemas_top/SOURCES/"
cp "$schemas_packaging/deepin-desktop-schemas.spec" "$schemas_top/SPECS/"

dnf -y builddep "$schemas_top/SPECS/deepin-desktop-schemas.spec" \
    2>&1 | tee /output/logs/schemas-builddep.log "$schemas_evidence/logs/builddep.log"
go version > "$schemas_evidence/go-version.txt"
glib-compile-schemas --version > "$schemas_evidence/glib-version.txt"
rpmspec --parse "$schemas_top/SPECS/deepin-desktop-schemas.spec" \
    > "$schemas_evidence/expanded.spec"
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' \
    | LC_ALL=C sort > "$schemas_evidence/build-packages.txt"
rpmbuild --define "_topdir $schemas_top" -ba "$schemas_top/SPECS/deepin-desktop-schemas.spec" \
    2>&1 | tee /output/logs/schemas-rpmbuild.log "$schemas_evidence/logs/rpmbuild.log"

python3 - "$schemas_top" "$schemas_evidence" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

top, evidence = map(Path, sys.argv[1:])
name = 'deepin-desktop-schemas'
version = '6.0.13'
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
        raise SystemExit('Expected exactly one schemas RPM in ' + str(directory))
    path = paths[0]
    if path.is_symlink() or not path.is_file():
        raise SystemExit('RPM output is not a regular file')
    suffix = 'src' if source else 'noarch'
    if path.name != f'{name}-{version}-{release}.{suffix}.rpm' or ':' in path.name:
        raise SystemExit('Unexpected schemas RPM filename')
    run('rpm', '--checksig', '--nosignature', str(path))
    fields = run('rpm', '-qp', '--qf',
                 '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{SOURCEPACKAGE}\n',
                 str(path)).split('\t')
    if len(fields) != 7 or fields[:4] != [name, '0', version, release]:
        raise SystemExit('Unexpected schemas RPM header identity')
    header_arch, source_rpm, source_flag = fields[4:]
    if source:
        if source_flag != '1' or header_arch not in {'src', 'noarch', 'x86_64'}:
            raise SystemExit('The matching source RPM is missing')
    elif header_arch != 'noarch' or source_flag not in {'0', '(none)'}:
        raise SystemExit('The schemas binary must be noarch')
    return path, {'filename': path.name, 'sha256': digest(path), 'name': name,
                  'epoch': 0, 'version': version, 'release': release,
                  'arch': suffix, 'header_arch': header_arch,
                  'source_rpm': source_rpm,
                  'nevra': f'{name}-0:{version}-{release}.{suffix}'}

binary, binary_info = inspect(top / 'RPMS', False)
source, source_info = inspect(top / 'SRPMS', True)
if binary_info['source_rpm'] != source.name:
    raise SystemExit('Schemas binary does not identify its matching SRPM')
requirements = run('rpm', '-qp', '--qf', '[%{REQUIRENAME}\n]', str(binary)).splitlines()
provides = run('rpm', '-qp', '--qf', '[%{PROVIDENAME}\n]', str(binary)).splitlines()
if not {'glib2', 'desktop-backgrounds-basic', 'dconf', 'deepin-gtk-theme',
        'deepin-icon-theme', 'deepin-sound-theme'} <= set(requirements):
    raise SystemExit('The schemas RPM is missing a required desktop resource dependency')
scriptlets = run('rpm', '-qp', '--scripts', str(binary))
if scriptlets:
    raise SystemExit('The schemas RPM must use Fedora glib2 file triggers without package scriptlets')
(evidence / 'binary-scriptlets.txt').write_text(scriptlets)
(evidence / 'binary-header.json').write_text(json.dumps(binary_info, indent=2) + '\n')
(evidence / 'source-header.json').write_text(json.dumps(source_info, indent=2) + '\n')

archive = evidence / 'sources/deepin-desktop-schemas-6.0.13.tar.gz'
manifest = {
    'schema': 1, 'repository': 'Fedora-DDE-Remix/ISO-Build',
    'build_commit': os.environ['iso_ref'],
    'maintainer_repository': 'Fedora-DDE-Remix/Deepin-Desktop-Environment',
    'maintainer_commit': 'adcd681b0b9e68cacbf9daa33bede62a253a3315',
    'upstream_repository': 'linuxdeepin/deepin-desktop-schemas',
    'upstream_tag': '6.0.13',
    'upstream_tag_object': 'ddeeb4848a07a55f0d843027466b4dcb12e732b6',
    'upstream_commit': '00a92111f8f0cc7bcba8af9ae2a9950c7f02ae4e',
    'name': name, 'version': version, 'release': release, 'base_release': '1.fc45',
    'patch_sha256': digest(evidence / 'sources/0001-fix-duplicate-mediakey-metadata.patch'),
    'wallpaper': '/usr/share/backgrounds/images/earth_from_space.jpg',
    'resource_dependency': 'desktop-backgrounds-basic',
    'schema_cache_trigger_provider': 'glib2',
    'source_archive': archive.name, 'source_archive_format': 'git-archive+gzip-n',
    'source_archive_sha256': digest(archive),
    'maintainer_spec_sha256': digest(evidence / 'sources/maintainer/deepin-desktop-schemas.spec'),
    'spec_sha256': digest(evidence / 'sources/deepin-desktop-schemas.spec'),
    'binary_rpm': binary_info, 'source_rpm': source_info,
    'requirements': requirements, 'provides': provides,
    'strict_schema_check': {'success': True, 'command': 'glib-compile-schemas --strict --dry-run',
                            'scope': 'installed RPM buildroot schemas and Go-generated x86 override',
                            'log': 'logs/rpmbuild.log'},
    'build_success': True,
}
shutil.copy2(binary, Path('/work/rpms') / binary.name)
shutil.copy2(source, Path('/output/rpms') / source.name)
rendered = json.dumps(manifest, indent=2) + '\n'
for destination in (Path('/work/schemas-hotfix-input.json'),
                    Path('/output/schemas-hotfix-input.json'),
                    evidence / 'schemas-hotfix-input.json'):
    destination.write_text(rendered)
with (evidence / 'SHA256SUMS').open('w') as output:
    for path in sorted(evidence.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            relative = path.relative_to(evidence).as_posix()
            if ':' in relative:
                raise SystemExit('Colon in schemas evidence filename')
            output.write(f'{digest(path)}  {relative}\n')
print(f'Verified temporary {binary_info["nevra"]} and matching SRPM.')
PY
