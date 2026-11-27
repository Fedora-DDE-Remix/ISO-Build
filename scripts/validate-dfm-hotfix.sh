#!/usr/bin/bash
# Revalidate the exact completed RPM build; never rewrite its failed run status.
set -euo pipefail
umask 022

dfmv_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dfmv_repo_dir=$(cd -- "$dfmv_script_dir/.." && pwd)
dfmv_helper="$dfmv_script_dir/validate-dfm-hotfix.py"
dfmv_output_dir=${1:-artifacts/dfm-validation}
mkdir -p "$dfmv_output_dir/validation/"{logs,provenance,symbols,probe}
dfmv_output_dir=$(cd -- "$dfmv_output_dir" && pwd)
dfmv_evidence="$dfmv_output_dir/validation"
dfmv_work_dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/dfm-validation.XXXXXX")
dfmv_stage=download-pinned-build
dfmv_finish() {
    local dfmv_status=$?
    trap - EXIT
    python3 "$dfmv_helper" finalize "$dfmv_output_dir" "$dfmv_status" "$dfmv_stage"
    exit "$dfmv_status"
}
trap dfmv_finish EXIT

test "$(id -u)" -eq 0
test "$(rpm --eval '%{fedora}')" = 45
test "$(uname -m)" = x86_64
gh api repos/Fedora-DDE-Remix/ISO-Build/actions/artifacts/15177359692/zip \
    > "$dfmv_work_dir/source-artifact.zip" 2> "$dfmv_evidence/logs/source-download.log"
unset GH_TOKEN
python3 "$dfmv_helper" prepare "$dfmv_work_dir/source-artifact.zip" "$dfmv_output_dir"
cp "$dfmv_script_dir/"validate-dfm-hotfix.{sh,py} "$dfmv_evidence/provenance/"
cp "$dfmv_repo_dir/.github/workflows/validate-dfm-hotfix.yml" "$dfmv_evidence/provenance/"
cp "$dfmv_repo_dir/packaging/hotfix/dde-file-manager/README.md" \
    "$dfmv_evidence/provenance/README-validation.md"
cp /etc/os-release "$dfmv_evidence/provenance/os-release"
uname -a > "$dfmv_evidence/provenance/uname.txt"

dfmv_stage=install-exact-rpms
python3 "$dfmv_helper" inventory "$dfmv_output_dir"
dnf -y copr enable mozixun/Fedora-DDE-Remix fedora-45-x86_64 \
    2>&1 | tee "$dfmv_evidence/logs/copr-enable.log"
cat /etc/yum.repos.d/*copr*.repo > "$dfmv_evidence/provenance/copr.repo"
mapfile -t dfmv_install_rpms < "$dfmv_evidence/provenance/install-rpms.txt"
dnf -y --refresh install qt6-qtbase-devel "${dfmv_install_rpms[@]}" \
    2>&1 | tee "$dfmv_evidence/logs/install-built-rpms.log"
rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n' \
    dde-file-manager dde-file-manager-libs dde-file-manager-desktop \
    dde-file-manager-services-plugins dde-file-manager-devel \
    > "$dfmv_evidence/provenance/installed-hotfix-packages.txt"
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n' \
    | LC_ALL=C sort > "$dfmv_evidence/provenance/validation-packages.txt"

dfmv_stage=verify-shared-symbol
for dfmv_library in /usr/lib64/libdfm6-framework.so.1 \
    /usr/lib64/dde-file-manager/plugins/desktop-core/libdd-core-plugin.so \
    /usr/lib64/dde-shell/org.deepin.ds.desktop.so; do
    dfmv_name=$(basename -- "$dfmv_library")
    rpm -qf "$dfmv_library" > "$dfmv_evidence/symbols/$dfmv_name.rpm-owner.txt"
    sha256sum "$dfmv_library" > "$dfmv_evidence/symbols/$dfmv_name.sha256"
    readelf --wide --dyn-syms "$dfmv_library" > "$dfmv_evidence/symbols/$dfmv_name.dynsym.txt"
    readelf --wide --relocs "$dfmv_library" > "$dfmv_evidence/symbols/$dfmv_name.relocations.txt"
    readelf --wide --dynamic "$dfmv_library" > "$dfmv_evidence/symbols/$dfmv_name.dynamic.txt"
done
python3 "$dfmv_helper" verify-elf "$dfmv_output_dir"

dfmv_stage=nested-qt-probe
cp "$dfmv_repo_dir/scripts/diagnose-dpf/"{CMakeLists.txt,host.cpp,outer.cpp,inner.cpp} "$dfmv_evidence/probe/"
dfmv_probe_flags="$(rpm --eval '%{optflags}') -g -Wall -Wl,--as-needed -fstack-protector-all -Werror=return-type -Wl,-z,relro -Wl,-z,now -Ofast"
dfmv_linker_flags=$(rpm --eval '%{build_ldflags}')
printf '%s\n' "$dfmv_probe_flags" > "$dfmv_evidence/probe/cxx-flags.txt"
printf '%s\n' "$dfmv_linker_flags" > "$dfmv_evidence/probe/linker-flags.txt"
cmake -S "$dfmv_repo_dir/scripts/diagnose-dpf" -B "$dfmv_work_dir/probe-build" -GNinja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DCMAKE_CXX_FLAGS_RELEASE:STRING=-DNDEBUG -DCMAKE_CXX_FLAGS:STRING="$dfmv_probe_flags" \
    -DCMAKE_MODULE_LINKER_FLAGS:STRING="$dfmv_linker_flags" \
    -DCMAKE_EXE_LINKER_FLAGS:STRING="$dfmv_linker_flags" \
    2>&1 | tee "$dfmv_evidence/logs/probe-configure.log"
cmake --build "$dfmv_work_dir/probe-build" --parallel 2 --verbose \
    2>&1 | tee "$dfmv_evidence/logs/probe-build.log"
cp "$dfmv_work_dir/probe-build/compile_commands.json" "$dfmv_evidence/probe/"
ctest --test-dir "$dfmv_work_dir/probe-build" --output-on-failure -V \
    2>&1 | tee "$dfmv_evidence/logs/probe-test.log"
for dfmv_plugin in outer inner; do
    readelf --wide --dyn-syms "$dfmv_work_dir/probe-build/dpf-probe-$dfmv_plugin.so" \
        > "$dfmv_evidence/probe/$dfmv_plugin.dynsym.txt"
done
python3 "$dfmv_helper" complete "$dfmv_output_dir"
dfmv_stage=complete
