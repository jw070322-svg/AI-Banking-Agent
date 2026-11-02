# 本轮整合说明

## 单一数据来源

web/index.html只加载journey-engine、backend-client、customer-language、customer-view、journey-workspace。旧同步XHR桥和旧JSON助手面板已移除，不加载local-store或旧contract-client。前端engine仅计算只读快照中的展示数据；所有变更经API提交给服务并重新读取快照。

backend-client使用异步fetch、HttpOnly会话cookie和每次变更独立幂等键。请求期间禁用操作，网络结果不明不重发；若快照也不可读，则阻止继续写入并提示刷新恢复。后端SQLite事务继续负责唯一账本与回执。

## 变更范围

- 保留原模块、知识库、场景生成器与API；以最新前端替换旧入口。
- journey-engine保留最新模板、卡片与统一状态，服务运行时保留验证断言；授权到期边界修正为到期即失效。
- journey-workspace异步化所有状态变更，复用现有面板承载分析、知识与推荐结果。
- customer-view对服务结果做显式字段投影、HTML转义和人类可读格式化，不直接展示未知JSON或工具日志。
- first_agent/developer新增服务端测试码与短时会话令牌，重置/恢复当前会话。模拟失败结果、推进日期等测试写操作要求开发者令牌。
- Python3.9兼容注解调整；启动器查找本机Node，不附带下载或自动安装。

## 边界

最新UI使用既有虚构联系人名册，原独立转账API仍保留其旧演示名册；两者共用资金状态，但不是现实联系人识别。结构化页面操作经RPC复用确定性引擎。原包独立分析、推荐和知识接口继续保留，未宣称接入生成式模型。

本地开发者码为演示防误操作，不能替代正式账户认证。浏览器会话cookie决定演示会话；不同浏览器或清cookie会得到另一个会话。未迁移旧HTML的localStorage。原始上传zip未修改。

## 验证

见reports/latest-integration-tests.json（116项）、latest-frontend-tests.json（66项）、latest-browser-verification.json和两张完整布局截图。原有历史报告不代表本轮新增检查。运行检查：python3 run_integration_checks.py；python3 run_frontend_checks.py。

## 1026转账解析合入

只移植intent_parser、recipients和服务端目录/草稿处理，未引入旧agent-panel或同步XHR桥。最新助手调用RPC assistant：转账采用1026解析和transfer_chat；其他输入清理未补齐槽位，再复用原interpret多场景导航与分析、知识路由。旧interpret接口保留兼容，最新UI不再用它提取转账草稿。

所有转账使用统一服务端名册，替代上文初次整合时两份名册的边界。只读快照中专用转账记录投影进统一任务页，不重复写账。确认前重新读取快照；错误更正后重新渲染，移除旧摘要与验证。开发者重置清理对话草稿。

新增8项统一助手检查覆盖槽位追问、更正失效、重复请求、服务重启、会话隔离与非转账导航；引入41项上游解析/业务回归。原始上传zip及上一版整合zip保留。

## 当前行为：收集字段再移交表单（替代上轮对话内生成预览）

RPC assistant改用assistant_fill，状态为assistant_transfer，不复用chat的clarification或直接创建transfer_ops。route=transfer-conversation代表继续补齐；route=transfer-form携带姓名、服务端名册ID、整数分金额与提示，前端自动打开现有transfer面板并填值。其余业务导航不变。保留原/api/chat和其解析回归作为兼容接口，不加载旧聊天面板。

服务端不把填表当授权；form propose才创建操作，后续verify/execute仍经过既有权限、卡限制和幂等规则。生成确认时绑定实际表单收款人与金额，使随后自然语言修改能让对应旧确认失效。取消/更正已提交操作不能回滚资金。重置清理assistant_transfer。

当前检查118项后端、66项前端；本轮浏览器证据fill-handoff-browser.json。之前continuous-dialog-browser.json属于上轮行为，仅作历史追溯。
