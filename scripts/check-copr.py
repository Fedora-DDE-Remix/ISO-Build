#!/usr/bin/python3
"""Verify the persistent, package-owned Remix repository without network access."""

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import stat
import subprocess


REPO_ID = "copr:copr.fedorainfracloud.org:mozixun:Fedora-DDE-Remix"
REPO_PATH = "etc/yum.repos.d/_" + REPO_ID + ".repo"
KEY_PATH = "etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-dde-remix"
KEY_SHA256 = "eb44eeabc2a5546db7b72d9f5adc6d9c17f7a4b7456e579e3dc0d964e2455200"
BASE_URL = "https://download.copr.fedorainfracloud.org/results/mozixun/Fedora-DDE-Remix/fedora-$releasever-$basearch/"


def regular(root, relative):
    path = root / relative
    for parent in reversed(path.relative_to(root).parents):
        current = root / parent
        if current.is_symlink() or not current.is_dir():
            raise ValueError("Repository configuration has an invalid parent: " + str(current))
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o644):
        raise ValueError("Repository configuration must be a root-owned mode 0644 regular file: " + relative)
    return path


def verify(root):
    repo = regular(root, REPO_PATH)
    key = regular(root, KEY_PATH)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string(repo.read_text(encoding="utf-8"))
    if parser.sections() != [REPO_ID]:
        raise ValueError("Unexpected persistent COPR repository section")
    section = parser[REPO_ID]
    if (section.get("baseurl") != BASE_URL
            or section.get("gpgkey") != "file:///" + KEY_PATH
            or not all(section.getboolean(option, fallback=False)
                       for option in ("enabled", "gpgcheck", "sslverify"))):
        raise ValueError("The Remix COPR repository must be enabled with the expected URL, key and signature/TLS checks")
    if hashlib.sha256(key.read_bytes()).hexdigest() != KEY_SHA256:
        raise ValueError("The packaged COPR key differs from the verified project key")
    for other in sorted(repo.parent.glob("*.repo")):
        if other == repo:
            continue
        if other.is_symlink() or not other.is_file():
            raise ValueError("Unexpected non-regular repository configuration: " + str(other))
        parsed = configparser.ConfigParser(interpolation=None, strict=True)
        parsed.read_string(other.read_text(encoding="utf-8"))
        if parsed.has_section(REPO_ID):
            raise ValueError("Duplicate Remix COPR repository section: " + str(other))
    owners = [subprocess.check_output(
        ["rpm", "--root", str(root), "--dbpath", "/usr/lib/sysimage/rpm", "-qf",
         "/" + path, "--qf", "%{NAME}\n"], text=True, timeout=30).strip()
        for path in (REPO_PATH, KEY_PATH)]
    if owners != ["fedora-dde-remix-config", "fedora-dde-remix-config"]:
        raise ValueError("The persistent COPR repository and key are not owned by the Remix configuration RPM")
    return {"repository": REPO_ID, "enabled": True, "gpgcheck": True, "sslverify": True,
            "baseurl": BASE_URL, "key_sha256": KEY_SHA256, "rpm_owner": owners[0]}


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--root", type=Path, default=Path("/"))
    options = arguments.parse_args()
    print(json.dumps(verify(options.root.resolve()), sort_keys=True))
