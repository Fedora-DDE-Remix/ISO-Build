#!/usr/bin/env python3
"""Boot the final ISO, install it, and test the installed DDE desktop under QEMU.

Host dependencies (Ubuntu 24.04): qemu-system-x86 qemu-utils ovmf xorriso
tesseract-ocr, plus Python 3's standard library. Run outside the compose
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
LIVE_USER = "liveuser"
LIVE_PASSWORD = "liveuser"
SCENARIOS = ("uefi-btrfs", "bios-ext4", "bios-mbr-ext4", "uefi-xfs-home-swap", "uefi-preserve", "uefi-small")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


class Failure(RuntimeError):
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
    return value.replace(TEST_PASSWORD, "[disposable test password]")


def log(message):
    print(f"[{utc()}] vm-test: {redact(str(message))}", flush=True)


def command(argv, *, timeout=120, check=True, input_text=None):
    result = subprocess.run(argv, input=input_text, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise Failure(f"{argv[0]} failed ({result.returncode}): {(result.stderr or '')[-4000:]}")
    return result


class Report:
    def __init__(self, directory, timeout):
        self.directory = directory
        self.path = directory / "report.json"
        self.started = time.monotonic()
        self.deadline = self.started + timeout
        self.data = {"schema": 1, "status": "running", "started_at": utc(), "timeout_seconds": timeout,
                     "scope": "Final ISO firmware boot, real backend installation, disk-only reboot, DDM Wayland login",
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

    def key(self, *keys):
        self.execute("send-key", {"keys": [{"type": "qcode", "data": key} for key in keys], "hold-time": 30})
        time.sleep(0.045)

    def type(self, text):
        plain = {" ": "spc", "-": "minus", "=": "equal", "/": "slash", ".": "dot", ",": "comma",
                 ";": "semicolon", "'": "apostrophe", "[": "bracket_left", "]": "bracket_right",
                 "\\": "backslash", "`": "grave_accent", "\n": "ret", "\t": "tab"}
        shifted = {"_": "minus", "+": "equal", ":": "semicolon", '"': "apostrophe", "?": "slash",
                   "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
                   "*": "8", "(": "9", ")": "0", "<": "comma", ">": "dot", "|": "backslash",
                   "{": "bracket_left", "}": "bracket_right", "~": "grave_accent"}
        for char in text:
            if "A" <= char <= "Z":
                self.key("shift", char.lower())
            elif char in shifted:
                self.key("shift", shifted[char])
            elif char in plain:
                self.key(plain[char])
            elif char.isascii() and char.isalnum():
                self.key(char)
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
            self.buffer += ANSI.sub("", data.decode("utf-8", errors="replace")).replace("\r", "")
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
            require(time.monotonic() < deadline, f"Timed out waiting for serial pattern {pattern!r}; tail: {redact(self.buffer[-2000:])}")
            require(self.process.poll() is None, "QEMU exited while waiting for the guest serial console.")
            self.receive(min(0.5, max(0, deadline - time.monotonic())))

    def close(self):
        self.socket.close()


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
        self.serial.expect(r"(?:^|\n)[^\n]{0,180}[\$#] ?$", max(1, deadline - time.monotonic()))
        self.serial.send("sudo -S -p '__VM_SUDO_PASSWORD__' -i\n")
        _, response = self.serial.expect(r"(?:^|\n)__VM_SUDO_PASSWORD__|(?:^|\n)[^\n]{0,180}# ?$", 60)
        if "__VM_SUDO_PASSWORD__" in response:
            self.serial.send(password + "\n")
            self.serial.expect(r"(?:^|\n)[^\n]{0,180}# ?$", 60)
        self.serial.send("stty -echo; export PS1='__VM_ROOT_READY__ '; export HISTFILE=/dev/null; set +o history; printf '\\n__VM_ROOT_READY__\\n'\n")
        self.serial.expect(r"\n__VM_ROOT_READY__\n", 30)
        self.ready = True

    def run(self, text, name, timeout=120, check=True, budget=True):
        self.counter += 1
        token = f"{self.counter}_{uuid.uuid4().hex[:8]}"
        begin, end = f"__VM_BEGIN_{token}__", f"__VM_END_{token}__"
        duration = self.report.remaining(timeout) if budget else timeout
        # Separate physical lines keep the canonical TTY input below 4096 bytes,
        # including while uploading a base64-encoded guest helper via heredoc.
        wrapped = f"printf '\\n{begin}\\n'; {{\n{text}\n}}; vm_status=$?; printf '\\n{end}%s\\n' \"$vm_status\"\n"
        self.serial.send(wrapped)
        self.serial.expect(re.escape(begin) + r"\n", min(60, duration))
        body, result = self.serial.expect(re.escape(end) + r"[0-9]+\n", duration)
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


def accelerator(output):
    request = '\n'.join(json.dumps({"execute": name}) for name in ("qmp_capabilities", "query-kvm", "quit")) + "\n"
    argv = ["qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host", "-m", "128",
            "-nodefaults", "-display", "none", "-S", "-qmp", "stdio"]
    try:
        result = command(argv, timeout=20, check=False, input_text=request)
        (output / "kvm-probe.log").write_text(result.stdout + result.stderr)
        values = []
        for line in result.stdout.splitlines():
            try:
                values.append(json.loads(line))
            except ValueError:
                continue
        enabled = result.returncode == 0 and any(v.get("return", {}).get("enabled") is True for v in values
                                               if isinstance(v.get("return"), dict))
        if enabled:
            return "kvm", {"available": True, "probe_status": result.returncode}
        return "tcg", {"available": False, "probe_status": result.returncode,
                        "reason": (result.stderr or result.stdout)[-3000:]}
    except (OSError, subprocess.TimeoutExpired) as error:
        (output / "kvm-probe.log").write_text(str(error) + "\n")
        return "tcg", {"available": False, "reason": str(error)}


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
        self.command = argv
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
            require(actual == accel, "QEMU's actual accelerator differs from the recorded selection.")
            self.report.data["acceleration"][phase] = {"actual": actual, "qmp": acceleration}
            self.report.save()
            self.serial = Serial(serial_path, self.process)
            self.guest = Guest(self.serial, report, output)
            self.qmp.execute("cont")
        except BaseException:
            self.close()
            raise

    def screenshot(self, name=None):
        self.counter += 1
        path = (self.snapshots / f"{self.counter:03d}-{name}.png") if name else self.work / f"{self.phase}-current.png"
        self.qmp.execute("screendump", {"filename": str(path), "format": "png"})
        return path

    def screen(self, name=None):
        path = self.screenshot(name)
        image = path.read_bytes()
        require(image.startswith(b"\x89PNG\r\n\x1a\n"), "QMP did not produce a PNG screenshot.")
        width, height = struct.unpack(">II", image[16:24])
        value = command(["tesseract", str(path), "stdout", "--psm", "11", "tsv"], timeout=30).stdout
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
            screen = self.screen()
            if re.search(r"GNU\s+GRUB|Start\s+Fedora|Test\s+this\s+media|Troubleshooting", screen["text"], re.I):
                self.screenshot("iso-grub-menu")
                break
            time.sleep(2)
        else:
            raise Failure("The final ISO GRUB menu did not appear before its deadline.")
        self.qmp.key("c")
        time.sleep(0.5)
        self.qmp.type("serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1\n")
        self.qmp.type("terminal_input --append serial\n")
        self.qmp.type("terminal_output --append serial\n")
        self.serial.expect(r"grub>\s*", self.report.remaining(60))
        for key in ("search", "kernel", "initrd"):
            self.serial.send(grub[key] + "\n")
            text, _ = self.serial.expect(r"grub>\s*", self.report.remaining(120))
            require(not re.search(r"(?im)^error:", text), f"GRUB rejected the final ISO's {key} command: {text}")
        self.screenshot("iso-grub-serial-boot")
        self.serial.send("boot\n")

    def desktop_login(self, user, password, timeout):
        deadline = time.monotonic() + self.report.remaining(timeout)
        initial = self.guest.check("session", user, timeout=60, name="session-before-login")
        require(not initial["ready"] and not initial["ddm_sessions"], "A graphical user session appeared before password entry (unexpected autologin).")
        # Keep the guest's normal greeter and compositor. OCR locates the
        # password placeholder/user tile; no display-manager config is changed.
        initial_screen = self.screen("ddm-before-login")
        if not any("password" in w["text"].lower() for w in initial_screen["words"]):
            self.qmp.key("ret")
            time.sleep(1)
        attempts = []
        for attempt in range(2):
            require(time.monotonic() < deadline, "The graphical login deadline expired.")
            screen = self.screen(f"ddm-login-attempt-{attempt + 1}")
            password_words = [w for w in screen["words"] if "password" in w["text"].lower()]
            if password_words:
                word = password_words[0]
                self.qmp.click(word["left"] + word["width"] / 2, word["top"] + word["height"] / 2,
                               screen["width"], screen["height"])
            elif attempt == 1:
                # An unselected user tile is the common alternative to the
                # initially focused password field. Only click its observed
                # label, never a guessed screen coordinate.
                names = {user.casefold(), "live" if user == LIVE_USER else user.casefold()}
                candidates = [w for w in screen["words"] if w["text"].casefold().strip(".,:") in names]
                require(candidates, "No password field or matching user tile could be located in the real DDM screen.")
                word = candidates[0]
                self.qmp.click(word["left"] + word["width"] / 2, word["top"] + word["height"] / 2,
                               screen["width"], screen["height"])
                time.sleep(1)
            self.qmp.key("ctrl", "a")
            self.qmp.type(password)
            self.qmp.key("ret")
            window = min(deadline, time.monotonic() + (90 if attempt == 0 else 180))
            last = None
            while time.monotonic() < window:
                time.sleep(3)
                last = self.guest.check("session", user, timeout=45, name="session-login-progress")
                if last["ready"]:
                    time.sleep(8)
                    stable = self.guest.check("session", user, timeout=45, name="session-stable")
                    require(stable["ready"], "The DDM Wayland desktop crashed immediately after login.")
                    self.screen("dde-desktop-after-login")
                    return {"attempts": attempt + 1, "session": stable}
            attempts.append(last)
        raise Failure("DDM did not create a stable Wayland + dde-shell desktop after password login; "
                      + json.dumps(attempts)[-3000:])

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

    def diagnostics(self):
        if self.process is None or self.process.poll() is not None:
            return
        with contextlib.suppress(Exception):
            self.screen("failure-or-final-state")
        if self.guest and self.guest.recover():
            try:
                data = self.guest.check("diagnostics", timeout=180, name="diagnostics", budget=False)
                (self.output / "diagnostics.json").write_text(redact(json.dumps(data, indent=2)) + "\n")
            except Exception as error:
                (self.output / "diagnostics-error.txt").write_text(redact(str(error)) + "\n")

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
    vm = None
    failure = None

    def interrupted(signum, frame):
        raise Failure(f"Received signal {signum}; collecting diagnostics before stopping QEMU.")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        with report.stage("host-preflight"):
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
            disk_size = 16_000_000_000 if args.scenario == "uefi-small" else 64 * 1024**3
            accel, probe = accelerator(output)
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

        with report.stage("live-ddm-password-login-and-desktop"):
            report.data["evidence"]["live_login"] = vm.desktop_login(LIVE_USER, LIVE_PASSWORD, args.desktop_timeout)
            report.data["evidence"]["live_pam"] = vm.guest.check("pam", LIVE_USER, timeout=180)

        with report.stage("prepare-disposable-partition-scenario"):
            report.data["evidence"]["partition_plan"] = vm.guest.check("prepare", timeout=180)

        for stage in ("preflight", "partition", "copy", "system", "ready", "configure", "finalize"):
            with report.stage("installer-" + stage):
                if stage == "configure":
                    report.data["evidence"]["account_configuration"] = vm.guest.check("account", timeout=120)
                result = vm.guest.check("stage", stage, timeout=3600, name="backend-" + stage)
                report.data["evidence"].setdefault("backend_stages", []).append(result)

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
            vm = VM(args, report, work, output / "installed", firmware, accel, cpus, memory, "installed")
            require(not any("id=live" in arg or str(args.iso) in arg for arg in vm.command), "The installed VM still has the ISO attached.")
            vm.guest.login(TEST_USER, TEST_PASSWORD, report.remaining(args.boot_timeout))
            vm.guest.upload_helper(helper, args.scenario,
                                   {"installation": installed, "partition_plan": report.data["evidence"]["partition_plan"]})
            vm.screenshot("installed-disk-login")

        with report.stage("installed-enforcing-partitions-user-and-boot"):
            disk = vm.guest.check("baseline", "installed", installed["root_uuid"], timeout=300)
            require(disk["boot_id"] != live["boot_id"], "The installed system did not reboot into a new kernel session.")
            require(disk["build_info"] == live["build_info"], "The installed system differs from the tested ISO build provenance.")
            report.data["evidence"]["installed"] = disk

        with report.stage("installed-ddm-password-login-and-desktop"):
            report.data["evidence"]["installed_login"] = vm.desktop_login(TEST_USER, TEST_PASSWORD, args.desktop_timeout)
            report.data["evidence"]["installed_pam"] = vm.guest.check("pam", TEST_USER, timeout=180)
            policy = vm.guest.check("baseline", "installed", installed["root_uuid"], timeout=300, name="after-login-enforcing")
            report.data["evidence"]["enforcing_after_desktop_login"] = policy["selinux"]

        with report.stage("collect-evidence-and-shut-down-installed-system"):
            diagnostics = vm.guest.check("diagnostics", timeout=180)
            (vm.output / "diagnostics.json").write_text(redact(json.dumps(diagnostics, indent=2)) + "\n")
            vm.screenshot("installed-desktop-verified")
            vm.poweroff()
            vm.close()
            vm = None
            require(sha256(args.iso) == report.data["iso"]["sha256"], "The release ISO changed during testing.")
        report.data.update(status="passed", finished_at=utc(), iso_unchanged=True)
        log("PASS: final ISO installed through the real backend; disk-only reboot, Enforcing SELinux and both DDM desktops verified.")
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
