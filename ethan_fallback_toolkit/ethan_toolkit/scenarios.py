"""A-E semantics from Ethan's 1022 delivery, implemented with local seeded state."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib, json, random, re
from .models import INCOMING, iso_date, money, require_ledger, validate_ledger

NAMES={'A':'普通银行用户','B':'购物支出增加','C':'疑似重复扣款','D':'余额不足','E':'周期性订阅'}


def month_day(anchor, offset, day=15):
    n=anchor.year*12+anchor.month-1+offset
    return date(n//12,n%12+1,day).isoformat()


def parse_requirement(text):
    if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError('requirement must contain 1-2000 characters')
    text=text.strip()
    if text.upper() in NAMES:return {'scenario_type':text.upper(),'increase_minor':80000}
    patterns=[('C',('重复扣款','重复扣费')),('D',('余额不足','余额不够')),('E',('订阅','周期扣款')),('B',('购物增加','购物支出增加','购物上涨','购物消费增加'))]
    kind=next((k for k,terms in patterns if any(w in text for w in terms)),None)
    if kind is None and '购物' in text and any(w in text for w in ('增加','上涨','提升')):kind='B'
    if kind is None and any(w in text for w in ('普通','日常','工资')):kind='A'
    if kind is None:raise ValueError('unsupported or ambiguous request; specify A-E or a supported scenario')
    delta=80000
    if kind=='B':
        match=re.search(r'(?:增加|上涨|提升)(?:了)?\s*([+-]?\d+(?:\.\d+)?)\s*元',text)
        if match:
            value=Decimal(match.group(1))*100
            if value!=value.to_integral_value():raise ValueError('increase must have at most two decimal places')
            delta=int(value)
        elif re.search(r'\d',text) and not re.search(r'\d+\s*个?月',text):
            raise ValueError('specify shopping increase as 增加 N 元')
    return {'scenario_type':kind,'increase_minor':delta}


def generate_environment(scenario_type='A', *, seed=42, as_of='2026-10-24', increase_minor=80000):
    if not isinstance(scenario_type,str) or scenario_type not in NAMES:raise ValueError('scenario_type must be A-E')
    if type(seed) is not int or not 0<=seed<=2**32-1:raise ValueError('seed must be a uint32 integer')
    anchor=iso_date(as_of)
    if not 2000<=anchor.year<=2100:raise ValueError('as_of year must be 2000-2100')
    money(increase_minor,'increase_minor')
    if not 1<=increase_minor<=100_000_000:raise ValueError('increase_minor must be 1-100000000')
    config={'scenario_type':scenario_type,'seed':seed,'as_of':as_of,'increase_minor':increase_minor}
    token=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:16]
    rng=random.Random(seed)
    account='ACC-SYN-'+token[:8]
    rows=[]
    def add(day,amount,kind,category,merchant,status='booked'):
        rows.append({'id':f'TXN-SYN-{token}-{len(rows)+1:03d}','account_id':account,'date':day,
                     'amount_minor':amount,'type':kind,'category':category,'merchant':merchant,'status':status})
    first=month_day(anchor,-2);second=month_day(anchor,-1)
    initial=2_000_000
    if scenario_type=='A':
        add(second,1_200_000,'income','工资','模拟雇主')
        for i,category in enumerate(['餐饮','交通','日用','购物']):
            add((iso_date(second)+timedelta(days=i+1)).isoformat(),-rng.randint(1000,30000),'expense',category,'模拟商户-'+str(i+1))
    elif scenario_type=='B':
        initial=increase_minor+2_000_000
        baseline=rng.randint(50000,100000)
        add(first,-baseline,'expense','购物','模拟购物商户')
        add(second,-(baseline+increase_minor),'expense','购物','模拟购物商户')
    elif scenario_type=='C':
        add(first,800000,'income','工资','模拟雇主')
        add(second,-29800,'expense','购物','模拟重复商户')
        add(second,-29800,'expense','购物','模拟重复商户')
        add((iso_date(second)+timedelta(days=1)).isoformat(),-3000,'expense','交通','模拟交通商户')
    elif scenario_type=='D':
        initial=50000
        add(first,-10000,'expense','餐饮','模拟餐饮商户')
        add(second,-60000,'transfer_out','转账','模拟收款人','rejected')
    else:
        for offset in (-3,-2,-1):
            add(month_day(anchor,offset),-2800,'expense','订阅','模拟云空间')
            add(month_day(anchor,offset,18),-4500,'expense','订阅','模拟音乐')
    out={'schema_version':'scenario-1.1','scenario_id':'SCN-SYN-'+token,'scenario_type':scenario_type,
         'scenario_name':NAMES[scenario_type],'as_of':as_of,'seed':seed,'parameters':{'increase_minor':increase_minor},
         'accounts':[{'account_id':account,'currency':'CNY','initial_balance_minor':initial,
                      'balance_minor':initial+sum(t['amount_minor'] for t in rows if t['status']=='booked')}],
         'transactions':rows,'simulated':True,'ledger_modified':False}
    errors=validate_environment(out)
    if errors:raise ValueError('; '.join(errors))
    return out


def validate_environment(data):
    errors=validate_ledger(data)
    if errors:return errors
    kind=data.get('scenario_type')
    if not isinstance(kind,str) or kind not in NAMES:return ['scenario_type must be A-E']
    rows=[t for t in data['transactions'] if t['status']=='booked']
    if kind=='A' and not (any(t['type']=='income' for t in rows) and any(t['type']=='expense' for t in rows)):
        errors.append('A requires booked income and expense')
    if kind=='B':
        sums=defaultdict(int)
        for t in rows:
            if t['category']=='购物' and t['type']=='expense':sums[t['date'][:7]]-=t['amount_minor']
        months=sorted(sums)
        params=data.get('parameters',{})
        target=params.get('increase_minor') if isinstance(params,dict) else None
        if type(target) is not int or target<=0:errors.append('B requires positive increase_minor')
        elif len(months)!=2 or (int(months[1][:4])*12+int(months[1][5:]))-(int(months[0][:4])*12+int(months[0][5:]))!=1 or sums[months[1]]-sums[months[0]]!=target:
            errors.append('B requires two consecutive shopping months with exact increase')
    if kind=='C':
        groups=defaultdict(list)
        for t in rows:
            if t['type']=='expense':groups[(t['account_id'],t['date'],t['merchant'],t['amount_minor'],t['category'])].append(t['id'])
        duplicate_ids={key for values in groups.values() if len(values)>1 for key in values}
        if not duplicate_ids or not any(t['id'] not in duplicate_ids for t in rows):
            errors.append('C requires duplicate candidates plus ordinary transactions; preserve all originals')
    if kind=='D':
        found=False
        for t in data['transactions']:
            if t['status']=='rejected' and t['type']=='transfer_out':
                a=next(a for a in data['accounts'] if a['account_id']==t['account_id'])
                available=a['initial_balance_minor']+sum(x['amount_minor'] for x in rows if x['account_id']==t['account_id'] and x['date']<=t['date'])
                found=found or -t['amount_minor']>available
        if not found:errors.append('D requires a rejected transfer larger than available balance')
    if kind=='E':
        groups=defaultdict(set)
        for t in rows:
            if t['category']=='订阅' and t['type']=='expense':groups[(t['account_id'],t['merchant'],t['amount_minor'],t['date'][8:])].add(t['date'][:7])
        def consecutive(months):
            values=sorted(int(m[:4])*12+int(m[5:]) for m in months)
            return len(values)>=3 and all(y-x==1 for x,y in zip(values,values[1:]))
        if not any(consecutive(ms) for ms in groups.values()):errors.append('E requires a fixed merchant/amount/day across at least three consecutive months')
    if 'as_of' in data:
        try:
            anchor=iso_date(data['as_of'])
            if any(iso_date(t['date'])>anchor for t in data['transactions']):errors.append('transactions cannot be later than as_of')
        except ValueError as exc:errors.append(str(exc))
    return errors


def to_agent_scenario(data):
    """Additive 1.1 -> SecondAsgent's scenario-1.0 read-only result."""
    errors=validate_environment(data)
    if errors:raise ValueError('; '.join(errors))
    return {'schema_version':'scenario-1.0','scenario_id':data['scenario_id'],'scenario_type':data['scenario_type'],
            'accounts':deepcopy(data['accounts']),
            'transactions':[{k:t[k] for k in ['id','account_id','date','amount_minor','category','status']} for t in data['transactions']],
            'warnings':['scenario-1.0 projection omits type/merchant/reference fields; use the full 1.1 data for financial analysis'],
            'simulated':True,'ledger_modified':False}


def import_ethan(data):
    """Normalize the actual 1022 JSON shape; drop source identity fields."""
    if not isinstance(data,dict):raise ValueError('source must be an object')
    def cents(value):
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):raise ValueError('source amount must be numeric')
        try:
            n=Decimal(str(value))*100
            if not n.is_finite() or n!=n.to_integral_value():raise ValueError('source amount must be finite with at most two decimals')
            return money(int(n))
        except InvalidOperation as exc:raise ValueError('invalid source amount') from exc
    try:
        accounts=[{'account_id':a['account_id'],'currency':'CNY','initial_balance_minor':cents(a['initial_balance']),
                   'balance_minor':cents(a['balance'])} for a in data['accounts']]
        rows=[]
        for t in data['transactions']:
            if t.get('status') not in ('completed','rejected'):raise ValueError('unsupported source status')
            value=cents(t['amount'])
            rows.append({'id':t['transaction_id'],'account_id':t['account_id'],'date':t['date'],
                         'amount_minor':value if t['transaction_type'] in INCOMING else -value,'type':t['transaction_type'],
                         'category':t['category'],'merchant':t['merchant'],'status':'booked' if t['status']=='completed' else 'rejected'})
            for field in ['duplicate_group_id','related_transaction_id','time','subscription_cycle','recurring','transfer_pair_id']:
                if field in t:rows[-1][field]=deepcopy(t[field])
            rows[-1]['raw_id']=t['transaction_id']
        out={'schema_version':'scenario-1.1','scenario_id':data['scenario_id'],'scenario_type':data['scenario_type'],
             'parameters':{'increase_minor':cents(data.get('scenario_requirements',{}).get('expected',{}).get('shopping_increase',800))},
             'accounts':accounts,'transactions':rows,'simulated':True,'ledger_modified':False,
             'source':{'provider':'Ethan 1022','sha256':hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()}}
    except (KeyError,TypeError) as exc:raise ValueError('source structure is incomplete') from exc
    errors=validate_environment(out)
    if errors:raise ValueError('; '.join(errors))
    return out
