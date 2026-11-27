#!/usr/bin/env python3
"""Boot the final ISO, install it, and test the installed DDE desktop under QEMU.

Host dependencies (Ubuntu 24.04): qemu-system-x86 qemu-utils ovmf xorriso
tesseract-ocr python3-pil. Run outside the compose
container. KVM is probed, and an unavailable KVM is recorded before using TCG.

Only the isolated qcow2 (64 GiB, or decimal 16 GB for uefi-small) and disposable
firmware variables are writable by the guest. The ISO is opened
read-only and its GRUB is used; only console arguments are added in memory.
No test account, password, service or script is injected into the release ISO.
The public disposable test password lives in vm-guest.py and is never printed.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import textwrap
import time
import traceback
import uuid


TEST_USER = "vmtest"
TEST_PASSWORD = "FedoraVmtest2026"
CRYPT_PASSWORD = "FedoraLuksVmtest2026"
LIVE_USER = "liveuser"
LIVE_PASSWORD = "liveuser"
SCENARIOS = ("uefi-btrfs", "bios-ext4", "bios-mbr-ext4", "uefi-xfs-home-swap", "uefi-preserve", "uefi-small",
             "uefi-luks-btrfs-small", "bios-luks-ext4", "uefi-luks-xfs")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


class Failure(RuntimeError):
    pass


class SerialTimeout(Failure):
    pass


class GraphicalLoginDeadline(Failure):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def redact(value):
    return value.replace(TEST_PASSWORD, "[disposable test password]").replace(CRYPT_PASSWORD, "[disposable LUKS passphrase]")


def log(message):
    print(f"[{utc()}] vm-test: {redact(str(message))}", flush=True)


def command(argv, *, timeout=120, check=True, input_text=None, env=None):
    result = subprocess.run(argv, input=input_text, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
    if check and result.returncode:
        raise Failure(f"{argv[0]} failed ({result.returncode}): {(result.stderr or '')[-4000:]}")
    return result


def password_control(screen):
    """Locate the control, rather than Treeland's separate password hint.

    Treeland 0.12.0, commit 859a8c314f00947bc98168f46631ba10f9c7e6fa,
    src/plugins/lockscreen/qml/UserInput.qml: a 220x30 passwordSlot and a
    horizontally centered hintText 16 logical pixels below it. The recorded
    1280x800 greeter's hint glyphs span 115 pixels; that also supplies a scale
    estimate. The initial y estimate is refined using the actual focused
    cursor before any password is entered. Never click the eye button.
    """
    words = screen["words"]
    for first in words:
        if first["text"].casefold().strip(".,:;!?") != "please":
            continue
        row = sorted((w for w in words if abs(w["top"] - first["top"]) <= max(first["height"], w["height"])),
                     key=lambda w: w["left"])
        labels = [w["text"].casefold().strip(".,:;!?") for w in row]
        for index in range(len(row) - 2):
            if labels[index:index + 3] != ["please", "enter", "password"]:
                continue
            hint = row[index:index + 3]
            left = min(w["left"] for w in hint)
            right = max(w["left"] + w["width"] for w in hint)
            scale = (right - left) / 115
            if not 0.75 <= scale <= 3:
                continue
            control = {"center_x": (left + right) / 2,
                       "center_y": min(w["top"] for w in hint) - 31 * scale,
                       "width": 220 * scale, "height": 30 * scale, "scale": scale,
                       "anchor": "treeland-0.12.0-password-hint"}
            if (control["width"] / 2 < control["center_x"] < screen["width"] - control["width"] / 2
                    and control["height"] < control["center_y"] < screen["height"] - control["height"]):
                return control
    # The real in-field placeholder has a capital P. A lone lowercase
    # "password" may be an incompletely recognized hint and is not safe.
    for word in words:
        if word["text"].strip(".,:;!?") == "Password":
            scale = word["width"] / 48
            if 0.75 <= scale <= 3:
                return {"center_x": word["left"] + word["width"] / 2,
                        "center_y": word["top"] + word["height"] / 2,
                        "width": 220 * scale, "height": 30 * scale, "scale": scale,
                        "anchor": "in-field-Password-placeholder"}
    return None


def same_password_control(first, second):
    if not first or not second or first["anchor"] != second["anchor"]:
        return False
    return (abs(first["scale"] - second["scale"]) <= 0.1
            and all(abs(first[key] - second[key]) <= 4 * max(first["scale"], second["scale"])
                    for key in ("center_x", "center_y")))


def password_pixels(path, control, baseline=None):
    """Inspect only the field interior: exclude borders and the eye button.

    The white, tall narrow cursor proves focus. Password bullets are small,
    separated, approximately round components on one evenly spaced line.
    Subtracting the focused empty frame removes wallpaper details. The count
    is diagnostic, not proof of authentication or a font-dependent pass gate.
    """
    from PIL import Image
    scale = control["scale"]
    cx, cy = control["center_x"], control["center_y"]
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        left = max(0, round(cx - control["width"] / 2 + 26 * scale))
        right = min(rgb.width, round(cx + control["width"] / 2 - 26 * scale))
        top = max(0, round(cy - control["height"] / 2 + 2 * scale))
        bottom = min(rgb.height, round(cy + control["height"] / 2 - 2 * scale))
        pixels = rgb.load()
        bright = {(x, y) for y in range(top, bottom) for x in range(left, right)
                  if min(pixels[x, y]) >= 190 and max(pixels[x, y]) - min(pixels[x, y]) <= 40}
        changed = None
        if baseline is not None:
            with Image.open(baseline) as empty:
                empty = empty.convert("RGB")
                require(empty.size == rgb.size, "The password field moved to a different display size.")
                old = empty.load()
                changed = {(x, y) for y in range(top, bottom) for x in range(left, right)
                           if max(abs(a - b) for a, b in zip(pixels[x, y], old[x, y])) > 32}
            bright.intersection_update(changed)
    components = []
    while bright:
        pending = [bright.pop()]
        points = []
        while pending:
            x, y = pending.pop()
            points.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (x + dx, y + dy)
                    if neighbor in bright:
                        bright.remove(neighbor)
                        pending.append(neighbor)
        xs, ys = zip(*points)
        components.append({"x": min(xs), "y": min(ys), "width": max(xs) - min(xs) + 1,
                           "height": max(ys) - min(ys) + 1, "pixels": len(points)})
    all_carets = [c for c in components if c["width"] <= max(2, 2 * scale)
                  and 8 * scale <= c["height"] <= 22 * scale]
    carets = [c for c in all_carets if abs(c["x"] + c["width"] / 2 - cx) <= 12 * scale]
    if changed is not None:
        # Neither the old centered cursor blinking off nor the new cursor at
        # the end of the text proves that characters reached the control.
        cursor_columns = set(range(round(cx - 2 * scale), round(cx + 2 * scale) + 1))
        for cursor in all_carets:
            cursor_columns.update(range(cursor["x"] - 1, cursor["x"] + cursor["width"] + 1))
        changed = {(x, y) for x, y in changed if x not in cursor_columns}
    dots = sorted((c for c in components if 2 * scale <= c["width"] <= 10 * scale
                   and 2 * scale <= c["height"] <= 10 * scale and c["pixels"] >= 3 * scale * scale
                   and 0.6 <= c["width"] / c["height"] <= 1.7), key=lambda c: c["x"])
    aligned = bool(dots) and (max(c["y"] for c in dots) - min(c["y"] for c in dots) <= 2 * scale
                             and max(c["height"] for c in dots) - min(c["height"] for c in dots) <= 2 * scale
                             and all(abs(c["y"] + c["height"] / 2 - cy) <= 8 * scale for c in dots))
    gaps = [b["x"] - a["x"] for a, b in zip(dots, dots[1:])]
    if gaps:
        aligned = aligned and min(gaps) >= 3 * scale and max(gaps) - min(gaps) <= 2 * scale
    return {"interior": [left, top, right, bottom], "carets": carets,
            "masked_characters": len(dots) if aligned else 0,
            "mask_components": dots if aligned else [],
            "changed_non_cursor_pixels": len(changed) if changed is not None else None}


def greeter_evidence(screen, session, user, *, password_required=False):
    """Recognize observed DDM controls without mistaking a getty for a greeter."""
    text = screen["text"]
    terminal = re.search(r"\blogin\s*:|\bKernel\s+\S+\s+on\s+\S+|"
                         r"Fedora\s+DDE\s+Remix\s+Live:\s+username", text, re.I)
    boot_console = (len(re.findall(r"\b(?:Starting|Started|Finished|Reached|Created|Listening)\b", text)) >= 3
                    and len(re.findall(r"\b(?:service|target|socket|slice)\b", text, re.I)) >= 3)
    password_words = [w for w in screen["words"]
                      if w["text"].casefold().strip(".,:;!?") == "password"]
    control = password_control(screen)
    labels = [w["text"].casefold().strip(".,:") for w in screen["words"]]
    user_words = [w for w, label in zip(screen["words"], labels) if label == user.casefold()]
    if user == LIVE_USER:
        # The actual greeter displays "Live User". A lone "Live" also occurs
        # in the systemd "Prepare the Fedora DDE Live installer" boot message.
        user_words += [w for index, w in enumerate(screen["words"][:-1])
                       if labels[index:index + 2] == ["live", "user"]]
    if terminal:
        reason = "A text getty is visible; it is not the DDM graphical greeter."
    elif boot_console:
        reason = "System startup messages are visible; they are not the DDM graphical greeter."
    elif not session["treeland"]:
        reason = "No running Treeland compositor was observed."
    elif not control and (password_required or not user_words):
        reason = "No graphical password prompt or matching user tile was observed."
    else:
        reason = "Running Treeland and graphical login controls were observed."
    return {"ready": not terminal and not boot_console and bool(session["treeland"])
                     and bool(control or (user_words and not password_required)),
            "reason": reason, "password_words": password_words, "user_words": user_words,
            "password_control": control}


def nonblack_frame(path):
    # Lazy import keeps the separate host sudo/PTY smoke test independent of
    # optional VM tools, which the workflow installs afterwards.
    from PIL import Image, ImageChops
    with Image.open(path) as image:
        require(image.format == "PNG", "The desktop frame is not a PNG image.")
        rgb = image.convert("RGB")
        red, green, blue = rgb.split()
        brightness = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        histogram = brightness.histogram()
        pixels = rgb.width * rgb.height
        visible_pixels = sum(histogram[17:])
    fraction = visible_pixels / pixels
    return {"nonblack": fraction >= 0.01, "width": rgb.width, "height": rgb.height,
            "nonblack_pixel_fraction": round(fraction, 6), "channel_threshold": 16,
            "minimum_fraction": 0.01,
            "scope": "Nonblack frame evidence; complete desktop usability still requires visual review."}


class Report:
    def __init__(self, directory, timeout):
        self.directory = directory
        self.path = directory / "report.json"
        self.started = time.monotonic()
        self.deadline = self.started + timeout
        self.data = {"schema": 1, "status": "running", "started_at": utc(), "timeout_seconds": timeout,
                     "scope": "Final ISO firmware boot, real backend installation, disk-only reboot, DDM Wayland login with crash and nonblack-frame checks",
                     "visual_review_required": True,
                     "secure_boot_tested": False, "stages": [], "evidence": {}}
        self.save()

    def save(self):
        self.data["elapsed_seconds"] = round(time.monotonic() - self.started, 2)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(redact(json.dumps(self.data, indent=2, sort_keys=True)) + "\n")
        temporary.replace(self.path)

    def remaining(self, maximum):
        remaining = min(maximum, self.deadline - time.monotonic())
        require(remaining > 0, "The overall VM validation deadline expired.")
        return remaining

    @contextlib.contextmanager
    def stage(self, name):
        entry = {"name": name, "started_at": utc(), "status": "running"}
        start = time.monotonic()
        self.data["stages"].append(entry)
        self.save()
        log(name)
        try:
            yield entry
        except BaseException as error:
            entry.update(status="failed", error=redact(str(error)))
            raise
        else:
            entry["status"] = "passed"
        finally:
            entry["elapsed_seconds"] = round(time.monotonic() - start, 2)
            self.save()


class QMP:
    def __init__(self, path, process, event_file):
        self.process = process
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic() + 30
        while True:
            try:
                self.socket.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                require(process.poll() is None, "QEMU exited before opening its QMP socket.")
                require(time.monotonic() < deadline, "QMP socket did not become available.")
                time.sleep(0.1)
        self.socket.setblocking(False)
        self.buffer = b""
        self.sequence = 0
        self.observed_events = []
        self.events = event_file.open("a", encoding="utf-8")
        require("QMP" in self.read(deadline), "Invalid QMP greeting.")
        self.execute("qmp_capabilities")

    def read(self, deadline):
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Timed out waiting for QMP.")
            ready, _, _ = select.select([self.socket], [], [], min(remaining, 1))
            if not ready:
                require(self.process.poll() is None, "QEMU exited while waiting for QMP.")
                continue
            chunk = self.socket.recv(65536)
            require(bool(chunk), "QMP connection closed.")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        value = json.loads(line)
        if "event" in value:
            self.observed_events.append(value)
            self.events.write(json.dumps(value) + "\n")
            self.events.flush()
        return value

    def execute(self, name, arguments=None, timeout=30):
        self.sequence += 1
        request = {"execute": name, "id": self.sequence}
        if arguments is not None:
            request["arguments"] = arguments
        self.socket.sendall(json.dumps(request).encode() + b"\n")
        deadline = time.monotonic() + timeout
        while True:
            response = self.read(deadline)
            if response.get("id") != self.sequence:
                continue
            if "error" in response:
                raise Failure(f"QMP {name}: {response['error']}")
            return response.get("return")

    def key(self, *keys, hold_time=30):
        self.execute("send-key", {"keys": [{"type": "qcode", "data": key} for key in keys], "hold-time": hold_time})
        time.sleep(0.045 if hold_time == 30 else hold_time / 1000 + 0.05)

    def type(self, text, *, hold_time=30):
        plain = {" ": "spc", "-": "minus", "=": "equal", "/": "slash", ".": "dot", ",": "comma",
                 ";": "semicolon", "'": "apostrophe", "[": "bracket_left", "]": "bracket_right",
                 "\\": "backslash", "`": "grave_accent", "\n": "ret", "\t": "tab"}
        shifted = {"_": "minus", "+": "equal", ":": "semicolon", '"': "apostrophe", "?": "slash",
                   "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
                   "*": "8", "(": "9", ")": "0", "<": "comma", ">": "dot", "|": "backslash",
                   "{": "bracket_left", "}": "bracket_right", "~": "grave_accent"}
        for char in text:
            if "A" <= char <= "Z":
                self.key("shift", char.lower(), hold_time=hold_time)
            elif char in shifted:
                self.key("shift", shifted[char], hold_time=hold_time)
            elif char in plain:
                self.key(plain[char], hold_time=hold_time)
            elif char.isascii() and char.isalnum():
                self.key(char, hold_time=hold_time)
            else:
                raise Failure(f"Unsupported keyboard character: {char!r}")

    def click(self, x, y, width, height):
        self.execute("input-send-event", {"events": [
            {"type": "abs", "data": {"axis": "x", "value": min(32767, max(0, round(x * 32767 / width)))}},
            {"type": "abs", "data": {"axis": "y", "value": min(32767, max(0, round(y * 32767 / height)))}},
            {"type": "btn", "data": {"button": "left", "down": True}}]})
        time.sleep(0.05)
        self.execute("input-send-event", {"events": [{"type": "btn", "data": {"button": "left", "down": False}}]})

    def close(self):
        self.socket.close()
        self.events.close()


class Serial:
    def __init__(self, path, process):
        self.process = process
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic() + 30
        while True:
            try:
                self.socket.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                require(process.poll() is None, "QEMU exited before opening the serial socket.")
                require(time.monotonic() < deadline, "Serial socket did not become available.")
                time.sleep(0.1)
        self.socket.setblocking(False)
        self.buffer = ""

    def send(self, value):
        data = value.encode() if isinstance(value, str) else value
        for offset in range(0, len(data), 256):
            part = memoryview(data[offset:offset + 256])
            while part:
                _, writable, _ = select.select([], [self.socket], [], 5)
                require(bool(writable), "Serial input is not draining.")
                part = part[self.socket.send(part):]
            if len(data) > 256:
                time.sleep(0.002)

    def receive(self, timeout):
        ready, _, _ = select.select([self.socket], [], [], timeout)
        if ready:
            data = self.socket.recv(65536)
            require(bool(data), "Serial connection closed.")
            # Terminal escape sequences can span multiple socket reads. Keep
            # incomplete sequences until the following chunk completes them.
            self.buffer = ANSI.sub("", self.buffer + data.decode("utf-8", errors="replace")).replace("\r", "")
            require(len(self.buffer) < 64 * 1024**2, "Guest command output exceeded the 64 MiB bound.")

    def expect(self, pattern, timeout):
        regex = re.compile(pattern, re.M)
        deadline = time.monotonic() + timeout
        while True:
            match = regex.search(self.buffer)
            if match:
                before = self.buffer[:match.start()]
                value = match.group(0)
                self.buffer = self.buffer[match.end():]
                return before, value
            if time.monotonic() >= deadline:
                raise SerialTimeout(f"Timed out waiting for serial pattern {pattern!r}; tail: {redact(self.buffer[-2000:])}")
            require(self.process.poll() is None, "QEMU exited while waiting for the guest serial console.")
            self.receive(min(0.5, max(0, deadline - time.monotonic())))

    def close(self):
        self.socket.close()


def root_shell_script(root_token):
    require(re.fullmatch(r"[A-Za-z0-9_]+", root_token), "Invalid root shell marker.")
    return ("stty -echo; export PS1='__VM_ROOT_READY__ '; export HISTFILE=/dev/null; "
            "set +o history; vm_uid=$(/usr/bin/id -u); "
            f"printf '\\n{root_token}%s\\n' \"$vm_uid\"; "
            "[ \"$vm_uid\" = 0 ] || exit 1; exec /bin/bash --noprofile --norc -i")


def sudo_shell_command(password_token, root_token, *, non_interactive=False):
    require(re.fullmatch(r"[A-Za-z0-9_]+", password_token), "Invalid sudo password marker.")
    options = ["sudo", "-H", "-k", "-n" if non_interactive else "-S"]
    # Execute Bash directly. sudo -i would add a second login-shell parsing
    # layer around the already quoted Bash script and expand its variables.
    return ("stty -echo && " + shlex.join(options) + " -p $'\\n" + password_token + "\\n' -- "
            + shlex.join(["/bin/bash", "--noprofile", "--norc", "-c", root_shell_script(root_token)]))


class Guest:
    def __init__(self, serial, report, output):
        self.serial = serial
        self.report = report
        self.output = output
        self.counter = 0
        self.ready = False

    def login(self, user, password, timeout):
        deadline = time.monotonic() + timeout
        self.serial.expect(r"(?:^|\n)[^\n]{0,100}login:\s*", max(1, deadline - time.monotonic()))
        self.serial.send(user + "\n")
        self.serial.expect(r"Password:\s*", max(1, deadline - time.monotonic()))
        self.serial.send(password + "\n")
        self.serial.expect(r"(?:^|\n)\[" + re.escape(user) + r"@[^\]\n]{1,150}\]\$ ?$",
                           max(1, deadline - time.monotonic()))
        token = uuid.uuid4().hex[:12]
        password_token = "__VM_SUDO_PASSWORD_" + token + "__"
        root_token = "__VM_ROOT_UID_" + token + "__"
        # Literal backslash-n escapes keep the typed command on one line, so
        # echoed input cannot impersonate the standalone password prompt. Never
        # use a generic '#' match: sudo's lecture itself contains '#1', '#2'...
        self.serial.send(sudo_shell_command(password_token, root_token) + "\n")
        password_pattern = r"(?:^|\n)" + password_token + r"\n"
        root_pattern = r"(?:^|\n)" + root_token + r"[0-9]+\n"
        _, response = self.serial.expect(password_pattern + "|" + root_pattern, 90)
        require(password_token in response, "sudo did not request the ordinary user's password.")
        self.serial.send(password + "\n")
        _, response = self.serial.expect(root_pattern + "|" + password_pattern, 90)
        require(root_token in response, "sudo rejected the ordinary user's password.")
        require(response.strip() == root_token + "0", "The authenticated sudo shell does not have UID 0.")
        self.serial.expect(r"(?:^|\n)__VM_ROOT_READY__ ?", 30)
        self.ready = True
        log("Serial login and normal sudo password authentication passed; root shell UID 0 verified.")

    def run(self, text, name, timeout=120, check=True, budget=True):
        self.counter += 1
        token = f"{self.counter}_{uuid.uuid4().hex[:8]}"
        begin, end = f"__VM_BEGIN_{token}__", f"__VM_END_{token}__"
        duration = self.report.remaining(timeout) if budget else timeout
        deadline = time.monotonic() + duration
        # Separate physical lines keep the canonical TTY input below 4096 bytes,
        # including while uploading a base64-encoded guest helper via heredoc.
        wrapped = f"printf '\\n{begin}\\n'; {{\n{text}\n}}; vm_status=$?; printf '\\n{end}%s\\n' \"$vm_status\"\n"
        self.serial.send(wrapped)
        self.serial.expect(re.escape(begin) + r"\n", min(60, duration))
        body, result = self.serial.expect(re.escape(end) + r"[0-9]+\n", max(0, deadline - time.monotonic()))
        status = int(result[len(end):].strip())
        path = self.output / (name + ".log")
        path.write_text(redact(body))
        if check and status:
            raise Failure(f"Guest command {name} failed ({status}); see {path.name}: {redact(body[-4000:])}")
        return status, body

    def upload_helper(self, source, scenario, expectations=None):
        encoded = "\n".join(textwrap.wrap(base64.b64encode(source.read_bytes()).decode(), 76))
        delimiter = "VM_HELPER_" + uuid.uuid4().hex
        config = "\n".join(textwrap.wrap(base64.b64encode(json.dumps(dict(expectations or {}, scenario=scenario)).encode()).decode(), 76))
        script = ("umask 077\ninstall -d -m 0700 /run/fedora-dde-vmtest\n"
                  "printf '%s\\n' fedora-dde-vmtest-v1 > /run/fedora-dde-vmtest/authorized\n"
                  "chmod 0600 /run/fedora-dde-vmtest/authorized\n"
                  f"base64 --decode > /run/fedora-dde-vmtest/guest.py <<'{delimiter}'\n{encoded}\n{delimiter}\n"
                  "chmod 0600 /run/fedora-dde-vmtest/guest.py\n"
                  f"base64 --decode > /run/fedora-dde-vmtest/context.json <<'{delimiter}'\n{config}\n{delimiter}\n"
                  "chmod 0600 /run/fedora-dde-vmtest/context.json")
        self.run(script, "upload-helper", 120)

    def check(self, action, *arguments, timeout=120, name=None, budget=True):
        text = shlex.join(["/usr/bin/python3", "-I", "/run/fedora-dde-vmtest/guest.py", action, *arguments])
        _, body = self.run(text, name or action, timeout, budget=budget)
        results = re.findall(r"(?m)^VMTEST_RESULT=(.*)$", body)
        require(len(results) == 1, f"Guest {action} did not return one structured result.")
        return json.loads(results[0])

    def recover(self):
        if not self.ready:
            return False
        try:
            self.serial.send(b"\x03\n")
            self.serial.expect(r"__VM_ROOT_READY__", 8)
            return True
        except Exception:
            return False


def parse_grub(text):
    search = next((line.strip() for line in text.splitlines() if re.match(r"^\s*search\s+", line)), None)
    entries = re.findall(r"(?ms)^\s*menuentry\b[^\n]*\{(.*?)^\s*\}", text)
    for entry in entries:
        kernel = re.search(r"(?m)^\s*(linux(?:efi|16)?\s+[^\n]+)", entry)
        initrd = re.search(r"(?m)^\s*(initrd(?:efi|16)?\s+[^\n]+)", entry)
        if not kernel or not initrd:
            continue
        tokens = shlex.split(kernel[1])
        if "rd.live.check" in tokens or "nomodeset" in tokens:
            continue
        require("rd.live.image" in tokens and any(t.startswith("root=live:") for t in tokens), "The ISO has no normal Live entry.")
        require(not {"selinux=0", "enforcing=0"}.intersection(tokens), "The final ISO disables SELinux in its boot entry.")
        require(search is not None and not any("$" in line for line in (search, kernel[1], initrd[1])),
                "The ISO GRUB commands are not self-contained; refusing to invent substitute boot arguments.")
        return {"search": search, "kernel_original": kernel[1],
                "kernel": kernel[1] + " console=tty0 console=ttyS0,115200n8", "initrd": initrd[1]}
    raise Failure("No normal, non-media-check GRUB boot entry was found in the final ISO.")


def firmware_paths(args):
    if args.ovmf_code or args.ovmf_vars:
        require(args.ovmf_code and args.ovmf_vars, "Supply both --ovmf-code and --ovmf-vars.")
        code, variables = Path(args.ovmf_code), Path(args.ovmf_vars)
    else:
        pairs = [("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
                 ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd")]
        found = next(((Path(c), Path(v)) for c, v in pairs if Path(c).is_file() and Path(v).is_file()), None)
        require(found, "No matching ordinary OVMF code/vars pair is installed.")
        code, variables = found
    require(code.is_file() and variables.is_file(), "OVMF firmware files are missing.")
    return code.resolve(), variables.resolve()


def accelerator(output, work):
    logfile = output / "kvm-probe.log"
    # query-kvm's enabled flag alone is not proof that initialization completed.
    # Sending query-kvm and quit together can terminate QEMU before it opens
    # /dev/kvm. Check access, then require a genuinely running probe machine.
    try:
        descriptor = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
        os.close(descriptor)
    except OSError as error:
        reason = f"Cannot open /dev/kvm: {error}"
        logfile.write_text(reason + "\n")
        return "tcg", {"available": False, "reason": reason}

    qmp_path = work / "kvm-probe-qmp.sock"
    require(len(str(qmp_path)) < 104, "Use a shorter --work-dir for UNIX socket paths.")
    argv = ["qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host", "-m", "128",
            "-nodefaults", "-display", "none", "-monitor", "none", "-S",
            "-qmp", f"unix:{qmp_path},server=on,wait=off"]
    process = control = None
    try:
        with logfile.open("w") as diagnostic:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=diagnostic,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            control = QMP(qmp_path, process, output / "kvm-probe-events.jsonl")
            stopped = control.execute("query-status")
            require(stopped.get("status") == "prelaunch" and not stopped.get("running"),
                    "KVM probe did not reach its initialized prelaunch state.")
            control.execute("cont")
            running = control.execute("query-status")
            kvm = control.execute("query-kvm")
            require(running.get("status") == "running" and running.get("running") is True
                    and kvm.get("enabled") is True, "KVM probe did not enter the running state.")
            time.sleep(0.5)
            require(process.poll() is None, "KVM probe exited during initial execution.")
            control.execute("quit")
            status = process.wait(timeout=5)
            require(status == 0, "KVM probe did not exit cleanly.")
            return "kvm", {"available": True, "probe_status": status,
                           "initialized_status": stopped, "running_status": running, "qmp": kvm}
    except (Failure, OSError, subprocess.TimeoutExpired) as error:
        reason = str(error)
        if logfile.exists():
            reason += "\n" + logfile.read_text(errors="replace")[-3000:]
        return "tcg", {"available": False, "reason": reason.strip()}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if control is not None:
            control.close()
        qmp_path.unlink(missing_ok=True)


class VM:
    def __init__(self, args, report, work, output, firmware, accel, cpus, memory, phase):
        self.args, self.report, self.work, self.output = args, report, work, output
        self.phase = phase
        self.output.mkdir(parents=True, exist_ok=True)
        self.snapshots = self.output / "screenshots"
        self.snapshots.mkdir()
        self.qmp = self.serial = self.guest = self.process = None
        self.counter = 0
        qmp_path, serial_path = work / f"{phase}-qmp.sock", work / f"{phase}-serial.sock"
        require(len(str(qmp_path)) < 104 and len(str(serial_path)) < 104, "Use a shorter --work-dir for UNIX socket paths.")
        argv = ["qemu-system-x86_64", "-name", f"fedora-dde-{phase}", "-machine", f"q35,accel={accel}",
                "-cpu", "host" if accel == "kvm" else "max", "-smp", str(cpus), "-m", str(memory),
                "-smbios", "type=1,serial=FDDESMOKE", "-S",
                "-drive", f"if=none,id=target,format=qcow2,file={work / 'install.qcow2'},discard=unmap",
                "-device", f"virtio-blk-pci,drive=target,serial=FDDESMOKE,bootindex={2 if phase == 'live' else 1}",
                "-vga", "none", "-device", "virtio-vga", "-device", "qemu-xhci", "-device", "usb-tablet",
                "-device", "virtio-rng-pci", "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0",
                "-display", "none", "-monitor", "none", "-qmp", f"unix:{qmp_path},server=on,wait=off",
                "-chardev", f"socket,id=serial0,path={serial_path},server=on,wait=off,logfile={output / 'serial.log'}",
                "-serial", "chardev:serial0", "-no-reboot"]
        if firmware is not None:
            argv += ["-drive", f"if=pflash,format=raw,readonly=on,file={firmware}",
                     "-drive", f"if=pflash,format=raw,file={work / 'OVMF_VARS.fd'}"]
        if phase == "live":
            argv += ["-drive", f"if=none,id=live,format=raw,media=cdrom,readonly=on,file={args.iso}",
                     "-device", "ide-cd,drive=live,bus=ide.0,bootindex=1"]
        for selected in (("kvm", "tcg") if accel == "kvm" else ("tcg",)):
            argv[argv.index("-machine") + 1] = f"q35,accel={selected}"
            argv[argv.index("-cpu") + 1] = "host" if selected == "kvm" else "max"
            self.command = list(argv)
            (output / "qemu-command.json").write_text(json.dumps(argv, indent=2) + "\n")
            self.logfile = (output / "qemu.log").open("w")
            try:
                self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=self.logfile,
                                                stderr=subprocess.STDOUT, start_new_session=True)
                self.qmp = QMP(qmp_path, self.process, output / "qmp-events.jsonl")
                supported = {item["name"] for item in self.qmp.execute("query-commands")}
                if "query-accelerators" in supported:
                    acceleration = self.qmp.execute("query-accelerators")
                    actual = acceleration["enabled"]
                else:
                    acceleration = self.qmp.execute("query-kvm")
                    actual = "kvm" if acceleration["enabled"] else "tcg"
                require(actual == selected, "QEMU's actual accelerator differs from the recorded selection.")
                self.serial = Serial(serial_path, self.process)
                self.guest = Guest(self.serial, report, output)
                self.qmp.execute("cont")
                status = self.qmp.execute("query-status")
                require(status.get("status") == "running" and status.get("running") is True,
                        "QEMU did not enter the running state.")
                self.report.data["acceleration"][phase] = {"actual": actual, "qmp": acceleration, "status": status}
                self.report.data["acceleration"]["selected"] = selected
                self.report.save()
                break
            except BaseException as error:
                # Only an explicit accelerator initialization error permits a
                # retry. Firmware, image, QMP and guest failures stay failures.
                exited_before_qmp = (self.qmp is None and self.process is not None
                                     and self.process.poll() is not None)
                self.close()
                diagnostic = (output / "qemu.log").read_text(errors="replace")
                if not (isinstance(error, Failure) and selected == "kvm" and exited_before_qmp
                        and re.search(r"(?im)^.*failed to initialize kvm: (?:Permission denied|Operation not permitted|No such file or directory|No such device)", diagnostic)):
                    raise
                shutil.copyfile(output / "qemu.log", output / "kvm-startup-failed.log")
                shutil.copyfile(output / "qemu-command.json", output / "kvm-startup-failed-command.json")
                self.report.data["acceleration"].setdefault("startup_fallbacks", []).append({
                    "phase": phase, "from": "kvm", "to": "tcg",
                    "reason": diagnostic.strip(), "qemu_exit_status": self.process.returncode})
                self.report.save()
                log(f"KVM initialization failed; retrying this VM with TCG: {diagnostic.strip()}")
                self.qmp = self.serial = self.guest = self.process = None
                qmp_path.unlink(missing_ok=True)
                serial_path.unlink(missing_ok=True)

    def screenshot(self, name=None):
        self.counter += 1
        path = (self.snapshots / f"{self.counter:03d}-{name}.png") if name else self.work / f"{self.phase}-current.png"
        self.qmp.execute("screendump", {"filename": str(path), "format": "png"})
        return path

    def screen(self, name=None, *, deadline=None):
        deadline = self.report.deadline if deadline is None else deadline
        path = self.screenshot(name)
        image = path.read_bytes()
        require(image.startswith(b"\x89PNG\r\n\x1a\n"), "QMP did not produce a PNG screenshot.")
        width, height = struct.unpack(">II", image[16:24])
        # Tesseract explicitly requests OpenMP threads internally. A thread
        # limit, not only OMP_NUM_THREADS, prevents OCR competing with all VM
        # vCPUs. Retry one transient timeout within the caller's same deadline.
        environment = dict(os.environ, OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1")
        for attempt in (1, 2):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "The screen OCR deadline expired; no graphical controls were accepted.")
            timeout = min(30, remaining)
            started = time.monotonic()
            event = {"started_at": utc(), "screenshot": path.name, "attempt": attempt,
                     "timeout_seconds": round(timeout, 3), "omp_thread_limit": 1, "omp_num_threads": 1}
            try:
                value = command(["tesseract", str(path), "stdout", "--psm", "11", "tsv"],
                                timeout=timeout, env=environment).stdout
            except subprocess.TimeoutExpired as error:
                event.update(status="timeout", elapsed_seconds=round(time.monotonic() - started, 3))
                with (self.output / "ocr-events.jsonl").open("a") as events:
                    events.write(json.dumps(event) + "\n")
                if not name:
                    shutil.copyfile(path, self.snapshots / f"{self.counter:03d}-ocr-timeout.png")
                log(f"Host OCR timeout on {path.name}, attempt {attempt}/2; no partial OCR output was accepted.")
                if attempt == 2 or time.monotonic() >= deadline:
                    raise Failure("Host screen OCR timed out within its bounded attempts/deadline; "
                                  "see ocr-events.jsonl and the retained screenshot.") from error
            else:
                event.update(status="completed", elapsed_seconds=round(time.monotonic() - started, 3))
                with (self.output / "ocr-events.jsonl").open("a") as events:
                    events.write(json.dumps(event) + "\n")
                break
        words = []
        for line in value.splitlines()[1:]:
            fields = line.split("\t", 11)
            if len(fields) == 12 and fields[11].strip():
                try:
                    words.append({"text": fields[11], "left": int(fields[6]), "top": int(fields[7]),
                                  "width": int(fields[8]), "height": int(fields[9]), "confidence": float(fields[10])})
                except ValueError:
                    pass
        text = " ".join(w["text"] for w in words)
        if name:
            path.with_suffix(".txt").write_text(redact(text) + "\n")
        return {"path": str(path), "width": width, "height": height, "words": words, "text": text}

    def boot_live(self, grub, timeout):
        deadline = time.monotonic() + self.report.remaining(timeout)
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "QEMU exited before the ISO boot menu.")
            screen = self.screen(deadline=deadline)
            if re.search(r"GNU\s+GRUB|Start\s+Fedora|Test\s+this\s+media|Troubleshooting", screen["text"], re.I):
                self.screenshot("iso-grub-menu")
                log("Observed the final ISO GRUB menu; configuring and synchronizing its serial console.")
                break
            time.sleep(2)
        else:
            raise Failure("The final ISO GRUB menu did not appear before its deadline.")
        self.qmp.key("c")
        time.sleep(0.5)
        self.qmp.type("serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1\n")
        self.qmp.type("terminal_input --append serial\n")
        self.qmp.type("terminal_output --append serial\n")
        # OVMF can already forward its GRUB console to serial. An old grub>
        # prompt is therefore not proof that queued keyboard input has drained.
        # First observe a unique *output line* from the final keyboard command;
        # only then switch input channels and prove serial input works as well.
        keyboard_token = "vmgrubkeyboard" + uuid.uuid4().hex[:12]
        self.qmp.key("ctrl", "u")
        self.qmp.type("echo " + keyboard_token + "\n")
        keyboard_output, _ = self.serial.expect(r"(?:^|\n)" + keyboard_token + r"\n", self.report.remaining(90))
        self.serial.expect(r"grub>\s*", self.report.remaining(30))
        serial_token = "vmgrubserial" + uuid.uuid4().hex[:12]
        self.serial.send("\x15echo " + serial_token + "\n")
        serial_output, _ = self.serial.expect(r"(?:^|\n)" + serial_token + r"\n", self.report.remaining(60))
        self.serial.expect(r"grub>\s*", self.report.remaining(30))
        (self.output / "grub-handoff.log").write_text(
            keyboard_output + "\nKeyboard handshake complete.\n" + serial_output + "\nSerial handshake complete.\n")
        setup_errors = [line for line in keyboard_output.splitlines() if line.startswith("error:")]
        handoff = {"keyboard_output_handshake": "passed", "serial_input_output_handshake": "passed",
                   "terminal_setup_errors": setup_errors,
                   "path": "existing console verified despite terminal setup errors" if setup_errors
                           else "serial console verified"}
        (self.output / "grub-handoff.json").write_text(json.dumps(handoff, indent=2) + "\n")
        self.report.data["evidence"]["grub_handoff"] = handoff
        self.report.save()
        log("GRUB keyboard and serial input/output handshakes passed.")
        for key in ("search", "kernel", "initrd"):
            self.serial.send(grub[key] + "\n")
            text, _ = self.serial.expect(r"grub>\s*", self.report.remaining(120))
            require(not re.search(r"(?im)^error:", text), f"GRUB rejected the final ISO's {key} command: {text}")
        self.screenshot("iso-grub-serial-boot")
        log("GRUB accepted the original ISO search/kernel/initrd commands; booting and waiting for serial login.")
        self.serial.send("boot\n")

    def unlock_root(self, installation, timeout):
        record = installation.get("encrypted_root")
        require(record and record.get("name") == "luks-" + record.get("uuid", ""),
                "Encrypted disk boot is missing its finalized LUKS identity.")
        # The test's inherited serial console is last on the kernel command
        # line. Wait for the real initramfs password request before sending any
        # input; never embed a key in the initramfs or bypass the boot unlock.
        before, prompt = self.serial.expect(
            r"(?i:Please enter (?:the )?(?:passphrase|password) for (?:disk|volume))[^\n]{0,600}:\s*",
            self.report.remaining(timeout))
        require(not re.search(r"(?:^|\n)[^\n]{0,100}login:\s*", before),
                "The encrypted installation booted to login before requesting its passphrase.")
        (self.output / "luks-boot-prompt.log").write_text(redact(prompt) + "\n")
        self.screenshot("encrypted-disk-passphrase-prompt")
        self.serial.send(CRYPT_PASSWORD + "\n")
        return {"luks_uuid": record["uuid"], "initramfs_password_prompt_observed": True,
                "passphrase_supplied_via": "interactive serial console", "boot_confirmed_by_following_login": True}

    def login_session(self, user, checkpoint, deadline, name):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GraphicalLoginDeadline("The graphical login deadline expired before the next session observation.")
        try:
            session = self.guest.check("session", user, str(checkpoint["observed_at_monotonic_us"]),
                checkpoint["boot_id"], timeout=min(45, remaining), name=name)
        except SerialTimeout as error:
            # Only a probe deliberately shortened by the stage's remaining
            # budget can become a stage-deadline error. Keep its original
            # framing failure as the cause; a full-budget timeout still fails
            # as a serial error, as do a disconnected console or bad output.
            if remaining < 45 and time.monotonic() >= deadline:
                raise GraphicalLoginDeadline(
                    f"The graphical login deadline expired during its final {remaining:.2f}s session observation; "
                    "the original serial framing timeout is retained as the cause.") from error
            raise
        require(not session["dde_shell_crashes"],
                "The target user's dde-shell crashed after this graphical login began: "
                + json.dumps(session["dde_shell_crashes"])[-4000:])
        return session

    def wait_greeter(self, user, deadline, name, *, checkpoint, password_required=False, before_password=False):
        # A black loading screen may recover. A compositor crash may instead
        # expose a getty whose issue text also contains the word "password".
        # Observe both processes and the screen; never send a wake-up Enter or
        # credentials until the real graphical controls have been identified.
        deadline = min(deadline, time.monotonic() + 120)
        observations = []
        previous_reason = None
        previous_control = None
        stable_since = None
        while time.monotonic() < deadline:
            session = self.login_session(user, checkpoint, deadline, f"{name}-session")
            if before_password:
                require(not session["ready"] and not session["ddm_sessions"],
                        "A graphical user session appeared before password entry (unexpected autologin).")
            screen = self.screen(f"{name}-{len(observations) + 1:02d}", deadline=deadline)
            evidence = greeter_evidence(screen, session, user, password_required=password_required)
            control = evidence["password_control"]
            now = time.monotonic()
            if not evidence["ready"] or not same_password_control(previous_control, control):
                stable_since = now if control and evidence["ready"] else None
            stable = stable_since is not None and now - stable_since >= 1
            previous_control = control
            observations.append({"observed_at": utc(), "ready": evidence["ready"],
                "reason": evidence["reason"], "screenshot": str(Path(screen["path"]).relative_to(self.output)),
                "treeland": session["treeland"], "password_control": control, "control_stable": stable})
            (self.output / f"{name}-gate.json").write_text(json.dumps(observations, indent=2) + "\n")
            if evidence["reason"] != previous_reason:
                log(evidence["reason"])
                previous_reason = evidence["reason"]
            if evidence["ready"] and (not control or stable):
                return screen, evidence
            time.sleep(max(0, min(1.2 if evidence["ready"] else 5, deadline - time.monotonic())))
        reason = observations[-1]["reason"] if observations else "The graphical login deadline expired."
        raise Failure("DDM greeter unavailable before password entry: " + reason)

    def submit_graphical_password(self, screen, control, password, deadline):
        require(control is not None, "No verified graphical password control was located.")
        require(deadline - time.monotonic() >= 30,
                "Too little graphical-login time remains to verify password focus and masked input safely.")
        control = dict(control)
        evidence = {"control": control, "password_entries": 0, "submissions": 0,
                    "focus_frames": [], "masked_frames": [],
                    "mask_analysis_role": "Diagnostic only; real DDM authentication and the desktop session remain required.",
                    "layout_source": "linuxdeepin/treeland@859a8c314f00947bc98168f46631ba10f9c7e6fa:src/plugins/lockscreen/qml/UserInput.qml"}
        evidence_path = self.output / "graphical-password-input.json"

        def save():
            evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")

        self.qmp.click(control["center_x"], control["center_y"], screen["width"], screen["height"])
        # Clear the disposable field before recording its empty baseline.
        # No credentials are sent until the centered caret confirms focus.
        self.qmp.key("ctrl", "a", hold_time=100)
        self.qmp.key("backspace", hold_time=100)
        focus_deadline = min(deadline, time.monotonic() + 15)
        while time.monotonic() < focus_deadline:
            path = self.screenshot("ddm-password-focus")
            pixels = password_pixels(path, control)
            evidence["focus_frames"].append(dict(pixels, screenshot=str(path.relative_to(self.output))))
            save()
            if len(pixels["carets"]) == 1:
                cursor = pixels["carets"][0]
                # The caret is drawn only when passwordField.activeFocus is
                # true. Its center refines the hint's glyph-based y estimate.
                control["center_y"] = cursor["y"] + cursor["height"] / 2
                baseline = path
                evidence["empty_baseline_screenshot"] = str(path.relative_to(self.output))
                break
            time.sleep(max(0, min(0.4, focus_deadline - time.monotonic())))
        else:
            raise Failure("The password field did not show its focused empty cursor; no password was entered.")
        # Slow only graphical credentials; GRUB and its proven input handshake
        # retain their original key timing. No password retry is permitted.
        self.qmp.type(password, hold_time=100)
        evidence["password_entries"] = 1
        evidence["entered_at"] = utc()
        save()
        # Password controls may briefly echo the last character. Wait for it
        # to hide and collect two stable observations. Exact bullet counts
        # are useful diagnostics, but the actual DDM session is the pass gate.
        time.sleep(min(1.5, max(0, deadline - time.monotonic())))
        masked_deadline = min(deadline, time.monotonic() + 20)
        previous = None
        while time.monotonic() < masked_deadline:
            path = self.screenshot("ddm-password-masked")
            pixels = password_pixels(path, control, baseline)
            frame = dict(pixels, screenshot=str(path.relative_to(self.output)), observed_at=utc())
            evidence["masked_frames"].append(frame)
            save()
            if pixels["changed_non_cursor_pixels"]:
                observed = (pixels["masked_characters"], pixels["changed_non_cursor_pixels"])
                if (previous is not None and observed[0] == previous[0]
                        and abs(observed[1] - previous[1]) <= max(5, previous[1] * 0.2)):
                    break
                previous = observed
            else:
                previous = None
            time.sleep(max(0, min(0.8, masked_deadline - time.monotonic())))
        else:
            raise Failure("The graphical password field remained empty or unstable relative to its focused empty frame; "
                          "the password was entered once but was not submitted. See graphical-password-input.json.")
        self.qmp.key("ret", hold_time=100)
        evidence.update(submissions=1, submitted_at=utc(),
                        masked_characters=pixels["masked_characters"],
                        mask_count_matches=pixels["masked_characters"] == len(password),
                        input_change_observed=True)
        save()
        path = self.screenshot("ddm-password-submitted")
        evidence["after_submit_screenshot"] = str(path.relative_to(self.output))
        save()
        return evidence

    def desktop_login(self, user, password, timeout):
        deadline = time.monotonic() + self.report.remaining(timeout)
        initial = self.guest.check("session", user, timeout=60, name="session-before-login")
        require(not initial["ready"] and not initial["ddm_sessions"], "A graphical user session appeared before password entry (unexpected autologin).")
        checkpoint = {key: initial[key] for key in ("boot_id", "observed_at_monotonic_us")}
        (self.output / "graphical-login-checkpoint.json").write_text(json.dumps(checkpoint, indent=2) + "\n")
        # Keep the guest's normal greeter and compositor. OCR and the observed
        # control geometry locate the input, never its explanatory hint.
        screen, evidence = self.wait_greeter(user, deadline, "ddm-login",
            checkpoint=checkpoint, before_password=True)
        if not evidence["password_control"]:
            # Click only an observed user tile, then wait for its password UI.
            word = evidence["user_words"][0]
            self.qmp.click(word["left"] + word["width"] / 2, word["top"] + word["height"] / 2,
                           screen["width"], screen["height"])
            screen, evidence = self.wait_greeter(user, deadline, "ddm-login-password",
                checkpoint=checkpoint, password_required=True, before_password=True)
        input_evidence = self.submit_graphical_password(screen, evidence["password_control"], password, deadline)
        # Submit once. A slow/black authenticated session never receives a
        # second password; the remaining original deadline is for observation.
        last = None
        authenticated = False
        visible_since = None
        observation_deadline_error = None
        while time.monotonic() < deadline:
            time.sleep(max(0, min(3, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
            try:
                last = self.login_session(user, checkpoint, deadline, "session-login-progress")
            except GraphicalLoginDeadline as error:
                observation_deadline_error = error
                break
            if any(s.get("Service") == "ddm" and s.get("Class") == "user" for s in last["sessions"]):
                authenticated = True
            if last["ready"]:
                path = self.screenshot("desktop-frame")
                frame = dict(nonblack_frame(path), captured_at=utc(),
                             screenshot=str(path.relative_to(self.output)))
                with (self.output / "desktop-frame-events.jsonl").open("a") as events:
                    events.write(json.dumps(frame) + "\n")
                if frame["nonblack"]:
                    now = time.monotonic()
                    if visible_since is None:
                        visible_since = now
                    elif now - visible_since >= 8:
                        stable = self.login_session(user, checkpoint, deadline, "session-stable")
                        require(stable["ready"], "The graphical desktop session stopped during the stability check.")
                        return {"attempts": 1, "session": stable,
                                "nonblack_frame": frame, "nonblack_stable_seconds": round(now - visible_since, 3),
                                "crash_check_checkpoint": checkpoint, "password_input": input_evidence}
                else:
                    visible_since = None
            else:
                visible_since = None
        message = ("DDM authenticated the user, but no stable session with nonblack desktop frames appeared "
                   "before the graphical login deadline; see desktop-frame-events.jsonl." if authenticated else
                   "DDM did not create an authenticated Wayland + dde-shell session before the graphical login "
                   "deadline after one focused password submission. Last completed observation: " + json.dumps(last)[-3000:])
        if observation_deadline_error:
            message += " The final shortened observation also exhausted the stage deadline; its original framing error is retained."
        raise Failure(message) from observation_deadline_error

    def poweroff(self):
        framing_error = None
        try:
            self.guest.run("systemctl poweroff --no-block", "poweroff", timeout=30)
        except Failure as error:
            # systemd can stop the login shell before it prints the final
            # command marker. Only this poweroff action permits missing framing;
            # require an actual guest-shutdown QMP event and a clean QEMU exit.
            framing_error = str(error)
        deadline = time.monotonic() + self.report.remaining(180)
        while self.process.poll() is None and time.monotonic() < deadline:
            # Drain serial output and QMP events while the guest flushes files.
            with contextlib.suppress(Failure, OSError):
                self.serial.receive(0.2)
            with contextlib.suppress(Failure, OSError):
                self.qmp.read(time.monotonic() + 0.2)
        require(self.process.poll() == 0, "The guest did not complete a clean poweroff before the deadline.")
        for _ in range(10):
            try:
                self.qmp.read(time.monotonic() + 0.2)
            except (Failure, OSError):
                break
        shutdown = next((e for e in self.qmp.observed_events if e.get("event") == "SHUTDOWN"
                         and e.get("data", {}).get("guest") is True
                         and e.get("data", {}).get("reason") == "guest-shutdown"), None)
        require(shutdown is not None, "QEMU exited without an observed orderly guest shutdown.")
        (self.output / "shutdown.json").write_text(json.dumps({"qemu_exit_status": 0, "event": shutdown,
            "serial_marker_note": redact(framing_error) if framing_error else None}, indent=2) + "\n")

    def diagnostics(self, name="diagnostics"):
        if self.process is None or self.process.poll() is not None:
            return
        with contextlib.suppress(Exception):
            self.screen("failure-or-final-state" if name == "diagnostics" else name + "-state",
                        deadline=time.monotonic() + 60)
        if self.guest and self.guest.recover():
            try:
                data = self.guest.check("diagnostics", timeout=180, name=name, budget=False)
                (self.output / f"{name}.json").write_text(redact(json.dumps(data, indent=2)) + "\n")
                for key, value in data.items():
                    if re.fullmatch(r"dde_shell_(?:liveuser|vmtest)_coreinfo", key) and isinstance(value, dict):
                        (self.output / f"{name}-{key}.txt").write_text(redact(value.get("stdout", ""))
                            + "\n" + redact(value.get("stderr", "")))
            except Exception as error:
                (self.output / f"{name}-error.txt").write_text(redact(str(error)) + "\n")

    def close(self):
        if self.process is not None and self.process.poll() is None:
            if self.qmp:
                with contextlib.suppress(Exception):
                    self.qmp.execute("quit", timeout=5)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
        if self.qmp:
            self.qmp.close()
        if self.serial:
            self.serial.close()
        if hasattr(self, "logfile"):
            self.logfile.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scenario", choices=SCENARIOS, default="uefi-btrfs")
    parser.add_argument("--timeout", type=int, default=5400, help="Overall deadline in seconds (plus bounded failure diagnostics).")
    parser.add_argument("--boot-timeout", type=int, default=900)
    parser.add_argument("--desktop-timeout", type=int, default=420)
    parser.add_argument("--continue-after-desktop-failure", action="store_true",
                        help="Diagnose independent installation/reboot checks after a failed desktop stage; the overall result still fails.")
    parser.add_argument("--memory", type=int, help="Guest RAM in MiB; defaults to at most 8192, keeping host headroom.")
    parser.add_argument("--cpus", type=int, help="Guest vCPUs; defaults to at most 4.")
    parser.add_argument("--ovmf-code")
    parser.add_argument("--ovmf-vars")
    parser.add_argument("--keep-disk", action="store_true", help="Keep the disposable qcow2 after a successful test.")
    args = parser.parse_args()
    os.umask(0o077)
    require(args.timeout >= 300 and args.boot_timeout > 0 and args.desktop_timeout > 0, "Invalid timeout.")
    args.iso = args.iso.resolve(strict=True)
    require(args.iso.is_file() and args.iso.stat().st_size > 0, "The final ISO is missing.")
    work, output = args.work_dir.resolve(), args.output_dir.resolve()
    require(not work.exists() or work.is_dir() and not any(work.iterdir()), "--work-dir must be new or empty.")
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), "--output-dir must be new or empty.")
    require(work != output and not work.is_relative_to(output) and not output.is_relative_to(work),
            "Keep large VM scratch files separate from uploaded evidence.")
    require("," not in str(work) + str(output) + str(args.iso), "QEMU option paths must not contain commas.")
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    report = Report(output, args.timeout)
    report.data["scenario"] = args.scenario
    report.data["graphical_layout_planner_tested"] = False
    report.data["continue_after_desktop_failure"] = args.continue_after_desktop_failure
    report.data["desktop_failures"] = []
    report.data["installation_checks_completed"] = False
    vm = None
    failure = None

    def record_desktop_failure(phase, error):
        # The stage context has already marked this stage FAILED. Preserve its
        # failure-time diagnostics separately from later installation logs.
        detail = vm.output / "desktop-failure.txt"
        detail.write_text(redact(traceback.format_exc()))
        report.data["desktop_failures"].append({"phase": phase, "error": redact(str(error)),
            "failed_at": utc(), "traceback": str(detail.relative_to(output)),
            "continued_for_installation_diagnostics": args.continue_after_desktop_failure})
        report.save()
        if args.continue_after_desktop_failure:
            log(f"FAILED {phase} desktop stage: {error}; continuing independent installation checks for diagnostics.")
            vm.diagnostics(name="desktop-failure-diagnostics")

    def interrupted(signum, frame):
        # Cancellation must never enter the optional desktop-failure recovery
        # path and start further installation work.
        raise InterruptedError(f"Received signal {signum}; collecting diagnostics before stopping QEMU.")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        with report.stage("host-preflight"):
            try:
                from PIL import Image
            except ImportError as error:
                raise Failure("Required host dependency is missing: python3-pil (Pillow).") from error
            for name in ("qemu-system-x86_64", "qemu-img", "xorriso", "tesseract"):
                require(shutil.which(name), f"Required host command is missing: {name}")
            helper = Path(__file__).resolve().with_name("vm-guest.py")
            require(helper.is_file(), "vm-guest.py is missing next to the controller.")
            free = shutil.disk_usage(work).free
            minimum = max(20 * 1024**3, args.iso.stat().st_size * 2 + 8 * 1024**3)
            require(free >= minimum, f"VM scratch needs at least {minimum // 1024**3} GiB free, available {free // 1024**3} GiB.")
            total_mib = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 1024**2
            memory = args.memory or min(8192, max(4096, total_mib - 3072))
            cpus = args.cpus or min(4, os.cpu_count() or 1)
            require(4096 <= memory < total_mib - 1024 and 1 <= cpus <= (os.cpu_count() or 1), "Guest resource settings exceed runner capacity.")
            uefi = not args.scenario.startswith("bios-")
            firmware, variables = firmware_paths(args) if uefi else (None, None)
            disk_size = 16_000_000_000 if args.scenario in {"uefi-small", "uefi-luks-btrfs-small"} else 64 * 1024**3
            accel, probe = accelerator(output, work)
            log(f"Using {accel.upper()}, {cpus} vCPUs, {memory} MiB RAM; KVM probe {'passed' if accel == 'kvm' else 'failed, real TCG fallback will run'}.")
            report.data.update(iso={"filename": args.iso.name, "sha256": sha256(args.iso), "size": args.iso.stat().st_size},
                               acceleration={"selected": accel, "kvm_probe": probe},
                               resources={"vcpus": cpus, "memory_mib": memory, "scratch_free_bytes": free, "disk_virtual_bytes": disk_size},
                               firmware=({"mode": "uefi", "code": str(firmware), "sha256": sha256(firmware), "vars_template": str(variables)}
                                         if uefi else {"mode": "bios", "implementation": "QEMU packaged SeaBIOS"}),
                               tools={"qemu": command(["qemu-system-x86_64", "--version"]).stdout.splitlines()[0],
                                      "guest_helper_sha256": sha256(helper)}, test_account=TEST_USER)
            if uefi:
                shutil.copyfile(variables, work / "OVMF_VARS.fd")
            command(["qemu-img", "create", "-f", "qcow2", str(work / "install.qcow2"), str(disk_size)])
            result = command(["xorriso", "-osirrox", "on", "-indev", str(args.iso),
                              "-extract", "/EFI/BOOT/grub.cfg" if uefi else "/boot/grub2/grub.cfg", str(output / "iso-grub.cfg")])
            (output / "extract-grub.log").write_text(result.stdout + result.stderr)
            grub = parse_grub((output / "iso-grub.cfg").read_text())
            report.data["boot_commands"] = grub

        with report.stage("boot-final-iso-and-login-serial"):
            vm = VM(args, report, work, output / "live", firmware, accel, cpus, memory, "live")
            vm.boot_live(grub, args.boot_timeout)
            vm.guest.login(LIVE_USER, LIVE_PASSWORD, report.remaining(args.boot_timeout))
            vm.guest.upload_helper(helper, args.scenario)

        with report.stage("live-enforcing-policies-and-account"):
            live = vm.guest.check("baseline", "live", timeout=300)
            report.data["evidence"]["live"] = live

        try:
            with report.stage("live-ddm-password-login-and-desktop"):
                report.data["evidence"]["live_login"] = vm.desktop_login(LIVE_USER, LIVE_PASSWORD, args.desktop_timeout)
            with report.stage("live-desktop-assets"):
                report.data["evidence"]["live_desktop_assets"] = vm.guest.check("desktop-assets", LIVE_USER, timeout=90)
            with report.stage("live-native-pam"):
                report.data["evidence"]["live_pam"] = vm.guest.check("pam", LIVE_USER, timeout=180)
        except Failure as error:
            record_desktop_failure("live", error)
            if not args.continue_after_desktop_failure:
                raise

        with report.stage("prepare-disposable-partition-scenario"):
            report.data["evidence"]["partition_plan"] = vm.guest.check("prepare", timeout=180)

        for stage in ("preflight", "partition", "copy", "system", "ready", "configure", "finalize"):
            with report.stage("installer-" + stage):
                if stage == "configure":
                    report.data["evidence"]["account_configuration"] = vm.guest.check("account", timeout=120)
                result = vm.guest.check("stage", stage, timeout=3600, name="backend-" + stage)
                report.data["evidence"].setdefault("backend_stages", []).append(result)
                if stage == "configure" and "-luks-" in args.scenario:
                    report.data["evidence"]["encrypted_target"] = vm.guest.check("encryption-check", "target", timeout=180)

        with report.stage("finalize-and-power-off-live"):
            installed = vm.guest.check("installed-state", timeout=120)
            report.data["evidence"]["installation"] = installed
            vm.screenshot("installation-finished-live")
            diagnostics = vm.guest.check("diagnostics", timeout=180)
            (vm.output / "diagnostics.json").write_text(redact(json.dumps(diagnostics, indent=2)) + "\n")
            vm.poweroff()
            vm.close()
            vm = None

        with report.stage("boot-installed-disk-without-iso"):
            vm = VM(args, report, work, output / "installed", firmware,
                    report.data["acceleration"]["selected"], cpus, memory, "installed")
            require(not any("id=live" in arg or str(args.iso) in arg for arg in vm.command), "The installed VM still has the ISO attached.")
            unlock = vm.unlock_root(installed, args.boot_timeout) if "-luks-" in args.scenario else None
            vm.guest.login(TEST_USER, TEST_PASSWORD, report.remaining(args.boot_timeout))
            if unlock:
                report.data["evidence"]["encrypted_disk_boot"] = unlock
            vm.guest.upload_helper(helper, args.scenario,
                                   {"installation": installed, "partition_plan": report.data["evidence"]["partition_plan"]})
            vm.screenshot("installed-disk-login")

        with report.stage("installed-enforcing-partitions-user-and-boot"):
            disk = vm.guest.check("baseline", "installed", installed["root_uuid"], timeout=300)
            require(disk["boot_id"] != live["boot_id"], "The installed system did not reboot into a new kernel session.")
            require(disk["build_info"] == live["build_info"], "The installed system differs from the tested ISO build provenance.")
            report.data["evidence"]["installed"] = disk
            report.data["installation_checks_completed"] = True

        try:
            with report.stage("installed-ddm-password-login-and-desktop"):
                report.data["evidence"]["installed_login"] = vm.desktop_login(TEST_USER, TEST_PASSWORD, args.desktop_timeout)
            with report.stage("installed-desktop-assets"):
                report.data["evidence"]["installed_desktop_assets"] = vm.guest.check("desktop-assets", TEST_USER, timeout=90)
            with report.stage("installed-native-pam"):
                report.data["evidence"]["installed_pam"] = vm.guest.check("pam", TEST_USER, timeout=180)
                policy = vm.guest.check("baseline", "installed", installed["root_uuid"], timeout=300, name="after-login-enforcing")
                report.data["evidence"]["enforcing_after_desktop_login"] = policy["selinux"]
        except Failure as error:
            record_desktop_failure("installed", error)
            if not args.continue_after_desktop_failure:
                raise

        with report.stage("collect-evidence-and-shut-down-installed-system"):
            diagnostics = vm.guest.check("diagnostics", timeout=180)
            (vm.output / "diagnostics.json").write_text(redact(json.dumps(diagnostics, indent=2)) + "\n")
            vm.screenshot("installed-system-final-state")
            vm.poweroff()
            vm.close()
            vm = None
            require(sha256(args.iso) == report.data["iso"]["sha256"], "The release ISO changed during testing.")
        report.data["iso_unchanged"] = True
        if report.data["desktop_failures"]:
            phases = ", ".join(item["phase"] for item in report.data["desktop_failures"])
            raise Failure("Installation, disk-only reboot and installed-system checks completed, "
                          f"but desktop stages failed ({phases}); this diagnostic run has not passed.")
        report.data.update(status="passed", finished_at=utc(), iso_unchanged=True)
        log("PASS automated checks: real installation, disk-only reboot, Enforcing SELinux, DDM sessions "
            "and stable nonblack frames verified. Review the captured desktop images for usability.")
    except BaseException as error:
        failure = error
        report.data.update(status="failed", finished_at=utc(), error=redact(str(error)))
        (output / "failure.txt").write_text(redact(traceback.format_exc()))
        log(f"FAIL: {error}")
        if vm:
            vm.diagnostics()
    finally:
        if vm:
            vm.close()
        report.save()
        # Keep a failed disk for local diagnosis, but never include it in the
        # evidence directory uploaded by Actions. Its test password is public.
        if not failure and not args.keep_disk:
            (work / "install.qcow2").unlink(missing_ok=True)
        log(f"Report: {report.path}")
    return 1 if failure else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        log(f"FAIL before VM setup: {error}")
        sys.exit(1)
