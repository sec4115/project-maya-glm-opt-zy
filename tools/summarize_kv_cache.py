"""Summarize completed isolated cache cases; no inference or file mutations outside the report."""
import argparse
import json
from pathlib import Path
import re
import statistics

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("root", type=Path)
args = ap.parse_args()
summaries = []
for p in sorted(args.root.rglob("results.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("status") != "success":
        continue
    rows = d["rows"]
    summary = {"name": d["name"], "model": d["model"], "exe_sha256": d["exe_sha256"],
               "engine_info": d["engine_info"], "rows": len(rows)}
    for category in ("short_decode", "long_decode"):
        selected = [r for r in rows if r["name"].startswith(category)]
        if selected:
            summary[category + "_tok_s"] = sum(r["engine"]["generated"] for r in selected) * 1000 / sum(
                r["engine"]["decode_ms"] for r in selected)
    for category in ("prefix_reordered_keys", "root_fork", "switch_A_recall", "switch_B_recall"):
        selected = [r for r in rows if r["name"].startswith(category)]
        if selected:
            summary[category] = {"ttft_s": statistics.mean(r["ttft_s"] for r in selected),
                                  "reused": [r["engine"].get("reused", 0) for r in selected]}
    log = (p.parent / "engine.log").read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r'glm kv: KV streaming: ([\d.]+)% of (\d+) block reads hit VRAM, ([\d.]+) MiB', log)
    if len(matches) == len(rows):
        # Counters reset when maps are reset. Only subtract successive snapshots
        # inside the same A conversation, immediately after its restore/recall.
        samples = []
        for i, row in enumerate(rows):
            if row["name"].startswith("long_decode") and i > 0:
                prev, cur = matches[i - 1], matches[i]
                before, after = int(prev[1]), int(cur[1])
                delta = after - before
                if delta > 0:
                    miss0 = before * (1 - float(prev[0]) / 100)
                    miss1 = after * (1 - float(cur[0]) / 100)
                    samples.append({"name": row["name"], "lookups": delta,
                                    "approx_hit_pct": 100 * (1 - (miss1 - miss0) / delta)})
        summary["long_kv_counter_deltas"] = samples
    summary["slot_save_timings"] = re.findall(r'glm slots: save .*', log)[-4:]
    summaries.append(summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ["slot_save_timings", "engine_info", "exe_sha256"]}))
(args.root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
