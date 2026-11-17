"""Run from the toolkit root: python -m examples.main_agent_call."""
import json
from ethan_toolkit.tools import call_tool


def main():
    environment=call_tool('generate_environment',{'scenario_type':'B','seed':42,'as_of':'2026-10-24','increase_minor':80000})
    if environment['status']!='succeeded':raise RuntimeError(environment['error'])
    report=call_tool('calculate_financial_metrics',{'data':environment['data']})
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
