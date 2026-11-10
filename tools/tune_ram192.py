"""Calibrate a model with the production vision allowance and isolated writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import calibrate_glm as cal
from benchmark_kv_cache import host_memory
from maya import busy_gpus, read_json
from serve.server import StrataEngine, child_env, engine_args, vision_footprint


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", choices=("m", "l", "xl"), required=True)
    ap.add_argument("--ram", required=True, type=int)
    ap.add_argument("--env", default="{}")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--idle-vram-mib", type=int, default=2304)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cfg = read_json(ROOT / f"maya-maya-{args.model}.json")
    if any(mib > args.idle_vram_mib for _, mib in busy_gpus(cfg)):
        raise RuntimeError("GPU busy; no model was loaded")
    cfg.setdefault("env", {}).update({"STRATA_GLM_RAM_GB": str(args.ram), "STRATA_GLM_SLOTS": "0",
                                       "STRATA_GLM_USAGE": "0", "STRATA_FAIR_SLICE_S": "0"})
    cfg["env"].update({str(k): str(v) for k, v in json.loads(args.env).items()})
    ve = child_env(cfg)
    ve["CUDA_VISIBLE_DEVICES"] = str(cfg["gpu"][0])
    footprint = vision_footprint(cfg["vision"], ve, ROOT / "vision-memory.json", cfg["gpu"][0])
    if footprint is None:
        raise RuntimeError("Cannot reproduce production vision allowance")
    cfg["env"]["STRATA_GLM_VISION_LEND_MB"] = str((footprint[1] >> 20) + 1)
    cfg["log"] = str((args.output / "engine.log").resolve())
    (args.output / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    report = {"at": datetime.now(timezone.utc).isoformat(), "model": args.model,
              "ram_budget_gib": args.ram, "memory_before": host_memory()}

    def start_engine(current):
        (args.output / "effective-config.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
        eng = StrataEngine(current["exe"], engine_args(current), cwd=current["cwd"],
                           log=current["log"], env=child_env(current))
        report["engine_info"] = dict(eng.info)
        report["memory_after_load"] = host_memory()
        return eng

    try:
        report["calibration"] = cal.run(cfg, say=lambda message: print(message, flush=True), start_engine=start_engine)
        report["status"] = "success"
    except Exception as ex:
        report.update(status="failed", error=f"{type(ex).__name__}: {ex}")
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["memory_after_close"] = host_memory()
        (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
