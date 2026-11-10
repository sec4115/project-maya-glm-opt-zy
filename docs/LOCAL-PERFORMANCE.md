# Local GLM performance controls

The local source keeps the fixed-SHA upstream #400 checkpoint-order fix: a restored conversation gets its turn
checkpoint after slot restoration and checkpoint pruning. It is active whenever the existing turn-checkpoint
policy applies; it does not change cache capacities.

Experimental controls use the normal MAYA_/STRATA_ aliases and can be set per isolated process:

| Control | Default | Purpose |
|---|---|---|
| MAYA_GLM_CPU_CAL_OVERRIDE[n]=1 | 0 | With CPU_BATCH_CAL or CPU_JOINT_CAL requested, explicitly disregard this device's manual CPU_PLAN/PCIE_SHARE for calibration. Without this override, manual settings remain authoritative and a skip reason is logged. |
| MAYA_GLM_BOUNDARY_INCREMENTAL=1 | 0 | Process changed RAM slots instead of scanning every slot at every boundary. A full sweep still runs every 256 boundaries. Free-slot counts are maintained on state writes. |
| MAYA_GLM_BOUNDARY_CHECK=1 | 0 | Before incremental maintenance, verify tracked transitions, invalid held-slot tracking and free counts against a full diagnostic scan. Use for correctness checks, not performance timings. |
| MAYA_GLM_BOUNDARY_TIMING=1 | 0 | Log cumulative boundary waiting, RAM processing and total time every 128 boundaries. |
| MAYA_GLM_CPU_EXPERT_PIPE=1 | 0 | On native GGUF CPU routes with at most eight experts, schedule down rows as each complete expert's gate/up and quantization become ready. Final expert reduction order is unchanged. EXL3 retains its original path. |
| MAYA_GLM_CPU_EXPERT_CHECK=1 | 0 | With EXPERT_PIPE, recompute each call using the old scheduler and require bitwise output equality. A mismatch terminates the test process. This doubles work and is unsuitable for timing. |
| MAYA_GLM_PREFILL_PIPE_CHUNK=N | unset | Cap the existing multi-GPU prefill chunk at N (N >= 256), within the configured allocation ceiling. Explicit caller-forced chunks take precedence. Smaller chunks can increase expert transfers; measure before adoption. |

Calibration override applies only when batch or joint calibration was explicitly requested. It does not overwrite
the user's JSON or change thread counts. The startup records final per-device plan source and settings.

Build the isolated candidate and run `glm_cpu_schedule_test` for dependency scheduling and dirty-slot checks, then
perform real model checks with the diagnostic switches enabled. Compare performance with checks disabled, using
the same input token hash, configuration, warmup and output limit. Keep session slots and logs isolated.

The daily binary is not replaced by an isolated build. Source changes need a newly compiled binary, and an already
running manually started Maya instance must be restarted by the user after an approved binary/config activation.

The 2026-10-30 XL tests and activation record are in
`bench/results/implement-20261030-p1-p4/REPORT.md`. The checkpoint-order fix restored 12K-token reuse after
editing a restored turn. The other controls remain opt-in: the single-sample tests did not establish a stable
decode improvement, and smaller chunks traded faster prefill for slower decode. See the raw measurements
before changing a daily configuration.


2026-11-03 四卡 XL 实测：12线程两轮加权decode 33.88/33.40 tok/s，10线程34.43、14线程33.85；输出轨迹与实际槽数不同，未证明稳定的完整请求收益，保留12。GPU0短prefill阈值768未通过完整验收，保留512。最终约50K分支恢复与召回通过；生产JSON/二进制均未修改。原始结果和限制见 `bench/results/tune-20261103/REPORT.md`。

### 11-04 审查缺口修复

常规 VRAM 淘汰与全 CPU 专家路径的后台替换共用同一个策略比较器。后台选择保留真实频次，晋升仍需满足原有热度门槛及槽位资格。

仪表盘从 `/health` 的 `capabilities` 判断是否显示模型管理、费用统计、Turbo 与思考预算编辑。当前服务提供空能力表，已有的 Model 设置继续可用。

单个恢复流的已保存 SSE 帧预算为 32 MiB，含估算对象开销及终止帧预留。超限取消生成并返回错误，已发布帧的续传索引保持有效。分词 piece 和长片段缓存各使用 16 MiB 估算预算，单项上限分别为 1 MiB 和 4 MiB。超大项仍正常编码。

原生构建已完成，Python mock 验证覆盖续传回放、超限取消和分词大项绕过。四卡复测已覆盖后台替换和约 50K 分支召回，两组各 12 条请求成功。六次续写总耗时 24.56 → 24.79 秒。单轮速度差与验证范围见 `bench/results/review-fixes-20261104/RETEST.md`。
