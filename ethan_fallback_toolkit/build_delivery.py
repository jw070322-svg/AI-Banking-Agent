"""Create a self-contained ZIP and content manifest; never includes caches."""
from pathlib import Path
import argparse,hashlib,json,zipfile

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--force',action='store_true')
    args=parser.parse_args();target=Path(args.output).resolve()
    if target==ROOT or ROOT in target.parents:raise ValueError('archive output must be outside toolkit directory')
    if target.exists() and not args.force:raise FileExistsError('archive exists; use --force to replace the generated archive')
    files=[p for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and '.test_runtime' not in p.parts and p.suffix!='.pyc' and p.name!='file_manifest.json']
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    m=ROOT/'reports/file_manifest.json';m.write_text(json.dumps({'sha256':manifest,'conclusion':'SHA-256 covers all delivery files except this manifest and caches'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w' if args.force else 'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files+[m]:z.write(p,'ethan_fallback_toolkit/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for path,digest in manifest.items():assert hashlib.sha256(z.read('ethan_fallback_toolkit/'+path)).hexdigest()==digest
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix+'.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(target),'files':len(files)+1,'sha256':digest,'conclusion':'archive and member hashes verified'},ensure_ascii=False))


if __name__=='__main__':main()
