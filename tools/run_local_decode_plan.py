"""Execute an explicit list of isolated decode experiments, one engine at a time."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    results = []
    for case in plan:
        name, model = case["name"], case["model"]
        dst = args.output / f"{model}-{name}"
        cmd = [sys.executable, str(ROOT / "tools/explore_local_decode.py"), "--model", model,
               "--name", name, "--output", str(dst), "--env", json.dumps(case.get("env", {})),
               "--stage", str(case.get("stage", 0)), "--count", str(case.get("count", 3)),
               "--tokens", str(case.get("tokens", 128)), "--temperature", str(case.get("temperature", 0))]
        if case.get("exe"):
            cmd += ["--exe", case["exe"]]
        if case.get("production_memory"):
            cmd += ["--production-memory"]
        if case.get("idle_vram_mib"):
            cmd += ["--idle-vram-mib", str(case["idle_vram_mib"])]
        print(f"CASE {model} {name}", flush=True)
        # A timeout ends only this owned worker process tree, not any user's service.
        with (args.output / f"{model}-{name}-console.log").open("w", encoding="utf-8") as console:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT)
            try:
                code = proc.wait(timeout=900)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                raise RuntimeError(f"Owned benchmark timed out: {model} {name}")
        record = {"model": model, "name": name, "exit_code": code,
                  "at": datetime.now(timezone.utc).isoformat()}
        file = dst / "results.json"
        if file.exists():
            data = json.loads(file.read_text(encoding="utf-8"))
            record.update(status=data.get("status"), median_tok_s=data.get("median_tok_s"),
                          error=data.get("error"))
        results.append(record)
        print(json.dumps(record), flush=True)
        (args.output / (args.plan.stem + "-summary.json")).write_text(json.dumps(results, indent=2), encoding="utf-8")
        if code:
            raise RuntimeError(f"Benchmark failed; stop before another load: {record}")


if __name__ == "__main__":
    main()
