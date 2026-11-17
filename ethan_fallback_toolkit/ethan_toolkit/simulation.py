"""Explicit dated cash events; no forecasts inferred and no live ledger mutation."""
from collections import defaultdict
from .models import iso_date, money
from .finance import fingerprint


def simulate_cashflow(*,start_date,end_date,start_balance_minor,events,minimum_reserve_minor=0):
    lo,hi=iso_date(start_date),iso_date(end_date)
    if lo>hi or (hi-lo).days>3660:raise ValueError('simulation range must be 0-3660 days')
    money(start_balance_minor,'start_balance_minor');money(minimum_reserve_minor,'minimum_reserve_minor')
    if not isinstance(events,list) or len(events)>10000:raise ValueError('events must be a list of at most 10000')
    ids=set();daily=defaultdict(list);excluded=[]
    for event in events:
        if not isinstance(event,dict):raise ValueError('event must be an object')
        key=event.get('id')
        if not isinstance(key,str) or not key.strip() or key in ids:raise ValueError('event IDs must be unique text')
        ids.add(key)
        d=iso_date(event.get('date'));money(event.get('amount_minor'),signed=True)
        if event.get('basis') not in ('user_input','contract','hypothesis'):raise ValueError('event basis must be explicit')
        effective=iso_date(event.get('effective_from',event['date']))
        if d<lo or d>hi or d<effective:excluded.append({'id':key,'reason':'outside period or before effective_from'});continue
        daily[event['date']].append(dict(event))
    balance=start_balance_minor;minimum=balance;minimum_date=start_date
    conservative_minimum=balance;timeline=[];shortfalls=[]
    if balance<minimum_reserve_minor:shortfalls.append({'date':start_date,'balance_minor':balance,'shortfall_minor':minimum_reserve_minor-balance})
    for day,items in sorted(daily.items()):
        outgoing=sum(e['amount_minor'] for e in items if e['amount_minor']<0)
        conservative_minimum=min(conservative_minimum,balance+outgoing)
        opening=balance;delta=sum(e['amount_minor'] for e in items);balance+=delta
        if balance<minimum:minimum,minimum_date=balance,day
        if balance<minimum_reserve_minor:shortfalls.append({'date':day,'balance_minor':balance,'shortfall_minor':minimum_reserve_minor-balance})
        timeline.append({'date':day,'opening_minor':opening,'movement_minor':delta,'closing_minor':balance,'events':sorted(items,key=lambda e:e['id'])})
    return {'schema_version':'cash-simulation-1.0','period':{'start':start_date,'end':end_date},
            'opening_minor':start_balance_minor,'closing_minor':balance,'net_cashflow_minor':balance-start_balance_minor,
            'minimum_balance_minor':minimum,'minimum_balance_date':minimum_date,
            'conservative_intraday_minimum_minor':conservative_minimum,'minimum_reserve_minor':minimum_reserve_minor,
            'shortfalls':shortfalls,'timeline':timeline,'excluded_events':excluded,
            'assumptions':['minimum_balance is end-of-day plus opening balance; dates without events are unchanged',
                           'intraday lower bound assumes all debits occur before credits on the same day',
                           'hypothetical events are not promised income or executed transactions'],
            'input_hash':fingerprint({'start':start_date,'end':end_date,'balance':start_balance_minor,'reserve':minimum_reserve_minor,'events':events}),
            'planned_only':True,'ledger_modified':False}


def compare_plans(*,start_date,end_date,start_balance_minor,plans,minimum_reserve_minor=0):
    if not isinstance(plans,dict) or not 1<=len(plans)<=20:raise ValueError('plans must contain 1-20 named event lists')
    if not all(isinstance(k,str) and k.strip() for k in plans):raise ValueError('plan names must be nonempty text')
    return {'schema_version':'plan-comparison-1.0','plans':{name:simulate_cashflow(start_date=start_date,end_date=end_date,
            start_balance_minor=start_balance_minor,events=events,minimum_reserve_minor=minimum_reserve_minor) for name,events in plans.items()},
            'selection':'user decision required; no automatic execution','ledger_modified':False}
