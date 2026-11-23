#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Preserve the exact, signed comps RPM for the image's later DNF transaction.
set -Eeuo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

die() { printf 'prepare-comps: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $# -eq 0 ]] || die 'Run as root without arguments.'
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 45 && $(uname -m) == x86_64 ]] ||
    die 'The builder must be Fedora 45 x86_64.'
[[ -d /work && ! -L /work ]] || die '/work must be a real directory.'
for command in dnf curl rpm rpmkeys python3 sha256sum; do
    command -v "$command" >/dev/null || die "Required command not found: $command"
done

bootstrap=/work/comps-bootstrap
[[ ! -e $bootstrap && ! -L $bootstrap ]] || die 'Use a fresh comps bootstrap directory.'
[[ ! -e /work/comps-input.json && ! -L /work/comps-input.json ]] || die 'Comps input metadata already exists.'
install -d -m 0755 "$bootstrap"
verify_dir=$(mktemp -d /work/comps-verify.XXXXXXXX)
trap 'rm -rf -- "$verify_dir"' EXIT

key_url=https://download.copr.fedorainfracloud.org/results/mozixun/Fedora-DDE-Remix/pubkey.gpg
key_sha256=eb44eeabc2a5546db7b72d9f5adc6d9c17f7a4b7456e579e3dc0d964e2455200
key_fingerprint=1E6DCAB9CD7C35C002E28E9737CFB2A4FF3592C8
fallback_nevra=dde-desktop-comps-6.2.1-1.fc45.noarch
fallback_url=https://download.copr.fedorainfracloud.org/results/mozixun/Fedora-DDE-Remix/fedora-45-x86_64/11377888-dde-desktop-comps/dde-desktop-comps-6.2.1-1.fc45.noarch.rpm
nevra_format='%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n'

download_https() {
    curl --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' \
        --connect-timeout 20 --max-time 120 \
        --retry 3 --retry-delay 2 --retry-max-time 300 --retry-all-errors \
        --output "$2" "$1"
}

# Prefer the normal enabled repository. A successful transaction is pinned to
# its installed epoch/version, rather than resolving the package name again.
source_url=
if dnf -y --refresh install dde-desktop-comps; then
    mode=repository
    nevra=$(rpm -q --qf "$nevra_format" dde-desktop-comps)
    epoch=$(rpm -q --qf '%{EPOCHNUM}\n' dde-desktop-comps)
    [[ $nevra =~ ^dde-desktop-comps-[[:alnum:]_.+~^]+-[[:alnum:]_.+~^]+\.(noarch|x86_64)$ && $epoch =~ ^[0-9]+$ ]] ||
        die 'Cannot identify a single installed comps package.'
    dnf download --destdir "$bootstrap" "dde-desktop-comps-${epoch}:${nevra#dde-desktop-comps-}"
else
    mode=copr-build-fallback
    nevra=$fallback_nevra
    epoch=0
    source_url=$fallback_url
    printf 'Using the signed RPM from completed COPR build 11377888.\n'
    download_https "$source_url" "$bootstrap/$nevra.rpm"
fi

shopt -s nullglob
rpms=("$bootstrap"/*.rpm)
(( ${#rpms[@]} == 1 )) || die 'Expected exactly one comps RPM.'
rpm_file=${rpms[0]}
[[ -s $rpm_file && ! -L $rpm_file ]] || die 'The downloaded RPM is not a regular nonempty file.'

download_https "$key_url" "$bootstrap/pubkey.gpg"
printf '%s  %s\n' "$key_sha256" "$bootstrap/pubkey.gpg" | sha256sum --check --strict

# Force the rpmdb backend as well as a private dbpath: Fedora's system keyring
# must not contribute any trusted keys to this verification.
verify_options=(--dbpath "$verify_dir/rpmdb" --define '_keyring rpmdb'
    --define '_pkgverify_flags 0x0' --define '_pkgverify_level all')
rpm "${verify_options[@]}" --initdb
rpmkeys "${verify_options[@]}" --import "$bootstrap/pubkey.gpg"
fingerprints=$(rpmkeys "${verify_options[@]}" --list | awk '{print toupper($1)}')
[[ $fingerprints == "$key_fingerprint" ]] || die 'The isolated keyring does not contain exactly the pinned project key.'
if ! rpmkeys "${verify_options[@]}" --checksig --verbose "$rpm_file" > "$verify_dir/signature.log" 2>&1; then
    cat "$verify_dir/signature.log" >&2
    die 'The comps RPM failed project signature verification.'
fi
cat "$verify_dir/signature.log"
# Do not accept an unsigned RPM whose digests alone happen to verify.
grep -Eiq 'signature.*: OK$' "$verify_dir/signature.log" || die 'No valid cryptographic RPM signature was reported.'

[[ $(rpm "${verify_options[@]}" -qp --qf '%{NAME}\n' "$rpm_file") == dde-desktop-comps ]] || die 'Unexpected RPM name.'
[[ $(rpm "${verify_options[@]}" -qp --qf "$nevra_format" "$rpm_file") == "$nevra" ]] || die 'Downloaded RPM NEVRA mismatch.'
[[ $(rpm "${verify_options[@]}" -qp --qf '%{EPOCHNUM}\n' "$rpm_file") == "$epoch" ]] || die 'Downloaded RPM epoch mismatch.'

# DNF's local-package check is an additional check after the isolated one.
rpmkeys --import "$bootstrap/pubkey.gpg"
dnf -y --setopt=localpkg_gpgcheck=1 install "$rpm_file"
[[ $(rpm -q --qf "$nevra_format" dde-desktop-comps) == "$nevra" ]] || die 'Installed comps NEVRA mismatch.'
[[ $(rpm -q --qf '%{EPOCHNUM}\n' dde-desktop-comps) == "$epoch" ]] || die 'Installed comps epoch mismatch.'

rpm_sha256=$(sha256sum "$rpm_file")
rpm_sha256=${rpm_sha256%% *}
rpm_filename=${rpm_file##*/}
(
    cd "$bootstrap"
    sha256sum pubkey.gpg "$rpm_filename" > SHA256SUMS
)
python3 - "$mode" "$nevra" "$epoch" "$rpm_sha256" "$source_url" \
    "$key_fingerprint" "$key_sha256" "$rpm_filename" "$key_url" <<'PY'
import json
from pathlib import Path
import sys

mode, nevra, epoch, digest, source_url, fingerprint, key_digest, filename, key_url = sys.argv[1:]
directory = Path('/work/comps-bootstrap')
expected = {filename, 'pubkey.gpg', 'SHA256SUMS'}
assert {p.name for p in directory.iterdir()} == expected, 'Unexpected bootstrap files'
assert all(p.is_file() and not p.is_symlink() for p in directory.iterdir()), 'Invalid bootstrap file'
data = {
    'schema': 1,
    'mode': mode,
    'nevra': nevra,
    'epoch': int(epoch),
    'sha256': digest,
    'rpm_filename': filename,
    'source_url': source_url or None,
    'copr_build_id': 11377888 if mode == 'copr-build-fallback' else None,
    'key_url': key_url,
    'key_fingerprint': fingerprint,
    'key_sha256': key_digest,
}
Path('/work/comps-input.json').write_text(json.dumps(data, indent=2) + '\n')
PY
printf 'Verified comps: %s (epoch %s, mode %s)\nSHA256: %s\n' "$nevra" "$epoch" "$mode" "$rpm_sha256"
