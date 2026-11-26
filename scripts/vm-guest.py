#!/usr/bin/python3
"""Guest-only checks for test-install-vm.py; never installed into the ISO.

The public password below belongs only to a disposable QEMU test disk. Every
entry point requires the VM's DMI marker and an authorization file in /run.
"""

from __future__ import annotations

import ctypes as C
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import time


RUNTIME = Path("/run/fedora-dde-vmtest")
INSTALLER = Path("/usr/share/fedora-dde-installer/tools")
CONFIG = Path("/run/fedora-dde-installer/installer.conf")
STATE = CONFIG.with_name("state.json")
CONFIG_TOOL = "/usr/bin/fedora-dde-installer-config"
USERNAME = "vmtest"
PASSWORD = "FedoraVmtest2026"
HOSTNAME = "fedora-dde-vmtest"
POLICIES = {"ddm", "dde_daemon", "dde_api", "deepin_system_monitor"}
STAGES = ("preflight", "partition", "copy", "system", "ready", "configure", "finalize")
SCENARIOS = {"uefi-btrfs", "bios-ext4", "bios-mbr-ext4", "uefi-xfs-home-swap", "uefi-preserve", "uefi-small"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(argv, *, check=True, timeout=120, capture=True):
    result = subprocess.run(argv, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None,
                            timeout=timeout, env=dict(os.environ, LC_ALL="C", LANG="C"))
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} exited {result.returncode}: {(result.stderr or '')[-3000:]}")
    return result


def authorize():
    require(os.geteuid() == 0, "VM checks must run through normal guest sudo authentication.")
    require(Path("/sys/class/dmi/id/product_serial").read_text().strip() == "FDDESMOKE",
            "This is not the isolated test-install-vm QEMU guest.")
    marker = RUNTIME / "authorized"
    require(marker.is_file() and not marker.is_symlink()
            and marker.stat().st_uid == 0 and not marker.stat().st_mode & 0o077
            and marker.read_text().strip() == "fedora-dde-vmtest-v1", "Missing private VM authorization marker.")
    require(run(["systemd-detect-virt"]).stdout.strip() in {"qemu", "kvm"}, "Expected a QEMU/KVM guest.")


def test_context():
    value = json.loads((RUNTIME / "context.json").read_text())
    require(value.get("scenario") in SCENARIOS, "Invalid VM partition scenario.")
    return value


def properties(command):
    return dict(line.split("=", 1) for line in run(command).stdout.splitlines() if "=" in line)


def processes():
    result = []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            result.append({"pid": int(path.name), "uid": path.stat().st_uid,
                           "comm": (path / "comm").read_text().strip(),
                           "exe": os.readlink(path / "exe"),
                           "label": (path / "attr/current").read_text().strip()})
        except (OSError, UnicodeError):
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
    cmdline = Path("/proc/cmdline").read_text().strip()
    root = mount_info("/")
    result = {"phase": phase, "scenario": scenario, "uefi": uefi,
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "cmdline": cmdline, "root": root, "profile": profile, "selinux": security,
              "build_info": json.loads(Path("/usr/share/fedora-dde-remix/build-info.json").read_text()),
              "packages": run(["rpm", "-q", "ddm", "treeland", "dde-session", "dde-shell",
                                "selinux-policy-targeted"], check=False).stdout.splitlines()}
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
        wanted_fs = "ext4" if scenario.startswith("bios-") else "xfs" if scenario == "uefi-xfs-home-swap" else "btrfs"
        require(root["fstype"] == wanted_fs and "rw" in root["options"].split(","), "Installed root filesystem is wrong or not writable.")
        result["boot_filesystems"] = installed_boot_mounts(test.get("installation", {}), uefi)
        home = mount_info("/home")
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


def session(user):
    uid = pwd.getpwnam(user).pw_uid
    sessions = []
    for line in run(["loginctl", "list-sessions", "--no-legend", "--no-pager"]).stdout.splitlines():
        if not line.split():
            continue
        sid = line.split()[0]
        command = ["loginctl", "show-session", sid, "--no-pager"]
        data = properties(command)
        if data.get("Name") == user:
            sessions.append(data)
    matching = [s for s in sessions if s.get("Service") == "ddm" and s.get("Type") == "wayland"
                and s.get("Class") == "user" and s.get("Active") == "yes" and s.get("State") == "active"]
    procs = processes()
    shell = [p for p in procs if p["uid"] == uid and p["comm"] == "dde-shell"]
    # Treeland can be a system compositor managed by DDM. Do not incorrectly
    # require its UID to equal the authenticated desktop user's UID.
    compositor = [p for p in procs if p["comm"] == "treeland"]
    return {"user": user, "uid": uid, "ready": bool(matching and shell and compositor),
            "sessions": sessions, "ddm_sessions": matching, "dde_shell": shell, "treeland": compositor,
            "wayland_sockets": [str(p) for p in Path(f"/run/user/{uid}").glob("wayland-*") if p.is_socket()]}


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
    bios_area = scenario == "bios-ext4"
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
            bounds += [(2649 * 2048, last, "btrfs", "/", "ROOT")]
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
                     "isstartpoint": True, "filesystem": filesystem, "mountPoint": mount, "isneedformat": True})
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
    disk_size = 16_000_000_000 if scenario == "uefi-small" else 64 * 1024**3
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
    require(state.get("phase") == "finalized" and not state.get("owned_mounts"), "Installation did not finalize cleanly.")
    for key in ("DI_PASSWORD", "DI_ROOT_PASSWORD", "DI_CRYPT_PASSWORD"):
        require(not run([CONFIG_TOOL, "get", str(CONFIG), "", key]).stdout, "An installer secret was not cleared.")
    root = next(item for item in state["mounts"] if item["mountpoint"] == "/")
    uuid = run(["blkid", "-s", "UUID", "-o", "value", root["device"]]).stdout.strip()
    require(bool(re.fullmatch(r"[A-Fa-f0-9-]+", uuid)), "Installed root UUID is invalid.")
    swap = next((item for item in state["mounts"] if item["mountpoint"] == "swap"), None)
    swap_uuid = run(["blkid", "-s", "UUID", "-o", "value", swap["device"]]).stdout.strip() if swap else None
    return {"phase": state["phase"], "root_uuid": uuid, "swap_uuid": swap_uuid, "mounts": state["mounts"],
            "installation_id": state["installation_id"], "install_profile": state["install_profile"],
            "kernels": state.get("kernels", []), "kernel_options": state.get("kernel_options", ""),
            "owned_mounts": state["owned_mounts"], "secrets_cleared": True}


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


def diagnostics():
    commands = {"journal": ["journalctl", "-b", "--no-pager", "-n", "250", "-o", "short-monotonic"],
                "ddm": ["journalctl", "-b", "-u", "ddm.service", "-u", "treeland.service", "--no-pager", "-n", "200"],
                "failed_units": ["systemctl", "--failed", "--no-pager"],
                "sessions": ["loginctl", "list-sessions", "--no-pager"],
                "process_labels": ["ps", "-eZ"],
                "avc": ["ausearch", "-m", "AVC,USER_AVC", "-ts", "boot", "--raw"],
                "coredumps": ["coredumpctl", "list", "--no-pager", "--since", "today"],
                "disks": ["lsblk", "-f"], "mounts": ["findmnt"],
                "treeland_units": ["systemctl", "cat", "treeland.service"]}
    result = {}
    for name, command in commands.items():
        try:
            value = run(command, check=False, timeout=15)
            result[name] = {"status": value.returncode, "stdout": (value.stdout or "")[-45000:],
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
    authorize()
    args = sys.argv[1:]
    require(bool(args), "Missing VM check action.")
    action = args.pop(0)
    if action == "baseline":
        result = baseline(*args)
    elif action == "session":
        result = session(*args)
    elif action == "prepare":
        result = prepare()
    elif action == "account":
        result = configure_account()
    elif action == "installed-state":
        result = installed_state()
    elif action == "pam":
        result = pam_check(*args)
    elif action == "diagnostics":
        result = diagnostics()
    elif action == "stage":
        require(len(args) == 1 and args[0] in STAGES, "Invalid backend stage.")
        stage = args[0]
        print(f"VMTEST_BACKEND_START {stage}", flush=True)
        completed = run(["/bin/bash", "-c", "source /usr/share/fedora-dde-installer/tools/scripts/init_environment.sh; "
                         'exec /usr/bin/python3 -I "$DI_INSTALL_TOOLS_DIR_ENV/scripts/fedora_backend.py" "$1"',
                         "vmtest", stage],
                        timeout=3600, capture=False, check=False)
        require(completed.returncode == 0, f"Actual installer backend {stage} failed ({completed.returncode}).")
        result = {"stage": stage, "status": "passed", "state": json.loads(STATE.read_text()).get("phase")}
    else:
        raise RuntimeError("Unknown VM check action.")
    print("VMTEST_RESULT=" + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("VMTEST_ERROR=" + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
