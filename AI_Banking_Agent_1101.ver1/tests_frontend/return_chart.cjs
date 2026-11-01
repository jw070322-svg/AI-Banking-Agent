const assert=require('node:assert/strict');
const {createSession}=require('../web/journey-engine.js');
const {chartModel,render}=require('../web/projection-chart.js');
const cases=[];function test(name,fn){fn();cases.push(name);}
const bank=createSession();
test('现金管理与四类固收目录具备独立的风险及预演假设',()=>{
 assert.equal(bank.catalog.length,5);assert.deepEqual(bank.catalog.map(p=>p.risk),[1,2,2,2,3]);
 assert.equal(new Set(bank.catalog.map(p=>p.projection.annual_return)).size,5);
 assert.ok(bank.catalog.every(p=>!p.name.includes('存款')&&p.yield===null&&p.projection.annual_volatility>0));
});
test('R1不能申购R2；R2正常匹配90天但不能配置超期产品',()=>{
 assert.equal(bank.eligibility('TERM3').kind,'不匹配');
 const state=bank.state;state.personal_profile={risk_capacity:2,risk_tolerance:2};const b=createSession(state);
 assert.equal(b.eligibility('TERM3').kind,'匹配');assert.equal(b.eligibility('TERM6').kind,'受限');assert.equal(b.eligibility('BALANCED').kind,'不匹配');
});
test('逐日曲线181个点与每月表格在所有月末精确一致',()=>{
 const daily=bank.projection({frequency:'daily'}),monthly=bank.projection();assert.equal(daily.length,181);
 for(let i=0;i<monthly.length;i++)assert.deepEqual(daily[i*30],monthly[i]);
});
test('同本金同期限产品切换使用各自默认收益率',()=>{
 for(const p of bank.catalog){const row=bank.projection({productId:p.id}).at(-1),years=(p.term?Math.min(6,p.term):6)/12;assert.equal(row.investment_value,Math.round(bank.state.amount*(1+p.projection.annual_return)**years));assert.equal(row.annual_volatility,p.projection.annual_volatility);}
});
test('低收益不再被本金坐标压平，收益端点与账面计算一致',()=>{
 const rows=bank.projection({frequency:'daily'}),m=chartModel(rows);assert.ok(m.main[0].y-m.main.at(-1).y>150);
 assert.equal(m.main.at(-1).value,rows.at(-1).investment_gain/100);assert.equal(m.main[0].value,0);
});
test('负收益向下且负数刻度和读数可见',()=>{
 const rows=bank.projection({annualReturn:-.2,annualVolatility:0,frequency:'daily'}),m=chartModel(rows);
 assert.ok(m.main.at(-1).y>m.main[0].y);assert.ok(m.min<0);assert.equal(rows.at(-1).investment_value,Math.round(bank.state.amount*Math.sqrt(.8)));assert.match(render(rows),/¥-/);
});
test('零收益为水平线，零本金和保留流动性为空态',()=>{
 const flat=chartModel(bank.projection({annualReturn:0,annualVolatility:0}));assert.equal(flat.main[0].y,flat.main.at(-1).y);
 assert.ok(chartModel(bank.projection({amount:0})).empty);assert.ok(chartModel(bank.projection({productId:'NONE'})).empty);
});
test('收益率和资产价值视图显示正确单位与坐标',()=>{
 const rows=bank.projection(),percent=chartModel(rows,{metric:'percent'}),value=chartModel(rows,{metric:'value'});
 assert.equal(percent.main.at(-1).value,rows.at(-1).investment_gain/rows[0].principal*100);
 assert.equal(value.main[0].value,rows[0].principal/100);assert.ok(value.min>0);
});
test('波动情景单独控制缩放并包含负收益可能',()=>{
 const rows=bank.projection({annualReturn:.02,annualVolatility:.2}),normal=chartModel(rows),band=chartModel(rows,{band:true});
 assert.ok(band.max>normal.max);assert.ok(band.min<0);assert.ok(rows.at(-1).lower<rows[0].principal);
});
test('90天赎回情景91天到账，此后收益保持不变',()=>{
 const rows=bank.projection({productId:'TERM3',frequency:'daily',income:0,expense:0});
 assert.equal(rows[90].recovered,false);assert.equal(rows[91].recovered,true);assert.equal(rows[91].locked,0);
 assert.equal(rows[91].planned-rows[90].planned,rows[90].investment_value);
 assert.equal(rows[180].investment_gain,rows[90].investment_gain);
 assert.equal(rows[90].wealth,rows[91].wealth);
});
test('收入支出只改变现金流，不冒充投资收益',()=>{
 const a=bank.projection({income:0,expense:0}),b=bank.projection({income:1000000,expense:500000});
 assert.equal(a.at(-1).investment_gain,b.at(-1).investment_gain);assert.equal(b.at(-1).planned-a.at(-1).planned,3000000);
});
test('事件预留压低可配置上限，曲线不允许超额资金',()=>{
 const state=bank.state;state.event_reservations={birthday:{status:'reserved',amount_minor:100000}};const b=createSession(state);
 assert.equal(b.capacity(),264000);assert.throws(()=>b.projection({amount:264001,frequency:'daily'}));assert.equal(b.projection({amount:264000})[0].required,3600000);
});
test('长周期极端输入图形有限，非法频率与无效数据被拒绝',()=>{
 const state=bank.state;state.goal.months=36;const rows=createSession(state).projection({annualReturn:1,annualVolatility:1,frequency:'daily'}),m=chartModel(rows,{band:true});
 assert.equal(rows.length,1081);assert.ok(m.main.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));assert.doesNotMatch(render(rows),/NaN|Infinity/);
 assert.throws(()=>bank.projection({frequency:'hourly'}));assert.throws(()=>chartModel([{principal:NaN}]));
});
console.log(JSON.stringify({passed:cases.length,cases},null,2));
