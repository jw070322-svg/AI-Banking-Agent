const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../live_products/cards.js'),'utf8');
function render(context){const sandbox={window:{}};vm.createContext(sandbox);vm.runInContext(source,sandbox);return sandbox.window.BankProductQuotes(context);}
const cases=[];function test(name,fn){fn();cases.push(name);}
const etf={product_code:'510300.SH',product_name:'华泰柏瑞沪深300ETF',product_type:'exchange_traded',status:'priced',result_source:'同花顺场内分时',cache:{reused:false},
  final_data:{price:4.065,previous_close:4.111,change_1d:-0.0112,as_of:'2026-10-30T15:00:00+08:00',retrieved_at:'2026-10-30T16:00:01+08:00',official_name:'沪深300ETF华泰柏瑞',freshness:'交易所公开分时最新可用价；非交易时段为最近收盘，可能延迟',points:[{date:'2026-10-30T09:30:00+08:00',price:4.059},{date:'2026-10-30T15:00:00+08:00',price:4.065}]},
  steps:[{source:'同花顺场内分时',search_keywords:'场内ETF 510300.SH',status:'accepted',observation:'代码与名称匹配',decision:'价格不参与评分'}]};
const wealth={product_code:'GL24651.LC',product_name:'工银理财·天天鑫稳益固定收益类开放式理财产品(24GS5090)',product_type:'bank_wealth',status:'not_applicable',result_source:null,final_data:null,
  error:'银行理财无公开交易市场；如需核验请人工在中国理财网查询',verification_url:'https://xinxipilu.chinawealth.com.cn/queryMenu/prodType/prodTypeDetail?prodRegCode=24GS5090',cache:{reused:false},
  steps:[{source:'中国理财网信息披露（仅人工核验）',search_keywords:'x',status:'not_applicable',observation:'产品名含登记编码 24GS5090',decision:'不展示价格'}]};
const observations=[{code:'510300.SH',latest_nav:1.9623,as_of:'2026-10-27',basis_label:'复权单位净值',stale:false},
  {code:'GL24651.LC',latest_nav:1.0312,as_of:'2026-10-27',basis_label:'单位净值，分红口径未核验',stale:false}];
function context(extra){return Object.assign({product_quote_selection:[etf,wealth],product_quote_summary:{attempted:35,priced:14,not_applicable:21,unavailable:0,participates_in_scoring:false},
  product_quote_notice:'下表价格来自交易所公开行情，不是单位净值，不参与评分与排名。',product_observations:observations},extra||{});}

test('缺少产品行情字段时不渲染，保持原界面',()=>{assert.equal(render({}),'');assert.equal(render(null),'');});
test('ETF 价格与净值并列且精度不同',()=>{const html=render(context());assert.match(html,/4\.065/);assert.match(html,/1\.9623/);assert.ok(html.includes('不参与评分'));assert.ok(html.includes('评分用'));});
test('银行理财不给价格只给核验入口',()=>{const html=render(context());assert.ok(html.includes('无公开可核验行情'));assert.ok(html.includes('prodRegCode=24GS5090'));assert.ok(html.includes('rel="noopener noreferrer"'));assert.ok(!html.includes('0.000'));assert.ok(!html.includes('NaN'));assert.ok(!html.includes('undefined'));});
test('没有行情的产品不画价格走势图',()=>{const html=render(context());assert.equal((html.match(/<svg/g)||[]).length,1);});
test('远程名称被转义，不注入标记',()=>{const evil=JSON.parse(JSON.stringify(etf));evil.product_name='<script>alert(1)</script>';const html=render(context({product_quote_selection:[evil]}));assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));});
test('非 https 核验链接不渲染为链接',()=>{const bad=JSON.parse(JSON.stringify(wealth));bad.verification_url='javascript:alert(1)';const html=render(context({product_quote_selection:[bad]}));assert.ok(!html.includes('javascript:alert'));});
test('汇总计数与来源尝试过程可见',()=>{const html=render(context());assert.ok(html.includes('已尝试 35 项'));assert.ok(html.includes('查看来源尝试过程'));assert.ok(html.includes('复用60秒')===false);});
console.log(JSON.stringify({passed:cases.length,cases},null,2));
