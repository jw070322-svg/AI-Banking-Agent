// 官方原文核验卡片：摘录在前、改写标注、转义与状态文案。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'customer-view.js'), 'utf8');
const ctx = { module: { exports: {} }, globalThis: {} };
vm.createContext(ctx);
vm.runInContext(source, ctx);
const view = ctx.module.exports;

const cases = [];
function test(name, fn) { fn(); cases.push(name); }

const VERIFIED = {
  status: 'verified',
  answer: '以下为官方原文摘录，未经改写；请以原文为准。',
  term: '基金',
  citations: [{
    citation_id: 'S1',
    title: '《基金投资者教育手册》',
    source_uri: 'https://www.csrc.gov.cn/xizang/c105485/c1304209/content.shtml',
    excerpt: '基金投资者即基金份额持有人，是基金的出资人。',
    publisher: '西藏证监局',
    published_at: '2009-05-07',
    fetched_at: '2026-10-31T00:40:00+08:00',
    document_sha256: 'a'.repeat(64),
    kind: 'official_web',
  }],
  rewrite: { status: 'ok', text: '基金投资者是基金的出资人。', label: '模型改写（非引用原文）' },
};

function html(result) { return view.render({ results: [{ tool: 'knowledge', result }] }); }

test('verified card is titled as official-source verification', () => {
  const out = html(VERIFIED);
  assert.match(out, /官方原文核验/);
  assert.doesNotMatch(out, /AI 补充解释/);
});

test('excerpt is shown before the rewrite', () => {
  const out = html(VERIFIED);
  assert.ok(out.indexOf('官方原文摘录') < out.indexOf('模型改写'));
  assert.match(out, /基金投资者即基金份额持有人/);
});

test('rewrite is labelled as not a quote', () => {
  assert.match(html(VERIFIED), /模型改写（非引用原文）/);
});

test('source metadata is rendered', () => {
  const out = html(VERIFIED);
  assert.match(out, /西藏证监局/);
  assert.match(out, /2009-05-07/);
});

test('excerpt with markup is escaped, not injected', () => {
  const hostile = {
    ...VERIFIED,
    citations: [{ ...VERIFIED.citations[0], excerpt: '<img src=x onerror=alert(1)>基金定义' }],
  };
  const out = html(hostile);
  assert.doesNotMatch(out, /<img/);
  assert.match(out, /&lt;img/);
});

test('non-https source is not turned into a link', () => {
  const hostile = { ...VERIFIED, citations: [{ ...VERIFIED.citations[0], source_uri: 'javascript:alert(1)' }] };
  assert.doesNotMatch(html(hostile), /href="javascript:/);
});

test('missing rewrite shows the model-unavailable line', () => {
  const out = html({ ...VERIFIED, rewrite: { status: 'unavailable', label: '模型改写（非引用原文）' } });
  assert.match(out, /本地模型未响应/);
});

test('unparseable source keeps an honest card without an excerpt', () => {
  const out = html({ status: 'needs_evidence', answer: '知识库没有足够依据。', citations: [], public_query: '现金流是什么意思' });
  assert.doesNotMatch(out, /官方原文摘录/);
  assert.match(out, /知识解答/);
});

console.log(JSON.stringify({ passed: cases.length, cases }, null, 2));
