"""Minimal session-private experience. Never stores arbitrary input or tool payloads.

This demo's identity is an HttpOnly session, NOT a verified person or bank login.
Learning consent is separate from mandatory banking audit and execution consent.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4
from first_agent.service import Fault, canonical

PAGES = {'overview', 'spending', 'wealth', 'tasks', 'other'}
CLIENT_ACTIONS = {'navigation', 'filter', 'search', 'open_detail', 'compare',
                  'plan_edit', 'preview', 'confirm_open', 'confirm_submit',
                  'confirm_close', 'cancel', 'form_submit', 'assistant_submit',
                  'permission_open', 'control', 'local_summary', 'local_eligibility',
                  'local_projection'}
RESULTS = {'succeeded', 'rejected', 'failed', 'cancelled', 'unknown', 'processing',
           'invalidated', 'awaiting_confirmation', 'needs_input'}

def now():
    return datetime.now(timezone.utc).isoformat()

def strict(body, required, optional=()):
    if not isinstance(body, dict) or set(body) - set(required) - set(optional) or not set(required) <= set(body):
        raise Fault('EXPERIENCE_SCHEMA', '记录格式不正确，请刷新后重试')

def uid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise Fault('EXPERIENCE_ID', '记录编号不正确')
    return value

class ExperienceStore:
    def __init__(self, service):
        self.service = service
        with service.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS xp_preferences(
                    sid TEXT PRIMARY KEY, enabled INTEGER NOT NULL, epoch TEXT NOT NULL,
                    changed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS xp_events(
                    sid TEXT NOT NULL, event_id TEXT NOT NULL, epoch TEXT NOT NULL,
                    source TEXT NOT NULL, action TEXT NOT NULL, phase TEXT NOT NULL,
                    status TEXT NOT NULL, page TEXT NOT NULL, request_id TEXT,
                    at TEXT NOT NULL, PRIMARY KEY(sid,event_id));
                CREATE TABLE IF NOT EXISTS xp_feedback(
                    sid TEXT NOT NULL, event_id TEXT NOT NULL, rating TEXT NOT NULL,
                    at TEXT NOT NULL, PRIMARY KEY(sid,event_id));
                CREATE TABLE IF NOT EXISTS xp_lifecycle(
                    id INTEGER PRIMARY KEY, sid TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS xp_attempt_results(
                    sid TEXT NOT NULL, attempt_id TEXT NOT NULL, result_event_id TEXT NOT NULL,
                    PRIMARY KEY(sid,attempt_id));
            ''')

    def _pref(self, db, sid):
        # Always authenticate through the existing server-side ledger.
        self.service.load(db, sid)
        row = db.execute('SELECT enabled,epoch FROM xp_preferences WHERE sid=?', (sid,)).fetchone()
        if not row:
            row = (0, str(uuid4()))
            db.execute('INSERT INTO xp_preferences VALUES(?,?,?,?)', (sid, *row, now()))
        return {'enabled': bool(row[0]), 'epoch': row[1]}

    def status(self, sid):
        with self.service.transaction() as db:
            pref = self._pref(db, sid)
            count = db.execute('SELECT COUNT(*) FROM xp_events WHERE sid=?', (sid,)).fetchone()[0]
        return {**pref, 'count': count, 'identity_scope': 'local_demo_session',
                'retention': '最多1000条摘要；删除不影响银行账单与必要操作记录',
                'coverage': '页面操作和应用服务结果；不采集输入原文，不保证关闭网页前全部送达'}

    def consent(self, sid, body):
        strict(body, {'enabled'})
        if type(body['enabled']) is not bool:
            raise Fault('EXPERIENCE_SCHEMA', '请选择开启或关闭')
        with self.service.transaction() as db:
            current = self._pref(db, sid)
            if current['enabled'] != body['enabled']:
                db.execute('UPDATE xp_preferences SET enabled=?,epoch=?,changed_at=? WHERE sid=?',
                           (int(body['enabled']), str(uuid4()), now(), sid))
                db.execute('INSERT INTO xp_lifecycle(sid,action,at) VALUES(?,?,?)',
                           (sid, 'consent_on' if body['enabled'] else 'consent_off', now()))
        return self.status(sid)

    def _insert(self, db, sid, epoch, event_id, source, action, phase, status, page, request_id=None):
        row = (epoch, source, action, phase, status, page, request_id)
        old = db.execute('SELECT epoch,source,action,phase,status,page,request_id FROM xp_events WHERE sid=? AND event_id=?',
                         (sid, event_id)).fetchone()
        if old:
            if old != row:
                raise Fault('EVENT_CONFLICT', '同一记录编号不能代表不同操作', 409)
            return False
        db.execute('INSERT INTO xp_events VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (sid, event_id, *row[:6], request_id, now()))
        # Bounded storage. Keep feedback only while its original event remains.
        db.execute('DELETE FROM xp_events WHERE sid=? AND rowid NOT IN '
                   '(SELECT rowid FROM xp_events WHERE sid=? ORDER BY rowid DESC LIMIT 1000)', (sid, sid))
        db.execute('DELETE FROM xp_feedback WHERE sid=? AND event_id NOT IN '
                   '(SELECT event_id FROM xp_events WHERE sid=?)', (sid, sid))
        db.execute('DELETE FROM xp_attempt_results WHERE sid=? AND (attempt_id NOT IN '
                   '(SELECT event_id FROM xp_events WHERE sid=?) OR result_event_id NOT IN '
                   '(SELECT event_id FROM xp_events WHERE sid=?))', (sid, sid, sid))
        return True

    def link_result(self, sid, attempt, result_id, epoch):
        with self.service.transaction() as db:
            pref=self._pref(db,sid)
            if not pref['enabled'] or pref['epoch']!=epoch:return
            rows=db.execute('SELECT event_id FROM xp_events WHERE sid=? AND epoch=? AND source=? '
                            'AND event_id IN (?,?)',(sid,epoch,'server_result',attempt,result_id)).fetchall()
            if len(rows)==2:
                db.execute('INSERT OR IGNORE INTO xp_attempt_results VALUES(?,?,?)',(sid,attempt,result_id))

    def ingest(self, sid, body):
        strict(body, {'epoch', 'events'})
        uid(body['epoch'])
        events = body['events']
        if not isinstance(events, list) or not 1 <= len(events) <= 30:
            raise Fault('EXPERIENCE_BATCH', '每次可同步1至30条记录')
        # Validate the whole batch before accepting any record.
        for event in events:
            strict(event, {'event_id', 'action', 'page'})
            uid(event['event_id'])
            if not isinstance(event['action'], str) or event['action'] not in CLIENT_ACTIONS:
                raise Fault('EXPERIENCE_ACTION', '不支持此类操作记录')
            if not isinstance(event['page'], str) or event['page'] not in PAGES:
                raise Fault('EXPERIENCE_PAGE', '页面标识不正确')
        with self.service.transaction() as db:
            pref = self._pref(db, sid)
            if not pref['enabled'] or pref['epoch'] != body['epoch']:
                raise Fault('EXPERIENCE_REVOKED', '记录已关闭或授权已更新，旧记录不会重新上传', 403)
            added = sum(self._insert(db, sid, pref['epoch'], e['event_id'], 'client_observation',
                        e['action'], 'observed', 'unverified', e['page']) for e in events)
        return {'accepted': [e['event_id'] for e in events], 'added': added,
                'meaning': '仅收到界面操作记录，不代表交易成功'}

    def server_event(self, sid, event_id, action, status, phase, request_id=None, epoch=None):
        """Internal-only entry point. Never bind identity/status from a submitted body."""
        with self.service.transaction() as db:
            pref = self._pref(db, sid)
            if not pref['enabled'] or (epoch is not None and pref['epoch'] != epoch):
                return False
            if status not in RESULTS | {'started'}:
                status = 'unknown'
            self._insert(db, sid, pref['epoch'], event_id, 'server_result', action,
                         phase, status, 'other', request_id)
        return True

    def query(self, sid, body):
        strict(body, set(), {'source', 'status', 'action'})
        for key, allowed in [('source', {'client_observation', 'server_result'}),
                             ('status', RESULTS | {'started', 'unverified'})]:
            if key in body and (not isinstance(body[key], str) or body[key] not in allowed):
                raise Fault('EXPERIENCE_FILTER', '记录筛选条件不正确')
        if 'action' in body and (not isinstance(body['action'], str) or not re.fullmatch(r'[a-z_.]{1,60}', body['action'])):
            raise Fault('EXPERIENCE_FILTER', '记录筛选条件不正确')
        with self.service.transaction() as db:
            pref = self._pref(db, sid)
            if not pref['enabled']:
                raise Fault('EXPERIENCE_REVOKED', '记录功能已关闭；重新开启后可查看，或直接删除', 403)
            clauses = ['e.sid=?', "NOT (e.phase='request_started' AND EXISTS "
                       '(SELECT 1 FROM xp_attempt_results a WHERE a.sid=e.sid AND a.attempt_id=e.event_id))']; values = [sid]
            for key, value in body.items():
                clauses.append('e.' + key + '=?'); values.append(value)
            rows = db.execute('SELECT e.event_id,e.source,e.action,e.phase,e.status,e.page,e.request_id,e.at,f.rating '
                'FROM xp_events e LEFT JOIN xp_feedback f ON e.sid=f.sid AND e.event_id=f.event_id WHERE '
                + ' AND '.join(clauses) + ' ORDER BY e.rowid DESC LIMIT 100', values).fetchall()
        keys = ['event_id', 'source', 'action', 'phase', 'status', 'page', 'request_id', 'at', 'feedback']
        return {'items': [dict(zip(keys, row)) for row in rows], 'trusted_for_execution': False}

    def feedback(self, sid, body):
        strict(body, {'event_id', 'rating'}); uid(body['event_id'])
        if body['rating'] not in ('helpful', 'incorrect'):
            raise Fault('EXPERIENCE_FEEDBACK', '请选择有帮助或需要核对')
        with self.service.transaction() as db:
            pref = self._pref(db, sid)
            if not pref['enabled']:
                raise Fault('EXPERIENCE_REVOKED', '记录功能已关闭', 403)
            row = db.execute('SELECT 1 FROM xp_events WHERE sid=? AND event_id=?', (sid, body['event_id'])).fetchone()
            if not row:
                raise Fault('NOT_FOUND', '未找到这条记录', 404)
            db.execute('INSERT OR REPLACE INTO xp_feedback VALUES(?,?,?,?)',
                       (sid, body['event_id'], body['rating'], now()))
        return {'saved': True, 'meaning': '反馈待核对，不会自动成为知识或执行授权'}

    def delete(self, sid, body):
        strict(body, {'confirmation'})
        if body['confirmation'] != '删除操作摘要':
            raise Fault('CONFIRMATION_REQUIRED', '请确认删除操作摘要')
        with self.service.transaction() as db:
            self._pref(db, sid)
            db.execute('DELETE FROM xp_events WHERE sid=?', (sid,))
            db.execute('DELETE FROM xp_feedback WHERE sid=?', (sid,))
            db.execute('DELETE FROM xp_attempt_results WHERE sid=?', (sid,))
            db.execute('UPDATE xp_preferences SET enabled=0,epoch=?,changed_at=? WHERE sid=?', (str(uuid4()), now(), sid))
            # Minimal deletion receipt: no copied event data or free text.
            db.execute('INSERT INTO xp_lifecycle(sid,action,at) VALUES(?,?,?)', (sid, 'deleted', now()))
        return self.status(sid)
