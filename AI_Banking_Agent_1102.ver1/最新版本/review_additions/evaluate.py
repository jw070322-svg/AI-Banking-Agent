"""Reproducible offline evaluation; reference answers are never ingested into RAG."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from unittest.mock import patch
import hashlib
import html
import json
import re
import tempfile

from first_agent.service import BASE, canonical
from first_agent.vendor.rag.service import RAGService
from first_agent.rag_additions import AdditiveRAGService
from .runtime import ReviewService
from .experience import now

REPORT = BASE / 'reports/review-continuation'
DATA = BASE / 'evaluation/yuki_1029'
SOURCE = BASE / 'sources/incoming_yuki_1029'

def structured_cases():
    existing = json.loads((DATA / 'cases.json').read_text(encoding='utf-8'))
    cases = deepcopy(existing['cases'])
    by_question = {c['question']: c for c in cases}
    text = (SOURCE / '评测题库.md').read_text(encoding='utf-8')
    lines = text.splitlines()
    special = []; mirrored = 0; variants = 0
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith('### ')]
    for position, (i, heading) in enumerate(headings):
        end = headings[position+1][0] if position+1 < len(headings) else len(lines)
        block = lines[i+1:end]
        if re.match(r'### 3\.\d+ 题 ', heading):
            for offset, line in enumerate(block, i+1):
                m = re.fullmatch(r'\s+- “(.+)”', line)
                if not m: continue
                question = m.group(1)
                occurrence = {'file':'评测题库.md','line':offset+1,'section':heading[4:],
                              'criteria_verbatim':'\n'.join(block)}
                if question in by_question:
                    by_question[question]['occurrences'].append(occurrence)
                else:
                    case = {'id':'SPECIAL-'+hashlib.sha256(question.encode()).hexdigest()[:12],
                        'question':question,'category':'special','occurrences':[occurrence],
                        'status':'not_evaluated','usage':'evaluation_only_not_training_or_knowledge'}
                    similar = sorted(((SequenceMatcher(None,question,c['question']).ratio(), c['id']) for c in cases), reverse=True)
                    case['related_not_merged'] = [{'id':cid,'text_similarity':round(score,3)} for score,cid in similar[:3] if score>=.35]
                    cases.append(case);by_question[question]=case
                special.append({'question':question,'line':offset+1})
        elif re.match(r'### \d+\. ', heading):
            question = re.sub(r'^### \d+\. ', '', heading)
            occurrence={'file':'评测题库.md','line':i+1,'criteria_verbatim':'\n'.join(block).strip()}
            if question in by_question:
                by_question[question]['occurrences'].append(occurrence);mirrored+=1
            else:
                similar = sorted(((SequenceMatcher(None,question,c['question']).ratio(), c['id']) for c in cases), reverse=True)
                case = {'id':'VARIANT-'+hashlib.sha256(question.encode()).hexdigest()[:12],
                    'question':question,'category':'consolidated_variant','occurrences':[occurrence],
                    'status':'not_evaluated','usage':'evaluation_only_not_training_or_knowledge',
                    'related_not_merged':[{'id':cid,'text_similarity':round(score,3)} for score,cid in similar[:3] if score>=.35]}
                cases.append(case);by_question[question]=case;variants+=1
    output = {'source_kind':existing['source_kind'],'cases':cases,'additional_cases':existing['additional_cases'],
              'core_unique':len(existing['cases']),'special_occurrences':len(special),
              'consolidated_core_occurrences':mirrored,'consolidated_new_variants':variants,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
              'all_special_examples_structured':True,'usage':'evaluation_only_not_training_or_knowledge'}
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT/'cases-complete.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    return output

def inspect_answer(result, retriever):
    """Structural provenance checks only. NO keyword-based claim of semantic accuracy."""
    errors=[]; checked=0; documents=retriever.documents
    chunks={c['id']:c for c in retriever.chunks}
    for evidence in result.get('evidence',[]):
        chunk=chunks.get(evidence.get('id'));doc=documents.get(evidence.get('document_id'))
        if not chunk or not doc:
            errors.append('unknown_chunk_or_document');continue
        raw=(BASE/'knowledge'/doc['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=doc['sha256']:
            errors.append('source_hash_mismatch')
        for key in ('text','start_line','end_line','document_id'):
            if evidence.get(key)!=chunk.get(key):errors.append('chunk_'+key+'_mismatch')
        lines=raw.decode('utf-8-sig').splitlines()
        original='\n'.join(lines[chunk['start_line']-1:chunk['end_line']]).strip()
        if original!=chunk['text'].strip():errors.append('source_line_mismatch')
        if evidence.get('document_sha256')!=doc['sha256']:errors.append('citation_hash_mismatch')
        checked+=1
    evidence_ids={e['citation_id']:e for e in result.get('evidence',[])}
    cited=set()
    for cite in result.get('citations',[]):
        e=evidence_ids.get(cite.get('citation_id'))
        if not e or any(cite.get(k)!=e.get(k) for k in ('document_id','start_line','end_line','document_sha256')):
            errors.append('citation_mismatch')
        cited.add(cite.get('citation_id'))
    markers=set(re.findall(r'\[(S\d+)\]',result.get('answer','')))
    if markers!=cited:errors.append('answer_citation_marker_mismatch')
    if result.get('status')=='grounded' and not cited:errors.append('grounded_without_citation')
    if result.get('tool_calls'):errors.append('unexpected_tool_call')
    return {'source_integrity':'passed' if not errors else 'failed','checked_evidence':checked,
            'errors':errors,'semantic_score':None,'semantic_status':'requires_human_review',
            'note':'原文、行号、哈希和引用对应检查，不等于回答正确或业务适当性通过'}

def run():
    dataset=structured_cases(); rows=[]
    baseline=AdditiveRAGService(RAGService(BASE/'knowledge/index.json'))
    with tempfile.TemporaryDirectory() as tmp:
        service=ReviewService(Path(tmp)/'evaluation.sqlite3');sid=service.create_session()
        with service.transaction() as db:
            before=db.execute('SELECT state FROM sessions WHERE sid=?',(sid,)).fetchone()[0]
        # Exercise the real knowledge service; block any remote fallback.
        with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_evaluation'}):
            for case in dataset['cases']:
                q=case['question']; old=baseline.ask(q,3)
                reply=service.call(sid,'knowledge',{'question':q,'top_k':3},case['id'])
                current=reply.get('data') or {'status':reply['status'],'answer':(reply.get('error') or {}).get('message',''),'citations':[],'evidence':[]}
                checks=inspect_answer(current,service.rag.retriever)
                rows.append({'id':case['id'],'question':q,'category':case['category'],
                    'baseline':old,'current':current,'envelope_status':reply['status'],'checks':checks,
                    'criteria_sources':case['occurrences']})
        with service.transaction() as db:
            after=db.execute('SELECT state FROM sessions WHERE sid=?',(sid,)).fetchone()[0]
        summary={'evaluated_at':now(),'questions':len(rows),'baseline_statuses':dict(Counter(x['baseline']['status'] for x in rows)),
                 'current_statuses':dict(Counter(x['current']['status'] for x in rows)),
                 'citation_integrity_failures':sum(x['checks']['source_integrity']=='failed' for x in rows),
                 'ledger_unchanged':before==after,'human_scoring_pending':len(rows),
                 'semantic_pass_rate':None,'network':'disabled_for_evaluation','model':'local extractive baseline; no LLM evaluated',
                 'statement':'不能把可追溯引用当成回答正确率；工程24项另见验收映射'}
        report={'summary':summary,'results':rows}
        (REPORT/'rag-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        e=html.escape
        blocks=[]
        for row in rows:
            source=row['current'].get('evidence',[])
            blocks.append('<details><summary>'+e(row['id']+' · '+row['question'])+'</summary><p>原版状态：'+e(row['baseline']['status'])+' → 当前：'+e(row['current']['status'])+'</p><p>引用结构核对：'+e(row['checks']['source_integrity'])+'；人工评分：待核对</p><pre>'+e(row['current'].get('answer',''))+'</pre><p>来源：'+e('、'.join(s['title'] for s in source) or '无引用')+'</p><details><summary>评分要求与原始位置</summary><pre>'+e(json.dumps(row['criteria_sources'],ensure_ascii=False,indent=2))+'</pre></details></details>')
        page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>知识问答核对</title><style>body{max-width:1000px;margin:40px auto;padding:20px;font:16px/1.65 system-ui;color:#19314e;background:#f3f6fb}details{padding:16px;background:white;border:1px solid #d9e1ee;border-radius:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h1{font-size:28px}</style><h1>知识问答核对</h1><p>共'+str(len(rows))+'题，已经实际运行。这里只自动检查来源与引用，所有回答仍需按原评分要求人工核对。不能据此宣称全部通过安全自评。</p><p>该报告包含测试指令，仅供评测，不是用户产品页面。</p>'+''.join(blocks)+'</html>'
        (REPORT/'知识问答核对.html').write_text(page)
        print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    from start import prepare_node
    prepare_node();run()
