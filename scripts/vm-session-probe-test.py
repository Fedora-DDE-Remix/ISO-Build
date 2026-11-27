#!/usr/bin/env python3
"""Read-only guest session regressions; no VM, system service or root access.

Run with python3 scripts/vm-session-probe-test.py. One test starts a disposable
Python sleeper to verify that a command timeout kills and reaps its child.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("vm_guest", Path(__file__).with_name("vm-guest.py"))
VM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VM)
BOOT = "11111111-2222-3333-4444-555555555555"


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def monotonic_ns(self):
        return int(self.now * 1_000_000_000)


class SessionProbeRegression(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.enterContext(mock.patch.object(VM.time, "monotonic", self.clock.monotonic))
        self.enterContext(mock.patch.object(VM.time, "monotonic_ns", self.clock.monotonic_ns))
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        (self.root / "boot-id").write_text(BOOT)
        (self.root / "runtime").mkdir()
        real_path = Path

        def path(value):
            if str(value) == "/proc/sys/kernel/random/boot_id":
                return self.root / "boot-id"
            if str(value) == "/run/user/1000":
                return self.root / "runtime"
            return real_path(value)

        self.enterContext(mock.patch.object(VM, "Path", side_effect=path))
        self.enterContext(mock.patch.object(VM.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1000)))
        self.authorization_delay = 0
        self.authorization = self.enterContext(mock.patch.object(VM, "authorize", side_effect=self.authorize))
        self.processes = self.enterContext(mock.patch.object(VM, "processes", return_value=[
            {"uid": 1000, "comm": "dde-shell", "pid": 42, "exe": "/usr/bin/dde-shell"},
            {"uid": 981, "comm": "treeland", "pid": 41, "exe": "/usr/bin/treeland"},
        ]))
        self.commands = []
        self.delays = {}
        self.failures = {}
        self.journal = ""
        self.listing = "3 1000 liveuser seat0 42 user tty1 no -\n"
        self.properties = ("Id=3\nName=liveuser\nService=ddm\nType=wayland\nClass=user\n"
                           "Active=yes\nState=active\n")
        self.runner = self.enterContext(mock.patch.object(VM, "run", side_effect=self.command))

    def authorize(self, *, probe):
        probe.marker("authorize", "begin")
        self.clock.now += self.authorization_delay
        probe.remaining("authorize")
        probe.marker("authorize", "complete")

    def command(self, argv, *, timeout, check):
        self.assertFalse(check)
        key = " ".join(argv[:2])
        self.commands.append((key, timeout))
        delay = self.delays.get(key, 0)
        if delay >= timeout:
            self.clock.now += timeout
            raise subprocess.TimeoutExpired(argv, timeout)
        self.clock.now += delay
        output = {"journalctl -b": self.journal, "loginctl list-sessions": self.listing,
                  "loginctl show-session": self.properties}.get(key, "")
        return subprocess.CompletedProcess(argv, self.failures.get(key, 0), output, "simulated error")

    def sample(self, **kwargs):
        return VM.session("liveuser", "90000000", BOOT, **kwargs)

    def crash(self):
        return {"__MONOTONIC_TIMESTAMP": "95000000", "_BOOT_ID": BOOT.replace("-", ""),
                "COREDUMP_UID": "1000", "COREDUMP_EXE": "/usr/bin/dde-shell",
                "COREDUMP_PID": "42", "COREDUMP_SIGNAL": "11"}

    def test_complete_session_requires_all_original_evidence(self):
        result = self.sample()
        self.assertTrue(result["probe_complete"])
        self.assertTrue(result["crash_check_complete"])
        self.assertEqual(result["dde_shell_crashes"], [])
        self.assertTrue(result["ready"])
        self.assertEqual(result["treeland"][0]["uid"], 981)
        self.assertEqual(result["probe_errors"], [])

    def test_complete_negative_sample_is_not_a_timeout_or_a_ready_desktop(self):
        self.properties = self.properties.replace("Service=ddm", "Service=login").replace("Type=wayland", "Type=tty")
        result = self.sample()
        self.assertTrue(result["probe_complete"])
        self.assertTrue(result["crash_check_complete"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["ddm_sessions"], [])

    def test_missing_shell_never_passes_a_complete_sample(self):
        self.processes.return_value = [{"uid": 981, "comm": "treeland", "pid": 41}]
        result = self.sample()
        self.assertTrue(result["probe_complete"])
        self.assertFalse(result["ready"])

    def test_authorization_and_every_command_share_one_total_budget(self):
        self.authorization_delay = 4
        self.delays = {"journalctl -b": 12, "loginctl list-sessions": 12, "loginctl show-session": 3}
        result = self.sample(budget_seconds=30)
        self.assertEqual(self.commands, [("journalctl -b", 15), ("loginctl list-sessions", 14),
                                         ("loginctl show-session", 2)])
        self.assertEqual(result["probe_elapsed_seconds"], 30)
        self.assertFalse(result["probe_complete"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["probe_errors"][0]["stage"], "loginctl-show:3")
        self.processes.assert_not_called()

    def test_unknown_crash_journal_is_null_and_never_ready(self):
        self.delays["journalctl -b"] = 60
        result = self.sample()
        self.assertFalse(result["probe_complete"])
        self.assertFalse(result["crash_check_complete"])
        self.assertIsNone(result["dde_shell_crashes"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["probe_errors"][0]["kind"], "timeout")

    def test_failed_journal_command_is_not_an_empty_crash_list(self):
        self.failures["journalctl -b"] = 1
        result = self.sample()
        self.assertFalse(result["probe_complete"])
        self.assertIsNone(result["dde_shell_crashes"])
        self.assertEqual(result["probe_errors"][0]["kind"], "command-failed")

    def test_real_crash_cannot_pass_otherwise_complete_session(self):
        event = self.crash()
        self.journal = json.dumps(event) + "\n"
        result = self.sample()
        self.assertTrue(result["probe_complete"])
        self.assertTrue(result["crash_check_complete"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["dde_shell_crashes"], [event])

    def test_known_crash_survives_later_loginctl_timeout(self):
        event = self.crash()
        self.journal = json.dumps(event) + "\n"
        self.delays["loginctl list-sessions"] = 60
        result = self.sample()
        self.assertFalse(result["probe_complete"])
        self.assertTrue(result["crash_check_complete"])
        self.assertEqual(result["dde_shell_crashes"], [event])
        self.assertFalse(result["ready"])

    def test_known_crash_survives_partial_malformed_journal(self):
        event = self.crash()
        self.journal = json.dumps(event) + "\n{\n"
        result = self.sample()
        self.assertFalse(result["probe_complete"])
        self.assertFalse(result["crash_check_complete"])
        self.assertEqual(result["dde_shell_crashes"], [event])
        self.assertFalse(result["ready"])

    def test_authorization_and_changed_boot_identity_remain_hard_failures(self):
        for message in ("VM checks must run through normal guest sudo authentication.",
                        "This is not the isolated test-install-vm QEMU guest.",
                        "Missing private VM authorization marker."):
            with self.subTest(message=message):
                self.authorization.side_effect = RuntimeError(message)
                with self.assertRaisesRegex(RuntimeError, message):
                    self.sample()
        self.authorization.side_effect = self.authorize
        with self.assertRaisesRegex(RuntimeError, "guest rebooted"):
            VM.session("liveuser", "90000000", "another-boot")
        self.runner.assert_not_called()

    def test_initial_cli_sample_uses_budget_before_authorization(self):
        self.authorization_delay = 7
        argv = ["vm-guest.py", "session", "liveuser", "--probe-budget-seconds", "6"]
        with mock.patch.object(VM.sys, "argv", argv):
            VM.main()
        lines = self.output.getvalue().splitlines()
        result = json.loads(next(line.split("=", 1)[1] for line in lines if line.startswith("VMTEST_RESULT=")))
        self.assertFalse(result["probe_complete"])
        self.assertIsNone(result["boot_id"])
        self.assertIsNone(result["dde_shell_crashes"])
        self.assertEqual(result["probe_errors"][0]["stage"], "authorize")
        self.runner.assert_not_called()
        self.assertTrue(any('"event": "incomplete"' in line for line in lines))

    def test_invalid_or_unbounded_budget_is_rejected(self):
        for value in (0, -1, 31, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.sample(budget_seconds=value)
        self.authorization.assert_not_called()


class ActualCommandTimeout(unittest.TestCase):
    def test_hung_child_is_killed_reaped_and_keeps_outer_timeout_process_group(self):
        children = []
        real_popen = subprocess.Popen

        def record(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append((child, os.getpgid(child.pid)))
            return child

        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(VM.subprocess, "Popen", side_effect=record):
            probe = VM.SessionProbe(2)
            with self.assertRaises(VM.ProbeIncomplete) as caught:
                probe.command("disposable-sleeper", [sys.executable, "-c", "import time; time.sleep(60)"], cap=0.15)
        self.assertEqual(caught.exception.detail["kind"], "timeout")
        self.assertEqual(len(children), 1)
        child, group = children[0]
        self.assertIsNotNone(child.poll())
        self.assertEqual(group, os.getpgrp())


if __name__ == "__main__":
    unittest.main(verbosity=2)
