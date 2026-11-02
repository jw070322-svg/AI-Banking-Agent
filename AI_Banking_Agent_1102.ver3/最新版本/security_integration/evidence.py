"""Relocation-stable source fingerprint and explicit test execution times."""
from pathlib import Path
import hashlib

def source_fingerprint(root):
    root=Path(root);rows=[]
    folders=['first_agent','security_integration','review_additions','relay_additions','live_products','live_indices','ui_fix','web']
    for folder in folders:
        for f in (root/folder).rglob('*'):
            if f.is_file() and f.suffix in {'.py','.js','.cjs','.css','.html'} and '__pycache__' not in f.parts:
                rows.append(f.relative_to(root).as_posix()+':'+hashlib.sha256(f.read_bytes()).hexdigest())
    return hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()
