"""Shared strict ledger boundary. All money is integer CNY minor units."""
from datetime import date
from collections import defaultdict

MAX_MONEY = 1_000_000_000
TYPES = {'income', 'income_reversal', 'expense', 'transfer_in', 'transfer_out', 'refund'}
INCOMING = {'income', 'transfer_in', 'refund'}


def money(value, name='amount', *, signed=False):
    if type(value) is not int or abs(value) > MAX_MONEY or (not signed and value < 0):
        raise ValueError(f'{name} must be integer minor units within bounds')
    return value


def iso_date(value):
    if not isinstance(value, str):
        raise ValueError('date must be YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('date must be YYYY-MM-DD')
    return parsed


def validate_ledger(data):
    errors = []
    if not isinstance(data, dict):
        return ['ledger must be an object']
    accounts, transactions = data.get('accounts'), data.get('transactions')
    if not isinstance(accounts, list) or not accounts:
        return ['accounts must be a nonempty list']
    if not isinstance(transactions, list):
        return ['transactions must be a list']
    if len(accounts) > 1000 or len(transactions) > 100000:
        return ['ledger exceeds fixture size limit']
    indexed, ids, valid_rows = {}, set(), []
    for n, a in enumerate(accounts):
        try:
            if not isinstance(a, dict): raise ValueError('account must be an object')
            key = a.get('account_id')
            if not isinstance(key, str) or not key.strip() or key in indexed:
                raise ValueError('account ID must be unique nonempty text')
            if a.get('currency') != 'CNY': raise ValueError('only CNY is supported')
            money(a.get('initial_balance_minor'), 'initial balance')
            money(a.get('balance_minor'), 'closing balance')
            indexed[key] = a
        except ValueError as exc: errors.append(f'accounts[{n}]: {exc}')
    for n, t in enumerate(transactions):
        try:
            if not isinstance(t, dict): raise ValueError('transaction must be an object')
            key=t.get('id');account=t.get('account_id')
            if not isinstance(key,str) or not key.strip() or key in ids:
                raise ValueError('transaction ID must be unique nonempty text')
            ids.add(key)
            if not isinstance(account,str) or account not in indexed: raise ValueError('unknown account')
            iso_date(t.get('date'))
            value=money(t.get('amount_minor'), signed=True)
            if t.get('status') not in ('booked','rejected'): raise ValueError('unsupported status')
            kind=t.get('type')
            if not isinstance(kind,str) or kind not in TYPES: raise ValueError('unsupported transaction type')
            if (kind in INCOMING and value < 0) or (kind not in INCOMING and value > 0):
                raise ValueError('amount sign conflicts with transaction type')
            for field in ('category','merchant'):
                if not isinstance(t.get(field),str) or not t[field].strip(): raise ValueError(f'{field} must be nonempty text')
            valid_rows.append(t)
        except (ValueError,TypeError) as exc: errors.append(f'transactions[{n}]: {exc}')
    if errors: return errors
    daily=defaultdict(lambda:defaultdict(int))
    for t in valid_rows:
        if t['status']=='booked':daily[t['account_id']][t['date']]+=t['amount_minor']
    for key,a in indexed.items():
        actual=a['initial_balance_minor']+sum(daily[key].values())
        if actual!=a['balance_minor']: errors.append(f'{key}: initial + booked transactions != closing balance')
        # Same-day ordering is unspecified; evaluate end-of-day balances only.
        balance=a['initial_balance_minor']
        for day in sorted(daily[key]):
            balance+=daily[key][day]
            if balance<0:errors.append(f'{key}: negative end-of-day balance on {day}')
    return errors


def require_ledger(data):
    errors=validate_ledger(data)
    if errors:raise ValueError('; '.join(errors))
