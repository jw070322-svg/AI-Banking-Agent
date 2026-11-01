"""Calendar orchestration, personalization, market research and grounded concepts."""
from copy import deepcopy
from datetime import date, timedelta, datetime, timezone
import re
from uuid import uuid4
from . import calendar_provider as calendar
from .market_data import market_status, market_context, recommend, MarketError
from . import finance_lexicon

ACTIONS={'page.open','calendar.list','calendar.save','calendar.reserve','calendar.release','calendar.google.sync','profile.update','market.status','market.recommend','market.context','recipients','audit.export'}
TERMS={
 '夏普':('夏普率衡量每承担一单位收益波动所获得的超额收益。单期公式是平均（产品收益率 − 同期无风险收益率）÷ 超额收益的样本标准差；日频近似年化再乘 √252。比如年化超额收益 6%、年化波动 12%，夏普率为 0.5。波动为零时不可计算。它依赖样本区间、费率和无风险基准，也不能完整反映极端亏损。','https://web.stanford.edu/~wfsharpe/art/sr/SR.htm'),
 '最大回撤':('最大回撤是历史净值从此前峰值下降到后续谷值的最大比例，例如从 100 降至 80，最大回撤为 20%。它表示已发生的路径风险，不是未来最大损失上限。','本地知识：净值峰谷定义'),
 '复利':('复利是收益继续参与计息。按年有效收益率 r，P 元经过 t 年的情景价值为 P×(1+r)^t。负收益也会复合累积；页面预演中的收益率是明确的假设。','本地知识：复利公式'),
 '波动率':('波动率描述收益率围绕均值的离散程度。日收益的样本标准差乘 √252 是常见年化近似，要求频率和口径一致；它不是亏损概率。','本地知识：样本标准差'),
 '净值':('单位净值表示每份基金对应的资产净值。计算可比历史总回报应使用包含分红再投资的复权净值，不能把累计净值或七日年化收益率当作可直接连乘的日净值。','本地知识：数据口径'),
 '年化收益':('年化收益将某段时期的回报折算到一年。几何年化可写为（期末价值÷期初价值）^(365/实际天数)−1；短期样本会放大偶然变化，不代表未来一年收益。','本地知识：几何年化'),
 '风险等级':('产品风险等级需要来自产品发行或销售文件，并与个人风险偏好和风险承受能力共同核对。历史低波动不能自动证明产品低风险。','本地知识：演示适配规则'),
}

def concept(text):
    normalized=text.replace('Sharpe','夏普').replace('sharpe','夏普')
    for key,(answer,source) in TERMS.items():
        if key in normalized:
            return {'status':'grounded','answer':answer,'citations':[{'title':key,'source_uri':source}],'educational':True}
    return None

def profile(state):
    return {**{'risk_tolerance':1,'risk_capacity':1},**state.get('personal_profile',{})}

def reserve_total(state):
    return sum(x['amount_minor'] for x in state.get('event_reservations',{}).values() if x['status']=='reserved')

def invalidate(service,state):
    if any(x['status']=='unknown' for x in state['operations']+state['transfer_ops']):
        from .service import Fault
        raise Fault('UNKNOWN_OPERATION','请先核对结果未知的操作，再调整资金预留或画像')
    state['version']+=1
    for op in state['operations']+state['transfer_ops']:
        if op['status']=='awaiting_confirmation': op['status']='invalidated'
    state['amount']=min(state['amount'],service.engine(state)['capacity'])

def calendar_view(state,reference=None):
    reference=reference or calendar.today();end=(date.fromisoformat(reference)+timedelta(days=6)).isoformat()
    events=sorted(state.get('calendar_events',[])+state.get('google_events',[]),key=lambda x:(x['date'],x['id']))
    reservations=state.get('event_reservations',{})
    upcoming=[{**e,'reservation':reservations.get(e['id'])} for e in events if reference<=e['date']<=end and e.get('special')]
    if state.get('google_status',{}).get('status')=='sync_failed': upcoming=[e for e in upcoming if e['source']!='google']
    return {'today':reference,'through':end,'events':events,'upcoming':upcoming,'reminders':[e for e in upcoming if e.get('reservation',{} ) is None or e.get('reservation',{}).get('status') not in ('reserved','declined')],
            'reservations':list(reservations.values()),'reserved_minor':reserve_total(state),'google':state.get('google_status',{'configured':calendar.google_configured(),'status':'not_connected','message':'尚未同步 Google 日历'})}

def dispatch(service,db,state,action,args):
    from .service import Fault, integer
    if not isinstance(args,dict): raise Fault('INVALID_ARGUMENT','参数应为对象')
    if action=='page.open' or action=='calendar.google.sync':
        events,status=calendar.fetch_google(calendar.today())
        state['google_status']=status
        if events is not None: state['google_events']=events
        view=calendar_view(state)
        if status['status']=='sync_failed':
            view['reminders']=[e for e in view['reminders'] if e['source']!='google']
        return {'calendar':view,'market':market_context(service.market_data,calendar.today()),'capacity_minor':service.engine(state)['capacity']}
    if action=='calendar.list': return calendar_view(state)
    if action=='calendar.save':
        if set(args)-{'id','title','date','special','city','kind'}: raise Fault('INVALID_ARGUMENT','日历字段不支持')
        title=args.get('title');stamp=args.get('date')
        if not isinstance(title,str) or not 1<=len(title.strip())<=120: raise Fault('INVALID_ARGUMENT','事件名称须为 1–120 字')
        try: stamp=date.fromisoformat(stamp).isoformat()
        except (TypeError,ValueError): raise Fault('INVALID_ARGUMENT','事件日期无效')
        if type(args.get('special',True)) is not bool: raise Fault('INVALID_ARGUMENT','special 必须为布尔值')
        city=args.get('city','')
        if not isinstance(city,str) or len(city)>40: raise Fault('INVALID_ARGUMENT','城市名称过长')
        events=state.setdefault('calendar_events',[])
        eid=args.get('id') or 'local:'+uuid4().hex
        if not isinstance(eid,str) or not eid.startswith('local:'): raise Fault('INVALID_ARGUMENT','只能编辑项目内日历')
        if args.get('id') and not any(e['id']==eid for e in events): raise Fault('NOT_FOUND','本会话没有此事件')
        if len(events)>=300 and not args.get('id'): raise Fault('LIMIT','最多保存 300 个本地事件')
        event={'id':eid,'title':title.strip(),'date':stamp,'special':args.get('special',True),'city':city,'source':'local','kind':str(args.get('kind','special'))[:30]}
        state['calendar_events']=[e for e in events if e['id']!=eid]+[event]
        existing=state.get('event_reservations',{}).get(eid)
        if existing: existing.update(title=event['title'],date=stamp)
        return {'event':event,'calendar':calendar_view(state)}
    if action=='calendar.reserve':
        if set(args)-{'event_id','amount_minor','decision'}: raise Fault('INVALID_ARGUMENT','预留字段不支持')
        event=next((e for e in state.get('calendar_events',[])+state.get('google_events',[]) if e['id']==args.get('event_id')),None)
        if not event: raise Fault('NOT_FOUND','本会话没有此事件')
        decision=args.get('decision','reserve')
        if decision not in ('reserve','decline'): raise Fault('INVALID_ARGUMENT','请选择预留或暂不预留')
        amount=integer(args.get('amount_minor',0),0)
        if decision=='reserve' and amount<=0: raise Fault('INVALID_ARGUMENT','预留金额须大于 0')
        reserves=state.setdefault('event_reservations',{});old=reserves.get(event['id'],{})
        capacity=service.engine(state)['capacity']+(old.get('amount_minor',0) if old.get('status')=='reserved' else 0)
        if decision=='reserve' and amount>capacity: raise Fault('INSUFFICIENT_CAPACITY','预留额超过扣除现有目标与应急金后的可配置资金，请先调整资金计划')
        reserves[event['id']]={'event_id':event['id'],'title':event['title'],'date':event['date'],'amount_minor':amount if decision=='reserve' else 0,'status':'reserved' if decision=='reserve' else 'declined'}
        invalidate(service,state)
        return {'calendar':calendar_view(state),'capacity_minor':service.engine(state)['capacity'],'ledger_modified':False,'conclusion':'资金已从可投资额度中划出。账户余额未扣款。' if decision=='reserve' else '已记录暂不预留。'}
    if action=='calendar.release':
        item=state.get('event_reservations',{}).get(args.get('event_id'))
        if not item: raise Fault('NOT_FOUND','没有对应预留记录')
        item['status']='released';invalidate(service,state)
        return {'calendar':calendar_view(state),'capacity_minor':service.engine(state)['capacity'],'ledger_modified':False}
    if action=='profile.update':
        allowed={'monthly_income_minor','monthly_expense_minor','salary_day','expense_day','annual_return','annual_volatility','risk_tolerance','risk_capacity','horizon_months','emergency_minor','upcoming_obligations_minor'}
        if not args or set(args)-allowed: raise Fault('INVALID_ARGUMENT','画像字段不支持')
        p=profile(state)
        for key in ('risk_tolerance','risk_capacity'):
            if key in args:
                if type(args[key]) is not int or not 1<=args[key]<=5: raise Fault('INVALID_ARGUMENT','风险等级须为 1–5')
                p[key]=args[key]
        for key in ('emergency_minor','upcoming_obligations_minor'):
            if key in args: integer(args[key])
        if 'horizon_months' in args and (type(args['horizon_months']) is not int or not 1<=args['horizon_months']<=36): raise Fault('INVALID_ARGUMENT','期限须为 1–36 月')
        invalidate(service,state)
        settings={k:v for k,v in args.items() if k in {'monthly_income_minor','monthly_expense_minor','salary_day','expense_day','annual_return','annual_volatility'}}
        if settings: service.engine_call(state,'configureSimulation',[settings])
        for field,target in [('horizon_months','months'),('emergency_minor','emergency'),('upcoming_obligations_minor','need')]:
            if field in args:state['goal'][target]=args[field]
        state['personal_profile']=p;state['amount']=min(state['amount'],service.engine(state)['capacity'])
        return {'profile':p,'simulation':state.get('simulation'),'goal':state['goal'],'conclusion':'个人条件已保存；未来收支、预演和产品筛选会使用这些条件。历史流水未改写。'}
    if action=='recipients':
        service.require(state,'accounts')
        return {'items':deepcopy(state['contacts']),'directory_version':state['recipient_directory_version']}
    if action=='market.status':
        result=market_status(service.market_data)
        if service.market_load_error: result['message']=service.market_load_error
        return result
    if action=='market.context': return market_context(service.market_data,calendar.today())
    if action=='market.recommend':
        service.require(state,'accounts')
        if state['profile']!='valid': raise Fault('PROFILE_REQUIRED','请先核对有效风险档案')
        if args: raise Fault('INVALID_ARGUMENT','推荐条件来自已保存画像，不能覆盖服务端资金额度')
        p=profile(state);p.update(amount_minor=service.engine(state)['capacity'],horizon_days=state['goal']['months']*30,event_reserved_minor=reserve_total(state))
        try: return recommend(service.market_data,p,calendar.today())
        except MarketError as e: raise Fault(e.code,e.message)
    if action=='audit.export':
        rows=db.execute('SELECT at,action,status,detail FROM audit WHERE sid=? ORDER BY id',(state['session_id'],)).fetchall()
        import json
        records=[]
        for at,tool,status,detail in rows:
            info=json.loads(detail)
            records.append({'user_id':state['customer_id'],'intent':info.get('intent') or tool,'tool':tool,'input':info.get('arguments',{}),'output':info.get('output',{'status':status,'error':info.get('error')}),'risk_check':info.get('risk_check',status),'approval':info.get('approval','not_required_read_or_local_configuration'),'timestamp':at})
        return {'schema_version':'1.0','records':records,'count':len(records)}
    raise Fault('NOT_FOUND','扩展接口不存在')

def answer(service,state,text):
    """Returns only for safe read-only questions; transfer parsing remains separate."""
    definition=finance_lexicon.answer(text)
    if definition:
        return {'route':'customer-result','results':[{'tool':'knowledge','result':definition}],'conclusion':definition['answer']}
    if re.search(r'美团|大众点评|百度|联网搜索|本地模型|外部\s*AI|免费\s*AI|网站连接|网站与|llama\.cpp',text,re.I):
        return {'route':'connections','conclusion':'打开网站与 AI 面板，可跳转官方页面、使用百度检索或检查本地模型。'}
    if re.search('名录|名册|收款人列表|收款人.*哪些|可以转给谁|联系人.*有谁|转账.*有哪些人',text):
        service.require(state,'accounts');items=state['contacts']
        return {'route':'customer-result','results':[{'tool':'recipients','result':{'items':items}}],'conclusion':'当前演示收款名录：'+'、'.join(x['name']+('（未准入）' if not x['whitelisted'] else '') for x in items)}
    if re.search('日历|生日|纪念日|预留资金|个性化',text): return {'route':'planning','conclusion':'请在个性化与日历中填写事件和预算。确认预留后，推荐会扣除这笔资金。'}
    if re.search('wind|量化|市场|指数|板块|宏观',text,re.I): return {'route':'market','conclusion':'打开 Wind 研究面板，导入文件并查看市场、指数和推荐依据。'}
    return None
