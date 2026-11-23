#!/usr/bin/python3
"""Require the installed image to contain every mandatory DDE group package.

Read the metadata supplied by dde-desktop-comps itself, not a second package
list. This check does not change repositories, packages, or the RPM database.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


REPOSITORY = Path("/usr/share/dde-desktop/comps-repo")
GROUP_ID = "dde-desktop"
MAX_METADATA_SIZE = 16 * 1024 * 1024
RPM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*\Z")
COMPRESSED_SUFFIXES = (".gz", ".xz", ".bz2", ".zst", ".zstd")


class CheckError(RuntimeError):
    """The group metadata or installed package set is incomplete."""


def repository_file(repository: Path, href: str) -> Path:
    """Resolve a local metadata reference without escaping this RPM's repository."""
    uri = urlsplit(href)
    relative = PurePosixPath(href)
    if (not href or uri.scheme or uri.netloc or uri.query or uri.fragment
            or relative.is_absolute() or ".." in relative.parts):
        raise CheckError("group metadata contains an unsafe repository location")
    root = repository.resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or path == root or not path.is_file():
        raise CheckError("group metadata location escapes its local repository")
    return path


def read_metadata(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_METADATA_SIZE + 1)
    if len(data) > MAX_METADATA_SIZE:
        raise CheckError("group metadata exceeds the supported size")
    return data


def verify_sha256(element: ET.Element | None, data: bytes) -> None:
    if element is None or element.get("type", "").lower() != "sha256":
        return
    expected = (element.text or "").strip().lower()
    if (not re.fullmatch(r"[0-9a-f]{64}", expected)
            or hashlib.sha256(data).hexdigest() != expected):
        raise CheckError("group metadata SHA256 does not match repomd.xml")


def decompress_metadata(path: Path, data: bytes) -> bytes:
    suffix = path.suffix.lower()
    if data.startswith(b"\x1f\x8b") or suffix == ".gz":
        decoded = gzip.decompress(data)
    elif data.startswith(b"\xfd7zXZ\x00") or suffix == ".xz":
        decoded = lzma.decompress(data)
    elif data.startswith(b"BZh") or suffix == ".bz2":
        decoded = bz2.decompress(data)
    elif data.startswith(b"\x28\xb5\x2f\xfd") or suffix in {".zst", ".zstd"}:
        try:
            from compression import zstd
        except ImportError:
            raise CheckError("zstd group metadata requires Python's compression.zstd module") from None
        try:
            decoded = zstd.decompress(data)
        except zstd.ZstdError:
            raise CheckError("invalid zstd group metadata") from None
    else:
        decoded = data
    if len(decoded) > MAX_METADATA_SIZE:
        raise CheckError("decompressed group metadata exceeds the supported size")
    return decoded


def mandatory_packages(repository: Path = REPOSITORY, group_id: str = GROUP_ID) -> set[str]:
    """Read package names from local files; a fixture repository may be supplied."""
    index = ET.fromstring(read_metadata(repository_file(repository, "repodata/repomd.xml")))
    candidates = []
    for entry in index.findall("{*}data"):
        if entry.get("type") not in {"group", "group_gz"}:
            continue
        location = entry.find("{*}location")
        if location is None or not location.get("href"):
            raise CheckError("group metadata has no repository location")
        href = location.get("href")
        # Prefer an uncompressed entry; group is preferred over group_gz if tied.
        priority = (href.lower().endswith(COMPRESSED_SUFFIXES), entry.get("type") != "group")
        candidates.append((priority, entry, href))
    if not candidates:
        raise CheckError("the local repository has no comps group metadata")
    _, entry, href = min(candidates, key=lambda item: item[0])
    path = repository_file(repository, href)
    compressed = read_metadata(path)
    verify_sha256(entry.find("{*}checksum"), compressed)
    decoded = decompress_metadata(path, compressed)
    verify_sha256(entry.find("{*}open-checksum"), decoded)
    comps = ET.fromstring(decoded)
    groups = [group for group in comps.findall("{*}group")
              if (group.findtext("{*}id") or "").strip() == group_id]
    if len(groups) != 1:
        raise CheckError(f"expected exactly one {group_id} group in the installed comps metadata")
    names = set()
    for package in groups[0].findall("{*}packagelist/{*}packagereq"):
        if package.get("type") != "mandatory":
            continue
        name = (package.text or "").strip()
        if not RPM_NAME.fullmatch(name):
            raise CheckError("the mandatory group list contains an invalid RPM package name")
        names.add(name)
    if not names:
        raise CheckError(f"the {group_id} group has no mandatory packages")
    return names


def installed_package_names() -> set[str]:
    result = subprocess.run(
        ["/usr/bin/rpm", "-qa", "--qf", "%{NAME}\n"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}, timeout=120,
    )
    if result.returncode:
        raise CheckError(f"RPM database query failed (exit {result.returncode})")
    names = set(result.stdout.splitlines())
    if any(not RPM_NAME.fullmatch(name) for name in names):
        raise CheckError("RPM database query returned invalid package names")
    return names


def verify_installed(required: set[str], installed: set[str]) -> int:
    """Compare names without invoking RPM, also usable with controlled fixtures."""
    missing = sorted(required - installed)
    if missing:
        raise CheckError("missing mandatory packages: " + ", ".join(missing))
    return len(required)


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise CheckError("this image check accepts no arguments")
        required = mandatory_packages()
        count = verify_installed(required, installed_package_names())
    except (CheckError, OSError, ValueError, EOFError, lzma.LZMAError,
            ET.ParseError, subprocess.TimeoutExpired) as error:
        print(f"FAIL {GROUP_ID}: {error}", file=sys.stderr)
        return 1
    print(f"PASS {GROUP_ID}: all {count} mandatory packages are installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
