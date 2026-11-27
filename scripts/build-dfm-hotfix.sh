#!/usr/bin/bash
# Temporary complete DFM rebuild. Run only in a disposable Fedora 45 container.
set -euo pipefail
umask 022

dfm_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dfm_repo_dir=$(cd -- "$dfm_script_dir/.." && pwd)
dfm_packaging_dir="$dfm_repo_dir/packaging/hotfix/dde-file-manager"
dfm_output_dir=${1:-artifacts/dfm-hotfix}
mkdir -p "$dfm_output_dir"
dfm_output_dir=$(cd -- "$dfm_output_dir" && pwd)
dfm_work_dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/dfm-hotfix.XXXXXX")
dfm_top_dir="$dfm_work_dir/rpmbuild"
dfm_upstream_commit=bdd0f409316054d136eeb8eb7a132a977e4915f7
dfm_maintainer_commit=adcd681b0b9e68cacbf9daa33bede62a253a3315
dfm_source_name="dde-file-manager-$dfm_upstream_commit.tar.gz"
dfm_stage=initializing
mkdir -p "$dfm_output_dir"/{logs,sources,provenance,symbols,probe,rpms,srpms}

dfm_finish() {
    local dfm_status=$?
    trap - EXIT
    python3 - "$dfm_output_dir" "$dfm_status" "$dfm_stage" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root, status, stage = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def packages(directory):
    result = []
    for path in sorted((root / directory).rglob('*.rpm')):
        if ':' in path.name:
            raise SystemExit('Colon in artifact filename: ' + str(path))
        fields = subprocess.check_output(['rpm', '-qp', '--qf',
            '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n', str(path)], text=True).strip().split('\t')
        name, epoch, version, release, arch, source_rpm = fields
        result.append({'path': path.relative_to(root).as_posix(), 'name': name,
            'nevra': f'{name}-{epoch}:{version}-{release}.{arch}', 'epoch': int(epoch),
            'version': version, 'release': release, 'arch': arch, 'source_rpm': source_rpm,
            'sha256': digest(path)})
    return result

validation = root / 'provenance/validation.json'
manifest = {
    'schema': 1, 'repository': os.environ.get('GITHUB_REPOSITORY', 'Fedora-DDE-Remix/ISO-Build'),
    'build_commit': os.environ.get('GITHUB_SHA'), 'build_ref': os.environ.get('GITHUB_REF'),
    'run_id': int(os.environ['GITHUB_RUN_ID']) if os.environ.get('GITHUB_RUN_ID') else None,
    'run_attempt': int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')),
    'maintainer_repository': 'Fedora-DDE-Remix/Deepin-Desktop-Environment',
    'maintainer_commit': 'adcd681b0b9e68cacbf9daa33bede62a253a3315',
    'upstream_repository': 'linuxdeepin/dde-file-manager',
    'upstream_commit': 'bdd0f409316054d136eeb8eb7a132a977e4915f7',
    'patch_sha256': digest(root / 'sources/0001-dpf-centralize-event-converter.patch')
                    if (root / 'sources/0001-dpf-centralize-event-converter.patch').is_file() else None,
    'version': '6.6.7', 'release': '9.1.remix1.fc45',
    'build_success': status == 0, 'exit_status': status, 'last_stage': stage,
    'patches': [{'path': p.relative_to(root).as_posix(), 'sha256': digest(p)}
                for p in sorted((root / 'sources').glob('*.patch'))],
    'source_archives': [{'path': p.relative_to(root).as_posix(), 'sha256': digest(p)}
                       for p in sorted((root / 'sources').glob('*.tar.gz'))],
    'rpms': packages('rpms'), 'srpms': packages('srpms'),
    'validation': json.loads(validation.read_text()) if validation.is_file() else {'passed': False},
}
(root / 'hotfix-input.json').write_text(json.dumps(manifest, indent=2) + '\n')
with (root / 'SHA256SUMS').open('w') as output:
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            relative = path.relative_to(root)
            if any(':' in part for part in relative.parts):
                raise SystemExit('Colon in artifact filename: ' + str(path))
            output.write(f'{digest(path)}  {relative.as_posix()}\n')
PY
    exit "$dfm_status"
}
trap dfm_finish EXIT

test "$(id -u)" -eq 0
test "$(rpm --eval '%{fedora}')" = 45
test "$(uname -m)" = x86_64
cp /etc/os-release "$dfm_output_dir/provenance/os-release"
uname -a > "$dfm_output_dir/provenance/uname.txt"
cp "$dfm_packaging_dir"/*.patch "$dfm_packaging_dir/dde-file-manager.spec" \
   "$dfm_packaging_dir/sources.lock.json" "$dfm_packaging_dir/README.md" "$dfm_output_dir/sources/"
cp -a "$dfm_packaging_dir/maintainer" "$dfm_output_dir/sources/"
cp "${BASH_SOURCE[0]}" "$dfm_output_dir/sources/build-dfm-hotfix.sh"
cp "$dfm_repo_dir/.github/workflows/build-dfm-hotfix.yml" "$dfm_output_dir/sources/build-dfm-hotfix.yml"

dfm_stage=verify-pinned-inputs
python3 - "$dfm_packaging_dir" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
lock = json.loads((root / 'sources.lock.json').read_text())
for name, expected in lock['files'].items():
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit('Pinned input changed: ' + name)
PY
# Re-fetch the pinned maintainer files for an independent comparison. A moving
# branch or a changed local copy must not silently become a new build input.
for dfm_file in dde-file-manager.spec 01-fedora-disable-appimage-qt611.patch 02-pc-remove-libappimage.patch; do
    dfm_reference="$dfm_packaging_dir/$dfm_file"
    if [[ $dfm_file == dde-file-manager.spec ]]; then
        dfm_reference="$dfm_packaging_dir/maintainer/$dfm_file"
    fi
    curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
        "https://raw.githubusercontent.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/$dfm_maintainer_commit/dde-file-manager/$dfm_file" \
        --output "$dfm_work_dir/$dfm_file" 2>> "$dfm_output_dir/logs/source-fetch.log"
    cmp "$dfm_reference" "$dfm_work_dir/$dfm_file"
done

mkdir -p "$dfm_top_dir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
git init "$dfm_work_dir/upstream" > "$dfm_output_dir/logs/git-source.log" 2>&1
git -C "$dfm_work_dir/upstream" fetch --depth=1 \
    https://github.com/linuxdeepin/dde-file-manager.git "$dfm_upstream_commit" \
    >> "$dfm_output_dir/logs/git-source.log" 2>&1
test "$(git -C "$dfm_work_dir/upstream" rev-parse FETCH_HEAD)" = "$dfm_upstream_commit"
git -C "$dfm_work_dir/upstream" show --no-patch --format=fuller "$dfm_upstream_commit" \
    > "$dfm_output_dir/provenance/upstream-commit.txt"
git -C "$dfm_work_dir/upstream" ls-tree -r "$dfm_upstream_commit" \
    > "$dfm_output_dir/provenance/upstream-tree.txt"
if grep -q '^160000 ' "$dfm_output_dir/provenance/upstream-tree.txt"; then
    echo 'Unexpected source submodules require an explicit source manifest.' >&2
    exit 1
fi
# Archive the exact Git tree with a deterministic gzip header. This is not the
# GitHub-generated tarball; its own checksum is recorded in the artifact.
git -C "$dfm_work_dir/upstream" archive --format=tar \
    --prefix="dde-file-manager-$dfm_upstream_commit/" "$dfm_upstream_commit" \
    | gzip -n > "$dfm_top_dir/SOURCES/$dfm_source_name"
git -C "$dfm_work_dir/upstream" show "$dfm_upstream_commit:LICENSE" \
    > "$dfm_output_dir/sources/UPSTREAM-LICENSE"
cp "$dfm_top_dir/SOURCES/$dfm_source_name" "$dfm_output_dir/sources/"
cp "$dfm_packaging_dir"/*.patch "$dfm_top_dir/SOURCES/"
cp "$dfm_packaging_dir/dde-file-manager.spec" "$dfm_top_dir/SPECS/"

dfm_stage=build-dependencies
dnf -y copr enable mozixun/Fedora-DDE-Remix fedora-45-x86_64 \
    2>&1 | tee "$dfm_output_dir/logs/copr-enable.log"
cat /etc/yum.repos.d/*copr*.repo > "$dfm_output_dir/provenance/copr.repo"
dnf -y --refresh builddep --spec "$dfm_top_dir/SPECS/dde-file-manager.spec" \
    2>&1 | tee "$dfm_output_dir/logs/builddep.log"
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' \
    | LC_ALL=C sort > "$dfm_output_dir/provenance/build-packages.txt"
rpm --eval '%{optflags}' > "$dfm_output_dir/provenance/rpm-optflags.txt"
rpm --eval '%{build_ldflags}' > "$dfm_output_dir/provenance/rpm-ldflags.txt"
rpm --showrc > "$dfm_output_dir/provenance/rpm-macros.txt"
rpmspec --parse "$dfm_top_dir/SPECS/dde-file-manager.spec" > "$dfm_output_dir/provenance/expanded.spec"
python3 - <<'PY'
import rpm
assert rpm.labelCompare(('0', '6.6.7', '9.fc45'), ('0', '6.6.7', '9.1.remix1.fc45')) < 0
assert rpm.labelCompare(('0', '6.6.7', '9.1.remix1.fc45'), ('0', '6.6.7', '10.fc45')) < 0
PY

dfm_stage=rpmbuild
# Compile as a dedicated unprivileged user. Only concurrency is bounded; Fedora
# optimization, hardening, LTO and upstream CMake flags remain unchanged.
useradd --system --create-home --home-dir "$dfm_work_dir/builder-home" --shell /bin/bash dfm-hotfix-builder
chown -R dfm-hotfix-builder:dfm-hotfix-builder "$dfm_work_dir"
runuser -u dfm-hotfix-builder -- rpmbuild -ba \
    --define "_topdir $dfm_top_dir" --define '_smp_build_ncpus 2' --define '_smp_mflags -j2' \
    "$dfm_top_dir/SPECS/dde-file-manager.spec" 2>&1 | tee "$dfm_output_dir/logs/rpmbuild.log"
cp -a "$dfm_top_dir/RPMS/." "$dfm_output_dir/rpms/"
cp -a "$dfm_top_dir/SRPMS/." "$dfm_output_dir/srpms/"

dfm_stage=install-complete-package
python3 - "$dfm_output_dir" <<'PY'
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
required = {'dde-file-manager', 'dde-file-manager-libs', 'dde-file-manager-desktop',
            'dde-file-manager-services-plugins', 'dde-file-manager-devel'}
selected = {}
for path in sorted((root / 'rpms').rglob('*.rpm')):
    name, version, release, arch = subprocess.check_output(
        ['rpm', '-qp', '--qf', '%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}', str(path)], text=True).split('\t')
    if version != '6.6.7' or release != '9.1.remix1.fc45':
        raise SystemExit('Unexpected version/release in build output: ' + str(path))
    if name in required:
        if arch != 'x86_64' or name in selected:
            raise SystemExit('Unexpected or duplicate package architecture: ' + str(path))
        selected[name] = str(path)
if set(selected) != required or len(list((root / 'srpms').glob('*.src.rpm'))) != 1:
    raise SystemExit('The complete DFM package or its source RPM is missing')
(root / 'provenance/install-rpms.txt').write_text('\n'.join(selected[name] for name in sorted(required)) + '\n')
PY
mapfile -t dfm_install_rpms < "$dfm_output_dir/provenance/install-rpms.txt"
dnf -y install "${dfm_install_rpms[@]}" 2>&1 | tee "$dfm_output_dir/logs/install-built-rpms.log"
rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n' \
    dde-file-manager dde-file-manager-libs dde-file-manager-desktop \
    dde-file-manager-services-plugins dde-file-manager-devel \
    > "$dfm_output_dir/provenance/installed-hotfix-packages.txt"
python3 - "$dfm_output_dir" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
source = next((root / 'srpms').glob('*.src.rpm')).name
rows = [line.split('\t') for line in (root / 'provenance/installed-hotfix-packages.txt').read_text().splitlines()]
if len(rows) != 5 or any(row[1:] != ['0:6.6.7-9.1.remix1.fc45', 'x86_64', source] for row in rows):
    raise SystemExit('Installed DFM packages differ from this complete hotfix build')
PY

dfm_stage=verify-shared-symbol
dfm_libraries=(/usr/lib64/libdfm6-framework.so.1 \
    /usr/lib64/dde-file-manager/plugins/desktop-core/libdd-core-plugin.so \
    /usr/lib64/dde-shell/org.deepin.ds.desktop.so)
for dfm_library in "${dfm_libraries[@]}"; do
    dfm_library_name=$(basename -- "$dfm_library")
    rpm -qf "$dfm_library" > "$dfm_output_dir/symbols/$dfm_library_name.rpm-owner.txt"
    sha256sum "$dfm_library" > "$dfm_output_dir/symbols/$dfm_library_name.sha256"
    readelf --wide --dyn-syms "$dfm_library" > "$dfm_output_dir/symbols/$dfm_library_name.dynsym.txt"
done
python3 - "$dfm_output_dir/symbols" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
symbol = '_ZN3dpf14EventConverter11convertFuncE'
for name, defined in [('libdfm6-framework.so.1', True), ('libdd-core-plugin.so', False),
                      ('org.deepin.ds.desktop.so', False)]:
    rows = [line.split() for line in (root / (name + '.dynsym.txt')).read_text().splitlines()
            if line.split() and line.split()[-1] == symbol]
    if len(rows) != 1 or rows[0][3] != 'OBJECT' or rows[0][4] != 'GLOBAL' or (rows[0][6] != 'UND') != defined:
        raise SystemExit('Unexpected event converter ownership in ' + name)
PY

dfm_stage=nested-qt-probe
cp "$dfm_repo_dir/scripts/diagnose-dpf/"{CMakeLists.txt,host.cpp,outer.cpp,inner.cpp} "$dfm_output_dir/probe/"
dfm_probe_flags="$(rpm --eval '%{optflags}') -g -Wall -Wl,--as-needed -fstack-protector-all -Werror=return-type -Wl,-z,relro -Wl,-z,now -Ofast"
dfm_probe_linker_flags=$(rpm --eval '%{build_ldflags}')
printf '%s\n' "$dfm_probe_flags" > "$dfm_output_dir/probe/cxx-flags.txt"
printf '%s\n' "$dfm_probe_linker_flags" > "$dfm_output_dir/probe/linker-flags.txt"
cmake -S "$dfm_repo_dir/scripts/diagnose-dpf" -B "$dfm_work_dir/probe-build" -GNinja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DCMAKE_CXX_FLAGS_RELEASE:STRING=-DNDEBUG -DCMAKE_CXX_FLAGS:STRING="$dfm_probe_flags" \
    -DCMAKE_MODULE_LINKER_FLAGS:STRING="$dfm_probe_linker_flags" \
    -DCMAKE_EXE_LINKER_FLAGS:STRING="$dfm_probe_linker_flags" \
    2>&1 | tee "$dfm_output_dir/logs/probe-configure.log"
cmake --build "$dfm_work_dir/probe-build" --parallel 2 --verbose \
    2>&1 | tee "$dfm_output_dir/logs/probe-build.log"
cp "$dfm_work_dir/probe-build/compile_commands.json" "$dfm_output_dir/probe/"
ctest --test-dir "$dfm_work_dir/probe-build" --output-on-failure -V \
    2>&1 | tee "$dfm_output_dir/logs/probe-test.log"
for dfm_plugin in outer inner; do
    readelf --wide --dyn-syms "$dfm_work_dir/probe-build/dpf-probe-$dfm_plugin.so" \
        > "$dfm_output_dir/probe/$dfm_plugin.dynsym.txt"
done
printf '%s\n' '{"passed":true,"complete_rpms_installed":true,"single_framework_definition":true,"nested_qt_probe_passed":true,"desktop_vm_verified":false}' \
    > "$dfm_output_dir/provenance/validation.json"
dfm_stage=complete
