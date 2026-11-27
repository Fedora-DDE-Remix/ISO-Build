#!/usr/bin/env python3
"""Require the observed failure and the exact header-only candidate to differ."""

import json
import os
from pathlib import Path
import re
import sys


def read_probe(path):
    report = None
    outer = None
    for line in path.read_text().splitlines():
        match = re.search(r"outer registry=(\d+) converted=(-?\d+) callback=(\d+) callback_address=(0x[0-9a-f]+)", line)
        if match:
            outer = {
                "registry_id": int(match[1]),
                "converted_id": int(match[2]),
                "callback_valid": bool(int(match[3])),
                "callback_address": match[4],
            }
        offset = line.find('{"callback_address"')
        if offset >= 0:
            report = json.loads(line[offset:])
    if report is None or outer is None:
        raise ValueError(f"missing direct probe report in {path}")
    return {"outer": outer, "inner": report}


root = Path(sys.argv[1])
baseline_status, candidate_status = map(int, sys.argv[2:4])
baseline = read_probe(root / "probe-test.log")
candidate = read_probe(root / "header-fixed" / "probe-test.log")
before, after = baseline["inner"], candidate["inner"]
baseline_reproduced = (
    baseline_status == 8
    and baseline["outer"]["callback_valid"]
    and baseline["outer"]["registry_id"] == baseline["outer"]["converted_id"]
    and before["registry_id"] > 0
    and before["converted_id"] == -1
    and not before["callback_valid"]
    and int(before["callback_address"], 16) != int(baseline["outer"]["callback_address"], 16)
    and not before["number_connected"] and not before["list_connected"]
)
candidate_passed = (
    candidate_status == 0
    and after["passed"] and after["callback_valid"]
    and after["registry_id"] == after["converted_id"] > 0
    and int(after["callback_address"], 16) == int(candidate["outer"]["callback_address"], 16)
    and after["number_connected"] and after["list_connected"]
    and after["number_variant_valid"] and after["number"] == 37
    and after["list_variant_valid"] and after["list_size"] == 2
)
result = {
    "schema": 2,
    "scope": "Packaged DPF, before and after declaring one external callback in probe headers",
    "source_commit": os.environ.get("GITHUB_SHA"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "baseline_ctest_exit_status": baseline_status,
    "candidate_ctest_exit_status": candidate_status,
    "baseline_reproduced": baseline_reproduced,
    "candidate_probe_passed": candidate_passed,
    "baseline": baseline,
    "candidate": candidate,
    "desktop_verified": False,
    "packaged_libraries_patched": False,
    "full_source_patch_built": False,
}
(root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if not baseline_reproduced or not candidate_passed:
    raise SystemExit("FAIL: the expected broken/candidate pair was not demonstrated")
