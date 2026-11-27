#!/usr/bin/bash
set -euo pipefail

probe_source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
probe_output_dir=${1:-artifacts/dpf}
mkdir -p "$probe_output_dir"
probe_output_dir=$(cd -- "$probe_output_dir" && pwd)
exec > >(tee "$probe_output_dir/run.log") 2>&1

cp /etc/os-release "$probe_output_dir/os-release"
uname -a > "$probe_output_dir/uname.txt"
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' \
  | LC_ALL=C sort > "$probe_output_dir/rpm-manifest.txt"
rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n' \
  dde-file-manager dde-file-manager-libs dde-file-manager-desktop \
  dde-file-manager-devel dde-shell qt6-qtbase qt6-qtbase-devel gcc-c++ \
  redhat-rpm-config > "$probe_output_dir/critical-packages.txt"
g++ --version > "$probe_output_dir/compiler.txt"
g++ -v >> "$probe_output_dir/compiler.txt" 2>&1
cmake --version > "$probe_output_dir/cmake-version.txt"
rpm --eval '%{optflags}' > "$probe_output_dir/rpm-optflags.txt"
rpm --eval '%{build_ldflags}' > "$probe_output_dir/rpm-ldflags.txt"

probe_framework=/usr/lib64/libdfm6-framework.so.1
probe_core=/usr/lib64/dde-file-manager/plugins/desktop-core/libdd-core-plugin.so
probe_desktop=/usr/lib64/dde-shell/org.deepin.ds.desktop.so
for probe_library in "$probe_framework" "$probe_core" "$probe_desktop"; do
  test -f "$probe_library"
  probe_library_name=$(basename -- "$probe_library")
  rpm -qf "$probe_library" > "$probe_output_dir/$probe_library_name.rpm-owner.txt"
  sha256sum "$probe_library" > "$probe_output_dir/$probe_library_name.sha256"
  readelf --wide --syms "$probe_library" > "$probe_output_dir/$probe_library_name.symbols.txt"
  readelf --wide --notes "$probe_library" > "$probe_output_dir/$probe_library_name.notes.txt"
  objdump -Cd "$probe_library" > "$probe_output_dir/$probe_library_name.disassembly.txt"
done

probe_cxx_flags="$(rpm --eval '%{optflags}') -g -Wall -Wl,--as-needed -fstack-protector-all -Werror=return-type -Wl,-z,relro -Wl,-z,now -Ofast"
probe_linker_flags=$(rpm --eval '%{build_ldflags}')
printf '%s\n' "$probe_cxx_flags" > "$probe_output_dir/probe-cxx-flags.txt"
printf '%s\n' "$probe_linker_flags" > "$probe_output_dir/probe-linker-flags.txt"
cmake -S "$probe_source_dir" -B "$probe_output_dir/build" -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DCMAKE_CXX_FLAGS_RELEASE:STRING=-DNDEBUG \
  -DCMAKE_CXX_FLAGS:STRING="$probe_cxx_flags" \
  -DCMAKE_MODULE_LINKER_FLAGS:STRING="$probe_linker_flags" \
  -DCMAKE_EXE_LINKER_FLAGS:STRING="$probe_linker_flags" \
  2>&1 | tee "$probe_output_dir/cmake-configure.log"
cmake --build "$probe_output_dir/build" --parallel 2 --verbose \
  2>&1 | tee "$probe_output_dir/cmake-build.log"

for probe_plugin in outer inner; do
  readelf --wide --syms "$probe_output_dir/build/dpf-probe-$probe_plugin.so" \
    > "$probe_output_dir/probe-$probe_plugin.symbols.txt"
done

set +e
ctest --test-dir "$probe_output_dir/build" --output-on-failure -V \
  2>&1 | tee "$probe_output_dir/probe-test.log"
probe_status=${PIPESTATUS[0]}
set -e
python3 - "$probe_output_dir/result.json" "$probe_status" <<'PY'
import json
import os
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema": 1,
    "scope": "Existing packaged DPF: nested QPluginLoader, event lookup and QVariant transfer",
    "source_commit": os.environ.get("GITHUB_SHA"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "ctest_exit_status": int(sys.argv[2]),
    "desktop_verified": False,
    "packaged_libraries_patched": False,
}, indent=2) + "\n")
PY
exit "$probe_status"
