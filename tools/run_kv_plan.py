"""Run an explicit KV/cache plan sequentially, with one owned engine at a time."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("plan", type=Path)
ap.add_argument("--output", type=Path, required=True)
args = ap.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
records = []
for case in json.loads(args.plan.read_text(encoding="utf-8")):
    name = case["name"]
    out = args.output / name
    cmd = [sys.executable, str(ROOT / "tools/benchmark_kv_cache.py"), "--model", case.get("model", "m"),
           "--name", name, "--output", str(out), "--env", json.dumps(case.get("env", {})),
           "--phase", case.get("phase", "full"), "--long-tokens", str(case.get("long_tokens", 45056)),
           "--idle-vram-mib", str(case.get("idle_vram_mib", 1536))]
    if case.get("exe"):
        cmd += ["--exe", case["exe"]]
    if case.get("config"):
        cmd += ["--config", case["config"]]
    print("CASE", name, flush=True)
    with (args.output / (name + "-console.log")).open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise RuntimeError("Owned case timed out: " + name)
    entry = {"name": name, "exit_code": code, "at": datetime.now(timezone.utc).isoformat()}
    p = out / "results.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        entry.update(status=d.get("status"), rows=len(d.get("rows", [])), error=d.get("error"))
    records.append(entry)
    (args.output / (args.plan.stem + "-summary.json")).write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(entry), flush=True)
    if code:
        raise RuntimeError("Failed case: " + name)
