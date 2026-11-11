#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Offline memo-equality validation (pure CPU, no engine).

Validates the locally spliced PromptMemo/LiteralMemo (production serve layer)
by reusing the upstream test module's data and helpers, but binding every
serve/tokenizer symbol to the LOCAL implementation: the local modules are
imported and cached in sys.modules BEFORE the upstream test module is
imported, so its from-imports resolve to the local code under test.

Role-marker literals are deliberately NEVER written in this file: they are
derived at runtime from the upstream model data (MODELS) and from
svc.literals.  Requires the upstream checkout at D:/project-maya to exist
(data source only; all code paths exercised are local).
"""
import ast
import collections
import copy
import json
import os
import random
import sys
import types
from pathlib import Path

LOCAL = Path(r"D:\project-maya-main")
UPSTREAM = Path(r"D:\project-maya")

sys.path.insert(0, str(LOCAL / "tools"))
sys.path.insert(0, str(LOCAL))

import serve.frontend   # noqa: E402  (local, cached)
import serve.server     # noqa: E402  (local, cached)
import strata_tokenizer # noqa: E402  (local, cached)

sys.path.insert(0, str(UPSTREAM / "serve"))
sys.path.insert(0, str(UPSTREAM))

# The upstream test module cannot be imported wholesale (its header imports
# DeepSeek-only symbols this v1.1.26-lineage tree does not have), so extract
# only the pure data and helper definitions via AST and exec them in a
# namespace that binds the LOCAL tokenizer implementation.
_WANT_FUNCS = {"train_merges", "make_tokenizer", "call", "histories", "fuzz_histories"}
_WANT_ASSIGNS = {"MODELS", "CORPUS", "TOOLS"}
_ns = {"BYTE_TO_UNICODE": strata_tokenizer.BYTE_TO_UNICODE,
       "Tokenizer": strata_tokenizer.Tokenizer,
       "collections": collections, "copy": copy, "json": json, "random": random}
_src = (UPSTREAM / "serve" / "test_prompt_memo.py").read_text(encoding="utf-8")
_keep = []
for _node in ast.parse(_src).body:
    if isinstance(_node, ast.FunctionDef) and _node.name in _WANT_FUNCS:
        _keep.append(_node)
    elif isinstance(_node, ast.Assign) and any(
            isinstance(_t, ast.Name) and _t.id in _WANT_ASSIGNS for _t in _node.targets):
        _keep.append(_node)
exec(compile(ast.Module(body=_keep, type_ignores=[]), str(UPSTREAM / "serve" / "test_prompt_memo.py"), "exec"), _ns)
T = types.SimpleNamespace(**{k: v for k, v in _ns.items()
                             if k in (_WANT_FUNCS | _WANT_ASSIGNS)})

THINK_CLOSE_TAIL = "/" + "think" + ">"   # piece-built so no marker literal appears here


def build_service():
    _path, pre, control, user = T.MODELS["glm5"]
    tok = T.make_tokenizer(pre, control, user)
    tpl = serve.frontend.ChatTemplate(LOCAL / "serve" / "glm5_chat_template.jinja")
    return serve.server.Service(serve.server.MockEngine(tok, "ok"), tok, tpl)


def ids_both(svc, messages, tools, mode="1"):
    """Whole-way ids (memo off) vs incremental ids (memo kept on the service)."""
    req = {"messages": copy.deepcopy(messages)}
    if tools:
        req["tools"] = copy.deepcopy(tools)
    os.environ["MAYA_PROMPT_MEMO"] = "0"
    m, t, kw = serve.frontend.openai_to_messages(copy.deepcopy(req))
    full = svc.render_ids(m, t, kw)
    os.environ["MAYA_PROMPT_MEMO"] = mode
    m, t, kw = serve.frontend.openai_to_messages(copy.deepcopy(req))
    memo = svc.render_ids(m, t, kw)
    os.environ.pop("MAYA_PROMPT_MEMO", None)
    return full, memo


def main():
    svc = build_service()
    lits = sorted(svc.literals)
    assert lits, "tokenizer must carry special literals"
    lit = next((s for s in lits if ("user" in s.lower() or "~b]" in s or "im_start" in s)), lits[0])
    close = next((s for s in lits if s.endswith(THINK_CLOSE_TAIL)), lits[-1])
    scripted = list(T.histories(lit, close))
    n_run = 0
    fail_s = 0
    for k, (messages, tools) in enumerate(scripted):
        full, memo = ids_both(svc, messages, tools)
        n_run += 1
        fail_s += (memo != full)
    rng = random.Random(813)
    fuzz = list(T.fuzz_histories(rng, lits[:6], 40))
    fail_f = 0
    for k, messages in enumerate(fuzz):
        full, memo = ids_both(svc, messages, None)
        n_run += 1
        fail_f += (memo != full)
    ran = svc._prompt_memo.usable()   # after render calls: the memo must exist and run, not fall back
    print(f"scripted histories: {len(scripted) - fail_s} ok / {len(scripted)} cases ({fail_s} failures)")
    print(f"fuzz cases: {len(fuzz) - fail_f} ok / {len(fuzz)} cases ({fail_f} failures)")
    print(f"total: {n_run - fail_s - fail_f} ok / {n_run} cases")
    print(f"memo ran (usable): {ran}")
    ok_all = (fail_s == 0 and fail_f == 0 and ran)
    print("RESULT: " + ("ALL PASS" if ok_all else "FAILURES PRESENT"))
    return 1 if not ok_all else 0


if __name__ == "__main__":
    sys.exit(main())
