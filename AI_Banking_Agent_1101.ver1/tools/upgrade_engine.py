from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'web/journey-engine.js'
s=p.read_text(encoding='utf-8')
s=s.replace('state.initialTotal=state.initialTotal??12864000;state.externalOut=state.externalOut??0;', '''state.initialTotal=state.initialTotal??12864000;state.externalOut=state.externalOut??0;state.externalIn=state.externalIn??0;
 state.simulation={monthly_income_minor:2850000,monthly_expense_minor:1286000,salary_day:15,expense_day:5,annual_return:.02,annual_volatility:.08,...(state.simulation||{})};state.valuation_events=state.valuation_events||[];state.event_reservations=state.event_reservations||{};''')
s=s.replace('function capacity(){return Math.max(0,Math.min(state.goal.total,state.available)-state.goal.need-state.goal.emergency);}', "function eventReserved(){return Object.values(state.event_reservations).filter(x=>x.status==='reserved').reduce((n,x)=>n+x.amount_minor,0);}\n function capacity(){return Math.max(0,Math.min(state.goal.total,state.available)-state.goal.need-state.goal.emergency-eventReserved());}")
s=s.replace('total()+state.externalOut!==state.initialTotal','total()+state.externalOut!==state.initialTotal+state.externalIn')
s=s.replace("if(p.risk>1)reasons.push('高于当前低风险档案上限');", "if(p.risk>Math.min(state.personal_profile?.risk_tolerance??1,state.personal_profile?.risk_capacity??1))reasons.push('高于当前风险档案上限');")
start=s.index(' function advance(days)');end=s.index(' function pause()',start)
s=s[:start]+''' function configureSimulation(settings){
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
''' + s[end:]
start=s.index(' function projection(');end=s.index(' function transferIntent(',start)
s=s[:start]+''' function projection({amount:configured=state.amount,productId=state.selected,income=state.simulation.monthly_income_minor,expense=state.budget,annualReturn=state.simulation.annual_return,annualVolatility=state.simulation.annual_volatility}={}){
  amount(configured);amount(income);amount(expense);if(configured>capacity())throw Error('预演金额超过扣除事件预留后的可配置资金');
  if(!Number.isFinite(annualReturn)||annualReturn<=-1||annualReturn>1||!Number.isFinite(annualVolatility)||annualVolatility<0||annualVolatility>1)throw Error('收益率须大于-100%且不超过100%，波动须为0–100%');
  const p=productId==='NONE'?null:product(productId),rows=[],principal=p?configured:0;
  for(let m=0;m<=state.goal.months;m++){
   const t=m/12,period=p&&p.term?Math.min(m,p.term)/12:t,value=Math.round(principal*Math.pow(1+annualReturn,period));
   const recovered=!!p&&p.term>0&&m>p.term,lock=p&&!recovered?value:0;
   const base=state.available+(income-state.simulation.monthly_expense_minor)*m;
   const plan=state.available+(income-expense+monthlySaved())*m-principal+(recovered?value:0);
   const reserve=state.goal.need+state.goal.emergency+eventReserved();
   const lower=Math.round(principal*Math.exp(Math.log1p(annualReturn)*period-annualVolatility*Math.sqrt(period)));
   const upper=Math.round(principal*Math.exp(Math.log1p(annualReturn)*period+annualVolatility*Math.sqrt(period)));
   rows.push({month:m,baseline:base,planned:plan,locked:lock,required:reserve,gap:Math.max(0,reserve-plan),investment_value:value,investment_gain:value-principal,wealth:plan+lock,lower,upper,annual_return:annualReturn,annual_volatility:annualVolatility});
  }return rows;
 }
''' + s[end:]
s=s.replace('capacity,monthlySaved,eligibility,configure,select','capacity,eventReserved,monthlySaved,eligibility,configure,configureSimulation,select')
s=s.replace("rows=state.transactions.filter(t=>t.date.startsWith(month))", "rows=state.transactions.filter(t=>t.date.startsWith(month)&&t.status==='booked')")
s=s.replace('样本净值固定为本金，不模拟收益或波动。','持仓按配置的假设收益更新市值，不代表实际市场净值。')
p.write_text(s,encoding='utf-8')
print('engine upgraded')
