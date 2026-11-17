"""Reconciled snapshots and deterministic accounting, never payment execution."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from .models import iso_date, money, require_ledger


def fingerprint(data):
    encoded=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return 'sha256:'+hashlib.sha256(encoded.encode()).hexdigest()


def organize(data, *, start_date=None, end_date=None):
    if not isinstance(data,dict):raise ValueError('data must be an object')
    # Only missing presentation fields may be completed. Never infer directions or units.
    clean=deepcopy(data)
    warnings=[]
    if not isinstance(clean.get('transactions'),list):raise ValueError('transactions must be a list')
    for i,row in enumerate(clean['transactions']):
        if not isinstance(row,dict):raise ValueError('transaction must be an object')
        for field,fallback in [('category','未分类'),('merchant','未知商户')]:
            if row.get(field) is None or row.get(field)=='':
                row[field]=fallback;warnings.append(f'transactions[{i}].{field} missing; marked {fallback}')
    require_ledger(clean)
    if start_date is not None:iso_date(start_date)
    if end_date is not None:iso_date(end_date)
    if start_date and end_date and start_date>end_date:raise ValueError('start_date must not exceed end_date')
    rows=sorted(clean['transactions'],key=lambda t:(t['date'],t['id']))
    lo=start_date or (rows[0]['date'] if rows else None)
    hi=end_date or (rows[-1]['date'] if rows else None)
    if lo and hi and lo>hi:raise ValueError('requested range does not form a valid period')
    selected=[t for t in rows if (lo is None or t['date']>=lo) and (hi is None or t['date']<=hi)]
    duplicate_groups=defaultdict(list)
    recurring=defaultdict(list)
    for t in selected:
        if t['status']=='booked' and t['type']=='expense' and t['merchant']!='未知商户':
            duplicate_groups[(t['account_id'],t['date'],t['merchant'],t['amount_minor'],t['category'])].append(t['id'])
            recurring[(t['account_id'],t['merchant'],t['amount_minor'],t['date'][8:])].append(t)
    candidates=[]
    for (account,merchant,amount,day),items in sorted(recurring.items()):
        months=sorted({t['date'][:7] for t in items})
        ordinals=[int(m[:4])*12+int(m[5:]) for m in months]
        if len(months)>=3 and all(b-a==1 for a,b in zip(ordinals,ordinals[1:])):
            candidates.append({'account_id':account,'merchant':merchant,'amount_minor':-amount,'day':int(day),
                               'months':months,'transaction_ids':[t['id'] for t in items],'confirmed':False})
    balances=[]
    for a in clean['accounts']:
        opening=a['initial_balance_minor']+sum(t['amount_minor'] for t in rows if t['account_id']==a['account_id'] and t['status']=='booked' and lo and t['date']<lo)
        delta=sum(t['amount_minor'] for t in selected if t['account_id']==a['account_id'] and t['status']=='booked')
        balances.append({'account_id':a['account_id'],'opening_minor':opening,'movement_minor':delta,'closing_minor':opening+delta})
    return {'schema_version':'financial-snapshot-1.0','source_hash':fingerprint(data),'normalized_hash':fingerprint(clean),
            'source_version':data.get('schema_version','unspecified'),'period':{'start':lo,'end':hi},
            'accounts':balances,'transactions':selected,'input_transaction_count':len(rows),
            'duplicate_candidates':[{'transaction_ids':v,'confirmed':False} for v in duplicate_groups.values() if len(v)>1],
            'subscription_candidates':candidates,'warnings':warnings,'fact_kind':'historical_input','ledger_modified':False}


def _totals(rows):
    sums=defaultdict(int)
    category=defaultdict(int)
    for t in rows:
        if t['status']!='booked':continue
        sums[t['type']]+=t['amount_minor']
        if t['type']=='expense':category[t['category']]-=t['amount_minor']
        if t['type']=='refund':category[t['category']]-=t['amount_minor']
    income=sums['income']+sums['income_reversal']
    expense=-sums['expense'];refund=sums['refund']
    net_expense=expense-refund
    return {'gross_income_minor':sums['income'],'income_reversal_minor':-sums['income_reversal'],
            'income_minor':income,'gross_expense_minor':expense,'refund_minor':refund,'net_expense_minor':net_expense,
            'transfer_in_minor':sums['transfer_in'],'transfer_out_minor':-sums['transfer_out'],
            'cash_surplus_minor':income-net_expense,'net_cashflow_minor':sum(sums.values()),
            'category_net_expense_minor':dict(sorted(category.items()))}


def calculate(data, *, start_date=None, end_date=None, liquid_assets_minor=None,
              monthly_debt_payment_minor=0, essential_monthly_expense_minor=None):
    snapshot=organize(data,start_date=start_date,end_date=end_date)
    money(monthly_debt_payment_minor,'monthly_debt_payment_minor')
    if liquid_assets_minor is not None:money(liquid_assets_minor,'liquid_assets_minor')
    if essential_monthly_expense_minor is not None:money(essential_monthly_expense_minor,'essential_monthly_expense_minor')
    totals=_totals(snapshot['transactions'])
    monthly=defaultdict(list)
    for t in snapshot['transactions']:monthly[t['date'][:7]].append(t)
    lo,hi=snapshot['period']['start'],snapshot['period']['end']
    count=0
    if lo and hi:
        first=int(lo[:4])*12+int(lo[5:7])-1;last=int(hi[:4])*12+int(hi[5:7])-1
        count=last-first+1
        if count>1200:raise ValueError('analysis period exceeds 100 years')
        for i in range(first,last+1):monthly.setdefault(f'{i//12:04d}-{i%12+1:02d}',[])
    reasons={}
    if totals['income_minor']>0:
        savings=round(totals['cash_surplus_minor']/totals['income_minor'],6)
        debt=round(monthly_debt_payment_minor*count/totals['income_minor'],6) if count else None
    else:
        savings=debt=None
        reasons['cash_surplus_ratio']=reasons['debt_service_ratio']='period net income is zero or negative'
    if liquid_assets_minor is not None and essential_monthly_expense_minor:
        liquidity=round(liquid_assets_minor/essential_monthly_expense_minor,6)
    else:
        liquidity=None;reasons['liquidity_months']='requires liquid assets and positive essential monthly expense'
    warnings=list(snapshot['warnings'])
    if snapshot['duplicate_candidates']:warnings.append('duplicate candidates remain in all totals until reviewed')
    if any(t['type'].startswith('transfer_') for t in snapshot['transactions']):
        warnings.append('transfers affect cash balance, not consumption or income; label credit-card repayment as transfer_out only when source confirms it')
    return {'schema_version':'financial-metrics-1.0','source_hash':snapshot['source_hash'],'period':snapshot['period'],
            'totals':totals,'monthly':{m:_totals(rows) for m,rows in sorted(monthly.items())},
            'ratios':{'cash_surplus_ratio':savings,'debt_service_ratio':debt,'liquidity_months':liquidity},
            'undefined_reasons':reasons,'assumptions':{'observed_calendar_months':count,'partial_months':'count as calendar months, not annualized',
            'cash_surplus':'net income - (gross consumption - refunds); excludes all transfers',
            'net_cashflow':'sum of all booked signed amounts, including transfers',
            'debt_service_ratio':'monthly debt payment / (period net income / calendar months)',
            'liquidity_months':'provided liquid assets / provided essential monthly expense'},
            'warnings':warnings,'ledger_modified':False}
