# ds4-strata 优化历史链与 Maya 对照

核对时间：2026-11-03。ds4-strata 只读；本文件写入 Maya 工作区。基于实际报告、当前启动配置与源码，不把报告中的早期“待测”当最终状态，也不把源码存在当部署或稳定收益。

## 当前实际路径

- ds4-strata V4.1：`D:/AIProjects/ds4-strata/START-DS41-Q4.bat` → ds41.py → ds41.json → `build-v41-daily/strata.exe`，cwd 为 `Abyss-1.3.56`。当前 SHA256 `65fe309a35450fb4e08f353c7a720b9ee76624dcd1219fa160df839a15c823df` 与 10-30 模型专属优化最终构建一致。旧记忆中的 abyss-source 已不在当前目录，不能继续按旧路径找代码。
- 当前 Maya：`run-maya-maya-xl.bat` → maya.py → maya-maya-xl.json → build/maya.exe。当前为1.1.26基座加本地补丁，前端来自1.1.50；不等于已升级1.1.50引擎。
- 模型不同：ds4 V4.1 为40层、5120/2304 MXFP4、384专家/top6、混合压缩共享KV与Engram；Maya GLM 为4096/2048、288专家/top8、当前native Q4_K/Q5_K等混合格式与MTP。不能搬用固定几何、压缩KV掩码、草稿权重或预算数值。

## 历史主链（后行覆盖前行的日常选择）

|阶段|问题与调整|验证/采用结论|证据文件（均在D:/AIProjects/ds4-strata）|
|---|---|---|---|
|10-15～18 V4基础调优|native experts、共享CPU池、线程/放置/专家RAM、Windows PAUSE与亲和性实验|一部分采用；10-18同模型ABBA旧22.39、新21.67 tok/s，不能宣传PAUSE稳定提速|TUNING.md、CPU-WORKER-TUNING.md|
|10-22 选择性迁移Abyss1.3.44/Maya1.1.21|mapped token/表更新/embedding行绕过大DMA队列、DSML参数扫描、编译器切换fresh|真实CUDA局部数值与API验证；后来192G机器重新测RAM预算。并非整版升级，也不是单项收益|UPSTREAM-IMPROVEMENTS.md|
|10-26 V4→V4.1|核对ISA/可见GPU/模型格式；256K容量、批量prefill、前缀快照、ngram适配|早期验收后发现无复用306-token prefill非有限值，早期“通过”并非最终正确性证明|V41-TUNING.md、V41-CONTEXT256-PREFILL.md|
|10-26～27 prefill依赖裁剪/内存选择|长提示按真实依赖跳过；RAM目标/arena、prefill512或32768、近似路径对照|严格裁剪32K约398.1→509.9 tok/s；不能忽略短输入及decode权衡。日常选择由后续FAST报告覆盖|V41-PREFILL-EXPERIMENTS-20261026.md、V41-DAILY-BEST-20261027.md、V41-FAST-DAILY-20261027.md|
|10-28 RAM完整驻留|pageable backing+pinned staging、no-shrink、按完整专家槽拆块、不同卡实际锁页资格|解决单大块锁页失败导致缩容；普通RAM不等于VirtualLock或保证常驻。旧目标140/142后被146/148替代|V41-RAM-STAGED-20261028.md、V41-RAM-NO-SHRINK-20261028.md、V41-SLOT-CHUNKS-20261028.md|
|10-28～29 HC5120|按设备/线程/宽度判断occupancy；将CPU结果汇合延至HC消费|四卡491904浮点数容差通过；模型输出差异不证明逐logit等价；单轮整机收益不稳定|V41-HC5120-NUMERIC-20261029.md、V41-HC5120-SPEED-20261029.md、V41-DAILY-PINNED-HC-20261029.md|
|10-29 15项性能修复|流式工具分块、KMP、MCP索引、BPE堆、缓存字节上限、服务并发/预算、UI增量扫描；RAM与Engram双缓冲|服务/CPU局部收益有证据；两项GPU实验虽单次prefill约+15%，staging控制组未走pageable路径，不足归因。后来按要求接入，不等于稳定提速已证实|PERFORMANCE-FIXES-20261029.md|
|10-29 跨块prefill流水|每卡线程、有界handoff、保留段内因果顺序|32985输入跨两块，单次542.4→687.0 tok/s、输出一致；HC/15项修复组合不能算独立倍率。后续日常启用|V41-CROSS-CHUNK-PIPELINE-20261029.md|
|10-29 decode双lane/预测准备|真实路由fetch与共享专家计算分流；下一层预测预取|真实路由8.7 vs9.3，预测9.1 vs9.9，无收益；真实路由小模型62×129280 logprob逐位一致，不等于所有KV/长上下文都验证。保持关闭|V41-DECODE-TWO-LANES-20261029.md、V41-DECODE-PREP-LANE-20261029.md|
|10-29 checkpoint146|4MiB pinned有界分块保存/恢复、失败条目淘汰、物理/commit保护、缩小未使用staging、无MTP尾段embedding裁剪|解决RAM restore OOM；保留生命周期同步。146GiB非永久最优，后续改148|V41-CHECKPOINT146-20261029.md|
|10-30 长短会话淘汰与Unicode|预算压力下优先换同分支合格旧前缀，保护无关短会话；Windows覆盖usage|短续问14.135/13.733→1.160/1.189秒；这是复用延迟收益，不是decode倍数；compact checkpoint先数值通过后被后续采用|V41-PERFORMANCE-AUDIT-20261030.md|
|10-30 模型专属优化|148GiB、5060Ti阶段主机RAM4GiB；按KV读者裁剪；Engram用满256MiB；MXFP4按SM固定几何|最新部署组合：两请求合计161.822→157.754s（单次顺序，约-2.51%）；不是每项都证明稳定吞吐收益|V41-MODEL-SPECIFIC-OPTIMIZATION-20261030.md|
|10-30 最终数值与缓存验收|KV掩码7/4/8/8、奇偶压缩边界、同会话最旧合格祖先快照替换、protected anchor|状态/logits位级一致；双32K及双258K共12/12恢复通过；258K后续中位1.916s。最终exe与当前hash一致|同上、updates/2026-10-30-model-specific/measured-summary.json|

CPU AVX2/AVX512配对内核、Engram批次去重、64MiB handoff、预测预取、最近路由加权等候选有失败/无收益记录，不应当作遗漏默认重新打开。FP4 KV、少专家或Turbo等质量取舍也不作为本轮等价优化。

## 逐项核对 Maya（当前磁盘源码/配置）

“已有”表示有对应机制，不保证移植来源相同；“本机已测”严格限已有夹具。1.1.50列仅表示本地该源码，不声称网上最新。

|优化方法|ds4历史成果|Maya当前状态与证据|1.1.50/后续处理|
|---|---|---|---|
|ISA与每卡内核dispatch|AVX512专家、SM70/120，MXFP4几何特化|已有：CMakeLists.txt单独编译iq/kq AVX512文件；native_expert.cpp运行时探测。不能看到GGML_AVX512=OFF就说整个CPU退回标量|固定5120/2304 MXFP4不适用GLM4096/2048混合Q格式；不照搬tile|
|共享CPU线程/Windows等待|共享池、PAUSE及亲和性实验|共享池已有且CPU12有效；glm_fast_state.hpp cpu_relax仅Linux实现，Windows仍为空；未迁移可配置PAUSE/绑核|属于未完整验证缺口；历史PAUSE无稳定Q4收益，不默认启用|
|mapped token边界|绕开大专家DMA队列|已有且MAYA_GLM_ZERO_COPY=1，glm_fast_path.cu:949|无需重复移植|
|RAM/VRAM预算与放置|分卡/完整RAM backing/锁页fallback|四卡140GiB RAM、split18,28,34已实测；当前不同于ds4的148GiB与0,2,1,3|1.1.50有WDDM NON_LOCAL预算查询等新实现；须按加载证据决定，不能套ds4额度|
|RAM staging双缓冲|pageable backing DMA事件保护|当前GLM主要用pinned RAM tier；未发现ds41对应pageable ram_stage路径|不是缺一个同名开关；若锁页不足需按当前数据结构独立移植|
|batched prefill/MMQ|V4.1按专家聚合BLAS与attention批处理|已有GLM MMQ/混合CPU成本规划、借显存，glm_prefill.cu|不把现成batch当新优化；1.1.50 CPU_GATE做独立候选|
|多卡跨块流水|V4.1新增有界handoff|已有GLM流水，glm_prefill.cu约4620；少于一个块时不会跨块并行|当前16384固定块；更小chunk旧测试prefill快但decode慢，保持原值|
|按模型依赖跳算|共享压缩KV仅实际读者计算/保存|V4.1源层2/8/14/20、mask7/4/8/8不适用GLM模型|不能把V4.1层号/压缩比硬移植；GLM状态依赖需独立审查|
|HC CPU汇合|5120 HC3+CPU等待融合|Maya不同模型几何/调用链；不是同一5120 HC路径|模型结构限定，不复制DS41开关|
|decode准备lane|真实路由/预测路径均试过|Maya有原有CPU/GPU异步协作与预测机制，未证明等效DS41候选|ds4无收益候选不作为本机提速方案|
|专家准入|PROMOTE_MIN按衰减计数门槛|已有，glm_fast_path.cu:5575；不是完整TinyLFU/二次访问算法|本轮最初按least固定容量测min4；后来核对发现并非ratio LFRU，结果已纠正|
|专家淘汰|按频次/近期性和保护窗口|已有：VRAM least为aged count优先、tick破同分；RAM近期保护后aged count，全部近期则最旧|现有least不是部署版ratio LFRU；真正LFRU已在隔离候选实现并经同一二进制受控A/B验证（固定布局 +3.40%、生产布局 +4.52%，区间均不重叠），**2026-11-04 已部署**（源码+二进制+env 三处一致）；不是会话checkpoint淘汰|
|后台晋升/回填|有界后台DMA、spare/landing生命周期|已有PROMOTE默认8、FILL默认24；in-flight上限、事件完成后可见|本轮单独测fill64，不把命中率直接当吞吐|
|完整设备驻留|满层时可绕过部分管理|当前每层97～209槽等，低于288+spares，未满足完整驻留资格|1.1.50完整池默认变化在当前容量下不触发|
|Engram缓存/去重/异步|256MiB预算利用、标签、raw行验证|当前GLM无DS4 Engram表|不适用，不能搬DS41_CACHE_FULL|
|checkpoint顺序|恢复后再建立turn保存点|已有#400，10-30本机12K编辑场景reuse=12321；11-03约50K召回通过|保留现有实现|
|checkpoint预算/祖先策略|4MiB pinned分块、同会话最旧合格祖先、物理峰值约束|Maya有RAM slots/anchor/最长前缀恢复与失败条目丢弃；不等效证明拥有ds4完整压力策略|未完成双258K及压力/取消对照，不能叫全部做过|
|MTP/ngram|V4与V4.1草稿资格不同|GLM MTP已启用且实测；V4.1当前关闭推测|不能搬禁用/启用草稿结论；不采用Turbo少专家换速|
|BPE首次分词|邻接链+堆，rank与最左位置不变|本轮发现原Maya仍O(n²)式反复扫描，已迁移并通过526条/50326-token逐项对照|已采用，47项回归通过；局部446→3.7ms不等于decode倍率|
|停止串/工具/MCP/HTTP预算|15项服务层修复|Maya已有body限制等部分能力；仍见停止串枚举全部前缀，未见ds4同等并发信号量。11-04实测日常配置无 `--parallel`，5 条混合请求总耗时与串行持平（142.1→143.6 s），短请求 p95 从 9.25 s 涨到 30.62 s；停止串扫描实测 2.8～194 µs/token（≤0.65% 且与 GPU 重叠）|并发不换吞吐、只叠加尾延迟，需按实际负载决定是否开 `--parallel`；停止串枚举经实测不是瓶颈，不为此改代码|
|前端增量扫描|ds4 Markdown边界扫描|Maya前端已替换为1.1.50 Preact模块，数据结构不同|须核对新md.js；不直接粘旧app.js补丁|
|量化/少专家/FP4 KV|质量取舍或无收益实验|当前保持原权重、top8与FP16 KV|不改质量换速度|

## Skill覆盖结论

没有“所有路径都已经优化完”。已经有大量基础实现和模型实测，11-03/04 又补上了并发尾延迟与满上下文压力，但仍缺持续峰值、多会话并发（`--parallel` 开启）、部分生命周期故障注入和完整数值对照。当前1.1.50不是全部移植；DS4特有架构优化也不是GLM的漏项。

11-03 夜间补上了真正 LFRU 的 GPU 证据：同一候选二进制、同一四卡布局、6 条固定提示×256 token，least 五组均值 32.652 tok/s、lfru 五组均值 33.761（+3.40%），VRAM 命中率 80.28%→81.37%；反向顺序对照同样成立（后一组是 lfru 时更快、是 least 时更慢），排除了页面缓存与热机漂移。生产二进制配 least 与候选配 least 一致，说明收益来自策略。这只证明单一布局下的解码负载，长上下文与 prefill 主导场景仍未测，且**尚未部署**。

11-04 补了并发尾延迟：日常配置没有 `--parallel`，5 条长短混合请求同时发出时总耗时与串行持平（142.1→143.6 s），短请求 p50 8.51→21.32 s、p95 9.25→30.62 s。即并发不换吞吐、只把等待前移，属于服务层配置缺口而非原生引擎问题；`--parallel` 开启后的多会话行为未测。

11-04 还补了满上下文：260,717 token（占 262,144 的 99.5%）预填成功，1,533 tok/s、170.0 s，无 OOM；同前缀第二问复用 245,760 token（16384 的整数倍），TTFT 170.1→19.3 s；该深度解码约 6.5 tok/s，是长上下文的固有代价。

11-04 已部署：`candidate.patch` 落进根源码，`build/maya.exe` 重新编译为含 LFRU 的实现（备份 `build/maya.exe.pre-lfru-20261104.bak`），`maya-maya-xl.json` 写入 `MAYA_GLM_VRAM_EVICT=lfru`、`MAYA_GLM_RAM_EVICT=lfru` 与 `--parallel 1`。生产布局复测 lfru 比 least 快 4.52%、命中高 0.68 pp。细节见 `bench/results/skill-audit-20261103/DEPLOYED.md`。

11-04 故障注入：引擎在答话中途被杀，客户端 10.48 s 内结束并收到显式错误帧加 `[DONE]`，不挂起、不静默截断；但恢复是惰性的，崩溃后第一个请求要等一次 83.7 s 冷加载。客户端中途断开不影响后续请求。

11-04 最后两项的独立核查结论是**不改**：GLM 状态 arena 已按层类型分配（`glm_model.cu:758-775`，KDA 层只留 KDA 状态、DSA 层只留 latent/indexer/gate/pool），ds4 的 V4.1 压缩 KV 裁剪在 GLM 上没有对应物；ds4 服务层 15 项里 body 上限、tokenizer 缓存预算、恢复流 TTL、BPE 堆都已有，停止串 KMP 实测最坏 0.80 ms/token（约 2.7% 且与 GPU 重叠）不构成瓶颈。另测 `MAYA_GLM_RAM_GB` 140/148/152 三档加载出的 RAM 层完全相同（103.1 GB、7204 槽），这个旋钮不是约束，保持 140。细节见 `bench/results/skill-audit-20261103/REVIEW-remaining.md`。

本轮实验状态与最终选择见 `../bench/results/skill-audit-20261103/REPORT.md`。历史性能只属于其模型、版本、输入和布局，不能把不同时期的增益相乘。


补充部署分支：继续执行时发现实际运行的是D:/abymya-ds4.1/build-eviction/strata.exe（152GiB），它已有ratio LFRU helper，score=count/(clock-tick+1)。这不是D:/AIProjects/ds4-strata当前ds41.json所指的65fe30构建，历史目录与实际部署须分别列身份。Maya原least不等价；候选状态以审计报告为准。
