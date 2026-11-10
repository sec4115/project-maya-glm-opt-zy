"""Summarize isolated RAM budget results without running inference."""
import argparse
import json
from pathlib import Path
import re
import statistics

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("root", type=Path)
args = ap.parse_args()
records = []
for p in sorted(args.root.glob("measured/*/results.json")):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A running worker may be replacing its latest request snapshot.
        continue
    rows = d.get("rows", [])
    record = {"name": d["name"], "model": d["model"], "ram_gib": d["env"]["STRATA_GLM_RAM_GB"],
              "status": d.get("status", "running"), "error": d.get("error"), "rows": len(rows),
              "load_s": d.get("load_s"), "memory_after_load": d.get("memory_after_load"),
              "engine_info": d.get("engine_info")}
    mem = [r["host_memory"]["available_phys_gib"] for r in rows if r.get("host_memory")]
    record["minimum_observed_free_gib"] = min(mem) if mem else None
    for group in ("short_decode", "long_decode"):
        selected = [r for r in rows if r["name"].startswith(group)]
        if selected:
            record[group] = {"aggregate_tok_s": sum(r["engine"]["generated"] for r in selected) * 1000 /
                            sum(r["engine"]["decode_ms"] for r in selected),
                            "individual_tok_s": [r["tok_s"] for r in selected],
                            "output_hashes": [r["sha256"] for r in selected]}
    for group in ("switch_A_recall", "switch_B_recall"):
        selected = [r for r in rows if r["name"].startswith(group)]
        if selected:
            record[group + "_ttft_s"] = statistics.mean(r["ttft_s"] for r in selected)
    log = (p.parent / "engine.log").read_text(encoding="utf-8", errors="replace")
    stats = re.findall(r"glm stat: decode .*?disk ([\d.]+) reads/tok in [\d.]+ waits/tok, ([\d.]+) ms/tok", log)
    if len(stats) == len(rows):
        record["decode_disk"] = [{"name": r["name"], "reads_per_token": float(s[0]), "wait_ms_per_token": float(s[1])}
                                 for r, s in zip(rows, stats) if "decode" in r["name"]]
    records.append(record)
    print(json.dumps({k: v for k, v in record.items() if k not in ("engine_info", "decode_disk")}, ensure_ascii=False))
(args.root / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
