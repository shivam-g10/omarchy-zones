#!/bin/sh
set -eu
evaluation_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 - "$evaluation_dir" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(sys.argv[1])
evidence = root / "evidence"
evidence.mkdir(exist_ok=True)
steps = [
    ("qtbridge", ["cargo", "build", "--locked", "--release", "--jobs", "2"], "zones-qtbridge-poc"),
    ("cxxqt", ["cargo", "build", "--locked", "--release", "--jobs", "2"], "zones-cxxqt-evaluation"),
    ("native", ["sh", "build-plugin.sh"], "zones-rust-poc.so"),
]
report = {"started_at_unix": time.time(), "steps": [], "artifacts": {}}
for project, command, artifact in steps:
    start = time.monotonic()
    result = subprocess.run(command, cwd=root / project)
    report["steps"].append({"project": project, "command": command,
                            "seconds": time.monotonic() - start, "exit_code": result.returncode})
    (evidence / "build-all.json").write_text(json.dumps(report, indent=2) + "\n")
    if result.returncode:
        raise SystemExit(result.returncode)
    path = root / project / "target/release" / artifact
    report["artifacts"][project] = {"path": str(path), "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
header = Path("/usr/include/hyprland/src/version.h").read_text()
report["hyprland_header_commit"] = re.search(r'^#define\s+GIT_COMMIT_HASH\s+"([0-9a-f]+)"', header, re.M)[1]
report["finished_at_unix"] = time.time()
(evidence / "build-all.json").write_text(json.dumps(report, indent=2) + "\n")
print("Built all three experiments. Timing and artifact hashes: " + str(evidence / "build-all.json"))
print("No installation, compositor loading, or desktop configuration changes performed.")
PY
