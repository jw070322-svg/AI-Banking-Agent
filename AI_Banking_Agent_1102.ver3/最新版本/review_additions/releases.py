"""Local operator review bundles; no browser endpoint and no automatic KB promotion.

Reviewer names are local audit labels, not authenticated bank employee identities.
Bundles reference existing verified corpus excerpts, never customer observations.
"""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from first_agent.service import BASE, canonical, Fault
from .experience import now

class Releases:
    def __init__(self, path, knowledge=BASE/'knowledge'):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.knowledge=Path(knowledge)
        with self.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,author TEXT,body TEXT,state TEXT,reviewer TEXT);
                CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,candidate TEXT UNIQUE,body TEXT,at TEXT);
                CREATE TABLE IF NOT EXISTS active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version TEXT);
                CREATE TABLE IF NOT EXISTS review_audit(id INTEGER PRIMARY KEY,action TEXT,object_id TEXT,operator TEXT,at TEXT);
            ''')

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,isolation_level=None,timeout=10)
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def actor(self, value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{2,39}',value):
            raise Fault('REVIEW_ID','需要本地审核者标识（3至40位英文字母、数字或下划线）')
        return value

    def source(self, chunk_id):
        index=json.loads((self.knowledge/'index.json').read_text(encoding='utf-8'))
        chunk=next((c for c in index['chunks'] if c['id']==chunk_id),None)
        if not chunk:raise Fault('REVIEW_SOURCE','只能引用当前知识库中已有的片段')
        doc=next(d for d in index['documents'] if d['id']==chunk['document_id'])
        path=(self.knowledge/doc['path']).resolve()
        if not path.is_relative_to(self.knowledge.resolve()):raise Fault('REVIEW_SOURCE','资料路径无效')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=doc['sha256']:raise Fault('REVIEW_SOURCE','原文哈希已变化')
        if '\n'.join(raw.decode('utf-8-sig').splitlines()[chunk['start_line']-1:chunk['end_line']]).strip()!=chunk['text'].strip():
            raise Fault('REVIEW_SOURCE','原文行号与索引不一致')
        if doc.get('valid_until') and doc['valid_until']<date.today().isoformat():raise Fault('REVIEW_SOURCE','资料已过期')
        return {'chunk_id':chunk_id,'document_id':doc['id'],'document_sha256':doc['sha256'],
                'revision':doc['revision'],'source_uri':doc['source_uri'],'kind':doc['kind'],
                'valid_from':doc.get('valid_from'),'valid_until':doc.get('valid_until'),
                'start_line':chunk['start_line'],'end_line':chunk['end_line'],'text':chunk['text']}

    def propose(self, author, chunk_ids):
        self.actor(author)
        if not isinstance(chunk_ids,list) or not 1<=len(chunk_ids)<=10 or len(set(chunk_ids))!=len(chunk_ids):
            raise Fault('REVIEW_SOURCE','请选择1至10个不同的原始片段')
        sources=[self.source(c) for c in chunk_ids]
        cid=str(uuid4());body={'sources':sources,'trust':'pending_human_review','purpose':'offline_review_bundle_not_live_knowledge'}
        with self.tx() as db:
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,NULL)',(cid,author,canonical(body),'pending'))
            db.execute('INSERT INTO review_audit(action,object_id,operator,at) VALUES(?,?,?,?)',('proposed',cid,author,now()))
        return cid

    def approve(self, cid, reviewer, evaluation_path, human_checked=False):
        self.actor(reviewer)
        raw=Path(evaluation_path).read_bytes();report=json.loads(raw)
        checks=report.get('summary',{})
        if not human_checked or checks.get('citation_integrity_failures')!=0 or checks.get('ledger_unchanged') is not True or checks.get('questions',0)<1:
            raise Fault('REVIEW_CHECK','需要实际离线评测报告及独立人员逐条核对原文；测试分数不替代人工审核')
        with self.tx() as db:
            row=db.execute('SELECT author,body,state FROM candidates WHERE id=?',(cid,)).fetchone()
            if not row:raise Fault('NOT_FOUND','候选不存在',404)
            if row[0]==reviewer:raise Fault('REVIEW_SEPARATION','候选提交者不能审核自己的候选')
            if row[2]!='pending':raise Fault('REVIEW_STATE','候选已处理')
            body=json.loads(row[1])
            for source in body['sources']:
                if source!=self.source(source['chunk_id']):raise Fault('REVIEW_SOURCE','候选引用已变化')
            body.update(trust='operator_reviewed_demo_material',reviewer=reviewer,
                        evaluation_sha256=hashlib.sha256(raw).hexdigest(),human_checked=True,
                        release_effective_date=date.today().isoformat())
            db.execute('UPDATE candidates SET body=?,state=?,reviewer=? WHERE id=?',(canonical(body),'approved',reviewer,cid))
            db.execute('INSERT INTO review_audit(action,object_id,operator,at) VALUES(?,?,?,?)',('approved',cid,reviewer,now()))

    def publish(self,cid,operator):
        self.actor(operator)
        with self.tx() as db:
            row=db.execute('SELECT body,state FROM candidates WHERE id=?',(cid,)).fetchone()
            if not row or row[1]!='approved':raise Fault('REVIEW_REQUIRED','候选尚未审核通过')
            body=json.loads(row[0])
            for source in body['sources']:
                if source!=self.source(source['chunk_id']):raise Fault('REVIEW_SOURCE','候选引用已变化')
            old=db.execute('SELECT id FROM versions WHERE candidate=?',(cid,)).fetchone()
            if old:return old[0]
            version=str(uuid4())
            db.execute('INSERT INTO versions VALUES(?,?,?,?)',(version,cid,row[0],now()))
            db.execute('INSERT OR REPLACE INTO active VALUES(1,?)',(version,))
            db.execute('INSERT INTO review_audit(action,object_id,operator,at) VALUES(?,?,?,?)',('published',version,operator,now()))
        return version

    def rollback(self,version,operator):
        self.actor(operator)
        with self.tx() as db:
            row=db.execute('SELECT body FROM versions WHERE id=?',(version,)).fetchone()
            if not row:raise Fault('NOT_FOUND','版本不存在',404)
            for source in json.loads(row[0])['sources']:
                if source!=self.source(source['chunk_id']):raise Fault('REVIEW_SOURCE','旧版本资料已变化，不能直接恢复')
            db.execute('INSERT OR REPLACE INTO active VALUES(1,?)',(version,))
            db.execute('INSERT INTO review_audit(action,object_id,operator,at) VALUES(?,?,?,?)',('rollback',version,operator,now()))

    def current(self):
        with self.tx() as db:
            row=db.execute('SELECT v.id,v.body FROM versions v JOIN active a ON a.version=v.id').fetchone()
        return {'version':row[0],'bundle':json.loads(row[1])} if row else None

def main():
    parser=argparse.ArgumentParser(description='本地人工审核工具；发布的是审核材料版本，不自动修改助手知识库')
    parser.add_argument('--db',default=str(BASE/'runtime/review-releases.sqlite3'))
    parser.add_argument('--operator',required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('propose');p.add_argument('chunks',nargs='+')
    p=sub.add_parser('approve');p.add_argument('candidate');p.add_argument('--evaluation',required=True);p.add_argument('--human-checked',action='store_true')
    p=sub.add_parser('publish');p.add_argument('candidate')
    p=sub.add_parser('rollback');p.add_argument('version')
    sub.add_parser('current')
    args=parser.parse_args();store=Releases(args.db)
    try:
        if args.action=='propose':result=store.propose(args.operator,args.chunks)
        elif args.action=='approve':result=store.approve(args.candidate,args.operator,args.evaluation,args.human_checked)
        elif args.action=='publish':result=store.publish(args.candidate,args.operator)
        elif args.action=='rollback':result=store.rollback(args.version,args.operator)
        else:result=store.current()
        print(json.dumps({'result':result,'live_knowledge_changed':False},ensure_ascii=False,indent=2))
    except Fault as exc:parser.exit(1,exc.message+'\n')

if __name__=='__main__':main()
