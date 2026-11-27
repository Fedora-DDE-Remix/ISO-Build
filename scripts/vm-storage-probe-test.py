#!/usr/bin/env python3
"""Read-only storage evidence regressions; no mapper, mount or root privilege.

One test starts a disposable Python sleeper to verify bounded child cleanup.
Run with python3 scripts/vm-storage-probe-test.py.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("vm_guest", Path(__file__).with_name("vm-guest.py"))
VM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VM)
LUKS_UUID = "11111111-2222-3333-4444-555555555555"
MAPPER = "/dev/mapper/luks-" + LUKS_UUID
INNER_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class StorageEvidenceRegression(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.sys_block = self.root / "sys-block"
        self.sys_block.mkdir()
        self.state_path = self.root / "state.json"
        self.enterContext(mock.patch.object(VM, "RUNTIME", self.runtime))
        self.enterContext(mock.patch.object(VM, "STATE", self.state_path))
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        device = self.root.stat().st_dev
        self.number = f"{os.major(device)}:{os.minor(device)}"
        self.state = {"phase": "finalizing", "target": "/target", "owned_mounts": [],
                      "encrypted_root": {"name": "luks-" + LUKS_UUID, "mapper": MAPPER,
                          "device": "/dev/vda3", "uuid": LUKS_UUID, "filesystem_uuid": INNER_UUID,
                          "fstype": "btrfs", "unexpected_password": "DO-NOT-EXPORT"},
                      "mounts": [{"mountpoint": "/", "device": MAPPER, "uuid": INNER_UUID}],
                      "mount_identity": {"source": MAPPER, "major_minor": self.number,
                          "fstype": "btrfs", "uuid": INNER_UUID, "fsroot": "/root",
                          "unexpected_password": "DO-NOT-EXPORT"},
                      "unexpected_password": "DO-NOT-EXPORT"}
        self.state_path.write_text(json.dumps(self.state))

    def probe(self, **kwargs):
        return VM.StorageCleanupProbe(proc=self.proc, sys_block=self.sys_block, **kwargs)

    def process(self, pid=123, namespace="mnt:[42]"):
        path = self.proc / str(pid)
        (path / "ns").mkdir(parents=True)
        (path / "ns/mnt").symlink_to(namespace)
        (path / "fd").mkdir()
        (path / "mountinfo").write_text(
            f"33 20 {self.number} /root /target rw shared:7 - btrfs {MAPPER} rw,subvolid=256\n")
        (path / "comm").write_text("metadata-holder\n")
        (path / "cgroup").write_text("0::/system.slice/example.service\n")
        held = self.root / "held-file"
        held.write_text("DO-NOT-READ-FD-CONTENTS")
        for name in ("root", "cwd", "exe", "fd/7"):
            (path / name).symlink_to(held)
        return path

    def test_mountinfo_unescapes_paths_and_keeps_btrfs_virtual_device_and_propagation(self):
        parsed = VM.storage_mountinfo(
            r"33 20 0:41 /root\040tree /other\040namespace rw master:7 - btrfs /dev/disk\040alias rw,subvolid=256" + "\n")
        self.assertEqual(parsed[0]["root"], "/root tree")
        self.assertEqual(parsed[0]["mountpoint"], "/other namespace")
        self.assertEqual(parsed[0]["source"], "/dev/disk alias")
        self.assertEqual(parsed[0]["major_minor"], "0:41")
        self.assertEqual(parsed[0]["propagation"], ["master:7"])

    def test_malformed_mountinfo_is_not_silently_an_empty_namespace(self):
        with self.assertRaises(ValueError):
            VM.storage_mountinfo("incomplete kernel output\n")

    def test_btrfs_namespace_can_match_virtual_device_with_different_source_and_mountpoint(self):
        probe = self.probe()
        probe.filesystem_devices = {os.makedev(0, 41)}
        mount = VM.storage_mountinfo("33 20 0:41 /root /private rw - btrfs /dev/dm-0 rw\n")[0]
        self.assertTrue(probe.matches_mount(mount))
        mount["major_minor"] = "0:42"
        self.assertFalse(probe.matches_mount(mount))

    def test_canonical_mapper_alias_matches_when_virtual_device_changes(self):
        probe = self.probe()
        probe.sources = {MAPPER, "/dev/dm-0"}
        mount = VM.storage_mountinfo("33 20 0:99 /home /private rw - btrfs /dev/alias rw\n")[0]
        with mock.patch.object(VM.os.path, "realpath", return_value="/dev/dm-0"):
            self.assertTrue(probe.matches_mount(mount))

    def test_state_exports_only_whitelisted_identity_and_uuid_alias(self):
        probe = self.probe()
        probe.prepare(self.state)
        self.assertIn("/dev/disk/by-uuid/" + INNER_UUID, probe.sources)
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(probe.result))
        self.assertEqual(probe.result["expected_filesystem_devices"], [self.number])

    def test_namespace_and_fd_metadata_are_retained_without_reading_held_contents(self):
        process = self.process()
        probe = self.probe()
        probe.prepare(self.state)
        probe.scan_process(process)
        result = probe.result
        self.assertEqual(result["namespaces"][0]["pids"], [123])
        self.assertEqual(result["namespaces"][0]["mounts"][0]["source"], MAPPER)
        references = result["process_references"][0]["references"]
        self.assertEqual({item["kind"] for item in references}, {"root", "cwd", "exe", "fd"})
        self.assertEqual(next(item for item in references if item["kind"] == "fd")["fd"], 7)
        self.assertNotIn("DO-NOT-READ-FD-CONTENTS", json.dumps(result))
        self.assertNotIn("cmdline", result["process_references"][0])

    def test_raw_mapper_descriptor_matches_its_block_device_number(self):
        probe = self.probe()
        probe.block_devices = {os.makedev(252, 0)}
        descriptor = mock.Mock()
        descriptor.stat.return_value = mock.Mock(st_mode=stat.S_IFBLK | 0o600,
                                                 st_rdev=os.makedev(252, 0), st_dev=os.makedev(0, 5))
        with mock.patch.object(VM.os, "readlink", return_value="/dev/dm-0"):
            result = probe.reference(descriptor, "fd", fd="8")
        self.assertEqual(result["matched_by"], ["mapper-block-device"])
        self.assertEqual(result["fd"], 8)

    def test_process_disappearance_does_not_hide_the_next_holder(self):
        self.process(123)
        self.process(124)
        probe = self.probe()
        original = probe.scan_process

        def disappearing(path):
            if path.name == "123":
                raise FileNotFoundError("process exited")
            return original(path)

        with mock.patch.object(probe, "scan_process", side_effect=disappearing), \
                mock.patch.object(probe, "command"):
            result = probe.collect()
        self.assertTrue(result["collection_complete"])
        self.assertEqual(result["pids_unavailable"], 1)
        self.assertEqual(result["process_references"][0]["pid"], 124)

    def test_permission_failure_is_incomplete_not_no_holder(self):
        self.process()
        probe = self.probe()
        with mock.patch.object(probe, "scan_process", side_effect=PermissionError("namespace denied")), \
                mock.patch.object(probe, "command"):
            result = probe.collect()
        self.assertFalse(result["collection_complete"])
        self.assertEqual(result["errors"][0]["stage"], "pid-123")

    def test_soft_budget_preserves_partial_evidence_and_marks_it_incomplete(self):
        self.process()
        clock = [100.0]
        with mock.patch.object(VM.time, "monotonic", side_effect=lambda: clock[0]):
            probe = self.probe(seconds=1)
            original = probe.scan_process

            def consumes_budget(path):
                original(path)
                clock[0] += 2

            with mock.patch.object(probe, "scan_process", side_effect=consumes_budget), \
                    mock.patch.object(probe, "command"):
                result = probe.collect()
        self.assertFalse(result["collection_complete"])
        self.assertEqual(result["process_references"][0]["pid"], 123)
        self.assertIn("wall-clock budget", result["errors"][-1]["error"])
        self.assertFalse(VM.storage_read_evidence()["collection_complete"])

    def test_output_and_metadata_reads_are_bounded(self):
        probe = self.probe()
        with self.assertRaises(VM.StorageProbeStopped):
            probe.append_detail([], {"unbounded": "x" * (81 * 1024)})
        with self.assertRaises(VM.StorageProbeStopped):
            probe.text(self.state_path, 10)
        with self.assertRaises(RuntimeError):
            VM.storage_save_evidence({"unbounded": "x" * VM.STORAGE_EVIDENCE_LIMIT})

    def test_timeout_kills_and_reaps_a_real_disposable_child(self):
        pid_path = self.root / "child.pid"
        script = "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
        probe = self.probe(seconds=1)
        probe.command("sleeper", [sys.executable, "-c", script, str(pid_path)], cap=0.3)
        self.assertIsNone(probe.result["commands"]["sleeper"]["status"])
        self.assertTrue(probe.result["errors"])
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_path.read_text()), 0)

    def test_hard_timeout_keeps_partial_file_and_original_exit(self):
        def killed(argv, **kwargs):
            self.assertIn("18s", argv)
            self.assertIn("--kill-after=2s", argv)
            self.assertNotIn("--foreground", argv)
            self.assertEqual(kwargs["timeout"], 22)
            VM.storage_save_evidence({"schema": 1, "collection_complete": False,
                                      "last_stage": "device-open-count", "errors": [],
                                      "commands": {"dm_info": {"stdout": "luks-name:252:0:1"}}})
            return subprocess.CompletedProcess(argv, 124)

        with mock.patch.object(VM, "run", side_effect=killed):
            VM.capture_storage_cleanup_failure(1)
        result = VM.storage_read_evidence()
        self.assertEqual(result["backend_exit_status"], 1)
        self.assertEqual(result["collector_exit_status"], 124)
        self.assertFalse(result["collection_complete"])
        self.assertIn("dm_info", result["commands"])
        self.assertEqual(stat.S_IMODE((self.runtime / VM.STORAGE_EVIDENCE_NAME).stat().st_mode), 0o600)

    def test_collector_exception_never_changes_original_backend_failure(self):
        with mock.patch.object(VM.sys, "argv", ["guest.py", "stage", "finalize"]), \
                mock.patch.object(VM, "authorize"), \
                mock.patch.object(VM, "run_backend", return_value=subprocess.CompletedProcess([], 5)), \
                mock.patch.object(VM, "capture_storage_cleanup_failure", side_effect=OSError("diagnostic failed")):
            with self.assertRaisesRegex(RuntimeError, r"Actual installer backend finalize failed \(5\)"):
                VM.main()

    def test_successful_finalize_does_not_run_probe(self):
        with mock.patch.object(VM.sys, "argv", ["guest.py", "stage", "finalize"]), \
                mock.patch.object(VM, "authorize"), \
                mock.patch.object(VM, "run_backend", return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(VM, "capture_storage_cleanup_failure") as capture:
            VM.main()
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
