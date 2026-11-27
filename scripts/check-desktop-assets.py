#!/usr/bin/python3
"""Verify packaged desktop defaults and their actual Fedora-owned resources.

This is a read-only structural check. The VM separately checks effective user
DConfig values, generated wallpaper configuration and actual rendered frames.
"""

import argparse
import ast
import configparser
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


WALLPAPER = "/usr/share/backgrounds/images/earth_from_space.jpg"
URI = "file://" + WALLPAPER
LOGO = "/usr/share/pixmaps/fedora-remix-logos/Fedora-Remix-Black-Blue.png"
TRANSPARENT_LOGO = "/usr/share/pixmaps/fedora-remix-logos/Fedora-Remix-Transparent-Blue.png"
TREELAND = "/usr/share/dsg/configs/overrides/org.deepin.dde.treeland/org.deepin.dde.treeland.user/90-fedora-dde-remix-background.json"
APPEARANCE = "/usr/share/dsg/configs/overrides/org.deepin.dde.appearance/org.deepin.dde.appearance/90-fedora-dde-remix-background.json"
GSETTINGS = "/usr/share/glib-2.0/schemas/99-fedora-dde-remix-background.gschema.override"
DISTRIBUTION = "/usr/share/deepin/distribution.info"
CONFIG_PACKAGE = "fedora-dde-remix-config"


def require(value, message):
    if not value:
        raise ValueError(message)


def regular(root, absolute):
    path = root / absolute.lstrip("/")
    current = root
    for part in Path(absolute).parts[1:-1]:
        current /= part
        require(not current.is_symlink() and current.is_dir(),
                f"Unexpected asset parent path: {absolute}")
        info = current.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022,
                f"Unsafe asset parent ownership/mode: {absolute}")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and not info.st_mode & 0o022 and info.st_size > 0,
            f"Missing or unsafe regular desktop asset: {absolute}")
    return path


def owned(root, absolute, package):
    path = regular(root, absolute)
    owner = subprocess.check_output(
        ["rpm", "--root", str(root), "--dbpath", "/usr/lib/sysimage/rpm",
         "-qf", absolute, "--qf", "%{NAME}\n"], text=True).strip()
    require(owner == package, f"Wrong RPM owner for {absolute}: {owner}")
    return path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate configuration key: {key}")
        result[key] = value
    return result


def override(root, absolute, key, value):
    path = owned(root, absolute, CONFIG_PACKAGE)
    require(path.stat().st_size <= 65536, "Oversized DConfig override")
    expected = {"magic": "dsg.config.override", "version": "1.0",
                "contents": {key: {"value": value}}}
    actual = json.loads(path.read_text(), object_pairs_hook=unique_object)
    require(actual == expected, f"Unexpected desktop default in {absolute}")


def ini(path):
    require(path.stat().st_size <= 65536, "Oversized desktop configuration")
    result = configparser.ConfigParser(interpolation=None, strict=True)
    result.optionxform = str
    result.read_string(path.read_text())
    return result


def check(root):
    rpm = ["rpm", "--root", str(root), "--dbpath", "/usr/lib/sysimage/rpm"]
    require(subprocess.run(rpm + ["-q", "fedora-logos"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL).returncode == 1,
            "The primary Fedora logo package is still installed in the Remix")
    installed = subprocess.check_output(rpm + ["-q", "generic-logos", "--qf", "%{NAME}"], text=True)
    require(installed == "generic-logos", "The generic system artwork package is missing")
    wallpaper = owned(root, WALLPAPER, "desktop-backgrounds-basic")
    logo = owned(root, LOGO, "fedora-remix-logos")
    transparent = owned(root, TRANSPARENT_LOGO, "fedora-remix-logos")
    with wallpaper.open("rb") as stream:
        require(stream.read(3) == b"\xff\xd8\xff", "Default wallpaper is not a JPEG")
    for path in (logo, transparent):
        with path.open("rb") as stream:
            require(stream.read(8) == b"\x89PNG\r\n\x1a\n", "Fedora Remix logo is not a PNG")
    override(root, TREELAND, "defaultBackground", WALLPAPER)
    override(root, APPEARANCE, "Background_Uris", [URI])
    distribution = ini(owned(root, DISTRIBUTION, CONFIG_PACKAGE))
    require(distribution.sections() == ["Distribution"]
            and dict(distribution["Distribution"]) == {
                "Name": "Fedora DDE Remix", "Logo": LOGO,
                "LogoTransparent": TRANSPARENT_LOGO},
            "Unexpected DSysInfo distribution name or logos")
    settings = ini(owned(root, GSETTINGS, CONFIG_PACKAGE))
    expected = {"com.deepin.dde.appearance": ("background-uris", [URI]),
                "com.deepin.wrap.gnome.desktop.background": ("picture-uri", URI)}
    require(set(settings.sections()) == set(expected), "Unexpected GSettings sections")
    schema_dir = root / "usr/share/glib-2.0/schemas"
    regular(root, "/usr/share/glib-2.0/schemas/gschemas.compiled")
    for schema, (key, value) in expected.items():
        require(set(settings[schema]) == {key}
                and ast.literal_eval(settings[schema][key]) == value,
                f"Unexpected GSettings override: {schema}.{key}")
        # The memory backend reads the compiled default without consulting or
        # changing any user's dconf values. Point at the actual image schemas.
        result = subprocess.check_output(
            ["gsettings", "get", schema, key], text=True,
            env=dict(os.environ, LC_ALL="C", GSETTINGS_BACKEND="memory",
                     GSETTINGS_SCHEMA_DIR=str(schema_dir)))
        require(ast.literal_eval(result.strip()) == value,
                f"Compiled GSettings default did not adopt the override: {schema}.{key}")
    with wallpaper.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"schema": 1, "wallpaper": WALLPAPER, "wallpaper_uri": URI,
            "wallpaper_rpm_owner": "desktop-backgrounds-basic",
            "wallpaper_sha256": digest, "wallpaper_bytes": wallpaper.stat().st_size,
            "logo": LOGO, "transparent_logo": TRANSPARENT_LOGO,
            "logo_rpm_owner": "fedora-remix-logos", "configuration_rpm_owner": CONFIG_PACKAGE,
            "system_artwork": "generic-logos", "primary_fedora_logo_package_absent": True,
            "distribution_name": "Fedora DDE Remix",
            "compiled_gsettings_defaults_verified": True,
            "structural_assets_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    require(root.is_dir(), "The image root must be a directory")
    print(json.dumps(check(root), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, SyntaxError, configparser.Error,
            subprocess.CalledProcessError) as error:
        print(f"Desktop asset verification failed: {error}", file=sys.stderr)
        sys.exit(1)
