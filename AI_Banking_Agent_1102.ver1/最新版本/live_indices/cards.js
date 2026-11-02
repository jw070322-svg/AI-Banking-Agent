/* Public index cards; all external strings are escaped and no webpage scripts run. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const pct = value => Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : '未提供';
  function chart(data) {
    const points = (data.points || []).filter(p => Number.isFinite(p.close));
    if (points.length < 2) return '<p>该来源未提供可核验走势。</p>';
    const values = points.map(p => p.close), min = Math.min(...values), max = Math.max(...values);
    const title = data.series_kind === 'intraday' ? '官网当日分时走势' : '本地最近60个观察日走势';
    const coordinates = values.map((v, i) => `${(4 + 252 * i / (values.length - 1)).toFixed(2)},${(64 - 58 * (v-min)/(max-min || 1)).toFixed(2)}`).join(' ');
    return `<svg viewBox="0 0 260 70" role="img" aria-label="${title}"><polyline fill="none" stroke="#6c64d4" stroke-width="2" points="${coordinates}"/></svg><small>${title}<br>${esc(points[0].date)} — ${esc(points.at(-1).date)}</small>`;
  }
  window.BankIndexCards = context => {
    const records = context?.index_selection || [];
    if (!records.length) return '<div class="index-grid"><p>尚未取得本轮官方来源检查结果。</p></div>';
    return `<p role="note">${esc(context.index_notice)}</p>${context.index_audit_warning ? `<p role="alert">${esc(context.index_audit_warning)}</p>` : ''}<div class="index-grid">${records.map(row => {
      const data = row.final_data;
      const trace = (row.steps || []).map(s => `<li><b>${esc(s.source)}</b>：${esc(s.search_keywords || '')}<br>${esc(s.observation)}；${esc(s.decision)}</li>`).join('');
      return `<article style="min-width:0;overflow-wrap:anywhere"><small>${esc(row.index_code)}</small><h3>${esc(row.index_name)}</h3>${data ? `<b>${data.close.toFixed(2)}</b><p>单日 ${pct(data.change_1d)}${data.series_kind === 'daily' ? ` / 20个观察日 ${pct(data.change_20d)}` : ''}</p>${chart(data)}<p><strong>${esc(row.result_source)}</strong><br>${esc(data.freshness)}${data.stale ? '（已过时）' : ''}<br>报价时间：${esc(data.as_of)}<br>抓取/读取时间：${esc(data.retrieved_at)}</p>` : `<p>${esc(row.error || '指数数据暂不可用')}</p>`}<details><summary>查看来源尝试过程</summary><ol>${trace}</ol><p>${row.cache?.reused ? '复用60秒内的完整检查；抓取时间保持原值。' : '本轮已执行来源检查。'}</p></details></article>`;
    }).join('')}</div>`;
  };
})();
