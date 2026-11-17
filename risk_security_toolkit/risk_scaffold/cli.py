"""CLI for source -> evidence plan -> fixed module scaffolds -> audit event."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .generation import write_scaffold
from .modules.audit import AuditEvent, append_event
from .planning import make_plan
from .sources import GitHubSource, Limits, LocalSource, SnapshotSource, SourceError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="owner/repo or https://github.com/owner/repo")
    source.add_argument("--local", type=Path, help="Existing cloned/downloaded source directory")
    source.add_argument("--snapshot", type=Path, help="JSON export from an authorized GitHub connector")
    parser.add_argument("--ref", help="Remote branch, tag or commit (resolved to one commit)")
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    parser.add_argument("--user-id", default="local-developer", help="Pseudonymous audit actor")
    parser.add_argument("--max-files", type=int, default=250)
    args = parser.parse_args(argv)
    try:
        if args.ref and not args.repo:
            raise ValueError("--ref is only valid with --repo")
        if args.out.exists() or args.out.is_symlink():
            raise FileExistsError("Output directory already exists; choose a new --out path")
        limits = Limits(max_files=args.max_files)
        reader = (GitHubSource(args.repo, args.ref) if args.repo else
                  LocalSource(args.local) if args.local else SnapshotSource(args.snapshot))
        # Avoid consuming our output, or embedding generated modules in evidence.
        if args.local and args.out.resolve().is_relative_to(args.local.resolve()):
            raise ValueError("Output directory must be outside the local source tree")
        corpus = reader.collect(limits)
        plan = make_plan(corpus)
        generated = write_scaffold(plan, args.out)
        append_event(args.out / "audit.jsonl", AuditEvent.now(
            user_id=args.user_id, intent="read_documentation_and_scaffold_risk_security",
            tool="risk_scaffold.cli", input=f"documents={len(corpus.documents)}; revision={corpus.revision}",
            output=f"files_generated={len(generated)}; plan=plan.json",
            risk_check="read_only_source; fixed_templates; all_verification_unknown; writes_require_review",
            approval="requested_local_scaffold"))
        print(json.dumps({"output": str(args.out.resolve()), "documents": len(corpus.documents),
                          "revision": corpus.revision, "warnings": plan["warnings"]}, ensure_ascii=False))
        return 0
    except (SourceError, ValueError, OSError, KeyError, TypeError) as exc:
        # Source errors are sanitized; no remote response body or token is printed.
        print(f"Scaffold failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
