"""Install official llama.cpp CPU release and official Qwen GGUF under F:\\AI_Banking.
Only hashes from the publishers' metadata are accepted. No credentials needed.
"""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib, json, shutil, zipfile

ROOT=Path(r'F:\AI_Banking\local-ai')
ROOT.mkdir(parents=True,exist_ok=True)
def fetch_json(url):
    with urlopen(Request(url,headers={'User-Agent':'AI-Banking-Installer'}),timeout=30) as r: return json.load(r)
def download(url,path,expected,headers=None):
    if path.exists() and hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==expected: return
    temp=path.with_suffix(path.suffix+'.part')
    with urlopen(Request(url,headers={'User-Agent':'AI-Banking-Installer',**(headers or {})}),timeout=60) as r:
        if 'json' in r.headers.get('Content-Type',''): raise RuntimeError('Download returned metadata instead of binary')
        h=hashlib.sha256();size=0;next_report=64*1024*1024
        with temp.open('wb') as out:
            while True:
                block=r.read(1024*1024)
                if not block: break
                out.write(block);h.update(block);size+=len(block)
                if size>=next_report: print(path.name,round(size/1024/1024),'MiB',flush=True);next_report+=64*1024*1024
    if h.hexdigest()!=expected: raise RuntimeError('Publisher SHA-256 mismatch')
    temp.replace(path);print('Verified',path.name,flush=True)

release=fetch_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11900')
asset=next(a for a in release['assets'] if a['name'].endswith('bin-win-cpu-x64.zip'))
digest=asset['digest'].removeprefix('sha256:')
archive=ROOT/asset['name']
# The official asset API serves the same publisher-signed public release.
download(asset['url'],archive,digest,{'Accept':'application/octet-stream'})
install=ROOT/'llama-b11900'
with zipfile.ZipFile(archive) as z:
    for name in z.namelist():
        if not (install/name).resolve().is_relative_to(install.resolve()): raise RuntimeError('Unsafe archive member')
    z.extractall(install)
print('Runtime installed',install,flush=True)
model=fetch_json('https://huggingface.co/api/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF?blobs=true')
entry=next(x for x in model['siblings'] if x['rfilename']=='qwen2.5-0.5b-instruct-q4_k_m.gguf')
model_path=ROOT/entry['rfilename']
source='https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/'+model['sha']+'/'+entry['rfilename']
download(source,model_path,entry['lfs']['sha256'])
receipt={'runtime':'llama.cpp','version':release['tag_name'],'archive_sha256':digest,
         'server':str(next(install.rglob('llama-server.exe'))),'model':str(model_path),
         'model_source':source,'model_sha256':entry['lfs']['sha256'],'alias':'banking-qwen2.5-0.5b'}
(ROOT/'llama-installation.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print('Installation complete',flush=True)
