#!/usr/bin/env python3
"""交付复现脚本：文件清单 → 测试 → Demo → 日志校验 → 交付 .md。

用法：
    cd ai-banking-agent
    python3 scripts/verify_delivery.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "bank_agent/__init__.py",
    "bank_agent/models.py",
    "bank_agent/data.py",
    "bank_agent/policy_config.json",
    "bank_agent/tools.py",
    "bank_agent/orchestrator.py",
    "bank_agent/brain.py",
    "bank_agent/stages/execution.py",
    "bank_agent/stages/selection.py",
    "bank_agent/risk/__init__.py",
    "bank_agent/risk/models.py",
    "bank_agent/risk/policy.py",
    "bank_agent/risk/preview.py",
    "bank_agent/risk/auth.py",
    "bank_agent/risk/compliance.py",
    "bank_agent/risk/controls.py",
    "bank_agent/risk/action_log.py",
    "bank_agent/risk/engine.py",
    "tests/test_pipeline.py",
    "tests/test_risk_compliance.py",
    "docs/05-action-log-spec.md",
    "docs/06-risk-compliance.md",
    "docs/07-compliance-control-matrix.md",
    "run_demo.py",
    "README.md",
]

HASH_FILES = REQUIRED_FILES + [
    "scripts/verify_delivery.py",
    "bank_agent/stages/planning.py",
    "bank_agent/stages/verification.py",
    "bank_agent/stages/response.py",
    "bank_agent/stages/intent.py",
    "bank_agent/utils.py",
]

LOG_FIELDS = {
    "user_id",
    "intent",
    "tool",
    "input",
    "output",
    "risk_check",
    "approval",
    "timestamp",
}

PII_PATTERNS = [
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise AssertionError(f"{path}: 缺少 JSON 代码块")
    return json.loads(match.group(1))


def main() -> int:
    problems: list[str] = []

    missing = [name for name in REQUIRED_FILES if not (ROOT / name).exists()]
    if missing:
        problems.append("缺少文件：" + ", ".join(missing))

    sys.path.insert(0, str(ROOT))
    try:
        import bank_agent  # noqa: F401
        from bank_agent import BankingAgent
        from bank_agent.risk import RiskComplianceEngine  # noqa: F401
    except Exception as exc:  # pragma: no cover
        problems.append(f"导入失败：{exc}")
        BankingAgent = None

    # 不可信内容不得被当作代码执行：静态检查动态执行入口。
    unsafe_calls: list[str] = []
    for path in (ROOT / "bank_agent").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("eval(", "exec(", "__import__("):
            if token in text:
                unsafe_calls.append(
                    f"{path.relative_to(ROOT)}:{token}"
                )
    if unsafe_calls:
        problems.append(
            "源代码中发现动态执行入口：" + ", ".join(unsafe_calls)
        )

    test_result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    test_output = test_result.stdout + test_result.stderr
    test_summary = ""
    match = re.search(r"Ran (\d+) tests?", test_output)
    if match:
        test_summary = f"{match.group(1)} tests"
    if test_result.returncode != 0:
        problems.append("测试失败：\n" + test_output[-3000:])

    demo_result = "not_run"
    demo_log_count = 0
    demo_tools: list[str] = []
    if BankingAgent is not None:
        try:
            with tempfile.TemporaryDirectory() as temp:
                temp_path = Path(temp)
                agent = BankingAgent(
                    action_log_root=str(temp_path / "logs"),
                    preview_state_path=str(
                        temp_path / "state" / "risk_state.json"
                    ),
                )
                session = agent.new_session()
                first = agent.handle(
                    session, "从我工资卡给张三转 3000 元"
                )
                second = agent.handle(session, "确认")
                if first.status != "needs_confirmation":
                    problems.append(f"预览阶段状态异常：{first.status}")
                if second.status != "completed":
                    problems.append(f"确认阶段状态异常：{second.status}")

                logs = sorted((temp_path / "logs").rglob("*.md"))
                demo_log_count = len(logs)
                for path in logs:
                    entry = parse_log(path)
                    if set(entry) != LOG_FIELDS:
                        problems.append(f"{path.name}: 字段不是严格 8 个")
                    if not all(isinstance(value, str) for value in entry.values()):
                        problems.append(f"{path.name}: 字段值不是字符串")
                    if not re.search(r"[+-]\d{2}:\d{2}$", entry["timestamp"]):
                        problems.append(f"{path.name}: 时间戳缺少时区")
                    raw = path.read_text(encoding="utf-8")
                    for pattern in PII_PATTERNS:
                        if pattern.search(raw):
                            problems.append(f"{path.name}: 发现未脱敏 PII")
                    demo_tools.append(entry["tool"])
                if demo_log_count < 3:
                    problems.append("演示日志少于 3 条")
                demo_result = (
                    f"completed · {demo_log_count} logs"
                    if demo_log_count
                    else "completed · no logs"
                )
        except Exception as exc:
            problems.append(f"Demo 失败：{exc}")

    manifest = []
    for name in HASH_FILES:
        path = ROOT / name
        if path.exists() and path.is_file():
            manifest.append((name, sha256(path)))

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    status = "passed" if not problems else "failed"
    log_lines = [
        "# Delivery Verification · Risk & Compliance",
        "",
        f"- 时间：{timestamp}",
        f"- 结果：{status}",
        f"- 测试：{test_summary or 'unknown'}",
        f"- Demo：{demo_result}",
        "",
        "## Manifest",
        "",
        "| 文件 | SHA-256 |",
        "|---|---|",
    ]
    for name, digest in manifest:
        log_lines.append(f"| `{name}` | `{digest}` |")
    log_lines += ["", "## 复现", "", "```bash", "python3 scripts/verify_delivery.py", "```", ""]
    if problems:
        log_lines += ["## 问题", ""]
        log_lines += [f"- {problem}" for problem in problems]
        log_lines.append("")

    entry = {
        "user_id": "team:delivery-verification",
        "intent": "verify_risk_compliance_delivery",
        "tool": "delivery.verify@1.0.0",
        "input": json.dumps(
            {
                "required_files": len(REQUIRED_FILES),
                "test_command": "python3 -m unittest discover -s tests -v",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "output": json.dumps(
            {
                "status": status,
                "tests": test_summary or "unknown",
                "demo": demo_result,
                "demo_log_count": demo_log_count,
                "demo_tools": sorted(set(demo_tools)),
                "manifest_files": len(manifest),
                "static_checks": (
                    "no_eval_exec_dynamic_import"
                    if not unsafe_calls
                    else "failed"
                ),
                "problems": problems,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "risk_check": json.dumps(
            {
                "mutating": False,
                "real_funds": False,
                "pii_scan": "passed" if status == "passed" else "failed",
                "external_side_effects": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "approval": json.dumps(
            {
                "required": False,
                "reason": "verification_only",
                "decision": "not_required",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "timestamp": timestamp,
    }
    log_lines += [
        "## Agent Action",
        "",
        "```json",
        json.dumps(entry, ensure_ascii=False, indent=2),
        "```",
        "",
    ]

    logs_dir = ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = logs_dir / (
        "delivery-verification-"
        + datetime.now().strftime("%Y%m%d-%H%M%S")
        + ".md"
    )
    output_path.write_text("\n".join(log_lines), encoding="utf-8")

    print(f"status: {status}")
    print(f"tests: {test_summary or 'unknown'}")
    print(f"demo: {demo_result}")
    print(f"manifest files: {len(manifest)}")
    print(f"report: {output_path}")
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
