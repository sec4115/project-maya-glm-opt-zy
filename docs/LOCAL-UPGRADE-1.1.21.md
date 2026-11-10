# 本机 Maya 1.1.21 合并版

本机运行目录仍是 `D:\project-maya-main`，上游输入是
`D:\project-maya-1.1.21`。输入目录保持原样；其空白 `VERSION` 在本机合并版
按目录名称和 CHANGELOG 补为 `1.1.21`。

## 使用范围

- 当前只构建 GLM CUDA 引擎 `build/maya.exe` 和视觉编码器
  `build-vision/bin/maya-vision.exe`，CUDA 架构为 `120`，适配当前
  5090D / 5060 Ti。`MAYA_BUILD_DS4=OFF`，HIP 不启用。
- DeepSeek、AMD、旧架构与其他量化支持的上游源码保留作参考，不作为本机
  提速项，也不额外构建它们的引擎。以后显式选择 DeepSeek 才会重新打开对应
  构建选项。
- M/L/XL 原来的三个 BAT 继续可用，同一时间启动一个模型。配置中的 exe
  路径已迁移，192G 的 RAM/CPU 参数、5060 Ti 的 11.3 GiB 专家池限制保持。
- 新版启动器会把配置里的 `STRATA_*` 写成 `MAYA_*`；两种名称兼容。
  本地测试/调优脚本先规范化名称，再应用本轮覆盖值，避免旧预算盖过新测试。

## 本机保留的优化

工具 schema 对象键规范化、共享前缀保护、流式 KV 会话文件直接使用 pinned
RAM、2 秒公平时间片、Anthropic 请求级 thinking budget 和 token 计数、工具
调用 ID 校验，以及 Codex 模型目录/命名空间/自定义工具。

新版增加了显存分配后预算复核、专家 spare 的 LRU 替换、短提示和部分
attention 路径改进、异步检查点及更可靠的取消/退出处理。单卡显存限制已接入
新的预算结构，不会因升级而被忽略。

未打开跳过专家、路由近似、并行多序列、额外草稿模型或 RAM 会话槽。
这些选择需要独立实测，部分会改变结果或增加内存；不能当作免费提速。
上游部分默认浮点运算顺序和专家放置也有变化，不保证与 1.1.8 逐 token 一致。

## 接口变化

新版 Responses 支持有界的服务内存储、`previous_response_id`、后台任务、
取消及结构化结果校验。本机保留 Codex 的 namespace/custom tool 扩展，
并验证它们能与存储续接共同工作。见 [API-COMPATIBILITY.md](API-COMPATIBILITY.md)
和上游 [RESPONSES.md](RESPONSES.md)。

## 证据与回退

实测结果、构建日志、源码清单及配置差异在
`bench/results/upgrade-1.1.21-20261022/`；汇总见该目录的 `REPORT.md`。
`before.zip` 保存被替换的原文件、三套原配置、旧引擎和构建戳。
回退须先停止服务，恢复归档中的同名文件，再用原 BAT 启动；新增文件清单
在 `incoming-manifest.json`。不要在新旧源码混合时只换一个 exe。
