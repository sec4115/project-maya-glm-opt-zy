"""Compare additional SSD read granularities for the installed Maya-L model."""
from __future__ import annotations

import json
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path

import calibrate_glm as cal
from maya import busy_gpus, read_json
from serve.server import StrataEngine, child_env, engine_args


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "maya-maya-l.json"
    original = path.read_bytes()
    cfg = read_json(path)
    if busy_gpus(cfg):
        raise RuntimeError("Stop the running model before calibration; its GPUs are busy")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = root / "bench" / "results" / f"local-disk-tuning-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, output / path.name)
    cfg["args"] = cal.without_writes(list(cfg["args"]))
    cfg["env"] = {**cfg.get("env", {}), "STRATA_GLM_USAGE": "0", "STRATA_GLM_SLOTS": "0"}
    cfg["env"].pop(cal.CHUNKS_ENV, None)
    cfg["log"] = str(output / "engine.log")
    result = {"max_new": 96, "sweep": {}, "confirm": {}}

    def save() -> None:
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Maya-L SSD comparison: {output}", flush=True)
    cal.MAX_NEW = 96
    engine = StrataEngine(cfg["exe"], engine_args(cfg), cwd=cfg.get("cwd"),
                          log=cfg["log"], env=child_env(cfg))
    try:
        session = cal.Session(engine, cal.prompt_ids(cfg))
        session.warm_up()
        for chunks in (8, 1, 2, 16):
            rate = session.rate({"read_chunks": chunks})
            result["sweep"][str(chunks)] = rate
            print(f"  {chunks} pieces: {rate:.2f} tok/s", flush=True)
            save()
        best = max(result["sweep"], key=result["sweep"].get)
        chosen = "8"
        if best != "8":
            result["confirm"] = {"8": [], best: []}
            for round_number in range(3):
                for chunks in ("8", best):
                    rate = session.rate({"read_chunks": int(chunks)})
                    result["confirm"][chunks].append(rate)
                    print(f"  confirm {round_number + 1}, {chunks} pieces: {rate:.2f} tok/s", flush=True)
                    save()
            chosen = cal.pick(result["confirm"], "8")
        result["chosen"] = chosen
        if result["confirm"]:
            result["baseline_tok_s"] = statistics.median(result["confirm"]["8"])
            result["chosen_tok_s"] = statistics.median(result["confirm"][chosen])
        result["measured_at"] = datetime.now(timezone.utc).isoformat()
        save()
    finally:
        cal.close(engine)
    if path.read_bytes() != original:
        raise RuntimeError("Config changed during calibration; measurements saved without applying")
    if chosen != "8":
        saved = json.loads(original.decode("utf-8"))
        saved.setdefault("env", {})[cal.CHUNKS_ENV] = chosen
        path.write_text(json.dumps(saved, indent=1) + "\n", encoding="utf-8")
    print(f"Maya-L: kept {chosen} pieces; results: {output}", flush=True)


if __name__ == "__main__":
    main()
