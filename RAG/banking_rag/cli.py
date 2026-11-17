"""No-install CLI. Run from the RAG directory: python -m banking_rag --help."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .corpus import CorpusError, build_index, prepare_demo, read_json, write_json
from .service import RAGService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "data" / "index.json"


def evaluate(service: RAGService, cases: dict) -> dict:
    rows = []
    for case in cases["cases"]:
        result = service.ask(case["question"], top_k=4)
        evidence = result["evidence"]
        status_ok = result["status"] == case["expected_status"]
        source_ok = (not case.get("expected_document_id") or any(
            e["document_id"] == case["expected_document_id"] for e in evidence))
        joined = "\n".join(e["text"] for e in evidence)
        terms_ok = all(term.casefold() in joined.casefold() for term in case.get("expected_terms", []))
        rows.append({"id": case["id"], "question": case["question"], "passed": status_ok and source_ok and terms_ok,
                     "status_ok": status_ok, "source_ok": source_ok, "terms_ok": terms_ok,
                     "actual_status": result["status"], "document_ids": sorted({e["document_id"] for e in evidence})})
    passed = sum(r["passed"] for r in rows)
    return {"schema_version": 1, "mode": "offline_retrieval_smoke_evaluation", "total": len(rows),
            "passed": passed, "pass_rate": passed / len(rows) if rows else 0,
            "index_sha256": service.retriever.index["content_sha256"],
            "limitations": ["手工小样本检索回归，不能代表真实金融问答准确率", "不评估大模型语义蕴含、真实业务执行或全面提示注入防御"],
            "cases": rows}


def main(argv=None) -> int:
    # Keep Chinese JSON readable when Windows launches Python through a pipe.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AI Banking 初版只读 RAG")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="准备固定提交的仓库资料、建库并运行一个离线问题")
    demo.add_argument("--question", default="取消订阅后，未来节约能计入当前余额吗？")
    demo.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    build = commands.add_parser("build", help="从显式资料清单构建索引")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    build.add_argument("--chunk-size", type=int, default=800)
    build.add_argument("--embedding-model", help="可选：本机 Ollama 已安装的嵌入模型名")
    build.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    for name in ("search", "ask"):
        command = commands.add_parser(name)
        command.add_argument("question")
        command.add_argument("--index", type=Path, default=DEFAULT_INDEX)
        command.add_argument("--top-k", type=int, default=4)
        command.add_argument("--as-of", help="资料有效日期 YYYY-MM-DD，默认北京时间当天")
        command.add_argument("--kind", action="append", dest="kinds", help="按资料类型过滤，可重复")
        command.add_argument("--hybrid", action="store_true", help="启用向量+BM25，需预先构建向量索引")
        command.add_argument("--ollama-url", default="http://127.0.0.1:11434")
        command.add_argument("--output", type=Path)
        if name == "ask":
            command.add_argument("--generation-model", help="可选：本机 Ollama 已安装的对话模型名")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    evaluation.add_argument("--cases", type=Path, default=ROOT / "examples" / "evaluation_cases.json")
    evaluation.add_argument("--output", type=Path, default=ROOT / "output" / "evaluation.json")
    args = parser.parse_args(argv)
    try:
        client = None
        if getattr(args, "embedding_model", None) or getattr(args, "generation_model", None) or getattr(args, "hybrid", False):
            from .providers import OllamaClient
            client = OllamaClient(args.ollama_url)
        if args.command == "demo":
            manifest = prepare_demo(ROOT)
            build_index(manifest, args.index)
            result = RAGService(args.index).ask(args.question)
            write_json(ROOT / "output" / "demo_answer.json", result)
        elif args.command == "build":
            index = build_index(args.manifest, args.index, max_chars=args.chunk_size,
                                embedder=client, embedding_model=args.embedding_model)
            result = {"status": "built", "documents": len(index["documents"]), "chunks": len(index["chunks"]),
                      "embedding_model": index["embedding_model"], "index": str(args.index)}
        elif args.command == "evaluate":
            result = evaluate(RAGService(args.index), read_json(args.cases))
            write_json(args.output, result)
        else:
            service = RAGService(args.index, client)
            kwargs = {"top_k": args.top_k, "as_of": args.as_of, "kinds": args.kinds, "hybrid": args.hybrid}
            result = ({"results": service.search(args.question, **kwargs)} if args.command == "search"
                      else service.ask(args.question, generation_model=args.generation_model, **kwargs))
            if args.output:
                write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if args.command == "evaluate" and result["passed"] != result["total"] else 0
    except (CorpusError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
