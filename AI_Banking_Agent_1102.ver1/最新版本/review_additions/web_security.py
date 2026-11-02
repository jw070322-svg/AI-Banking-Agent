"""Shared injection screening on real web calls; legacy ledger enforces authorization."""
from first_agent.service import Fault
from first_agent.vendor.eva.tool_calling.hardening import bounded_json
from first_agent.vendor.eva.security.injection import PromptInjectionGuard
from first_agent.vendor.eva.security.models import Decision
from first_agent.vendor.eva.security.compatibility import CompatibleScanner

class WebSecurity:
    def __init__(self):
        self.detector = PromptInjectionGuard(CompatibleScanner())

    def check(self, state, action, args):
        if not isinstance(args, dict):
            raise Fault('INVALID_ARGUMENT', '请求参数格式不正确')
        try:
            bounded_json(args)
        except Exception:
            raise Fault('INVALID_ARGUMENT', '请求结构过深、过大或包含不支持的数据')
        forbidden = {'userid','customerid','sid','sessionid','principal','permissions','scopes','roles'}
        def contains_identity(value):
            if isinstance(value, dict):
                return any(str(k).replace('_','').lower() in forbidden or contains_identity(v) for k,v in value.items())
            return isinstance(value,list) and any(contains_identity(v) for v in value)
        if contains_identity(args):
            raise Fault('IDENTITY_OVERRIDE_DENIED', '账户身份和权限由当前会话确定，不能在请求中更换', 403)
        text = None
        if action == 'chat': text = args.get('message')
        elif action in {'knowledge','external.search'}: text = args.get('question')
        elif action == 'rpc' and args.get('method') in {'assistant','interpret'}:
            values = args.get('args', [])
            if isinstance(values, list) and values: text = values[0]
        if text is None: return
        if not isinstance(text, str) or len(text) > 2000:
            raise Fault('INVALID_ARGUMENT', '请输入不超过2000字的需求')
        try:
            result = self.detector.screen_input(text, context={'user_id':state['customer_id']})
        except Exception:
            raise Fault('SECURITY_UNAVAILABLE', '安全检查暂不可用，请稍后重试；本次请求未执行', 503)
        if result.decision.decision != Decision.ALLOW:
            raise Fault('SECURITY_REVIEW_REQUIRED', '该请求涉及权限、隐私或确认限制，未执行。请在对应业务页面核对信息与授权', 403)
