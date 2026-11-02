"""Portable verification of historical sources against a published path manifest.
Manifests/ledgers are local provenance, not signed third-party attestations.
"""
from pathlib import Path,PurePosixPath
import hashlib,json,posixpath,re

def safe_relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:
        raise ValueError('非法发布路径')
    parts=PurePosixPath(value).parts
    if value.startswith('/') or any(p in {'.','..'} for p in value.split('/')):
        raise ValueError('发布路径不能越界')
    return '/'.join(parts)

def local_file(root,relative):
    rel=safe_relative(relative);path=root/rel
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('发布路径越界')
    cursor=root
    for part in PurePosixPath(rel).parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('发布文件不接受符号链接')
    return path

def runtime_artifact(rel):
    p=PurePosixPath(rel)
    return p.suffix in {'.sqlite3','.sqlite','.db','.pyc'} or '__pycache__' in p.parts

def archived_document(rel,target):
    p=PurePosixPath(rel);t=PurePosixPath(target)
    return len(p.parts)==1 and (p.suffix in {'.bat','.command'} or p.name.startswith(('README','先看这里'))) and t.parts[0]=='history_version' and t.name==p.name

def verify_publication(root,baseline,manifest=None,changes=None):
    root=Path(root);manifest=manifest or {};changes=changes or {}
    mappings=manifest.get('mappings',{});omitted=set(manifest.get('omitted_runtime_and_cache',[]))
    if not isinstance(mappings,dict):raise ValueError('发布清单格式无效')
    prefix=manifest.get('root_prefix')
    if mappings and not prefix:
        prefix=posixpath.commonpath([safe_relative(v) for v in mappings.values()]).rstrip('/')+'/'
    if prefix:prefix=safe_relative(prefix.rstrip('/'))+'/'
    checked=[];excluded=[];modified=[]
    for rel,expected in baseline.items():
        safe_relative(rel)
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('基线哈希无效')
        mapped=rel
        if rel in mappings:
            archive_path=safe_relative(mappings[rel])
            if not prefix or not archive_path.startswith(prefix):raise ValueError('发布根路径不匹配')
            mapped=safe_relative(archive_path[len(prefix):])
            if mapped!=rel and not archived_document(rel,mapped):raise ValueError('未允许的源码迁移: '+rel)
        if rel in omitted and runtime_artifact(rel):
            excluded.append(rel);continue
        path=local_file(root,mapped)
        if not path.is_file():
            if rel in omitted and runtime_artifact(rel):excluded.append(rel);continue
            raise ValueError('未登记缺失: '+rel+' -> '+mapped)
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        change=changes.get(rel)
        if actual!=expected:
            if not isinstance(change,dict) or change.get('before')!=expected or change.get('after')!=actual or not change.get('reason'):
                raise ValueError('哈希不符或未登记改动: '+rel)
            modified.append({'file':rel,**change})
        # A relocated valid archive must not hide a modified original source/path.
        original=local_file(root,rel)
        if mapped!=rel and original.is_file() and hashlib.sha256(original.read_bytes()).hexdigest()!=expected:
            raise ValueError('原址存在未登记的不同副本: '+rel)
        checked.append({'source':rel,'published':mapped,'sha256':actual})
    return {'checked':len(checked),'files':checked,'excluded_runtime':excluded,'authorized_changes':modified,'unexpected_changes':[]}

def verify_project(root):
    root=Path(root);report=root/'reports/security-integration-1101'
    baseline=json.loads((report/'input-hashes.json').read_text())
    manifest=json.loads((report/'package-manifest.json').read_text()) if (report/'package-manifest.json').is_file() else {}
    ledger=root/'reports/g01-d01-fix/authorized-changes.json'
    changes=json.loads(ledger.read_text()).get('changes',{}) if ledger.is_file() else {}
    return verify_publication(root,baseline,manifest,changes)
