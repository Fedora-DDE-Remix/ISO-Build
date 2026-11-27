#!/usr/bin/python3
"""Verify an immutable complete RPM build and record a separate validation run."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile


SOURCE_ARTIFACT = {
    'id': 15177359692,
    'sha256': '9854fe0f8539d2b201fddf5d860afc1b7ad39abca371acb902106fe39e73a0a2',
    'size_in_bytes': 333599067,
}
BUILD_COMMIT = 'ab1626ed9504613fcd9190eb48e484401c9d7961'
BUILD_RUN = 45950112995
VERSION, RELEASE = '6.6.7', '9.1.remix1.fc45'
SYMBOL = '_ZN3dpf14EventConverter11convertFuncE'
REQUIRED = {'dde-file-manager', 'dde-file-manager-libs', 'dde-file-manager-desktop',
            'dde-file-manager-services-plugins', 'dde-file-manager-devel'}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def checksums(root):
    with (root / 'SHA256SUMS').open('w') as output:
        for path in sorted(root.rglob('*')):
            if path.is_file() and path != root / 'SHA256SUMS':
                relative = path.relative_to(root)
                require(not any(':' in part for part in relative.parts), 'Colon in artifact filename')
                output.write(f'{digest(path)}  {relative.as_posix()}\n')


def prepare(archive, root):
    require(archive.stat().st_size == SOURCE_ARTIFACT['size_in_bytes']
            and digest(archive) == SOURCE_ARTIFACT['sha256'], 'Source artifact bytes or SHA-256 differ')
    with zipfile.ZipFile(archive) as bundle:
        names = set()
        for item in bundle.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and '..' not in path.parts and not any(
                char in item.filename for char in ('\\', ':', '\n', '\r', '\0')),
                'Unsafe artifact member')
            require(item.filename not in names and not stat.S_ISLNK(item.external_attr >> 16),
                    'Duplicate or linked artifact member')
            require(not path.parts or path.parts[0] != 'validation', 'Source has conflicting validation evidence')
            names.add(item.filename)
            target = root / item.filename
            require(target.resolve().is_relative_to(root.resolve()) and not target.exists(),
                    'Source would overwrite existing validation data')
        bundle.extractall(root)
    verified = set()
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        require(name not in verified and name in names and digest(root / name) == expected,
                'Original artifact file checksum mismatch: ' + name)
        verified.add(name)
    require(verified == {name for name in names if not name.endswith('/') and name != 'SHA256SUMS'},
            'Original checksum inventory is incomplete')
    original = json.loads((root / 'hotfix-input.json').read_text())
    expected = {'schema': 1, 'repository': 'Fedora-DDE-Remix/ISO-Build',
                'build_commit': BUILD_COMMIT, 'run_id': BUILD_RUN, 'run_attempt': 1,
                'build_success': False, 'exit_status': 1, 'last_stage': 'verify-shared-symbol',
                'maintainer_commit': 'adcd681b0b9e68cacbf9daa33bede62a253a3315',
                'upstream_commit': 'bdd0f409316054d136eeb8eb7a132a977e4915f7',
                'patch_sha256': '40b726528a34f41cdcbba4a538e5fc9b08fb3b354f8c340f905ead2c0d3d0381',
                'version': VERSION, 'release': RELEASE}
    require(all(type(original.get(key)) is type(value) and original[key] == value
                for key, value in expected.items()), 'Original build identity or failed stage differs')
    require(len(original['rpms']) == 10 and len(original['srpms']) == 1,
            'Expected all ten binary RPMs and the matching SRPM')
    for item in original['rpms'] + original['srpms'] + original['patches'] + original['source_archives']:
        require(item['path'] in verified and digest(root / item['path']) == item['sha256'],
                'Original manifest does not match preserved files')
    require({item['name'] for item in original['rpms']} >= REQUIRED, 'Incomplete DFM package set')
    shutil.copyfile(root / 'hotfix-input.json', root / 'provenance/original-hotfix-input.json')
    shutil.copyfile(root / 'SHA256SUMS', root / 'provenance/original-SHA256SUMS')
    (root / 'validation/provenance/source-verification.json').write_text(json.dumps({
        'source_artifact': SOURCE_ARTIFACT, 'build_commit': BUILD_COMMIT, 'run_id': BUILD_RUN,
        'original_manifest_sha256': digest(root / 'provenance/original-hotfix-input.json'),
        'verified_original_files': len(verified), 'all_original_checksums_match': True,
    }, indent=2) + '\n')


def inventory(root):
    original = json.loads((root / 'provenance/original-hotfix-input.json').read_text())
    source = Path(original['srpms'][0]['path']).name
    selected = {}
    for record in original['rpms'] + original['srpms']:
        path = root / record['path']
        actual = subprocess.check_output(['rpm', '-qp', '--qf',
            '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{SOURCEPACKAGE}',
            str(path)], text=True).split('\t')
        require(actual[:6] == [record['name'], str(record['epoch']), VERSION, RELEASE,
                              record['arch'], record['source_rpm']], 'RPM header differs from original build')
        if record in original['srpms']:
            require(actual[6] == '1' and record['name'] == 'dde-file-manager', 'Invalid source RPM')
        else:
            require(actual[6] in {'(none)', '0'} and actual[5] == source and actual[4] == 'x86_64',
                    'Binary RPM does not belong to the pinned complete build')
            if record['name'] in REQUIRED:
                require(record['name'] not in selected, 'Duplicate runtime/devel RPM')
                selected[record['name']] = str(path)
    require(set(selected) == REQUIRED, 'Missing runtime/devel RPM')
    (root / 'validation/provenance/install-rpms.txt').write_text(
        '\n'.join(selected[name] for name in sorted(REQUIRED)) + '\n')


def verify_elf(root):
    original = json.loads((root / 'provenance/original-hotfix-input.json').read_text())
    source = Path(original['srpms'][0]['path']).name
    installed = [line.split('\t') for line in (
        root / 'validation/provenance/installed-hotfix-packages.txt').read_text().splitlines()]
    require(len(installed) == 5 and {row[0] for row in installed} == REQUIRED
            and all(row[1:] == [f'0:{VERSION}-{RELEASE}', 'x86_64', source] for row in installed),
            'Validation did not install all five exact packages')
    ownership = {}
    for library, owner, defined in (
        ('libdfm6-framework.so.1', 'dde-file-manager-libs', True),
        ('libdd-core-plugin.so', 'dde-file-manager-desktop', False),
        ('org.deepin.ds.desktop.so', 'dde-file-manager-desktop', False),
    ):
        base = root / 'validation/symbols'
        rows = [line.split() for line in (base / (library + '.dynsym.txt')).read_text().splitlines()
                if line.split() and line.split()[-1] == SYMBOL]
        relocations = (base / (library + '.relocations.txt')).read_text()
        dynamic = (base / (library + '.dynamic.txt')).read_text()
        require((base / (library + '.rpm-owner.txt')).read_text().strip()
                == f'{owner}-{VERSION}-{RELEASE}.x86_64', 'Wrong installed ELF owner')
        require((base / (library + '.sha256')).read_text().split()[0]
                == (root / 'symbols' / (library + '.sha256')).read_text().split()[0],
                'Installed library bytes differ from the original build')
        if library != 'libdfm6-framework.so.1':
            require('[libdfm6-framework.so.1]' in dynamic, 'Plugin lost its framework dependency')
        if library == 'org.deepin.ds.desktop.so' and not rows:
            require(SYMBOL not in relocations, 'Absent callback has a relocation')
            ownership[library] = 'unused'
            continue
        require(len(rows) == 1 and len(rows[0]) == 8 and rows[0][3:6] == ['OBJECT', 'GLOBAL', 'DEFAULT']
                and (rows[0][6] != 'UND') == defined, 'Incorrect shared callback ownership')
        require(SYMBOL in relocations, 'Required callback relocation is missing')
        ownership[library] = 'defined' if defined else 'undefined'
    (root / 'validation/provenance/elf-ownership.json').write_text(json.dumps(ownership, indent=2) + '\n')


def complete(root):
    probe = (root / 'validation/logs/probe-test.log').read_text()
    outer = re.findall(r'outer registry=(\d+) converted=(\d+) callback=1 callback_address=(0x[0-9a-f]+)', probe)
    results = [json.loads(line[line.index('{"callback_address"'):]) for line in probe.splitlines()
               if '{"callback_address"' in line]
    require(len(outer) == 1 and len(results) == 1 and 'host result=0' in probe, 'Ambiguous nested Qt probe')
    result = results[0]
    require(outer[0][0] == outer[0][1] and int(outer[0][0]) > 0
            and result.get('passed') is True and result.get('callback_valid') is True
            and type(result.get('registry_id')) is int and result['registry_id'] > 0
            and result.get('registry_id') == result.get('converted_id')
            and int(result['callback_address'], 16) == int(outer[0][2], 16)
            and result.get('number_connected') is True and result.get('list_connected') is True
            and result.get('number_variant_valid') is True and result.get('number') == 37
            and result.get('list_variant_valid') is True and result.get('list_size') == 2,
            'Nested Qt callback validation failed')
    ownership = json.loads((root / 'validation/provenance/elf-ownership.json').read_text())
    (root / 'validation/provenance/validation.json').write_text(json.dumps({
        'passed': True, 'complete_rpms_installed': True, 'single_framework_definition': True,
        'nested_qt_probe_passed': True, 'desktop_vm_verified': False,
        'desktop_callback': ownership['org.deepin.ds.desktop.so'],
    }, indent=2) + '\n')


def finalize(root, status, stage):
    original = root / 'provenance/original-hotfix-input.json'
    if not original.is_file():
        (root / 'validation-error.json').write_text(json.dumps({'exit_status': status, 'stage': stage}) + '\n')
        checksums(root)
        return
    manifest = json.loads(original.read_text())
    path = root / 'validation/provenance/validation.json'
    validation = json.loads(path.read_text()) if path.is_file() else {'passed': False}
    require(status != 0 or validation.get('passed') is True, 'Successful validation requires actual probe evidence')
    manifest.update(schema=2, validation_commit=os.environ.get('GITHUB_SHA'),
                    validation_ref=os.environ.get('GITHUB_REF'),
                    validation_run_id=int(os.environ['GITHUB_RUN_ID']),
                    validation_run_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')),
                    validation_success=status == 0, validation_exit_status=status,
                    validation_last_stage=stage, source_artifact=SOURCE_ARTIFACT, validation=validation)
    (root / 'hotfix-input.json').write_text(json.dumps(manifest, indent=2) + '\n')
    checksums(root)


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'prepare':
        prepare(Path(sys.argv[2]), Path(sys.argv[3]))
    elif command == 'finalize':
        finalize(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    elif command in {'inventory', 'verify-elf', 'complete', 'checksums'}:
        {'inventory': inventory, 'verify-elf': verify_elf, 'complete': complete,
         'checksums': checksums}[command](Path(sys.argv[2]))
    else:
        raise SystemExit('Unknown validation stage')
