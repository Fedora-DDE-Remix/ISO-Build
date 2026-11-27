#!/usr/bin/env python3
"""Non-VM checks for bounded session probes, serial evidence and KVM diagnostics.

Uses GNU timeout and an ordinary local Bash/socket pair for the transport check.
No KVM device, guest disk, installed account or privileged configuration is used.
"""

import contextlib
import errno
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("bounded_vm_controller", ROOT / "test-install-vm.py")
CONTROLLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLLER)


class ControllerRegression(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.report = SimpleNamespace(remaining=lambda seconds: seconds)

    def guest(self):
        serial = mock.Mock()
        serial.buffer = ""
        return CONTROLLER.Guest(serial, self.report, self.output)

    def vm(self, observation):
        value = object.__new__(CONTROLLER.VM)
        value.output = self.output
        value.report = self.report
        value.guest = mock.Mock()
        value.guest.check.return_value = observation
        return value

    def incomplete(self):
        return {"probe_complete": False, "ready": False, "crash_check_complete": False,
                "dde_shell_crashes": None, "probe_errors": [{"stage": "sessions", "kind": "timeout"}]}

    def assert_process_exited(self, process, timeout=3):
        # timeout can die before every SIGKILL recipient has finished exiting.
        # Match the identity recorded before the timeout, not a reused PID.
        pid, starttime = process["pid"], process["starttime"]
        self.assertTrue(type(pid) is int and pid > 0 and type(starttime) is int and starttime > 0,
                        "The fixture did not record a valid process identity before timeout")
        began = time.monotonic()
        deadline = began + timeout
        observed = []
        while True:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2].split()
            except OSError as error:
                # Linux can reap a process after opening its procfs stat file.
                if error.errno not in {errno.ENOENT, errno.ESRCH}:
                    raise
                reason = "reaped"
                break
            state, current_starttime = fields[0], int(fields[19])
            self.assertGreater(current_starttime, 0, "Cannot verify the observed process starttime")
            if not observed or observed[-1] != state:
                observed.append(state)
            if current_starttime != starttime:
                reason = "pid-reused"
                break
            if state in {"Z", "X"}:
                reason = "terminated"
                break
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0,
                               f"Process {pid} (starttime {starttime}) remained alive after "
                               f"{timeout}s; observed states: {observed}")
            time.sleep(min(0.02, remaining))
        return dict(process, exit_observed=reason, states=observed,
                    elapsed_seconds=round(time.monotonic() - began, 4))

    @staticmethod
    def process_stat_fixture(state, starttime):
        # Fields after the final ')' start at state (3); starttime is field 22.
        return "123 (test ) process) " + " ".join([state, *(["0"] * 18), str(starttime)])

    def test_reaped_process_race_accepts_only_missing_process_errors(self):
        process = {"pid": 123, "starttime": 456}
        for number in (errno.ENOENT, errno.ESRCH):
            with self.subTest(errno=number), mock.patch.object(Path, "read_text", side_effect=OSError(number, "reaped")):
                self.assert_process_exited(process)
        with mock.patch.object(Path, "read_text", side_effect=PermissionError(errno.EACCES, "denied")):
            with self.assertRaises(PermissionError):
                self.assert_process_exited(process)
        for state in ("R", "S", "D", "T"):
            with self.subTest(state=state), mock.patch.object(
                    Path, "read_text", return_value=self.process_stat_fixture(state, 456)):
                with self.assertRaisesRegex(AssertionError, "remained alive"):
                    self.assert_process_exited(process, timeout=0)

    def test_exit_polling_waits_for_the_original_process_to_terminate(self):
        process = {"pid": 123, "starttime": 456}
        for final in ("Z", "X"):
            samples = [self.process_stat_fixture(state, 456) for state in ("R", "R", final)]
            with self.subTest(final=final), mock.patch.object(Path, "read_text", side_effect=samples), \
                    mock.patch.object(time, "sleep") as sleep:
                result = self.assert_process_exited(process)
                self.assertEqual(result["exit_observed"], "terminated")
                self.assertEqual(result["states"], ["R", final])
                self.assertEqual(sleep.call_count, 2)

    def test_exit_polling_distinguishes_pid_reuse_from_a_live_original(self):
        with mock.patch.object(Path, "read_text", return_value=self.process_stat_fixture("R", 789)):
            result = self.assert_process_exited({"pid": 123, "starttime": 456}, timeout=0)
        self.assertEqual(result["exit_observed"], "pid-reused")
        starttime = int(Path(f"/proc/{os.getpid()}/stat").read_text().rpartition(") ")[2].split()[19])
        with self.assertRaisesRegex(AssertionError, "remained alive"):
            self.assert_process_exited({"pid": os.getpid(), "starttime": starttime}, timeout=0.05)

    def test_soft_hard_and_transport_budgets_fit_existing_outer_limit(self):
        for duration in (8.5, 12, 45, 60):
            argv, limits = CONTROLLER.session_probe_command(["python3", "guest.py", "session", "liveuser"], duration)
            self.assertLessEqual(limits["soft_seconds"], 30)
            self.assertLessEqual(limits["hard_seconds"] + limits["kill_after_seconds"] + 3, duration)
            self.assertNotIn("--foreground", argv)
        with self.assertRaises(CONTROLLER.GraphicalLoginDeadline):
            CONTROLLER.session_probe_command(["python3"], 8)

    def test_real_timeout_kills_descendants_and_serial_end_still_arrives(self):
        # Exercise the actual Serial/Guest protocol with a real hanging process
        # group, including a descendant that also ignores TERM.
        parent, child = socket.socketpair()
        shell = subprocess.Popen(["/bin/bash", "--noprofile", "--norc"], stdin=child,
                                 stdout=child, stderr=child, start_new_session=True)
        child.close()
        parent.setblocking(False)
        serial = object.__new__(CONTROLLER.Serial)
        serial.socket, serial.process, serial.buffer = parent, shell, ""
        guest = CONTROLLER.Guest(serial, self.report, self.output)
        pid_file = self.output / "hanging-probe-pids.json"
        source = ("import json,os,pathlib,signal,subprocess,sys,time; "
                  "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  "child=subprocess.Popen([sys.executable,'-c',"
                  "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)',sys.argv[1]]); "
                  "identity=lambda pid:{'pid':pid,'starttime':int(pathlib.Path('/proc/'+str(pid)+'/stat')"
                  ".read_text().rpartition(') ')[2].split()[19])}; "
                  "pathlib.Path(sys.argv[1]).write_text(json.dumps({'helper':identity(os.getpid()),'child':identity(child.pid)})); "
                  "print('VMTEST_PROBE_STAGE=hanging-child',flush=True); time.sleep(60)")
        argv, limits = CONTROLLER.session_probe_command([sys.executable, "-c", source, str(pid_file)], 8.5)
        try:
            status, body = guest.run(shlex.join(argv), "real-timeout", timeout=8.5, check=False)
            self.assertEqual(status, 137)
            self.assertIn("VMTEST_PROBE_STAGE=hanging-child", body)
            self.assertEqual(guest.run("printf after-timeout", "after-timeout", timeout=3), (0, "after-timeout\n"))
            exited = {name: self.assert_process_exited(process)
                      for name, process in json.loads(pid_file.read_text()).items()}
            print("VM_TIMEOUT_EXIT_OBSERVATIONS=" + json.dumps(exited, sort_keys=True), flush=True)
        finally:
            # Clean only children carrying this temporary test's unique path.
            if pid_file.exists():
                for process in json.loads(pid_file.read_text()).values():
                    pid = process["pid"]
                    with contextlib.suppress(OSError):
                        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2].split()
                        if (int(fields[19]) == process["starttime"]
                                and str(pid_file).encode() in Path(f"/proc/{pid}/cmdline").read_bytes()):
                            os.kill(pid, signal.SIGKILL)
            parent.close()
            if shell.poll() is None:
                shell.terminate()
            try:
                shell.wait(timeout=3)
            except subprocess.TimeoutExpired:
                shell.kill()
                shell.wait(timeout=3)

    def test_hard_timeout_does_not_invent_guest_identity_or_clean_crash_state(self):
        guest = self.guest()
        guest.run = mock.Mock(return_value=(124, 'VMTEST_PROBE_STAGE={"stage":"sessions"}\n'))
        result = guest.check("session", "liveuser", timeout=45)
        self.assertFalse(result["probe_complete"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["crash_check_complete"])
        self.assertIsNone(result["dde_shell_crashes"])
        self.assertEqual(result["probe_origin"], "controller")
        for key in ("boot_id", "uid", "sessions", "ddm_sessions", "treeland", "dde_shell"):
            self.assertNotIn(key, result)
        self.assertIn("--probe-budget-seconds", guest.run.call_args.args[0])
        self.assertFalse(guest.run.call_args.kwargs["check"])

    def test_authorization_failure_is_not_retried_as_a_sampling_timeout(self):
        guest = self.guest()
        guest.run = mock.Mock(return_value=(1, "VMTEST_ERROR=authorization marker mismatch\n"))
        with self.assertRaisesRegex(CONTROLLER.Failure, "authorization marker mismatch"):
            guest.check("session", "liveuser", timeout=45)

    def test_non_session_actions_do_not_gain_a_short_timeout_wrapper(self):
        guest = self.guest()
        guest.run = mock.Mock(return_value=(0, 'VMTEST_RESULT={"status":"done"}\n'))
        self.assertEqual(guest.check("stage", "payload", timeout=3600), {"status": "done"})
        self.assertNotIn("/usr/bin/timeout", guest.run.call_args.args[0])
        self.assertTrue(guest.run.call_args.kwargs["check"])

    def test_known_crash_survives_hard_timeout_and_fails_even_if_probe_incomplete(self):
        guest = self.guest()
        known = dict(self.incomplete(), crash_check_complete=True, dde_shell_crashes=[{"pid": 123, "signal": 11}])
        guest.run = mock.Mock(return_value=(137, "VMTEST_RESULT=" + json.dumps(known) + "\n"))
        observed = guest.check("session", "liveuser", timeout=45)
        self.assertEqual(observed["dde_shell_crashes"], known["dde_shell_crashes"])
        with self.assertRaisesRegex(CONTROLLER.Failure, "dde-shell crashed"):
            self.vm(observed).login_session("liveuser", None, time.monotonic() + 60, "crash")

    def test_incomplete_or_unknown_crash_evidence_cannot_be_ready(self):
        for observed in (dict(self.incomplete(), ready=True),
                         dict(self.incomplete(), dde_shell_crashes=[]),
                         dict(self.incomplete(), probe_complete=True)):
            with self.subTest(observed=observed), self.assertRaises(CONTROLLER.Failure):
                self.vm(observed).login_session("liveuser", None, time.monotonic() + 60, "invalid")

    def test_missing_completion_fields_are_rejected(self):
        with self.assertRaisesRegex(CONTROLLER.Failure, "completion status"):
            self.vm({"ready": False, "dde_shell_crashes": []}).login_session(
                "liveuser", None, time.monotonic() + 60, "legacy")

    def test_no_initial_complete_observation_means_no_checkpoint_or_password(self):
        vm = self.vm(self.incomplete())
        clock = [100.0]
        def observe(*args, **kwargs):
            clock[0] += 6
            return self.incomplete()
        vm.guest.check.side_effect = observe
        vm.wait_greeter = mock.Mock()
        vm.submit_graphical_password = mock.Mock()
        with mock.patch.object(CONTROLLER.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(CONTROLLER.time, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
            with self.assertRaises(CONTROLLER.GraphicalLoginDeadline):
                vm.desktop_login("liveuser", "unused", 20)
        self.assertFalse((self.output / "graphical-login-checkpoint.json").exists())
        vm.wait_greeter.assert_not_called()
        vm.submit_graphical_password.assert_not_called()

    def test_framing_failure_keeps_partial_output_and_the_original_error(self):
        guest = self.guest()
        failure = CONTROLLER.SerialTimeout("missing end marker")
        guest.serial.buffer = "VMTEST_PROBE_STAGE=loginctl\n" + CONTROLLER.CRYPT_PASSWORD
        guest.serial.expect.side_effect = [("", "begin"), failure]
        with self.assertRaises(CONTROLLER.SerialTimeout) as caught:
            guest.run("do-not-save-command-text", "session-progress", timeout=45)
        self.assertIs(caught.exception, failure)
        detail = json.loads((self.output / "session-progress-command-1.failure.json").read_text())
        partial = (self.output / detail["partial_output"]).read_text()
        self.assertTrue(detail["begin_observed"])
        self.assertIn("VMTEST_PROBE_STAGE=loginctl", partial)
        self.assertNotIn(CONTROLLER.CRYPT_PASSWORD, partial)
        self.assertNotIn("do-not-save-command-text", json.dumps(detail) + partial)

    def test_recovery_failure_has_its_own_reason_and_partial_output(self):
        guest = self.guest()
        guest.ready = True
        guest.serial.buffer = "unfinished probe stage"
        guest.serial.expect.side_effect = CONTROLLER.SerialTimeout("no root prompt after interrupt")
        self.assertFalse(guest.recover())
        detail = json.loads((self.output / "serial-recovery.json").read_text())
        self.assertFalse(detail["recovered"])
        self.assertEqual(detail["error_type"], "SerialTimeout")
        self.assertIn("no root prompt", detail["error"])
        self.assertEqual((self.output / detail["partial_output"]).read_text(), "unfinished probe stage")

    def test_kvm_diagnostics_record_access_and_errno_without_changing_permissions(self):
        device = self.output / "ordinary-fixture-file"
        device.write_bytes(b"unchanged")
        device.chmod(0o600)
        original = device.stat()
        acl = subprocess.CompletedProcess([], 0, "user::rw-\ngroup::---\nother::---\n", "")
        with mock.patch.object(CONTROLLER, "command", return_value=acl) as invoked:
            success = CONTROLLER.kvm_access_snapshot("fixture-before", str(device))
            with mock.patch.object(CONTROLLER.os, "open", side_effect=PermissionError(errno.EACCES, "denied", str(device))):
                denied = CONTROLLER.kvm_access_snapshot("fixture-denied", str(device))
        self.assertTrue(success["open"]["success"])
        self.assertFalse(denied["open"]["success"])
        self.assertEqual(denied["open"]["errno"], errno.EACCES)
        self.assertEqual(denied["uid"], os.getuid())
        self.assertIn("groups", denied)
        self.assertEqual(device.stat().st_mode, original.st_mode)
        self.assertEqual(device.read_bytes(), b"unchanged")
        self.assertTrue(all(call.args[0][0] == "getfacl" for call in invoked.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
