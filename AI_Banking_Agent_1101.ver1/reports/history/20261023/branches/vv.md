# vv / 页面交互与卡管理前端：本轮代码修改与交接

## 判断依据

1023 单页 HTML 修改时间更晚，但源码 ZIP 包含单页缺少的契约修复。新版卡片 UI 可以复用；local-store 与 contract-client 若直接载入，会与现有服务端状态发生冲突。

## 本轮逐项修改（2026-10-23）

| 文件 | 实际改动及目的 |
|---|---|
| `web/journey-engine.js` | 以 1023 ZIP 补齐最新单页缺少的 trade 权限映射、300 秒预览、120 秒验证、累计 1000 元分级和锁定加结算规则；新增 options.preserveVerification 仅供可信服务端恢复。 |
| `web/journey-engine.js` | 保留新版 cards、contacts、externalOut 和 settleCard；授权到期边界改为 >=。开卡须次日查询审核，开卡和额度调整不增加资金，挂失不可解锁。 |
| `web/journey-workspace.js` | 接入新版卡选择、转账、任务记录及卡管理交互；移除对 BankGateway/BankLocal 的运行依赖，使用现有 BankCore；页面文案改为服务端模拟保存及已连接模拟 API。 |
| `web/journey-workspace.css` | 采用新版配套样式，支持卡管理和更新的转账布局。 |
| `web/server-bridge.js` | 暴露 settleCard；导出当前服务端公开快照；不写浏览器 localStorage，不运行客户端账本。 |
| `web/agent-panel.js` | 新增独立测试场景生成按钮，调用 /api/scenarios/generate；保留聊天澄清、旧转账及带证据问答。 |
| `first_agent/engine_worker.cjs` | 使用 Python 传入的时钟及 preserveVerification:true，让相邻 HTTP 请求共享已验证状态，继续执行服务端 120 秒期限检查。 |
| `tests/vv_simulation.cjs` | 引入交付中的 15 项转账/卡管理/恢复/资金守恒测试，路径改为当前 web。 |
| `tests/vv_contract_rules.cjs` | 引入交付中的 5 项授权、300/120 秒边界和累计分级测试；原 vv_core 15 项保留。 |

## 首轮保留内容与详细历史

首轮的 server-bridge、Agent 面板、统一服务端状态和本地字体继续保留。浏览器验收覆盖卡限制完成及刷新、RAG、场景入口；不宣称全尺寸视觉回归已完成。

[首轮逐项变更记录](../history/20261022/branches/vv.md)。历史中的“卡管理未实现”“Ethan 空交付”为当时状态，本轮以上文为准。

## 本轮完整代码差异

- `first_agent/engine_worker.cjs`：[完整补丁](../diffs/first_agent__engine_worker.cjs.diff)，SHA-256 `42d89fb173d447d47fed1e54139567e12636c201c5a1654b234df23a49e5f6f3`。

- `tests/vv_contract_rules.cjs`：[完整补丁](../diffs/tests__vv_contract_rules.cjs.diff)，SHA-256 `5d4c830ee5195b692dce2c751f984a3b0af3c491ed3cb425ee8f3f062e721588`。

- `tests/vv_simulation.cjs`：[完整补丁](../diffs/tests__vv_simulation.cjs.diff)，SHA-256 `60c467baad792ff84111a94cf5d4166b9160a423e3b59b63aa1c2c2792b76922`。

- `web/agent-panel.js`：[完整补丁](../diffs/web__agent-panel.js.diff)，SHA-256 `29e570639e3cba2a586f092104d2b5ba392b68da082fae9e15caf837b6af95d8`。

- `web/journey-engine.js`：[完整补丁](../diffs/web__journey-engine.js.diff)，SHA-256 `27e2c29ab3a79965a5e2069f47b21b1837482d5f2352d1070acdf161317b1ff4`。

- `web/journey-workspace.css`：[完整补丁](../diffs/web__journey-workspace.css.diff)，SHA-256 `dd232b8baadcbbbb78e938f757c07978903cd3e9c3cad34dfe2a73ebefd926d0`。

- `web/journey-workspace.js`：[完整补丁](../diffs/web__journey-workspace.js.diff)，SHA-256 `2e33c63a1c5869e2b6114a592f0ff5597c75280c1134b1fc4ac8121e0d2a1caf`。

- `web/server-bridge.js`：[完整补丁](../diffs/web__server-bridge.js.diff)，SHA-256 `554291f5d7ed4526967345c9c5bbccfcf08cabb07232bd65ac874869c15de4fd`。

## 验证与责任边界

总包实测：32/32 Python 集成检查，35/35 JS 检查；详见 [验证报告](../verification.json)。此结果不等于各队友原版测试全部通过。

卡管理分工：eva 主责后端模拟接口、卡状态与风控；vv 主责卡片库选择与确认交互；集成负责状态/安全/回执串联；Ethan 提供场景测试数据；YUKI 提供知识及评测资料。

## 后续协作

- 将兼容同步 XHR 改为异步加载并设计等待/失败状态。

- 继续完成窄屏、键盘及屏幕阅读器验收。

- 旧聊天名册与新页面 contacts 使用不同虚构联系人集合，后续可统一目录服务；当前都执行共同账本与限制。

结论：升级到 1023 的转账、卡管理、任务与记录界面，沿用同源 BankCore 服务端桥接，卡申请/限额/限制/解锁/挂失均进入确认与回执流程。
