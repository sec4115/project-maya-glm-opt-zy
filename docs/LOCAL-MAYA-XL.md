# 本机 Maya-XL

`Maya-XL` 是本机 `GLM-5.3-Flash-UD-Q4_K_XL` 的安装别名。
它读取 `D:\AI\lla_models\gguf\Maya-XL` 中的六个原始 GGUF 分片，
不是下载列表里新增的远程预设。

## 启动

先停止当前模型，再双击项目根目录的 `run-maya-maya-xl.bat`。
也可以在项目目录执行：

```powershell
.venv\Scripts\python.exe maya.py --config maya-maya-xl.json --port 8080
```

该配置会出现在工具的已安装模型列表中。M、L、XL 使用相同的本地
8080 端口和 API，分别由对应的 BAT 选择权重；同一时间运行一个模型。
API 中的逻辑模型名仍是 `glm-5.3-flash`，与现有客户端配置兼容。

## 文件与兼容性

- 首个 GGUF 分片只包含元数据和 tokenizer，约 9 MB、0 个张量，
  是有效的 metadata-only 分片；其余五个分片承载张量。
- `pack/` 包含索引、约 0.88 GiB 的 BF16 兼容小权重和 tokenizer。
  专家继续从原 GGUF 按偏移读取，没有复制整份 200 GB 模型，
  也没有重新量化专家。
- GGUF 的部分小投影按现有引擎要求转换到 BF16，转换记录在
  `pack/compat-bf16.json`。不能将这视作与其他 GGUF 引擎的逐位等价保证。
- `pack/sources.json` 记录分片大小和修改时间；分片替换后需要重新生成 pack。
- tokenizer 的词表、merges、特殊 token、token type 和聊天模板与本机 L
  的对应文件逐项 SHA256 一致。视觉配置复用 L 目录的 GLM-5.3 视觉资源，
  因此使用 XL 图像输入时需保留配置中引用的 L/vision 文件。

## 调优

测试使用升级后的 192 GiB 机器，当前配置和结果以
`bench/results/ram192-20261022/REPORT.md` 为准。
XL 比 M/L 大，缓存预算、实际分配量和系统余量必须分别测量。
本机缓存预算不是“使用全部物理内存”的开关；仍需给 Windows、KV、
会话检查点及服务留空间。

本轮还修复了校准工具对 SSD 使用的判断：缓存槽含 spare/重复副本，
总槽数超过专家数时仍可能读盘。现在也检查本次引擎日志中的实际专家读取，
避免漏测磁盘读取分块；只扫描有界日志尾部并排除旧运行的统计。
