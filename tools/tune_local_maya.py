"""Calibrate installed Maya configs, saving backups and measurements locally."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import calibrate_glm as cal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m-finalist", action="store_true",
                        help="recheck only the M finalist from the October 2026 local sweep")
    parser.add_argument("--l-finalist", action="store_true",
                        help="recheck L at 10%% PCIe share and 6 CPU threads, then tune disk reads")
    parser.add_argument("--only", choices=("m", "l"), help="calibrate one model")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = root / "bench" / "results" / f"local-tuning-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    # Keep temporary calibration files inside the writable workspace on Windows.
    tempfile.tempdir = str(output)
    for name in ("maya-maya-m.json", "maya-maya-l.json"):
        if options.only and name != f"maya-maya-{options.only}.json":
            continue
        path = root / name
        original = path.read_bytes()
        from maya import busy_gpus, read_json
        cfg = read_json(path)

        if busy_gpus(cfg):
            raise RuntimeError("Stop the running model before calibration; its GPUs are busy")
        shutil.copy2(path, output / name)
        cfg["log"] = str(output / name.replace(".json", ".log"))
        # Benchmark conversations must not replace the user's saved chat slots.
        cfg.setdefault("env", {})["STRATA_GLM_SLOTS"] = "0"
        print(f"\nCalibrating {name}; results: {output}", flush=True)
        shares, candidates, max_new = cal.PCIE_SHARES, cal.thread_candidates, cal.MAX_NEW
        if name == "maya-maya-m.json" and options.m_finalist:
            # The broad local sweep already ruled out larger shares and fewer
            # threads; repeat only the finalist and the default, interleaved.
            cal.PCIE_SHARES = (0.1,)
            cal.thread_candidates = lambda default, extra=(): [default]
        if name == "maya-maya-l.json" and options.l_finalist:
            cal.PCIE_SHARES = (0.1,)
            cal.thread_candidates = lambda default, extra=(): [default, 6] if default > 6 else [default]
            cal.MAX_NEW = 96
        def progress(msg: str) -> None:
            print(msg, flush=True)
            with (output / "progress.txt").open("a", encoding="utf-8") as stream:
                stream.write(msg + "\n")
        try:
            result = cal.run(cfg, say=progress)
        finally:
            cal.PCIE_SHARES, cal.thread_candidates, cal.MAX_NEW = shares, candidates, max_new
        result["measured_at"] = datetime.now(timezone.utc).isoformat()
        (output / name.replace(".json", "-results.json")).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        if path.read_bytes() != original:
            raise RuntimeError(f"{name} changed during calibration; results saved without applying")
        saved = json.loads(original.decode("utf-8"))
        saved["env"] = cal.apply(saved.get("env", {}), result["settings"])
        path.write_text(json.dumps(saved, indent=1) + "\n", encoding="utf-8")
        print(f"Applied {name}: {result['settings']}; {result['report']}", flush=True)


if __name__ == "__main__":
    main()
