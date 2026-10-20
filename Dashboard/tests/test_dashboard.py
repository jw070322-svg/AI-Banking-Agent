"""Behavior and Streamlit integration tests. python -m unittest discover -s Dashboard/tests -v"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import types
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'dashboard_ui.py'
DOMAIN_ONLY = os.environ.get('BANKING_DOMAIN_ONLY') == '1'
if DOMAIN_ONLY:
    # Only pure functions run in this mode; UI tests are explicitly skipped.
    fake=types.ModuleType('streamlit')
    fake.fragment=lambda **kwargs: lambda function:function
    sys.modules['streamlit']=fake
spec=importlib.util.spec_from_file_location('banking_dashboard',SOURCE)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)
if not DOMAIN_ONLY:
    from streamlit.testing.v1 import AppTest


class DomainTests(unittest.TestCase):
    def test_default_two_eligible(self):
        self.assertEqual([r['product']['id'] for r in m.match_products(m.Profile()) if r['eligible']],['SIM-01','SIM-02'])

    def test_reserve_and_available(self):
        p=m.Profile()
        self.assertEqual(p.reserve,2_750_000)
        self.assertEqual(p.available,12_680_000)

    def test_risk_uses_lower_limit(self):
        rows=m.match_products(replace(m.Profile(),tolerance=5,capacity=1,horizon=365))
        self.assertEqual(sum(r['eligible'] for r in rows),1)

    def test_cash_boundary(self):
        p=m.Profile()
        self.assertTrue(any(r['eligible'] for r in m.match_products(replace(p,amount=p.available))))
        self.assertFalse(any(r['eligible'] for r in m.match_products(replace(p,amount=p.available+1))))

    def test_minimum_boundary(self):
        for amount,eligible in ((10000,True),(9999,False)):
            row=next(r for r in m.match_products(replace(m.Profile(),amount=amount)) if r['product']['id']=='SIM-01')
            self.assertEqual(row['eligible'],eligible)

    def test_horizon_boundary(self):
        for days,eligible in ((90,True),(89,False)):
            row=next(r for r in m.match_products(replace(m.Profile(),horizon=days)) if r['product']['id']=='SIM-02')
            self.assertEqual(row['eligible'],eligible)

    def test_zero_cash_empty_match(self):
        self.assertFalse(any(r['eligible'] for r in m.match_products(replace(m.Profile(),cash=0))))

    def test_type_and_range_validation(self):
        for kwargs in ({'cash':True},{'amount':0},{'cash':1.5},{'capacity':None},{'tolerance':6},
                       {'reserve_months':0},{'horizon':-1},{'essential':-1},{'objective':'yield'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                m.match_products(replace(m.Profile(),**kwargs))

    def test_order_changes_only_eligible_rank(self):
        rows=m.match_products(replace(m.Profile(),objective='期限贴合'))
        self.assertEqual(rows[0]['product']['id'],'SIM-02')
        self.assertTrue(all(not r['eligible'] for r in rows[2:]))

    def test_stress_uses_liquidity_and_preserves_profile(self):
        p=m.Profile()
        liquid=m.stress_test(p,'SIM-01',10_000_000,1_000_000)
        locked=m.stress_test(p,'SIM-02',10_000_000,1_000_000)
        self.assertEqual(liquid['accessible_after'],p.cash)
        self.assertEqual(locked['accessible_after'],p.cash-p.amount)
        self.assertTrue(liquid['passed'])
        self.assertFalse(locked['passed'])
        self.assertEqual(p,m.Profile())

    def test_stress_rejects_invalid_and_ineligible(self):
        for product,extra in (('SIM-04',0),('SIM-01',-1)):
            with self.assertRaises(ValueError):
                m.stress_test(m.Profile(),product,extra,0)

    def test_confirmation_and_eligibility_rechecked(self):
        with self.assertRaises(ValueError):m.make_plan(m.Profile(),'SIM-01',False)
        with self.assertRaises(ValueError):m.make_plan(m.Profile(),'SIM-04',True)

    def test_plan_id_binding(self):
        a=m.make_plan(m.Profile(),'SIM-01',True)
        b=m.make_plan(m.Profile(),'SIM-01',True)
        c=m.make_plan(replace(m.Profile(),amount=2_000_000),'SIM-01',True)
        d=m.make_plan(m.Profile(),'SIM-02',True)
        self.assertEqual(a['plan_id'],b['plan_id'])
        self.assertNotEqual(a['plan_id'],c['plan_id'])
        self.assertNotEqual(a['plan_id'],d['plan_id'])
        self.assertFalse(a['cash_changed'])

    def test_threshold_strict(self):
        for value,halted in ((10,False),(9.99,True),(0,True),(100,False)):
            self.assertEqual(m.quota_halts(m.read_quota(demo_value=value)),halted)

    def test_quota_file_validation(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory(dir=SOURCE.parent) as tmp:
            path=Path(tmp)/'quota.json'
            raw=dict(source='codex_host',scope='codex',window_minutes=300,remaining_percent=45,observed_at=now.isoformat())
            path.write_text(json.dumps(raw))
            self.assertEqual(m.read_quota(path,now=now)['remaining_percent'],45)
            for changes in ({'remaining_percent':True},{'remaining_percent':float('nan')},
                            {'remaining_percent':101},{'scope':'weekly'}, {'window_minutes':10080},
                            {'observed_at':(now-timedelta(seconds=91)).isoformat()},
                            {'observed_at':(now+timedelta(seconds=6)).isoformat()}):
                path.write_text(json.dumps(dict(raw,**changes)))
                with self.subTest(changes=changes),self.assertRaises(ValueError):m.read_quota(path,now=now)

    def test_schema_and_context(self):
        record=m.event('test','UnitTest',{},'done')
        self.assertEqual(tuple(record),m.LOG_KEYS)
        self.assertTrue(all(isinstance(v,str) for v in record.values()))
        text=m.context_markdown({'events':[record],'amount_input':123,'halt_reason':'test'})
        self.assertIn('123',text)
        self.assertIn('test',text)


@unittest.skipIf(DOMAIN_ONLY,'Streamlit installation pending; pure-domain run only')
class UITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SOURCE.parent)
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'BANKING_SESSION_DIR':self.tmp.name,'BANKING_DEMO_QUOTA':'100'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.old_file=os.environ.pop('BANKING_QUOTA_FILE',None)
        self.addCleanup(self.restore_file)

    def restore_file(self):
        if self.old_file is not None:os.environ['BANKING_QUOTA_FILE']=self.old_file
        else:os.environ.pop('BANKING_QUOTA_FILE',None)

    def app(self):
        app=AppTest.from_file(str(SOURCE),default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def matching(self):
        app=self.app()
        app.radio(key='page').set_value('产品匹配').run()
        self.assertFalse(app.exception)
        app.button(key='generate_match').click().run()
        self.assertFalse(app.exception)
        return app

    def selected(self):
        app=self.matching()
        app.button(key='choose_SIM-01').click().run()
        self.assertFalse(app.exception)
        return app

    def test_overview_and_navigation(self):
        app=self.app()
        self.assertEqual(app.title[0].value,'财务总览')
        for page in m.PAGES:
            app.radio(key='page').set_value(page).run()
            self.assertFalse(app.exception)

    def test_matching_selection_confirmation_save_idempotent(self):
        app=self.selected()
        self.assertTrue(app.button(key='save_plan').disabled)
        app.checkbox(key='confirmed').check().run()
        app.button(key='save_plan').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state['plans']),1)
        app.button(key='save_plan').click().run()
        self.assertEqual(len(app.session_state['plans']),1)

    def test_changed_amount_revokes_result_and_confirmation(self):
        app=self.selected()
        app.checkbox(key='confirmed').check().run()
        app.number_input(key='amount_input').set_value(40000).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['results'],[])
        self.assertIsNone(app.session_state['selected'])
        self.assertFalse(app.session_state['confirmed'])

    def test_changed_selection_revokes_confirmation(self):
        app=self.selected()
        app.checkbox(key='confirmed').check().run()
        app.button(key='choose_SIM-02').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.checkbox(key='confirmed').value)

    def test_stress_workflow_and_invalidated_result(self):
        app=self.selected()
        app.radio(key='page').set_value('情景验证').run()
        app.button(key='run_stress').click().run()
        self.assertFalse(app.exception)
        self.assertIsNotNone(app.session_state['stress'])
        app.slider(key='extra_stress').set_value(100000).run()
        self.assertIsNone(app.session_state['stress'])

    def test_saved_plan_refreshes_stress_evidence_without_duplicate(self):
        app=self.selected()
        app.checkbox(key='confirmed').check().run()
        app.button(key='save_plan').click().run()
        original_id=app.session_state['plans'][0]['plan_id']
        self.assertEqual(app.session_state['plans'][0]['stress_status'],'not_run')

        app.radio(key='page').set_value('情景验证').run()
        app.slider(key='extra_stress').set_value(100000).run()
        app.slider(key='delay_stress').set_value(25000).run()
        app.button(key='run_stress').click().run()
        tested_result=dict(app.session_state['stress'])
        app.radio(key='page').set_value('产品匹配').run()
        app.checkbox(key='confirmed').check().run()
        app.button(key='save_plan').click().run()

        self.assertFalse(app.exception)
        plans=app.session_state['plans']
        self.assertEqual(len(plans),1)
        self.assertEqual(plans[0]['plan_id'],original_id)
        self.assertEqual(plans[0]['stress_status'],'tested')
        self.assertEqual(plans[0]['stress'],tested_result)
        self.assertEqual(plans[0]['stress']['extra_expense'],10_000_000)
        self.assertEqual(plans[0]['stress']['delayed_income'],2_500_000)

    def test_custom_stress_inputs_and_result_survive_navigation(self):
        app=self.selected()
        app.radio(key='page').set_value('情景验证').run()
        app.slider(key='extra_stress').set_value(100000).run()
        app.slider(key='delay_stress').set_value(25000).run()
        app.button(key='run_stress').click().run()
        tested_result=dict(app.session_state['stress'])

        app.radio(key='page').set_value('方案与活动').run()
        app.radio(key='page').set_value('情景验证').run()

        self.assertFalse(app.exception)
        self.assertEqual(app.slider(key='extra_stress').value,100000)
        self.assertEqual(app.slider(key='delay_stress').value,25000)
        self.assertEqual(app.session_state['stress'],tested_result)

    def test_zero_matches(self):
        app=self.matching()
        app.number_input(key='cash_input').set_value(0).run()
        app.button(key='generate_match').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(any(r['eligible'] for r in app.session_state['results']))

    def test_low_quota_start_exports_without_actions(self):
        os.environ['BANKING_DEMO_QUOTA']='9.99'
        app=self.app()
        self.assertTrue(app.session_state['halted'])
        self.assertEqual(app.session_state['results'],[])
        self.assertTrue(list(Path(self.tmp.name).glob('*.md')))
        self.assertFalse(any(b.key=='generate_match' for b in app.button))

    def test_ten_percent_allowed(self):
        os.environ['BANKING_DEMO_QUOTA']='10'
        app=self.app()
        self.assertFalse(app.session_state['halted'])

    def test_drop_before_save_preserves_previous_work(self):
        app=self.selected()
        app.checkbox(key='confirmed').check().run()
        os.environ['BANKING_DEMO_QUOTA']='9'
        app.button(key='save_plan').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state['halted'])
        self.assertEqual(len(app.session_state['plans']),0)
        self.assertEqual(len(app.session_state['results']),4)
        os.environ['BANKING_DEMO_QUOTA']='100'
        app.run()
        self.assertTrue(app.session_state['halted'])

    def test_unavailable_live_quota_stops(self):
        os.environ['BANKING_QUOTA_FILE']=str(Path(self.tmp.name)/'missing.json')
        app=self.app()
        self.assertTrue(app.session_state['halted'])
        self.assertIn('quota_unavailable',app.session_state['halt_reason'])

    def test_user_pause_preserves_context(self):
        app=self.selected()
        app.button(key='pause').click().run()
        self.assertTrue(app.session_state['halted'])
        self.assertEqual(app.session_state['halt_reason'],'user_pause')
        self.assertEqual(app.session_state['selected'],'SIM-01')


if __name__=='__main__':unittest.main()
