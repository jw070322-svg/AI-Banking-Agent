"""Install the pinned original GGUF on first launch using only Python's standard library."""
import hashlib
import json
import os
import tempfile
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FILENAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
MIRROR = "https://media.githubusercontent.com/media/jw070322-svg/AI-Banking-Agent/b283030b8d52c2825be338773f3596a9543550a5/"


def ensure_reviewer_model():
    manifest = json.loads((ROOT / "model-assets/manifest.json").read_text(encoding="utf-8"))
    relative = "model-assets/" + FILENAME
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    target = ROOT / relative
    if target.is_file() and target.stat().st_size == entry["bytes"]:
        with target.open("rb") as current:
            if hashlib.file_digest(current, "sha256").hexdigest() == entry["sha256"]:
                print("原版模型校验通过，使用本地文件。", flush=True)
                return

    print("首次准备原版千问模型（约 491 MB）。下载并校验后，就能在本机离线推理。", flush=True)
    mirror = MIRROR + quote("AI_Banking_Agent_1102.ver1/最新版本/" + relative)
    for source in (manifest["model_source"], mirror):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                count = 0
                digest = hashlib.sha256()
                with urlopen(Request(source, headers={"User-Agent": "AI-Banking-Reviewer/1"}), timeout=45) as response:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > entry["bytes"]:
                            raise ValueError("下载大小超过预期")
                        out.write(chunk)
                        digest.update(chunk)
                        if count % (32 * 1024 * 1024) == 0:
                            print(f"已下载 {count * 100 // entry['bytes']}%", flush=True)
            if count != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise ValueError("文件大小或 SHA-256 未通过校验")
            os.replace(temporary, target)
            print("原版模型下载并校验完成。", flush=True)
            return
        except (OSError, URLError, ValueError, EOFError, HTTPException) as exc:
            print(f"本次下载未完成（{exc}）。", flush=True)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise SystemExit(f"请重新联网运行启动器，或按 README.md 手动下载模型，放入 {target} 后重试。")
