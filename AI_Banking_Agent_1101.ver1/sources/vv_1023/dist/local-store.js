/* Frontend demo persistence adapter. No network requests, bank credentials, or backend. */
(function(global){
'use strict';
const KEY='banking-unified-demo-v3';
function createSession(){
 let revision=0,warning='',blocked=false,saved;
 try{const raw=localStorage.getItem(KEY);if(raw){const envelope=JSON.parse(raw);if(envelope.schema!==3||!envelope.state)throw Error('不支持的快照版本');saved=envelope.state;revision=envelope.revision;}}
 catch(e){warning='无法读取本地演示记录。为避免覆盖旧记录，已停止写操作。可在沙箱设置下载原始备份后清除浏览器站点数据。';blocked=true;}
 let core;try{core=BankCore.createSession(saved);}catch(e){warning='本地快照未通过账本校验，已阻止写入，未覆盖旧记录。';blocked=true;core=BankCore.createSession();}
 const writeNames=['configure','select','authorize','setProfile','analyze','reviewSubscription','keep','budget','propose','cancel','verify','execute','reconcile','settle','settleCard','advance','pause','resume','unlock','liquid','interpret'];
 function checkRevision(){if(blocked)throw Error(warning);try{const raw=localStorage.getItem(KEY);if((!raw&&revision>0)||(raw&&JSON.parse(raw).revision!==revision))throw Error('另一个页面已更新账本，请刷新本页后继续，避免覆盖记录。');}catch(e){throw Error(e.message||'无法访问本地存储');}}
 function persist(){try{localStorage.setItem(KEY,JSON.stringify({schema:3,revision:++revision,state:core.state,savedAt:new Date().toISOString()}));warning='';}catch(e){warning='浏览器未能保存本次模拟记录（可能存储已满或被禁用）。当前视图仍可核对，请下载备份；刷新可能丢失这次变化。';blocked=true;}}
 const adapter={get state(){return core.state;},get catalog(){return core.catalog;},get storageWarning(){return warning;},get persisted(){return !warning;},exportSnapshot(){try{return localStorage.getItem(KEY)||JSON.stringify({schema:3,state:core.state});}catch(e){return JSON.stringify({schema:3,state:core.state});}},exportCurrent(){return JSON.stringify({schema:3,revision,state:core.state,savedAt:new Date().toISOString()},null,2);}};
 for(const name of Object.keys(core)){if(typeof core[name]!=='function')continue;if(writeNames.includes(name))adapter[name]=(...args)=>{checkRevision();try{return core[name](...args);}finally{persist();}};else adapter[name]=(...args)=>core[name](...args);}
 if(!blocked)persist();
 return adapter;
}
global.BankLocal={createSession,key:KEY};
})(globalThis);
