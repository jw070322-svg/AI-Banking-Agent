"""Conservative grounded definitions from an explicitly authored local glossary."""
from functools import lru_cache
from pathlib import Path
import json, re, unicodedata

PATH=Path(__file__).resolve().parents[1]/'knowledge'/'finance_glossary.json'
@lru_cache(maxsize=1)
def entries():
    data=json.loads(PATH.read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or not isinstance(data.get('terms'),list): raise ValueError('术语表无效')
    return data['terms']

def normalize(value): return unicodedata.normalize('NFKC',value).lower()

def answer(question):
    if not isinstance(question,str) or len(question)>500: return None
    q=normalize(question).strip()
    if not q:return None
    # Only answer explanations or a bare term; account/transaction requests use business tools.
    explain=bool(re.search(r'什么是|是什么|什么叫|解释|含义|什么意思|怎么理解|怎么算|如何计算|定义|区别|不同|对比|比较|概念|介绍',q))
    candidates=[]
    for item in entries():
        for alias in [item['term']]+item['aliases']:
            key=normalize(alias)
            if key==q or (explain and key in q): candidates.append((len(key),key,item))
    if not candidates:return None
    candidates.sort(key=lambda x:-x[0]);masked=q;selected=[]
    for _,key,item in candidates:
        if key in masked and all(x['term']!=item['term'] for x in selected):
            if len(selected)>=3:return None
            selected.append(item);masked=masked.replace(key,' ',1)
    # Reject residual unknown subject words rather than mislabeling e.g. a convertible bond as a bond.
    residue=re.sub(r'我想了解|我想知道|是什么意思|什么是|是什么|什么叫|解释一下|解释|请问|请|介绍一下|介绍|怎么理解|如何理解|怎么算|如何计算|计算方法|公式|含义|什么意思|定义|有何|有什么|有哪些|区别|不同|对比|比较|概念|请教|能否|可以|一下|之间|和|跟|与|及|的|吗|呢|是|如何看待|如何|怎么|分别|[\s?？,，。.!！:：、/（）()]+','',masked)
    if residue:return None
    citations=[]
    for item in selected:
        if item['source_uri'] not in [x['source_uri'] for x in citations]:
            citations.append({'title':item['source_title'],'source_uri':item['source_uri']})
    answer='\n\n'.join(item['term']+'：'+item['definition'] for item in selected)
    return {'status':'grounded','answer':answer,'citations':citations,'evidence':[],
            'generation_mode':'local_glossary','educational':True,
            'warnings':['通用知识解释，不代表产品条款、实时数据或个人投资建议；参考资料按领域归类，具体内容请结合原文核验。'],
            'matched_terms':[item['term'] for item in selected]}
