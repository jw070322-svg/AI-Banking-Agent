const assert = require('node:assert/strict');
const {classifyClick,classifyForm,cleanQueue} = require('./experience.js');
const id = 'd93dbe4b-600e-4000-a8a2-04c2bf104c58';
const checks = [];
function check(name, fn) { fn(); checks.push(name); }
check('filters and comparison map to a semantic operation', () => {
  assert.equal(classifyClick({dataset:{action:'add-compare'}}),'compare');
  assert.equal(classifyClick({dataset:{action:'cancel-op'}}),'cancel');
});
check('disabled controls are not recorded as attempted actions',()=>assert.equal(classifyClick({disabled:true,dataset:{action:'purchase'}}),null));
check('submission and confirmation separated',()=>{
  assert.equal(classifyForm('confirm-form'),'confirm_submit');
  assert.equal(classifyForm('assistant-form'),'assistant_submit');
  assert.equal(classifyForm('transaction-search'),'search');
});
check('queue cannot switch owner or consent epoch',()=>assert.deepEqual(cleanQueue({epoch:'old',events:[{event_id:id,action:'filter',page:'wealth'}]},'new'),[]));
check('poisoned storage never leaks text or credentials',()=>{
  for(const extra of [{text:'password 123456'},{status:'succeeded'},{user_id:'someone'},{source:'server_result'}]) {
    assert.deepEqual(cleanQueue({epoch:'e',events:[{event_id:id,action:'filter',page:'wealth',...extra}]},'e'),[]);
  }
});
check('malformed/unknown queued events rejected',()=>assert.deepEqual(cleanQueue({epoch:'e',events:[{event_id:'cardnumber',action:'filter',page:'wealth'},{event_id:id,action:'execute_transfer',page:'wealth'}]},'e'),[]));
check('queue bounded and safe event retained',()=>{
 const events=Array.from({length:130},()=>({event_id:id,action:'filter',page:'wealth'}));
 assert.equal(cleanQueue({epoch:'e',events},'e').length,100);
});
check('local citations are clickable and unsafe links cannot enter markup',()=>{
 const {links}=require('./source-links.js');
 const result=links({results:[{tool:'knowledge',result:{citations:[{citation_uri:'/review/source/yuki-01#L3',title:'<img onerror=evil()>',start_line:3},{citation_uri:'javascript:alert(1)',title:'bad'}]}}]});
 assert.ok(result.includes('href="/review/source/yuki-01#L3"'));
 assert.ok(result.includes('&lt;img'));assert.ok(!result.includes('javascript:'));assert.ok(!result.includes('<img'));
});
console.log(JSON.stringify({passed:checks.length,checks}));
