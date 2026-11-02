/* FirstAgent 1.0 transport preparation. Explicit use only; no startup requests or local fallback. */
(function(global){
'use strict';
const STATUS=new Set(['succeeded','needs_input','awaiting_confirmation','unknown','processing','failed','rejected','cancelled','invalidated']);
const RPC=new Set('authorize configure select setProfile analyze summary reviewSubscription keep budget propose cancel verify execute reconcile settle advance pause resume unlock liquid projection interpret eligibility total capacity monthlySaved'.split(' '));
class ContractError extends Error{constructor(code,message,details={}){super(message);this.name='ContractError';this.code=code;Object.assign(this,details);}}
function minor(n,positive=true){if(typeof n!=='number'||!Number.isSafeInteger(n)||n<(positive?1:0))throw new ContractError('INVALID_AMOUNT','金额必须为 CNY 整数分。');return n;}
function scopes(v){if(!v||!['read','subscriptions','trade'].every(k=>typeof v[k]==='boolean'))throw new ContractError('INVALID_CONSENT','查询、订阅、交易权限均须为布尔值。');return {read:v.read,subscriptions:v.subscriptions,trade:v.trade};}
function envelope(v){if(!v||typeof v!=='object'||Array.isArray(v)||!['string','number'].includes(typeof v.schema_version)||typeof v.request_id!=='string'||!STATUS.has(v.status)||!('data' in v)||!('trace' in v)||typeof v.simulated!=='boolean'||!(v.error===null||v.error&&typeof v.error.code==='string'&&typeof v.error.message==='string'))throw new ContractError('INVALID_RESPONSE','响应不符合 FirstAgent 统一外壳；未更新本地账本。');return v;}
function createClient({baseURL,fetchImpl=global.fetch,idFactory=()=>global.crypto.randomUUID(),timeoutMs=15000}={}){
 if(!baseURL)throw new ContractError('BACKEND_NOT_CONFIGURED','尚未配置小组后台；本地模拟仍可独立使用。');
 const base=new URL(baseURL);if(!['http:','https:'].includes(base.protocol)||base.username||base.password||base.search||base.hash||base.pathname!=='/')throw new ContractError('INVALID_BASE_URL','请提供后台根地址，例如 http://localhost:8000/，不含凭据。');
 const seen=new Map();let initialized=false,starting=null;
 function prepare(path,body){if(!path.startsWith('/api/')||path.includes('..'))throw new ContractError('INVALID_PATH','无效接口路径');const payload=JSON.stringify(body);return Object.freeze({path,method:'POST',body:payload,key:idFactory()});}
 async function transport(path,{method='GET',body,key}={}){
  const url=new URL(path,base);if(url.origin!==base.origin)throw new ContractError('INVALID_ORIGIN','不允许跨到另一后台。');
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{const headers={'Accept':'application/json'};if(method==='POST'){headers['Content-Type']='application/json';if(key)headers['Idempotency-Key']=key;}
   const response=await fetchImpl(url.href,{method,headers,body,credentials:'include',signal:controller.signal});
   let data;try{data=envelope(await response.json());}catch(e){throw e instanceof ContractError?e:new ContractError('INVALID_RESPONSE','无法解析后台响应，未更新账本。');}
   if(!response.ok||data.error)throw new ContractError(data.error?.code||'HTTP_ERROR',data.error?.message||'后台请求失败',{response:data});return data;
  }catch(e){if(e instanceof ContractError)throw e;throw new ContractError(method==='POST'?'TRANSPORT_UNCERTAIN':'NETWORK_ERROR',method==='POST'?'连接中断，是否受理尚不确定。保留原请求键；已提交操作先查原回执，不自动重新提交。':'无法读取后台，请检查服务地址。',{idempotencyKey:key,path});}finally{clearTimeout(timer);}
 }
 async function start(){if(initialized)return;if(!starting)starting=transport('/api/session',{method:'POST',body:'{}'}).then(()=>{initialized=true;}).finally(()=>{starting=null;});await starting;}
 async function send(command){await start();if(!command||command.method!=='POST'||!command.key)throw new ContractError('INVALID_COMMAND','缺少固定幂等键');const fingerprint=command.path+'\n'+command.body;if(seen.has(command.key)&&seen.get(command.key)!==fingerprint)throw new ContractError('IDEMPOTENCY_CONFLICT','不能用同一请求键提交不同参数。');seen.set(command.key,fingerprint);return transport(command.path,{method:'POST',body:command.body,key:command.key});}
 async function get(path){await start();return transport(path);}
 const text=(x,label)=>{if(typeof x!=='string'||!x.trim())throw new ContractError('NEEDS_INPUT','请补充'+label);return x.trim();};
 return {start,send,health:()=>transport('/api/health'),snapshot:()=>get('/api/snapshot'),overview:()=>get('/api/accounts/overview'),transactions:month=>get('/api/transactions?month='+encodeURIComponent(text(month,'月份'))),subscriptions:()=>get('/api/subscriptions'),products:()=>get('/api/products'),operation:id=>get('/api/operations/'+encodeURIComponent(text(id,'操作编号'))),events:()=>get('/api/events'),
 previewTransfer({amount_minor,beneficiary_name,account_id='ACC-4821'}){minor(amount_minor);if(account_id!=='ACC-4821')throw new ContractError('ACCOUNT_FORBIDDEN','首版只支持 ACC-4821。');return prepare('/api/transfers/preview',{amount_minor,beneficiary_name:text(beneficiary_name,'名册姓名'),account_id});},
 verifyTransfer({operation_id,code}){return prepare('/api/transfers/verify',{operation_id:text(operation_id,'操作编号'),code:text(code,'验证码')});},
 confirmTransfer({operation_id,confirmed,assertion_id,outcome}){if(confirmed!==true)throw new ContractError('CONFIRMATION_REQUIRED','需要明确确认');const body={operation_id:text(operation_id,'操作编号'),confirmed:true};if(assertion_id!==undefined)body.assertion_id=text(assertion_id,'断言编号');if(outcome!==undefined){if(!['success','failed','unknown'].includes(outcome))throw new ContractError('INVALID_OUTCOME','无效模拟返回');body.outcome=outcome;}return prepare('/api/transfers/confirm',body);},
 cancelTransfer:id=>prepare('/api/transfers/cancel',{operation_id:text(id,'操作编号')}),
 reconcileTransfer(id,result){if(!['pending','success','failed'].includes(result))throw new ContractError('INVALID_RESULT','无效回执状态');return prepare('/api/transfers/reconcile',{operation_id:text(id,'操作编号'),result});},
 rpc(method,args=[]){if(!RPC.has(method)||!Array.isArray(args))throw new ContractError('UNSUPPORTED_CONTRACT','该方法不在小组接口白名单中，卡管理仍仅本地模拟。');if(method==='authorize')args=[scopes(args[0])];if(method==='propose'&&!['subscription','purchase','redeem'].includes(args[0]))throw new ContractError('UNSUPPORTED_CONTRACT','转账使用专用接口；银行卡接口尚未提供。');return prepare('/api/rpc',{method,args});},
 chat:message=>prepare('/api/chat',{message:text(message,'消息')}),recommendations:(objective,top_k=3)=>prepare('/api/recommendations',{objective,top_k}),knowledge:(question,top_k=3)=>prepare('/api/knowledge',{question:text(question,'问题'),top_k})};
}
global.FirstAgentContract={version:'1.0.0',minor,scopes,envelope,createClient,ContractError};
/* Explicit gateway: UI remains local until real backend integration is verified. */
global.BankGateway={createLocalSession:()=>global.BankLocal.createSession(),createBackendClient:options=>createClient(options)};
})(globalThis);
