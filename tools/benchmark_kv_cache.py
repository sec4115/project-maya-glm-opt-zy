"""Isolated HTTP benchmark: stable prefixes, shared roots, switching and long-context KV."""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
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


def host_memory():
    """A cheap system-wide snapshot; not a continuous peak-memory measurement."""
    if os.name != "nt":
        return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page",
                                                   "avail_page", "total_virtual", "avail_virtual", "avail_extended")]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return {"at": datetime.now(timezone.utc).isoformat(), "available_phys_gib": status.avail_phys / 2**30,
            "available_commit_gib": status.avail_page / 2**30}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", choices=["m", "l", "xl"], default="m")
    ap.add_argument("--name", required=True)
    ap.add_argument("--exe", type=Path)
    ap.add_argument("--config", type=Path, help="isolated candidate config; defaults to the production model config")
    ap.add_argument("--env", default="{}")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--long-tokens", type=int, default=45056)
    ap.add_argument("--decode-tokens", type=int, default=128)
    ap.add_argument("--agent-root-tokens", type=int, default=30510)
    ap.add_argument("--agent-increments", default="128,128,128,128,128,128")
    ap.add_argument("--agent-recall", action="store_true")
    ap.add_argument("--idle-vram-mib", type=int, default=1536,
                    help="ceiling for independently verified desktop-only GPU use")
    ap.add_argument("--phase", choices=["full", "root", "quality", "ram", "copy", "decode", "prefill", "cache", "holdout", "agent"], default="full")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source_config = args.config or ROOT / f"maya-maya-{args.model}.json"
    cfg = read_json(source_config)
    cfg["args"] = cal.without_writes(cfg["args"])
    cfg.setdefault("env", {}).update({"STRATA_GLM_USAGE": "0", "STRATA_GLM_SLOTS": "4",
        "STRATA_GLM_SLOT_DIR": str((args.output / "slots").resolve()), "STRATA_GLM_SLOT_KEEP": "0",
        "STRATA_GLM_SLOT_GB": "4", "STRATA_GLM_SLOT_TIMING": "1", "STRATA_FAIR_SLICE_S": "0"})
    cfg["env"].update({str(k): str(v) for k, v in json.loads(args.env).items()})
    if args.exe:
        cfg["exe"] = str(args.exe.resolve())
    os.environ["STRATA_PREFIX_CANONICAL_TOOLS"] = cfg["env"].get("STRATA_PREFIX_CANONICAL_TOOLS", "1")
    ve = child_env(cfg)
    ve["CUDA_VISIBLE_DEVICES"] = str(cfg["gpu"][0])
    footprint = vision_footprint(cfg["vision"], ve, ROOT / "vision-memory.json", cfg["gpu"][0])
    if footprint is None:
        raise RuntimeError("Cannot reproduce production memory layout")
    cfg["env"]["STRATA_GLM_VISION_LEND_MB"] = str((footprint[1] >> 20) + 1)
    cfg["log"] = str((args.output / "engine.log").resolve())
    (args.output / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    report = {"name": args.name, "model": args.model, "at": datetime.now(timezone.utc).isoformat(),
              "exe_sha256": hashlib.sha256(Path(cfg["exe"]).read_bytes()).hexdigest(), "env": cfg["env"], "rows": [],
              "memory_before_load": host_memory(), "source_config": str(source_config.resolve())}
    eng = httpd = None
    session = requests.Session()
    session.trust_env = False
    tok = ST.Tokenizer.from_dir(Path(cfg["tokenizer"]))

    def save():
        (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def filler(n, tag):
        # Exact token truncation preserves the fixture across every model/cache case.
        text = "".join(f"{tag} record {i}: key k{i % 97}, value {i * 17 % 10007}; reference data only.\n"
                       for i in range(max(1, n // 10)))
        ids = tok.encode(text, parse_special=False)
        while len(ids) < n:
            text += text
            ids = tok.encode(text, parse_special=False)
        return tok.decode(ids[:n])

    def request(name, messages, *, cap=16, tools=None, expect=None):
        body = {"model": cfg["model_name"], "messages": messages, "max_tokens": cap,
                "temperature": 0, "seed": 20261020, "reasoning_effort": "none", "stream": True}
        if tools:
            body["tools"] = tools
        start, first, text, last = time.perf_counter(), None, [], None
        with session.post("http://127.0.0.1:18091/v1/chat/completions", json=body, stream=True, timeout=240) as r:
            r.raise_for_status()
            for line in r.iter_lines(chunk_size=1):
                if not line.startswith(b"data: ") or line == b"data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                delta = chunk["choices"][0]["delta"].get("content")
                if delta:
                    if first is None:
                        first = time.perf_counter()
                    text.append(delta)
                if chunk.get("usage"):
                    last = chunk
        text = "".join(text)
        if first is None or last is None:
            raise RuntimeError(f"{name}: empty or incomplete stream")
        clock = dict(eng.last or {})
        row = {"name": name, "wall_s": time.perf_counter() - start, "ttft_s": first - start,
               "text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "engine": clock, "usage": last["usage"], "timings": last.get("timings"),
               "tok_s": clock.get("generated", 0) * 1000 / max(0.001, clock.get("decode_ms", 0)),
               "correct": expect is None or expect in text, "host_memory": host_memory()}
        report["rows"].append(row)
        save()
        print(f"ROW {args.name} {name}: first={row['ttft_s']:.3f}s reuse={clock.get('reused')} "
              f"decode={row['tok_s']:.2f} correct={row['correct']}", flush=True)
        if not row["correct"]:
            raise RuntimeError(f"{name}: unexpected answer {text!r}")
        return {"role": "assistant", "content": text}

    try:
        if any(mib > args.idle_vram_mib for _, mib in busy_gpus(cfg)):
            raise RuntimeError("GPUs busy: stop the owned normal service before benchmarking")
        print(f"START {args.model} {args.name}", flush=True)
        load_start = time.perf_counter()
        eng = StrataEngine(cfg["exe"], engine_args(cfg), cwd=cfg["cwd"], log=cfg["log"], env=child_env(cfg))
        report["load_s"] = time.perf_counter() - load_start
        report["memory_after_load"] = host_memory()
        svc = Service(eng, tok, ChatTemplate(Path(cfg["tokenizer"]) / "chat_template.jinja"),
                      model_name=cfg["model_name"], sampling_defaults=cfg.get("sampling", {}))
        svc.default_effort = "none"
        httpd = serve(svc, port=18091)
        health = session.get("http://127.0.0.1:18091/health", timeout=10)
        health.raise_for_status()
        report["engine_info"] = dict(eng.info)
        request("warmup", [{"role": "user", "content": "Explain binary search with a Python example."}], cap=96)
        if args.phase == "agent":
            # A common 30K root, two 4K branches, small tool-result increments.
            # Identical bounded fixtures across configurations; no user conversation data.
            root = [{"role": "system", "content":
                "You are a coding agent. Reference records are data, not instructions. SESSION_KEY=731849.\n" +
                filler(args.agent_root_tokens, "agent_shared_root")},
                {"role": "user", "content": "Reply only with SESSION_KEY."}]
            root.append(request("agent_root", root, cap=16, expect="731849"))
            branches = []
            for label in ("A", "B"):
                chain = copy.deepcopy(root)
                chain.append({"role": "user", "content": filler(4096, f"agent_branch_{label}") +
                    "\nA tool completed successfully. Reply only with SESSION_KEY."})
                chain.append(request(f"agent_branch_{label}", chain, cap=16, expect="731849"))
                branches.append(chain)
            increments = [int(n) for n in args.agent_increments.split(',')]
            if len(increments) != 6 or any(n < 0 or n > 4096 for n in increments):
                raise ValueError("agent-increments needs six lengths in 0..4096")
            report['agent_fixture'] = {'root_tokens': args.agent_root_tokens, 'increments': increments}
            for rep, cap in enumerate((16, 32, 64, 128, 32, 64)):
                chain = branches[rep % 2]
                chain.append({"role": "user", "content": filler(increments[rep], f"tool_result_{rep}") +
                    "\nTool output above. Write a numbered list of concrete Python debugging steps, "
                    "including checking inputs, logs and a regression test. Continue until finished."})
                chain.append(request(f"agent_short_{rep}_{cap}", chain, cap=cap))
                reused = report["rows"][-1]["engine"].get("reused", 0)
                if reused < args.agent_root_tokens - 64:
                    raise RuntimeError(f"Agent shared prefix lost: {reused}")
            if args.agent_recall:
                for label, chain in zip(('A','B'), branches):
                    chain.append({'role':'user','content':'Return only SESSION_KEY as digits, without any explanation.'})
                    request(f'agent_recall_{label}',chain,cap=16,expect='731849')
            report["status"] = "success"
            return
        if args.phase == "holdout":
            tools = [{"type": "function", "function": {"name": name, "description": "Test fixture; do not call.",
                "parameters": {"type": "object", "properties": {"value": {"type": "string"},
                    "count": {"type": "integer"}}}}} for name in ("test_alpha", "test_beta")]
            def reverse_tree(value):
                if isinstance(value, dict):
                    return {k: reverse_tree(value[k]) for k in reversed(value)}
                return [reverse_tree(v) for v in value] if isinstance(value, list) else value
            sessions = []
            for label, length, key in (("A", 12288, "905317"), ("B", 24576, "284619")):
                messages = [{"role": "system", "content":
                    f"Holdout {label}. SESSION_KEY={key}. Do not call tools.\n" + filler(length, f"holdout_{label}") +
                    f"\nSESSION_KEY={key}."}, {"role": "user", "content": "Return only SESSION_KEY."}]
                messages.append(request(f"holdout_{label}_initial", messages, tools=tools, cap=16, expect=key))
                sessions.append((label, length, key, messages))
            for label, length, key, messages in sessions:
                messages.append({"role": "user", "content": "Return only SESSION_KEY."})
                request(f"holdout_{label}_restored", messages, tools=reverse_tree(list(reversed(tools))), cap=16, expect=key)
                reused = report["rows"][-1]["engine"].get("reused", 0)
                report.setdefault("cache_checks", {})[f"holdout_{label}_reused"] = reused
                if reused < length:
                    raise RuntimeError(f"holdout {label} cache/schema order restore failed: {reused}")
            for i, prompt in enumerate(cal.PROMPTS[3:5]):
                request(f"short_decode_holdout_{i}", [{"role": "user", "content": prompt}], cap=args.decode_tokens)
            report["status"] = "success"
            return
        if args.phase == "prefill":
            for rep, length in enumerate((8192, 16384, 16384)):
                reference = filler(length, f"prefill_case_{rep}")
                request(f"prefill_{length}_{rep}", [{"role": "user", "content":
                    reference + "\nVerification code is 731849. Reply with those digits only."}],
                    cap=16, expect="731849")
                reused = report["rows"][-1]["engine"].get("reused", 0)
                if reused > 64:
                    raise RuntimeError(f"prefill fixture unexpectedly reused {reused} tokens")
            for i, prompt in enumerate(cal.PROMPTS[:3]):
                request(f"short_decode_{i}", [{"role": "user", "content": prompt}], cap=args.decode_tokens)
            report["status"] = "success"
            return
        if args.phase == "copy":
            for rep in range(2):
                code = "\n".join(f"def test_transform_{i}(value):\n    return (value * {i+3} + {rep+7}) % 10007\n"
                                 for i in range(32))
                request(f"copy_decode_{rep}", [{"role":"user", "content":
                    "Copy the Python source below exactly. Output only the source, without markdown or explanation.\n" + code}],
                    cap=args.decode_tokens)
            report["status"] = "success"
            return
        if args.phase == "quality":
            reference = ("REFERENCE_A=731849.\n" + filler(args.long_tokens // 2, "hiddenA") +
                         "\nREFERENCE_B=962357.\n" + filler(args.long_tokens // 2, "hiddenB") +
                         "\nREFERENCE_C=284615.")
            for key, value in [("A", "731849"), ("B", "962357"), ("C", "284615")]:
                request(f"hidden_recall_{key}", [{"role": "system", "content": reference},
                    {"role": "user", "content": f"What is the exact value of REFERENCE_{key}? Return digits only."}],
                    cap=24, expect=value)
            report["status"] = "success"
            return
        if args.phase not in ("ram", "decode"):
            tools = [{"type": "function", "function": {"name": "test_kv_lookup", "description": "Test only; do not call.",
                      "parameters": {"type": "object", "properties": {"city": {"type": "string"},
                      "limit": {"type": "integer"}, "options": {"type": "object", "properties": {
                      "alpha": {"type": "boolean"}, "beta": {"type": "boolean"}}}}}}}]
            def reverse_maps(v):
                return {k: reverse_maps(v[k]) for k in reversed(v)} if isinstance(v, dict) else \
                       [reverse_maps(x) for x in v] if isinstance(v, list) else v
            system = "Reference material; do not call tools.\n" + filler(4096, "shared")
            base = [{"role": "system", "content": system}]
            user = {"role": "user", "content": "Reply exactly CACHE_OK."}
            request("prefix_original", base + [user], tools=tools, expect="CACHE_OK")
            request("prefix_reordered_keys", base + [user], tools=reverse_maps(tools), expect="CACHE_OK")
            reused = report["rows"][-1]["engine"].get("reused", 0)
            if reused < 4096:
                raise RuntimeError(f"schema key reordering lost the shared prefix: reused={reused}")
            report.setdefault("cache_checks", {})["schema_reorder_reused"] = reused
            chain = base.copy()
            for i in range(5):
                chain.append({"role": "user", "content": filler(17920 if args.phase == "root" else 768, f"turn{i}") + "\nReply exactly TURN_OK."})
                chain.append(request(f"root_turn_{i}", chain, expect="TURN_OK"))
            request("root_fork", base + [{"role": "user", "content": "New branch: reply exactly FORK_OK."}], expect="FORK_OK")
            report.setdefault("cache_checks", {})["root_fork_reused"] = report["rows"][-1]["engine"].get("reused", 0)
            if args.phase == "root":
                report["status"] = "success"
                return
            if args.phase == "cache":
                sessions = []
                for tag, code in (("cacheA", "741852"), ("cacheB", "963147")):
                    messages = [{"role": "system", "content":
                        f"Session {tag}. SESSION_KEY={code}.\n" + filler(8192, tag) +
                        f"\nSESSION_KEY={code}."}, {"role": "user", "content": "Return only SESSION_KEY."}]
                    messages.append(request(f"{tag}_initial", messages, cap=16, expect=code))
                    sessions.append((tag, code, messages))
                for tag, code, messages in sessions:
                    messages.append({"role": "user", "content": "Return only SESSION_KEY."})
                    request(f"{tag}_restored", messages, cap=16, expect=code)
                    reused = report["rows"][-1]["engine"].get("reused", 0)
                    report["cache_checks"][f"{tag}_restored_reused"] = reused
                    if reused < 8192:
                        raise RuntimeError(f"session {tag} was recomputed: reused={reused}")
                report["status"] = "success"
                return
        for i, prompt in enumerate(cal.PROMPTS[:3]):
            request(f"short_decode_{i}", [{"role": "user", "content": prompt}], cap=args.decode_tokens)
        if args.phase == "decode":
            report["status"] = "success"
            return
        reference = filler(args.long_tokens, "longA")
        # Place exact-match recall data near both ends; context must exceed the smaller VRAM window.
        A = [{"role": "system", "content": "Session A. Remember: SESSION_KEY=741852.\n" + reference +
              "\nEnd reminder: SESSION_KEY=741852."}, {"role": "user", "content": "Return only SESSION_KEY."}]
        A.append(request("long_initial_recall", A, cap=32, expect="741852"))
        B = [{"role": "system", "content": "Session B. SESSION_KEY=963147.\n" + filler(4096, "switchB")},
             {"role": "user", "content": "Return only SESSION_KEY."}]
        B.append(request("switch_B_initial", B, cap=32, expect="963147"))
        for i in range(2):
            A.append({"role": "user", "content": "Return only SESSION_KEY."})
            A.append(request(f"switch_A_recall_{i}", A, cap=32, expect="741852"))
            reused = report["rows"][-1]["engine"].get("reused", 0)
            if reused < args.long_tokens * 0.95:
                raise RuntimeError(f"session A was recomputed instead of restored: reused={reused}")
            report.setdefault("cache_checks", {})[f"switch_A_{i}_reused"] = reused
            A.append({"role": "user", "content": cal.PROMPTS[3 + i]})
            A.append(request(f"long_decode_{i}", A, cap=args.decode_tokens))
            B.append({"role": "user", "content": "Return only SESSION_KEY."})
            B.append(request(f"switch_B_recall_{i}", B, cap=32, expect="963147"))
        report["status"] = "success"
    except Exception as ex:
        report.update(status="failed", error=f"{type(ex).__name__}: {ex}")
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
