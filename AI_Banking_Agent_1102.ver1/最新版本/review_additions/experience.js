/* Optional semantic summaries. Never reads input values, textContent or form data. */
(function (global) {
  'use strict';
  const CLIENT_ACTIONS = new Set(['navigation','filter','search','open_detail','compare','plan_edit','preview','confirm_open','confirm_submit','confirm_close','cancel','form_submit','assistant_submit','permission_open','control']);
  const PAGE = new Set(['overview','spending','wealth','tasks','other']);
  const actions = {overview:'navigation',spending:'navigation',wealth:'navigation',tasks:'navigation',
    'wealth-tab':'navigation','spending-tab':'navigation',plan:'navigation',holdings:'navigation',subscriptions:'navigation',
    'add-compare':'compare','remove-compare':'compare',compare:'compare',preview:'preview','preview-reset':'preview',
    purchase:'confirm_open','confirm-op':'confirm_open','cancel-sub':'confirm_open',
    close:'confirm_close','cancel-op':'cancel','cancel-wait':'cancel','assistant-cancel':'cancel',
    permissions:'permission_open',revoke:'permission_open',choose:'plan_edit',liquid:'plan_edit'};
  function classifyClick(el) {
    if (!el || el.disabled) return null;
    if (el.id === 'close-panel') return 'confirm_close';
    if (el.hasAttribute?.('data-review-source')) return 'open_detail';
    const action = el.dataset && el.dataset.action;
    if (!action) return 'control';
    return actions[action] || (/detail|receipts/.test(action) ? 'open_detail' : 'control');
  }
  function classifyForm(id) {
    return id === 'confirm-form' ? 'confirm_submit' : /assistant/.test(id) ? 'assistant_submit' :
      /search/.test(id) ? 'search' : /goal|budget|amount/.test(id) ? 'plan_edit' : 'form_submit';
  }
  function cleanQueue(value, epoch) {
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    if (!value || value.epoch !== epoch || !Array.isArray(value.events)) return [];
    return value.events.filter(e => e && Object.keys(e).sort().join() === 'action,event_id,page' && uuid.test(e.event_id) && CLIENT_ACTIONS.has(e.action) && PAGE.has(e.page)).slice(-100);
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {classifyClick, classifyForm, cleanQueue}; return;
  }
  const storeKey = 'banking-operation-summaries-v1';
  let pref = {enabled:false,epoch:null}, queue = [], busy = false, timer = null, retry = 1000, error = '', lost = 0;
  let dialog, launcher, items, notice, toggle, state, initialized = false, lastFocus;
  const page = () => location.hash.match(/^#\/(overview|spending|wealth|tasks)(?:\/|$)/)?.[1] || 'other';
  async function api(route, body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/experience/' + route, {method:body === undefined?'GET':'POST', credentials:'same-origin',
        headers:body === undefined?{}:{'Content-Type':'application/json'}, body:body === undefined?undefined:JSON.stringify(body), signal:controller.signal});
      const data = await response.json();
      if (!response.ok || data.error) {const err = new Error(data.error?.message || '操作摘要暂不可用'); err.code=data.error?.code; throw err;}
      return data.data;
    } catch (error) {
      if (error.code) throw error;
      const friendly = new Error('暂时无法连接操作摘要服务。已保留待同步摘要，请稍后重试。');
      friendly.code='EXPERIENCE_NETWORK';throw friendly;
    } finally {clearTimeout(timeout);}
  }
  function persist() {
    try {sessionStorage.setItem(storeKey, JSON.stringify({epoch:pref.epoch, events:queue}));}
    catch (_) {error='浏览器暂不能保存待同步摘要，关闭页面后可能丢失。';}
  }
  function showState() {
    if (!state) return;
    state.textContent = error || (!pref.enabled ? '操作摘要未开启' : queue.length ? `有 ${queue.length} 条摘要待同步${navigator.onLine?'':'，连接恢复后会重试'}` : '操作摘要已同步');
    if (lost) state.textContent += `；队列已满，${lost} 条较早摘要未保留`;
    launcher.textContent = queue.length ? '操作摘要 · 待同步' : '操作摘要';
    launcher.title = state.textContent;
    toggle.textContent = pref.enabled ? '关闭记录' : '开启操作摘要';
  }
  function schedule(delay=500) {clearTimeout(timer);if (pref.enabled && queue.length) timer=setTimeout(flush,delay);}
  async function refreshStatus() {
    const next = await api('status');
    if (pref.epoch !== next.epoch || !next.enabled) queue=[];
    pref=next; persist(); showState(); return next;
  }
  async function flush() {
    if (busy || !pref.enabled || !queue.length) return;
    if (!navigator.onLine) {error='当前离线，摘要待同步；交易结果请以任务回执为准。';showState();return;}
    busy=true; const epoch=pref.epoch, batch=queue.slice(0,30);
    try {
      const result=await api('events',{epoch,events:batch});
      if (pref.epoch===epoch) {const accepted=new Set(result.accepted);queue=queue.filter(e=>!accepted.has(e.event_id));error='';retry=1000;persist();}
    } catch (e) {
      if (pref.epoch!==epoch) return;
      if (e.code==='EXPERIENCE_REVOKED' || e.code==='AUTH_REQUIRED') {
        queue=[];pref.enabled=false;persist();error='记录授权已更新，旧摘要已停止上传。';
      } else {error='摘要暂未同步，会自动重试；不会重复提交金融操作。';retry=Math.min(retry*2,30000);}
    } finally {busy=false;showState();schedule(retry);}
  }
  function record(action) {
    if (!pref.enabled || !CLIENT_ACTIONS.has(action)) return;
    if (queue.length>=100) {queue.shift();lost++;}
    queue.push({event_id:crypto.randomUUID(),action,page:page()});persist();showState();schedule();
  }
  const labels={navigation:'切换页面',filter:'调整筛选',search:'查询明细',open_detail:'查看详情',compare:'比较产品',plan_edit:'调整计划',preview:'资金预演',confirm_open:'打开确认',confirm_submit:'提交确认',confirm_close:'关闭面板',cancel:'取消操作',form_submit:'提交表单',assistant_submit:'向助手提交需求',permission_open:'查看权限',control:'使用页面功能',
    snapshot:'更新账户概况',knowledge:'查阅知识资料',chat:'向助手提交需求',analysis:'分析账单','rpc.authorize':'更新业务授权','rpc.propose':'生成待确认操作','rpc.verify':'验证本次操作','rpc.execute':'执行操作','rpc.cancel':'取消待执行操作','rpc.reconcile':'查询回执','rpc.settle':'查询到账','rpc.select':'选择配置','rpc.configure':'更新资金计划','rpc.budget':'更新预算','transfer.preview':'核对转账','transfer.confirm':'确认转账','transfer.verify':'验证转账'};
  const statuses={unverified:'界面操作已收到，结果未核实',started:'请求已开始，需核对后续回执',succeeded:'服务已完成请求',rejected:'请求未获允许',failed:'服务返回失败',cancelled:'已取消',unknown:'结果待核实',processing:'处理中',invalidated:'条件已变化',awaiting_confirmation:'等待确认',needs_input:'需要补充信息'};
  async function loadRecords() {
    items.replaceChildren();notice.textContent='正在读取操作摘要…';
    try {
      await refreshStatus();
      if (!pref.enabled) {notice.textContent='可自愿开启，便于回看操作过程。关闭后停止记录和查询；也可以直接删除已有摘要。';return;}
      const data=await api('query',{});notice.textContent=data.items.length?'以下为最近的操作摘要。交易是否到账，请到“任务与记录”核对。':'还没有操作摘要。使用页面后会显示在这里。';
      data.items.forEach(item=>{
        const row=document.createElement('li'),title=document.createElement('strong'),description=document.createElement('p'),time=document.createElement('small');
        title.textContent=labels[item.action] || (item.source==='server_result'?'处理银行服务请求':'使用页面功能');
        description.textContent=(item.source==='server_result'?'服务记录 · ':'界面记录 · ')+(statuses[item.status]||'待核对');
        time.textContent=new Date(item.at).toLocaleString('zh-CN');row.append(title,description,time);
        if (item.phase==='request_result') {
          const feedback=document.createElement('button');feedback.type='button';feedback.textContent=item.feedback==='incorrect'?'已标记待核对':'这条需要核对';feedback.disabled=item.feedback==='incorrect';
          feedback.onclick=async()=>{feedback.disabled=true;try{await api('feedback',{event_id:item.event_id,rating:'incorrect'});feedback.textContent='已标记待核对';}catch(e){notice.textContent=e.message;feedback.disabled=false;}};
          row.append(feedback);
        }
        items.append(row);
      });
    } catch(e) {notice.textContent=e.message;}
  }
  function button(text, fn) {const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=fn;return b;}
  async function init() {
    if (initialized || !global.BankSession) return;initialized=true;
    launcher=button('操作摘要',async()=>{lastFocus=document.activeElement;dialog.showModal();await loadRecords();});launcher.id='experience-launcher';
    dialog=document.createElement('dialog');dialog.id='experience-dialog';dialog.setAttribute('aria-labelledby','experience-heading');
    const heading=document.createElement('h2');heading.id='experience-heading';heading.textContent='你的操作摘要';
    const intro=document.createElement('p');intro.textContent='仅记录操作类型与处理状态，用于回看和问题核对。不记录输入原文、密码或验证码，也不会自动替你执行交易。';
    state=document.createElement('p');state.setAttribute('role','status');
    notice=document.createElement('p');notice.setAttribute('aria-live','polite');items=document.createElement('ol');
    const controls=document.createElement('div');controls.className='experience-controls';
    toggle=button('开启操作摘要',async()=>{toggle.disabled=true;try{pref=await api('consent',{enabled:!pref.enabled});queue=[];error='';persist();showState();await loadRecords();}catch(e){notice.textContent=e.message;}finally{toggle.disabled=false;}});
    controls.append(toggle,button('刷新摘要',loadRecords),button('立即同步',flush));
    const remove=button('删除操作摘要',async()=>{remove.disabled=true;try{pref=await api('delete',{confirmation:'删除操作摘要'});queue=[];lost=0;error='';persist();showState();await loadRecords();notice.textContent='操作摘要已删除，记录已关闭。账单、余额和任务回执保留。';}catch(e){notice.textContent=e.message;}finally{remove.disabled=false;}});remove.className='experience-delete';
    const deletion=document.createElement('details'),summary=document.createElement('summary');summary.textContent='删除与记录范围';
    const limitation=document.createElement('p');limitation.textContent='摘要保存在本机，按当前浏览器会话隔离，最多保留1000条。断网时最多暂存100条；关闭页面、清理浏览器数据或服务异常可能造成遗漏。删除后停止记录并清空摘要，必要的银行操作记录仍会保留。';deletion.append(summary,limitation,remove);
    dialog.append(heading,intro,button('关闭',()=>dialog.close()),controls,state,notice,items,deletion);
    dialog.addEventListener('close',()=>lastFocus?.focus());document.body.append(launcher,dialog);
    try {pref=await api('status');let saved;try{saved=JSON.parse(sessionStorage.getItem(storeKey));}catch(_){}queue=pref.enabled?cleanQueue(saved,pref.epoch):[];persist();showState();schedule();}
    catch(e) {error=e.message;showState();}
    document.addEventListener('click',e=>{if (e.target.closest('#experience-dialog,#experience-launcher')) return;const el=e.target.closest('button,[data-action],a[href]');if (el && !el.disabled)record(classifyClick(el));},true);
    document.addEventListener('change',e=>{if (e.target.matches('[data-filter]'))record('filter');},true);
    document.addEventListener('submit',e=>{if (!e.target.closest('#experience-dialog'))record(classifyForm(e.target.id));},true);
    document.addEventListener('cancel',e=>{if(e.target.id!=='experience-dialog')record('confirm_close');},true);
    global.addEventListener('hashchange',()=>record('navigation'));
    global.addEventListener('bank-feature-open',()=>record('navigation'));
    global.addEventListener('online',flush);global.addEventListener('offline',showState);
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshStatus().then(flush).catch(()=>{});});
  }
  global.addEventListener('bank-ready',init);if(global.BankSession)init();
})(globalThis);
