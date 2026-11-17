"""Emit fixed reviewed Python templates; source text only appears in JSON."""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from . import modules


def write_scaffold(plan: dict, destination: Path) -> list[str]:
    # A new directory is mandatory: rerunning cannot overwrite developer work.
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Scaffold destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    package = destination / "generated_controls"
    package.mkdir()
    emitted = []
    for name in ("__init__.py", "risk_assessment.py", "compliance.py", "security.py", "audit.py"):
        source = files(modules).joinpath(name).read_text(encoding="utf-8")
        (package / name).write_text(source, encoding="utf-8")
        emitted.append("generated_controls/" + name)
    (destination / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    questions = "\n".join(f"- {c['id']}: {c['question']}" for c in plan["controls"])
    (destination / "REVIEW.md").write_text(
        "# Scaffold review\n\nEvery control verification status starts as unknown.\n"
        "Documentation mentions are candidate requirements, not implementation evidence.\n\n"
        + questions + "\n\nWrite tools always return review. No tool execution is implemented.\n",
        encoding="utf-8")
    return emitted + ["plan.json", "REVIEW.md"]
