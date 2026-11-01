# AI Banking Agent 1101.ver1

本项目提供本地模拟银行业务、金融知识检索、理财分析和网页安全执行链。Windows x64 版随包提供千问 Qwen2.5 0.5B、金融 LoRA 和 llama.cpp CPU 推理服务。

## 启动

安装 Python 3.11+ 和 Node.js 18+，完整解压发布 ZIP 到可写目录，双击“启动最新安全自评版.bat”。看到模型就绪后，打开 http://127.0.0.1:8808/ 并保留窗口。模型服务监听本机 8811。详细部署、校验和排障步骤见 [便携版使用说明](便携版使用说明.md)。

## 验证和提交材料

- 安全自评：`python -X utf8 -B -m security_integration.self_assess`。
- 继承回归：`python -X utf8 -B -m security_integration.regression`。
- 网页及模型服务运行时，执行 `python -X utf8 -B tools/verify_portable_inference.py` 验证推理和网页知识路径。
- 查看[系统架构图](赛题辅助材料/系统架构图.png)、[核心算法说明](赛题辅助材料/核心算法说明.md)、[安全自评](安全自评报告_1101.html)及赛题补充版技术报告。
- 测试证据位于 `reports/security-integration-1101/` 与 `reports/portable-model/`，测试时间以各记录为准。

## 取得源码和模型

私有仓库交付分支为 `codex/1101-portable-local-model`。安装 Git LFS 后克隆并运行 `git lfs pull`。接收方也可下载仓库 `releases/` 中的完整 ZIP 和 SHA-256 文件。仓库访问权限需由项目成员与评审方确认。

本应用使用本地模拟账本和演示身份。模型金融回答质量、真实银行接入、生产认证与审计仍需独立业务验收。
