#!/usr/bin/python3
"""Guest-only checks for test-install-vm.py; never installed into the ISO.

The public password below belongs only to a disposable QEMU test disk. Every
entry point requires the VM's DMI marker and an authorization file in /run.
"""

from __future__ import annotations

import ctypes as C
import fcntl
import grp
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time


RUNTIME = Path("/run/fedora-dde-vmtest")
INSTALLER = Path("/usr/share/fedora-dde-installer/tools")
CONFIG = Path("/run/fedora-dde-installer/installer.conf")
STATE = CONFIG.with_name("state.json")
CONFIG_TOOL = "/usr/bin/fedora-dde-installer-config"
USERNAME = "vmtest"
PASSWORD = "FedoraVmtest2026"
CRYPT_PASSWORD = "FedoraLuksVmtest2026"
HOSTNAME = "fedora-dde-vmtest"
POLICIES = {"ddm", "dde_daemon", "dde_api", "deepin_system_monitor"}
STAGES = ("preflight", "partition", "copy", "system", "ready", "configure", "finalize")
SCENARIOS = {"uefi-btrfs", "bios-ext4", "bios-mbr-ext4", "uefi-xfs-home-swap", "uefi-preserve", "uefi-small",
             "uefi-luks-btrfs-small", "bios-luks-ext4", "uefi-luks-xfs"}
STORAGE_EVIDENCE_NAME = "storage-cleanup-evidence.json"
STORAGE_EVIDENCE_LIMIT = 192 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(argv, *, check=True, timeout=120, capture=True, input_text=None, pass_fds=(), extra_env=None):
    result = subprocess.run(argv, input=input_text, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None,
                            timeout=timeout, pass_fds=pass_fds,
                            env=dict(os.environ, LC_ALL="C", LANG="C", **(extra_env or {})))
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} exited {result.returncode}: {(result.stderr or '')[-3000:]}")
    return result


class ProbeIncomplete(Exception):
    """A read-only observation could not finish; it is never a ready session."""

    def __init__(self, stage, kind, message):
        super().__init__(message)
        self.detail = {"stage": stage, "kind": kind, "message": str(message)[:1000]}


class SessionProbe:
    """One wall-clock budget, including authorization, for a session sample."""

    def __init__(self, seconds=30):
        self.started = time.monotonic()
        self.seconds = float(seconds)
        require(math.isfinite(self.seconds) and 0 < self.seconds <= 30,
                "Session probe budget must be finite and between 0 and 30 seconds.")
        self.deadline = self.started + self.seconds

    def marker(self, stage, event, **details):
        print("VMTEST_PROBE_STAGE=" + json.dumps({
            "stage": stage, "event": event,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "remaining_seconds": round(max(0, self.deadline - time.monotonic()), 3),
            **details}, sort_keys=True), flush=True)

    def remaining(self, stage):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeIncomplete(stage, "deadline", "The session probe exhausted its total wall-clock budget.")
        return remaining

    def collect(self, stage, operation):
        self.marker(stage, "begin")
        self.remaining(stage)
        try:
            result = operation()
        except (OSError, UnicodeError) as error:
            raise ProbeIncomplete(stage, "io", error) from error
        self.remaining(stage)
        self.marker(stage, "complete")
        return result

    def command(self, stage, argv, *, cap=15, check=True):
        def execute():
            # subprocess.run kills and reaps its child on TimeoutExpired. Keep
            # the inherited process group: the controller's GNU timeout also
            # kills descendants if the guest cannot finish its soft timeout.
            try:
                result = run(argv, timeout=min(cap, self.remaining(stage)), check=False)
            except subprocess.TimeoutExpired as error:
                raise ProbeIncomplete(stage, "timeout", f"{argv[0]} exceeded its remaining probe budget.") from error
            if check and result.returncode:
                raise ProbeIncomplete(stage, "command-failed",
                                      f"{argv[0]} exited {result.returncode}: {(result.stderr or '')[-500:]}")
            return result
        return self.collect(stage, execute)


def authorize(*, probe=None):
    if probe is not None:
        probe.marker("authorize", "begin")
        probe.remaining("authorize")
    # Invalid authorization, UID or VM identity is a hard failure, including
    # when a session probe is retriable for unrelated collection timeouts.
    require(os.geteuid() == 0, "VM checks must run through normal guest sudo authentication.")
    require(Path("/sys/class/dmi/id/product_serial").read_text().strip() == "FDDESMOKE",
            "This is not the isolated test-install-vm QEMU guest.")
    marker = RUNTIME / "authorized"
    require(marker.is_file() and not marker.is_symlink()
            and marker.stat().st_uid == 0 and not marker.stat().st_mode & 0o077
            and marker.read_text().strip() == "fedora-dde-vmtest-v1", "Missing private VM authorization marker.")
    detection = (probe.command("authorize-virtualization", ["systemd-detect-virt"], cap=5, check=False)
                 if probe is not None else run(["systemd-detect-virt"]))
    require(detection.returncode == 0 and detection.stdout.strip() in {"qemu", "kvm"},
            "Expected a QEMU/KVM guest.")
    if probe is not None:
        probe.remaining("authorize")
        probe.marker("authorize", "complete")


def test_context():
    value = json.loads((RUNTIME / "context.json").read_text())
    require(value.get("scenario") in SCENARIOS, "Invalid VM partition scenario.")
    return value


def properties(command):
    return dict(line.split("=", 1) for line in run(command).stdout.splitlines() if "=" in line)


def processes(*, probe=None):
    result = []
    for path in Path("/proc").iterdir():
        if probe is not None:
            probe.remaining("processes")
        if not path.name.isdecimal():
            continue
        try:
            entry = {"pid": int(path.name), "uid": path.stat().st_uid,
                           "comm": (path / "comm").read_text().strip(),
                           "exe": os.readlink(path / "exe"),
                           "label": (path / "attr/current").read_text().strip()}
            if entry["exe"] == "/usr/bin/dde-shell":
                entry["cmdline"] = (path / "cmdline").read_text().rstrip("\0").split("\0")
            result.append(entry)
        except (OSError, UnicodeError) as error:
            # A process may exit during enumeration. Other failures leave a
            # session sample incomplete instead of silently losing evidence.
            if probe is not None and not isinstance(error, (FileNotFoundError, ProcessLookupError)):
                raise ProbeIncomplete("processes", "io", error) from error
            continue
    return result


def context(path):
    return os.getxattr(path, "security.selinux").rstrip(b"\0").decode("ascii")


def mount_info(path):
    data = json.loads(run(["findmnt", "--json", "--target", path, "--output",
                           "TARGET,SOURCE,FSTYPE,OPTIONS,UUID,FSROOT"]).stdout)
    require(len(data.get("filesystems", [])) == 1, f"Cannot identify mount for {path}.")
    return data["filesystems"][0]


def installed_boot_mounts(installation, uefi):
    """Check first-boot mounts against the backend's finalized UUID records."""
    expected = installation.get("mounts", [])
    result = {}
    for point, filesystem in (("/boot", "ext4"),) + ((("/boot/efi", "vfat"),) if uefi else ()):
        matches = [item for item in expected if item.get("mountpoint") == point]
        require(len(matches) == 1 and matches[0].get("fstype") == filesystem
                and re.fullmatch(r"[A-Fa-f0-9-]+", matches[0].get("uuid", "")),
                f"The finalized installation has no unique {filesystem} UUID record for {point}.")
        actual = mount_info(point)
        require(actual.get("target") == point and actual.get("fstype") == filesystem
                and actual.get("uuid") == matches[0]["uuid"],
                f"The installed {point} mount does not match its finalized filesystem type and UUID.")
        result[point] = actual
    return result


def policy_check():
    require(run(["getenforce"]).stdout.strip() == "Enforcing", "SELinux is not Enforcing.")
    require(Path("/sys/fs/selinux/enforce").read_text().strip() == "1", "SELinux kernel enforcement is off.")
    cmdline = Path("/proc/cmdline").read_text().split()
    require(not {"selinux=0", "enforcing=0"}.intersection(cmdline), "Booted with a weakening SELinux argument.")
    config = Path("/etc/selinux/config").read_text()
    require(re.search(r"(?m)^\s*SELINUX\s*=\s*enforcing\s*$", config), "SELinux config is not enforcing.")
    modules = {line.split()[0] for line in run(["semodule", "--list=full"]).stdout.splitlines()
               if line.split() and not line.split()[0].isdigit()}
    # --list=full includes a priority column; ordinary --list is stable across
    # Fedora policycoreutils versions and is sufficient to check loaded names.
    modules.update(line.split()[0] for line in run(["semodule", "-l"]).stdout.splitlines() if line.split())
    require(POLICIES <= modules, "Required SELinux modules are not loaded: " + ", ".join(sorted(POLICIES - modules)))
    expected = {"/usr/bin/ddm": "xdm_exec_t", "/usr/libexec/ddm-helper": "xdm_exec_t",
                "/usr/lib/systemd/system/treeland.service": "xdm_unit_file_t",
                "/usr/bin/bash": "shell_exec_t", "/usr/lib/systemd/systemd": "init_exec_t",
                "/etc/passwd": "passwd_file_t"}
    labels = {}
    for path, wanted in expected.items():
        label = context(path)
        require(len(label.split(":")) >= 4 and label.split(":")[2] == wanted,
                f"Unexpected SELinux label on {path}: {label}")
        labels[path] = label
    ddm = [item for item in processes() if item["comm"] == "ddm"]
    require(ddm and all(len(p["label"].split(":")) >= 3 and p["label"].split(":")[2] == "xdm_t"
                        for p in ddm), "The running DDM daemon is not confined to xdm_t.")
    run(["authselect", "check"])
    return {"mode": "Enforcing", "modules": sorted(POLICIES), "labels": labels, "ddm": ddm}


def baseline(phase, expected_uuid=""):
    require(phase in {"live", "installed"}, "Invalid phase.")
    test = test_context()
    scenario = test["scenario"]
    uefi = not scenario.startswith("bios-")
    require(Path("/sys/firmware/efi").is_dir() == uefi, "The guest booted with the wrong firmware type.")
    release = Path("/etc/os-release").read_text()
    require(re.search(r"(?m)^ID=[\"']?fedora[\"']?$", release)
            and re.search(r"(?m)^VERSION_ID=[\"']?45[\"']?$", release), "Expected Fedora 45.")
    profile = json.loads(Path("/etc/fedora-dde-installer/install-profile.json").read_text())
    require(profile == {"schema": 1, "selinux": "enforcing", "pam": "fedora"}
            and type(profile["schema"]) is int, "Unexpected enforcing installation profile.")
    for _ in range(60):
        if run(["systemctl", "is-active", "ddm.service"], check=False).returncode == 0:
            break
        time.sleep(2)
    run(["systemctl", "is-active", "ddm.service"])
    security = policy_check()
    copr = json.loads(run(["/usr/libexec/fedora-dde-check-copr"]).stdout)
    assets = json.loads(run(["/usr/libexec/fedora-dde-check-desktop-assets"]).stdout)
    enabled_repositories = json.loads(run(["dnf", "--cacheonly", "repo", "list", "--enabled", "--json"], timeout=60).stdout)
    require(isinstance(enabled_repositories, list)
            and sum(repo.get("id") == copr["repository"] and repo.get("is_enabled") is True
                    for repo in enabled_repositories) == 1,
            "DNF does not list the installed Remix COPR repository as enabled.")
    copr["dnf_enabled_verified"] = True
    cmdline = Path("/proc/cmdline").read_text().strip()
    root = mount_info("/")
    result = {"phase": phase, "scenario": scenario, "uefi": uefi,
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "cmdline": cmdline, "root": root, "profile": profile, "selinux": security, "copr": copr,
              "desktop_assets": assets,
              "build_info": json.loads(Path("/usr/share/fedora-dde-remix/build-info.json").read_text()),
              "packages": run(["rpm", "-q", "ddm", "treeland", "dde-session", "dde-shell",
                                "selinux-policy-targeted"], check=False).stdout.splitlines()}
    hotfix_packages = []
    for package in result["build_info"]["dfm_hotfix"]["runtime_rpms"]:
        actual = run(["rpm", "-q", "--qf", "%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}", package["name"]]).stdout.split("\t")
        require(actual == [str(package["epoch"]), package["version"], package["release"], package["arch"], package["source_rpm"]],
                "The tested DFM package differs from the verified temporary hotfix: " + package["name"])
        hotfix_packages.append(package["name"] + "-" + package["version"] + "-" + package["release"])
    result["verified_dfm_hotfix_packages"] = hotfix_packages
    base = result["build_info"]["desktop_base_hotfix"]
    actual_base = run(["rpm", "-q", "--qf", "%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}", base["name"]]).stdout.split("\t")
    require(actual_base == ["0", base["version"], base["release"], "noarch", base["binary_rpm"]["source_rpm"]],
            "The desktop base package differs from the verified temporary dependency adaptation.")
    result["verified_desktop_base_hotfix"] = base["name"] + "-" + base["version"] + "-" + base["release"]
    schemas = result["build_info"]["schemas_hotfix"]
    require((schemas["name"], schemas["version"], schemas["release"]) ==
            ("deepin-desktop-schemas", "6.0.13", "1.1.remix1.fc45")
            and schemas.get("build_success") is True
            and schemas["strict_schema_check"].get("success") is True
            and schemas["strict_schema_check"].get("command") == "glib-compile-schemas --strict --dry-run",
            "The desktop schema repair lacks the expected identity or successful strict build check.")
    actual_schemas = run(["rpm", "-q", "--qf", "%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}", schemas["name"]]).stdout.split("\t")
    require(actual_schemas == ["0", schemas["version"], schemas["release"], "noarch", schemas["binary_rpm"]["source_rpm"]],
            "The installed desktop schemas differ from the verified temporary repair.")
    result["verified_schemas_hotfix"] = schemas["name"] + "-" + schemas["version"] + "-" + schemas["release"]
    user = "liveuser" if phase == "live" else USERNAME
    account = pwd.getpwnam(user)
    groups = [grp.getgrgid(g).gr_name for g in os.getgrouplist(user, account.pw_gid)]
    require(account.pw_uid >= 1000 and "wheel" in groups, "The login account is not an ordinary wheel user.")
    result["account"] = {"name": user, "uid": account.pw_uid, "groups": groups, "home": account.pw_dir}
    if phase == "live":
        require("rd.live.image" in cmdline.split(), "The first boot did not use the final Live ISO.")
        require((INSTALLER / "scripts/fedora_backend.py").is_file(), "The ISO lacks the real installer backend.")
        result["installer_rpm"] = run(["rpm", "-q", "fedora-dde-installer"]).stdout.strip()
    else:
        require("rd.live.image" not in cmdline.split() and "root=live:" not in cmdline,
                "The second boot is still running a Live system.")
        require(expected_uuid and root.get("uuid") == expected_uuid, "The disk boot has the wrong root UUID.")
        wanted_fs = "ext4" if scenario.startswith("bios-") else "xfs" if scenario in {"uefi-xfs-home-swap", "uefi-luks-xfs"} else "btrfs"
        require(root["fstype"] == wanted_fs and "rw" in root["options"].split(","), "Installed root filesystem is wrong or not writable.")
        result["boot_filesystems"] = installed_boot_mounts(test.get("installation", {}), uefi)
        if "-luks-" in scenario:
            result["encryption"] = encryption_check("installed")
        home = mount_info("/home")
        if "-luks-" in scenario:
            encrypted = test["installation"]["encrypted_root"]
            require(home.get("uuid") == expected_uuid
                    and Path(home["source"].split("[", 1)[0]).resolve() == Path(encrypted["mapper"]).resolve(),
                    "The installed home directory is outside the encrypted root filesystem.")
            if wanted_fs != "btrfs":
                require(home["target"] == "/", "Encrypted ext4/XFS home must remain a directory in the root filesystem.")
        if wanted_fs == "btrfs":
            require(root["fsroot"] == "/root" and "compress=zstd:1" in root["options"].split(","),
                    "Installed Btrfs root lacks its root subvolume or zstd:1 compression.")
            if scenario != "uefi-preserve":
                require(home["fstype"] == "btrfs" and home["fsroot"] == "/home"
                        and home.get("uuid") == expected_uuid and "compress=zstd:1" in home["options"].split(","),
                        "Installed Btrfs home subvolume is wrong.")
        if scenario in {"uefi-preserve", "uefi-xfs-home-swap"}:
            require(home["target"] == "/home" and home["fstype"] == "ext4" and home.get("uuid") != expected_uuid,
                    "The separate ext4 home filesystem was not mounted.")
        if scenario == "uefi-xfs-home-swap":
            active_swap = run(["swapon", "--show=NAME", "--noheadings", "--raw"]).stdout.splitlines()
            swap_uuids = [run(["blkid", "-s", "UUID", "-o", "value", p], check=False).stdout.strip() for p in active_swap]
            require(test.get("installation", {}).get("swap_uuid") in swap_uuids, "The installed disk swap is not active.")
            result["active_swap"] = active_swap
        if scenario == "uefi-preserve":
            preserved = test["partition_plan"]["preserved"]
            current = preserved_identity(preserved["path"])
            require(current == {k: preserved[k] for k in current}, "The retained partition identity or geometry changed.")
            marker = Path("/home/iso-preserve.bin")
            require(home.get("uuid") == preserved["uuid"] and marker.is_file()
                    and hashlib.sha256(marker.read_bytes()).hexdigest() == preserved["marker_sha256"],
                    "Retained home contents were not preserved through installation and reboot.")
            result["preserved"] = dict(current, marker_sha256=preserved["marker_sha256"], verified=True)
            esp = preserved["esp"]
            esp_current = preserved_identity(esp["path"])
            require(esp_current == {k: esp[k] for k in esp_current}, "The retained ESP identity or geometry changed.")
            esp_marker = Path("/boot/efi/EFI/KeepTest/iso-preserve.bin")
            require(mount_info("/boot/efi").get("uuid") == esp["uuid"] and esp_marker.is_file()
                    and hashlib.sha256(esp_marker.read_bytes()).hexdigest() == esp["marker_sha256"],
                    "The unrelated EFI vendor marker was not preserved through installation and reboot.")
            result["preserved_esp"] = dict(esp_current, marker_sha256=esp["marker_sha256"], verified=True)
        require(run(["getent", "passwd", "liveuser"], check=False).returncode != 0,
                "The temporary Live account leaked into the installed system.")
        shadow = run(["getent", "shadow", "root"]).stdout.split(":")
        require(len(shadow) >= 2 and shadow[1].startswith(("!", "*")), "The installed root account is not locked.")
        require(socket.gethostname() == HOSTNAME, "Installed hostname mismatch.")
        require(Path("/etc/localtime").resolve() == Path("/usr/share/zoneinfo/UTC").resolve(), "Installed timezone mismatch.")
        require("LANG=en_US.UTF-8" in Path("/etc/locale.conf").read_text(), "Installed locale mismatch.")
        summary = json.loads(Path("/var/log/fedora-dde-installer/install-summary.json").read_text())
        require(summary.get("status") == "configured" and summary.get("uefi") is uefi
                and summary.get("install_profile") == profile, "Installer completion summary mismatch.")
        result.update(home=home, root_locked=True, liveuser_absent=True, hostname=socket.gethostname(), summary=summary)
    return result


def shell_crashes(uid, boot_id, since_monotonic_us, *, probe=None, observed=None):
    fields = "__MONOTONIC_TIMESTAMP,_BOOT_ID,COREDUMP_UID,COREDUMP_PID,COREDUMP_EXE,COREDUMP_SIGNAL,COREDUMP_SIGNAL_NAME"
    command = ["journalctl", "-b", "--no-pager", "-o", "json", "--output-fields=" + fields,
               f"COREDUMP_UID={uid}", "COREDUMP_EXE=/usr/bin/dde-shell"]
    output = (probe.command("crash-journal", command) if probe is not None
              else run(command, timeout=15)).stdout
    crashes = observed if observed is not None else []
    for line in output.splitlines():
        if probe is not None:
            probe.remaining("crash-journal-decode")
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("Crash journal entry is not an object.")
            timestamp = int(event["__MONOTONIC_TIMESTAMP"])
        except (ValueError, KeyError, TypeError) as error:
            if probe is not None:
                raise ProbeIncomplete("crash-journal-decode", "invalid-output", error) from error
            raise
        require(event.get("_BOOT_ID") == boot_id.replace("-", "")
                and event.get("COREDUMP_UID") == str(uid)
                and event.get("COREDUMP_EXE") == "/usr/bin/dde-shell",
                "Unexpected identity in the filtered dde-shell crash journal.")
        if timestamp >= since_monotonic_us:
            crashes.append(event)
    return crashes


def session(user, since_monotonic_us=None, expected_boot_id=None, *, budget_seconds=30):
    probe = SessionProbe(budget_seconds)
    result = {"user": user, "uid": None, "ready": False,
              "boot_id": None, "observed_at_monotonic_us": None,
              "dde_shell_crashes": None, "crash_check_complete": False,
              "sessions": [], "ddm_sessions": [], "dde_shell": [], "treeland": [],
              "wayland_sockets": [], "probe_complete": False, "probe_errors": [],
              "probe_budget_seconds": probe.seconds}
    try:
        # Start the deadline before authorization's systemd-detect-virt, unlike
        # other actions whose existing installation/diagnostic limits remain.
        authorize(probe=probe)
        observed_at = time.monotonic_ns() // 1000
        boot_id = probe.collect("boot-identity", lambda:
                                Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        uid = probe.collect("user-identity", lambda: pwd.getpwnam(user).pw_uid)
        result.update(uid=uid, boot_id=boot_id, observed_at_monotonic_us=observed_at)
        if since_monotonic_us is not None:
            require(expected_boot_id == boot_id, "The guest rebooted during the graphical login check.")
            since_monotonic_us = int(since_monotonic_us)
            require(0 <= since_monotonic_us <= observed_at, "Invalid graphical-login monotonic checkpoint.")
        else:
            # An initial sample establishes this checkpoint; still verify that
            # the journal is readable instead of treating an unknown as [].
            require(expected_boot_id is None, "An initial session sample cannot supply only a boot ID.")
            since_monotonic_us = observed_at
        result["dde_shell_crashes"] = []
        shell_crashes(uid, boot_id, since_monotonic_us, probe=probe,
                      observed=result["dde_shell_crashes"])
        result["crash_check_complete"] = True
        listing = probe.command("loginctl-list", ["loginctl", "list-sessions", "--no-legend", "--no-pager"])
        for line in listing.stdout.splitlines():
            if not line.split():
                continue
            sid = line.split()[0]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", sid):
                raise ProbeIncomplete("loginctl-list", "invalid-output", "Invalid loginctl session identifier.")
            stage = "loginctl-show:" + sid
            output = probe.command(stage, ["loginctl", "show-session", sid, "--no-pager"]).stdout
            data = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            if data.get("Id") != sid or not {"Name", "Service", "Type", "Class", "Active", "State"} <= data.keys():
                raise ProbeIncomplete(stage, "invalid-output", "loginctl did not return complete session properties.")
            if data["Name"] == user:
                result["sessions"].append(data)
        result["ddm_sessions"] = [s for s in result["sessions"]
                                  if s["Service"] == "ddm" and s["Type"] == "wayland"
                                  and s["Class"] == "user" and s["Active"] == "yes" and s["State"] == "active"]
        procs = probe.collect("processes", lambda: processes(probe=probe))
        result["dde_shell"] = [p for p in procs if p["uid"] == uid and p["comm"] == "dde-shell"]
        # Treeland may be a system compositor owned by another UID.
        result["treeland"] = [p for p in procs if p["comm"] == "treeland"]
        result["wayland_sockets"] = probe.collect("wayland-sockets", lambda:
            [str(p) for p in Path(f"/run/user/{uid}").glob("wayland-*") if p.is_socket()])
        probe.remaining("complete")
        result["probe_complete"] = True
        result["ready"] = bool(result["ddm_sessions"] and result["dde_shell"] and result["treeland"]
                               and result["crash_check_complete"] and not result["dde_shell_crashes"])
    except ProbeIncomplete as error:
        result["probe_errors"].append(error.detail)
        if not result["crash_check_complete"] and not result["dde_shell_crashes"]:
            result["dde_shell_crashes"] = None
        probe.marker(error.detail["stage"], "incomplete", **{k: v for k, v in error.detail.items() if k != "stage"})
    result["probe_elapsed_seconds"] = round(time.monotonic() - probe.started, 3)
    probe.marker("complete", "complete" if result["probe_complete"] else "incomplete")
    return result


def set_config(key, value):
    require("PASSWORD" not in key, "Password values cannot be put on a command line.")
    run([CONFIG_TOOL, "set", str(CONFIG), "", key, value])


def preserved_identity(path):
    block = Path("/sys/class/block") / Path(path).name
    start = int((block / "start").read_text())
    size = int((block / "size").read_text())
    return {"path": path, "start": start, "end": start + size - 1,
            "uuid": run(["blkid", "-s", "UUID", "-o", "value", path]).stdout.strip(),
            "partuuid": run(["blkid", "-s", "PARTUUID", "-o", "value", path]).stdout.strip()}


def seed_preserved_home(total):
    start, end = total - 8 * 1024**3 // 512, total - 2049
    run(["parted", "--script", "/dev/vda", "mklabel", "gpt"])
    run(["parted", "--script", "/dev/vda", "mkpart", "retained-esp", "fat32", "2048s", f"{601 * 2048 - 1}s"])
    run(["parted", "--script", "/dev/vda", "set", "1", "esp", "on"])
    run(["parted", "--script", "/dev/vda", "mkpart", "retained-home", "ext4", f"{start}s", f"{end}s"])
    run(["udevadm", "settle"])
    run(["mkfs.vfat", "-F32", "-n", "KEEPEFI", "/dev/vda1"])
    run(["mkfs.ext4", "-F", "-L", "KEEPHOME", "/dev/vda2"])
    esp_mount = RUNTIME / "retained-esp"
    esp_mount.mkdir(mode=0o700)
    run(["mount", "/dev/vda1", str(esp_mount)])
    try:
        esp_marker = esp_mount / "EFI/KeepTest/iso-preserve.bin"
        esp_marker.parent.mkdir(parents=True)
        esp_marker.write_bytes(os.urandom(256))
        esp_digest = hashlib.sha256(esp_marker.read_bytes()).hexdigest()
        run(["sync"])
    finally:
        run(["umount", str(esp_mount)])
    seed = RUNTIME / "retained-home"
    seed.mkdir(mode=0o700)
    run(["mount", "/dev/vda2", str(seed)])
    try:
        run(["chcon", "--reference=/home", str(seed)])
        marker = seed / "iso-preserve.bin"
        marker.write_bytes(os.urandom(256))
        marker.chmod(0o644)
        run(["chcon", "--reference=/home", str(marker)])
        digest = hashlib.sha256(marker.read_bytes()).hexdigest()
        run(["sync"])
    finally:
        run(["umount", str(seed)])
    return dict(preserved_identity("/dev/vda2"), marker_sha256=digest,
                esp=dict(preserved_identity("/dev/vda1"), marker_sha256=esp_digest))


def plan_for(scenario, total, preserved=None):
    """Return the same reviewed JSON protocol consumed by the real helper.

    This exercises partition execution, not the graphical layout planner.
    All endpoints are inclusive 512-byte sectors on the isolated virtual disk.
    """
    bios_area = scenario in {"bios-ext4", "bios-luks-ext4"}
    if scenario.startswith("bios-"):
        boot_start = 3 if bios_area else 1
        root_start = boot_start + 2048
        bounds = [(boot_start * 2048, root_start * 2048 - 1, "ext4", "/boot", "BOOT"),
                  (root_start * 2048, total - 2049, "ext4", "/", "ROOT")]
        table = "gpt" if bios_area else "msdos"
    else:
        bounds = [(2048, 601 * 2048 - 1, "vfat", "/boot/efi", "EFI"),
                  (601 * 2048, 2649 * 2048 - 1, "ext4", "/boot", "BOOT")]
        if scenario == "uefi-xfs-home-swap":
            root_end = (2649 + 32768) * 2048 - 1
            swap_start = total - (2048 + 1) * 2048
            bounds += [(2649 * 2048, root_end, "xfs", "/", "ROOT"),
                       (root_end + 1, swap_start - 1, "ext4", "/home", "HOME"),
                       (swap_start, total - 2049, "linux-swap", "swap", "SWAP")]
        else:
            last = preserved["start"] - 1 if preserved else total - 2049
            bounds += [(2649 * 2048, last, "xfs" if scenario == "uefi-luks-xfs" else "btrfs", "/", "ROOT")]
        table = "gpt"
    plan = [] if preserved else [{"type": "disk", "operate": "new", "device": "/dev/vda", "diskType": table}]
    if preserved:
        esp = preserved["esp"]
        bounds = bounds[1:]  # The existing ESP is reused without formatting.
        plan.append({"type": "partition", "operate": "edit", "device": "/dev/vda", "path": esp["path"],
                     "id": "keep-esp", "index": 1, "partType": "primary", "label": "KEEPEFI",
                     "startPoint": esp["start"], "endPoint": esp["end"], "sectorSize": 512,
                     "size": (esp["end"] - esp["start"] + 1) * 512 // 1024**2,
                     "deviceSize": total * 512 // 1024**2, "filesystem": "vfat", "mountPoint": "/boot/efi",
                     "isneedformat": False, "isBiosBoot": False, "isCrypt": False, "partUuid": esp["partuuid"]})
    if bios_area:
        plan.append({"type": "partition", "operate": "new", "device": "/dev/vda", "path": "",
                     "id": "vmtest-bios-grub", "index": 1, "partType": "primary", "label": "",
                     "startPoint": 2048, "endPoint": 6143, "sectorSize": 512, "size": 2,
                     "deviceSize": total * 512 // 1024**2, "filesystem": "", "mountPoint": "",
                     "isneedformat": False, "isBiosBoot": True})
    for index, (start, end, filesystem, mount, label) in enumerate(bounds, 3 if preserved else 2 if bios_area else 1):
        require(end >= start, "The VM layout does not fit the disposable disk.")
        plan.append({"type": "partition", "operate": "new", "device": "/dev/vda", "path": "",
                     "id": f"vmtest-{index}", "index": index, "partType": "primary", "label": label,
                     "startPoint": start, "endPoint": end, "sectorSize": 512,
                     "size": (end - start + 1) * 512 // 1024**2, "deviceSize": total * 512 // 1024**2,
                     "isstartpoint": True, "filesystem": filesystem, "mountPoint": mount, "isneedformat": True,
                     "isCrypt": "-luks-" in scenario and mount == "/"})
    if preserved:
        plan.append({"type": "partition", "operate": "edit", "device": "/dev/vda", "path": preserved["path"],
                     "id": "keep-home", "index": 2, "partType": "primary", "label": "KEEPHOME",
                     "startPoint": preserved["start"], "endPoint": preserved["end"], "sectorSize": 512,
                     "size": (preserved["end"] - preserved["start"] + 1) * 512 // 1024**2,
                     "deviceSize": total * 512 // 1024**2, "filesystem": "ext4", "mountPoint": "/home",
                     "isneedformat": False, "isBiosBoot": False, "isCrypt": False, "partUuid": preserved["partuuid"]})
    return plan


def prepare():
    require("rd.live.image" in Path("/proc/cmdline").read_text().split(), "Installation requires the Live boot.")
    scenario = test_context()["scenario"]
    disk_size = 16_000_000_000 if scenario in {"uefi-small", "uefi-luks-btrfs-small"} else 64 * 1024**3
    disks = json.loads(run(["lsblk", "--json", "--bytes", "--nodeps", "--output", "PATH,SERIAL,SIZE,TYPE,RO"]).stdout)["blockdevices"]
    targets = [d for d in disks if str(d.get("serial", "")).strip() == "FDDESMOKE"]
    require(len(targets) == 1 and targets[0]["path"] == "/dev/vda"
            and targets[0]["type"] == "disk" and not targets[0]["ro"]
            and int(targets[0]["size"]) == disk_size, "The disposable target disk identity or capacity is wrong.")
    require(not run(["lsblk", "--noheadings", "--raw", "--output", "MOUNTPOINTS", "/dev/vda"]).stdout.strip(),
            "The disposable disk is already mounted.")
    sector = int(run(["blockdev", "--getss", "/dev/vda"]).stdout)
    require(sector == 512, "This QEMU test plan requires 512-byte logical sectors.")
    require(not STATE.exists(), "An installation is already active; never retry destructive partitioning implicitly.")
    run([str(INSTALLER / "fedora-dde-installer-preinit")])
    total = int(targets[0]["size"]) // sector
    preserved = seed_preserved_home(total) if scenario == "uefi-preserve" else None
    plan = plan_for(scenario, total, preserved)
    policy = CONFIG.with_name("partition-policy.json")
    policy.write_text(json.dumps(plan, indent=2) + "\n")
    policy.chmod(0o600)
    set_config("DI_PARTITION_CONFIG", str(policy))
    mode = 6 if preserved else 0
    set_config("DI_PARTITION_TYPE", str(mode))
    set_config("DI_SOURCE_ROOT", "auto")
    set_config("DI_DEVICE_LIST", "/dev/vda")
    return {"disk": targets[0], "plan": plan, "partition_mode": mode, "preserved": preserved,
            "scenario": scenario, "graphical_layout_planner_tested": False}


def configure_account():
    require(json.loads(STATE.read_text()).get("phase") == "awaiting-user", "Account setup is not in the post-install phase.")
    for key, value in {"DI_USERNAME": USERNAME, "DI_HOSTNAME": HOSTNAME,
                       "DI_LOCALE": "en_US", "DI_REGION_FORMAT_LOCALE_SET": "en_US",
                       "DI_TIMEZONE": "UTC", "DI_LAYOUT": "us", "DI_LAYOUT_VARIANT": "",
                       "DI_DDE_SESSION": "treeland", "DI_IS_ENABLE_NTP": "false"}.items():
        set_config(key, value)
    # The fixed disposable password is ASCII without QSettings metacharacters.
    # Replace only the existing General-section key in the private runtime INI.
    data = CONFIG.read_text()
    data, count = re.subn(r"(?m)^DI_PASSWORD\s*=.*$", "DI_PASSWORD=" + PASSWORD, data)
    require(count == 1, "Cannot locate the private runtime password field.")
    CONFIG.write_text(data)
    CONFIG.chmod(0o600)
    return {"user": USERNAME, "hostname": HOSTNAME, "locale": "en_US.UTF-8", "timezone": "UTC"}


def installed_state():
    state = json.loads(STATE.read_text())
    require(state.get("phase") == "finalized" and not state.get("owned_mounts")
            and not state.get("owned_mappers"), "Installation did not finalize cleanly.")
    for key in ("DI_PASSWORD", "DI_ROOT_PASSWORD", "DI_CRYPT_PASSWORD"):
        require(not run([CONFIG_TOOL, "get", str(CONFIG), "", key]).stdout, "An installer secret was not cleared.")
    root = next(item for item in state["mounts"] if item["mountpoint"] == "/")
    encrypted = state.get("encrypted_root")
    if encrypted:
        require(not Path(encrypted["mapper"]).exists(), "The installer left its encrypted mapper open.")
        uuid = encrypted["filesystem_uuid"]
        require(root.get("uuid") == uuid, "The saved encrypted filesystem UUIDs disagree.")
        run(["cryptsetup", "isLuks", "--type", "luks2", encrypted["device"]])
        require(run(["cryptsetup", "luksUUID", encrypted["device"]]).stdout.strip() == encrypted["uuid"],
                "The finalized LUKS UUID changed.")
    else:
        uuid = run(["blkid", "-s", "UUID", "-o", "value", root["device"]]).stdout.strip()
    require(bool(re.fullmatch(r"[A-Fa-f0-9-]+", uuid)), "Installed root UUID is invalid.")
    swap = next((item for item in state["mounts"] if item["mountpoint"] == "swap"), None)
    swap_uuid = run(["blkid", "-s", "UUID", "-o", "value", swap["device"]]).stdout.strip() if swap else None
    return {"phase": state["phase"], "root_uuid": uuid, "swap_uuid": swap_uuid, "mounts": state["mounts"],
            "installation_id": state["installation_id"], "install_profile": state["install_profile"],
            "kernels": state.get("kernels", []), "kernel_options": state.get("kernel_options", ""),
            "owned_mounts": state["owned_mounts"], "owned_mappers": state.get("owned_mappers", []),
            "encrypted_root": encrypted, "secrets_cleared": True,
            "mount_namespace": state.get("mount_namespace")}


def encryption_check(phase):
    require(phase in {"target", "installed"}, "Invalid encryption verification phase.")
    test = test_context()
    require("-luks-" in test["scenario"], "This scenario does not request encryption.")
    installation = json.loads(STATE.read_text()) if phase == "target" else test["installation"]
    record = installation.get("encrypted_root")
    require(isinstance(record, dict) and record.get("name") == "luks-" + record.get("uuid", ""),
            "Missing encrypted root record.")
    target = Path(installation["target"]) if phase == "target" else Path("/")
    root = mount_info(str(target))
    require(root.get("uuid") == record["filesystem_uuid"] and root.get("fstype") == record["fstype"],
            "The mounted encrypted root does not match its inner filesystem identity.")
    require(Path(root["source"].split("[", 1)[0]).resolve() == Path(record["mapper"]).resolve(),
            "The root is not mounted through its expected encryption mapper.")
    run(["cryptsetup", "isLuks", "--type", "luks2", record["device"]])
    require(run(["cryptsetup", "luksUUID", record["device"]]).stdout.strip() == record["uuid"],
            "The physical LUKS UUID differs from the installation record.")
    metadata = json.loads(run(["cryptsetup", "luksDump", "--dump-json-metadata", record["device"]]).stdout)
    keyslots = metadata.get("keyslots", {})
    require(len(keyslots) == 1 and all(value.get("kdf", {}).get("type") == "argon2id" for value in keyslots.values()),
            "Expected exactly one Argon2id password keyslot.")
    rows = [line.split() for line in (target / "etc/crypttab").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    require(rows == [[record["name"], "UUID=" + record["uuid"], "none", "luks,x-initrd.attach"]],
            "crypttab does not request password-only encrypted root activation.")
    expected_argument = "rd.luks.uuid=luks-" + record["uuid"]
    require(expected_argument in (target / "etc/kernel/cmdline").read_text().split(),
            "Kernel installation defaults lack the encrypted root UUID.")
    if phase == "installed":
        require(expected_argument in Path("/proc/cmdline").read_text().split(),
                "The disk-only boot did not use the encrypted root argument.")
        summary = json.loads((target / "var/log/fedora-dde-installer/install-summary.json").read_text())
        require(summary.get("encryption") == {"type": "luks2", "uuid": record["uuid"]},
                "The installed summary does not record this encrypted installation.")
    checked = []
    for relative in ("etc/crypttab", "etc/kernel/cmdline", "etc/fstab", "etc/fedora-dde-installer",
                     "boot/loader/entries", "var/log/fedora-dde-installer"):
        candidate = target / relative
        files = sorted(candidate.rglob("*")) if candidate.is_dir() else [candidate]
        for path in files:
            if path.is_file() and not path.is_symlink():
                require(path.stat().st_size <= 32 * 1024**2, "Unexpectedly large installer configuration or log.")
                require(CRYPT_PASSWORD.encode() not in path.read_bytes(),
                        "The test encryption passphrase leaked into target configuration or logs.")
                checked.append(str(path.relative_to(target)))
    if phase == "target":
        for path in (CONFIG, STATE, CONFIG.with_name("partition-policy.json")):
            require(CRYPT_PASSWORD.encode() not in path.read_bytes(),
                    "The encryption passphrase leaked into installer runtime configuration.")
        wrong = run(["cryptsetup", "open", "--test-passphrase", "--key-file", "-", record["device"]],
                    input_text="DeliberatelyWrongVmPassphrase", check=False)
        require(wrong.returncode == 2, "cryptsetup did not reject the wrong passphrase as an authentication failure.")
        run(["cryptsetup", "open", "--test-passphrase", "--key-file", "-", record["device"]],
            input_text=CRYPT_PASSWORD)
    return {"type": "luks2", "luks_uuid": record["uuid"], "filesystem_uuid": record["filesystem_uuid"],
            "filesystem": record["fstype"], "keyslots": len(keyslots), "kdf": "argon2id",
            "crypttab_key_file": "none", "checked_secret_free_files": checked,
            "wrong_and_correct_passphrase_checked": phase == "target", "phase": phase}


def run_backend(stage):
    descriptor = None
    try:
        extra_env = {}
        if "-luks-" in test_context()["scenario"] and stage in {"preflight", "partition"}:
            descriptor = os.memfd_create("fedora-dde-crypt-passphrase", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, CRYPT_PASSWORD.encode())
            fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_SEAL | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_WRITE)
            extra_env["FEDORA_DDE_CRYPT_FD"] = str(descriptor)
        return run(["/bin/bash", "-c", "source /usr/share/fedora-dde-installer/tools/scripts/init_environment.sh; "
                    'exec /usr/bin/python3 -I "$DI_INSTALL_TOOLS_DIR_ENV/scripts/fedora_backend.py" "$1"',
                    "vmtest", stage], timeout=3600, capture=False, check=False,
                   extra_env=extra_env, pass_fds=(descriptor,) if descriptor is not None else ())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def storage_mountinfo(text):
    """Parse kernel mountinfo, including its octal path escaping and Btrfs dev IDs."""
    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)

    result = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        fields, filesystem = before.split(), after.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            raise ValueError("Malformed kernel mountinfo entry.")
        result.append({"mount_id": fields[0], "parent_id": fields[1], "major_minor": fields[2],
                       "root": unescape(fields[3]), "mountpoint": unescape(fields[4]),
                       "options": fields[5], "propagation": fields[6:], "fstype": filesystem[0],
                       "source": unescape(filesystem[1]), "super_options": filesystem[2]})
    return result


class StorageProbeStopped(Exception):
    """Only the diagnostic sample stops; the original installer error remains."""


class StorageCleanupProbe:
    """Bounded read-only evidence for a failed teardown, never an automatic fix.

    The parent also applies GNU timeout to this whole process group. That hard
    bound covers a procfs/stat operation which cannot honor our soft deadline.
    No cmdline, environment, file contents, keyslot contents or dm table are read.
    """

    def __init__(self, seconds=15, *, proc=Path("/proc"), sys_block=Path("/sys/class/block")):
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.proc, self.sys_block = proc, sys_block
        self.result = {"schema": 1, "reason": "installer-finalize-failed", "collection_complete": False,
                       "budget_seconds": seconds, "errors": [], "commands": {}, "namespaces": [],
                       "process_references": [], "pids_examined": 0, "pids_unavailable": 0,
                       "fds_examined": 0, "namespaces_examined": 0}
        self.sources, self.filesystem_devices, self.block_devices = set(), set(), set()
        self.target = "/target"
        self.namespace_cache = {}
        self.detail_bytes = 0

    def check_budget(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise StorageProbeStopped("The storage evidence collection reached its wall-clock budget.")
        return remaining

    def error(self, stage, error):
        if len(self.result["errors"]) < 32:
            self.result["errors"].append({"stage": stage, "error": str(error)[:500]})

    def checkpoint(self, stage):
        self.result["last_stage"] = stage
        self.result["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
        storage_save_evidence(self.result)
        print("VMTEST_STORAGE_PROBE_STAGE=" + json.dumps({"stage": stage,
            "elapsed_seconds": self.result["elapsed_seconds"]}), flush=True)

    def text(self, path, limit):
        self.check_budget()
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        self.check_budget()
        if len(data) > limit:
            raise StorageProbeStopped(f"The bounded metadata read exceeded {limit} bytes: {path}.")
        return data.decode("utf-8", errors="replace")

    def append_detail(self, destination, value):
        size = len(json.dumps(value, ensure_ascii=True).encode())
        if self.detail_bytes + size > 80 * 1024:
            raise StorageProbeStopped("The storage namespace/reference evidence reached its output limit.")
        destination.append(value)
        self.detail_bytes += size

    def command(self, name, argv, *, cap=3, limit=8192):
        """Fixed read-only commands; anonymous output files avoid unbounded RAM."""
        self.check_budget()
        try:
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                try:
                    value = subprocess.run(argv, stdout=output, stderr=errors, check=False,
                                           timeout=min(cap, self.check_budget()),
                                           env=dict(os.environ, LC_ALL="C", LANG="C"))
                    status = value.returncode
                except subprocess.TimeoutExpired:
                    status = None
                    self.error(name, "The read-only command exceeded its remaining collection budget.")
                output.seek(0)
                errors.seek(0)
                data, detail = output.read(limit + 1), errors.read(2049)
            self.result["commands"][name] = {"status": status,
                "stdout": data[:limit].decode("utf-8", errors="replace"),
                "stderr": detail[:2048].decode("utf-8", errors="replace"),
                "output_truncated": len(data) > limit or len(detail) > 2048}
            if status not in (0, None):
                self.error(name, f"The read-only command exited {status}.")
        except OSError as error:
            self.error(name, error)

    def prepare(self, state):
        record = state.get("encrypted_root") or {}
        self.target = str(state.get("target") or "/target")
        require(self.target == "/target", "Unexpected installation target in storage evidence state.")
        metadata = {key: record.get(key) for key in
                    ("name", "mapper", "device", "uuid", "fstype", "filesystem_uuid") if key in record}
        owned = state.get("owned_mounts", [])
        require(isinstance(owned, list) and len(owned) <= 32 and all(isinstance(point, str)
                and (point == self.target or point.startswith(self.target + "/")) for point in owned),
                "Invalid owned mount metadata in storage evidence state.")
        identity = state.get("mount_identity", {})
        self.result["installation"] = {"phase": state.get("phase"), "target": self.target,
            "owned_mounts": owned, "encrypted_root": metadata,
            "mount_identity": {key: identity.get(key) for key in
                               ("source", "major_minor", "fstype", "uuid", "fsroot") if key in identity}}
        sources = [metadata.get("mapper")]
        root = next((entry for entry in state.get("mounts", []) if entry.get("mountpoint") == "/"), {})
        sources.append(root.get("device"))
        identifier = metadata.get("filesystem_uuid") or root.get("uuid")
        if identifier and re.fullmatch(r"[0-9A-Fa-f-]{4,64}", identifier):
            sources.append("/dev/disk/by-uuid/" + identifier)
        for source in filter(None, sources):
            require(isinstance(source, str) and re.fullmatch(r"/dev/[A-Za-z0-9_./:+-]+", source)
                    and ".." not in Path(source).parts, "Invalid device metadata in storage evidence state.")
            self.sources.update((source, os.path.realpath(source)))
            try:
                value = os.stat(source)
                if stat.S_ISBLK(value.st_mode):
                    self.block_devices.add(value.st_rdev)
            except FileNotFoundError:
                continue  # A disappeared mapper is itself useful evidence.
        identities = [state.get("mount_identity", {})]
        identities.extend(value for value in state.get("mount_identities", {}).values()
                          if value.get("source") in self.sources)
        for identity in identities:
            number = str(identity.get("major_minor", ""))
            if re.fullmatch(r"[0-9]+:[0-9]+", number):
                self.filesystem_devices.add(os.makedev(*map(int, number.split(":"))))
        self.result["expected_filesystem_devices"] = sorted(
            f"{os.major(value)}:{os.minor(value)}" for value in self.filesystem_devices)
        self.result["expected_block_devices"] = sorted(
            f"{os.major(value)}:{os.minor(value)}" for value in self.block_devices)
        self.result["canonical_sources"] = sorted(self.sources)
        return metadata

    def matches_mount(self, mount):
        number = mount["major_minor"]
        device_match = bool(re.fullmatch(r"[0-9]+:[0-9]+", number)) and (
            os.makedev(*map(int, number.split(":"))) in self.filesystem_devices)
        source = mount["source"]
        source_match = source in self.sources or (source.startswith("/dev/") and
                                                  os.path.realpath(source) in self.sources)
        point = mount["mountpoint"]
        path_match = point == self.target or point.startswith(self.target + "/")
        return device_match or source_match or path_match

    def reference(self, path, kind, *, fd=None):
        self.check_budget()
        value = path.stat()  # Metadata only; never open a target or an FD's contents.
        link = os.readlink(path)
        reasons = []
        if stat.S_ISBLK(value.st_mode) and value.st_rdev in self.block_devices:
            reasons.append("mapper-block-device")
        if value.st_dev in self.filesystem_devices:
            reasons.append("target-filesystem-device")
        if link == self.target or link.startswith(self.target + "/"):
            reasons.append("target-path")
        if not reasons:
            return None
        return {"kind": kind, **({"fd": int(fd)} if fd is not None else {}), "path": link[:4096],
                "device": f"{os.major(value.st_dev)}:{os.minor(value.st_dev)}", "matched_by": reasons}

    def scan_process(self, directory):
        self.check_budget()
        pid = int(directory.name)
        namespace = os.readlink(directory / "ns/mnt")
        if namespace not in self.namespace_cache:
            mounts = [mount for mount in storage_mountinfo(self.text(directory / "mountinfo", 256 * 1024))
                      if self.matches_mount(mount)]
            group = {"namespace": namespace, "representative_pid": pid, "pids": [], "mounts": mounts}
            self.namespace_cache[namespace] = group
            self.result["namespaces_examined"] += 1
            if mounts:
                self.append_detail(self.result["namespaces"], group)
        group = self.namespace_cache[namespace]
        if group["mounts"]:
            if len(group["pids"]) >= 1024:
                raise StorageProbeStopped("Too many processes share a matching mount namespace.")
            group["pids"].append(pid)
        references = []
        for kind in ("root", "cwd", "exe"):
            try:
                value = self.reference(directory / kind, kind)
                if value:
                    references.append(value)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError as error:
                self.error(f"pid-{pid}-{kind}", error)
        for descriptor in (directory / "fd").iterdir():
            self.check_budget()
            if not descriptor.name.isdecimal():
                continue
            self.result["fds_examined"] += 1
            if self.result["fds_examined"] > 32768:
                raise StorageProbeStopped("The storage evidence reached its file-descriptor count limit.")
            try:
                value = self.reference(descriptor, "fd", fd=descriptor.name)
                if value:
                    if len(references) >= 64:
                        raise StorageProbeStopped(f"PID {pid} exceeded the matching reference output limit.")
                    references.append(value)
            except (FileNotFoundError, ProcessLookupError):
                continue  # A descriptor may close while the process remains alive.
            except OSError as error:
                self.error(f"pid-{pid}-fd", error)
        if references or group["mounts"]:
            self.append_detail(self.result["process_references"], {
                "pid": pid, "uid": directory.stat().st_uid, "namespace": namespace,
                "comm": self.text(directory / "comm", 256).strip(),
                "cgroup": self.text(directory / "cgroup", 4096).splitlines(), "references": references})

    def collect(self):
        try:
            state = json.loads(self.text(STATE, 1024 * 1024))
            metadata = self.prepare(state)
            self.checkpoint("identity")
            # Capture open counts/holders before slower per-process scans.
            name = metadata.get("name")
            if name:
                require(re.fullmatch(r"luks-[0-9A-Fa-f-]{36}", name) is not None,
                        "Invalid mapper name in storage evidence state.")
                self.command("dm_info", ["dmsetup", "info", "--columns", "--noheadings",
                    "--separator", ":", "--options", "name,major,minor,open,segments,uuid", name], cap=2)
                self.command("crypt_status", ["cryptsetup", "status", name], cap=2)
            holders = []
            for device in self.block_devices:
                self.check_budget()
                for block in self.sys_block.iterdir():
                    try:
                        if self.text(block / "dev", 64).strip() != f"{os.major(device)}:{os.minor(device)}":
                            continue
                        holders.append({"device": block.name,
                                        "holders": sorted(path.name for path in (block / "holders").iterdir())})
                    except (FileNotFoundError, ProcessLookupError):
                        continue
            self.result["block_holders"] = holders
            self.checkpoint("device-open-count")
            for directory in self.proc.iterdir():
                self.check_budget()
                if not directory.name.isdecimal():
                    continue
                self.result["pids_examined"] += 1
                if self.result["pids_examined"] > 2048:
                    raise StorageProbeStopped("The storage evidence reached its process count limit.")
                try:
                    self.scan_process(directory)
                except (FileNotFoundError, ProcessLookupError):
                    # Exited processes and kernel threads without a userspace
                    # mount namespace both have absent /proc metadata.
                    self.result["pids_unavailable"] += 1
                except (OSError, ValueError) as error:
                    self.error("pid-" + directory.name, error)
            self.checkpoint("process-namespaces-and-references")
            self.command("kernel_journal", ["journalctl", "-k", "-b", "--no-pager", "-n", "200",
                                           "-o", "short-monotonic"], cap=3, limit=48 * 1024)
            self.check_budget()
            self.result["collection_complete"] = not self.result["errors"]
        except (OSError, ValueError, RuntimeError, StorageProbeStopped) as error:
            self.error("collection", error)
        finally:
            self.checkpoint("finished")
        return self.result


def storage_save_evidence(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=True)
    require(len(data.encode()) <= STORAGE_EVIDENCE_LIMIT, "Storage evidence exceeded its total output limit.")
    destination = RUNTIME / STORAGE_EVIDENCE_NAME
    temporary = destination.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(data + "\n")
    os.replace(temporary, destination)


def storage_read_evidence():
    path = RUNTIME / STORAGE_EVIDENCE_NAME
    require(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.geteuid()
            and not path.stat().st_mode & 0o077, "Invalid private storage evidence file.")
    with path.open("rb") as stream:
        data = stream.read(STORAGE_EVIDENCE_LIMIT + 2)
    require(len(data) <= STORAGE_EVIDENCE_LIMIT + 1, "Storage evidence exceeded its read limit.")
    return json.loads(data)


def capture_storage_cleanup_failure(status):
    """Preserve the original failure even if read-only diagnosis times out."""
    evidence = {"schema": 1, "reason": "installer-finalize-failed", "backend_exit_status": status,
                "collection_complete": False, "last_stage": "starting", "errors": []}
    try:
        storage_save_evidence(evidence)
        # Default GNU timeout process groups are intentional: --foreground
        # would leave a stuck metadata/command child outside the hard bound.
        completed = run(["timeout", "--signal=TERM", "--kill-after=2s", "18s",
                         sys.executable, "-I", str(Path(__file__).resolve()), "storage-cleanup-probe"],
                        check=False, capture=False, timeout=22)
        evidence = storage_read_evidence()
        evidence["backend_exit_status"] = status
        evidence["collector_exit_status"] = completed.returncode
        if completed.returncode:
            evidence["collection_complete"] = False
            evidence.setdefault("errors", []).append({"stage": "collector",
                "error": f"The bounded evidence process exited {completed.returncode}."})
    except Exception as error:
        evidence["collection_complete"] = False
        evidence.setdefault("errors", []).append({"stage": "collector", "error": str(error)[:500]})
    try:
        storage_save_evidence(evidence)
    except Exception as error:
        evidence["save_error"] = str(error)[:500]
    print("VMTEST_STORAGE_CLEANUP_EVIDENCE=" + json.dumps(evidence, sort_keys=True), flush=True)


def pam_check(user):
    """Exercise the packaged DDM password stack without fabricating a session."""
    password = "liveuser" if user == "liveuser" else PASSWORD
    lib = C.CDLL("libpam.so.0")
    libc = C.CDLL(None)
    class Message(C.Structure):
        _fields_ = [("msg_style", C.c_int), ("msg", C.c_char_p)]
    class Response(C.Structure):
        _fields_ = [("resp", C.c_void_p), ("resp_retcode", C.c_int)]
    Callback = C.CFUNCTYPE(C.c_int, C.c_int, C.POINTER(C.POINTER(Message)),
                          C.POINTER(C.POINTER(Response)), C.c_void_p)
    class Conversation(C.Structure):
        _fields_ = [("conv", Callback), ("appdata_ptr", C.c_void_p)]
    libc.calloc.argtypes, libc.calloc.restype = [C.c_size_t, C.c_size_t], C.c_void_p
    libc.strdup.argtypes, libc.strdup.restype = [C.c_char_p], C.c_void_p
    lib.pam_start.argtypes = [C.c_char_p, C.c_char_p, C.POINTER(Conversation), C.POINTER(C.c_void_p)]
    lib.pam_authenticate.argtypes = lib.pam_acct_mgmt.argtypes = [C.c_void_p, C.c_int]
    lib.pam_end.argtypes = [C.c_void_p, C.c_int]
    def attempt(secret):
        @Callback
        def converse(count, messages, responses, data):
            if not 0 < count < 32:
                return 19
            block = libc.calloc(count, C.sizeof(Response))
            if not block:
                return 5
            answer = C.cast(block, C.POINTER(Response))
            for index in range(count):
                style = messages[index].contents.msg_style
                if style in (1, 2):
                    answer[index].resp = libc.strdup((secret if style == 1 else user).encode())
                elif style not in (3, 4):
                    return 19
            responses[0] = answer
            return 0
        conv, handle = Conversation(converse, None), C.c_void_p()
        status = lib.pam_start(b"ddm", user.encode(), C.byref(conv), C.byref(handle))
        require(status == 0, "pam_start(ddm) failed.")
        final_status = 0
        try:
            auth = lib.pam_authenticate(handle, 0)
            account = lib.pam_acct_mgmt(handle, 0) if auth == 0 else None
            final_status = auth or account or 0
            return auth, account
        finally:
            lib.pam_end(handle, final_status)
    require(attempt(password) == (0, 0), "DDM PAM rejected the correct password/account.")
    wrong, _ = attempt("IncorrectVmPassword")
    require(wrong != 0, "DDM PAM accepted an incorrect password.")
    require(attempt(password) == (0, 0), "DDM PAM could not authenticate after the negative check.")
    return {"service": "ddm", "correct_password": "accepted", "incorrect_password": "rejected",
            "session": "verified separately through the real graphical login"}


def desktop_assets(user):
    """Read effective defaults and the compositor's generated user background."""
    require(user in {"liveuser", USERNAME}, "Unexpected desktop asset test user.")
    account = pwd.getpwnam(user)
    runtime = Path(f"/run/user/{account.pw_uid}")
    require((runtime / "bus").exists(), "The desktop user's session bus is missing.")
    result = json.loads(run(["/usr/libexec/fedora-dde-check-desktop-assets"]).stdout)
    appearance_prefix = ["runuser", "-u", user, "--", "env", "HOME=" + account.pw_dir,
              "XDG_RUNTIME_DIR=" + str(runtime),
              "DBUS_SESSION_BUS_ADDRESS=unix:path=" + str(runtime / "bus"),
              "dde-dconfig", "get"]
    compositor_pid = int(run(["systemctl", "show", "treeland.service", "-p", "MainPID", "--value"]).stdout.strip())
    compositor = [p for p in processes() if p["pid"] == compositor_pid and p["exe"] == "/usr/bin/treeland"]
    require(len(compositor) == 1, "Cannot identify the actual Treeland service process.")
    compositor_account = pwd.getpwuid(compositor[0]["uid"])
    # These Treeland keys are non-global DConfig values. The daemon running
    # the compositor owns the cache; /<login-user> is only its subpath. Read
    # through that actual UID, not a different cache belonging to login-user.
    compositor_prefix = ["runuser", "-u", compositor_account.pw_name, "--", "env",
                         "HOME=" + compositor_account.pw_dir, "dde-dconfig", "get"]
    requests = {
        "treeland_default": ["-a", "org.deepin.dde.treeland", "-r", "org.deepin.dde.treeland.user",
                             "-s", "/" + user, "-k", "defaultBackground"],
        "appearance_default": ["-a", "org.deepin.dde.appearance", "-r", "org.deepin.dde.appearance",
                               "-k", "Background_Uris"],
        "generated_wallpaper": ["-a", "org.deepin.dde.treeland", "-r", "org.deepin.dde.treeland.user",
                                "-s", "/" + user, "-k", "wallpaperConfig"],
    }
    observed = {}
    missing_defaults = ("/usr/share/backgrounds/default_background.jpg",
                        "/usr/share/backgrounds/deepin/desktop.jpg",
                        "/usr/share/wallpapers/deepin/deepin-default.jpg")
    for name, request in requests.items():
        prefix = appearance_prefix if name == "appearance_default" else compositor_prefix
        deadline = time.monotonic() + 20
        while True:
            value = run(prefix + request, timeout=30).stdout.strip()
            # wallpaperConfig is generated asynchronously by the compositor.
            # Only an empty value may be retried; wrong nonempty paths fail.
            if name != "generated_wallpaper" or value not in {"", '""', '"{}"', '"[]"'}:
                break
            require(time.monotonic() < deadline, "Treeland did not generate the user's wallpaper configuration.")
            time.sleep(1)
        require(len(value) <= 131072 and result["wallpaper"] in value
                and not any(path in value for path in missing_defaults),
                f"The effective user background is missing or still references an absent file: {name}: {value[:2000]}")
        # Retain native CLI output instead of guessing its display encoding.
        # The expected resource is not a CLI argument: it must come from the
        # actual value returned for this one requested key.
        observed[name] = value
    result.update(user=user, uid=account.pw_uid, compositor_pid=compositor_pid,
                  compositor_uid=compositor_account.pw_uid, effective_dconfig=observed,
                  effective_user_background_verified=True)
    return result


def diagnostics():
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    commands = {"journal": ["journalctl", "-b", "--no-pager", "-n", "250", "-o", "short-monotonic"],
                "ddm": ["journalctl", "-b", "-u", "ddm.service", "-u", "treeland.service", "--no-pager", "-n", "200"],
                "failed_units": ["systemctl", "--failed", "--no-pager"],
                "sessions": ["loginctl", "list-sessions", "--no-pager"],
                "process_labels": ["ps", "-eZ"],
                "avc": ["ausearch", "-m", "AVC,USER_AVC", "-ts", "boot", "--raw"],
                "coredumps": ["coredumpctl", "list", "--no-pager", "_BOOT_ID=" + boot_id],
                "disks": ["lsblk", "-f"], "mounts": ["findmnt"],
                "treeland_units": ["systemctl", "cat", "treeland.service"],
                "wallpaper_factory": ["journalctl", "-b", "--no-pager", "-n", "100", "-o", "short-monotonic",
                                      "_EXE=/usr/bin/treeland-wallpaper-factory"],
                "desktop_asset_files": ["stat", "--", "/usr/share/backgrounds/images/earth_from_space.jpg",
                                        "/usr/share/pixmaps/fedora-remix-logos/Fedora-Remix-Black-Blue.png",
                                        "/usr/share/pixmaps/fedora-remix-logos/Fedora-Remix-Transparent-Blue.png",
                                        "/usr/share/deepin/distribution.info"]}
    for user in ("liveuser", USERNAME):
        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            continue
        commands[f"dde_shell_{user}_journal"] = ["journalctl", "-b", "--no-pager", "-n", "200",
            "-o", "short-monotonic", "_COMM=dde-shell", f"_UID={uid}"]
        commands[f"desktop_plugin_{user}_journal"] = ["journalctl", "-b", "--no-pager", "-n", "200",
            "-o", "short-monotonic", f"_UID={uid}",
            "_SYSTEMD_USER_UNIT=dde-shell-plugin@org.deepin.ds.desktop.service"]
        # coredumpctl has no --boot option. Explicit journal matches identify
        # this boot/user, and -1 bounds info to the latest matching crash.
        commands[f"dde_shell_{user}_coreinfo"] = ["coredumpctl", "--no-pager", "-1", "info",
            "_BOOT_ID=" + boot_id, f"COREDUMP_UID={uid}", "COREDUMP_EXE=/usr/bin/dde-shell"]
        commands[f"clipboard_{user}_journal"] = ["journalctl", "-b", "--no-pager", "-n", "100",
            "-o", "short-monotonic", f"_UID={uid}", "_SYSTEMD_USER_UNIT=dde-clipboard.service",
            "+", f"_BOOT_ID={boot_id}", f"_UID={uid}", "_SYSTEMD_USER_UNIT=dde-clipboard-daemon.service"]
        user_prefix = ["runuser", "-u", user, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}",
                       f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"]
        commands[f"desktop_user_units_{user}"] = user_prefix + ["systemctl", "--user", "show",
            "dde-clipboard.service", "dde-clipboard-daemon.service",
            "dde-shell-plugin@org.deepin.ds.desktop.service", "--no-pager",
            "-p", "Id,ActiveState,SubState,Result,MainPID,BusName,ExecMainStatus"]
        commands[f"user_bus_owners_{user}"] = user_prefix + ["busctl", "--user", "list", "--no-pager"]
    result = {"dde_shell_processes": [p for p in processes() if p["exe"] == "/usr/bin/dde-shell"]}
    if (RUNTIME / STORAGE_EVIDENCE_NAME).exists():
        try:
            result["storage_cleanup"] = storage_read_evidence()
        except (OSError, ValueError, RuntimeError) as error:
            result["storage_cleanup"] = {"collection_complete": False, "error": str(error)[:500]}
    deadline = time.monotonic() + 160
    # Collect the specific crash trace before general journal output can spend
    # the bounded diagnostics budget. Never request or export core bytes.
    ordered = sorted(commands, key=lambda name: (not name.endswith("_coreinfo"),
                                                 not name.startswith("desktop_plugin"), name))
    for name in ordered:
        command = commands[name]
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result[name] = {"error": "The bounded diagnostics collection deadline expired."}
                continue
            value = run(command, check=False, timeout=min(15, remaining))
            output = value.stdout or ""
            limit = 256 * 1024 if name.endswith("_coreinfo") else 45000
            # Keep the top of core info (including its first stack frames),
            # rather than silently retaining only the tail of a large trace.
            retained = output[:limit] if name.endswith("_coreinfo") else output[-limit:]
            result[name] = {"status": value.returncode, "stdout": retained,
                            "stdout_characters": len(output), "stdout_truncated": len(output) > limit,
                            "stderr": (value.stderr or "")[-3000:]}
        except (OSError, subprocess.TimeoutExpired) as error:
            result[name] = {"error": str(error)}
    if STATE.exists():
        try:
            data = json.loads(STATE.read_text())
            result["installer_state"] = {k: data.get(k) for k in
                ("phase", "source", "target", "owned_mounts", "mounts", "install_profile", "user", "kernels")}
        except (OSError, ValueError) as error:
            result["installer_state"] = {"error": str(error)}
    return result


def main():
    os.umask(0o077)
    args = sys.argv[1:]
    require(bool(args), "Missing VM check action.")
    action = args.pop(0)
    if action == "session":
        budget = 30
        if "--probe-budget-seconds" in args:
            require(len(args) >= 3 and args[-2] == "--probe-budget-seconds"
                    and args.count("--probe-budget-seconds") == 1, "Invalid session probe budget option.")
            budget = args[-1]
            args = args[:-2]
        require(len(args) in {1, 3}, "Expected a user and optional monotonic checkpoint/boot ID for session.")
        result = session(*args, budget_seconds=budget)
        print("VMTEST_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
        return
    authorize()
    if action == "baseline":
        result = baseline(*args)
    elif action == "desktop-assets":
        result = desktop_assets(*args)
    elif action == "prepare":
        result = prepare()
    elif action == "account":
        result = configure_account()
    elif action == "installed-state":
        result = installed_state()
    elif action == "encryption-check":
        result = encryption_check(*args)
    elif action == "pam":
        result = pam_check(*args)
    elif action == "diagnostics":
        result = diagnostics()
    elif action == "storage-cleanup-probe":
        require(not args, "Storage cleanup evidence takes no command arguments.")
        StorageCleanupProbe().collect()
        return
    elif action == "stage":
        require(len(args) == 1 and args[0] in STAGES, "Invalid backend stage.")
        stage = args[0]
        print(f"VMTEST_BACKEND_START {stage}", flush=True)
        completed = run_backend(stage)
        if stage == "finalize" and completed.returncode:
            try:
                capture_storage_cleanup_failure(completed.returncode)
            except Exception as error:
                print("VMTEST_STORAGE_PROBE_ERROR=" + str(error)[:500], flush=True)
        require(completed.returncode == 0, f"Actual installer backend {stage} failed ({completed.returncode}).")
        state = json.loads(STATE.read_text())
        namespace = Path("/proc/self/ns/mnt").stat()
        identity = {"device": namespace.st_dev, "inode": namespace.st_ino}
        require(state.get("mount_namespace") == identity,
                "The completed backend stage did not record this installation namespace.")
        result = {"stage": stage, "status": "passed", "state": state.get("phase"),
                  "mount_namespace": identity}
    else:
        raise RuntimeError("Unknown VM check action.")
    print("VMTEST_RESULT=" + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("VMTEST_ERROR=" + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
