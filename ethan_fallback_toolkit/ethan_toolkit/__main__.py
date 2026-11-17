"""UTF-8 JSON CLI; no network, no implicit overwrites."""
import argparse
import json
from pathlib import Path
import sys
from .tools import call_tool,catalog


def load_json(path):
    def reject_constant(value):raise ValueError('non-finite JSON numbers are forbidden: '+value)
    def unique_pairs(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate JSON key: '+k)
            result[k]=v
        return result
    p=Path(path)
    if p.stat().st_size>20_000_000:raise ValueError('input JSON exceeds 20 MB')
    return json.loads(p.read_text(encoding='utf-8-sig'),parse_constant=reject_constant,object_pairs_hook=unique_pairs)


def save(path,content,force=False):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w' if force else 'x',encoding='utf-8',newline='') as f:f.write(content)


def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='Ethan offline fallback toolkit')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('tools')
    gen=sub.add_parser('generate');gen.add_argument('kind',choices=list('ABCDE'));gen.add_argument('--seed',type=int,default=42)
    gen.add_argument('--as-of',required=True);gen.add_argument('--increase-minor',type=int,default=80000)
    invoke=sub.add_parser('call');invoke.add_argument('tool');invoke.add_argument('--input',required=True)
    validate=sub.add_parser('validate');validate.add_argument('input')
    for p in [gen,invoke,validate]:p.add_argument('--output');p.add_argument('--force',action='store_true')
    demo=sub.add_parser('demo');demo.add_argument('--output-dir',default='output/demo');demo.add_argument('--force',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='tools':result=catalog()
        elif args.command=='demo':
            from .demo import build_demo
            result=build_demo(args.output_dir,force=args.force)
        elif args.command=='generate':
            result=call_tool('generate_environment',{'scenario_type':args.kind,'seed':args.seed,'as_of':args.as_of,'increase_minor':args.increase_minor})
            if result['status']=='succeeded':result=result['data']
        elif args.command=='validate':result=call_tool('validate_environment',{'data':load_json(args.input)})
        else:result=call_tool(args.tool,load_json(args.input))
        content=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        if getattr(args,'output',None):save(args.output,content,args.force)
        else:print(content,end='')
        return 2 if isinstance(result,dict) and result.get('status')=='rejected' else 0
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'rejected','error':{'code':'CLI_ERROR','message':str(exc)}},ensure_ascii=False))
        return 2


if __name__=='__main__':sys.exit(main())
