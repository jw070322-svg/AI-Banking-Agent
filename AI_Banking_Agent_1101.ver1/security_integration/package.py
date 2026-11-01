"""Package the relocatable release and verify every bundled model dependency."""
from hashlib import sha256
from pathlib import Path
import json
import zipfile
from .publication import verify_project

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'AI_Banking_Agent_1101.ver1'


def digest(path):
    with path.open('rb') as stream:
        result = sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    verify_project(ROOT)
    manifest = json.loads((ROOT / 'model-assets/manifest.json').read_text(encoding='utf-8'))
    for asset in manifest['files']:
        path = ROOT / asset['path']
        if not path.is_file() or digest(path) != asset['sha256']:
            raise ValueError(f"Missing or damaged model file: {asset['path']}")

    target = ROOT.parent / (VERSION + '.zip')
    temporary = target.with_suffix('.zip.part')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for path in sorted(ROOT.rglob('*')):
            rel = path.relative_to(ROOT)
            if not path.is_file() or {'runtime', '__pycache__', '.git'} & set(rel.parts):
                continue
            if path.suffix.lower() in {'.key', '.pyc', '.sqlite3', '.sqlite', '.db'} or path.name.endswith(('-wal', '-shm', '-journal')):
                continue
            archive.write(path, f'{VERSION}/{rel.as_posix()}')
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f'Corrupt ZIP member: {bad}')
    temporary.replace(target)
    target.with_suffix('.zip.sha256').write_text(digest(target) + '  ' + target.name + '\n', encoding='ascii')
    print(target)


if __name__ == '__main__':
    main()
