#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prompt-memo speed A/B (pure CPU, real production pack tokenizer).

Measures serve-side prompt preparation wall time per request for a realistic
multi-turn history, whole-way (memo off, the pre-memo behaviour) vs the memo
(cold first request / warm follow-up).  No role-marker literals appear here.
"""
import ast
import collections
import copy
import json
import os
import statistics
import sys
import time
import types
from pathlib import Path

LOCAL = Path(r"D:\project-maya-main")
UPSTREAM = Path(r"D:\project-maya")
sys.path.insert(0, str(LOCAL / "tools"))
sys.path.insert(0, str(LOCAL))

import serve.frontend   # noqa: E402
import serve.server     # noqa: E402
import strata_tokenizer  # noqa: E402

_WANT_FUNCS = {"call"}
_ns = {"json": json}
_src = (UPSTREAM / "serve" / "test_prompt_memo.py").read_text(encoding="utf-8")
_keep = [n for n in ast.parse(_src).body
         if isinstance(n, ast.FunctionDef) and n.name in _WANT_FUNCS]
exec(compile(ast.Module(body=_keep, type_ignores=[]), "upstream_call", "exec"), _ns)
T_call = _ns["call"]

TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                           "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
         {"type": "function", "function": {"name": "run", "description": "Run a command.",
                                           "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]

TOK = strata_tokenizer.Tokenizer.from_dir(r"D:/AI/lla_models/gguf/Maya-XL/pack/tokenizer")


def tool_payload(kb: float) -> str:
    code = ("def read_file(path):\n    with open(path, encoding='utf-8') as f:\n        return f.read()\n"
            "for i in range(10):\n    print(i, 'value', i * 2)  # scan loop\n"
            "results = {'latency_ms': 12.5, 'tokens': 18432, 'path': 'src/engine/kernel.cu'}\n")
    prose = ("The scan covered the full workspace and found the hot loop in the mixer kernel. "
             "Latency improved after the reorder, but the tail batch still shows jitter around the boundary. "
             "日本語のテキストも混ぜておく: 数値は 1234567 89.5, emoji 🚀✓, café naïve Ünïcödé. ")
    unit = code + prose
    return unit * max(1, int(kb * 1024 / len(unit.encode("utf-8"))))


def build_history(target_kb: int, tail: bool):
    """sys + 4 tool rounds with sizeable results (+ optional small follow-up user tail)."""
    per = (target_kb * 1024 - 2000) / 4 / 1024
    convo = [{"role": "system", "content": "You are a careful coding agent. Work in small steps."}]
    for i in range(4):
        convo.append({"role": "user", "content": f"Round {i}: inspect the kernel and report."})
        convo.append({"role": "assistant", "content": "",
                      "reasoning_content": f"Reading the file for round {i}.",
                      "tool_calls": [T_call(f"c{i}", "read_file", {"path": f"src/m{i}.py"})]})
        convo.append({"role": "tool", "tool_call_id": f"c{i}", "content": tool_payload(per)})
        convo.append({"role": "assistant", "content": f"Round {i} done: the hot loop sits in the mixer tail; "
                                                      f"the boundary jitter needs a second pass."})
    convo.append({"role": "user", "content": "Thanks. Now run the tests and summarize."})
    if tail:
        convo.append({"role": "assistant", "content": "All 390 pass; the boundary fix lands next."})
        convo.append({"role": "user", "content": "Good. What about the prefetch overlap, any risk there?"})
    return convo


def prep_ms(svc, convo, reps=5):
    ts = []
    for _ in range(reps):
        m, t, kw = serve.frontend.openai_to_messages(copy.deepcopy({"messages": copy.deepcopy(convo), "tools": TOOLS}))
        t0 = time.perf_counter()
        svc.render_ids(m, t, kw)
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


def fresh_svc():
    tpl = serve.frontend.ChatTemplate(LOCAL / "serve" / "glm5_chat_template.jinja")
    return serve.server.Service(serve.server.MockEngine(TOK, "ok"), TOK, tpl)


def run(convo, mode):
    os.environ["MAYA_PROMPT_MEMO"] = mode
    try:
        return prep_ms(fresh_svc(), convo)
    finally:
        os.environ.pop("MAYA_PROMPT_MEMO", None)


def main():
    print(f"tokenizer: real production pack ({type(TOK).__name__})")
    print(f"{'history':>9} | {'whole (memo off)':>16} | {'memo cold':>9} | {'memo warm follow-up':>19} | {'warm saves':>10}")
    for kb in (25, 100, 200):
        base = build_history(kb, tail=False)
        follow = build_history(kb, tail=True)
        # warm the memo on `base`, then time the follow-up render on `follow` (base + small tail)
        os.environ["MAYA_PROMPT_MEMO"] = "1"
        svc = fresh_svc()
        m, t, kw = serve.frontend.openai_to_messages(copy.deepcopy({"messages": copy.deepcopy(base), "tools": TOOLS}))
        svc.render_ids(m, t, kw)                       # warm-up render builds the memo
        m, t, kw = serve.frontend.openai_to_messages(copy.deepcopy({"messages": copy.deepcopy(follow), "tools": TOOLS}))
        t0 = time.perf_counter()
        svc.render_ids(m, t, kw)
        warm = (time.perf_counter() - t0) * 1000       # single-shot: the memo must not be disturbed by reps
        os.environ.pop("MAYA_PROMPT_MEMO", None)
        whole = run(follow, "0")
        cold = run(base, "1")
        save = (1 - warm / whole) * 100 if whole else 0
        print(f"{kb:>7}KB | {whole:>14.1f}ms | {cold:>7.1f}ms | {warm:>17.1f}ms | {save:>8.1f}%")
    print()
    print("context: a follow-up turn decoding ~200 tokens at ~30 tok/s is ~6.5s of engine time;")
    print("the warm column is the serve-side prep cost the memo leaves on that request.")


if __name__ == "__main__":
    main()
