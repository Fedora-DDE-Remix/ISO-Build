# Packaged DPF nested-plugin probe

This is a diagnostic test of the actual installed DFM framework and Qt SDK.
It does not launch a desktop, touch a disk, change policy, or install packages.
The host links only QtCore; the outer Qt plugin initializes the packaged DPF
framework, then loads an inner Qt plugin in the default QPluginLoader scope.
The inner plugin uses the real DPF constructor-registration macros and tests
both direct registry lookup and EventConverter lookup, followed by QVariant
integer/list transfer through the real EventChannelManager.

The diagnostic workflow runs only on `diagnose-dpf-*` pushes or an explicit
manual dispatch. It installs the published COPR `dde-file-manager-devel` and
`dde-file-manager-desktop` packages in an isolated Fedora 45 container, and
records their exact NEVRAs alongside the Qt/compiler versions. It does not
build a replacement package or trigger the ISO compose workflow.

In the same prepared environment, from the repository root:

```sh
bash scripts/diagnose-dpf/run.sh artifacts/dpf
```

Run against the existing RPM first, then against a candidate build. A successful
probe proves this limited DPF path works; it does not replace a real visible
desktop login and crash-free VM gate. On failure retain the printed registry ID,
converted ID, callback validity/address, and QVariant validity before choosing
a source patch. The script also saves the complete installed-library symbol
tables and disassembly, compiler/RPM flags, build commands, and test output.
