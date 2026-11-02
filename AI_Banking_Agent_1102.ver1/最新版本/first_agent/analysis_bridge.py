"""Bridge between the persisted demo session ledger and the analysis toolkit.

The analysis module is bundled once in this delivery:

    Third_Agent/modules/主任务_金融分析与量化

It is imported at runtime (source of truth stays there) rather than copied into
vendor/, so algorithm and policy changes take effect without a second copy.
Set AI_BANKING_ANALYSIS_DIR when the project is placed elsewhere.

Read-only contract:
- converts the vv session state into the API contract scenario shape
  (integer minor units, booked status, no raw customer identifiers);
- never writes the ledger; every result carries ledger_modified=false.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS_DIR = BASE / 'modules' / '主任务_金融分析与量化'
ANALYSIS_DIR = Path(os.environ.get('AI_BANKING_ANALYSIS_DIR', DEFAULT_ANALYSIS_DIR))

# Tools safe to run against a customer session (no scenario generation here).
SESSION_TOOLS = {
    'bills.summary',
    'bills.categories',
    'anomalies.detect',
    'subscriptions.burden',
    'cashflow.project',
    'liquidity.available',
    'budget.advice',
    'analysis.pipeline',
    'data.organize',
}

# vv category codes -> Chinese report categories (unknown values pass through).
CATEGORY_MAP = {
    'income': '工资',
    'housing': '居住',
    'dining': '餐饮',
    'shopping': '购物',
    'transport': '交通',
    'subscription': '订阅',
    'other': '其他',
    'transfer': '转账',
    'investment': '理财',
    'redeem': '赎回',
    'medical': '医疗',
    'education': '教育',
    'travel': '旅行',
    'utilities': '日用',
    'entertainment': '娱乐',
}

STATUS_MAP = {
    'booked': 'booked',
    'pending': 'pending',
    'rejected': 'rejected',
    'failed': 'failed',
}

_MODULES: Optional[Dict[str, Any]] = None
_IMPORT_LOCK = threading.RLock()


class AnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _load_modules() -> Dict[str, Any]:
    with _IMPORT_LOCK:
        return _load_modules_locked()


def _load_modules_locked() -> Dict[str, Any]:
    global _MODULES
    if _MODULES is not None:
        return _MODULES
    if not ANALYSIS_DIR.exists():
        raise AnalysisError(
            'ANALYSIS_UNAVAILABLE',
            f'分析模块不可用，请检查路径或设置 AI_BANKING_ANALYSIS_DIR：{ANALYSIS_DIR}',
        )
    path = str(ANALYSIS_DIR)
    added = path not in sys.path
    if added:
        sys.path.insert(0, path)
    try:
        import tools as analysis_tools  # type: ignore
        import organizer as analysis_organizer  # type: ignore
    except ImportError as exc:
        raise AnalysisError('ANALYSIS_UNAVAILABLE', f'分析模块导入失败：{exc}') from exc
    finally:
        # Keep sys.path clean: the sibling project has its own tests package,
        # which would shadow FirstAgent's tests in spawned worker processes.
        if added:
            try:
                sys.path.remove(path)
            except ValueError:
                pass
    _MODULES = {'tools': analysis_tools, 'organizer': analysis_organizer}
    return _MODULES


def analysis_status() -> Dict[str, Any]:
    try:
        _load_modules()
    except AnalysisError as exc:
        return {
            'available': False,
            'directory': str(ANALYSIS_DIR),
            'tools': sorted(SESSION_TOOLS),
            'error': {'code': exc.code, 'message': exc.message},
        }
    return {
        'available': True,
        'directory': str(ANALYSIS_DIR),
        'tools': sorted(SESSION_TOOLS),
        'error': None,
    }


def _shift_month(value: date, delta: int) -> date:
    index = value.year * 12 + (value.month - 1) + delta
    year, month_index = divmod(index, 12)
    month = month_index + 1
    next_month = date(year, month, 28) + timedelta(days=4)
    last_day = (next_month.replace(day=1) - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def _parse_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def session_date(state: Dict[str, Any]) -> date:
    day = state.get('day')
    if isinstance(day, int) and not isinstance(day, bool) and day > 0:
        return datetime.fromtimestamp(day / 1000, timezone.utc).date()
    return datetime.now(timezone.utc).date()


def _scenario_transactions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    transactions: List[Dict[str, Any]] = []
    for item in state.get('transactions', []) or []:
        if not isinstance(item, dict):
            continue
        amount = item.get('amount')
        if isinstance(amount, bool) or not isinstance(amount, int):
            continue
        raw_category = item.get('category') or 'other'
        if raw_category == 'income':
            transaction_type = 'income'
        elif raw_category == 'transfer':
            transaction_type = 'transfer_out'
        elif raw_category == 'investment':
            transaction_type = 'investment_purchase'
        elif raw_category == 'redeem':
            transaction_type = 'investment_redemption'
        elif amount > 0:
            transaction_type = 'refund'
        else:
            transaction_type = 'expense'
        transactions.append({
            'transaction_id': str(item.get('id')),
            'account_id': 'ACC-4821',
            'date': item.get('date'),
            'amount_minor': abs(amount),
            'amount': amount,
            'direction': 'credit' if amount > 0 else 'debit',
            'transaction_type': transaction_type,
            'category': CATEGORY_MAP.get(raw_category, str(raw_category)),
            'merchant': item.get('name') or '',
            'description': item.get('note') or item.get('name') or '',
            'status': STATUS_MAP.get(item.get('status'), 'pending'),
        })
    return transactions


def _scenario_subscriptions(
    state: Dict[str, Any],
    transactions: List[Dict[str, Any]],
    base_date: date,
) -> List[Dict[str, Any]]:
    subscriptions: List[Dict[str, Any]] = []
    for item in state.get('subscriptions', []) or []:
        if not isinstance(item, dict):
            continue
        amount = item.get('amount')
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            continue
        name = item.get('name') or item.get('id') or '订阅服务'
        charges = [
            t for t in transactions
            if t['category'] == '订阅' and t['merchant'] == name
        ]
        last_charge = max(
            (t['date'] for t in charges if _parse_date(t['date'])),
            key=_parse_date,
            default=None,
        )
        next_charge = _shift_month(_parse_date(last_charge) or base_date, 1)
        subscriptions.append({
            'subscription_id': str(item.get('id')),
            'merchant': name,
            'amount_minor': amount,
            'cycle': 'monthly',
            'category': '订阅',
            'last_charge_date': last_charge,
            'next_charge_date': next_charge.isoformat(),
            'status': 'active' if item.get('status') == 'active' else 'cancelled',
        })
    return subscriptions


def session_to_scenario(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a vv session state into the analysis contract scenario."""
    base_date = session_date(state)
    available = state.get('available')
    if isinstance(available, bool) or not isinstance(available, int):
        available = 0
    transactions = _scenario_transactions(state)
    subscriptions = _scenario_subscriptions(state, transactions, base_date)
    sid = state.get('session_id') or 'unknown'
    net = sum(t['amount'] for t in transactions if t['status'] == 'booked')
    reserves=[x for x in state.get('event_reservations',{}).values() if x['status']=='reserved']
    return {
        'schema_version': '1.0.0',
        'scenario_id': f'SESSION-{sid[:12]}',
        'scenario_type': 'SESSION',
        'scenario_name': '当前演示会话',
        'created_at': datetime(
            base_date.year, base_date.month, base_date.day
        ).isoformat(timespec='seconds'),
        'currency': 'CNY',
        'ledger_modified': False,
        'user': {'user_id': state.get('customer_id')},
        'accounts': [{
            'account_id': 'ACC-4821',
            'user_id': state.get('customer_id'),
            'account_type': '活期',
            'currency': 'CNY',
            'initial_balance_minor': available - net,
            'balance_minor': available,
            'status': '正常',
        }],
        'transactions': transactions,
        'subscriptions': subscriptions,
        'cards': [{
            'card_id': c['id'], 'card_type': c['kind'],
            'masked_card_number': '**** **** **** ' + c['last4'],
            'status': c['status'],
            'transaction_limit_minor': c['limit'],
            'spent_today_minor': c['spent'] if c.get('spentDay') == state.get('day') else 0,
            'source': 'session_ledger',
        } for c in state.get('cards', [])],
        'calendar_events': [],
        'budget': {'locked_amount_minor':sum(x['amount_minor'] for x in reserves)},
        'activity_calendar': [{'date':x['date'],'title':x['title'],'budget_minor':x['amount_minor'],'status':'planned','event_id':x['event_id']} for x in reserves],
        'cashflow_assumptions': {**state.get('simulation',{}),'monthly_expense_minor':max(0,state.get('simulation',{}).get('monthly_expense_minor',state['budget'])-sum(x['amount'] for x in state['subscriptions'] if x['status']=='cancelled'))},
        'expected_insights': [],
    }


def _normalize_arguments(arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise AnalysisError('INVALID_ARGUMENT', '分析参数必须为对象')
    normalized: Dict[str, Any] = {}
    for key, value in arguments.items():
        if key in {'days', 'year'} and isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise AnalysisError('INVALID_ARGUMENT', f'{key} 必须是整数') from None
        normalized[key] = value
    return normalized


def run_analysis_tool(
    tool: str,
    arguments: Optional[Dict[str, Any]],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Run one read-only analysis tool against the current session state."""
    if tool not in SESSION_TOOLS:
        raise AnalysisError('TOOL_NOT_REGISTERED', f'不支持的分析工具：{tool}')
    modules = _load_modules()
    scenario = session_to_scenario(state)
    args = _normalize_arguments(arguments)
    if set(args) - {'days', 'month', 'year'}:
        raise AnalysisError('INVALID_ARGUMENT', '会话分析只接受 days/month/year，不接受文件、评测答案或客户端账本')
    if tool == 'data.organize':
        if set(args) - {'days'}:
            raise AnalysisError('INVALID_ARGUMENT', 'data.organize 仅接受 days，上下文来自服务端会话')
        try:
            package = modules['organizer'].organize(scenario, session_context(state, args))
        except (ValueError, TypeError) as exc:
            raise AnalysisError('INVALID_ARGUMENT', str(exc)) from exc
        return {'tool': tool, 'source': 'session_ledger', 'result': package,
                'simulated': True, 'ledger_modified': False}
    result = modules['tools'].call_tool(
        tool, args, data=scenario
    )
    if result.get('status') != 'succeeded':
        error = result.get('error') or {}
        raise AnalysisError(
            error.get('code', 'ANALYSIS_FAILED'),
            error.get('message', '分析工具执行失败'),
        )
    return {
        'tool': tool,
        'source': 'session_ledger',
        'result': result.get('data'),
        'simulated': True,
        'ledger_modified': False,
    }


def session_context(state: Dict[str, Any], arguments=None) -> Dict[str, Any]:
    personal=state.get('personal_profile',{});goal=dict(state['goal'])
    goal['need']+=sum(x['amount_minor'] for x in state.get('event_reservations',{}).values() if x['status']=='reserved')
    return {
        'source': 'session_ledger', 'days': (arguments or {}).get('days', 30),
        'configured_amount_minor': state['amount'], 'goal': goal,
        'consent': dict(state['consent']),
        'profile': {'risk_tolerance': personal.get('risk_tolerance',1) if state['profile'] == 'valid' else None,
                    'risk_capacity': personal.get('risk_capacity',1), 'max_redemption_days': 1,
                    'objective': 'liquidity', 'preferred_categories': ['cash']},
    }


def generate_scenario(
    prompt: str,
    scenario_type: Optional[str] = None,
    seed: Optional[int] = None,
    reference_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate an independent demo scenario through the environment agent."""
    modules = _load_modules()
    # Upstream generation uses a process-global seed/date. Serialize this boundary.
    with _IMPORT_LOCK:
        before_path = list(sys.path)
        try:
            result = modules['tools'].call_tool('scenario.generate', {
                'prompt': prompt,
                'scenario_type': scenario_type,
                'seed': seed,
                'reference_date': reference_date,
            })
        finally:
            sys.path[:] = before_path
    if result.get('status') != 'succeeded':
        error = result.get('error') or {}
        raise AnalysisError(
            error.get('code', 'SCENARIO_GENERATION_FAILED'),
            error.get('message', '场景生成失败'),
        )
    return {**result['data'], 'schema_version': '1.0.0', 'simulated': True,
            'ledger_modified': False}
