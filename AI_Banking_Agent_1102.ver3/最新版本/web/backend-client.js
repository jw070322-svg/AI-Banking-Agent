/* One authoritative SQLite ledger. No localStorage ledger and no synchronous XHR. */
(function(global){'use strict';
async function createBackendSession(){
 let snapshot,token='',developer=false,hasBackup=false,busy=false,warning='';
 const emit=()=>global.dispatchEvent(new Event('bank-network-state'));
 async function transport(path,body,key){const post=body!==undefined,research=path==='/api/knowledge'||path.startsWith('/api/external/')||path.startsWith('/api/local-life/'),controller=new AbortController(),timer=setTimeout(()=>controller.abort(),research?65000:20000);let response,data;
  try{const headers={Accept:'application/json'};if(post){headers['Content-Type']='application/json';headers['Idempotency-Key']=key||crypto.randomUUID();}if(token)headers['X-Developer-Token']=token;
   response=await fetch(path,{method:post?'POST':'GET',headers,credentials:'same-origin',body:post?JSON.stringify(body):undefined,signal:controller.signal});data=await response.json();
  }catch(e){const error=Error(post&&!research?'连接中断，是否受理尚不确定。请刷新后查询原操作，暂勿重复提交。':'无法连接账户服务，请确认服务已启动后重试。');error.uncertain=post&&!research;throw error;}finally{clearTimeout(timer);}
  if(!data||typeof data!=='object'||!('data' in data)||typeof data.status!=='string')throw Error('暂时无法核对服务结果，请刷新后查询记录。');
  if(!response.ok||data.error){if(data.error?.code==='DEVELOPER_REQUIRED'){token='';developer=false;}throw Error(data.error?.message||'本次操作未完成，请核对条件后重试。');}return data.data;
 }
 async function refresh(){snapshot=await transport('/api/snapshot');if(!snapshot?.state||!Array.isArray(snapshot.catalog)||!Number.isSafeInteger(snapshot.state.available))throw Error('账户资料暂时不可用，请重新连接。');warning='';}
 async function request(path,body){if(busy)throw Error('上一项请求仍在处理中，请稍候。');busy=true;emit();try{return await transport(path,body);}finally{busy=false;emit();}}
 async function mutate(path,body){if(warning)throw Error(warning);if(busy)throw Error('上一项请求仍在处理中，请稍候。');busy=true;emit();let result,error;try{result=await transport(path,body);}catch(e){error=e;}try{await refresh();}catch(e){warning='账户信息尚未刷新，请重新加载后核对，暂勿重复提交。';if(!error)error=e;}finally{busy=false;emit();}if(error)throw error;return result;}
 await transport('/api/session',{});await refresh();
 const readCore=()=>global.BankCore.createSession(snapshot.state);
 const api={get state(){return structuredClone(snapshot.state);},get catalog(){return structuredClone(snapshot.catalog);},get networkBusy(){return busy;},get storageWarning(){return warning;},get persisted(){return !warning;},get developerUnlocked(){return developer;},get hasDeveloperBackup(){return hasBackup;},total:()=>snapshot.total,capacity:()=>snapshot.capacity,monthlySaved:()=>snapshot.state.subscriptions.filter(x=>x.status==='cancelled').reduce((n,x)=>n+x.amount,0),summary:month=>readCore().summary(month),eligibility:(...args)=>readCore().eligibility(...args),projection:(...args)=>readCore().projection(...args),exportCurrent:()=>JSON.stringify(snapshot,null,2),exportSnapshot:()=>JSON.stringify(snapshot),refresh:()=>request('/api/snapshot').then(value=>{snapshot=value;warning='';}),
 async developerLogin(code){const result=await request('/api/developer/login',{code});token=result.token;developer=true;hasBackup=result.has_backup;},async developerLogout(){if(token)try{await request('/api/developer/logout',{});}finally{token='';developer=false;}},async developerReset(confirmation){if(!developer)throw Error('请先解锁开发者工具');const result=await mutate('/api/developer/reset',{confirmation});hasBackup=true;return result;},async developerRestore(confirmation){if(!developer)throw Error('请先解锁开发者工具');return mutate('/api/developer/restore',{confirmation});},recommendations:()=>request('/api/recommendations',{objective:'liquidity',top_k:3}),generateScenario:prompt=>request('/api/scenarios/generate',{prompt,format:'contract'}),analysis:tool=>request('/api/analysis',{tool,args:{days:30}}),knowledge:question=>request('/api/knowledge',{question,top_k:3})};
 for(const method of ['configureSimulation','authorize','configure','select','setProfile','analyze','reviewSubscription','keep','budget','propose','cancel','verify','execute','reconcile','settle','settleCard','advance','pause','resume','unlock','liquid','interpret','assistant'])api[method]=(...args)=>mutate('/api/rpc',{method,args});
 api.research=(action,args={})=>request('/api/'+action,args);
 api.extension=(action,args={})=>mutate('/api/'+action,args);
 api.extensionRead=path=>request('/api/'+path);
 global.BankSession=api;
 return api;
}
global.BankGateway={createBackendSession};
})(globalThis);
