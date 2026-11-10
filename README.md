[English](README.en.md) | 中文

# maya-glm-opt — GLM-5.3-Flash 本地优化 fork

本仓库是 **Project Maya**（引擎基座 `v1.1.26`）的 source-only 镜像，带有一层让
**GLM-5.3-Flash** 在三卡混合工作站上跑得更好的本地性能优化。它是个人使用的 fork：
上游引擎源码以“纯净祖先提交”原样保留，所有本地改动收敛为顶上的单个“本地层”提交——
将来同步上游新版本时可以做干净的三路合并。

上游项目：Peasant Smith（[@mw00](https://github.com/mw00)）的 Project Maya，模型量化发布在
[Hugging Face 的 peasantsmith 主页](https://huggingface.co/peasantsmith)。引擎以“专家分层驻留”
的设计把 [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash)（zai-org，MIT）与
DeepSeek-V4.1-Flash（DeepSeek，MIT）跑在工作站硬件上。

## 本仓库是什么

- **两段式提交设计**：
  1. `upstream v1.1.26 pristine` — 上游 `v1.1.26` 归档树（去掉二进制 fixture），作为合并祖先；
  2. `local layer` — 全部本地改动：引擎优化层、回移补丁、测试、工具与文档。
- **刻意不入库的内容**：模型权重（GGUF）、运行配置（`maya-*.json`）、日志、批测产物、
  `data/` fixture、构建输出。它们是机器本地的、可再生的；沿用上游自己的 `.gitignore` 约定。
- **这不是上游项目**：上游的 README、基准与发布公告在上游仓库里；本仓库只记录自己的增量。

## 引擎一页话

Maya 是一个“模型优先”的 MoE 推理引擎：对话最常用的专家常驻显存，次一级驻留内存，
其余直接从 NVMe 原位读取，并随对话流动换入换出。层可拆到单卡或多卡；MTP 模块负责超前起草；
serve 层提供 OpenAI/Anthropic 兼容 API（含工具调用）与浏览器聊天页 + 实时监视器。
decode 路径还会把冷专家交给 CPU lane 在主机侧计算。

本 fork 把引擎编译目标覆盖 **Volta (sm_70) 到 Blackwell (sm_120)**——其中 Volta 支持是本地
重新放行的（上游默认路径已移除）。

## 面向的模型量化

本 fork 的调优与全部实测围绕一个模型产物展开：**GLM-5.3-Flash**（zai-org，MIT；321B 参数、
约 18B 每 token 激活、最高 1M 上下文）的 **unsloth UD-Q4_K_XL 动态 4-bit 量化**
（`GLM-5.3-Flash-UD-Q4_K_XL.gguf`，来自
[unsloth/GLM-5.3-Flash-GGUF](https://huggingface.co/unsloth/GLM-5.3-Flash-GGUF) 仓库的
UD-Q4_K_XL 目录，分 6 卷、共约 200 GB，官方口径保留约 93% 的 FP8 精度），
随模型自带的 MTP 起草模块一起加载。本文中的实测数据（8K 上下文持续 decode 约 30 tokens/s、
prefill 约 1400 tokens/s、256K+ 上下文验证可跑）均以该量化为基准。

## 本地优化层

按关注点分组；入口主要在 `include/strata/core/*.hpp` 与 `src/core/glm_fast_path.cu`：

- **专家放置与缓存**：VRAM 与 RAM 层的 LFRU 淘汰、按卡的显存池上限（逐卡 `POOL_GB` 预算）、
  小传输零拷贝、投机窗口的脏槽位跟踪。
- **CPU 通道**：通道规划（`cpu_lane_plan.hpp`）、通道宽度与批形状的联合校准、带逐位对拍校验的
  CPU 专家流水线、CPU 预填充辅助。
- **策略与运行时**：缓存策略、循环历史、窗口运行时（`glm_cache_policy.hpp`、`loop_history.hpp`、
  `window_runtime.hpp`）——各自附带单元测试。
- **上游回移**：`STRATA_GLM_DEFER_CPU=2`——多卡分片的**每一段**都做 CPU 专家延迟提交
  （上游 #722 的模式 2；**有损**——会改变采样答案，采纳前实测了漂移幅度与边界；目标机型上
  五个上下文长度平均 decode ≈ **+4.6%**）；以及 #845 种子修复（无 seed 的采样请求改为每次
  抽取新种子，而不是永远复用 seed 0）。
- **服务层**：本地强化的网页界面（聊天、多会话、监视器、设置）、API 兼容性测试
  （`serve/test_api_compat.py`）、前缀缓存测试与响应处理工具。
- **工具**：KV 缓存基准与规划（`tools/benchmark_kv_cache.py`、`run_kv_plan.py`、
  `summarize_kv_cache.py`）、本地 decode 探索（`explore_local_decode.py`）、调优驱动
  （`tune_local_maya*.py`、`tune_ram192.py`）、服务控制（`tools/stop_maya.ps1`）。
- **文档**：`docs/LOCAL-DECODE-TUNING.md`、`docs/LOCAL-MAYA-XL.md`、`docs/LOCAL-PERFORMANCE.md`、
  `docs/DS4-STRATA-OPTIMIZATION-MAP.md` 记录了本层的推理依据与实测数据。

## 构建

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

- `native` 自动探测本机架构（参考机型上是 sm_70 + sm_120）。
- **只编 `maya` 目标**——见“已知怪癖”。
- 引擎可执行文件由运行配置的 `exe` 字段指向；`maya.py` 启动服务层：
  `python maya.py --config <config.json> --port <port>`。

## 运行

服务层提供 OpenAI/Anthropic 兼容 API（chat completions、工具调用、多请求并发）并托管浏览器
聊天页与监视器。运行配置是机器本地的（不入库）；上游的 `setup.py` 负责生成配置并从
Hugging Face 下载模型量化。

## 调优目标与实测状态

本 fork 的参考机型：**1× GeForce RTX 5090 D (sm_120) + 2× Tesla V100 级 PG500-216 (sm_70)**，
192 GB 内存；MoE 层拆到三卡，int8 KV 缓存，开启 MTP 起草。实测：8K 上下文附近持续 decode
约 30 tokens/s，prefill 约 1400 tokens/s，256K 以上上下文验证可跑。你的数字会不同；
引擎会自测量并自适应（上游特性）。

## 验证纪律

这里采纳的每一项优化都先经过实测 A/B：私有端口上的隔离引擎实例、固定种子提示 +
召回/校验探针、prefill 阴性对照（改动不许碰 prefill，除非它声称如此）、已知噪声带
（本机 decode ±0.55%）。不达标的特性一律回退；有损开关在采纳前还要记录答案漂移。

## 合并上游新版本

纯净祖先让升级成为标准三路合并：

```bash
git remote add upstream <upstream-repo-url>   # 只 fetch
git fetch upstream --tags
git checkout -b upgrade-vX.Y.Z
git merge vX.Y.Z    # 三路合并：合并基 = v1.1.26 纯净树
```

冲突集中在本地层与上游重写相交的文件上（`src/core/glm_fast_path.cu` 是常客）。每个合并进来的
特性都要用同一套 A/B 流程验证后再采纳。

## 已知怪癖

- `src/kernels/native_expert_parity.cpp`（独立对拍工具，不属于 `maya.exe`）用了 MSVC 不接受的
  变长数组；**全量**构建会在它上面失败。只编 `maya` 目标，或把该工具改成 `std::vector`。
- `third_party/llama.cpp` 是不入库的钉住检出：新克隆必须先提供它才能构建。
- `bench/micro/*.txt` fixture 是生成物（上游同样不入库）；PLE 对拍测试需要时用上游工具再生成。

## 许可

本 fork 原样保留上游许可证文件（`LICENSE`、`LICENSE.deepseek-v41`）。模型权重遵循各自的条款：
GLM-5.3-Flash 与 DeepSeek-V4.1-Flash 按发布方为 MIT，Maya 量化 GGUF 遵循上游项目的发布条款。
