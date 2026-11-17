"""Reproducible A-E, metrics, budget calendar, and delayed-income comparison."""
from pathlib import Path
import hashlib,json
from .scenarios import generate_environment,to_agent_scenario
from .finance import organize,calculate
from .lifestyle import plan_event,export_ics
from .simulation import compare_plans


def build_demo(output_dir,*,force=False):
    root=Path(output_dir)
    artifacts={}
    def add(name,value):artifacts[name]=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    for kind in 'ABCDE':
        data=generate_environment(kind,seed=42,as_of='2026-10-24')
        add(f'{kind}.json',data)
        add(f'{kind}_snapshot.json',organize(data));add(f'{kind}_metrics.json',calculate(data))
    add('second_agent_scenario.json',to_agent_scenario(generate_environment('A',seed=42,as_of='2026-10-24')))
    plan=plan_event(event_date='2026-11-02',as_of='2026-10-24',budget_minor=100000,available_minor=800000,emergency_reserve_minor=500000)
    add('birthday_plan.json',plan);artifacts['birthday_calendar.ics']=export_ics(plan)
    base=[{'id':'salary','date':'2026-11-01','amount_minor':500000,'basis':'hypothesis'},
          {'id':'rent','date':'2026-11-02','amount_minor':-300000,'basis':'contract'},
          {'id':'subscription','date':'2026-11-05','amount_minor':-10000,'basis':'contract'}]
    late=[{**e,'date':'2026-11-10'} if e['id']=='salary' else dict(e) for e in base]
    add('plan_comparison.json',compare_plans(start_date='2026-10-24',end_date='2026-11-30',start_balance_minor=350000,
        minimum_reserve_minor=100000,plans={'baseline':base,'income_delayed':late,
        'birthday_budget':base+[{'id':'birthday','date':'2026-11-02','amount_minor':-100000,'basis':'user_input'}],
        'subscription_cancelled':[e for e in base if e['id']!='subscription']}))
    manifest={name:hashlib.sha256(text.encode()).hexdigest() for name,text in artifacts.items()}
    add('manifest.json',{'files':manifest,'seed':42,'as_of':'2026-10-24','conclusion':'fixed inputs produce identical content'})
    if not force:
        occupied=[str(root/name) for name in artifacts if (root/name).exists()]
        if occupied:raise ValueError('refusing to overwrite demo files; choose another directory or --force')
    root.mkdir(parents=True,exist_ok=True)
    from .__main__ import save
    for name,text in artifacts.items():save(root/name,text,force)
    return {'status':'succeeded','output_dir':str(root.resolve()),'files':len(artifacts),'conclusion':'offline demonstration bundle generated'}
