[中文](README.md) | English

# maya-glm-opt — a tuned Project Maya fork

This repository is a source-only mirror of **Project Maya** (engine base `v1.1.26`) carrying a
local performance-optimization layer aimed at running **GLM-5.3-Flash** well on a specific 3-GPU hybrid
workstation. It is a personal fork: the upstream engine source is kept intact as a pristine ancestor commit,
and all local work is consolidated into a single "local layer" commit on top — so future upstream releases
can be absorbed with a clean 3-way merge.

Upstream: **Project Maya** by Peasant Smith ([@mw00](https://github.com/mw00)); model quants at
[peasantsmith on Hugging Face](https://huggingface.co/peasantsmith). The engine runs
[GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) (zai-org, MIT) and DeepSeek-V4.1-Flash
(DeepSeek, MIT) on workstation hardware with an expert-tiered memory design.

## What this repository is

- **Two-commit history by design**:
  1. `upstream v1.1.26 pristine` — the exact upstream `v1.1.26` tree (minus binary test fixtures),
     serving as the merge ancestor;
  2. `local layer` — every local change: the engine optimization layer, backports, tests, tooling and
     docs.
- **What is deliberately NOT here**: model weights (GGUF), runtime configs (`maya-*.json`), logs,
  benchmark result sets, `data/` fixtures, build outputs. They are machine-local and regenerable;
  upstream's own `.gitignore` conventions are kept.
- **Not the upstream project**: upstream's README, benchmarks and release announcements live in the
  upstream repository; this fork documents only its own delta.

## The engine in one paragraph

Maya is a Mixture-of-Experts inference engine built model-first: the experts a conversation uses most stay
in VRAM, the next tier lives in pinned RAM, the rest is read in place from NVMe — and everything moves as
you chat. Layers split across one or many GPUs; an MTP block drafts tokens ahead; a serve layer speaks the
OpenAI- and Anthropic-compatible API (with tool calls) and ships a browser chat + live monitor. The decode
path also off-loads cold experts to a CPU lane that computes them on the host.

This fork builds the engine for **Volta (sm_70) through Blackwell (sm_120)** — Volta support is re-enabled
locally (upstream dropped it from the default path).

## The model quantization in use

All tuning and measurements in this fork revolve around one model artifact: **GLM-5.3-Flash** (zai-org,
MIT; 321 B parameters, ~18 B active per token, up to 1 M context) in **unsloth's UD-Q4_K_XL dynamic
4-bit quantization** (`GLM-5.3-Flash-UD-Q4_K_XL.gguf`, from the
[unsloth/GLM-5.3-Flash-GGUF](https://huggingface.co/unsloth/GLM-5.3-Flash-GGUF) repository's UD-Q4_K_XL
folder — 6 split volumes, ~200 GB total, keeping ~93% of the FP8 model's accuracy by Unsloth's figures),
loaded together with the model's own MTP drafting block. The measured figures below (≈30 tokens/s
sustained decode at 8K context, ≈1400 tokens/s prefill, verified past 256K context) all reference this
quantization.

## The local optimization layer

Grouped by concern; the interesting entry points are `include/strata/core/*.hpp` and
`src/core/glm_fast_path.cu`:

- **Expert placement & caching**: LFRU eviction policies for the VRAM and RAM tiers, per-GPU
  device-memory pool caps (per-device `POOL_GB` budgeting), zero-copy small transfers, and dirty-slot
  tracking for speculative windows.
- **CPU lane**: explicit lane planning (`cpu_lane_plan.hpp`), joint calibration of lane width and batch
  shape, a CPU expert pipeline with bitwise parity checks against the GPU reference, and a CPU prefill
  helper.
- **Policy & runtime objects**: cache policy, loop history, window runtime (`glm_cache_policy.hpp`,
  `loop_history.hpp`, `window_runtime.hpp`) — each with its own test.
- **Upstream backports**: `STRATA_GLM_DEFER_CPU=2` — CPU-lane expert deferral on **every** part of a
  multi-GPU split (upstream #722's mode 2; **LOSSY**: it changes sampled answers — drift was measured and
  bounded before adoption; ≈ **+4.6% average decode** on the target rig across five context lengths), and
  the #845 seed fix (a sampled request without a seed now draws a fresh seed per request instead of always
  reusing seed 0).
- **Serve layer**: a locally hardened web UI (chat, multi-chat, monitor, settings), API compatibility
  tests (`serve/test_api_compat.py`), prefix-cache tests and response tooling.
- **Tooling**: KV-cache benchmarking and planning (`tools/benchmark_kv_cache.py`, `run_kv_plan.py`,
  `summarize_kv_cache.py`), local decode exploration (`explore_local_decode.py`), tuning drivers
  (`tune_local_maya*.py`, `tune_ram192.py`), and service control (`tools/stop_maya.ps1`).
- **Docs**: `docs/LOCAL-DECODE-TUNING.md`, `docs/LOCAL-MAYA-XL.md`, `docs/LOCAL-PERFORMANCE.md`,
  `docs/DS4-STRATA-OPTIMIZATION-MAP.md` record the reasoning and measurements behind the layer.

## Building

Prerequisites: MSVC 2022 (x64 developer prompt), CUDA 12.9, Python 3.13 with `cmake` and `ninja`, and a
**pinned, locally patched llama.cpp checkout** at `third_party/llama.cpp` (gitignored — supply your own
path via `STRATA_GGML_DIR`).

```bat
cmake -S . -B build -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_CUDA_ARCHITECTURES=native ^
  -DMAYA_BUILD_DS4=OFF -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF ^
  -DSTRATA_NATIVE_EXPERTS=ON ^
  -DSTRATA_GGML_DIR=<path-to-pinned-llama.cpp>
ninja -C build maya
```

- `native` detects the local GPUs' architectures (here: sm_70 + sm_120).
- Build **only the `maya` target** — see Known quirks.
- The engine executable is referenced by a runtime config's `exe` field; `maya.py` starts the serve
  layer: `python maya.py --config <config.json> --port <port>`.

## Running

The serve layer speaks the OpenAI- and Anthropic-compatible API (chat completions, tool calls, multiple
concurrent requests) and hosts the browser chat + monitor. Runtime configs are machine-local
(gitignored); upstream's `setup.py` generates them and downloads the model quants from Hugging Face.

## Tuning target & measured state

This fork's reference rig: **1× GeForce RTX 5090 D (sm_120) + 2× Tesla V100-class PG500-216 (sm_70)**,
192 GB host RAM; MoE layers split across the three GPUs, int8 KV cache, MTP drafting enabled.
Measured there: ~30 tokens/s sustained decode around an 8K context, ~1400 tokens/s prefill, and verified
operation past 256K context. Your numbers will differ; the engine self-measures and adapts.

## Verification discipline

Every optimization adopted here went through a measured A/B before adoption: an isolated engine instance
on a private port, fixed-seed prompts with needle/checksum probes, a prefill negative control (the change
must not move prefill unless it claims to), and a known noise band (±0.55% on this rig's decode). Features
that do not measure up are reverted. LOSSY knobs additionally record answer-drift before adoption.

## Merging future upstream releases

The pristine ancestor makes upgrades a standard 3-way merge:

```bash
git remote add upstream <upstream-repo-url>   # fetch-only
git fetch upstream --tags
git checkout -b upgrade-vX.Y.Z
git merge vX.Y.Z    # 3-way: merge base = v1.1.26 pristine
```

Conflicts concentrate where the local layer touches files upstream rewrote (`src/core/glm_fast_path.cu`
is the usual suspect). Validate every merged feature with the same A/B battery before adopting.

## Known quirks

- `src/kernels/native_expert_parity.cpp` (a standalone parity tool, not part of `maya.exe`) uses a
  variable-length array that MSVC rejects; building **all** targets fails on it. Build the `maya` target
  only, or fix the tool to use `std::vector`.
- `third_party/llama.cpp` is a gitignored pinned checkout: a fresh clone must supply it before building.
- `bench/micro/*.txt` fixtures are generated (upstream gitignores them); regenerate with the upstream
  tools if the PLE parity tests need them.

## License

This fork carries the upstream license files verbatim (`LICENSE`, `LICENSE.deepseek-v41`). The model
weights have their own terms — GLM-5.3-Flash and DeepSeek-V4.1-Flash are MIT per their publishers, while
Maya's quantized GGUF releases follow the upstream project's terms.
