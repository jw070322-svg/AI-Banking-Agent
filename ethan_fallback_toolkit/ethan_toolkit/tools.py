"""Allowlisted, side-effect-free functions for a main Agent's tool dispatcher."""
from inspect import signature
from .finance import organize,calculate
from .lifestyle import plan_event,export_ics
from .models import validate_ledger
from .scenarios import generate_environment,parse_requirement,validate_environment,import_ethan,to_agent_scenario
from .simulation import simulate_cashflow,compare_plans
from .contracts import SCHEMAS,DESCRIPTIONS

FUNCTIONS={'generate_environment':generate_environment,'parse_requirement':parse_requirement,
           'validate_environment':validate_environment,'validate_ledger':validate_ledger,
           'import_ethan':import_ethan,'to_agent_scenario':to_agent_scenario,
           'organize_financial_data':organize,'calculate_financial_metrics':calculate,
           'simulate_cashflow':simulate_cashflow,'compare_plans':compare_plans,
           'plan_life_event':plan_event,'export_ics':export_ics}


def catalog():
    return [{'name':name,'python_signature':str(signature(fn)),'input_schema':SCHEMAS[name],'side_effects':False,
             'description':DESCRIPTIONS[name]} for name,fn in FUNCTIONS.items()]


def call_tool(name,arguments):
    result={'schema_version':'ethan-toolkit-1.0','tool':name if isinstance(name,str) else None,
            'simulated':True,'ledger_modified':False}
    if not isinstance(name,str) or name not in FUNCTIONS:
        return {**result,'status':'rejected','data':None,'error':{'code':'UNKNOWN_TOOL','message':'Tool is not registered'}}
    if not isinstance(arguments,dict):
        return {**result,'status':'rejected','data':None,'error':{'code':'INVALID_ARGUMENT','message':'arguments must be an object'}}
    try:
        signature(FUNCTIONS[name]).bind(**arguments)
        data=FUNCTIONS[name](**arguments)
        if name.startswith('validate_'):
            return {**result,'status':'succeeded' if not data else 'rejected','data':{'valid':not data,'errors':data},
                    'error':None if not data else {'code':'VALIDATION_FAILED','message':'Input failed validation'}}
        return {**result,'status':'succeeded','data':data,'error':None}
    except (ValueError,TypeError,KeyError,OverflowError,AttributeError) as exc:
        return {**result,'status':'rejected','data':None,'error':{'code':'INVALID_ARGUMENT','message':str(exc)}}
