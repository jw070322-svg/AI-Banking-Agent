"""Conservative transfer candidates, never account resolution or authorization.

The supported grammar is deliberately finite. A complete sentence must match a
supported shape; amounts are validated as complete tokens, never searched out of
a longer token. Non-request speech acts do not supply actionable amounts.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import re

PARSER_VERSION = 'transfer-rules-1026.1'
MAX_AMOUNT_MINOR = 1_000_000_000
_TRANSLATION = str.maketrans('０１２３４５６７８９．－＋，　', '0123456789.-+, ')
_PREFIX = r'(?:请\s*)?(?:帮我\s*)?(?:我\s*)?(?:(?:要|想)\s*)?'
_ALIAS = r'[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·•._ -]{0,39}?'
_DIRECT = re.compile(_PREFIX + r'(?:给|向)\s*(?P<alias>' + _ALIAS + r')\s*(?:转账|转)\s*(?P<money>.*)')
_REVERSE = re.compile(_PREFIX + r'(?:转账|转)\s*(?P<money>.*?)\s*(?:给|向)\s*(?P<alias>' + _ALIAS + r')')
_TO = re.compile(_PREFIX + r'转(?:账)?给\s*(?P<alias>' + _ALIAS + r')\s*(?P<money>[+\-0-9一二三四五六七八九十百千万零〇两壹贰叁肆伍陆柒捌玖拾佰仟￥¥$].*)')
_TO_ONLY = re.compile(_PREFIX + r'转(?:账)?给\s*(?P<alias>' + _ALIAS + r')')
_AMOUNT_ONLY_REQUEST = re.compile(_PREFIX + r'(?:转账|转)\s*(?P<money>.*)')
_CORRECTION = re.compile(_PREFIX + r'(?:把\s*)?(?:金额\s*)?(?:改成|改为|调整为|换成)\s*(?P<money>.*)')
_CANCEL = re.compile(_PREFIX + r'(?:(?:取消|撤销)(?:(?:刚才|刚刚|上一笔|上笔|这笔|该笔|本次|当前|我的)的?)?(?:转账|请求|操作)?|不转了|算了)')
_UNRELATED = re.compile(r'余额|账单|消费|理财|推荐|投资|现金流|订阅|扣费|银行卡|卡管理|挂失|额度|储蓄|流动性|分析|数据|整理|查看|查询|什么|怎么|如何|为什么|你好|谢谢|不知道|不确定')
_UNITS = ('人民币', '块钱', '美元', '美金', '欧元', '日元', '港元', '港币', 'CNY', 'RMB', 'USD', 'EUR', 'JPY', 'HKD', '元', '块')
_UNIT_PATTERN = '|'.join(re.escape(unit) for unit in _UNITS)
_MONEY = re.compile(r'(?P<number>.*?)\s*(?P<unit>' + _UNIT_PATTERN + r')', re.I)
_DECIMAL = re.compile(r'[0-9]+(?:\.[0-9]{1,2})?')
_CNY_UNITS = {'人民币', '块钱', '元', '块', 'CNY', 'RMB'}
_ALTERNATIVES = re.compile(r'\s*[,，]?\s*(?:或者|还是|或|和)\s*')


def _candidate(speech_act='request', *, fragment=False, issues=()):
    return {
        'schema_version': '1.0', 'intent': 'transfer',
        'speech_act': speech_act, 'recipient_alias': None,
        'amount_text': None, 'amount_minor': None, 'currency_text': None,
        'issues': list(issues), 'is_fragment': fragment,
    }


def _money_fields(value: str) -> dict:
    value = value.strip()
    result = {'amount_text': None, 'amount_minor': None, 'currency_text': None, 'issues': []}
    if not value:
        result['issues'] = ['missing_amount']
        return result
    match = _MONEY.fullmatch(value)
    if match:
        number, unit = match['number'].strip(), match['unit']
        result.update(amount_text=number or None, currency_text=unit)
    else:
        number, unit = value, None
        result['amount_text'] = number
    if not number:
        result['issues'].append('missing_amount')
        return result
    # No alternate digit or separator is removed from this complete token.
    # Chinese numerals intentionally require clarification in this first version.
    if re.fullmatch(r'[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟点]+', number):
        result['issues'].append('unsupported_expression')
    elif len(number) > 32 or not _DECIMAL.fullmatch(number):
        result['issues'].append('amount_invalid')
    else:
        try:
            with localcontext() as ctx:
                ctx.prec = max(36, len(number) + 4)
                amount = Decimal(number)
                minor = int(amount * 100)
            if not 0 < minor <= MAX_AMOUNT_MINOR:
                result['issues'].append('amount_invalid')
            elif unit is not None and unit.upper() in _CNY_UNITS:
                result['amount_minor'] = minor
        except (InvalidOperation, ValueError, OverflowError):
            result['issues'].append('amount_invalid')
    if unit is None:
        result['issues'].append('missing_currency')
    elif unit.upper() not in _CNY_UNITS:
        result['issues'].append('currency_unsupported')
    return result


def _with_slots(alias, money, *, speech_act='request', fragment=False):
    candidate = _candidate(speech_act, fragment=fragment)
    candidate['recipient_alias'] = alias.strip() if alias else None
    pieces = _ALTERNATIVES.split(money.strip()) if money else []
    if len(pieces) > 1 and all(pieces):
        candidates = [_money_fields(piece) for piece in pieces]
        if all(item['amount_text'] and item['currency_text'] for item in candidates):
            candidate['issues'] = ['ambiguous_amount']
        else:
            candidate['issues'] = ['unsupported_expression']
    else:
        candidate.update(_money_fields(money))
    if candidate['recipient_alias'] is None and speech_act != 'correction':
        candidate['issues'].insert(0, 'missing_recipient')
    return candidate


def parse_transfer(text: str, *, context: bool = False) -> dict | None:
    """Return a candidate, or None for an unrelated task.

    is_fragment is true only for a standalone amount/name supplied while the
    caller explicitly awaits clarification. The caller must still bind that
    fragment to a particular draft; a complete new request must not inherit old
    fields. A candidate with issues or non-request speech_act is not executable.
    Amount text is the normalized complete lexical token, not a model guess.
    """
    if not isinstance(text, str):
        return _candidate('unknown', issues=['unsupported_expression'])
    value = text.strip().translate(_TRANSLATION).rstrip('。！!').strip()
    if not value or len(value) > 2000:
        return _candidate('unknown', issues=['unsupported_expression'])

    transfer_hint = bool(re.search(r'转账|转给|(?:给|向).{1,40}?转', value))
    correction = _CORRECTION.fullmatch(value)
    cancel = _CANCEL.fullmatch(value)
    if not transfer_hint and not context and not correction and not cancel:
        return None
    if not transfer_hint and not correction and not cancel and _UNRELATED.search(value):
        return None

    # Classify meaning before accepting any slots. These categories intentionally
    # expose no amount that a caller might mistake for an immediate instruction.
    if re.search(r'[“”‘’"\']|这句话|这句|示例|举例|例如|比如|怎么解析|如何解析', value):
        return _candidate('quoted_example')
    if re.search(r'[?？]|了吗|了么|了没|是否|是不是|能否|可否|怎么|如何|为什么|(?:到账|转账).*没有|转账记录|转账历史', value):
        return _candidate('question')
    if cancel:
        return _candidate('cancellation')
    if re.search(r'不要|别|不想|不需要|不转|不执行|禁止|仅(?:测试|模拟)|只(?:说说|解析)', value):
        return _candidate('negation')
    if re.search(r'如果|假如|假设|若|等到|等.{0,30}再|到账.{0,20}再|明天|后天|今晚|明早|明晚|下周|下月|预约|定时|周[一二三四五六日天]|[0-9]+[点时号日]', value):
        return _candidate('unknown', issues=['unsupported_expression'])
    action_count = len(re.findall(r'转账|转给|转(?=\s*[+\-0-9一二三四五六七八九十百千万零〇两])', value))
    if action_count > 1 or re.search(r'(?:再|然后|同时|另外|还有|并且).{0,12}(?:给|向)', value):
        return _candidate('unknown', issues=['multiple_requests'])

    if correction:
        return _with_slots(None, correction['money'], speech_act='correction')

    # '转给小王800元' must be parsed before the reverse-order grammar,
    # whose empty money group would otherwise swallow digits into the alias.
    for grammar in (_DIRECT, _TO, _REVERSE):
        match = grammar.fullmatch(value)
        if match:
            alias = match['alias'].strip()
            if re.search(r'和|以及|与|及|、', alias):
                return _candidate('unknown', issues=['multiple_requests'])
            return _with_slots(alias, match['money'])
    match = _TO_ONLY.fullmatch(value)
    if match:
        return _with_slots(match['alias'], '')
    match = _AMOUNT_ONLY_REQUEST.fullmatch(value)
    if match:
        return _with_slots(None, match['money'])

    # A new task must be allowed to leave a previous transfer clarification.
    if not transfer_hint and _UNRELATED.search(value):
        return None
    if context and not transfer_hint:
        if re.match(r'[+\-0-9一二三四五六七八九十百千万零〇两壹贰叁肆伍陆柒捌玖拾佰仟￥¥$]', value):
            return _with_slots(None, value, fragment=True)
        name = re.fullmatch(r'(?:收款人(?:是|为)?\s*)?(?P<alias>' + _ALIAS + r')', value)
        if name and not re.search(r'我|你|他|我们|这个|那个|确定|好的|知道|金额|取消|改成|改为', name['alias']):
            return _with_slots(name['alias'], '', fragment=True)
    if transfer_hint or context:
        return _candidate('unknown', issues=['unsupported_expression'])
    return None
