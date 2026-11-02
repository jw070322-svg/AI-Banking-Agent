(function(global){
'use strict';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=n=>Number(n).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const labels={gain:'累计收益（元）',percent:'累计收益率（%）',value:'资产价值（元）'};
function chartModel(rows,{metric='gain',band=false}={}){
 if(!labels[metric])throw Error('未知曲线口径');
 if(!rows.length)return {empty:true};
 if(rows.some(r=>!['day','principal','investment_value','investment_gain','lower','upper'].every(k=>Number.isFinite(r[k]))))throw Error('曲线数据无效');
 if(rows[0].principal===0)return {empty:true};
 const value=(r,key)=>metric==='value'?r[key]/100:metric==='percent'?(r[key]-r.principal)/r.principal*100:(r[key]-r.principal)/100;
 const keys=band?['investment_value','lower','upper']:['investment_value'];
 const values=rows.flatMap(r=>keys.map(k=>value(r,k)));
 let min=Math.min(...values),max=Math.max(...values);
 if(metric!=='value'){min=Math.min(0,min);max=Math.max(0,max);}
 const padding=Math.max((max-min)*.12,metric==='percent'?.001:.01);min-=padding;max+=padding;
 const end=rows.at(-1).day||1,x=d=>80+610*d/end,y=v=>240-210*(v-min)/(max-min);
 const points=key=>rows.map(r=>({x:x(r.day),y:y(value(r,key)),day:r.day,value:value(r,key)}));
 return {empty:false,min,max,metric,band,x,y,points,main:points('investment_value'),ticks:Array.from({length:5},(_,i)=>min+(max-min)*i/4),label:labels[metric]};
}
function plot(rows,options){
 const m=chartModel(rows,options);if(m.empty)return '<div class="return-empty">尚未配置资金，累计收益为 ¥0.00。输入配置金额后更新预演。</div>';
 const pts=key=>m.points(key).map(p=>`${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
 const tick=v=>Math.abs(m.max-m.min)<.05?v.toFixed(3):number(v);
 const grid=m.ticks.map(v=>`<path d="M80 ${m.y(v)}H690" stroke="#e2e6ef"/><text x="70" y="${m.y(v)+4}" text-anchor="end">${tick(v)}</text>`).join('');
 const end=rows.at(-1).day;
 const dates=Array.from({length:5},(_,i)=>Math.round(end*i/4)).map(d=>`<text x="${m.x(d)}" y="265" text-anchor="middle">${d===0?'当前':d+'天'}</text>`).join('');
 return `<svg class="return-svg" viewBox="0 0 720 290" role="img" aria-label="${esc(m.label)}，按每日复利计算的假设曲线"><title>${esc(m.label)}；第 ${end} 天 ${number(m.main.at(-1).value)}；非真实净值或收益承诺</title><text x="80" y="16">${esc(m.label)}${m.metric==='value'?' · 纵轴局部放大':''}</text>${grid}${m.min<=0&&m.max>=0?`<path d="M80 ${m.y(0)}H690" stroke="#9aabc1" stroke-dasharray="3 4"/>`:''}${m.band?`<polygon points="${pts('upper')} ${m.points('lower').reverse().map(p=>`${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')}" fill="#dbdefc" opacity=".5"/><polyline points="${pts('lower')}" class="return-bound"/><polyline points="${pts('upper')}" class="return-bound"/>`:''}<polyline points="${pts('investment_value')}" class="return-main"/><line data-return-cursor x1="690" y1="30" x2="690" y2="240" stroke="#9485b9" stroke-dasharray="3 3"/><circle data-return-dot cx="690" cy="${m.main.at(-1).y}" r="4" fill="#5846b8"/>${dates}</svg>`;
}
function readout(row,band){
 if(!row)return '';
 const rate=row.principal?row.investment_gain/row.principal*100:0;
 return `<span><small>第 ${row.day} 个模拟日</small><b>${row.recovered?'已赎回情景':'持有情景'}</b></span><span><small>累计收益</small><b>¥${number(row.investment_gain/100)}</b></span><span><small>累计收益率</small><b>${rate.toFixed(4)}%</b></span><span><small>${row.recovered?'赎回金额':'资产价值'}</small><b>¥${number(row.investment_value/100)}</b></span>${band?`<span class="return-range"><small>下行 / 上行情景收益（非置信区间）</small><b>¥${number((row.lower-row.principal)/100)} / ¥${number((row.upper-row.principal)/100)}</b></span>`:''}`;
}
function render(rows){return `<section class="return-chart" aria-label="收益曲线"><div class="return-controls"><label>显示口径<select data-return-metric><option value="gain">累计收益</option><option value="percent">累计收益率</option><option value="value">资产价值</option></select></label><label class="return-band"><input type="checkbox" data-return-band>显示波动情景区间</label></div><p class="return-caption">每日计算 · 纵轴自动缩放 · 紫线为复利假设，参数变化后请点击“更新收益预演”。</p><div data-return-plot>${plot(rows,{metric:'gain',band:false})}</div><label class="return-scrubber">逐日查看<input type="range" data-return-day min="0" max="${Math.max(0,rows.length-1)}" step="1" value="${Math.max(0,rows.length-1)}" aria-label="查看第几个模拟日的收益"></label><output class="return-readout" data-return-readout aria-live="polite">${readout(rows.at(-1),false)}</output></section>`;}
function mount(root,rows){
 const host=root.querySelector('.return-chart');if(!host)return;
 const metric=host.querySelector('[data-return-metric]'),band=host.querySelector('[data-return-band]'),slider=host.querySelector('[data-return-day]'),box=host.querySelector('[data-return-plot]');
 const options=()=>({metric:metric.value,band:band.checked});
 const updatePoint=()=>{const i=Number(slider.value),m=chartModel(rows,options());host.querySelector('[data-return-readout]').innerHTML=readout(rows[i],band.checked);slider.setAttribute('aria-valuetext',`第 ${rows[i]?.day??0} 天`);if(m.empty)return;const p=m.main[i],line=box.querySelector('[data-return-cursor]'),dot=box.querySelector('[data-return-dot]');line.setAttribute('x1',p.x);line.setAttribute('x2',p.x);dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);};
 const redraw=()=>{box.innerHTML=plot(rows,options());updatePoint();};
 metric.onchange=redraw;band.onchange=redraw;slider.oninput=updatePoint;
 box.onpointermove=e=>{const svg=box.querySelector('svg');if(!svg)return;const bounds=svg.getBoundingClientRect(),x=(e.clientX-bounds.left)*720/bounds.width;slider.value=Math.round(Math.max(0,Math.min(1,(x-80)/610))*(rows.length-1));updatePoint();};
 updatePoint();
}
const api={chartModel,render,mount};if(typeof module!=='undefined'&&module.exports)module.exports=api;else global.ProjectionChart=api;
})(typeof window!=='undefined'?window:globalThis);
