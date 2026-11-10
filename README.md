# maya-glm-opt — a tuned Project Maya fork · GLM-5.3-Flash 本地优化 fork

**English** — This repository is a source-only mirror of **Project Maya** (engine base `v1.1.26`) carrying a
local performance-optimization layer aimed at running **GLM-5.3-Flash** well on a specific 3-GPU hybrid
workstation. It is a personal fork: the upstream engine source is kept intact as a pristine ancestor commit,
and all local work is consolidated into a single "local layer" commit on top — so future upstream releases
can be absorbed with a clean 3-way merge.

**中文** — 本仓库是 **Project Maya**（引擎基座 `v1.1.26`）的 source-only 镜像，带有一层让
**GLM-5.3-Flash** 在三卡混合工作站上跑得更好的本地性能优化。它是个人使用的 fork：
上游引擎源码以“纯净祖先提交”原样保留，所有本地改动收敛为顶上的单个“本地层”提交——
将来同步上游新版本时可以做干净的三路合并。

Upstream: **Project Maya** by Peasant Smith ([@mw00](https://github.com/mw00)); model quants at
[peasantsmith on Hugging Face](https://huggingface.co/peasantsmith). The engine runs
[GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) (zai-org, MIT) and DeepSeek-V4.1-Flash
(DeepSeek, MIT) on workstation hardware with an expert-tiered memory design.
上游项目为 Peasant Smith 的 Project Maya，模型量化发布在其 Hugging Face 主页。引擎以
“专家分层驻留”的设计把 GLM-5.3-Flash 与 DeepSeek-V4.1-Flash 跑在工作站硬件上。

---

## What this repository is / 本仓库是什么

- **Two-commit history by design / 两段式提交设计**:
  1. `upstream v1.1.26 pristine` — the exact upstream `v1.1.26` tree (minus binary test fixtures),
     serving as the merge ancestor / 上游 v1.1.26 归档树（去掉二进制 fixture），作为合并祖先；
  2. `local layer` — every local change: the engine optimization layer, backports, tests, tooling and
     docs / 全部本地改动：引擎优化层、回移补丁、测试、工具与文档。
- **What is deliberately NOT here / 刻意不入库的内容**: model weights (GGUF), runtime configs
  (`maya-*.json`), logs, benchmark result sets, `data/` fixtures, build outputs. They are machine-local
  and regenerable; upstream's own `.gitignore` conventions are kept.
  模型权重、运行配置、日志、批测产物、`data/` fixture、构建产物都不入库——它们是机器本地的、
  可再生的；沿用上游自己的 .gitignore 约定。
- **Not the upstream project / 这不是上游项目**: upstream's README, benchmarks and release
  announcements live in the upstream repository; this fork documents only its own delta.
  上游的 README、基准与发布公告在上游仓库里；本仓库只记录自己的增量。

## The engine in one paragraph / 引擎一页话

Maya is a Mixture-of-Experts inference engine built model-first: the experts a conversation uses most stay
in VRAM, the next tier lives in pinned RAM, the rest is read in place from NVMe — and everything moves as
you chat. Layers split across one or many GPUs; an MTP block drafts tokens ahead; a serve layer speaks the
OpenAI- and Anthropic-compatible API (with tool calls) and ships a browser chat + live monitor. The decode
path also off-loads cold experts to a CPU lane that computes them on the host.
Maya 是一个“模型优先”的 MoE 推理引擎：对话最常用的专家常驻显存，次一级驻留内存，其余直接从
NVMe 原位读取，并随对话流动换入换出。层可拆到单卡或多卡；MTP 模块负责超前起草；serve 层提供
OpenAI/Anthropic 兼容 API（含工具调用）与浏览器聊天页 + 实时监视器。decode 路径还会把冷专家
交给 CPU lane 在主机侧计算。

This fork builds the engine for **Volta (sm_70) through Blackwell (sm_120)** — Volta support is re-enabled
locally (upstream dropped it from the default path).
本 fork 把引擎编译目标覆盖 **Volta (sm_70) 到 Blackwell (sm_120)**——其中 Volta 支持是本地重新
放行的（上游默认路径已移除）。

## The local optimization layer / 本地优化层

Grouped by concern; the interesting entry points are `include/strata/core/*.hpp` and
`src/core/glm_fast_path.cu` / 按关注点分组；入口主要在 `include/strata/core/*.hpp` 与
`src/core/glm_fast_path.cu`:

- **Expert placement & caching / 专家放置与缓存**: LFRU eviction policies for the VRAM and RAM tiers,
  per-GPU device-memory pool caps (per-device `POOL_GB` budgeting), zero-copy small transfers, and
  dirty-slot tracking for speculative windows / VRAM 与 RAM 层的 LFRU 淘汰、按卡的显存池上限
  （逐卡 `POOL_GB` 预算）、小传输零拷贝、投机窗口的脏槽位跟踪。
- **CPU lane / CPU 通道**: explicit lane planning (`cpu_lane_plan.hpp`), joint calibration of lane width
  and batch shape, a CPU expert pipeline with bitwise parity checks against the GPU reference, and a
  CPU prefill helper / 通道宽度与批形状的联合校准、带逐位对拍校验的 CPU 专家流水线、CPU 预填充辅助。
- **Policy & runtime objects / 策略与运行时**: cache policy, loop history, window runtime
  (`glm_cache_policy.hpp`, `loop_history.hpp`, `window_runtime.hpp`) — each with its own test
  / 各自附带单元测试。
- **Upstream backports / 上游回移**: `STRATA_GLM_DEFER_CPU=2` — CPU-lane expert deferral on **every**
  part of a multi-GPU split (upstream #722's mode 2; **LOSSY**: it changes sampled answers — drift was
  measured and bounded before adoption; ≈ **+4.6% average decode** on the target rig across five
  context lengths), and the #845 seed fix (a sampled request without a seed now draws a fresh seed per
  request instead of always reusing seed 0) / 多卡分片的每一段都做 CPU 专家延迟提交（上游 #722 的
  模式 2；**有损**——会改变采样答案，采纳前实测了漂移幅度与边界），以及 #845 种子修复。
- **serve layer / 服务层**: a locally hardened web UI (chat, multi-chat, monitor, settings), API
  compatibility tests (`serve/test_api_compat.py`), prefix-cache tests and response tooling
  / 本地强化的网页界面与 API 兼容性测试、前缀缓存测试、响应处理工具。
- **Tooling / 工具**: KV-cache benchmarking and planning (`tools/benchmark_kv_cache.py`,
  `run_kv_plan.py`, `summarize_kv_cache.py`), local decode exploration (`explore_local_decode.py`),
  tuning drivers (`tune_local_maya*.py`, `tune_ram192.py`), and service control (`tools/stop_maya.ps1`).
- **Docs / 文档**: `docs/LOCAL-DECODE-TUNING.md`, `docs/LOCAL-MAYA-XL.md`, `docs/LOCAL-PERFORMANCE.md`,
  `docs/DS4-STRATA-OPTIMIZATION-MAP.md` record the reasoning and measurements behind the layer
  / 这些文档记录了本层的推理依据与实测数据。

## Building / 构建

Prerequisites: MSVC 2022 (x64 developer prompt), CUDA 12.9, Python 3.13 with `cmake` and `ninja`, and a
**pinned, locally patched llama.cpp checkout** at `third_party/llama.cpp` (gitignored — supply your own
path via `STRATA_GGML_DIR`).
前置：MSVC 2022（x64 开发者提示符）、CUDA 12.9、带 cmake/ninja 的 Python，以及
`third_party/llama.cpp` 处**已钉住并打过补丁的 llama.cpp 检出**（不入库——用 `STRATA_GGML_DIR`
指定你的路径）。

```bat
cmake -S . -B build -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_CUDA_ARCHITECTURES=native ^
  -DMAYA_BUILD_DS4=OFF -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF ^
  -DSTRATA_NATIVE_EXPERTS=ON ^
  -DSTRATA_GGML_DIR=<path-to-pinned-llama.cpp>
ninja -C build maya
```

- `native` detects the local GPUs' architectures (here: sm_70 + sm_120) / `native` 自动探测本机架构。
- Build **only the `maya` target** — see Known quirks / 只编 `maya` 目标——见“已知怪癖”。
- The engine executable is referenced by a runtime config's `exe` field; `maya.py` starts the serve
  layer: `python maya.py --config <config.json> --port <port>` / 引擎可执行文件由运行配置的
  `exe` 字段指向；`maya.py` 启动服务层。

## Running / 运行

The serve layer speaks the OpenAI- and Anthropic-compatible API (chat completions, tool calls, multiple
concurrent requests) and hosts the browser chat + monitor. Runtime configs are machine-local
(gitignored); upstream's `setup.py` generates them and downloads the model quants from Hugging Face.
服务层提供 OpenAI/Anthropic 兼容 API（chat completions、工具调用、多请求并发）并托管浏览器聊天页
与监视器。运行配置是机器本地的（不入库）；上游的 `setup.py` 负责生成配置并从 Hugging Face
下载模型量化。

## Tuning target & measured state / 调优目标与实测状态

This fork's reference rig: **1× GeForce RTX 5090 D (sm_120) + 2× Tesla V100-class PG500-216 (sm_70)**,
192 GB host RAM; MoE layers split across the three GPUs, int8 KV cache, MTP drafting enabled.
Measured there: ~30 tokens/s sustained decode around an 8K context, ~1400 tokens/s prefill, and verified
operation past 256K context. Your numbers will differ; the engine self-measures and adapts.
本 fork 的参考机型：**1× GeForce RTX 5090 D (sm_120) + 2× Tesla V100 级 PG500-216 (sm_70)**，
192 GB 内存；MoE 层拆到三卡，int8 KV 缓存，开启 MTP 起草。实测：8K 上下文附近持续 decode
约 30 tokens/s，prefill 约 1400 tokens/s，256K 以上上下文验证可跑。你的数字会不同；
引擎会自测量并自适应（上游特性）。

## Verification discipline / 验证纪律

Every optimization adopted here went through a measured A/B before adoption: an isolated engine instance
on a private port, fixed-seed prompts with needle/checksum probes, a prefill negative control (the change
must not move prefill unless it claims to), and a known noise band (±0.55% on this rig's decode). Features
that do not measure up are reverted. LOSSY knobs additionally record answer-drift before adoption.
这里采纳的每一项优化都先经过实测 A/B：私有端口上的隔离引擎实例、固定种子提示 + 召回/校验探针、
prefill 阴性对照（改动不许碰 prefill，除非它声称如此）、已知噪声带（本机 decode ±0.55%）。
不达标的特性一律回退；有损开关在采纳前还要记录答案漂移。

## Merging future upstream releases / 合并上游新版本

The pristine ancestor makes upgrades a standard 3-way merge / 纯净祖先让升级成为标准三路合并：

```bash
git remote add upstream <upstream-repo-url>   # fetch-only / 只 fetch
git fetch upstream --tags
git checkout -b upgrade-vX.Y.Z
git merge vX.Y.Z    # 3-way: merge base = v1.1.26 pristine / 合并基 = v1.1.26 纯净树
```

Conflicts concentrate where the local layer touches files upstream rewrote (`src/core/glm_fast_path.cu`
is the usual suspect). Validate every merged feature with the same A/B battery before adopting.
冲突集中在本地层与上游重写相交的文件上（`src/core/glm_fast_path.cu` 是常客）。每个合并进来的
特性都要用同一套 A/B 流程验证后再采纳。

## Known quirks / 已知怪癖

- `src/kernels/native_expert_parity.cpp` (a standalone parity tool, not part of `maya.exe`) uses a
  variable-length array that MSVC rejects; building **all** targets fails on it. Build the `maya` target
  only, or fix the tool to use `std::vector`.
  `native_expert_parity.cpp`（独立对拍工具，不属于 `maya.exe`）用了 MSVC 不接受的变长数组；
  **全量**构建会在它上面失败。只编 `maya` 目标，或把该工具改成 `std::vector`。
- `third_party/llama.cpp` is a gitignored pinned checkout: a fresh clone must supply it before building.
  `third_party/llama.cpp` 是不入库的钉住检出：新克隆必须先提供它才能构建。
- `bench/micro/*.txt` fixtures are generated (upstream gitignores them); regenerate with the upstream
  tools if the PLE parity tests need them.
  `bench/micro/*.txt` fixture 是生成物（上游同样不入库）；PLE 对拍测试需要时用上游工具再生成。

## License / 许可

This fork carries the upstream license files verbatim (`LICENSE`, `LICENSE.deepseek-v41`). The model
weights have their own terms — GLM-5.3-Flash and DeepSeek-V4.1-Flash are MIT per their publishers, while
Maya's quantized GGUF releases follow the upstream project's terms.
本 fork 原样保留上游许可证文件（`LICENSE`、`LICENSE.deepseek-v41`）。模型权重遵循各自的条款：
GLM-5.3-Flash 与 DeepSeek-V4.1-Flash 按发布方为 MIT，Maya 量化 GGUF 遵循上游项目的发布条款。
