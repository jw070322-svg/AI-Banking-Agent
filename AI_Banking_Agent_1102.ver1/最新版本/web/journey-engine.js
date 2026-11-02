(function (global) {
'use strict';
const copy=x=>JSON.parse(JSON.stringify(x));
const DAY=86400000;
const catalog=[
 {id:'FLEX',name:'现金管理类理财',type:'现金管理 · 演示',risk:1,term:0,min:10000,liquidity:'无最低持有期；申请赎回后下一模拟日到账',redemption:'next_day',projection:{annual_return:.018,annual_volatility:.003},description:'模拟银行常见现金管理类产品，主要配置现金、存款及短期限债券。流动性较高，仍存在净值波动与流动性风险。'},
 {id:'TERM3',name:'90天持有期纯固收理财',type:'纯固定收益 · 演示',risk:2,term:3,min:100000,liquidity:'最低持有 90 个模拟日；之后可申请赎回，次日到账',redemption:'maturity',projection:{annual_return:.028,annual_volatility:.012},description:'模拟以债券、存款等债权资产为主的纯固收产品，不配置股票。存在利率与信用风险，净值可能下跌。'},
 {id:'TERM6',name:'180天持有期固收理财',type:'固定收益 · 演示',risk:2,term:6,min:100000,liquidity:'最低持有 180 个模拟日；之后可申请赎回，次日到账',redemption:'maturity',projection:{annual_return:.031,annual_volatility:.025},description:'模拟中期持有的固定收益类理财，债权类资产占比不低于 80%。最低持有期内不能赎回，需留足近期用款。'},
 {id:'TERM12',name:'12个月封闭式固收理财',type:'封闭式固定收益 · 演示',risk:2,term:12,min:500000,liquidity:'封闭 12 个模拟月（360 日）；期满申请赎回，次日到账',redemption:'maturity',projection:{annual_return:.034,annual_volatility:.03},description:'模拟封闭式固定收益类理财，适用于较长期限的资金。演示按每月 30 日折算；实际封闭期和清算规则应以说明书为准。'},
 {id:'BALANCED',name:'90天持有期固收增强理财',type:'固收增强 · 演示',risk:3,term:3,min:100000,liquidity:'最低持有 90 个模拟日；之后可申请赎回，次日到账',redemption:'maturity',projection:{annual_return:.04,annual_volatility:.10},description:'模拟以固定收益为底仓、少量权益等增强收益的产品。波动及亏损风险较高，需满足 R3 风险条件。'}
].map(p=>({...p,fee:'演示假设：收益率为扣费后输入，申赎费为 0；真实费率未接入',source:'银行常见理财类别演示目录 v3；非在售产品报价',updated:'2026-10-26',yield:null}));
const subs=[{id:'video',name:'映像会员',amount:9600,note:'近 30 天无使用记录，仅为待核实线索',usage:'模拟使用记录：0 次',status:'active',reviewed:false},{id:'cloud',name:'云端空间',amount:2800,note:'近期持续使用，先核对空间需求',usage:'模拟使用记录：12 次',status:'active',reviewed:false},{id:'music',name:'音乐会员',amount:4500,note:'可能与家庭套餐重叠，请自行判断',usage:'模拟使用记录：3 次',status:'active',reviewed:false}];
function makeTransactions(){let rows=[];for(const month of ['2026-10','2026-09']){const oct=month==='2026-10';const r=[['15','薪资入账','income',oct?2850000:2700000],['05','月度房租','housing',-600000],['10','餐饮汇总样本','dining',oct?-340000:-420000],['12','生活购物汇总样本','shopping',oct?-180000:-220000],['16','交通汇总样本','transport',oct?-100000:-140000],['18','其他支出汇总样本','other',oct?-49100:-23100],['03','映像会员','subscription',-9600],['03','云端空间','subscription',-2800],['03','音乐会员','subscription',-4500]];r.forEach((x,i)=>rows.push({id:month+'-'+i,date:month+'-'+x[0],name:x[1],category:x[2],amount:x[3],status:'booked',source:'本地账单样本 v2',note:'已记账的虚构记录。标为汇总的条目不代表单笔真实交易。'}));}return rows;}
function createSession(saved,options={}){
 const initialDay=Date.parse('2026-10-19T04:00:00Z');
 const state=saved?copy(saved):{day:initialDay,available:3864000,goal:{total:3864000,need:3000000,emergency:500000,months:6},budget:1286000,profile:'valid',consent:{read:false,subscriptions:false,trade:false},version:1,selected:'FLEX',amount:364000,active:true,locked:false,failures:0,operations:[],events:[],subscriptions:copy(subs),positions:[{id:'POS-SEED',productId:'FLEX',amount:9000000,reserved:0,openedAt:initialDay-30*DAY,maturesAt:initialDay-30*DAY,source:'期初模拟储蓄持仓'}],transactions:makeTransactions(),planSaved:false};
 state.initialTotal=state.initialTotal??12864000;state.externalOut=state.externalOut??0;state.externalIn=state.externalIn??0;
 state.simulation={monthly_income_minor:2850000,monthly_expense_minor:1286000,salary_day:15,expense_day:5,annual_return:.02,annual_volatility:.08,...(state.simulation||{})};state.valuation_events=state.valuation_events||[];state.event_reservations=state.event_reservations||{};
 state.consent.transfer=!!state.consent.trade;state.consent.cards=state.consent.cards??false;
 state.contacts=state.contacts||[{id:'R-WANG',name:'小王',phone:'13800000001',note:'同学 · 虚构联系人'},{id:'R-LIN',name:'林晓',phone:'13800000002',note:'家人 · 虚构联系人'},{id:'R-CHEN',name:'陈晨',phone:'13800000003',note:'朋友 · 虚构联系人'}];
 state.cards=state.cards||[{id:'CARD-DEBIT',name:'日常借记卡',last4:'1024',kind:'debit',status:'active',limit:1000000,spent:0,spentDay:state.day,version:1},{id:'CARD-CREDIT',name:'生活信用卡',last4:'2088',kind:'credit',status:'active',limit:2000000,spent:0,spentDay:state.day,version:1}];
 if(!options.preserveVerification)state.operations.forEach(o=>{if(o.status==='awaiting_confirmation')o.verified=false;});
 let serial=Math.max(0,...[...state.operations,...state.events,...state.positions,...state.cards].map(x=>Number((String(x.id).match(/(\d+)$/)||[])[1])||0));
 assertState();
 function event(tool,status,detail,opId=null){state.events.push({id:'EV-'+(++serial),time:new Date(state.day).toISOString(),observedAt:new Date().toISOString(),tool,status,detail,version:state.version,opId});}
 function amount(n,min=0){if(!Number.isSafeInteger(n)||n<min||n>1000000000)throw Error('金额需为有效整数分，且不能为负。');}
 function total(){return state.available+state.positions.reduce((sum,p)=>sum+p.amount,0);}
 function eventReserved(){return Object.values(state.event_reservations).filter(x=>x.status==='reserved').reduce((n,x)=>n+x.amount_minor,0);}
 function capacity(){return Math.max(0,Math.min(state.goal.total,state.available)-state.goal.need-state.goal.emergency-eventReserved());}
 function monthlySaved(){return state.subscriptions.filter(x=>x.status==='cancelled').reduce((a,x)=>a+x.amount,0);}
 function assertState(){if(!Number.isSafeInteger(state.available)||!Number.isSafeInteger(state.initialTotal)||!Number.isSafeInteger(state.externalOut)||state.externalOut<0||state.cards.some(c=>!Number.isSafeInteger(c.limit)||c.limit<10000||c.limit>5000000||!Number.isSafeInteger(c.spent)||c.spent<0||!['active','locked','lost'].includes(c.status)))throw Error('模拟快照数据无效，已停止操作。');if(state.available<0||state.positions.some(p=>p.amount<0||p.reserved<0||p.reserved>p.amount)||total()+state.externalOut!==state.initialTotal+state.externalIn)throw Error('账本不一致，操作已停止。');}
 function invalidate(reason){state.operations.filter(o=>o.status==='awaiting_confirmation').forEach(o=>{o.status='invalidated';event('proposal.invalidate','invalidated',reason,o.id);});state.version++;}
 function scope(name){if(state.consentExpiresAt&&Date.now()>=state.consentExpiresAt)throw Error('本地演示授权已过期，请重新授权。');if(!state.consent[name])throw Error('需要开启对应演示权限。请进入右上角「授权中心」补齐。');}
 function mutable(name){if(!state.active)throw Error('任务已中断，请在「任务与记录」恢复后再操作。');if(state.locked)throw Error('连续失败触发安全锁定，请在授权中心核实并重置执行锁；已完成操作不会清除。');scope(name);if(state.operations.some(o=>o.status==='unknown'))throw Error('有结果待核实的操作。请在「任务与记录」查询回执，不能重复执行。');}
 function product(id){const p=catalog.find(p=>p.id===id);if(!p)throw Error('产品不存在');return p;}
 function eligibility(id,configured=state.amount){const p=product(id),reasons=[],riskMismatch=p.risk>Math.min(state.personal_profile?.risk_tolerance??1,state.personal_profile?.risk_capacity??1);if(state.profile==='missing')reasons.push('风险档案缺失');if(state.profile==='expired')reasons.push('风险档案已过期');if(riskMismatch)reasons.push('高于当前风险档案上限');if(p.term*30+1>state.goal.months*30)reasons.push('锁定期加次日结算超过目标用款时间');if(configured<p.min)reasons.push('配置金额低于起点 ¥'+p.min/100);if(configured>capacity())reasons.push('超过扣除必要用款与应急金后的可配置资金');if(p.redemption==='unsupported')reasons.push('费用及赎回资料不完整');return{eligible:!reasons.length,reasons,kind:riskMismatch?'不匹配':reasons.length?'受限':'匹配'};}
 function configure(g){amount(g.total,10000);amount(g.need);amount(g.emergency);if(g.total>state.available)throw Error('规划总额不能超过当前可用资金。');if(g.need+g.emergency>g.total)throw Error('必要用款与应急金之和不能超过规划总额。');if(!Number.isInteger(g.months)||g.months<1||g.months>36)throw Error('用款期限必须为 1–36 个整月。');invalidate('目标修改，旧确认和校验失效');state.goal=copy(g);state.amount=Math.min(state.amount,capacity());state.planSaved=false;event('goal.update','success',`规划总额 ${g.total} 分，必要用款 ${g.need} 分，应急金 ${g.emergency} 分，${g.months} 个月。`);}
 function select(id,n){product(id);amount(n);if(n>capacity())throw Error('配置金额超过当前可配置上限。');invalidate('产品或配置金额修改，旧确认失效');state.selected=id;state.amount=n;state.planSaved=false;event('allocation.update','success',`选择 ${id}，配置 ${n} 分；不触发申购。`);}
 function authorize(scopes){if(!['read','subscriptions','trade'].every(k=>typeof scopes[k]==='boolean'))throw Error('无效权限');invalidate('授权范围变化，旧确认失效');state.consent={...copy(scopes),transfer:scopes.trade,cards:!!scopes.cards};state.consentExpiresAt=Date.now()+24*60*60*1000;event('consent.update','success',`本地模拟权限（24 小时有效）：查询 ${scopes.read}，订阅 ${scopes.subscriptions}，交易 ${scopes.trade}；每项写操作仍需具体确认。`);}
 function setProfile(value){if(!['valid','expired','missing'].includes(value))throw Error('无效测试档案');invalidate('风险档案版本变化');state.profile=value;event('profile.fixture','success','切换本地风险档案测试样本：'+value+'；不是用户自报风险测评。');}
 function analyze(month){scope('read');const rows=state.transactions.filter(t=>t.date.startsWith(month)&&t.status==='booked');if(!rows.length)throw Error('当前月份没有数据');event('transactions.analyze','success',month+' 本地已记账数据完成分类汇总；未改变余额。');return summary(month);}
 function summary(month=new Date(state.day).toISOString().slice(0,7)){const tx=state.transactions.filter(t=>t.date.startsWith(month)&&t.status==='booked'),income=tx.filter(x=>x.amount>0).reduce((a,x)=>a+x.amount,0),expense=tx.filter(x=>x.amount<0).reduce((a,x)=>a-x.amount,0);return{income,expense,net:income-expense,categories:tx.filter(x=>x.amount<0).reduce((a,x)=>(a[x.category]=(a[x.category]||0)-x.amount,a),{})};}
 function reviewSubscription(id){scope('read');const x=state.subscriptions.find(x=>x.id===id);if(!x)throw Error('订阅不存在');x.reviewed=true;event('subscription.inspect','success',x.name+' 使用和周期扣费已核实（本地样本）。');}
 function keep(id){scope('read');const x=state.subscriptions.find(x=>x.id===id);if(!x||x.status==='cancelled')throw Error('该订阅已取消，不可直接恢复');x.reviewed=true;event('subscription.keep','success','用户保留 '+x.name+'；未发送取消请求。');}
 function budget(n){amount(n,10000);invalidate('预算假设修改');state.budget=n;event('budget.update','success','月度支出预算更新为 '+n+' 分；不改动历史账单和当前余额。');}
 function propose(type,id,n,options={}){let target,name,value,level='red',permission='trade';if(type==='subscription'){permission='subscriptions';mutable(permission);const x=state.subscriptions.find(x=>x.id===id);if(!x||x.status!=='active')throw Error('订阅不是生效状态，不能重复取消。');if(!x.reviewed)throw Error('请先查看周期扣费详情并核实，再取消。');target=id;name=x.name;value=x.amount;level='yellow';}else if(type==='purchase'){mutable(permission);const e=eligibility(state.selected);if(!e.eligible)throw Error(e.reasons.join('；'));target=state.selected;value=state.amount;name=product(target).name;}else if(type==='redeem'){mutable(permission);const pos=state.positions.find(x=>x.id===id);if(!pos)throw Error('持仓不存在');const p=product(pos.productId);amount(n,1);if(n>pos.amount-pos.reserved)throw Error('赎回金额超过未占用持仓。');if(state.day<pos.maturesAt)throw Error('样本尚未到期，不支持提前赎回。');target=id;value=n;name=p.name;}else if(type==='transfer'){permission='trade';mutable(permission);amount(n,1);const c=state.contacts.find(c=>c.id===id);if(!c)throw Error('请选择名册中的虚构收款人');checkTransfer(n,options.cardId||'CARD-DEBIT');target=c.id;name='转给 '+c.name;value=n;level=transferDaily()+n<=100000?'yellow':'red';
 }else if(['card_limit','card_lock','card_unlock','card_loss','card_apply'].includes(type)){permission='cards';mutable(permission);target=type==='card_apply'?'NEW-CARD':id;const c=state.cards.find(c=>c.id===id);if(type!=='card_apply'&&!c)throw Error('银行卡不存在');value=0;if(type==='card_limit'){amount(n,10000);if(n>5000000)throw Error('模拟额度上限为 50000 元');if(c.status!=='active')throw Error('请先恢复卡片交易状态');if(n<cardSpent(c))throw Error('新额度不能低于当日已用额度');value=n;}if(type==='card_lock'&&c.status!=='active')throw Error('仅正常卡片可限制交易');if(type==='card_unlock'&&c.status!=='locked')throw Error('仅交易受限卡片可解锁；挂失不可解锁');if(type==='card_loss'&&c.status==='lost')throw Error('卡片已挂失');name=type==='card_apply'?'申请模拟借记卡':({card_limit:'调整额度',card_lock:'限制交易',card_unlock:'恢复交易',card_loss:'挂失卡片'}[type]+' · '+c.name+' '+c.last4);
 }else throw Error('不支持的操作');if(state.operations.some(x=>x.status==='awaiting_confirmation'))throw Error('已有待确认操作，请先处理或取消。');const op={id:'OP-'+(++serial),type,target,name,amount:value,level,permission,version:state.version,status:'awaiting_confirmation',verified:false,createdAt:new Date(state.day).toISOString(),expiresAt:Math.floor(Date.now()/1000)+300,notes:'本地虚构业务，不调用银行',cardId:type==='transfer'?(options.cardId||'CARD-DEBIT'):null,cardSnapshot:type.startsWith('card_')&&type!=='card_apply'?copy(state.cards.find(c=>c.id===target)):null,snapshot:{available:state.available,goal:copy(state.goal),profile:state.profile,scope:copy(state.consent),catalog:'本地虚构产品目录 v2',product:type==='purchase'?copy(product(target)):type==='redeem'?copy(product(state.positions.find(p=>p.id===target).productId)):null},dependencies:type==='subscription'?['查询权限','周期扣费核实','取消权限','明确确认']:type.startsWith('card_')?['卡管理权限',type==='card_apply'?'模拟申请条件':'卡片状态与额度规则','明确确认','模拟验证']:type==='transfer'?['交易权限','虚构收款人核验','付款卡状态、余额与累计限额','明确确认',level==='red'?'模拟验证':'无需强验证']:['交易权限',type==='purchase'?'资金与适配规则':'到期与可赎回金额','明确确认','模拟验证']};state.operations.push(op);event('policy.check','awaiting_confirmation',`${type}；金额 ${value} 分；${level==='red'?'需要模拟验证':'需要明确确认'}；绑定 V${state.version}`,op.id);return copy(op);}
 function cancel(id){const o=state.operations.find(o=>o.id===id);if(!o||o.status!=='awaiting_confirmation')return;o.status='cancelled';o.verified=false;event('proposal.cancel','cancelled','用户关闭或返回调整，未执行资金操作。',id);}
 function fail(o,detail){state.failures++;if(state.failures>=3){state.locked=true;invalidate('连续失败安全锁定');event('policy.lock','blocked','连续三次失败或验证错误，执行锁定。');}event('operation.error','failed',detail,o&&o.id);}
 function checkPreview(o){if(!Number.isInteger(o.expiresAt)||Math.floor(Date.now()/1000)>=o.expiresAt){o.status='invalidated';o.verified=false;event('proposal.expire','invalidated','预览超过300秒，请重新生成。',o.id);throw Error('预览已过期，请重新发起。');}}
 function verify(id,code){const o=state.operations.find(o=>o.id===id);if(!o||o.status!=='awaiting_confirmation'||o.version!==state.version)throw Error('确认已失效，请重新生成方案。');mutable(o.permission);checkPreview(o);if(o.level!=='red')throw Error('该操作不需要强验证');if(code!=='246810'){fail(o,'本地演示校验码错误，未调用执行工具');throw Error('演示校验码不正确。');}o.verified=true;o.assertionExpiresAt=Math.floor(Date.now()/1000)+120;event('verification.demo','success','演示码验证通过；不是真实短信、人脸或生产 MFA。',id);}
 function transferDaily(){const day=new Date(state.day).toISOString().slice(0,10);return state.transactions.filter(t=>t.category==='transfer'&&t.date===day).reduce((sum,t)=>sum-t.amount,0);}
 function cardSpent(c){return c.spentDay===state.day?c.spent:0;}
 function checkTransfer(n,cardId){const c=state.cards.find(c=>c.id===cardId);if(!c||c.kind!=='debit'||c.status!=='active')throw Error('付款借记卡已限制交易或挂失，不能转账');if(n>state.available)throw Error('可用余额不足');if(cardSpent(c)+n>c.limit)throw Error('超过付款卡当日剩余交易限额');}
 function apply(o){if(o.applied)return;
 if(o.type==='transfer'){checkTransfer(o.amount,o.cardId);const c=state.cards.find(c=>c.id===o.cardId);state.available-=o.amount;state.externalOut+=o.amount;c.spent=cardSpent(c)+o.amount;c.spentDay=state.day;state.amount=Math.min(state.amount,capacity());state.transactions.push({id:'TX-'+o.id,date:new Date(state.day).toISOString().slice(0,10),name:o.name,category:'transfer',amount:-o.amount,status:'booked',source:'前端模拟转账 / '+o.id,note:'转出至账本外的虚构联系人；未调用银行。'});o.status='succeeded';
 }else if(o.type==='card_apply'){o.status='processing';o.reviewAfter=state.day+DAY;
 }else if(o.type.startsWith('card_')){const c=state.cards.find(c=>c.id===o.target);if(!c)throw Error('银行卡不存在');if(o.type==='card_limit'){if(c.status!=='active'||o.amount<cardSpent(c))throw Error('卡片状态或当日用额发生变化');c.limit=o.amount;}else if(o.type==='card_lock'){if(c.status!=='active')throw Error('卡片状态已变化');c.status='locked';}else if(o.type==='card_unlock'){if(c.status!=='locked')throw Error('挂失卡不可通过解锁恢复');c.status='active';}else if(o.type==='card_loss'){if(c.status==='lost')throw Error('已挂失');c.status='lost';}c.version++;o.status='succeeded';
 }else if(o.type==='subscription'){const x=state.subscriptions.find(x=>x.id===o.target);x.status='cancelled';o.status='succeeded';}else if(o.type==='purchase'){if(o.amount>state.available)throw Error('余额不足');state.available-=o.amount;const p=product(o.target);state.positions.push({id:'POS-'+o.id,productId:o.target,amount:o.amount,reserved:0,openedAt:state.day,maturesAt:state.day+p.term*30*DAY,source:o.id});o.status='succeeded';}else{const pos=state.positions.find(x=>x.id===o.target);if(!pos||o.amount>pos.amount-pos.reserved)throw Error('持仓可赎回金额不足');pos.reserved+=o.amount;o.status='processing';o.settlesAt=state.day+DAY;}o.applied=true;state.failures=0;invalidate('已确认业务状态变化');assertState();}
 function execute(id,mode){const o=state.operations.find(o=>o.id===id);if(!o||o.status!=='awaiting_confirmation'||o.version!==state.version)throw Error('操作已经提交、取消或失效，不能重复执行。');mutable(o.permission);checkPreview(o);if(o.level==='red'&&(!o.verified||!Number.isInteger(o.assertionExpiresAt)||Math.floor(Date.now()/1000)>=o.assertionExpiresAt))throw Error('请先完成本地演示验证。');if(!['success','failed','unknown'].includes(mode))throw Error('无效测试结果');if(o.type==='transfer'){checkTransfer(o.amount,o.cardId);if(transferDaily()+o.amount>100000&&o.level!=='red')throw Error('累计等级变化，请重新生成预览。');}if(o.type==='purchase'){const e=eligibility(o.target,o.amount);if(!e.eligible)throw Error(e.reasons.join('；'));}o.submittedAt=new Date(state.day).toISOString();o.verified=false;if(mode==='failed'){o.status='failed';fail(o,'模拟工具明确失败，账本未变。');}else if(mode==='unknown'){o.status='unknown';event(o.type+'.submit','unknown','结果未知；未改动已确认账本，阻止重复执行。',id);}else{apply(o);event(o.type+'.submit',o.status,o.type==='redeem'?'赎回申请已受理，仍持有本金；下一个模拟日处理到账。':'模拟工具确认完成，账本已同步。',id);}assertState();return copy(o);}
 function reconcile(id,result){scope('read');const o=state.operations.find(o=>o.id===id);if(!o||o.status!=='unknown')throw Error('该操作没有待核实结果');if(!['pending','success','failed'].includes(result))throw Error('无效回执');if(result==='success'){apply(o);}else if(result==='failed'){o.status='failed';fail(o,'权威模拟记录确认失败，未执行。');}event('receipts.query',result==='pending'?'unknown':o.status,'仅查询本地模拟记录，不重发原操作。',id);assertState();}
 function settle(id,result){scope('read');const o=state.operations.find(o=>o.id===id);if(!o||o.type!=='redeem'||o.status!=='processing')throw Error('该申请不是待到账状态');if(state.day<o.settlesAt)throw Error('尚未到下一个模拟日。请在测试设置推进模拟时钟后查询。');if(!['success','failed'].includes(result))throw Error('无效到账结果');const pos=state.positions.find(p=>p.id===o.target);pos.reserved-=o.amount;if(result==='success'){pos.amount-=o.amount;state.available+=o.amount;o.status='succeeded';o.settledAt=new Date(state.day).toISOString();}else o.status='failed';invalidate('赎回到账结果已确认');event('redemption.settle',o.status,result==='success'?'模拟本金已到账，可用资金增加，持仓减少，总资产不变。':'模拟到账失败，占用已释放，持仓未扣减。',id);assertState();}
 function settleCard(id,result){scope('read');const o=state.operations.find(o=>o.id===id);if(!o||o.type!=='card_apply'||o.status!=='processing')throw Error('卡申请不在待审核状态');if(state.day<o.reviewAfter)throw Error('请推进到下一个模拟日后再查询审核');if(!['success','failed'].includes(result))throw Error('无效模拟结果');if(result==='success'){const n=++serial;state.cards.push({id:'CARD-'+n,name:'新申请借记卡',last4:String(n).padStart(4,'0').slice(-4),kind:'debit',status:'active',limit:500000,spent:0,spentDay:state.day,version:1});o.status='succeeded';}else o.status='failed';invalidate('模拟开卡审核已返回');event('card.application.review',o.status,'仅模拟审核结果；开卡不增加资金或授信，不是真实开户。',id);assertState();}
 function configureSimulation(settings){
  const keys=['monthly_income_minor','monthly_expense_minor','salary_day','expense_day','annual_return','annual_volatility'];
  if(!settings||Object.keys(settings).some(k=>!keys.includes(k)))throw Error('模拟参数无效');
  const next={...state.simulation,...settings};amount(next.monthly_income_minor);amount(next.monthly_expense_minor);
  for(const k of ['salary_day','expense_day'])if(!Number.isInteger(next[k])||next[k]<1||next[k]>28)throw Error('入账日与支出日须为1–28');
  if(!Number.isFinite(next.annual_return)||next.annual_return<0||next.annual_return>.3||!Number.isFinite(next.annual_volatility)||next.annual_volatility<0||next.annual_volatility>1)throw Error('模拟持仓年收益参数须为0–30%，波动须为0–100%；负收益压力可在预演中设置');
  invalidate('个人收支参数改变');state.simulation=next;state.budget=next.monthly_expense_minor;event('simulation.configure','success','未来工资、支出与收益假设已保存，不改历史流水。');return copy(next);
 }
 function advance(days){
  if(![1,7,30,90,180,360].includes(days))throw Error('请选择允许的模拟时长');
  if(state.operations.some(o=>o.status==='unknown'))throw Error('请先核对结果未知的操作');
  invalidate('模拟日期改变，旧确认失效');const settings=state.simulation;let salary=0,expense=0,gain=0;
  for(let n=0;n<days;n++){
   state.day+=DAY;const dt=new Date(state.day),date=dt.toISOString().slice(0,10),dom=dt.getUTCDate();
   const post=(kind,value,name)=>{const id='SIM-'+date+'-'+kind;if(state.transactions.some(t=>t.id===id))return;const insufficient=value<0&&-value>state.available;
    state.transactions.push({id,date,name,category:kind,amount:value,status:insufficient?'failed':'booked',source:'已配置的模拟周期收支',note:insufficient?'余额不足，未扣款':'按日历日生成，非真实银行流水'});
    if(insufficient){event('simulation.shortfall','blocked','计划支出余额不足，未扣款');return;}
    state.available+=value;if(value>0){state.externalIn+=value;salary+=value;}else{state.externalOut-=value;expense-=value;}
   };
   if(dom===settings.salary_day)post('income',settings.monthly_income_minor,'模拟工资入账');
   if(dom===settings.expense_day)post('other',-Math.max(0,settings.monthly_expense_minor-monthlySaved()),'模拟月度支出（含生效订阅）');
   let daily=0;for(const pos of state.positions){const exact=pos.amount*(Math.pow(1+settings.annual_return,1/365)-1)+(pos.interestCarry||0);const delta=Math.floor(exact+1e-9);pos.interestCarry=exact-delta;pos.amount+=delta;daily+=delta;}
   if(daily){state.externalIn+=daily;gain+=daily;state.valuation_events.push({id:'NAV-'+date,date,amount_minor:daily,source:'假设收益按日复利；计入持仓市值，赎回后才变为现金'});}
   assertState();
  }
  state.amount=Math.min(state.amount,capacity());event('clock.advance','success',`已逐日推进 ${days} 天：工资 ${salary} 分、支出 ${expense} 分、持仓估值收益 ${gain} 分。`);
  return {days,salary_minor:salary,expense_minor:expense,investment_income_minor:gain,available_minor:state.available};
 }
 function pause(){invalidate('任务中断，取消待执行确认');state.active=false;event('task.pause','paused','中断后续执行，已完成业务不回滚。');}
 function resume(){if(state.locked)throw Error('请先核实执行锁');state.active=true;event('task.resume','success','恢复后续任务，需重新确认写操作。');}
 function unlock(){if(state.operations.some(o=>o.status==='unknown'))throw Error('请先核实未知回执');state.locked=false;state.failures=0;invalidate('用户核实后重置本地执行锁');event('policy.unlock','success','演示执行锁已重置，不改变资金和历史记录。');}
 function liquid(){invalidate('用户选择保持流动性');state.selected='NONE';state.amount=0;state.planSaved=true;event('plan.liquidity','succeeded','仅保存保留流动性的计划，不申购、不改变账本。');}
 function projection({amount:configured=state.amount,productId=state.selected,income=state.simulation.monthly_income_minor,expense=state.budget,annualReturn,annualVolatility,frequency='monthly'}={}){
  amount(configured);amount(income);amount(expense);if(configured>capacity())throw Error('预演金额超过扣除事件预留后的可配置资金');
  const p=productId==='NONE'?null:product(productId),rows=[],principal=p?configured:0;
  annualReturn=annualReturn??p?.projection.annual_return??0;annualVolatility=annualVolatility??p?.projection.annual_volatility??0;
  if(!Number.isFinite(annualReturn)||annualReturn<=-1||annualReturn>1||!Number.isFinite(annualVolatility)||annualVolatility<0||annualVolatility>1)throw Error('收益率须大于-100%且不超过100%，波动须为0–100%');
  if(!['monthly','daily'].includes(frequency))throw Error('预演频率须为 monthly 或 daily');
  for(let day=0;day<=state.goal.months*30;day+=frequency==='daily'?1:30){
   const m=day/30;
   const t=m/12,period=p&&p.term?Math.min(m,p.term)/12:t,value=Math.round(principal*Math.pow(1+annualReturn,period));
   const recovered=!!p&&p.term>0&&m>p.term,lock=p&&!recovered?value:0;
   const base=Math.round(state.available+(income-state.simulation.monthly_expense_minor)*m);
   const plan=Math.round(state.available+(income-expense+monthlySaved())*m-principal+(recovered?value:0));
   const reserve=state.goal.need+state.goal.emergency+eventReserved();
   const lower=Math.round(principal*Math.exp(Math.log1p(annualReturn)*period-annualVolatility*Math.sqrt(period)));
   const upper=Math.round(principal*Math.exp(Math.log1p(annualReturn)*period+annualVolatility*Math.sqrt(period)));
   rows.push({day,month:m,principal,recovered,baseline:base,planned:plan,locked:lock,required:reserve,gap:Math.max(0,reserve-plan),investment_value:value,investment_gain:value-principal,wealth:plan+lock,lower,upper,annual_return:annualReturn,annual_volatility:annualVolatility});
  }return rows;
 }
 function transferIntent(text){
  let normalized=String(text).normalize('NFKC').trim().replace(/^(?:我想要|我想|我要|我需要)\s*/,'').replace(/(?:吧|谢谢|好吗)[。!！?？]?$/,'').replace(/^(?:请帮我|麻烦帮我|请|麻烦|帮我)\s*/,'');
  normalized=normalized.replace(/汇款|打钱/g,'转账').replace(/^(给|向)([\p{Script=Han}A-Za-z·]{1,20})\s*(?:转|打)\s*(?=\d)/u,'向$2转账').replace(/^转给([\p{Script=Han}A-Za-z·]{1,20})\s*(?=\d)/u,'向$1转账').replace(/^转\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(?:元|块钱?|快)?\s*给([\p{Script=Han}A-Za-z·]{1,20})$/u,'向$2转账$1元');
  const guidance='请按模板输入：向【名册姓名】转账【数字金额】元，例如：向小王转账500元。仅填入表单，不自动执行。';
  const incomplete=message=>({route:'transfer',transfer:{status:'needs_template',recipientId:null,recipientName:'',amountMinor:null},message});
  if(/不要|先别|暂不|取消|不想|勿/.test(normalized))return incomplete('没有发起转账。否定或取消类表达不会按转账指令处理；如需转账，'+guidance);
  if(/明天|后天|下周|下个月|如果|定时|每天|每月|然后|再给|分别/.test(normalized))return incomplete(guidance+' 当前不支持定时、条件或多笔转账。');
  const match=normalized.match(/^(?:(?:请|麻烦)(?:帮我)?|帮我)?\s*(?:向|给)?\s*([\p{Script=Han}A-Za-z·]{1,20})\s*转账\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(?:元|块钱?|快)?[。!！]?$/u);
  if(!match)return incomplete(guidance+' 当前不支持一句话多笔、中文金额或复杂附加条件。');
  const recipientName=match[1],parts=match[2].split('.'),amountMinor=Number(parts[0])*100+Number((parts[1]||'').padEnd(2,'0'));
  if(!Number.isSafeInteger(amountMinor)||amountMinor<1||amountMinor>1000000000)return incomplete('金额需大于0、最多两位小数，且不超过本地演示金额范围。'+guidance);
  const contacts=state.contacts.filter(c=>c.name===recipientName);
  if(contacts.length!==1)return{route:'transfer',transfer:{status:'needs_recipient',recipientId:null,recipientName,amountMinor},message:contacts.length?'名册中有重名收款人，请手动选择并核对。金额已识别，未执行转账。':'已识别给'+recipientName+'转账'+match[2]+'元，但虚构名册中没有此人。请选择已有收款人并重新核对；不会默认换成其他人。'};
  return{route:'transfer',transfer:{status:'ready',recipientId:contacts[0].id,recipientName,amountMinor},message:'已填入：向'+recipientName+'转账'+match[2]+'元。请核对付款卡、收款人和金额，再生成确认；尚未扣款。'};
 }
 function interpret(input){
  const text=String(input??'').normalize('NFKC').trim().slice(0,500);
  event('intent.capture','received',text);
  const result=(route,tab,message,extra={})=>({route,tab,message,...extra});
  if(/忽略.*(规则|权限)|跳过.*(验证|确认)|system prompt/i.test(text))return result('tasks',null,'不能跳过权限、确认或验证。可到任务页核对记录，未执行任何操作。');
  if(/密码|验证码/.test(text))return result('permissions',null,'这里不办理密码修改或真实验证码验证。已打开授权与控制；演示验证只在具体操作确认页进行。');
  const choices=[];
  const add=(route,tab,label,query,message,extra={})=>choices.push({route,tab,label,query,message,...extra});
  const records=/回执|任务|进度|失败|结果未知|历史操作|操作记录|交易记录|转账记录|转账明细|转账.*(?:状态|结果)|取消.*转账|挂失记录|刚才.*(转|操作)|上一笔/.test(text);
  if(records)add('tasks',null,'任务与操作记录','查看任务进度和回执','已打开统一任务记录。可以查看结果、继续确认或查询未知回执；不会重发原交易。');
  const preview=/预演|预测|情景|资金缺口|资金够不够|会不会影响|是否影响/.test(text);
  if(preview)add('preview',null,'资金预演','打开资金预演','已打开资金预演。收入、预算和用款时间需核对，不承诺未来收益。');
  const transfer=/转账|汇款|打钱|转给|给.+(?:转|打)\s*\d|转\s*\d+.*给/.test(text)&&!records&&!preview;
  if(transfer){const t=transferIntent(text);add('transfer',null,'模拟转账','向小王转账500元',t.message,{transfer:t.transfer});}
  if(/挂失|额度|限额|银行卡|卡管理|卡片|卡丢|卡不见|冻结|解冻|锁卡|解锁|办卡|我的卡|几张卡|借记卡|信用卡|申请.*卡/.test(text)&&!records)add('cards',null,'银行卡管理','打开银行卡管理','已打开银行卡管理。请选择具体卡片，再核对挂失、额度或限制操作；没有自动改卡。');
  const subs=/订阅|代扣|自动扣|自动续费|续费|会员|包月|连续包|取消扣费/.test(text)||state.subscriptions.some(x=>text.includes(x.name));
  if(subs)add('spending','subscriptions','订阅与代扣','查看自动续费和订阅','已打开订阅管理。先查看扣费依据，再保留或取消；没有自动取消或退款。');
  const bills=/账单|收支|消费|支出|开销|花销|餐饮|吃饭|购物|交通|房租|收入|工资|薪资|流水|花钱|花费|钱.*花|花.*(哪里|哪了|多少)|花了多少/.test(text)&&(!subs||/账单|流水|消费分类/.test(text))&&!/预算|控制开销|支出计划/.test(text)&&!preview;
  if(bills){
   let month=new Date(state.day).toISOString().slice(0,7);const d=new Date(state.day);
   if(/上个月|上月/.test(text)){d.setUTCMonth(d.getUTCMonth()-1,1);month=d.toISOString().slice(0,7);}
   const explicit=text.match(/(?:(20\d{2})[年\/-])?(1[0-2]|0?[1-9])月/);if(explicit)month=(explicit[1]||String(d.getUTCFullYear()))+'-'+explicit[2].padStart(2,'0');
   else{const months=['一','二','三','四','五','六','七','八','九','十','十一','十二'];for(let i=11;i>=0;i--)if(text.includes(months[i]+'月')){month=d.getUTCFullYear()+'-'+String(i+1).padStart(2,'0');break;}}
   const categories=[['dining',/餐饮|吃饭/],['shopping',/购物/],['transport',/交通|出行/],['housing',/房租|住房/],['income',/收入|工资|薪资/]].filter(x=>x[1].test(text));
   add('spending','bills','账单与收支','看看这个月钱花到哪里了',(/年度|全年|今年/.test(text)?'年度报告尚未实现，当前仅提供月度样本。':'')+'已打开'+month+'账单'+(categories.length===1?'及对应分类':'')+'。没有样本时会显示空状态，可更改月份。',{filters:{month,category:categories.length===1?categories[0][0]:'all'}});
  }
  const holdings=/持仓|赎回|卖出|我买的|已买|取出.*(理财|存款)|理财.*取出/.test(text)&&!preview;
  const plan=/预算|应急|用款|目标|资金计划|存钱计划|每月存|攒钱|控制开销|支出计划|买房|买车/.test(text)&&!preview;
  if(holdings)add('wealth','holdings','持仓与赎回','查看我的持仓','已打开持仓。请选中对应持仓和赎回金额；提交赎回不代表立即到账。');
  else if(plan)add('wealth','plan','资金计划与预算','调整预算和应急金','已打开资金计划。请在表单核对目标、用款期限和必要预留，未自动修改金额。');
  else if(/理财|存款|投资|申购|基金|产品|低风险|活期|闲钱|闲置|收益|半年|三万/.test(text)&&!preview)add('wealth','products','理财产品与比较','推荐低风险理财产品','已打开产品与推荐。可筛选、比较和预演；产品是虚构样本，不保证收益。');
  if(/风险档案|风险测评|风险评估/.test(text))add('profile',null,'风险档案','查看风险档案','已打开风险档案。这里只核对模拟档案状态，不代表完成真实风险测评。');
  if(/授权|权限/.test(text))add('permissions',null,'授权与控制','查看授权范围','已打开授权中心。只展示权限，不自动开启或撤销授权。');
  if(/余额|总资产|资产总额|还有多少钱|剩下多少钱|剩多少钱|有多少钱|有多少.*资产|可用资金|账户总览/.test(text)&&!preview)add('overview',null,'账户总览','查看账户余额','已打开总览，显示当前本地账本余额与持仓。');
  if(choices.length>1)return result(null,null,'你提到了多个事项，请先选择这次要办理的一项。不会自动执行任何操作。',{choices});
  if(choices.length===1)return choices[0];
  return result(null,null,/帮助|怎么用|能做什么|支持|不知道/.test(text)?'可以查询余额、筛选账单、管理订阅、比较理财、查看持仓、管理卡片和核对任务。点击下面的示例填入，再提交。':'暂时没有确定你要办理的事项。请补充“查什么”或“做什么”，也可以点击下面的示例；不会替你猜测金额或执行操作。');
 }

 return{get state(){return copy(state)},catalog:copy(catalog),total,capacity,eventReserved,monthlySaved,eligibility,configure,configureSimulation,select,authorize,setProfile,analyze,summary,reviewSubscription,keep,budget,propose,cancel,verify,execute,reconcile,settle,settleCard,advance,pause,resume,unlock,liquid,projection,interpret};
}
const api={createSession};if(typeof module==='object'&&module.exports)module.exports=api;else global.BankCore=api;
})(typeof globalThis==='object'?globalThis:this);
