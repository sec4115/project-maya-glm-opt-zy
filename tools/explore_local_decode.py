"""Run an isolated real HTTP service and record a reproducible decode experiment."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import requests
import strata_tokenizer as ST
import calibrate_glm as cal
from maya import busy_gpus, read_json
from serve.frontend import ChatTemplate
from serve.server import Service, StrataEngine, child_env, engine_args, serve, vision_footprint


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", choices=("m", "l", "xl"), required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--env", default="{}")
    ap.add_argument("--stage", type=int, default=0)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--tokens", type=int, default=128)
    ap.add_argument("--temperature", type=float, default=0)
    ap.add_argument("--exe", type=Path)
    ap.add_argument("--port", type=int, default=18091)
    ap.add_argument("--production-memory", action="store_true", help="include the normal server's vision lending layout")
    ap.add_argument("--idle-vram-mib", type=int, default=1024, help="explicit ceiling for verified desktop-only GPU usage")
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    original = (ROOT / f"maya-maya-{a.model}.json").read_bytes()
    cfg = read_json(ROOT / f"maya-maya-{a.model}.json")
    (a.output / "original-config.json").write_bytes(original)
    cfg = copy.deepcopy(cfg)
    cfg["args"] = cal.without_writes(cfg["args"])
    cfg["env"].update({"STRATA_GLM_USAGE": "0", "STRATA_GLM_SLOTS": "0"})
    cfg["env"].update({str(k): str(v) for k, v in json.loads(a.env).items()})
    if a.production_memory and cfg.get("vision", {}).get("gpu"):
        ve = child_env(cfg)
        ve["CUDA_VISIBLE_DEVICES"] = str(cfg["gpu"][0])
        footprint = vision_footprint(cfg["vision"], ve, ROOT / "vision-memory.json", cfg["gpu"][0])
        if footprint is None:
            raise RuntimeError("Could not reproduce production vision lending layout")
        cfg["env"]["STRATA_GLM_VISION_LEND_MB"] = str((footprint[1] >> 20) + 1)
    cfg["log"] = str((a.output / "engine.log").resolve())
    if a.exe:
        cfg["exe"] = str(a.exe.resolve())
    (a.output / "test-config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    report = {"name": a.name, "model": a.model, "started_at": datetime.now(timezone.utc).isoformat(),
              "exe": cfg["exe"], "exe_mtime": Path(cfg["exe"]).stat().st_mtime,
              "env": cfg["env"], "samples": [], "warmup": [], "stage": a.stage,
              "temperature": a.temperature, "max_tokens": a.tokens, "production_memory": a.production_memory}
    eng, httpd = None, None
    session = requests.Session()
    session.trust_env = False
    base = f"http://127.0.0.1:{a.port}"
    def save():
        (a.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        if any(mib > a.idle_vram_mib for _, mib in busy_gpus(cfg)):
            raise RuntimeError("GPUs are busy; stop the running model before an isolated experiment")
        print(f"START {a.model} {a.name}", flush=True)
        t0 = time.perf_counter()
        eng = StrataEngine(cfg["exe"], engine_args(cfg), cwd=cfg["cwd"], log=cfg["log"], env=child_env(cfg))
        tok = ST.Tokenizer.from_dir(Path(cfg["tokenizer"]))
        svc = Service(eng, tok, ChatTemplate(Path(cfg["tokenizer"]) / "chat_template.jinja"),
                      model_name=cfg["model_name"], sampling_defaults=cfg.get("sampling", {}))
        svc.default_effort = "none"
        httpd = serve(svc, host="127.0.0.1", port=a.port)
        health = session.get(base + "/health", timeout=10)
        health.raise_for_status()
        report.update(load_seconds=time.perf_counter()-t0, engine_info=eng.info, health=health.json())
        save()
        prompts = list(cal.PROMPTS)
        warm = ["Explain how a binary search works, with an example.", "Write a Python function to count characters in a string, with tests."]
        tested = [prompts[(a.stage * 9 + i) % len(prompts)] for i in range(a.count)]
        for i, prompt in enumerate(warm + tested):
            body = {"model": cfg["model_name"], "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 96 if i < len(warm) else a.tokens, "temperature": a.temperature,
                    "seed": 20261019, "reasoning_effort": "none", "stream": False}
            wall = time.perf_counter()
            response = session.post(base + "/v1/chat/completions", json=body, timeout=240)
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"].get("content") or ""
            last = dict(eng.last or {})
            n = int(last.get("generated") or 0)
            ms = float(last.get("decode_ms") or 0)
            if n < 16 or ms <= 0 or not text.strip():
                raise RuntimeError(f"Invalid generation: tokens={n}, ms={ms}, body={data}")
            row = {"prompt": prompt, "rate": n * 1000/ms, "wall_seconds": time.perf_counter()-wall,
                   "engine": last, "timings": data.get("timings"), "usage": data.get("usage"),
                   "finish": data["choices"][0].get("finish_reason"),
                   "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            key = "warmup" if i < len(warm) else "samples"
            report[key].append(row)
            save()
            print(f"SAMPLE {a.name} {key} {len(report[key])}: {row['rate']:.2f} tok/s", flush=True)
        report["median_tok_s"] = statistics.median(r["rate"] for r in report["samples"])
        report["aggregate_tok_s"] = sum(r["engine"]["generated"] for r in report["samples"]) * 1000 / sum(r["engine"]["decode_ms"] for r in report["samples"])
        report["status"] = "success"
        print(f"RESULT {a.model} {a.name}: {report['median_tok_s']:.3f} tok/s", flush=True)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if eng:
            cal.close(eng)
        session.close()


if __name__ == "__main__":
    main()
