const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/journey-engine.js'),'utf8');let now=1800000000000;class ClockDate extends Date{static now(){return now;}}
const ctx={module:{exports:{}},Date:ClockDate};vm.createContext(ctx);vm.runInContext(source,ctx);const {createSession}=ctx.module.exports;
const passed=[];function test(n,f){f();passed.push(n);}function ready(){const b=createSession();b.authorize({read:true,subscriptions:true,trade:true,cards:true});return b;}
function run(b,n,options){const o=b.propose('transfer','R-WANG',n,options);if(o.level==='red')b.verify(o.id,'246810');b.execute(o.id,'success');return o;}
test('1000元边界黄色可确认，累计多笔超限变红色',()=>{const b=ready(),a=run(b,80000);assert.equal(a.level,'yellow');const o=b.propose('transfer','R-WANG',20001);assert.equal(o.level,'red');assert.throws(()=>b.execute(o.id,'success'));b.cancel(o.id);assert.equal(run(b,20000).level,'yellow');assert.equal(b.state.available,3764000);});
test('300秒预览过期不扣款且状态失效',()=>{const b=ready(),o=b.propose('transfer','R-WANG',80000);assert.equal(Number.isInteger(o.expiresAt),true);now+=300000;assert.throws(()=>b.execute(o.id,'success'));assert.equal(b.state.available,3864000);assert.equal(b.state.operations.at(-1).status,'invalidated');});
test('120秒断言过期需重新验证但不延长预览',()=>{const b=ready(),o=b.propose('transfer','R-WANG',120000);b.verify(o.id,'246810');now+=120000;assert.throws(()=>b.execute(o.id,'success'));b.verify(o.id,'246810');b.execute(o.id,'success');assert.equal(b.state.available,3744000);});
test('申购遵循相同的预览/断言时限',()=>{const b=ready(),o=b.propose('purchase');b.verify(o.id,'246810');now+=301000;assert.throws(()=>b.execute(o.id,'success'));assert.equal(b.state.available,3864000);});
test('只有独立旧转账权限不能绕过trade，卡扩展仍隔离',()=>{const b=createSession();b.authorize({read:true,trade:false,subscriptions:false,transfer:true,cards:true});assert.throws(()=>b.propose('transfer','R-WANG',1));const o=b.propose('card_lock','CARD-DEBIT');assert.equal(o.permission,'cards');});
console.log(JSON.stringify({passed:passed.length,cases:passed},null,2));
