#!/usr/bin/env python3
"""Check the VM controller against real host sudo and Bash in a disposable PTY.

Run as the ordinary Actions runner user with its existing sudo -n permission.
Only the sudo child becomes root. No accounts, PAM rules, services, disks or
host configuration are changed. All uploaded fixture files stay in a temporary
directory and the actual VM guest helper is never executed on the host.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pty
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import uuid


class PtyTransport:
    def __init__(self, descriptor):
        self.descriptor = descriptor

    def fileno(self):
        return self.descriptor

    def send(self, data):
        return os.write(self.descriptor, data)

    def recv(self, size):
        return os.read(self.descriptor, size)

    def close(self):
        os.close(self.descriptor)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Run this smoke check as the ordinary runner user; only its sudo child should become root.")
    if not shutil.which("sudo"):
        raise RuntimeError("This smoke check requires the host's real sudo executable.")
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().with_name("test-install-vm.py")
    spec = importlib.util.spec_from_file_location("fedora_dde_vm_controller", source)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    helper = source.with_name("vm-guest.py")
    with tempfile.TemporaryDirectory(prefix="fedora-dde-vm-shell-") as directory:
        scratch = Path(directory)
        output = scratch / "evidence"
        output.mkdir()
        runtime = scratch / "runtime"
        runtime.mkdir(mode=0o700)
        report = controller.Report(output, 120)
        token = uuid.uuid4().hex[:12]
        password_token = "__VM_HOST_SUDO_" + token + "__"
        root_token = "__VM_HOST_ROOT_UID_" + token + "__"
        command = controller.sudo_shell_command(password_token, root_token, non_interactive=True)
        master, slave = pty.openpty()
        process = serial = guest = None

        def attach_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        class ScratchGuest(controller.Guest):
            def run(self, text, *args, **kwargs):
                # Exercise the production upload/check framing, but redirect
                # its fixed /run location into this disposable fixture only.
                text = text.replace("/run/fedora-dde-vmtest", shlex.quote(str(runtime)))
                return super().run(text, *args, **kwargs)

        try:
            process = subprocess.Popen(
                ["/bin/bash", "--noprofile", "--norc", "-c", command],
                stdin=slave, stdout=slave, stderr=slave, cwd=scratch,
                env=dict(os.environ, TERM="xterm", HISTFILE="/dev/null"),
                preexec_fn=attach_terminal)
            os.close(slave)
            slave = None
            serial = controller.Serial.__new__(controller.Serial)
            serial.process, serial.socket, serial.buffer = process, PtyTransport(master), ""
            _, ready = serial.expect(r"(?:^|\n)" + root_token + r"[0-9]+\n", 30)
            controller.require(ready.strip() == root_token + "0", "The real sudo child did not report UID 0.")
            serial.expect(r"(?:^|\n)__VM_ROOT_READY__ ?", 10)
            guest = ScratchGuest(serial, report, output)
            guest.ready = True
            _, uid = guest.run("/usr/bin/id -u", "real-root-uid", timeout=10)
            controller.require(uid.strip() == "0", "Guest.run did not execute in the actual root shell.")
            status, body = guest.run("printf 'smoke-status\\n'; (exit 23)", "nonzero-status", timeout=10, check=False)
            controller.require(status == 23 and "smoke-status" in body, "Nonzero command framing was lost.")
            try:
                guest.run("(exit 31)", "checked-failure", timeout=10)
            except controller.Failure as error:
                controller.require("failed (31)" in str(error), "The wrong failure was reported.")
            else:
                raise RuntimeError("A failing command was incorrectly accepted.")

            fixture = "host-pty-fixture-" + "x" * 8192
            guest.upload_helper(helper, "uefi-small", {"fixture": fixture})
            # Run a tiny read-only verifier, not the guest helper or its disk
            # actions. Check actual uploaded bytes, context and permissions.
            verification = (
                "import hashlib,json,pathlib; "
                f"p=pathlib.Path({str(runtime)!r}); "
                "c=json.loads((p/'context.json').read_text()); "
                "print(json.dumps({'sha256':hashlib.sha256((p/'guest.py').read_bytes()).hexdigest(),"
                "'fixture':c['fixture'],'mode':(p/'guest.py').stat().st_mode & 511,'scenario':c['scenario']}))")
            _, uploaded = guest.run(shlex.join(["/usr/bin/python3", "-I", "-c", verification]),
                                    "verify-upload", timeout=15)
            result = json.loads(uploaded.strip())
            controller.require(result == {"sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
                               "fixture": fixture, "mode": 0o600, "scenario": "uefi-small"},
                               "The production helper upload failed its byte/context/permission check.")
            guest.run("rm -rf -- " + shlex.quote(str(runtime)), "remove-fixture", timeout=10)
            serial.send("exit\n")
            controller.require(process.wait(timeout=10) == 0, "The real sudo shell did not exit cleanly.")
            print(json.dumps({"status": "passed", "actual_sudo": True, "uid": 0,
                              "root_prompt": "verified", "command_statuses": [0, 23, 31],
                              "helper_sha256": result["sha256"], "helper_mode": "0600",
                              "context_bytes": len(fixture)}, sort_keys=True))
        except BaseException:
            if serial is not None:
                print("Last PTY output: " + controller.redact(serial.buffer[-5000:]), file=sys.stderr)
            raise
        finally:
            if guest is not None and process.poll() is None:
                with contextlib.suppress(Exception):
                    guest.run("rm -rf -- " + shlex.quote(str(runtime)), "cleanup", timeout=5, budget=False)
                    serial.send("exit\n")
                    process.wait(timeout=5)
            if process is not None and process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            if slave is not None:
                os.close(slave)
            if serial is not None:
                serial.close()
            else:
                os.close(master)


if __name__ == "__main__":
    main()
