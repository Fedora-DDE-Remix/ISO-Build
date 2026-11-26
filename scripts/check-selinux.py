#!/usr/bin/python3
"""Validate Fedora SELinux policy and the labels that enter the Live payload.

The policy check runs inside the compose chroot. The only mutating mode, label,
accepts the independently mounted /mnt/sysimage compose root and runs setfiles
inside that chroot. It never relabels the builder's root filesystem.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


PROFILE = {"schema": 1, "selinux": "enforcing", "pam": "fedora"}
MODULES = {"ddm", "dde_daemon", "dde_api", "deepin_system_monitor"}
POLICY_RPMS = ("ddm-selinux", "dde-daemon-selinux", "dde-api-selinux",
               "deepin-system-monitor-selinux")
LABELS = {
    "usr/bin/bash": "shell_exec_t",
    "usr/lib/systemd/systemd": "init_exec_t",
    "etc/passwd": "passwd_file_t",
    "usr/bin/ddm": "xdm_exec_t",
    "usr/libexec/ddm-helper": "xdm_exec_t",
    "usr/lib/systemd/system/treeland.service": "xdm_unit_file_t",
}
DIRECTORY_PATHS = ("dev", "proc", "sys", "run")
CONTEXTS = "etc/selinux/targeted/contexts/files/file_contexts"
COMMAND_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}


class CheckError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def run(*arguments: str) -> str:
    completed = subprocess.run(arguments, env=COMMAND_ENV, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-3000:]
        raise CheckError(f"{arguments[0]} failed (exit {completed.returncode}): {detail}")
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.stdout


def image_path(root: Path, relative: str, *, directory: bool = False) -> Path:
    """All checked paths are real files/directories; refuse symlink escapes."""
    path = root
    for component in Path(relative).parts:
        path /= component
        require(not path.is_symlink(), f"Unexpected symlink in {relative}")
    require(path.is_dir() if directory else path.is_file(), f"Missing image {'directory' if directory else 'file'}: {relative}")
    return path


def regular(root: Path, relative: str) -> Path:
    return image_path(root, relative)


def configuration(root: Path) -> None:
    config = regular(root, "etc/selinux/config").read_text()
    for key, expected in (("SELINUX", "enforcing"), ("SELINUXTYPE", "targeted")):
        values = re.findall(rf"(?m)^\s*{key}\s*=\s*([A-Za-z0-9_-]+)\s*(?:#.*)?$", config)
        require(values == [expected], f"The image must explicitly set {key}={expected}")
    path = regular(root, "etc/fedora-dde-installer/install-profile.json")
    metadata = path.stat()
    require(metadata.st_uid == 0 and stat.S_IMODE(metadata.st_mode) == 0o644,
            "The installation profile must be root-owned with mode 0644")
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and type(value.get("schema")) is int and value == PROFILE,
            "The image must select the enforcing/Fedora installation profile")


def policy_file(root: Path) -> Path:
    directory = root / "etc/selinux/targeted/policy"
    candidates = []
    for path in directory.glob("policy.*"):
        version = path.name.removeprefix("policy.")
        if version.isdecimal():
            regular(root, str(path.relative_to(root)))
            require(path.stat().st_size > 0, "The compiled SELinux policy is empty")
            candidates.append((int(version), path))
    require(bool(candidates), "The image has no compiled targeted SELinux policy")
    return max(candidates)[1]


def directory_contexts(root: Path) -> dict[str, str]:
    """Look up on-disk mountpoints, not the genfs labels of mounted pseudo-FS."""
    contexts = regular(root, CONTEXTS)
    require(contexts.stat().st_size > 0, "The targeted file-context map is empty")
    # libselinux also reads local, homedirs, substitution and compiled sidecars.
    # These must all come from the image and must not escape through symlinks.
    for path in contexts.parent.glob("file_contexts*"):
        regular(root, str(path.relative_to(root)))
    result = {}
    for relative in DIRECTORY_PATHS:
        image_path(root, relative, directory=True)
        expected = run("matchpathcon", "-N", "-n", "-m", "d", "-f", str(contexts), "/" + relative).strip()
        require(re.fullmatch(r"system_u:object_r:[A-Za-z0-9_]+:s0", expected) is not None,
                f"The image has no valid persistent directory context for /{relative}: {expected!r}")
        result[relative] = expected
    return result


def verify_labels(root: Path) -> None:
    configuration(root)
    expected_paths = {relative: f"system_u:object_r:{kind}:s0" for relative, kind in LABELS.items()}
    expected_paths.update(directory_contexts(root))
    for relative, expected in expected_paths.items():
        path = image_path(root, relative, directory=relative in DIRECTORY_PATHS)
        try:
            actual = os.getxattr(path, "security.selinux", follow_symlinks=False).rstrip(b"\0").decode("ascii")
        except (OSError, UnicodeError) as error:
            raise CheckError(f"Cannot read the payload's SELinux label: /{relative}: {error}") from error
        require(actual == expected, f"Incorrect payload label on /{relative}: {actual!r}; expected {expected}")
        print(f"PASS label /{relative}: {actual}")


def verify_policy() -> None:
    """Check the policy store, not the builder kernel's loaded SELinux policy."""
    require(os.geteuid() == 0, "The compose policy check requires root")
    root = Path("/")
    configuration(root)
    print(run("rpm", "-q", *POLICY_RPMS).rstrip())
    listing = run("semodule", "-l")
    enabled = {parts[0] for line in listing.splitlines()
               if (parts := line.split()) and not any("disabled" in item for item in parts[1:])}
    require(MODULES <= enabled, f"Required SELinux modules are not registered: {sorted(MODULES - enabled)}")
    policy = policy_file(root)
    contexts = regular(root, CONTEXTS)
    require(contexts.stat().st_size > 0, "The targeted file-context map is empty")
    expected_paths = dict(LABELS)
    for relative, expected in directory_contexts(root).items():
        print(f"PASS persistent mountpoint context /{relative}: {expected}")
    # The maintained policies deliberately map these helpers to bin_t. Use
    # actual packaged executables instead of guessing their changing names.
    for relative in ("usr/lib/deepin-daemon", "usr/lib/deepin-api"):
        directory = image_path(root, relative, directory=True)
        helpers = [path for path in directory.rglob("*") if path.is_file()
                   and not path.is_symlink() and path.stat().st_mode & 0o111]
        require(bool(helpers), f"The DDE image has no executable helpers in /{relative}")
        expected_paths.update({str(path.relative_to(root)): "bin_t" for path in helpers})
    paths = []
    for relative, kind in expected_paths.items():
        path = regular(root, relative)
        expected = f"system_u:object_r:{kind}:s0"
        actual = run("matchpathcon", "-n", str(path)).strip()
        require(actual == expected, f"The installed policy maps {path} to {actual!r}, expected {expected}")
        paths.append(str(path))
    # -n does not relabel; -c validates contexts against the image's compiled
    # policy, including on a builder whose kernel has SELinux disabled.
    run("setfiles", "-n", "-c", str(policy), str(contexts), *paths)
    print("PASS registered SELinux modules: " + ", ".join(sorted(MODULES)))
    print(f"PASS persistent compiled policy and file contexts: {policy}")


def label_image(root: Path) -> None:
    require(os.geteuid() == 0, "Offline image labelling requires root")
    require(root == Path("/mnt/sysimage") and not root.is_symlink()
            and root.resolve() == root and root.is_dir(),
            "Labelling is restricted to the real /mnt/sysimage compose mount")
    require(os.path.ismount(root) and root.stat().st_dev != Path("/").stat().st_dev,
            "The compose image must be a distinct mounted filesystem")
    entries = json.loads(run("findmnt", "--json", "--mountpoint", str(root),
                             "--output", "TARGET,FSTYPE,OPTIONS")).get("filesystems", [])
    require(len(entries) == 1 and entries[0].get("target") == str(root)
            and entries[0].get("fstype") in {"ext4", "xfs", "btrfs"}
            and "rw" in entries[0].get("options", "").split(","),
            "The compose image must be a writable disk filesystem at /mnt/sysimage")
    release = regular(root, "usr/lib/os-release").read_text()
    require(re.search(r'''(?m)^ID=["']?fedora["']?$''', release) is not None
            and re.search(r'''(?m)^VERSION_ID=["']?45["']?$''', release) is not None,
            "Offline labelling is only supported for the Fedora 45 image")
    configuration(root)
    # The final post runs after account-test cleanup and resolver restoration.
    require(not (root / "root/.fedora-dde-iso-build").exists(),
            "Finish PAM-test cleanup before labelling the image")
    require(not re.search(r"(?m)^liveuser:", regular(root, "etc/passwd").read_text()),
            "The read-only image must not contain the temporary Live user")
    policy = "/" + str(policy_file(root).relative_to(root))
    regular(root, CONTEXTS)
    # A non-recursive bind exposes the image's underlying dev/proc/sys/run
    # directories, without Anaconda's runtime submounts. Never use rbind here.
    # Do not use TemporaryDirectory: its recursive cleanup would delete image
    # contents if unmount failed. An unsuccessful unmount leaves the alias alone.
    alias = Path(tempfile.mkdtemp(prefix="fedora-dde-label-", dir="/run"))
    try:
        run("mount", "--bind", str(root), str(alias))
        run("mount", "--make-private", str(alias))
        mounts = json.loads(run("findmnt", "--json", "--mountpoint", str(alias),
                                "--submounts", "--output", "TARGET,FSTYPE")).get("filesystems", [])
        require(len(mounts) == 1 and mounts[0].get("target") == str(alias)
                and not mounts[0].get("children") and alias.stat().st_dev == root.stat().st_dev,
                "The labelling alias must contain only the image filesystem, with no runtime submounts")
        run("chroot", str(alias), "setfiles", "-F", "-c", policy, "/" + CONTEXTS, "/")
        verify_labels(alias)
    finally:
        if os.path.ismount(alias):
            run("umount", str(alias))
        # rmdir never follows or recursively removes anything below the alias.
        alias.rmdir()
    print("PASS offline Fedora 45 image relabel completed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("policy", "label", "verify", "paths"))
    parser.add_argument("root", nargs="?")
    args = parser.parse_args()
    try:
        if args.mode in {"label", "verify"}:
            require(args.root is not None, "This mode requires an image-root path")
            root = Path(args.root).absolute()
            require(root != Path("/") and root.is_dir() and not root.is_symlink()
                    and root.resolve() == root, "Use a real, separate image-root directory")
            (label_image if args.mode == "label" else verify_labels)(root)
        else:
            require(args.root is None, "This mode does not accept an image-root path")
            if args.mode == "paths":
                print("\n".join((*LABELS, *DIRECTORY_PATHS, str(Path(CONTEXTS).parent))))
            else:
                verify_policy()
    except (CheckError, OSError, ValueError) as error:
        print(f"FAIL SELinux image check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
