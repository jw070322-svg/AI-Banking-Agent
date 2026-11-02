"""Authoritative, local-demo recipient directory shared by chat and forms.

The R-* entries are explicit synthetic recipients, not mappings to somebody
else's bank account. No account reference is accepted from language output.
"""
from copy import deepcopy
from .vendor.eva.data import BENEFICIARIES

DIRECTORY_VERSION = 'demo-recipients-2026-10-26.1'

DEMO_RECIPIENTS = (
    {'beneficiary_id': 'R-WANG', 'customer_id': 'CUST-001', 'name': '小王',
     'bank': '本地模拟收款目录', 'account_last4': '0001',
     'account_ref': 'demo-recipient:R-WANG', 'whitelisted': True,
     'added_days_ago': 365, 'note': '同学 · 虚构联系人'},
    {'beneficiary_id': 'R-LIN', 'customer_id': 'CUST-001', 'name': '林晓',
     'bank': '本地模拟收款目录', 'account_last4': '0002',
     'account_ref': 'demo-recipient:R-LIN', 'whitelisted': True,
     'added_days_ago': 365, 'note': '家人 · 虚构联系人'},
    {'beneficiary_id': 'R-CHEN', 'customer_id': 'CUST-001', 'name': '陈晨',
     'bank': '本地模拟收款目录', 'account_last4': '0003',
     'account_ref': 'demo-recipient:R-CHEN', 'whitelisted': True,
     'added_days_ago': 365, 'note': '朋友 · 虚构联系人'},
)


def default_directory():
    records = [deepcopy(item) for item in DEMO_RECIPIENTS]
    for item in BENEFICIARIES.values():
        item = deepcopy(item)
        item['account_ref'] = 'demo-recipient:' + item['beneficiary_id']
        item['note'] = '兼容演示收款人' if item['whitelisted'] else '演示名册未准入，不能转出'
        records.append(item)
    return records


def contacts_for(records, customer_id):
    """Display projection; never a source of authority from the client."""
    return [{'id': r['beneficiary_id'], 'name': r['name'], 'phone': {'R-WANG':'13800000001','R-LIN':'13800000002','R-CHEN':'13800000003'}.get(r['beneficiary_id'],''),
             'note': r.get('note', '虚构演示收款人'),
             'account_last4': r['account_last4'], 'whitelisted': r['whitelisted']}
            for r in records if r['customer_id'] == customer_id]
