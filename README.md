# AI Banking Agent 1102.ver1

本项目提供本地模拟银行业务、金融知识检索、理财分析和网页安全执行链。Windows x64 版随包提供千问 Qwen2.5 0.5B、金融 LoRA 和 llama.cpp CPU 推理服务。

评委材料包括 [安全自评 PDF](AI_Banking_Agent_1102.ver1/最新版本/安全自评报告_1101.pdf)、[安全自评 Markdown](AI_Banking_Agent_1102.ver1/最新版本/安全自评报告_1101.md) 和 [DeepSleep 答辩 PPT](AI_Banking_Agent_1102.ver1/最新版本/赛题辅助材料/答辩PPT_DeepSleep.pptx)。历史启动资料归档在 history_version。

[评委打开说明](AI_Banking_Agent_1102.ver1/打开说明.md) · [原项目文档归档](README_原项目文档.md)

## 启动

安装 Python 3.11+ 和 Node.js 18+，完整解压发布 ZIP 到可写目录，双击外层的“01_启动演示.bat”。看到模型就绪后，打开 http://127.0.0.1:8808/ 并保留窗口。模型服务监听本机 8811。详细部署、校验和排障步骤见 [便携版使用说明](AI_Banking_Agent_1102.ver1/最新版本/便携版使用说明.md)。

## 验证和提交材料

- 安全自评：`python -X utf8 -B -m security_integration.self_assess`。
- 继承回归：`python -X utf8 -B -m security_integration.regression`。
- 网页及模型服务运行时，执行 `python -X utf8 -B tools/verify_portable_inference.py` 验证推理和网页知识路径。
- 查看[系统架构图](AI_Banking_Agent_1102.ver1/最新版本/赛题辅助材料/系统架构图.png)、[核心算法说明](AI_Banking_Agent_1102.ver1/最新版本/赛题辅助材料/核心算法说明.md)、[安全自评](AI_Banking_Agent_1102.ver1/最新版本/安全自评报告_1101.html)及赛题补充版技术报告。
- 测试证据位于 `reports/security-integration-1101/` 与 `reports/portable-model/`，测试时间以各记录为准。

## 取得源码和模型

安装 Git LFS 后克隆本仓库并运行 `git lfs pull`，进入 `AI_Banking_Agent_1102.ver1/最新版本`。也可直接下载 [完整 ZIP](releases/AI_Banking_Agent_1102.ver1.zip) 和 [SHA-256 校验文件](releases/AI_Banking_Agent_1102.ver1.zip.sha256)。仓库包含模型权重，建议使用完整 ZIP 并在解压后核对 SHA-256。

本应用使用本地模拟账本和演示身份。模型金融回答质量、真实银行接入、生产认证与审计仍需独立业务验收。
