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

The script first reproduces the observed failure using the unchanged packaged
headers. It then copies those headers into the artifact directory and changes
only the inline callback definition to an external declaration. Recompiled probe
plugins still link to the unchanged installed framework, which already exports
that symbol. A comparison passes only when the baseline shows different callback
addresses and a failed conversion despite successful registration, while the
candidate shares the callback and passes integer/list transfers. Both test logs,
return codes and original-library checksums remain in the evidence.

The accompanying two-file source patch defines the callback exactly once in the
framework. Production use requires rebuilding all DFM plugins with the patched
header; replacing only the framework RPM leaves old plugin definitions in place.
The diagnostic does not build this complete replacement package. Its result
explicitly records `full_source_patch_built: false` and `desktop_verified: false`.
A successful probe does not replace a visible desktop login and crash-free VM
gate. The script also saves the installed-library symbol tables and disassembly,
compiler/RPM flags, build commands, and test output.
