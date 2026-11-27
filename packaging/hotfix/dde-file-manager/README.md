# Temporary complete DFM hotfix build

This recipe rebuilds the complete Fedora DDE Remix `dde-file-manager` package
with one shared DPF event-converter callback. It is a temporary package build
for validation and ISO integration; it does not publish to COPR, modify the
maintainer repository, or replace the installed desktop during an ISO build.

## Pinned inputs

| Input | Revision |
| --- | --- |
| Maintainer specification and original patches | `Fedora-DDE-Remix/Deepin-Desktop-Environment` at `adcd681b0b9e68cacbf9daa33bede62a253a3315` |
| Upstream DFM source | `linuxdeepin/dde-file-manager` at `bdd0f409316054d136eeb8eb7a132a977e4915f7` (`6.6.7`) |
| Temporary package version | `6.6.7-9.1.remix1.fc45` |
| Additional patch | `0001-dpf-centralize-event-converter.patch`, SHA-256 `40b726528a34f41cdcbba4a538e5fc9b08fb3b354f8c340f905ead2c0d3d0381` |

The exact `6.6.7-9` maintainer specification is retained under `maintainer/`.
The original AppImage/Qt compatibility patches, package layout, dependencies,
Fedora compiler settings, LTO, upstream optimization settings and SELinux
behavior remain intact. The hotfix specification changes only the release,
pinned source references, archive directory, new patch and changelog.
The build checks with RPM's own version comparison that
`9.fc45 < 9.1.remix1.fc45 < 10.fc45`, so the maintainer's next ordinary release
can supersede this temporary build.

The new patch removes the header's inline storage definition and defines
`dpf::EventConverter::convertFunc` once in the shared framework. All DFM
subpackages are rebuilt together, including their desktop and core plugins;
replacing only the library would leave consumers built with the old header.

## Run and validation

The workflow is `.github/workflows/build-dfm-hotfix.yml`. Pushes trigger it only
on branches matching `build-dfm-hotfix-*`; manual dispatch is also supported.
The job uses an x86_64 Fedora 45 container, installs build requirements from
the specification, and runs `rpmbuild -ba` as an unprivileged build user.
COPR is used only to read existing dependencies. The compilation parallelism
is limited to two jobs without changing optimization or hardening flags.

The script can also be run as root in a fresh, disposable Fedora 45 container
with the tooling listed in the workflow:

```bash
bash scripts/build-dfm-hotfix.sh artifacts/dfm-hotfix
```

The script verifies the checked-in input hashes and compares the original
specification and both original patches with their pinned maintainer URLs.
It fetches the exact upstream commit, rejects unaccounted-for submodules,
and generates `git archive` plus `gzip -n` from that Git tree. The archive's
checksum is recorded separately; it must not be confused with the checksum
of a GitHub-generated archive of the same tree.

After building all binary and source RPMs, the job installs this build's main,
libs, desktop, services-plugins and devel packages inside the disposable
container. It confirms the installed versions and source RPM match. `readelf`
then requires a single global callback definition in the framework and only
undefined references in the actual desktop/core plugins. Finally it builds
and runs the nested Qt plugin probe in `scripts/diagnose-dpf` against these
installed RPMs, using the same compiler flags as the original diagnosis.
It does **not** run that directory's baseline-versus-header experiment.

A successful package build and probe validate the full source patch and
shared callback ownership. Desktop behavior inside a Live or installed VM
still requires separate verification; `desktop_vm_verified` remains false.

## Artifact and consumption contract

The workflow uploads `DFM-hotfix-Fedora45-x86_64-RUN_ID-RUN_ATTEMPT`, including
logs on failure. All artifact filenames are checked to exclude colons.
Epoch colons occur only inside package metadata, never in filenames.

- `hotfix-input.json`: schema 1; repository/build commit/run identity, pinned
  source commits, hotfix patch hash, version/release, build status and validation.
- `rpms/ARCH/*.rpm`: **all** binary RPMs, including generated debug packages.
- `srpms/*.src.rpm`: the complete matching source RPM.
- `sources/`: the complete source archive, final and original specifications,
  all three patches, original licenses, lock file, README and build recipe.
- `logs/`, `symbols/`, `probe/`, `provenance/`: build/install/test logs,
  actual dynamic symbols, probe inputs, flags, repository configuration,
  expanded spec and exact installed build-dependency package list.
- `SHA256SUMS`: SHA-256 of every other artifact file.

`hotfix-input.json` has `schema`, `repository`, `build_commit`, `build_ref`,
`run_id`, `run_attempt`, `maintainer_commit`, `upstream_commit`, `patch_sha256`,
`version`, `release`, `build_success`, `exit_status` and `last_stage`.
Each `rpms` or `srpms` entry has `path`, `name`, `nevra`, `epoch`, `version`,
`release`, `arch`, `source_rpm` and `sha256`; `path` is relative to the artifact
root. `patches` and `source_archives` record their paths and hashes.
The `validation` object requires `passed`, `complete_rpms_installed`,
`single_framework_definition` and `nested_qt_probe_passed` to be true.

An ISO consumer must separately pin the successful Actions commit/run,
artifact ID and downloaded ZIP SHA-256. It must validate the metadata and
checksums and install exactly the four matching runtime packages:
`dde-file-manager`, `dde-file-manager-libs`, `dde-file-manager-desktop` and
`dde-file-manager-services-plugins`. The devel/debug packages stay available
for analysis and are not required in the Live image.

## Source and license preservation

The upstream package remains `GPL-3.0-or-later`, with its original `%license
LICENSE` entry. Original author notices and the two maintainer patches are
preserved. `maintainer/LICENSE` is copied from the pinned maintenance tree;
the build separately exports the upstream `LICENSE` without editing it.
The new patch is supplied under the same GPL-3.0-or-later terms as DFM.

Keep the matching source RPM, source archive, all patches, specifications and
license notices available alongside any redistributed binary RPMs. The
uploaded artifact contains this complete set; copying only the four runtime
RPMs into another distribution location does not copy their source bundle.

References: [pinned maintenance specification](https://github.com/Fedora-DDE-Remix/Deepin-Desktop-Environment/blob/adcd681b0b9e68cacbf9daa33bede62a253a3315/dde-file-manager/dde-file-manager.spec),
[pinned upstream source](https://github.com/linuxdeepin/dde-file-manager/tree/bdd0f409316054d136eeb8eb7a132a977e4915f7),
[DNF5 builddep command](https://dnf5.readthedocs.io/en/latest/dnf5_plugins/builddep.8.html).
