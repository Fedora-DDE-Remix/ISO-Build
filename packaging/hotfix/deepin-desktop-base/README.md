# Temporary Remix branding dependency adaptation

This data-only rebuild is part of the ISO compose workflow. It does not write
to the maintainer's repository or publish to COPR.

The maintainer input is `Fedora-DDE-Remix/Deepin-Desktop-Environment` commit
`adcd681b0b9e68cacbf9daa33bede62a253a3315`. The original spec and its repository
license are preserved in `maintainer/`.

The upstream input is `linuxdeepin/deepin-desktop-base` commit
`63c52c9387a350df684bb5043dd836d86f862092`, the commit referenced by the
`2026.10.28` tag object `f918a51224a6767103a3044a7595ff2602ee5826`.

The adapted spec differs from the maintainer spec in exactly two lines:

- `Requires: fedora-logos` becomes `Requires: system-logos`, allowing the
  real Fedora `generic-logos` provider. No replacement package is impersonated.
- `Release: 1%{?dist}` becomes `Release: 1.1.remix1%{?dist}`. This updates
  the current `1.fc45` package and is superseded by a normal `2.fc45` update.

All upstream files, build/install commands, package file ownership and
`Source0` declarations remain unchanged. The builder checks out the exact
commit and creates `deepin-desktop-base-2026.10.28.tar.gz` with `git archive`
and `gzip -n`; the archive checksum is recorded as a generated source input,
not claimed to be the checksum of GitHub's tag archive.

`scripts/build-desktop-base-hotfix.sh` verifies the vendored input hashes and
independently compares the maintainer spec at its fixed commit, then runs
`rpmbuild -ba` in the existing disposable Fedora 45 compose container.
It verifies the resulting noarch RPM and matching SRPM, including their
digests, version, release, dependency and Provides names.

The binary enters `/work/rpms/`. The matching SRPM and source/spec/license
evidence enter `/output/rpms/` and
`/output/rpms/desktop-base-hotfix-provenance/`. The manifest is written to
`/work/desktop-base-hotfix-input.json` and
`/output/desktop-base-hotfix-input.json`, and included as
`desktop_base_hotfix` in the ISO build information.

The image transaction must first verify the installed maintainer package is
`0:2026.10.28-1.fc45.noarch`, upgrade this one temporary package, then perform
the targeted `fedora-logos` to `generic-logos` swap before installing the
remaining local RPMs and `fedora-remix-logos`. Do not use broad erasure options
or fake Provides. The maintained source remains untouched.
