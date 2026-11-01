"""Copy the genuinely missing previous-version handoffs into history_version.

Why this exists
---------------
`history_version/` in 1030.ver4 was verified complete for every launcher and
every *named* HANDOFF file from 1027 onward. Two gaps remained:

1. `1025.ver1/handoff/` (HANDOFF.json / HANDOFF.md and their quota_monitor
   copies) had never been archived anywhere in the tree.
2. Each version from 1026.ver1 to 1027.ver5 carried its own revision of
   `LOCAL_AGENT_HANDOFF.md`; only the final 12,492-byte revision (1028 onward)
   was preserved.

This script copies those files byte for byte into
`history_version/from_previous_versions/<version>/...`, re-hashes every copy to
prove it matches the source, and writes a manifest with source path, hash, size
and intent. It never edits a copied file and never touches a baseline.

Existing files are skipped, not overwritten. Byte-identical duplicates are
recorded as `duplicate_of` instead of being copied again.

Run: python tools/backfill_history_versions.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
TARGET_DIR = ROOT / 'history_version/from_previous_versions'
REPORT = ROOT / 'reports/归档补齐_1030ver4.json'

USER_REQUEST = '用户要求确认 history_version 内所有历史版本文件齐备'

# (source version directory, paths relative to that directory, intent)
SOURCES = [
    ('1025.ver1', ['handoff/HANDOFF.json', 'handoff/HANDOFF.md',
                   'handoff/quota_monitor_2026-10-25/HANDOFF.json',
                   'handoff/quota_monitor_2026-10-25/HANDOFF.md'],
     '1025 版交接包；此前任何版本目录都未保存，是唯一完全缺失的交接'),
    ('1026.ver1', ['LOCAL_AGENT_HANDOFF.md'], '1026.ver1 交接修订版'),
    ('1026.ver2', ['LOCAL_AGENT_HANDOFF.md'], '1026.ver2 交接修订版'),
    ('1027.ver1', ['LOCAL_AGENT_HANDOFF.md'], '1027.ver1 交接修订版'),
    ('1027.ver2', ['LOCAL_AGENT_HANDOFF.md'], '1027.ver2 交接修订版'),
    ('1027.ver3', ['LOCAL_AGENT_HANDOFF.md'], '1027.ver3 交接修订版'),
    ('1027.ver4', ['LOCAL_AGENT_HANDOFF.md'], '1027.ver4 交接修订版'),
    ('1027.ver5', ['LOCAL_AGENT_HANDOFF.md'], '1027.ver5 交接修订版'),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_plan() -> list[dict]:
    entries: list[dict] = []
    seen: dict[str, str] = {}
    for version, rels, intent in SOURCES:
        for rel in rels:
            source = PARENT / f'AI_Banking_Agent_{version}' / rel
            if not source.is_file():
                entries.append({'source_version': version, 'source': str(source),
                                'status': 'missing_source', 'intent': intent})
                continue
            digest = sha256(source)
            entry = {
                'source_version': version,
                'source': str(source),
                'target': f'history_version/from_previous_versions/{version}/{rel}',
                'sha256': digest,
                'size': source.stat().st_size,
                'intent': intent,
            }
            first = seen.get(digest)
            if first is not None:
                entry['status'] = 'duplicate'
                entry['duplicate_of'] = first
            else:
                seen[digest] = entry['target']
                entry['status'] = 'copy'
            entries.append(entry)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='补齐 history_version 缺口')
    parser.add_argument('--dry-run', action='store_true')
    options = parser.parse_args(argv)

    entries = build_plan()
    copied, duplicated, failed = [], [], []
    for entry in entries:
        if entry['status'] == 'missing_source':
            failed.append(entry)
            continue
        if entry['status'] == 'duplicate':
            duplicated.append(entry)
            continue
        target = ROOT / entry['target']
        if target.exists():
            # 已存在：只校验，不覆盖。
            entry['status'] = 'present' if sha256(target) == entry['sha256'] else 'conflict'
            if entry['status'] == 'conflict':
                failed.append(entry)
            else:
                copied.append(entry)
            continue
        if options.dry_run:
            copied.append({**entry, 'status': 'would_copy'})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry['source'], target)
        actual = sha256(target)
        if actual != entry['sha256']:
            failed.append({**entry, 'status': 'hash_mismatch', 'target_sha256': actual})
            continue
        copied.append({**entry, 'status': 'copied'})

    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    manifest = {
        'generated_by': 'tools/backfill_history_versions.py',
        'generated_at': now,
        'user_request': USER_REQUEST,
        'method': '逐字节复制后重算 SHA-256 比对；不覆盖已存在文件；不改写任何历史基线',
        'not_a_baseline_edit': '基线 JSON 未改动，本清单只新增历史材料副本',
        'entries': entries,
        'summary': {
            'planned': len(entries),
            'copied_or_present': len(copied),
            'duplicates_skipped': len(duplicated),
            'failed': len(failed),
        },
    }
    if not options.dry_run:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        (TARGET_DIR / 'MANIFEST.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        REPORT.write_text(
            json.dumps({**manifest, 'report_note': '归档补齐核对报告；与 MANIFEST 同源'},
                       ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(manifest['summary'], ensure_ascii=False))
    for item in failed:
        print('FAILED', item.get('status'), item.get('target') or item.get('source'))
    for item in duplicated:
        print('DUP', item['target'], '==', item['duplicate_of'])
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
