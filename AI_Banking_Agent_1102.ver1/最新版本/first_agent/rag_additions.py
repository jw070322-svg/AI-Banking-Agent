"""Add-only sparse retrieval inspired by the reviewed simple_RAG(3).py.

The original RAG, source documents, chunks and successful answers are untouched.
This module has no file ingestion, networking, model calls or banking actions.
TF-IDF/cosine/Jaccard measure lexical similarity, not semantic understanding.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import log, sqrt
import re
from uuid import uuid4

from .vendor.rag.corpus import validate_date
from .vendor.rag.retrieval import tokenize
from .vendor.rag.service import RAGService


def lexical_overlap(left, right):
    """Jaccard overlap of distinct existing-tokenizer terms."""
    left, right = set(left), set(right)
    return len(left & right) / len(left | right) if left or right else 0.0


def sparse_cosine(left, right):
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    norm = sqrt(sum(v*v for v in left.values()) * sum(v*v for v in right.values()))
    return dot / norm if norm else 0.0


def _eligible(document, today, kinds):
    return not ((document.get('valid_from') and document['valid_from'] > today)
                or (document.get('valid_until') and document['valid_until'] < today)
                or (kinds is not None and document['kind'] not in kinds))


def _unsafe_for_additive_retrieval(question):
    # Scope the new script's additional relatives/colleagues patterns to requests
    # for actual private records; do not reject generic bank-card education.
    other = r'他人|别人|朋友|好友|家人|同事|丈夫|妻子|父母'
    private = r'余额|账单|流水|交易明细|身份证|手机号|银行卡号|账户'
    return bool(re.search(r'(?:'+other+r').{0,20}(?:'+private+r')', question)
                or re.search(r'直接(?:转账|扣款|退款)|\d{7,}|验证码|密码|api[_ -]?key|secret', question, re.I))


class SparseSupplement:
    def __init__(self, retriever):
        self.retriever = retriever
        self.counts = [Counter(tokenize(c['section']+'\n'+c['text'])) for c in retriever.chunks]
        df = Counter(t for counts in self.counts for t in counts)
        self.idf = {term: log((1+len(self.counts))/(1+count))+1 for term, count in df.items()}
        self.term_documents = {}
        for i,counts in enumerate(self.counts):
            for term in counts:self.term_documents.setdefault(term,set()).add(retriever.chunks[i]['document_id'])
        self.unknown_idf = log(1+len(self.counts))+1
        self.vectors = [{t: n/sum(counts.values())*self.idf[t] for t,n in counts.items()}
                        for counts in self.counts]

    def search(self, question, top_k=4, *, as_of=None, kinds=None):
        if not isinstance(question,str) or not question.strip() or len(question)>2000:
            raise ValueError('问题需要 1–2000 个字符')
        if type(top_k) is not int or not 1<=top_k<=10:
            raise ValueError('top_k 必须为 1–10')
        today = validate_date(as_of) if as_of is not None else datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        terms = Counter(tokenize(question))
        if not terms or _unsafe_for_additive_retrieval(question): return []
        # Keep out-of-vocabulary terms in the denominator: a single coincidental
        # word in a long unrelated query must not become a perfect similarity.
        total = sum(terms.values())
        query = {t: n/total*self.idf.get(t,self.unknown_idf) for t,n in terms.items()}
        candidates=[]
        for i,chunk in enumerate(self.retriever.chunks):
            document=self.retriever.documents[chunk['document_id']]
            if not _eligible(document,today,kinds): continue
            overlap=set(terms)&self.counts[i].keys()
            if not overlap: continue
            cosine=sparse_cosine(query,self.vectors[i])
            jaccard=lexical_overlap(terms,self.counts[i])
            coverage=len(overlap)/len(terms)
            # The literal English acronym exception can recover short technical
            # terms in otherwise unrecognized English wording. It must appear in
            # the original passage and be unique to one document in this corpus.
            acronyms=[t for t in overlap if re.fullmatch(r'[a-z][a-z0-9]{1,9}',t)
                      and re.search(r'(?<![A-Za-z0-9])'+re.escape(t)+r'(?![A-Za-z0-9])',chunk['text'],re.I)]
            distinct_anchor=(bool(re.search(r'\bexplain\b|\bdefine\b|\bmeaning\b|\bdefinition\b|解释|什么是|是什么',question,re.I))
                             and any(len(self.term_documents[t])==1 for t in acronyms))
            ordinary_match=len(overlap)>=2 and coverage>=0.25 and cosine>=0.18
            acronym_match=distinct_anchor and coverage>=0.15 and cosine>=0.10
            if not (ordinary_match or acronym_match):
                continue
            score=cosine*5.0+jaccard*6.0
            candidates.append((score,i,cosine,jaccard,coverage))
        selected=[];results=[]
        for score,i,cosine,jaccard,coverage in sorted(candidates,key=lambda x:(-x[0],self.retriever.chunks[x[1]]['id'])):
            c=self.retriever.chunks[i];d=self.retriever.documents[c['document_id']]
            # Use existing original chunks and source/line identifiers. Never
            # create another copy in the corpus or mix incompatible chunk IDs.
            if any(c['text'] in old['text'] or old['text'] in c['text'] for old in selected): continue
            selected.append(c)
            results.append({**c,'citation_id':f'S{len(results)+1}','title':d['title'],
                            'source_uri':d['source_uri'],'citation_uri':f"{d['source_uri']}#L{c['start_line']}-L{c['end_line']}",
                            'revision':d['revision'],'document_sha256':d['sha256'],'kind':d['kind'],
                            'valid_from':d.get('valid_from'),'valid_until':d.get('valid_until'),
                            'score':round(score,6),'cosine_score':round(cosine,6),
                            'lexical_overlap':round(jaccard,6),'query_coverage':round(coverage,4)})
            if len(results)>=top_k:break
        return results


class AdditiveRAGService:
    """Composition adapter: never replaces an existing nonempty answer."""
    def __init__(self, primary):
        self.primary=primary
        self.retriever=primary.retriever
        self.client=primary.client
        self.supplement=SparseSupplement(primary.retriever)

    def search(self, question, top_k=4, **kwargs):
        existing=self.primary.search(question,top_k,**kwargs)
        if existing or kwargs.get('hybrid'): return existing
        return self.supplement.search(question,top_k,as_of=kwargs.get('as_of'),kinds=kwargs.get('kinds'))

    def ask(self, question, top_k=4, **kwargs):
        existing=self.primary.ask(question,top_k,**kwargs)
        # Do not bypass personal-account routing, rejected generation, explicit
        # hybrid mode, or model abstention over existing evidence.
        if (existing.get('status')!='no_evidence' or existing.get('evidence')
                or kwargs.get('hybrid') or kwargs.get('generation_model')):
            return existing
        evidence=self.supplement.search(question,top_k,as_of=kwargs.get('as_of'),kinds=kwargs.get('kinds'))
        if not evidence:return existing
        query=set(tokenize(question));parts=[];used=[]
        for item in evidence:
            lines=[(i,line) for i,line in enumerate(item['text'].splitlines())
                   if line.strip() and not re.match(r'^\s*(#|[-|\s:]+$)',line)]
            if not lines:continue
            selected=sorted(sorted(lines,key=lambda x:(-len(query&set(tokenize(x[1]))),x[0]))[:2])
            excerpt='\n'.join(line for _,line in selected)
            if len(excerpt)>650:excerpt=excerpt[:650]+'…'
            parts.append(f"[{item['citation_id']}] {item['section'] or item['title']}\n{excerpt}")
            used.append(item)
        if not used:return existing
        warnings=list(existing.get('warnings',[]))+['补充检索采用词项相似度，分数不是事实正确率；请核对原始证据。']
        if any(e['kind']=='project_design' for e in used):
            warnings.append('引用包含项目设计资料，不能证明相关功能已实现，也不代表真实银行条款或现行法规。')
        if any(not e.get('valid_until') for e in used):warnings.append('部分资料未提供有效期；当前业务适用性仍需核验。')
        return {**existing,'status':'grounded','retrieval_mode':'tfidf_additive','generation_mode':'extractive',
                'answer':'以下为补充检索找到的原文摘录：\n\n'+'\n\n'.join(parts),
                'evidence':used,'citations':[RAGService._citation(e) for e in used],'warnings':warnings,'tool_calls':[]}


def compatibility_response(result, top_k=3):
    """Opt-in new-script-shaped projection; existing API contracts stay intact."""
    evidence=result.get('evidence',[])
    return {'schema_version':'1.0.0','request_id':uuid4().hex,'status':'succeeded',
            'data':{'status':result['status'],'answer':result['answer'],
                    'evidence':[{'source':e['source_uri'],'title':e['title'],'score':e['score'],
                                 'snippet':e['text'][:360]} for e in evidence],
                    'sources':list(dict.fromkeys(e['source_uri'] for e in evidence)),
                    'risk_notice':'通用资料检索，不代表账户数据、实时行情或执行授权。'},
            'error':None,'trace':{'top_k':top_k,'evidence_count':len(evidence),
                                'retrieval_mode':result.get('retrieval_mode'),'question_logged':False},'simulated':True}
