"""Banking Agent dashboard. Run: python -m streamlit run Dashboard/dashboard_ui.py

Synthetic, local-only prototype. No bank API, LLM, purchase, or return promise.
BANKING_QUOTA_FILE enables a trusted host's live five-hour Codex quota snapshots.
Without it, quota is explicitly simulated (BANKING_DEMO_QUOTA, default 100).
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

VERSION = 'dashboard-v1.2'
POLICY = 'educational-matching-v1'
LOG_KEYS = ('user_id', 'intent', 'tool', 'input', 'output', 'risk_check', 'approval', 'timestamp')
PAGES = ('财务总览', '产品匹配', '情景验证', '方案与活动')
OBJECTIVES = ('流动性优先', '风险优先', '期限贴合')


def utcnow():
    return datetime.now(timezone.utc)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def money(minor):
    return f'¥{minor / 100:,.0f}'


@dataclass(frozen=True)
class Profile:
    cash: int = 15_430_000
    essential: int = 750_000
    obligations: int = 500_000
    reserve_months: int = 3
    amount: int = 3_000_000
    horizon: int = 90
    tolerance: int = 3
    capacity: int = 2
    objective: str = '流动性优先'

    def validate(self):
        if any(type(getattr(self, key)) is not int or getattr(self, key) < 0
               for key in ('cash', 'essential', 'obligations', 'amount')):
            raise ValueError('金额必须是非负整数分。')
        if self.amount <= 0:
            raise ValueError('计划金额必须大于零。')
        if type(self.reserve_months) is not int or not 1 <= self.reserve_months <= 12:
            raise ValueError('储备月数应为1–12。')
        if type(self.horizon) is not int or not 1 <= self.horizon <= 3650:
            raise ValueError('资金使用期限无效。')
        if any(type(x) is not int or not 1 <= x <= 5 for x in (self.tolerance, self.capacity)):
            raise ValueError('风险偏好与承受能力都必须明确，范围1–5。')
        if self.objective not in OBJECTIVES:
            raise ValueError('未知匹配偏好。')

    @property
    def reserve(self):
        return self.essential * self.reserve_months + self.obligations

    @property
    def available(self):
        return max(0, self.cash - self.reserve)


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    risk: int
    lock_days: int
    minimum: int
    description: str


PRODUCTS = (
    Product('SIM-01', '随需 · 灵活计划', '流动性示例', 1, 0, 10_000,
            '用于比较流动性需求的虚构产品，演示设定为无锁定期。'),
    Product('SIM-02', '稳序 · 90天计划', '固定期限示例', 2, 90, 100_000,
            '用于测试三个月资金安排；锁定期间不计作可立即使用现金。'),
    Product('SIM-03', '均衡 · 180天计划', '中期配置示例', 3, 180, 500_000,
            '用于测试中期资金与较高风险约束，无真实收益数据。'),
    Product('SIM-04', '远望 · 长期计划', '长期配置示例', 5, 365, 1_000_000,
            '用于检验风险及期限排除规则，不提供真实投资建议。'),
)
CATALOG_VERSION = fingerprint([asdict(p) for p in PRODUCTS])[:12]


def profile_key(profile):
    return fingerprint(dict(profile=asdict(profile), catalog=CATALOG_VERSION, policy=POLICY))


def match_products(profile):
    profile.validate()
    results = []
    for p in PRODUCTS:
        reasons = []
        if p.risk > min(profile.tolerance, profile.capacity):
            reasons.append('风险等级超过偏好或承受能力')
        if p.lock_days > profile.horizon:
            reasons.append('锁定期超过资金可用期限')
        if profile.amount < p.minimum:
            reasons.append('计划金额低于起始金额')
        if profile.amount > profile.available:
            reasons.append('分配后不足以覆盖现金储备和近期支出')
        # Sort only eligible products. These are ordering points, not probabilities.
        if profile.objective == '流动性优先':
            order = (p.lock_days, p.risk, p.id)
        elif profile.objective == '风险优先':
            order = (p.risk, p.lock_days, p.id)
        else:
            order = (abs(profile.horizon - p.lock_days), p.risk, p.id)
        results.append(dict(product=asdict(p), eligible=not reasons, reasons=reasons,
                            order=order, input_key=profile_key(profile)))
    return sorted(results, key=lambda x: (not x['eligible'], x['order']))


def stress_test(profile, product_id, extra_expense, delayed_income):
    profile.validate()
    if any(type(v) is not int or v < 0 for v in (extra_expense, delayed_income)):
        raise ValueError('压力金额必须为非负整数分。')
    product = next((p for p in PRODUCTS if p.id == product_id), None)
    if product is None:
        raise ValueError('未知产品，请重新选择。')
    current = next(r for r in match_products(profile) if r['product']['id'] == product_id)
    if not current['eligible']:
        raise ValueError('当前条件下该方案已不匹配，请重新生成方案。')
    # Delayed income is a future cash shortfall, not a reversal of historical cash.
    accessible_after = profile.cash - profile.amount + (profile.amount if product.lock_days == 0 else 0)
    required = profile.reserve + extra_expense + delayed_income
    return dict(accessible_after=accessible_after, required=required,
                gap=max(0, required - accessible_after),
                passed=accessible_after >= required, product_id=product_id,
                extra_expense=extra_expense, delayed_income=delayed_income,
                assumption='按锁定期内即时赎回能力演示；延期收入作为额外现金缓冲需求。')


def make_plan(profile, product_id, confirmed):
    if confirmed is not True:
        raise ValueError('请先确认这只是模拟方案。')
    row = next((r for r in match_products(profile) if r['product']['id'] == product_id), None)
    if row is None:
        raise ValueError('未知产品，请重新选择。')
    if not row['eligible']:
        raise ValueError('当前条件不匹配，无法保存方案。')
    key = fingerprint(dict(input_key=profile_key(profile), product_id=product_id))
    return dict(plan_id='PLAN-' + key[:12], input_key=profile_key(profile),
                product=row['product'], profile=asdict(profile), amount=profile.amount,
                status='saved_simulation', created_at=utcnow().isoformat(),
                catalog_version=CATALOG_VERSION, policy_version=POLICY,
                matching_basis=row, stress_status='not_run', cash_changed=False)


def read_quota(path=None, demo_value=None, now=None):
    """Use only the five-hour window. Unavailable data is never interpreted as 100%."""
    moment = now or utcnow()
    if path is None:
        value = float(os.environ.get('BANKING_DEMO_QUOTA', '100') if demo_value is None else demo_value)
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError('invalid_demo_quota')
        return dict(source='simulated', scope='demo', remaining_percent=value,
                    observed_at=moment.isoformat(), window_minutes=300)
    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if raw.get('source') != 'codex_host' or raw.get('scope') != 'codex' or raw.get('window_minutes') != 300:
        raise ValueError('wrong_quota_scope')
    value = raw.get('remaining_percent')
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('invalid_remaining')
    stamp = datetime.fromisoformat(raw['observed_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or not -5 <= (moment - stamp).total_seconds() <= 90:
        raise ValueError('stale_or_future_quota')
    return {key: raw[key] for key in ('source', 'scope', 'remaining_percent', 'observed_at', 'window_minutes')}


def quota_halts(snapshot):
    return snapshot['remaining_percent'] < 10  # Latest user requirement: strictly below.


def event(intent, tool, inputs, outputs, risk='本地合成数据；无真实资金操作。', approval='DEMO_ONLY'):
    return dict(user_id='SIM-USER-01', intent=intent, tool=tool, input=canonical(inputs),
                output=canonical(outputs), risk_check=risk, approval=approval,
                timestamp=utcnow().isoformat())


def audit(intent, tool, inputs, outputs, **kwargs):
    st.session_state.events.append(event(intent, tool, inputs, outputs, **kwargs))


def context_markdown(state):
    payload = {key: state.get(key) for key in ('session_id', 'page', 'profile', 'results',
               'selected', 'stress', 'stress_key', 'stress_inputs', 'plans', 'halted', 'confirmed', 'halt_reason', 'quota', 'active_key')}
    payload.update(version=VERSION, policy_version=POLICY, catalog_version=CATALOG_VERSION)
    payload['draft_inputs'] = {key: state.get(key) for key in (
        'cash_input','essential_input','obligations_input','amount_input','horizon_input',
        'reserve_input','tolerance_input','capacity_input','objective_input','extra_stress','delay_stress')}
    text = '# Banking Agent 会话成果与接续上下文\n\n'
    text += '所有方案均为演示；保存不代表申购或转账。额度停止后不能自动续跑。\n\n'
    text += '## 当前状态\n\n```json\n' + json.dumps(payload, ensure_ascii=False, indent=2) + '\n```\n'
    text += '\n## 下一步\n\n核对额度来源及有效期；重新开启会话并重新确认当前条件。已保存方案用于审阅，不可重放为真实交易。\n'
    text += '\n## 完整事件日志\n'
    for i, record in enumerate(state.get('events', []), 1):
        text += f'\n### {i:03d} {record["intent"]}\n\n```json\n'
        text += json.dumps(record, ensure_ascii=False, indent=2) + '\n```\n'
    return text


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def persist():
    path = Path(os.environ.get('BANKING_SESSION_DIR', Path(__file__).parent / '.sessions'))
    destination = path / f'{st.session_state.session_id}.md'
    try:
        atomic_write(destination, context_markdown(st.session_state))
        st.session_state.save_error = None
    except OSError as exc:
        st.session_state.save_error = type(exc).__name__


def init_state():
    defaults = dict(session_id=uuid4().hex, page=PAGES[0], profile=asdict(Profile()),
                    results=[], selected=None, stress=None, stress_key=None,
                    stress_inputs={'extra': 20000, 'delay': 18000}, plans=[], events=[],
                    halted=False, halt_reason=None, quota=None, active_key=None,
                    save_error=None, confirmed=False)
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.events:
        audit('session_started', 'UI', {'version': VERSION}, '本地演示会话已建立')
        persist()


def check_session_quota():
    if st.session_state.halted:
        return False
    try:
        snapshot = read_quota(os.environ.get('BANKING_QUOTA_FILE'))
        old = st.session_state.quota
        st.session_state.quota = snapshot
        if old is None or (old['remaining_percent'], old['scope']) != (snapshot['remaining_percent'], snapshot['scope']):
            audit('quota_checked', 'QuotaProvider', {'window_minutes': 300}, snapshot)
        reason = 'five_hour_quota_below_10_percent' if quota_halts(snapshot) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        reason = 'quota_unavailable:' + type(exc).__name__
    if reason:
        st.session_state.halted = True
        st.session_state.halt_reason = reason
        audit('session_halted', 'QuotaGuard', {'threshold': '<10%'}, reason,
              risk='已停止新匹配和方案保存，仅封存和下载已有成果。', approval='HALTED')
        persist()
        return False
    return True


def action_guard():
    if not check_session_quota():
        st.rerun()


def goto(page):
    st.session_state.page = page


CSS = '''<style>
:root { --ink:#152f37; --muted:#60777c; --accent:#087e70; }
.stApp { background:#f3f6f5; color:var(--ink); }
header[data-testid="stHeader"] { background:rgba(243,246,245,.94); }
.block-container { max-width:1320px; padding-top:4.5rem; padding-bottom:3rem; }
h1,h2,h3 { color:var(--ink); letter-spacing:-.035em; }
h1 { font-size:2.35rem!important; font-weight:650!important; }
[data-testid="stSidebar"] { background:#102e36; }
[data-testid="stSidebar"] * { color:#e5efed; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:#b9cdcc; }
[data-testid="stSidebar"] button { background:#23464d; border:1px solid #48656b; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { padding:.3rem 0; }
[data-testid="stVerticalBlockBorderWrapper"]>div { border-radius:16px!important; }
div[data-testid="stMetric"] { background:white; border:1px solid #e0e8e5; padding:18px 20px; border-radius:14px; }
[data-testid="stMetricValue"] { font-size:1.8rem; color:var(--ink); }
[data-testid="stMetricLabel"] { color:#60777c; }
button[kind="primary"] { background:#087e70; border-color:#087e70; border-radius:9px; }
button[kind="secondary"] { border-radius:9px; }
.eyebrow { font-size:.72rem; letter-spacing:.17em; color:#557271; font-weight:700; }
.hero { background:#e4efea; border:1px solid #cfdfd7; padding:28px 32px; border-radius:18px; margin:12px 0 24px; }
.hero h2 { margin:8px 0 12px; font-size:1.95rem; }
.hero p { color:#3e625d; max-width:660px; margin:0; line-height:1.8; }
.tag { display:inline-block; font-size:.76rem; padding:4px 10px; border-radius:20px; color:#175e50; background:#e0eee8; }
.product-title { margin:10px 0 6px; font-size:1.28rem; font-weight:650; }
.detail { color:#5b7276; font-size:.86rem; line-height:1.8; }
.rule-row { border-bottom:1px solid #dce6e1; padding:12px 0; display:flex; justify-content:space-between; }
.sidebar-brand { font-size:1.45rem; letter-spacing:-.04em; font-weight:700; margin:8px 0 0; }
@media(max-width:700px) { .block-container {padding:4.5rem 1rem 3rem;} .hero {padding:20px;} h1{font-size:1.8rem!important;} }
</style>'''


def page_header(kicker, title, subtitle):
    st.markdown(f'<div class="eyebrow">{html.escape(kicker)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(subtitle)


def render_overview():
    p = Profile(**st.session_state.profile)
    page_header('YOUR FINANCIAL SPACE / 01', '财务总览', '演示账户 · CNY人民币 · 合成数据，不连接真实银行')
    st.markdown('''<div class="hero"><span class="tag">从现金流出发</span>
<h2>让每一笔钱，都有合适的安排。</h2>
<p>先照顾未来的生活，再寻找适合的产品。把可用资金、使用期限与风险承受能力放在同一张图里。</p></div>''', unsafe_allow_html=True)
    for column, label, value, note in zip(st.columns(4),
            ('可用现金', '预留现金', '可规划金额', '已保存方案'),
            (money(p.cash), money(p.reserve), money(p.available), str(len(st.session_state.plans))),
            ('当前匹配假设', f'{p.reserve_months}个月必要支出 + 近期义务', '扣除预留后的上限', '仅方案，不扣款')):
        with column:
            st.metric(label, value)
            st.caption(note)
    st.write('')
    left, right = st.columns([1.8, 1], gap='large')
    with left, st.container(border=True):
        st.subheader('收支有序，规划有底')
        st.caption('近六个月固定演示流水 · 与右侧匹配假设独立')
        rows = []
        for month, income, expense in zip(('05月','06月','07月','08月','09月','10月'),
                                         (16500,18000,18000,18000,19000,18000),
                                         (11300,10800,11000,9600,10300,10200)):
            rows += [{'月份':month,'类型':'收入','金额':income}, {'月份':month,'类型':'支出','金额':expense}]
        st.vega_lite_chart(rows, {'mark':{'type':'bar','cornerRadiusTopLeft':4,'cornerRadiusTopRight':4},
            'encoding':{'x':{'field':'月份','type':'ordinal','axis':{'labelAngle':0,'title':None}},
                        'y':{'field':'金额','type':'quantitative','title':'人民币 / 元'},
                        'xOffset':{'field':'类型'},
                        'color':{'field':'类型','scale':{'domain':['收入','支出'],'range':['#168475','#bacfc5']},'legend':{'orient':'bottom'}},
                        'tooltip':[{'field':'月份'},{'field':'类型'},{'field':'金额','format':',.0f'}]},
            'height':235,'config':{'view':{'stroke':None},'axis':{'gridColor':'#e7eeeb'}}}, width='stretch')
    with right, st.container(border=True):
        st.subheader('下一步，为你留好余地')
        st.markdown('**01　明确需求**  \n计划金额、使用期限与风险偏好。')
        st.markdown('**02　了解匹配理由**  \n查看符合条件的产品，也看为什么排除。')
        st.markdown('**03　验证意外情况**  \n收入延迟或临时支出时，现金是否够用。')
        st.button('开始产品匹配 →', type='primary', width='stretch',
                  on_click=goto, args=(PAGES[1],))
        st.caption('4个演示产品 · 每条规则均可解释')
    with st.expander('查看演示流水与数据口径'):
        st.dataframe([{'日期':'2026-10-01','事项':'工资收入','金额（元）':18000},
                      {'日期':'2026-10-05','事项':'房租及必要支出','金额（元）':-7500},
                      {'日期':'2026-10-15','事项':'可选消费','金额（元）':-2700}], hide_index=True, width='stretch')
        st.caption('默认现金154,300元 = 期初110,000元 + 六个月收入107,500元 − 支出63,200元。修改匹配假设后，历史图仍保留原始演示样本。')


def render_matching():
    page_header('PERSONAL MATCH / 02', '找到适合你的安排', '先满足资金与风险约束，再按你的偏好排序。所有产品均为虚构示例。')
    p = Profile(**st.session_state.profile)
    with st.expander('01 · 你的资金与使用计划', expanded=True):
        a,b,c = st.columns(3)
        cash = a.number_input('可用现金（元）', min_value=0, max_value=10000000, value=p.cash//100, step=1000, key='cash_input')
        essential = b.number_input('每月必要支出（元）', min_value=0, max_value=1000000, value=p.essential//100, step=500, key='essential_input')
        obligations = c.number_input('近期其他支出（元）', min_value=0, max_value=1000000, value=p.obligations//100, step=500, key='obligations_input')
        a,b,c = st.columns(3)
        amount = a.number_input('计划金额（元）', min_value=100, max_value=10000000, value=p.amount//100, step=1000, key='amount_input')
        horizon = b.selectbox('这笔钱多久后可能用到？', (30,90,180,365), index=(30,90,180,365).index(p.horizon), format_func=lambda x:f'{x}天', key='horizon_input')
        reserve = c.slider('保留几个月必要支出？', 1,12,p.reserve_months,key='reserve_input')
        a,b,c = st.columns(3)
        tolerance = a.selectbox('风险偏好（教学等级）', (1,2,3,4,5), index=p.tolerance-1, key='tolerance_input')
        capacity = b.selectbox('风险承受能力（教学等级）', (1,2,3,4,5), index=p.capacity-1, key='capacity_input')
        objective = c.selectbox('匹配时更看重', OBJECTIVES, index=OBJECTIVES.index(p.objective), key='objective_input')
        p = Profile(cash*100, essential*100, obligations*100, reserve, amount*100, horizon,tolerance,capacity,objective)
        current_key = profile_key(p)
        if current_key != st.session_state.active_key:
            action_guard()
            st.session_state.profile = asdict(p)
            st.session_state.active_key = current_key
            st.session_state.results = []
            st.session_state.selected = None
            st.session_state.stress = None
            st.session_state.confirmed = False
            audit('profile_updated', 'ProfileForm', asdict(p), '旧匹配与确认已失效')
            persist()
        st.info(f'建议保留 {money(p.reserve)}，本次可规划上限 {money(p.available)}。储备月数是可调整的演示假设。')
        if st.button('生成匹配方案', type='primary', key='generate_match'):
            action_guard()
            st.session_state.results = match_products(p)
            audit('matching_completed', 'MatchingService', asdict(p), st.session_state.results)
            persist()
    results = st.session_state.results
    if not results:
        st.caption('提交条件后，将同时展示匹配项与排除原因。')
        return
    eligible = [r for r in results if r['eligible']]
    st.subheader(f'02 · {len(eligible)}个匹配项，理由看得见')
    if not eligible:
        st.warning('当前没有符合全部约束的产品。请核对计划金额与使用期限；不要仅为通过匹配而提高风险等级。')
    for start in range(0,len(eligible),2):
        for col, row in zip(st.columns(2), eligible[start:start+2]):
            q = row['product']
            with col, st.container(border=True):
                st.markdown(f'<span class="tag">符合当前约束 · 演示产品</span><div class="product-title">{html.escape(q["name"])}</div>', unsafe_allow_html=True)
                st.caption(q['category'])
                c1,c2,c3=st.columns(3)
                c1.metric('风险等级',f'{q["risk"]}/5')
                c2.metric('锁定期',f'{q["lock_days"]}天')
                c3.metric('起始金额',money(q['minimum']))
                st.write(q['description'])
                st.caption(f'匹配理由：风险≤{min(p.tolerance,p.capacity)}级；期限≤{p.horizon}天；分配后预留现金充足。排序偏好：{p.objective}。')
                if st.button('选择此方案', key='choose_'+q['id'],width='stretch'):
                    action_guard()
                    st.session_state.selected = q['id']
                    st.session_state.confirmed = False
                    st.session_state.stress = None
                    audit('product_selected','MatchingUI',q['id'],{'input_key':current_key})
                    persist()
    with st.expander(f'为什么排除另外{len(results)-len(eligible)}个产品？'):
        for row in results:
            if not row['eligible']:
                st.markdown(f'**{row["product"]["name"]}** — ' + '；'.join(row['reasons']))
    if st.session_state.selected:
        selected = next(p for p in PRODUCTS if p.id == st.session_state.selected)
        with st.container(border=True):
            st.subheader('03 · 核对与留存')
            st.write(f'已选择 **{selected.name}** · 计划 {money(p.amount)} · 现金分配后 {money(p.cash-p.amount)}')
            st.caption('产品来源：本文件内的SIM目录；条款版本 '+CATALOG_VERSION+'。不包含真实产品评级或收益数据。')
            st.checkbox('我了解这是模拟方案，保存不会申购或扣款。', key='confirmed')
            left,right=st.columns(2)
            if left.button('保存模拟方案',type='primary',disabled=not st.session_state.confirmed,key='save_plan',width='stretch'):
                action_guard()
                plan=make_plan(p,st.session_state.selected,st.session_state.confirmed)
                scenario=st.session_state.stress
                inputs=st.session_state.stress_inputs
                expected=(current_key,st.session_state.selected,inputs['extra'],inputs['delay'])
                if scenario and st.session_state.stress_key==expected:
                    plan.update(stress_status='tested', stress=scenario)
                existing=next((x for x in st.session_state.plans if x['plan_id']==plan['plan_id']),None)
                if existing is None:
                    st.session_state.plans.append(plan)
                    audit('plan_saved','PlanService',{'input_key':current_key},plan,approval='USER_CONFIRMED_SIMULATION')
                    persist()
                elif (existing['stress_status'],existing.get('stress')) != (plan['stress_status'],plan.get('stress')):
                    plan['created_at']=existing['created_at']
                    plan['updated_at']=utcnow().isoformat()
                    before=dict(existing)
                    existing.clear()
                    existing.update(plan)
                    audit('plan_updated','PlanService',{'previous':before},plan,approval='USER_CONFIRMED_SIMULATION')
                    persist()
                st.success('方案已留存，资金余额没有变化。可在“方案与活动”下载。')
            right.button('先做情景验证 →', on_click=goto,args=(PAGES[2],),width='stretch')


def render_stress():
    page_header('SCENARIO LAB / 03','意外发生时，现金还够吗？','把临时支出和收入延迟加入同一份方案，观察现金缓冲。')
    if not st.session_state.selected:
        st.info('请先在产品匹配中选择一个方案。')
        st.button('前往产品匹配', on_click=goto,args=(PAGES[1],))
        return
    p=Profile(**st.session_state.profile)
    product=next(x for x in PRODUCTS if x.id==st.session_state.selected)
    st.write(f'当前方案：**{product.name}** · {money(p.amount)}')
    a,b=st.columns(2)
    saved_inputs=st.session_state.stress_inputs
    extra=a.slider('额外临时支出（元）',0,200000,saved_inputs['extra'],step=1000,key='extra_stress')
    delay=b.slider('预期收入延迟带来的额外缓冲需求（元）',0,100000,saved_inputs['delay'],step=1000,key='delay_stress')
    new_inputs={'extra':extra,'delay':delay}
    args=(profile_key(p),product.id,extra,delay)
    if new_inputs!=saved_inputs:
        action_guard()
        st.session_state.stress_inputs=new_inputs
        st.session_state.stress=None
        st.session_state.stress_key=None
        audit('scenario_inputs_updated','ScenarioUI',saved_inputs,new_inputs)
        persist()
    elif st.session_state.stress is not None and st.session_state.stress_key!=args:
        action_guard()
        st.session_state.stress=None
        st.session_state.stress_key=None
        audit('scenario_invalidated','ScenarioUI',{'current_key':args},'条件变化，旧情景结果已失效')
        persist()
    if st.button('运行情景验证',type='primary',key='run_stress'):
        action_guard()
        st.session_state.stress=stress_test(p,product.id,extra*100,delay*100)
        st.session_state.stress_key=args
        audit('scenario_tested','ScenarioService',{'extra':extra*100,'delay':delay*100},st.session_state.stress)
        persist()
    result=st.session_state.stress
    if result:
        a,b,c=st.columns(3)
        a.metric('可及时动用的现金',money(result['accessible_after']))
        b.metric('情景下需要的现金',money(result['required']))
        c.metric('资金缺口',money(result['gap']))
        if result['passed']:
            st.success('在本次假设下，现金缓冲足以覆盖需求。')
        else:
            st.warning('该情景出现资金缺口。可减少计划金额或重新考虑锁定期限，再生成方案。')
        st.caption(result['assumption']+' 未模拟市场价格、费用、税收、赎回延迟或违约。')
    st.button('返回调整方案',on_click=goto,args=(PAGES[1],))


def render_activity():
    page_header('SAVED & TRACEABLE / 04','方案与活动','保留选择依据，让每一次调整都可回看。')
    if not st.session_state.plans:
        st.info('还没有保存方案。完成产品匹配后，可将模拟方案留存在这里。')
    for plan in reversed(st.session_state.plans):
        with st.container(border=True):
            st.subheader(plan['product']['name'])
            stale=plan['input_key']!=profile_key(Profile(**st.session_state.profile))
            st.caption(plan['plan_id']+' · '+('历史条件快照，当前输入已变化' if stale else '与当前条件一致'))
            st.write(f'计划金额 **{money(plan["amount"])}** · 仅保存方案 · 未扣款')
            st.download_button('下载方案 JSON',json.dumps(plan,ensure_ascii=False,indent=2),
                               file_name=plan['plan_id']+'.json',mime='application/json',key='download_'+plan['plan_id'])
    st.subheader('操作记录')
    st.dataframe([{'时间（UTC）':e['timestamp'],'动作':e['intent'],'结果':e['approval']}
                  for e in reversed(st.session_state.events)],hide_index=True,width='stretch')
    st.download_button('下载完整会话与日志 Markdown',context_markdown(st.session_state),
                       file_name='banking_session.md',mime='text/markdown',key='download_context')


@st.fragment(run_every=5)
def quota_status():
    active=check_session_quota()
    snapshot=st.session_state.quota
    if snapshot:
        label='模拟额度' if snapshot['scope']=='demo' else 'Codex 五小时额度'
        st.caption(f'{label} · 剩余 {snapshot["remaining_percent"]:g}%')
    if not active:
        st.rerun()


def main():
    st.set_page_config(page_title='Banking Agent · 财务空间',page_icon='◈',layout='wide')
    st.markdown(CSS,unsafe_allow_html=True)
    init_state()
    active=check_session_quota()
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">◈ Banking Agent</div>',unsafe_allow_html=True)
        st.caption('你的个人财务空间')
        st.divider()
        st.radio('工作空间',PAGES,key='page',disabled=not active)
        st.divider()
        st.caption('SIM-USER-01 · 本地演示\n\n所有产品、账户和流水均为合成数据。')
        if active:
            quota_status()
            if st.button('暂停并保存当前工作',width='stretch',key='pause'):
                st.session_state.halted=True
                st.session_state.halt_reason='user_pause'
                audit('session_paused','UI',{},'封存当前工作',approval='USER_PAUSED')
                persist()
                st.rerun()
    if st.session_state.halted:
        st.title('当前工作已暂停')
        st.warning('原因：'+str(st.session_state.halt_reason))
        st.write('不再启动匹配、情景计算或保存新方案。已有成果与完整日志仍可下载。')
        st.download_button('下载中断成果与接续上下文',context_markdown(st.session_state),
                           file_name='interrupted_dashboard.md',mime='text/markdown')
    else:
        {PAGES[0]:render_overview,PAGES[1]:render_matching,PAGES[2]:render_stress,PAGES[3]:render_activity}[st.session_state.page]()
    if st.session_state.save_error:
        st.error('本地自动保存未完成：'+st.session_state.save_error+'。请立即下载当前成果。')
        st.download_button('下载备份',context_markdown(st.session_state),file_name='backup_dashboard.md',mime='text/markdown')
    st.caption('BANKING AGENT / 设计原型 v1.2 · 规则匹配与压力演示 · 无真实申购功能')


if __name__=='__main__':
    main()
