"""Build a reviewer package with relocatable model files and no runtime secrets."""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile, ZIP_DEFLATED
import json
from security_integration.publication import verify_project
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
OUTPUT = PROJECT.parent / (PROJECT.name + '.zip')

def digest(path):
    h = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    verify_project(ROOT)
    assets = json.loads((ROOT / 'model-assets/manifest.json').read_text(encoding='utf-8'))
    for asset in assets['files']:
        file = ROOT / asset['path']
        if not file.is_file() or digest(file) != asset['sha256']:
            raise ValueError('模型文件缺失或校验失败: ' + asset['path'])
    temporary = OUTPUT.with_suffix('.zip.part')
    with ZipFile(temporary, 'w', ZIP_DEFLATED, compresslevel=3) as archive:
        for file in sorted(PROJECT.rglob('*')):
            rel = file.relative_to(PROJECT)
            if not file.is_file() or {'runtime', '__pycache__', '.git'} & set(rel.parts):
                continue
            if file.suffix.lower() in {'.key', '.pyc', '.sqlite3', '.sqlite', '.db'} or file.name.endswith(('-wal', '-shm', '-journal')):
                continue
            archive.write(file, PROJECT.name + '/' + rel.as_posix())
    with ZipFile(temporary) as archive:
        if archive.testzip():
            raise ValueError('压缩包校验失败')
    temporary.replace(OUTPUT)
    OUTPUT.with_suffix('.zip.sha256').write_text(digest(OUTPUT) + '  ' + OUTPUT.name + '\n', encoding='utf-8')
    print(OUTPUT)

if __name__ == '__main__':
    main()
