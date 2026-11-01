const assert=require('node:assert/strict');const {createSession}=require('../web/journey-engine.js');const cases=[];function test(name,fn){fn();cases.push(name);}function routes(inputs,route,tab){const b=createSession();for(const input of inputs){const r=b.interpret(input);assert.equal(r.route,route,input);if(tab)assert.equal(r.tab,tab,input);}}
test('转账常见同义句可提取变量',()=>{const b=createSession();for(const text of ['给林晓转300块','给林晓打300块钱','给林晓打钱300元','向林晓汇款300元','转给林晓300','转300元给林晓','请帮我给林晓转300块','我想向林晓转账300元']){const r=b.interpret(text);assert.equal(r.route,'transfer',text);assert.equal(r.transfer.recipientId,'R-LIN',text);assert.equal(r.transfer.amountMinor,30000,text);}});
test('日常账单说法进入账单页',()=>routes(['钱花哪了','看看这个月花了多少','查工资收入','查消费流水','看看交通开销','帮我看看花钱情况'],'spending','bills'));
test('续费代扣会员语句进入订阅而非账单默认页',()=>routes(['停掉自动续费','检查会员扣费','取消连续包月','查看订阅','看看代扣'],'spending','subscriptions'));
test('理财产品进入产品页，持仓赎回进入持仓页',()=>{routes(['推荐低风险理财产品','闲钱怎么安排','比较活期存款','我想买基金'],'wealth','products');routes(['查看我的持仓','我买的理财在哪','想赎回1000元','取出理财'],'wealth','holdings');});
test('预算目标进入资金计划',()=>routes(['调整预算和应急金','制定存钱计划','控制开销','本月支出预算','攒钱买车'],'wealth','plan'));
test('卡片同义词只打开管理页面',()=>routes(['我的卡丢了','银行卡不见了','提高限额','冻结卡片','申请办卡','解锁银行卡'],'cards'));
test('回执与交易历史不误当成新转账',()=>routes(['查上一笔转账回执','看看转账记录','查转账明细','这笔转账结果怎么样','取消这笔转账','刚才的操作失败了'],'tasks'));
test('查询余额与账户总览',()=>routes(['账户还有多少钱','我有多少钱','查余额','看看总资产','我有多少资产'],'overview'));
test('预演权限和风险档案有直接入口但不修改条件',()=>{routes(['资金够不够','转账会不会影响用款','打开资金预演'],'preview');routes(['撤销授权','看看权限范围'],'permissions');routes(['查看风险档案','风险测评'],'profile');});
test('账单月份分类联动，绝对与相对日期明确',()=>{const b=createSession();for(const [text,month,category] of [['看看上个月餐饮花了多少','2026-09','dining'],['查2026年9月交通账单','2026-09','transport'],['十月购物消费','2026-10','shopping'],['本月工资收入','2026-10','income']]){const r=b.interpret(text);assert.equal(r.route,'spending');assert.equal(r.filters.month,month,text);assert.equal(r.filters.category,category,text);}});
test('多个场景需选择，不按第一个关键词直接执行',()=>{const b=createSession(),r=b.interpret('看看余额和账单');assert.equal(r.route,null);assert.equal(r.choices.length,2);assert.ok(r.choices.some(c=>c.route==='overview'));assert.ok(r.choices.some(c=>c.tab==='bills'));});
test('未知或帮助语句保留可恢复指引',()=>{const b=createSession();for(const text of ['你好','支持哪些功能','我不知道怎么用','今天的天气']){const r=b.interpret(text);assert.equal(r.route,null);assert.ok(r.message.length>10);}});
test('所有识别仅记录输入，不授权扣款取消或修改卡片',()=>{const b=createSession(),before=b.state;for(const text of ['给林晓转300块','取消会员续费','挂失银行卡','撤销授权','想赎回1000元','调整预算','推荐理财'])b.interpret(text);assert.equal(b.state.available,before.available);assert.equal(b.state.operations.length,0);assert.deepEqual(b.state.cards,before.cards);assert.deepEqual(b.state.consent,before.consent);assert.deepEqual(b.state.subscriptions,before.subscriptions);assert.deepEqual(b.state.goal,before.goal);});
console.log(JSON.stringify({passed:cases.length,cases},null,2));
