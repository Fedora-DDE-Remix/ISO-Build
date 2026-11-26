#!/usr/bin/bash
# Run only inside the disposable, privileged Fedora 45 compose container.
set -euo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8
unset ANACONDA_ROOT_PATH
source /workspace/config/build.env
[[ $CONFIG_VERSION =~ ^45\.[0-9]{8}$ ]]
iso_name=Fedora-DDE-Remix-$CONFIG_VERSION-x86_64.iso

die() { printf 'compose: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $# -eq 0 ]] || die 'Run as root without arguments.'
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 45 && $(uname -m) == x86_64 ]] ||
    die 'The compose environment must be Fedora 45 x86_64.'
for directory in /workspace /work /output; do
    [[ -d $directory && ! -L $directory ]] || die "Missing real directory: $directory"
done
[[ -f /workspace/kickstarts/fedora-dde-live.ks ]] || die 'Kickstart is missing.'
[[ -f /workspace/scripts/check-pam.py ]] || die 'PAM smoke check is missing.'
[[ -f /workspace/scripts/check-comps.py ]] || die 'Desktop group completeness check is missing.'
[[ -f /workspace/scripts/check-selinux.py ]] || die 'SELinux policy and labeling check is missing.'
[[ -s /work/build-info.json && ! -L /work/build-info.json ]] || die 'The build provenance JSON is missing.'
[[ ! -e /work/compose-result ]] || die '/work/compose-result already exists; use a fresh compose workspace.'
[[ ! -e /output/$iso_name ]] || die 'The output ISO already exists.'

shopt -s nullglob
rpms=(/work/rpms/*.rpm)
(( ${#rpms[@]} > 0 )) || die 'No locally built installer/configuration RPMs in /work/rpms.'
names=$(rpm -qp --qf '%{NAME}\n' "${rpms[@]}")
grep -qx fedora-dde-installer <<< "$names" || die 'The installer RPM is missing.'
grep -qx fedora-dde-remix-config <<< "$names" || die 'The ISO configuration RPM is missing.'

# This Fedora metapackage supplies Anaconda's no-virt runtime and Lorax's
# xorriso, squashfs, loop/filesystem and Kickstart dependencies.
dnf -y install lorax-lmc-novirt pykickstart dnf5-plugins
for command in livemedia-creator ksflatten ksvalidator xorriso unsquashfs lsinitrd python3 tail; do
    command -v "$command" >/dev/null || die "Required command not found: $command"
done
losetup --find >/dev/null || die 'The container cannot allocate a loop device.'

install -d -m 0755 /work/compose-tmp /output/logs
ksflatten --config /workspace/kickstarts/fedora-dde-live.ks -o /work/fedora-dde-live-flat.ks
ksvalidator --version F45 /work/fedora-dde-live-flat.ks
install -m 0644 /work/fedora-dde-live-flat.ks /output/build.ks
rpm -q lorax anaconda-core anaconda-tui python3-kickstart > /output/logs/compose-tool-versions.txt

# Follow the external %post logs while LMC runs. Anaconda deliberately waits
# after a fatal error; preserve its diagnostics before ending that wait.
python3 - /output/logs /work/compose-tmp /tmp livemedia-creator \
    --make-iso --no-virt \
    --ks /work/fedora-dde-live-flat.ks \
    --releasever 45 --project 'Fedora DDE Remix' \
    --volid Fedora-DDE-45-x86_64 \
    --rootfs-type squashfs --nomacboot \
    --extra-boot-args 'selinux=1 enforcing=1' \
    --iso-only --iso-name "$iso_name" \
    --tmp /work/compose-tmp --resultdir /work/compose-result \
    --logfile /output/logs/lmc.log <<'PY'
from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback

log_dir, lmc_tmp, anaconda_tmp = map(Path, sys.argv[1:4])
command = sys.argv[4:]
post_logs = [log_dir / name for name in
             ('stage-files.log', 'image-config.log', 'save-manifest.log')]
for path in post_logs:
    if path.is_symlink():
        raise RuntimeError(f'Refusing a symlinked compose log: {path}')
    path.touch()
    path.chmod(0o644)

requested_signal = None
def request_stop(signum, _frame):
    global requested_signal
    requested_signal = signum

for signum in (signal.SIGINT, signal.SIGTERM):
    signal.signal(signum, request_stop)

def mirror_logs():
    # These are the Fedora 45 Anaconda runtime paths and Lorax's copy location.
    # Inspect only bounded-depth paths under --tmp, never walk a mounted root.
    sources = ((anaconda_tmp, 'runtime', ('*.log', 'anaconda-tb-*')),
               (log_dir / 'anaconda', 'lmc-copy', ('*',)),
               (lmc_tmp, 'lmc-tmp', ('*.log', 'anaconda-tb-*',
                   '*/anaconda*.log', '*/program.log', '*/dbus.log',
                   '*/packaging.log', '*/storage.log', '*/logs/*.log')))
    copied = 0
    for base, label, patterns in sources:
        if not base.is_dir():
            continue
        for pattern in patterns:
            for source in base.glob(pattern):
                try:
                    if source.is_symlink() or not source.is_file():
                        continue
                    if not source.resolve().is_relative_to(base.resolve()):
                        continue
                    target = log_dir / 'anaconda-snapshot' / label / source.relative_to(base)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(0o644)
                    copied += 1
                except OSError as error:
                    print(f'compose: Cannot preserve {source}: {error}', flush=True)
    if copied:
        print(f'compose: Preserved {copied} Anaconda log files in '
              f'{log_dir / "anaconda-snapshot"}.', flush=True)

def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False

def stop_group(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 10
    while group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.2)
    if group_exists(process.pid):
        print('compose: Killing the remaining LMC process group after 10 seconds.', flush=True)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        print('compose: LMC did not exit after SIGKILL; container teardown is required.', flush=True)

def show_failure_logs():
    paths = post_logs + [log_dir / 'anaconda-snapshot' / 'runtime' / name
                        for name in ('anaconda.log', 'program.log', 'dbus.log')]
    for path in paths:
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 32768))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()[-80:]
            print(f'\n=== Final diagnostics: {path} (up to 80 lines) ===', flush=True)
            print('\n'.join(lines), flush=True)
        except OSError as error:
            print(f'compose: Cannot read {path}: {error}', flush=True)

process = follower = None
status = 1
position = 0
identity = None
previous = b''
try:
    follower = subprocess.Popen(['tail', '-n', '+1', '-F', '-s', '0.2', '--',
                                 *map(str, post_logs)], start_new_session=True)
    process = subprocess.Popen(command, start_new_session=True)
    while True:
        terminal_error = False
        try:
            path = log_dir / 'lmc.log'
            info = path.stat()
            current_identity = (info.st_dev, info.st_ino)
            if current_identity != identity or info.st_size < position:
                identity, position, previous = current_identity, 0, b''
            with path.open('rb') as stream:
                stream.seek(position)
                content = previous + stream.read()
                position = stream.tell()
            terminal_error = b'the installer will now terminate.' in content.lower()
            previous = content[-256:]
        except FileNotFoundError:
            pass
        if terminal_error:
            print('compose: Anaconda reported a terminal error. Preserving diagnostics '
                  'before ending its termination wait.', flush=True)
            status = 1
            break
        if requested_signal is not None:
            print(f'compose: Received signal {requested_signal}; preserving diagnostics.', flush=True)
            status = 128 + requested_signal
            break
        returncode = process.poll()
        if returncode is not None:
            status = returncode if returncode >= 0 else 128 - returncode
            break
        time.sleep(0.2)
except Exception:
    traceback.print_exc()
finally:
    # Capture before signaling: Anaconda cleanup may remove its runtime logs.
    mirror_logs()
    stop_group(process)
    mirror_logs()
    # Give tail one final polling interval to forward the last %post output.
    time.sleep(0.3)
    if follower is not None:
        follower.terminate()
        try:
            follower.wait(timeout=2)
        except subprocess.TimeoutExpired:
            follower.kill()
            follower.wait(timeout=2)
    if status:
        show_failure_logs()
sys.exit(status)
PY

iso=/work/compose-result/$iso_name
[[ -s $iso ]] || die 'LMC did not produce the expected ISO.'
/usr/bin/bash /workspace/scripts/check-image.sh "$iso" /output/rpm-manifest.txt /output/logs
install -m 0644 "$iso" "/output/$iso_name"
(
    cd /output
    sha256sum "$iso_name" | tee CHECKSUM
)
stat --printf='ISO size: %s bytes\n' "/output/$iso_name"
printf 'Verified ISO: %s\n' "/output/$iso_name"
