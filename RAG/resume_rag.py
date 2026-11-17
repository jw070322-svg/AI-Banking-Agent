"""AI Banking RAG 恢复入口与代码导航。

上下文：参考固定提交的两份项目设计资料，初版为只读、可追溯知识问答。
实现路径：
  corpus.py -> 清单/哈希/分块/JSON索引
  retrieval.py -> BM25与可选本地向量融合
  service.py -> 检索、摘录、可选生成、引用校验
  providers.py -> Ollama本机适配；cli.py -> 命令行
设计依据：先确保来源可核验、无依据不编造，再接入本地模型与编排器。
验证状态与剩余事项以 HANDOFF.md 和 session_log.json 为准。
运行本文件仅重建离线示例并输出回答，不检查Codex额度、不自动恢复开发。
"""
from banking_rag.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["demo"]))
