from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ethan_toolkit.models import validate_ledger
from ethan_toolkit.scenarios import generate_environment,validate_environment,parse_requirement,import_ethan,to_agent_scenario
from ethan_toolkit.finance import organize,calculate
from ethan_toolkit.simulation import simulate_cashflow,compare_plans
from ethan_toolkit.lifestyle import plan_event,export_ics
from ethan_toolkit.tools import call_tool,catalog
from ethan_toolkit.__main__ import load_json
from ethan_toolkit.demo import build_demo

BASE=Path(__file__).resolve().parents[1]


def ledger(rows, initial=1000000):
    tx=[]
    for n,(day,amount,kind,category,merchant,*status) in enumerate(rows):
        tx.append({'id':f'T{n}','account_id':'A','date':day,'amount_minor':amount,'type':kind,
                   'category':category,'merchant':merchant,'status':status[0] if status else 'booked'})
    return {'schema_version':'scenario-1.1','accounts':[{'account_id':'A','currency':'CNY','initial_balance_minor':initial,
            'balance_minor':initial+sum(t['amount_minor'] for t in tx if t['status']=='booked')}],'transactions':tx}


class EnvironmentTests(unittest.TestCase):
    def test_seeded_generation_and_isolated_random_state(self):
        import random
        random.seed(123);before=random.getstate()
        for kind in 'ABCDE':
            a=generate_environment(kind,seed=7,as_of='2026-01-02')
            self.assertEqual(a,generate_environment(kind,seed=7,as_of='2026-01-02'))
            self.assertEqual([],validate_environment(a))
            self.assertNotEqual(a['scenario_id'],generate_environment(kind,seed=8,as_of='2026-01-02')['scenario_id'])
        self.assertEqual(before,random.getstate())

    def test_generated_balances_and_calendar_are_reconciled(self):
        for seed in range(20):
            for kind in 'ABCDE':
                data=generate_environment(kind,seed=seed,as_of='2024-02-29')
                self.assertEqual([],validate_environment(data))
                a=data['accounts'][0]
                self.assertEqual(a['balance_minor'],a['initial_balance_minor']+sum(t['amount_minor'] for t in data['transactions'] if t['status']=='booked'))
                self.assertTrue(all(t['date']<='2024-02-29' for t in data['transactions']))

    def test_exact_shopping_delta_and_parameter_parse(self):
        parsed=parse_requirement('最近2个月购物支出增加800.01元')
        self.assertEqual(parsed,{'scenario_type':'B','increase_minor':80001})
        data=generate_environment(**parsed)
        rows=data['transactions'];self.assertEqual(rows[0]['amount_minor']-rows[1]['amount_minor'],80001)
        for text in ['未知业务','投资基金','购物增加0.001元','购物增加123']:
            with self.assertRaises(ValueError):parse_requirement(text)
        for value in [True,0,-1,1.2]:
            with self.assertRaises(ValueError):generate_environment('B',increase_minor=value)

    def test_each_semantic_rule_rejects_counterexample(self):
        for kind in 'ABCDE':
            data=generate_environment(kind)
            if kind=='A':data['transactions'][0]['type']='transfer_in'
            elif kind=='B':data['parameters']['increase_minor']+=1
            elif kind=='C':data['transactions'][2]['merchant']='different'
            elif kind=='D':data['transactions'][-1]['amount_minor']=-1
            else:data['transactions']=[{**t,'category':'其他'} for t in data['transactions']]
            self.assertTrue(validate_environment(data),kind)

    def test_strict_invalid_fields_and_early_negative_balance(self):
        good=generate_environment('A')
        for field,value in [('amount_minor',True),('amount_minor',1.5),('amount_minor',float('inf')),('date','2026-02-30'),('date','20261001'),('type','mystery'),('account_id',[]),('status',{})]:
            bad=deepcopy(good);bad['transactions'][0][field]=value
            self.assertTrue(validate_ledger(bad),(field,value))
        bad=deepcopy(good);bad['transactions'].append(deepcopy(bad['transactions'][0]));self.assertTrue(validate_ledger(bad))
        bad=ledger([('2026-01-01',-110,'expense','购物','商户'),('2026-01-02',120,'income','工资','雇主')],initial=100)
        self.assertTrue(validate_ledger(bad))

    def test_import_drops_identity_preserves_semantics_and_source(self):
        raw={'scenario_id':'old','scenario_type':'A','user':{'phone':'TEST-PRIVATE'},
             'accounts':[{'account_id':'A','initial_balance':100,'balance':105}],
             'transactions':[{'transaction_id':'1','account_id':'A','date':'2026-10-01','amount':10,'transaction_type':'income','category':'工资','merchant':'雇主','status':'completed'},
                             {'transaction_id':'2','account_id':'A','date':'2026-10-02','amount':5,'transaction_type':'expense','category':'订阅','merchant':'音乐','status':'completed','recurring':True,'subscription_cycle':'monthly','related_transaction_id':'x'}]}
        out=import_ethan(raw)
        self.assertEqual(out['accounts'][0]['balance_minor'],10500)
        self.assertNotIn('TEST-PRIVATE',json.dumps(out))
        self.assertTrue(out['transactions'][1]['recurring'])
        self.assertEqual(out['transactions'][1]['related_transaction_id'],'x')
        self.assertEqual(out['transactions'][1]['type'],'expense')
        self.assertEqual(len(out['source']['sha256']),64)
        self.assertEqual(to_agent_scenario(out)['schema_version'],'scenario-1.0')
        for amount in [True,float('nan'),1.001,-1]:
            bad=deepcopy(raw);bad['transactions'][0]['amount']=amount
            with self.assertRaises(ValueError):import_ethan(bad)


class FinanceTests(unittest.TestCase):
    def sample(self):
        return ledger([('2026-10-01',1000000,'income','工资','雇主'),
                       ('2026-10-02',-300000,'expense','购物','商户'),
                       ('2026-10-03',50000,'refund','购物','商户'),
                       ('2026-10-04',-200000,'transfer_out','本人转账','本人另一账户'),
                       ('2026-10-05',200000,'transfer_in','本人转账','本人另一账户'),
                       ('2026-10-06',-300000,'transfer_out','信用卡还款','模拟信用卡'),
                       ('2026-10-07',-999999,'expense','购物','失败商户','rejected')])

    def test_hand_calculated_refund_transfer_and_repayment(self):
        report=calculate(self.sample(),liquid_assets_minor=600000,essential_monthly_expense_minor=200000,monthly_debt_payment_minor=100000)
        t=report['totals']
        self.assertEqual(t['income_minor'],1000000)
        self.assertEqual(t['gross_expense_minor'],300000)
        self.assertEqual(t['refund_minor'],50000)
        self.assertEqual(t['net_expense_minor'],250000)
        self.assertEqual(t['net_cashflow_minor'],450000)
        self.assertEqual(t['cash_surplus_minor'],750000)
        self.assertEqual(report['ratios'],{'cash_surplus_ratio':.75,'debt_service_ratio':.1,'liquidity_months':3.0})

    def test_zero_negative_income_and_refund_exceeding_expense(self):
        data=ledger([('2026-10-01',-100,'income_reversal','工资冲回','雇主'),('2026-10-02',200,'refund','购物','商户')])
        r=calculate(data)
        self.assertEqual(r['totals']['income_minor'],-100)
        self.assertEqual(r['totals']['net_expense_minor'],-200)
        self.assertIsNone(r['ratios']['cash_surplus_ratio']);self.assertIsNone(r['ratios']['debt_service_ratio'])
        self.assertIsNone(calculate(ledger([]))['ratios']['cash_surplus_ratio'])
        for val in [True,-1,1.1]:
            with self.assertRaises(ValueError):calculate(data,monthly_debt_payment_minor=val)

    def test_missing_category_flagged_duplicate_preserved_no_mutation(self):
        data=generate_environment('C');before=deepcopy(data)
        snapshot=organize(data)
        self.assertEqual(len(snapshot['duplicate_candidates']),1)
        self.assertEqual(len(snapshot['transactions']),len(data['transactions']))
        self.assertEqual(data,before)
        del data['transactions'][0]['category'];snapshot=organize(data)
        self.assertTrue(snapshot['warnings']);self.assertEqual(snapshot['transactions'][0]['category'],'未分类')
        self.assertTrue(organize(generate_environment('E'))['subscription_candidates'])

    def test_range_snapshot_reconciliation_and_empty_months(self):
        data=ledger([('2026-01-10',100000,'income','工资','雇主'),('2026-03-10',-30000,'expense','购物','商户')])
        snap=organize(data,start_date='2026-02-01',end_date='2026-03-31')
        self.assertEqual(snap['accounts'][0],{'account_id':'A','opening_minor':1100000,'movement_minor':-30000,'closing_minor':1070000})
        r=calculate(data,start_date='2026-01-01',end_date='2026-03-31',monthly_debt_payment_minor=10000)
        self.assertEqual(r['monthly']['2026-02']['income_minor'],0)
        self.assertEqual(r['ratios']['debt_service_ratio'],.3)
        with self.assertRaises(ValueError):organize(data,start_date='2026-03-01',end_date='2026-02-01')

    def test_missing_direction_and_bad_balance_are_not_guessed(self):
        data=self.sample();del data['transactions'][0]['type']
        with self.assertRaises(ValueError):organize(data)
        data=self.sample();data['accounts'][0]['balance_minor']+=1
        with self.assertRaises(ValueError):calculate(data)


class SimulationTests(unittest.TestCase):
    def test_income_delay_changes_minimum_not_ending_balance(self):
        salary={'id':'salary','date':'2026-11-01','amount_minor':500000,'basis':'hypothesis'}
        rent={'id':'rent','date':'2026-11-02','amount_minor':-300000,'basis':'contract'}
        report=compare_plans(start_date='2026-10-24',end_date='2026-11-30',start_balance_minor=350000,minimum_reserve_minor=100000,
                             plans={'base':[rent,salary],'delay':[rent,{**salary,'date':'2026-11-10'}]})['plans']
        self.assertEqual(report['base']['closing_minor'],550000);self.assertEqual(report['delay']['closing_minor'],550000)
        self.assertEqual(report['base']['minimum_balance_minor'],350000);self.assertEqual(report['delay']['minimum_balance_minor'],50000)
        self.assertEqual(report['delay']['shortfalls'][0]['shortfall_minor'],50000)

    def test_subscription_effective_date_and_intraday_bound(self):
        events=[{'id':'old-sub','date':'2026-11-01','effective_from':'2026-11-02','amount_minor':-100,'basis':'contract'},
                {'id':'pay','date':'2026-11-02','amount_minor':-200,'basis':'user_input'},
                {'id':'income','date':'2026-11-02','amount_minor':300,'basis':'hypothesis'}]
        r=simulate_cashflow(start_date='2026-11-01',end_date='2026-11-30',start_balance_minor=100,events=events)
        self.assertEqual(r['closing_minor'],200);self.assertEqual(r['minimum_balance_minor'],100)
        self.assertEqual(r['conservative_intraday_minimum_minor'],-100)
        self.assertEqual(r['excluded_events'][0]['id'],'old-sub')
        self.assertEqual(r,simulate_cashflow(start_date='2026-11-01',end_date='2026-11-30',start_balance_minor=100,events=events))

    def test_invalid_events_and_initial_reserve_shortfall(self):
        kwargs={'start_date':'2026-11-01','end_date':'2026-11-30','start_balance_minor':100,'minimum_reserve_minor':200,'events':[]}
        self.assertEqual(simulate_cashflow(**kwargs)['shortfalls'][0]['shortfall_minor'],100)
        for bad in [[{'id':'x','date':'2026-11-02','amount_minor':True,'basis':'user_input'}],[{'id':'x','date':'2026-11-02','amount_minor':10,'basis':'guaranteed'}]]:
            with self.assertRaises(ValueError):simulate_cashflow(**{**kwargs,'events':bad})


class LifestyleTests(unittest.TestCase):
    def plan(self,**changes):
        return plan_event(**{'event_date':'2024-02-29','as_of':'2024-02-28','budget_minor':101,'available_minor':201,'emergency_reserve_minor':100,**changes})

    def test_exact_budget_small_amount_zero_and_no_backdating(self):
        for budget in [0,1,2,101]:
            p=self.plan(budget_minor=budget)
            self.assertEqual(sum(a['amount_minor'] for a in p['allocations']),budget)
            self.assertEqual(p['status'],'draft');self.assertTrue(p['ledger_modified'] is False)
            self.assertTrue(all(e['date']>='2024-02-28' for e in p['calendar']))
        self.assertEqual(self.plan(event_date='2024-02-28')['calendar'][0]['date'],'2024-02-28')

    def test_overspend_and_reserve_shortage_do_not_schedule(self):
        p=self.plan(budget_minor=102);self.assertEqual(p['status'],'needs_adjustment');self.assertEqual(p['shortfall_minor'],1);self.assertEqual(p['calendar'],[])
        p=self.plan(budget_minor=0,available_minor=50);self.assertEqual(p['reserve_shortfall_minor'],50);self.assertEqual(p['calendar'],[])
        with self.assertRaises(ValueError):export_ics(p)

    def test_invalid_dates_money_and_currency(self):
        for args in [{'event_date':'2023-02-29'},{'event_date':'2024-02-27'},{'budget_minor':True},{'budget_minor':1.2},{'budget_minor':-1},{'currency':'USD'}]:
            with self.assertRaises(ValueError):self.plan(**args)

    def test_calendar_escaping_folding_and_stability(self):
        p=self.plan(label='生日\r\nBEGIN:VEVENT;伪造,'+'很长的中文'*15)
        result=export_ics(p)
        self.assertEqual(result,export_ics(p))
        self.assertEqual(result.count('\r\nBEGIN:VEVENT\r\n'),3)
        self.assertIn('\\nBEGIN:VEVENT\\;',result)
        self.assertTrue(all(len(line.encode())<=75 for line in result.split('\r\n')))


class DeliveryTests(unittest.TestCase):
    def test_delivered_ethan_fixtures_and_catalog_contracts(self):
        fixtures=BASE/'examples/ethan'
        for kind in 'ABCDE':
            data=json.loads((fixtures/f'{kind}.json').read_text(encoding='utf-8'))
            self.assertEqual([],validate_environment(data))
            self.assertEqual(calculate(data)['ledger_modified'],False)
        definitions=json.loads((BASE/'tool_definitions.json').read_text(encoding='utf-8'))
        self.assertEqual(definitions,catalog())
        self.assertEqual(len(definitions),12)

    def test_tool_allowlist_validation_and_no_financial_execution(self):
        self.assertEqual(call_tool('execute_transfer',{})['error']['code'],'UNKNOWN_TOOL')
        self.assertEqual(call_tool('generate_environment',{'scenario_type':'A','unexpected':True})['status'],'rejected')
        self.assertEqual(call_tool('validate_environment',{'data':{'accounts':[]}})['status'],'rejected')
        self.assertTrue(all(not t['side_effects'] for t in catalog()))
        self.assertEqual(call_tool('plan_life_event',{'event_date':'2026-11-01','as_of':'2026-10-24','budget_minor':0,'available_minor':0})['data']['status'],'draft')

    def test_cli_demo_reproducible_standalone_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            a=Path(temp)/'a';b=Path(temp)/'b'
            build_demo(a);build_demo(b)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()},{p.name:p.read_bytes() for p in b.iterdir()})
            with self.assertRaises(ValueError):build_demo(a)
            run=subprocess.run([sys.executable,'-m','ethan_toolkit','validate',str(a/'A.json')],cwd=BASE,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertTrue(json.loads(run.stdout)['data']['valid'])

    def test_json_nan_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            p=Path(temp)/'bad.json'
            for content in ['{"n":NaN}','{"n":1,"n":2}']:
                p.write_text(content,encoding='utf-8')
                with self.assertRaises(ValueError):load_json(p)


if __name__=='__main__':unittest.main()
