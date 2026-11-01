"""Build reviewed, original glossary summaries, retrieval index and split data."""
from pathlib import Path
import csv, hashlib, json, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from first_agent.vendor.rag.corpus import build_index, digest
KNOW=ROOT/'knowledge'
SOURCES={
 '银行与现金流':('中国人民银行金融知识普及读本','https://guiyang.pbc.gov.cn/guiyang/113337/114084/3540759/2018051811593716305.pdf'),
 '基金与理财':('证监会基金投资者教育手册','https://www.csrc.gov.cn/xizang/c105485/c1304209/content.shtml'),
 '风险与组合':('证监局基金风险指标介绍','https://www.csrc.gov.cn/tianjin/c105377/c7bbc987b3f8c43a997f7f6f0c9bf2ae5/content.shtml'),
 '收益与估值':('美国证监会投资者教育词汇表','https://www.investor.gov/introduction-investing/investing-basics/glossary'),
 '股票与指数':('美国证监会投资者教育词汇表','https://www.investor.gov/introduction-investing/investing-basics/glossary'),
 '债券':('美国证监会投资者教育词汇表','https://www.investor.gov/introduction-investing/investing-basics/glossary'),
 '贷款与信用':('中国人民银行金融知识普及读本','https://guiyang.pbc.gov.cn/guiyang/113337/114084/3540759/2018051811593716305.pdf'),
 '宏观与市场':('中国人民银行金融知识普及读本','https://guiyang.pbc.gov.cn/guiyang/113337/114084/3540759/2018051811593716305.pdf'),
 '保险':('中国人民银行金融知识普及读本','https://guiyang.pbc.gov.cn/guiyang/113337/114084/3540759/2018051811593716305.pdf'),
 '支付与账户':('中国人民银行金融知识普及读本','https://guiyang.pbc.gov.cn/guiyang/113337/114084/3540759/2018051811593716305.pdf')}

def write(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    with (KNOW/'finance_terms.tsv').open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f,delimiter='\t'))
    if not rows: raise ValueError('空术语表')
    seen=set();terms=[];groups={}
    for row in rows:
        category,name,aliases,definition=(row[k].strip() for k in ('类别','术语','别名','释义'))
        if category not in SOURCES or not name or not definition or name in seen: raise ValueError('类别/术语重复或不完整: '+name)
        seen.add(name);title,url=SOURCES[category]
        item={'category':category,'term':name,'aliases':aliases.split('|') if aliases else [],
              'definition':definition,'source_title':title,'source_uri':url}
        terms.append(item);groups.setdefault(category,[]).append(item)
    manifest=json.loads((KNOW/'manifest.json').read_text(encoding='utf-8'))
    manifest['documents']=[d for d in manifest['documents'] if not d['id'].startswith('finance-2027-')]
    for i,(category,items) in enumerate(groups.items(),1):
        name=f'finance-{i:02}.md';text=f'# {category}金融术语\n\n本资料为面向演示用途的原创教学概括；官方投教链接为本类别相关参考，并非对每条释义的逐条背书。具体产品、法规和数值需核实。\n\n'
        for item in items: text+=f"## {item['term']}\n\n{item['definition']}\n\n别名：{'、'.join(item['aliases']) or '无'}\n\n"
        (KNOW/name).write_bytes(text.encode('utf-8'))
        title,url=SOURCES[category]
        manifest['documents'].append({'id':f'finance-2027-{i:02}','path':name,'title':category+'金融术语',
            'kind':'educational_demo','revision':'finance-glossary-2026-10-27-v1',
            'source_uri':url,'sha256':digest(text),'valid_from':None,'valid_until':None})
    write(KNOW/'finance_glossary.json',{'schema_version':1,'terms':terms})
    write(KNOW/'manifest.json',manifest)
    index=build_index(KNOW/'manifest.json',KNOW/'index.json')
    train=ROOT/'training';train.mkdir(exist_ok=True)
    split={'train':[],'holdout':[]}
    for item in terms:
        key=hashlib.sha256(item['term'].encode()).digest()[0]
        part='holdout' if key%5==0 else 'train'
        for prompt in (f"什么是{item['term']}？",f"请简要解释{item['term']}。"):
            split[part].append({'term':item['term'],'question':prompt,'answer':item['definition'],
                                'source_uri':item['source_uri'],'category':item['category']})
    for part,records in split.items():
        (train/(part+'.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records),encoding='utf-8')
    report={'term_count':len(terms),'category_count':len(groups),'indexed_documents':len(index['documents']),
            'indexed_chunks':len(index['chunks']),'train_examples':len(split['train']),'holdout_examples':len(split['holdout']),
            'split_method':'sha256 of canonical term; held-out terms absent from training',
            'all_financial_terms_claimed':False,'training_has_customer_data':False}
    write(ROOT/'reports/finance-knowledge-build.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
