"""make_fixtures.py —— 用环境生成 Agent 生成可复现的分析样例。

每次运行都会用固定 seed + 固定参考日期调用 `handle_generate()`，
把契约格式的 `data` 写到 `fixtures/SCENARIO_A.json` ~ `SCENARIO_G.json`。
这样分析模块的测试和评测就有稳定输入。

用法：
    python make_fixtures.py
    python make_fixtures.py --seed 42 --reference-date 2026-10-23
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_DIR = BASE_DIR.parent / "环境生成agent"
FIXTURE_DIR = BASE_DIR / "fixtures"

SCENARIO_TYPES = "ABCDEFG"


def _load_env_modules():
    if not ENV_DIR.exists():
        raise RuntimeError(f"找不到环境生成 Agent 目录：{ENV_DIR}")
    env_path = str(ENV_DIR)
    if env_path not in sys.path:
        sys.path.insert(0, env_path)
    import main as env_main  # type: ignore
    from scenario_adapter import handle_generate, reset_idempotency_store  # type: ignore
    return env_main, handle_generate, reset_idempotency_store


def build_all(
    seed: int = 42,
    reference_date: str = "2026-10-23",
    out_dir: Path | str = FIXTURE_DIR,
) -> list[Path]:
    """生成 A~G 七份契约样例，返回写出的文件路径。"""
    env_main, handle_generate, reset_idempotency_store = _load_env_modules()
    reset_idempotency_store()

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for scenario_type in SCENARIO_TYPES:
        response = handle_generate(
            {
                "prompt": env_main.DEFAULT_REQUIREMENTS[scenario_type],
                "scenario_type": scenario_type,
                "seed": seed,
                "reference_date": reference_date,
            },
            idempotency_key=f"fixture-{scenario_type}-{seed}",
        )
        if response.get("status") != "succeeded":
            raise RuntimeError(
                f"场景 {scenario_type} 生成失败：{response.get('error')}"
            )
        path = out_path / f"SCENARIO_{scenario_type}.json"
        path.write_text(
            json.dumps(response["data"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(path)

    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成分析用的固定样例")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-date", default="2026-10-23")
    parser.add_argument("--out", default=str(FIXTURE_DIR))
    args = parser.parse_args()

    for fixture in build_all(args.seed, args.reference_date, args.out):
        print(f"已生成：{fixture}")
