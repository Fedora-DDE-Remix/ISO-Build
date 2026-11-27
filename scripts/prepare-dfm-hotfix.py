#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the pinned, fully rebuilt DFM RPMs into the disposable ISO builder."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

LOCK = Path('/workspace/config/dfm-hotfix-input.json')
ARCHIVE = Path('/dfm-hotfix-input.zip')
WORK = Path('/work')
OUTPUT = Path('/output')
RUNTIME = ('dde-file-manager', 'dde-file-manager-desktop',
           'dde-file-manager-libs', 'dde-file-manager-services-plugins')
BUILT = {*RUNTIME, 'dde-file-manager-devel'}
VERSION, RELEASE = '6.6.7', '9.1.remix1.fc45'
SYMBOL = '_ZN3dpf14EventConverter11convertFuncE'
PATCH = '0001-dpf-centralize-event-converter.patch'
LOCK_FIELDS = {'schema', 'repository', 'build_commit', 'run_id', 'artifact_id',
               'sha256', 'maintainer_commit', 'upstream_commit', 'patch_sha256',
               'version', 'release'}
REVALIDATION_FIELDS = {'validation_commit', 'validation_run_id', 'source_artifact'}
ORIGINAL_BUILD_FIELDS = {'schema', 'repository', 'build_commit', 'build_ref', 'run_id', 'run_attempt',
    'maintainer_repository', 'maintainer_commit', 'upstream_repository', 'upstream_commit',
    'patch_sha256', 'version', 'release', 'build_success', 'exit_status', 'last_stage',
    'patches', 'source_archives', 'rpms', 'srpms', 'validation'}
MIB = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON field: ' + key)
        result[key] = value
    return result


def parse_json(data):
    return json.loads(data, object_pairs_hook=unique_object)


def hex_string(value, length):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{%d}' % length, value)


def plain_file(path, limit):
    require(path.resolve(strict=True) == path, 'Input path contains a symlink: ' + str(path))
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit,
            'Input is not a bounded regular file: ' + str(path))


def readonly_archive(path):
    require(os.statvfs(path).f_flag & os.ST_RDONLY,
            '/dfm-hotfix-input.zip must be mounted read-only')


def relative_name(name):
    require(isinstance(name, str) and 0 < len(name) <= 512
            and re.fullmatch(r'[A-Za-z0-9_./+\-]+', name), 'Invalid artifact path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name
            and all(part not in {'.', '..'} for part in path.parts),
            'Artifact path is not an ordinary relative path: ' + name)
    return name


class Artifact:
    """Inspect every ZIP entry; stream only the selected RPMs and source archive."""

    def __init__(self, stream):
        self.zip = zipfile.ZipFile(stream)
        entries = self.zip.infolist()
        require(len(entries) <= 8192, 'Too many artifact members')
        require(sum(item.file_size for item in entries) <= 4096 * MIB,
                'Artifact expanded size exceeds 4 GiB')
        self.files, self.proof, seen = {}, {}, set()
        for item in entries:
            name = relative_name(item.filename[:-1] if item.is_dir() else item.filename)
            require(name not in seen, 'Duplicate ZIP path: ' + name)
            seen.add(name)
            kind = stat.S_IFMT(item.external_attr >> 16)
            expected_kind = stat.S_IFDIR if item.is_dir() else stat.S_IFREG
            require(kind in {0, expected_kind} and not item.flag_bits & 1,
                    'Nonregular or encrypted ZIP entry: ' + name)
            require(item.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    and item.file_size <= 2048 * MIB, 'Unsupported ZIP entry: ' + name)
            if not item.is_dir():
                self.files[name] = item
        for name in self.files:
            require(not any(str(parent) in self.files for parent in PurePosixPath(name).parents),
                    'ZIP file/directory collision: ' + name)
        sums = self.raw('SHA256SUMS', 4 * MIB)
        self.proof['SHA256SUMS'] = sums
        self.sums = {}
        for line in sums.decode('utf-8').splitlines():
            digest, separator, name = line.partition('  ')
            require(separator and hex_string(digest, 64), 'Malformed artifact SHA256SUMS')
            relative_name(name)
            require(name not in self.sums, 'Duplicate checksum path: ' + name)
            self.sums[name] = digest
        require(set(self.sums) == set(self.files) - {'SHA256SUMS'},
                'Artifact checksum inventory does not match ZIP files')

    def raw(self, name, limit):
        require(name in self.files and self.files[name].file_size <= limit,
                'Missing or oversized artifact evidence: ' + name)
        return self.zip.read(self.files[name])

    def read(self, name, limit=2 * MIB):
        data = self.raw(name, limit)
        require(hashlib.sha256(data).hexdigest() == self.sums.get(name),
                'Artifact evidence checksum mismatch: ' + name)
        self.proof[name] = data
        return data

    def json(self, name):
        return parse_json(self.read(name))

    def stream(self, name, digest, destination=None):
        require(name in self.files and self.files[name].file_size <= 1024 * MIB
                and digest == self.sums.get(name) and hex_string(digest, 64),
                'Invalid selected artifact file: ' + name)
        output = destination.open('xb') if destination else None
        actual = hashlib.sha256()
        try:
            with self.zip.open(self.files[name]) as source:
                while chunk := source.read(MIB):
                    actual.update(chunk)
                    if output:
                        output.write(chunk)
        finally:
            if output:
                output.close()
        require(actual.hexdigest() == digest, 'Checksum mismatch: ' + name)


def read_lock():
    plain_file(LOCK, 16384)
    value = parse_json(LOCK.read_bytes())
    require(isinstance(value, dict) and type(value.get('schema')) is int
            and value['schema'] in {1, 2}, 'Invalid hotfix lock schema')
    fields = LOCK_FIELDS | (REVALIDATION_FIELDS if value['schema'] == 2 else set())
    require(set(value) == fields, 'Invalid hotfix lock fields')
    require(value['repository'] == 'Fedora-DDE-Remix/ISO-Build', 'Invalid lock repository')
    for key in ('run_id', 'artifact_id'):
        require(type(value[key]) is int and value[key] > 0, 'Invalid lock ' + key)
    for key in ('build_commit', 'maintainer_commit', 'upstream_commit'):
        require(hex_string(value[key], 40), 'Invalid lock ' + key)
    for key in ('sha256', 'patch_sha256'):
        require(hex_string(value[key], 64), 'Invalid lock ' + key)
    if value['schema'] == 2:
        require(hex_string(value['validation_commit'], 40)
                and type(value['validation_run_id']) is int and value['validation_run_id'] > 0,
                'Invalid independent validation identity')
        source = value['source_artifact']
        require(isinstance(source, dict) and set(source) == {'id', 'sha256', 'size_in_bytes'}
                and type(source['id']) is int and source['id'] > 0
                and type(source['size_in_bytes']) is int and 0 < source['size_in_bytes'] <= 2048 * MIB
                and hex_string(source['sha256'], 64), 'Invalid original build artifact identity')
    require(value['version'] == VERSION and value['release'] == RELEASE,
            'This importer accepts only the reviewed DFM 6.6.7-9.1.remix1.fc45 rebuild')
    return value


def validate_evidence(artifact, manifest, lock, source_name):
    require(isinstance(manifest, dict), 'Invalid build provenance object')
    for key in set(lock) - {'artifact_id', 'sha256'}:
        require(type(manifest.get(key)) is type(lock[key]) and manifest[key] == lock[key],
                'Build provenance differs from the approved lock: ' + key)
    if lock['schema'] == 1:
        require(manifest.get('build_success') is True and type(manifest.get('exit_status')) is int
                and manifest['exit_status'] == 0 and manifest.get('last_stage') == 'complete',
                'The complete hotfix build did not succeed')
    else:
        # Revalidation never rewrites the original failed job as successful.
        # Its only accepted starting point is a completed RPM build/install
        # that stopped at the old, overly strict unused-desktop-symbol check.
        original = artifact.json('provenance/original-hotfix-input.json')
        require(isinstance(original, dict) and set(original) == ORIGINAL_BUILD_FIELDS
                and type(original.get('schema')) is int
                and original['schema'] == 1 and original.get('build_success') is False
                and type(original.get('exit_status')) is int and original['exit_status'] == 1
                and original.get('last_stage') == 'verify-shared-symbol'
                and original.get('validation') == {'passed': False},
                'Original build did not stop at the reviewed ELF validation condition')
        require(all(type(manifest.get(key)) is type(value) and manifest[key] == value
                    for key, value in original.items()
                    if key not in {'schema', 'validation'}),
                'Revalidation altered original build identity, RPMs or source provenance')
        require(manifest.get('validation_success') is True
                and type(manifest.get('validation_exit_status')) is int
                and manifest['validation_exit_status'] == 0
                and manifest.get('validation_last_stage') == 'complete'
                and type(manifest.get('validation_run_attempt')) is int
                and manifest['validation_run_attempt'] > 0,
                'The independent complete-package validation did not succeed')
    require(manifest.get('maintainer_repository') == 'Fedora-DDE-Remix/Deepin-Desktop-Environment'
            and manifest.get('upstream_repository') == 'linuxdeepin/dde-file-manager',
            'Unexpected source repositories')
    evidence = 'validation/' if lock['schema'] == 2 else ''
    validation = artifact.json(evidence + 'provenance/validation.json')
    require(isinstance(validation, dict) and validation == manifest.get('validation'),
            'Conflicting validation records')
    require(all(validation.get(key) is True for key in (
        'passed', 'complete_rpms_installed', 'single_framework_definition', 'nested_qt_probe_passed')),
        'Complete installed-RPM and ELF/probe validation is required; header-only A/B is insufficient')
    installed = [line.split('\t') for line in artifact.read(
        evidence + 'provenance/installed-hotfix-packages.txt').decode().splitlines()]
    require(len(installed) == 5 and {row[0] for row in installed if row} == BUILT
            and all(row[1:] == [f'0:{VERSION}-{RELEASE}', 'x86_64', source_name] for row in installed),
            'Installed-package evidence does not identify all five rebuilt packages')
    for library, owner, defined in (
        ('libdfm6-framework.so.1', 'dde-file-manager-libs', True),
        ('libdd-core-plugin.so', 'dde-file-manager-desktop', False),
        ('org.deepin.ds.desktop.so', 'dde-file-manager-desktop', False),
    ):
        rows = [line.split() for line in artifact.read(evidence + f'symbols/{library}.dynsym.txt').decode().splitlines()
                if line.split() and line.split()[-1] == SYMBOL]
        # The top-level desktop module only loads the DPF LifeCycle. It does
        # not call EventConverter, so the fixed header may leave no dynamic
        # reference at all. The real core consumer must still import the
        # framework's object; no plugin may define its own copy.
        unused_desktop = library == 'org.deepin.ds.desktop.so' and not rows
        require(unused_desktop or (len(rows) == 1 and len(rows[0]) == 8
                and rows[0][3:6] == ['OBJECT', 'GLOBAL', 'DEFAULT']
                and (rows[0][6] != 'UND') == defined), 'Wrong callback ownership in ' + library)
        require(artifact.read(evidence + f'symbols/{library}.rpm-owner.txt').decode().strip()
                == f'{owner}-{VERSION}-{RELEASE}.x86_64', 'ELF evidence is from another RPM: ' + library)
        if lock['schema'] == 2:
            dynamic = artifact.read(evidence + f'symbols/{library}.dynamic.txt').decode()
            relocations = artifact.read(evidence + f'symbols/{library}.relocations.txt').decode()
            if not defined:
                require(re.search(r'\(NEEDED\).*\[libdfm6-framework\.so\.1\]', dynamic),
                        'Plugin does not declare the shared framework dependency: ' + library)
                require((SYMBOL in relocations) == bool(rows),
                        'Callback relocation differs from its dynamic-symbol reference: ' + library)
    probe = artifact.read(evidence + 'logs/probe-test.log').decode()
    outer = re.findall(r'outer registry=(\d+) converted=(\d+) callback=1 callback_address=(0x[0-9a-f]+)', probe)
    results = [parse_json(line[line.index('{"callback_address"'):]) for line in probe.splitlines()
               if '{"callback_address"' in line]
    require(len(outer) == 1 and len(results) == 1 and 'host result=0' in probe,
            'Missing unambiguous full-RPM nested Qt probe evidence')
    result = results[0]
    require(outer[0][0] == outer[0][1] and int(outer[0][0]) > 0
            and result.get('passed') is True and result.get('callback_valid') is True
            and type(result.get('registry_id')) is int and result['registry_id'] > 0
            and result.get('converted_id') == result['registry_id']
            and int(result['callback_address'], 16) == int(outer[0][2], 16)
            and result.get('number_connected') is True and result.get('list_connected') is True
            and result.get('number_variant_valid') is True and result.get('number') == 37
            and result.get('list_variant_valid') is True and result.get('list_size') == 2,
            'The installed-RPM nested Qt probe failed')
    sources = artifact.json('sources/sources.lock.json')
    require(isinstance(sources, dict) and sources.get('schema') == 1
            and all(sources.get(key) == manifest[key] for key in (
                'maintainer_repository', 'maintainer_commit', 'upstream_repository', 'upstream_commit')),
            'Source lock differs from build provenance')
    source_files = {'dde-file-manager.spec', 'maintainer/dde-file-manager.spec', 'maintainer/LICENSE',
                    '01-fedora-disable-appimage-qt611.patch', '02-pc-remove-libappimage.patch', PATCH}
    require(isinstance(sources.get('files'), dict) and set(sources['files']) == source_files,
            'Unexpected pinned source-file inventory')
    for name, digest in sources['files'].items():
        require(hex_string(digest, 64) and hashlib.sha256(artifact.read('sources/' + name)).hexdigest() == digest,
                'Pinned source checksum mismatch: ' + name)
    require(sources['files'][PATCH] == lock['patch_sha256'], 'The source patch differs from the approved patch')
    patches = manifest.get('patches')
    require(isinstance(patches, list) and len(patches) == 3
            and {item['path']: item['sha256'] for item in patches} == {
                'sources/' + name: sources['files'][name] for name in source_files if name.endswith('.patch')},
            'Unexpected patch provenance')
    archives = manifest.get('source_archives')
    require(isinstance(archives, list) and len(archives) == 1
            and archives[0]['path'] == f"sources/dde-file-manager-{lock['upstream_commit']}.tar.gz",
            'Expected one source archive from the pinned upstream commit')
    artifact.stream(archives[0]['path'], archives[0]['sha256'])
    artifact.read('sources/UPSTREAM-LICENSE')
    return validation, archives[0]


def rpm_query(path):
    # Query only; no installation, scriptlets, macro expressions or shell input.
    result = subprocess.run(['/usr/bin/rpm', '-qp', '--qf',
        '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCEPACKAGE}\t%{SOURCERPM}\n',
        '--', str(path)], check=False, capture_output=True, text=True, timeout=30,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'})
    require(result.returncode == 0, f'RPM metadata query failed for {path.name}: {result.stderr.strip()}')
    fields = result.stdout.rstrip('\n').split('\t')
    require(len(fields) == 7, 'Malformed RPM metadata: ' + path.name)
    return fields


def verify_rpm(artifact, record, stage, source_name, source=False):
    name, arch = record['name'], record['arch']
    require(name == 'dde-file-manager' if source else name in RUNTIME, 'Unexpected selected RPM name')
    suffix = 'src' if source else 'x86_64'
    filename = f'{name}-{VERSION}-{RELEASE}.{suffix}.rpm'
    expected_path = ('srpms/' if source else 'rpms/x86_64/') + filename
    require(record['path'] == expected_path and record['version'] == VERSION
            and record['release'] == RELEASE and type(record['epoch']) is int and record['epoch'] == 0
            and record['nevra'] == f'{name}-0:{VERSION}-{RELEASE}.{arch}', 'Unexpected RPM manifest identity')
    destination = stage / filename
    artifact.stream(expected_path, record['sha256'], destination)
    actual = rpm_query(destination)
    require(actual[:5] == [name, '0', VERSION, RELEASE, arch]
            and actual[6] == record['source_rpm'], 'RPM header differs from its manifest: ' + filename)
    if source:
        require(name == 'dde-file-manager' and actual[5] == '1' and arch in {'src', 'noarch', 'x86_64'},
                'Expected the matching source RPM, identified by SOURCEPACKAGE')
    else:
        require(name in RUNTIME and arch == 'x86_64' and actual[5] in {'(none)', '0'}
                and actual[6] == source_name, 'Runtime RPM does not identify the matching SRPM')
    return {key: record[key] for key in ('name', 'version', 'release', 'arch', 'epoch', 'sha256', 'source_rpm')} | {
        'filename': filename, 'nevra': record['nevra']}


def directory(path):
    if not path.exists():
        path.mkdir(mode=0o755)
    require(path.resolve(strict=True) == path and stat.S_ISDIR(path.lstat().st_mode),
            'Output path must be a real directory: ' + str(path))


def copy_new(source, destination):
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, MIB)
    destination.chmod(0o644)


def prepare():
    lock = read_lock()
    plain_file(ARCHIVE, 2048 * MIB)
    readonly_archive(ARCHIVE)
    directory(WORK)
    directory(OUTPUT)
    with ARCHIVE.open('rb') as stream, tempfile.TemporaryDirectory(prefix='dfm-hotfix-', dir=WORK) as temporary:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == lock['sha256'], 'Pinned ZIP SHA256 mismatch')
        stream.seek(0)
        artifact = Artifact(stream)
        manifest = artifact.json('hotfix-input.json')
        source_name = f'dde-file-manager-{VERSION}-{RELEASE}.src.rpm'
        validation, source_archive = validate_evidence(artifact, manifest, lock, source_name)
        rpms, srpms = manifest.get('rpms'), manifest.get('srpms')
        require(isinstance(rpms, list) and len(rpms) <= 32 and isinstance(srpms, list) and len(srpms) == 1,
                'Invalid complete-build RPM inventory')
        allowed = BUILT | {name + '-debuginfo' for name in BUILT} | {'dde-file-manager-debugsource'}
        by_name = {}
        for record in rpms:
            name = record['name']
            require(name in allowed and name not in by_name and record['arch'] == 'x86_64'
                    and record['source_rpm'] == source_name and record['version'] == VERSION
                    and record['release'] == RELEASE and type(record['epoch']) is int and record['epoch'] == 0
                    and record['nevra'] == f'{name}-0:{VERSION}-{RELEASE}.x86_64'
                    and record['path'] == f'rpms/x86_64/{name}-{VERSION}-{RELEASE}.x86_64.rpm'
                    and hex_string(record['sha256'], 64)
                    and record['sha256'] == artifact.sums.get(record['path']), 'Unexpected or duplicate built RPM')
            by_name[name] = record
        require(BUILT <= set(by_name), 'One of the five complete-build packages is missing')
        stage = Path(temporary)
        runtime = [verify_rpm(artifact, by_name[name], stage, source_name) for name in RUNTIME]
        source = verify_rpm(artifact, srpms[0], stage, source_name, source=True)
        metadata = {**lock, 'mode': 'temporary-unsigned-ci-rpms',
            'authentication': 'pinned GitHub Actions artifact SHA256; no COPR signature claim',
            'base_version': VERSION, 'base_release': '9.fc45', 'runtime_rpms': runtime,
            'source_rpm': source, 'source_archive': source_archive, 'validation': validation,
            'provenance_directory': 'rpms/dfm-hotfix-provenance'}
        proof = stage / 'provenance'
        proof.mkdir()
        artifact.proof['approved-input.json'] = (json.dumps(lock, indent=2) + '\n').encode()
        for name, data in artifact.proof.items():
            target = proof / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        report = stage / 'dfm-hotfix-input.json'
        report.write_text(json.dumps(metadata, indent=2) + '\n')
        directory(WORK / 'rpms')
        directory(OUTPUT / 'rpms')
        outputs = [(stage / row['filename'], WORK / 'rpms' / row['filename']) for row in runtime]
        outputs += [(stage / source['filename'], OUTPUT / 'rpms' / source['filename']),
                    (report, WORK / 'dfm-hotfix-input.json')]
        proof_target = OUTPUT / 'rpms/dfm-hotfix-provenance'
        require(not proof_target.exists() and not proof_target.is_symlink()
                and all(not target.exists() and not target.is_symlink() for _, target in outputs),
                'Refusing to overwrite existing hotfix outputs')
        for original, target in outputs[:-1]:
            copy_new(original, target)
        shutil.copytree(proof, proof_target)
        copy_new(*outputs[-1])
        artifact.zip.close()
    print(f'Validated and imported four temporary DFM runtime RPMs: {VERSION}-{RELEASE}')
    return metadata


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 1 and os.geteuid() == 0, 'Run as root without arguments in the ISO builder')
        os.umask(0o022)
        prepare()
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(f'DFM hotfix input verification failed: {error}', file=sys.stderr)
        raise SystemExit(1)
