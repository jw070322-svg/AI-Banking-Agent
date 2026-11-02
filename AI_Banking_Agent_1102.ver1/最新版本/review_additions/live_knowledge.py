"""Opt-in local approved-bundle activation; does not grant real employee identity."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from first_agent.service import BASE, Fault
from first_agent.vendor.rag.corpus import index_digest,write_json
from first_agent.vendor.rag.service import RAGService
from .releases import Releases

class LiveKnowledge:
    def __init__(self, database):
        if not Path(database).is_file():raise Fault('REVIEW_REQUIRED','审核数据库不存在，不能开启审核知识模式')
        self.store=Releases(database)

    def snapshot(self):
        current=self.store.current()
        if not current:raise Fault('REVIEW_REQUIRED','尚无已发布审核版本，当前不提供知识回答')
        body=current['bundle']
        if body.get('human_checked') is not True or body.get('trust')!='operator_reviewed_demo_material':
            raise Fault('REVIEW_REQUIRED','知识版本缺少审核记录')
        ids=set()
        for source in body['sources']:
            if self.store.source(source['chunk_id'])!=source:
                raise Fault('REVIEW_SOURCE','知识原文已改变，暂停使用该版本')
            ids.add(source['chunk_id'])
        index=json.loads((BASE/'knowledge/index.json').read_text(encoding='utf-8'))
        keep=[i for i,c in enumerate(index['chunks']) if c['id'] in ids]
        index['chunks']=[index['chunks'][i] for i in keep]
        if index.get('vectors') is not None:index['vectors']=[index['vectors'][i] for i in keep]
        docs={c['document_id'] for c in index['chunks']}
        index['documents']=[d for d in index['documents'] if d['id'] in docs]
        index['content_sha256']=index_digest(index)
        return current['version'],index

    def ask(self, question, top_k=4, **kwargs):
        from .runtime import ReviewRAG
        version,index=self.snapshot()
        # A per-request immutable snapshot avoids version races and leaves the source intact.
        with TemporaryDirectory() as folder:
            path=Path(folder)/'index.json';write_json(path,index)
            result=ReviewRAG(RAGService(path)).ask(question,top_k,**kwargs)
        result['review_version']=version
        result['warnings']=result.get('warnings',[])+['本地审核标识不是银行员工身份认证；仅使用该版本已核对片段']
        return result
