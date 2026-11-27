#!/usr/bin/env python3
"""Non-VM regressions for greeter focus, one-shot input and serial deadlines.

Run with python3 scripts/test-vm-login.py (requires Pillow). The two PNG
fixtures are unmodified real failed-run frames. Generated glyph canvases test
the local pixel classifier only; they are not evidence of a working desktop.
"""

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("vm_controller", ROOT / "test-install-vm.py")
VM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VM)
FIXTURES = ROOT / "testdata" / "treeland-0.12.0"
WORDS = [
    {"text": "Live", "left": 753, "top": 433, "width": 57, "height": 23},
    {"text": "User", "left": 820, "top": 434, "width": 65, "height": 22},
    {"text": "Please", "left": 761, "top": 530, "width": 32, "height": 8},
    {"text": "enter", "left": 797, "top": 531, "width": 27, "height": 7},
    {"text": "password", "left": 828, "top": 532, "width": 48, "height": 8},
]
SCREEN = {"words": WORDS, "text": "Live User Please enter password", "width": 1280, "height": 800}
CHECKPOINT = {"observed_at_monotonic_us": 1, "boot_id": "test-boot"}


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LoginRegression(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.clock = Clock()
        self.enterContext(mock.patch.object(VM.time, "monotonic", self.clock.monotonic))
        self.enterContext(mock.patch.object(VM.time, "sleep", self.clock.sleep))
        self.baseline = self.output / "real-empty.png"
        shutil.copyfile(FIXTURES / "008-ddm-login-03.png", self.baseline)
        self.control = VM.password_control(SCREEN)

    def instance(self):
        vm = object.__new__(VM.VM)
        vm.output = self.output
        vm.qmp = mock.Mock()
        vm.guest = mock.Mock()
        return vm

    def canvas(self, name, *, characters=0, round_glyphs=True, wallpaper=False, caret=True):
        image = Image.new("RGB", (1280, 800), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        if wallpaper:
            # Static bright details inside the field would resemble bullets
            # without the actual focused-empty-frame subtraction.
            for x in range(744, 781, 6):
                draw.ellipse((x, 490, x + 3, 493), fill=(240, 240, 240))
        for index in range(characters):
            x = 790 + index * 7
            if round_glyphs:
                draw.ellipse((x, 492, x + 3, 495), fill=(255, 255, 255))
            else:
                draw.rectangle((x, 492, x + 5, 493), fill=(255, 255, 255))
        if caret:
            x = 850 if characters else 818
            draw.line((x, 487, x, 501), fill=(255, 255, 255))
        # The real eye icon and field edges are outside the text ROI.
        draw.ellipse((905, 490, 912, 497), outline=(255, 255, 255))
        draw.rectangle((708, 480, 927, 510), outline=(255, 255, 255))
        path = self.output / name
        image.save(path)
        return path

    def test_real_frames_have_empty_focused_field_not_hint_input(self):
        expected = {
            "008-ddm-login-03.png": "3a6a7bbe585bc69291a90ed80cd1ee865ca5b6006c93c32c87e6142bc880193a",
            "009-failure-or-final-state.png": "5d33f4468f3c342fc1168eefc8319ee00f9185043c4be95d470f1258d6dd9c7b",
        }
        self.assertTrue(708 < self.control["center_x"] < 927)
        self.assertTrue(480 < self.control["center_y"] < 510)
        self.assertLess(self.control["center_y"], WORDS[-1]["top"])
        for name, digest in expected.items():
            with self.subTest(name=name):
                path = FIXTURES / name
                self.assertEqual(VM.sha256(path), digest)
                pixels = VM.password_pixels(path, self.control)
                self.assertEqual(pixels["masked_characters"], 0)
                self.assertEqual([(c["x"], c["y"], c["width"], c["height"]) for c in pixels["carets"]],
                                 [(818, 487, 1, 15)])
                self.assertEqual(VM.password_pixels(path, self.control, path)["changed_non_cursor_pixels"], 0)

    def test_hint_fragment_is_not_an_in_field_placeholder(self):
        screen = dict(SCREEN, words=[WORDS[-1]])
        self.assertIsNone(VM.password_control(screen))
        actual = dict(WORDS[-1], text="Password", left=795, top=490)
        self.assertEqual(VM.password_control(dict(SCREEN, words=[actual]))["anchor"],
                         "in-field-Password-placeholder")

    def test_getty_and_boot_messages_remain_rejected(self):
        session = {"treeland": [{"pid": 1}]}
        for text in ("localhost login:", "Started service Starting service Reached target"):
            self.assertFalse(VM.greeter_evidence(dict(SCREEN, text=text), session, VM.LIVE_USER)["ready"])

    def test_background_eye_border_and_blink_do_not_count_as_typed_password(self):
        baseline = self.canvas("synthetic-background.png", wallpaper=True)
        blink = self.canvas("synthetic-blink.png", wallpaper=True, caret=False)
        pixels = VM.password_pixels(blink, self.control, baseline)
        self.assertEqual(pixels["changed_non_cursor_pixels"], 0)
        self.assertEqual(pixels["masked_characters"], 0)
        typed = self.canvas("synthetic-bullets.png", wallpaper=True, characters=8)
        pixels = VM.password_pixels(typed, self.control, baseline)
        self.assertEqual(pixels["masked_characters"], 8)
        self.assertGreater(pixels["changed_non_cursor_pixels"], 0)

    def test_control_requires_two_stable_observations(self):
        vm = self.instance()
        vm.login_session = mock.Mock(return_value={"treeland": [{"pid": 1}], "ready": False, "ddm_sessions": []})
        vm.screen = mock.Mock(return_value=dict(SCREEN, path=str(self.baseline)))
        vm.wait_greeter(VM.LIVE_USER, 200, "test-greeter", checkpoint=CHECKPOINT, before_password=True)
        records = json.loads((self.output / "test-greeter-gate.json").read_text())
        self.assertEqual([r["control_stable"] for r in records], [False, True])

    def test_one_slow_entry_and_one_submit_after_stable_input(self):
        vm = self.instance()
        partial = self.canvas("synthetic-incomplete-mask.png", characters=7)
        masked = self.canvas("synthetic-complete-mask.png", characters=8)
        vm.screenshot = mock.Mock(side_effect=[self.baseline, partial, masked, masked, masked])
        result = vm.submit_graphical_password(SCREEN, self.control, VM.LIVE_PASSWORD, 200)
        vm.qmp.type.assert_called_once_with(VM.LIVE_PASSWORD, hold_time=100)
        self.assertEqual(sum(c.args == ("ret",) for c in vm.qmp.key.call_args_list), 1)
        self.assertEqual(len(result["masked_frames"]), 3)
        self.assertEqual(result["submissions"], 1)
        self.assertTrue(result["mask_count_matches"])

    def test_mask_shape_is_diagnostic_not_an_authentication_gate(self):
        vm = self.instance()
        different_font = self.canvas("synthetic-wide-glyphs.png", characters=8, round_glyphs=False)
        vm.screenshot = mock.Mock(side_effect=[self.baseline, different_font, different_font, different_font])
        result = vm.submit_graphical_password(SCREEN, self.control, VM.LIVE_PASSWORD, 200)
        self.assertFalse(result["mask_count_matches"])
        self.assertEqual(result["submissions"], 1)

    def test_unchanged_empty_input_is_never_submitted_or_retyped(self):
        vm = self.instance()
        vm.screenshot = mock.Mock(return_value=self.baseline)
        with self.assertRaisesRegex(VM.Failure, "remained empty or unstable"):
            vm.submit_graphical_password(SCREEN, self.control, VM.LIVE_PASSWORD, 200)
        self.assertEqual(vm.qmp.type.call_count, 1)
        self.assertFalse(any(c.args == ("ret",) for c in vm.qmp.key.call_args_list))
        evidence = json.loads((self.output / "graphical-password-input.json").read_text())
        self.assertEqual(evidence["password_entries"], 1)
        self.assertEqual(evidence["submissions"], 0)

    def test_no_focus_prevents_any_password_entry(self):
        vm = self.instance()
        vm.screenshot = mock.Mock(return_value=self.canvas("synthetic-no-focus.png", caret=False))
        with self.assertRaisesRegex(VM.Failure, "no password was entered"):
            vm.submit_graphical_password(SCREEN, self.control, VM.LIVE_PASSWORD, 200)
        vm.qmp.type.assert_not_called()

    def test_password_submission_alone_cannot_pass_login(self):
        vm = self.instance()
        vm.report = SimpleNamespace(remaining=lambda timeout: timeout)
        session = dict(CHECKPOINT, ready=False, ddm_sessions=[], sessions=[], dde_shell_crashes=[])
        vm.guest.check.return_value = session
        vm.wait_greeter = mock.Mock(return_value=(SCREEN, {"password_control": self.control}))
        vm.submit_graphical_password = mock.Mock(return_value={"submissions": 1})
        vm.login_session = mock.Mock(return_value=session)
        with self.assertRaisesRegex(VM.Failure, "did not create an authenticated Wayland"):
            vm.desktop_login(VM.LIVE_USER, VM.LIVE_PASSWORD, 12)
        self.assertEqual(vm.submit_graphical_password.call_count, 1)

    def test_short_final_probe_preserves_its_serial_timeout_cause(self):
        vm = self.instance()
        framing = VM.SerialTimeout("missing __VM_END_test__")

        def timeout(*args, **kwargs):
            self.clock.sleep(kwargs["timeout"])
            raise framing

        vm.guest.check.side_effect = timeout
        with self.assertRaises(VM.GraphicalLoginDeadline) as caught:
            vm.login_session(VM.LIVE_USER, CHECKPOINT, 112, "final-probe")
        self.assertIs(caught.exception.__cause__, framing)

    def test_full_budget_framing_failure_is_not_reclassified(self):
        vm = self.instance()
        framing = VM.SerialTimeout("full 45 second framing failure")

        def timeout(*args, **kwargs):
            self.clock.sleep(kwargs["timeout"])
            raise framing

        vm.guest.check.side_effect = timeout
        with self.assertRaises(VM.SerialTimeout) as caught:
            vm.login_session(VM.LIVE_USER, CHECKPOINT, 145, "full-probe")
        self.assertIs(caught.exception, framing)

    def test_early_failure_on_short_probe_is_not_reclassified(self):
        vm = self.instance()
        failure = VM.SerialTimeout("early framing failure")
        vm.guest.check.side_effect = failure
        with self.assertRaises(VM.SerialTimeout) as caught:
            vm.login_session(VM.LIVE_USER, CHECKPOINT, 112, "early-probe")
        self.assertIs(caught.exception, failure)

    def test_serial_begin_and_end_share_one_command_budget(self):
        serial = mock.Mock()
        durations = []

        def expect(pattern, duration):
            durations.append(duration)
            if len(durations) == 1:
                self.clock.sleep(3)
                return "", "begin"
            return "command output", "__VM_END_1_abcdef12__0\n"

        serial.expect.side_effect = expect
        guest = VM.Guest(serial, SimpleNamespace(remaining=lambda timeout: timeout), self.output)
        with mock.patch.object(VM.uuid, "uuid4", return_value=SimpleNamespace(hex="abcdef123456")):
            self.assertEqual(guest.run("true", "budget", timeout=10), (0, "command output"))
        self.assertEqual(durations, [10, 7])

    def test_default_key_timing_is_unchanged(self):
        qmp = object.__new__(VM.QMP)
        qmp.execute = mock.Mock()
        qmp.type("x")
        self.assertEqual(qmp.execute.call_args.args[1]["hold-time"], 30)
        qmp.type("A", hold_time=100)
        self.assertEqual(qmp.execute.call_args.args[1]["hold-time"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
