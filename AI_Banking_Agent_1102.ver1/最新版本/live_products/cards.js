/* Exchange-traded prices beside scoring NAV; all external strings escaped, no page scripts run. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const pct = value => Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : '未提供';
  const TYPE = {exchange_traded: '场内ETF', open_end_fund: '场外基金', bank_wealth: '银行理财'};
  // 继承样式没有给 .feature-table 里的 small 设显示方式，这里显式设成块级，避免数字与日期挤在一行。
  const note = html => `<small style="display:block;color:#7e8799">${html}</small>`;
  function chart(data) {
    const points = (data.points || []).filter(p => Number.isFinite(p.price));
    if (points.length < 2) return note('该来源未提供可核验分时走势。');
    const values = points.map(p => p.price), min = Math.min(...values), max = Math.max(...values);
    const coordinates = values.map((v, i) => `${(4 + 252 * i / (values.length - 1)).toFixed(2)},${(64 - 58 * (v-min)/(max-min || 1)).toFixed(2)}`).join(' ');
    return `<svg viewBox="0 0 260 70" role="img" aria-label="同花顺当日分时走势"><polyline fill="none" stroke="#6c64d4" stroke-width="2" points="${coordinates}"/></svg>${note(`同花顺当日分时 ${esc(points[0].date)} — ${esc(points.at(-1).date)}`)}`;
  }
  function navCell(observation) {
    if (!observation) return note('本地快照无该产品净值');
    return `${observation.latest_nav.toFixed(4)}${note(`${esc(observation.as_of)} ${observation.stale ? '（过时）' : ''}<br>${esc(observation.basis_label)}`)}`;
  }
  function priceCell(row) {
    const data = row.final_data;
    if (!data) {
      const link = row.verification_url && /^https:\/\//.test(row.verification_url)
        ? `<br><a href="${esc(row.verification_url)}" target="_blank" rel="noopener noreferrer">人工核验入口</a>` : '';
      return `<b>无公开可核验行情</b>${note(`${esc(row.error || '该产品没有公开交易行情')}${link}`)}`;
    }
    return `<b>${data.price.toFixed(3)}</b>${note(`单日 ${pct(data.change_1d)}<br>价格时间 ${esc(data.as_of)}<br>${esc(data.freshness)}`)}${chart(data)}`;
  }
  window.BankProductQuotes = context => {
    if (!context || !('product_quote_selection' in context)) return '';
    const records = context.product_quote_selection || [];
    const summary = context.product_quote_summary;
    const navByCode = new Map((context.product_observations || []).map(item => [item.code, item]));
    const alert = context.product_quote_error || context.product_quote_audit_warning;
    if (!records.length) {
      return `<h3>金融产品实时行情</h3><p role="alert">${esc(alert || '本轮没有取得产品行情结果。')}</p>`;
    }
    const head = `<h3>金融产品实时行情（公开来源，可能延迟）</h3>
      <p role="note">${esc(context.product_quote_notice)}</p>
      ${alert ? `<p role="alert">${esc(alert)}</p>` : ''}
      ${summary ? `<p>已尝试 ${summary.attempted} 项：${summary.priced} 项取得场内公开价格，${summary.not_applicable} 项无公开交易行情，${summary.unavailable} 项来源暂不可用。</p>` : ''}`;
    const rows = records.map(row => {
      const data = row.final_data;
      const trace = (row.steps || []).map(s => `<li><b>${esc(s.source)}</b>：${esc(s.search_keywords || '')}<br>${esc(s.status)}；${esc(s.observation)}；${esc(s.decision)}</li>`).join('');
      const source = data
        ? `<strong>${esc(row.result_source)}</strong><br>抓取时间：${esc(data.retrieved_at)}${data.official_name ? `<br>官方名称：${esc(data.official_name)}` : ''}`
        : esc(row.error || '无公开行情');
      return `<tr><td>${esc(row.product_name)}${note(esc(row.product_code))}</td>
        <td>${esc(TYPE[row.product_type] || row.product_type || '')}</td>
        <td>${priceCell(row)}</td>
        <td>${navCell(navByCode.get(row.product_code))}</td>
        <td>${note(source)}<details><summary>查看来源尝试过程</summary><ol>${trace}</ol><p>${row.cache?.reused ? '复用60秒内的完整检查；抓取时间保持原值。' : '本轮已执行来源检查。'}</p></details></td></tr>`;
    }).join('');
    // 继承样式给 .feature-table 表格设了 nowrap；产品名列很长，这里按单元格换行。
    return `${head}<div class="feature-table" style="overflow:auto;max-width:100%"><table style="white-space:normal"><thead><tr>
      <th>产品与代码</th><th>类型</th>
      <th>场内最新价格（公开行情，不参与评分）</th>
      <th>最近净值（评分用，口径见行内）</th>
      <th>来源与状态</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  };
})();
