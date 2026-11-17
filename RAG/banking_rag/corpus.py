"""Explicit source ingestion, line-preserving chunks, and portable JSON indexes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote


class CorpusError(ValueError):
    """Invalid or inconsistent knowledge data."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_date(value: str) -> str:
    """Require canonical calendar dates so lexicographic filtering is sound."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CorpusError("日期需要 YYYY-MM-DD 格式")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise CorpusError("日期不是有效的日历日期") from exc


def read_json(path: Path) -> dict:
    if path.stat().st_size > 30_000_000:
        raise CorpusError("JSON 文件超过 30 MB 限制")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusError("需要有效的 UTF-8 JSON 文件") from exc
    if not isinstance(value, dict):
        raise CorpusError("JSON 根节点必须是对象")
    return value


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".rag-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _relative_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise CorpusError("资料路径必须为清单目录下的相对路径")
    parts = relative.split("/")
    if any(p in {"", ".", ".."} or p.startswith(".") for p in parts):
        raise CorpusError("资料路径不允许隐藏目录或路径穿越")
    target = (root / relative).resolve(strict=True)
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise CorpusError("资料必须位于清单目录内")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise CorpusError("资料路径不允许符号链接或目录联接")
    if target.suffix.lower() not in {".md", ".txt"}:
        raise CorpusError("初版仅支持显式清单中的 Markdown/TXT")
    if target.stat().st_size > 1_000_000:
        raise CorpusError("单份资料不能超过 1 MB")
    return target


def load_documents(manifest: Path) -> list[dict]:
    data = read_json(manifest)
    entries = data.get("documents")
    if data.get("schema_version") != 1 or not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise CorpusError("清单 schema_version 必须为 1，资料数须为 1–100")
    documents, seen, total = [], set(), 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise CorpusError("资料条目必须是对象")
        for key in ("id", "path", "title", "source_uri", "revision", "kind"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise CorpusError(f"资料缺少非空字段：{key}")
        if entry["id"] in seen:
            raise CorpusError("资料 ID 重复")
        seen.add(entry["id"])
        path = _relative_file(manifest.parent, entry["path"])
        raw = path.read_bytes()
        total += len(raw)
        if total > 10_000_000:
            raise CorpusError("资料总量超过 10 MB")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise CorpusError("资料需要 UTF-8 编码") from exc
        if not text.strip() or "\x00" in text:
            raise CorpusError("资料为空或包含二进制数据")
        sha = digest(text)
        if entry.get("sha256") and entry["sha256"] != sha:
            raise CorpusError(f"资料摘要不匹配，请审核更新：{entry['id']}")
        for key in ("valid_from", "valid_until"):
            if entry.get(key) is not None:
                validate_date(entry[key])
        if entry.get("valid_from") and entry.get("valid_until") and entry["valid_from"] > entry["valid_until"]:
            raise CorpusError("资料有效期起始晚于截止日期")
        documents.append({**entry, "sha256": sha, "text": text})
    return documents


def chunk_document(document: dict, max_chars: int = 800, overlap_lines: int = 2) -> list[dict]:
    if not 100 <= max_chars <= 4000 or not 0 <= overlap_lines <= 5:
        raise CorpusError("分块字符数需为100–4000，重叠行数需为0–5")
    result, pending, headings = [], [], []
    fence = None

    def emit():
        if not pending or not any(t.strip() for _, t in pending):
            return
        text = "\n".join(t for _, t in pending)
        start, end = pending[0][0], pending[-1][0]
        chunk_id = digest(f"{document['id']}:{document['sha256']}:{start}:{end}:{text}")[:24]
        result.append({"id": chunk_id, "document_id": document["id"], "section": " / ".join(headings),
                       "start_line": start, "end_line": end, "text": text, "sha256": digest(text)})

    for number, line in enumerate(document["text"].splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                emit(); pending = []
                fence = marker.group(1)
            elif (marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)
                  and not line[marker.end():].strip()):
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)", line)
        if heading:
            emit(); pending = []
            level = len(heading.group(1))
            headings = headings[:level - 1] + [heading.group(2)]
        # Long table rows are split without inventing source line numbers.
        pieces = [line[i:i + max_chars] for i in range(0, len(line), max_chars)] or [""]
        for piece in pieces:
            if pending and sum(len(t) + 1 for _, t in pending) + len(piece) > max_chars:
                emit()
                pending = pending[-overlap_lines:] if overlap_lines else []
                while pending and sum(len(t) + 1 for _, t in pending) + len(piece) > max_chars:
                    pending.pop(0)
            pending.append((number, piece))
    emit()
    return result


def build_index(manifest: Path, destination: Path, *, max_chars: int = 800,
                overlap_lines: int = 2, embedder=None, embedding_model: str | None = None) -> dict:
    documents = load_documents(manifest)
    inputs = {manifest.resolve()} | {(manifest.parent / d["path"]).resolve() for d in documents}
    if destination.resolve() in inputs:
        raise CorpusError("索引输出不能覆盖资料清单或原文")
    chunks = [c for d in documents for c in chunk_document(d, max_chars, overlap_lines)]
    if not chunks:
        raise CorpusError("没有可索引正文（代码块不入库）")
    vectors = None
    if embedding_model:
        if embedder is None:
            raise CorpusError("指定向量模型时需要 embedder")
        vectors = []
        for start in range(0, len(chunks), 16):
            vectors.extend(embedder.embed([c["text"] for c in chunks[start:start + 16]], embedding_model))
        validate_vectors(vectors, len(chunks))
    index = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
             "chunking": {"max_chars": max_chars, "overlap_lines": overlap_lines},
             "documents": [{k: v for k, v in d.items() if k != "text"} for d in documents],
             "chunks": chunks, "embedding_model": embedding_model, "vectors": vectors}
    index["content_sha256"] = index_digest(index)
    write_json(destination, index)
    return index


def index_digest(index: dict) -> str:
    return digest(json.dumps({k: v for k, v in index.items() if k != "content_sha256"},
                             ensure_ascii=False, sort_keys=True, allow_nan=False))


def validate_vectors(vectors, count: int) -> None:
    import math
    if not isinstance(vectors, list) or len(vectors) != count or not vectors:
        raise CorpusError("向量数量与分块数不一致")
    dimension = len(vectors[0]) if isinstance(vectors[0], list) else 0
    if not dimension:
        raise CorpusError("向量维度不能为空")
    for vector in vectors:
        if (not isinstance(vector, list) or len(vector) != dimension
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector)
            or not any(vector)):
            raise CorpusError("向量必须维度一致、非零且为有限数值")


def load_index(path: Path) -> dict:
    index = read_json(path)
    try:
        if index.get("schema_version") != 1 or index.get("content_sha256") != index_digest(index):
            raise CorpusError("索引版本或摘要不匹配，请重新构建")
        documents = {d["id"]: d for d in index["documents"]}
        if not documents or not index["chunks"] or len(documents) != len(index["documents"]):
            raise CorpusError("索引文档为空或重复")
        for c in index["chunks"]:
            if (c["document_id"] not in documents or c["sha256"] != digest(c["text"])
                or not 1 <= c["start_line"] <= c["end_line"]):
                raise CorpusError("索引分块或来源无效")
        if index.get("embedding_model"):
            validate_vectors(index.get("vectors"), len(index["chunks"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError("索引结构无效或已损坏，请重新构建") from exc
    return index


def prepare_demo(root: Path) -> Path:
    """Export the already-authorized snapshot; never perform network access."""
    snapshot = read_json(root / "data" / "repository_snapshot.json")
    folder = root / "data" / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in snapshot["documents"]:
        name = item["path"]
        if "/" in name or "\\" in name or ":" in name or name.startswith("."):
            raise CorpusError("示例快照路径不合法")
        text = item["text"]
        blob = hashlib.sha1(b"blob " + str(len(text.encode('utf-8'))).encode() + b"\x00" + text.encode('utf-8')).hexdigest()
        if blob != item["git_blob_sha"]:
            raise CorpusError("快照内容与 Git blob SHA 不一致")
        target = folder / name
        if target.exists() and target.read_bytes() != text.encode("utf-8"):
            raise CorpusError("示例资料已被修改；请先保留修改并使用独立清单")
        target.write_bytes(text.encode("utf-8"))
        entries.append({"id": "repo-readme" if name == "README.md" else "repo-architecture",
                        "path": name, "title": name.removesuffix(".md"), "kind": "project_design",
                        "revision": snapshot["revision"], "sha256": digest(text),
                        "source_uri": f"https://github.com/{snapshot['repository']}/blob/{snapshot['revision']}/{quote(name)}",
                        "verified_on": snapshot["verified_on"], "valid_from": None, "valid_until": None})
    manifest = folder / "manifest.json"
    if manifest.exists() and read_json(manifest) != {"schema_version": 1, "documents": entries}:
        raise CorpusError("示例清单已修改，请使用独立清单或索引命令")
    write_json(manifest, {"schema_version": 1, "documents": entries})
    return manifest
