# Recorded empty Treeland password fields

The two PNGs are byte-for-byte copies from the failed `uefi-luks-btrfs-small`
canary in [ISO workflow run 45964408039](https://github.com/Fedora-DDE-Remix/ISO-Build/actions/runs/45964408039),
artifact `ISO-installation-evidence-uefi-luks-btrfs-small-45964408039-1`
(ID `15184540664`). Their original paths are `test/live/screenshots/` in that
artifact. Neither image was cropped, recolored or otherwise edited.

| File | SHA-256 |
| --- | --- |
| `008-ddm-login-03.png` | `3a6a7bbe585bc69291a90ed80cd1ee865ca5b6006c93c32c87e6142bc880193a` |
| `009-failure-or-final-state.png` | `5d33f4468f3c342fc1168eefc8319ee00f9185043c4be95d470f1258d6dd9c7b` |

Both show the Live User greeter with an empty password field and its caret.
The actual field occupies approximately x=708..927, y=480..510 at 1280×800;
the phrase “Please enter password” beneath it is explanatory text, not the
field itself. The old controller clicked the OCR word “password” in that
phrase. The regression checks the corrected field center and confirms that
neither recorded frame contains entered password bullets.

The layout reference is
[Treeland 0.12.0 UserInput.qml at commit 859a8c314f00947bc98168f46631ba10f9c7e6fa](https://github.com/linuxdeepin/treeland/blob/859a8c314f00947bc98168f46631ba10f9c7e6fa/src/plugins/lockscreen/qml/UserInput.qml):
`passwordSlot` is 220×30 logical pixels, `hintText` is centered below it with
a 16-pixel top margin, and the 1×18 cursor is drawn only while the field has
active focus.

Run `python3 scripts/test-vm-login.py` with Pillow installed. The suite also
creates small synthetic glyph patterns in a temporary directory to exercise
background subtraction, blinking cursors and different mask shapes. Those
canvases are unit-test inputs, not screenshots or evidence that a VM logged
in. Final acceptance still requires the real DDM authentication, matching
user Wayland and `dde-shell` session, crash checks and stable visible desktop.
