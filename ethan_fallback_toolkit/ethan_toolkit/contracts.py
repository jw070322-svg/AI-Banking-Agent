"""JSON input schemas for integration; runtime validators remain authoritative."""
MONEY={'type':'integer','minimum':0,'maximum':1000000000}
DAY={'type':'string','format':'date','pattern':r'^\d{4}-\d{2}-\d{2}$'}
TEXT={'type':'string'}
LEDGER={'type':'object','required':['accounts','transactions'],
        'properties':{'accounts':{'type':'array','minItems':1},'transactions':{'type':'array'}}}
PERIOD={'start_date':DAY,'end_date':DAY}


def obj(properties,required):return {'type':'object','properties':properties,'required':required,'additionalProperties':False}


SCHEMAS={
 'generate_environment':obj({'scenario_type':{'type':'string','enum':list('ABCDE')},'seed':{'type':'integer','minimum':0,'maximum':4294967295},
                              'as_of':DAY,'increase_minor':{'type':'integer','minimum':1,'maximum':100000000}},[]),
 'parse_requirement':obj({'text':{'type':'string','minLength':1,'maxLength':2000}},['text']),
 'validate_environment':obj({'data':LEDGER},['data']),
 'validate_ledger':obj({'data':LEDGER},['data']),
 'import_ethan':obj({'data':{'type':'object'}},['data']),
 'to_agent_scenario':obj({'data':LEDGER},['data']),
 'organize_financial_data':obj({'data':LEDGER,**PERIOD},['data']),
 'calculate_financial_metrics':obj({'data':LEDGER,**PERIOD,'liquid_assets_minor':MONEY,'monthly_debt_payment_minor':MONEY,'essential_monthly_expense_minor':MONEY},['data']),
 'simulate_cashflow':obj({**PERIOD,'start_balance_minor':MONEY,'minimum_reserve_minor':MONEY,'events':{'type':'array','maxItems':10000}},['start_date','end_date','start_balance_minor','events']),
 'compare_plans':obj({**PERIOD,'start_balance_minor':MONEY,'minimum_reserve_minor':MONEY,'plans':{'type':'object','minProperties':1,'maxProperties':20}},['start_date','end_date','start_balance_minor','plans']),
 'plan_life_event':obj({'event_date':DAY,'as_of':DAY,'budget_minor':MONEY,'available_minor':MONEY,'emergency_reserve_minor':MONEY,
                       'label':{'type':'string','minLength':1,'maxLength':200},'currency':{'type':'string','enum':['CNY']}},['event_date','as_of','budget_minor','available_minor']),
 'export_ics':obj({'plan':{'type':'object'}},['plan'])}

DESCRIPTIONS={
 'generate_environment':'Generate a deterministic, reconciled A-E synthetic banking environment with a seed and reference date.',
 'parse_requirement':'Parse supported Chinese scenario descriptions into A-E and an exact integer shopping increase.',
 'validate_environment':'Check ledger structure, money, dates, balances and the specified A-E semantic requirements.',
 'validate_ledger':'Check canonical CNY ledger structure, unique identifiers and end-of-day reconciliation.',
 'import_ethan':'Import original Ethan 1022 yuan-based JSON, preserving business semantics and removing user identity fields.',
 'to_agent_scenario':'Produce a read-only scenario-1.0 projection compatible with SecondAsgent; not a financial-analysis input.',
 'organize_financial_data':'Build a dated snapshot with source hashes, reconciliation and unconfirmed duplicate/subscription candidates.',
 'calculate_financial_metrics':'Compute booked income, refunds, consumption, transfers, monthly summaries and explicitly defined ratios.',
 'simulate_cashflow':'Simulate user-supplied dated events and minimum cash balances without changing any live ledger.',
 'compare_plans':'Compare named deterministic cashflow plans; does not choose or execute a plan.',
 'plan_life_event':'Draft an affordable life-event budget and dated reminders, respecting the stated reserve.',
 'export_ics':'Render a draft life-event calendar as escaped, folded ICS text; does not publish or schedule anything.'}
