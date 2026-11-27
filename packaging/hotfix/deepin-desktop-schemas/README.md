# Temporary Fedora desktop schema repair

This package is an ISO-local rebuild of the maintainer's
`deepin-desktop-schemas-6.0.13-1` recipe. It does not submit a COPR build or alter
the installed upstream desktop configuration files after the RPM transaction.

The original recipe is pinned to
`Fedora-DDE-Remix/Deepin-Desktop-Environment` commit
`adcd681b0b9e68cacbf9daa33bede62a253a3315`. Upstream tag `6.0.13` resolves to commit
`00a92111f8f0cc7bcba8af9ae2a9950c7f02ae4e`; the builder fetches that commit,
verifies it and makes the source archive with `git archive` and `gzip -n`.

The source patch removes only the duplicate empty summary and description in
the mediakey `away` key. The original `XF86Away` binding and `Lock user` text are
preserved. Without this fix, GLib rejects the schema under `--strict`.

The SPEC also selects the Fedora-owned
`/usr/share/backgrounds/images/earth_from_space.jpg` for the existing appearance
GSettings defaults and requires `desktop-backgrounds-basic`. It requires glib2,
uses Fedora's glib2 file triggers for the system schema cache, and validates the
actual installed buildroot schemas and Go-generated override with
`glib-compile-schemas --strict --dry-run` in `%check`. It does not include any
Treeland/DConfig defaults, modify existing per-user settings, or weaken the ISO
strict compilation gate.

The temporary release is `1.1.remix1%{?dist}` so the maintainer's planned ordinary
release `2%{?dist}` naturally supersedes it. The original SPEC and maintainer
license remain in `maintainer/`; `sources.lock.json` pins all review inputs.
The local `Patch0` is copied into RPM's SOURCES directory by the builder, so no
unpublished patch URL is required.

Run `scripts/build-schemas-hotfix.sh` only through the disposable Fedora 45
x86_64 ISO compose container. It performs the real Go build and `rpmbuild -ba`,
checks binary/SRPM headers, runtime dependencies and package scriptlets, and
publishes a successful input manifest only after every build check succeeds.

Outputs are the binary RPM under `/work/rpms`, its matching SRPM under
`/output/rpms`, and identical `schemas-hotfix-input.json` files under `/work`,
`/output` and `/output/rpms/schemas-hotfix-provenance`. Provenance contains the
fixed source archive, source and maintainer licenses, original/adapted SPEC,
patch, build tool versions, build dependency and RPM build logs, header checks,
input hashes and SHA256SUMS. Filenames contain no epoch colon. The source archive
hash describes this `git archive` output, not a GitHub-generated release tarball.

The compose recipe separately checks the currently installed maintainer EVR
before accepting this temporary replacement. It must stop for a newer or
otherwise changed maintainer package, rather than replacing it blindly.
