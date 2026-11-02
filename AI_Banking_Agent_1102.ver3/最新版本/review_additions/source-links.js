(function(global){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function links(value){
    const citations=(value?.results||[]).filter(r=>r.tool==='knowledge').flatMap(r=>r.result?.citations||[]);
    const safe=citations.filter(c=>typeof c.citation_uri==='string' && /^\/review\/source\/[a-zA-Z0-9_-]+#L\d+$/.test(c.citation_uri));
    return safe.length?'<section class="agent-result-card"><h4>核对引用原文</h4>'+safe.map(c=>'<p><a data-review-source href="'+esc(c.citation_uri)+'" target="_blank" rel="noopener noreferrer">'+esc(c.title)+' · 第 '+esc(c.start_line)+' 行</a></p>').join('')+'</section>':'';
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={links};return;}
  function install(){
    const view=global.BankCustomerView;if(!view||view.reviewLinksInstalled)return;
    const original=view.render;view.render=value=>original(value)+links(value);view.reviewLinksInstalled=true;
  }
  install();global.addEventListener('bank-ready',install);
})(globalThis);
