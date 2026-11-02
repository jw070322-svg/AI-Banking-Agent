# DeepSleep · AI Banking Agent 评委使用说明

提交版 1102.ver3 提供模拟银行业务、金融知识问答与财务分析。推理程序和金融 LoRA 已随包提供，基础模型在首次使用时准备。

**[下载评委提交 ZIP](https://media.githubusercontent.com/media/jw070322-svg/AI-Banking-Agent/main/releases/AI_Banking_Agent_1102.ver3.zip)** · [压缩包 SHA-256](releases/AI_Banking_Agent_1102.ver3.zip.sha256)

## 首次准备本地模型

1. 在 Windows x64 上安装 Python 3.11+ 和 Node.js 18+，完整解压评审 ZIP 至可写目录。
2. **首次保持联网，双击解压目录里的 01_启动演示.bat**。启动器会下载原版 Qwen2.5-0.5B-Instruct Q4_K_M（约 491 MB），显示下载进度，并核对文件大小和 SHA-256。随后自动加载随包的金融 LoRA。
3. 窗口出现“本地模型已就绪”后，打开 <http://127.0.0.1:8808/>。请保留启动窗口。以后在同一份解压目录双击启动器，校验通过即可离线推理。实时行情与官网核验等联网功能仍需网络。

**选择手动准备，或评审机器无法联网时**，请在可联网的电脑上下载原始 GGUF 文件，再复制到解压目录内的 `最新版本/model-assets/qwen2.5-0.5b-instruct-q4_k_m.gguf`。保留文件名后双击同一启动器，它会自动校验并使用本地副本。下载中断可重新运行启动器。[官方模型下载](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf) · [项目备用下载](https://media.githubusercontent.com/media/jw070322-svg/AI-Banking-Agent/b283030b8d52c2825be338773f3596a9543550a5/AI_Banking_Agent_1102.ver1/%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC/model-assets/qwen2.5-0.5b-instruct-q4_k_m.gguf)

文件大小为 **491,400,032 字节**，SHA-256 为 `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`。

## 提交材料

- [DeepSleep 答辩 PPT](AI_Banking_Agent_1102.ver3/最新版本/赛题辅助材料/答辩PPT_DeepSleep.pptx)
- [技术设计报告](AI_Banking_Agent_1102.ver3/最新版本/AI_Banking_Agent_技术设计与实现报告_1101赛题补充版.docx)、[架构图](AI_Banking_Agent_1102.ver3/最新版本/赛题辅助材料/系统架构图.png)与[算法说明](AI_Banking_Agent_1102.ver3/最新版本/赛题辅助材料/核心算法说明.md)
- [终版安全自评 PDF](AI_Banking_Agent_1102.ver3/最新版本/安全自评报告_1101.pdf)和[同版 Markdown](AI_Banking_Agent_1102.ver3/最新版本/安全自评报告_1101.md)，内含权限分级与已知风险
- [应用 README](AI_Banking_Agent_1102.ver3/最新版本/README.md)、[部署与排障](AI_Banking_Agent_1102.ver3/最新版本/便携版使用说明.md)、[历史资料索引](AI_Banking_Agent_1102.ver3/最新版本/history_version/历史资料索引.md)

[原项目文档归档](README_原项目文档.md)

## 自带本地模型的压缩包文件
[含满血版本地模型压缩包](releases/AI_Banking_Agent_1102.ver3.zip) 文件大小532,742KB，因此无法上传于赛事提交网站
