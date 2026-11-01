/* Public research UI. Data is escaped; external URLs never become tool calls. */
(()=>{'use strict';
const esc=BankCustomerView.esc;
const dlg=document.createElement('dialog');dlg.id='external-dialog';dlg.setAttribute('aria-labelledby','external-title');
document.body.append(dlg);let pending=false,search=null,health=null,question='';
const link=(url,title)=>/^https:\/\//.test(url||'')?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`:'';
function render(){dlg.innerHTML=`<button id="external-close">关闭</button><h2 id="external-title">网站与免费 AI</h2>
<p>美团和大众点评直接打开官网。百度会尝试读取公开搜索结果；需要验证时，请在官方页面继续。</p>
<div class="external-sites">${link('https://www.meituan.com/','打开美团官网')}${link('https://www.dianping.com/','打开大众点评')}</div>
<p>商户价格、评分、可预约时间请在官网核对，本应用不自动下单。</p>
<h3>百度公开检索</h3><form id="external-search"><label>通用问题<input name="question" maxlength="300" required value="${esc(question)}" placeholder="例如：什么是债券久期"></label><label class="external-consent"><input name="public_approval" type="checkbox" required><span>本次问题可发送给百度，不含个人信息；知识库无依据时允许搜索</span></label><button ${pending?'disabled':''}>搜索百度</button><label class="external-consent"><input name="official_verify" type="checkbox"><span>知识库无依据时，允许读取该术语在知识库登记的官方页面原文（只访问 csrc.gov.cn / gov.cn / pbc.gov.cn / nfra.gov.cn；不发送我的问题）</span></label><button type="button" id="external-answer" ${pending?'disabled':''}>知识库 + 免费 AI 解答</button></form>
<p>“搜索百度”会向百度发送此处的问题；请只输入通用问题，不要输入个人、账户、流水、日历或预算信息。自动过滤无法保证识别全部敏感信息。知识解答仅在本次勾选确认且本地资料不足时搜索百度；未勾选时不外发。</p><div id="external-result" role="status">${pending?'正在读取，请稍候…':search?resultHtml(search):''}</div>
<h3>本地 AI 回退</h3><p>llama.cpp · 金融 LoRA 微调模型 · 无 API 费用。缺少可核验正文时会拦截模型解释，提示补充证据；不执行银行操作。</p>
<button id="external-probe" ${pending?'disabled':''}>检查百度与本地模型</button><div id="external-health">${health?`<p>百度：${esc(health.providers.baidu.message)}<br>本地模型：${esc(health.providers.llama_cpp.message)}</p>`:'尚未检查连接。'}</div>`;
dlg.querySelector('#external-close').onclick=()=>dlg.close();
dlg.querySelector('#external-search').onsubmit=e=>{e.preventDefault();const form=new FormData(e.target);question=form.get('question');if(form.get('public_approval')!=='on')return;run(async()=>{search=await BankSession.research('external/search',{question,public_search_approved:true});});};
dlg.querySelector('#external-answer').onclick=()=>{question=dlg.querySelector('input').value;const approved=dlg.querySelector('[name=public_approval]').checked;const verify=dlg.querySelector('[name=official_verify]').checked;run(async()=>{search={knowledge:await BankSession.research('knowledge',{question,top_k:3,public_search_approved:approved,online_verify:verify})};});};
dlg.querySelector('#external-probe').onclick=()=>run(async()=>{const r=await BankSession.research('external/probe',{});health=r.connections;});
}
function resultHtml(r){if(r.knowledge)return BankCustomerView.render({results:[{tool:'knowledge',result:r.knowledge}]})+(r.knowledge.status==='needs_evidence'?'<p>本地资料不足。确认问题不含个人信息后，勾选上方确认框并点击“搜索百度”。</p>':'');if(r.error)return `<p class="feature-error">${esc(r.error)}</p>`;return `<p>${esc(r.message)} · ${esc(r.retrieved_at||'')}</p><p>${esc(r.notice||'')}</p><div class="baidu-search-link">${link(r.url,'在百度打开此搜索')}</div>${(r.items||[]).map(x=>`<p>${link(x.url,x.title)}</p>`).join('')}`;}
async function run(fn){if(pending)return;pending=true;render();try{await fn();}catch(e){search={error:e.message};}finally{pending=false;render();}}
function open(){if(!window.BankSession)return;render();if(!dlg.open)dlg.showModal();run(async()=>{health=await BankSession.extensionRead('external/status');});}
const button=document.createElement('button');button.textContent='网站与免费 AI';button.onclick=open;document.getElementById('feature-launchers').append(button);
document.addEventListener('click',e=>{const b=e.target.closest('[data-research-query]');if(b){question=b.dataset.researchQuery;search=null;open();}});
window.addEventListener('bank-feature-open',e=>{if(e.detail.tab==='connections')open();});
})();
