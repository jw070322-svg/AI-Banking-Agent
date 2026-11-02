# 首次 Agent 总版总结

## 集成依据与版本选择

递归盘点 Teammate_output，实际包含 77 个非缓存/非 Mac 元数据文件（ZIP 内另行核对）；四个分支中三个有内容，Ethan 为空。原始目录保持原样。

eva 采用 1020/ver.2；ver.1 仅补回新版缺失的 scanner。vv 采用 1021，最新独立 HTML 与包内两段脚本及非字体样式一致。YUKI 采用 1022 的源码、八篇知识及评测材料。源文件时间、大小、SHA-256 见 reports/source_inventory.json。ZIP 复核额外恢复 YUKI 三篇知识与一份说明，详情见 reports/yuki-archive-recovery.json。

空编排器及残缺包不能直接作为首版运行，因此新增明确的集成实现，并从已有推荐、RAG、安全工具包补齐可运行链路。

## 架构与接口

vv 界面 → 同源 HTTP 兼容层/对话 → AgentService → SQLite 事务 → Node 业务引擎 + eva 校验/认证契约 + 推荐规则 + BM25 RAG

所有业务共享 vv 整数分账本；eva 只复用校验与数据契约，推荐使用同一目录与资金/期限约束；RAG 使用 YUKI 最新八篇原文与项目可追溯检索补丁。

接口结构、权限、状态和单位见 API-CONTRACT.md；实际状态与幂等返回、累计和审计在同一个 SQLite 事务提交。预览绑定操作与版本，300 秒过期；模拟增强断言绑定本次预览，120 秒有效且一次消费。

## 补丁来源与作用

- P01：Orchestrator/agent_orchestrator.py 为 0 字节；eva 编排缺少 brain/stages/risk 等关键依赖。处理：无法把残缺包宣称为可运行交付；依据其阶段设计新增规则路由、缺参澄清、查询依赖、金融预览及回执状态机，已交付的 data/tools/models 保留为真实校验依赖。 来源：Orchestrator/agent_orchestrator.py、Teammate_output/eva output/1020/ver.2/orchestrator.py、Teammate_output/eva output/1020/ver.2/models(3).py。

- P02：Ethan output 为空，推荐模块尚无包级接入，且金额单位为元。处理：复用项目协作代码补齐实际推荐能力，修正包内相对导入；仅适配层把分转换为元，同步 vv 目录、配置金额、风险和到期结算约束。Ethan 原角色不能从空目录确认，此为暂定交接归属。 来源：financial_recommendation_module/matching_core.py、financial_recommendation_module/rule_driven.py、financial_recommendation_module/data_driven.py。

- P03：vv 原版账本只在浏览器内存中，刷新丢失，与 eva 虚构初值不同。处理：最新独立 HTML 与包内脚本及非字体 CSS 一致，采用可维护源码布局。引擎在服务端逐事务运行，SQLite 保存唯一状态；新增转账助手、真实接通本地 API，更新刷新与能力文案。 来源：Teammate_output/vv output/1021/Banking 统一版(2).html、Teammate_output/vv output/1021/Banking-统一版源码(1)/banking-agent/dist/journey-engine.js。

- P04：eva ver.2 未交付 scanner；旧 scanner 对自由文本密码、数字 PII 和哈希的处理不足。处理：明确标记从旧版本补回缺失 scanner，再在外层修复脱敏；使用 toolkit 默认拒绝 scope/resource gate。复用认证断言数据契约，但在持久化状态内验证绑定、过期及一次性消费，与扣账同事务；未调用旧 consume 接口冒充完整授权。 来源：Teammate_output/eva output/1020/ver.1/compliance(1).py、risk_security_toolkit/risk_scaffold/modules/security.py、Teammate_output/eva output/1020/ver.2/auth.py。

- P05：YUKI simple_RAG 对无关文档也加分，中文长句分词弱，来源仅文件名；文件名乱码。处理：保留八份最新知识原文及原始字节哈希，以正文标题修复运行副本文件名；复用项目 BM25、中文双字分词、哈希与行号引用，对无关问题拒答，个人业务查询由 Agent 工具处理。未把教育资料称作权威银行规则。 来源：Teammate_output/YUKI ouput/1022/AI-Banking-agent.zip、Teammate_output/YUKI ouput/1022/AI-Banking-agent/AI-Banking-agent/src/RAG/simple_RAG.py、Teammate_output/YUKI ouput/1022/AI-Banking-agent/AI-Banking-agent/data/knowledge、RAG/banking_rag。

- P06：多个接口无统一单位、幂等、期限或错误状态，跨语言预览哈希存在整数/浮点差异。处理：边界使用整数分和固定响应外壳；预览绑定客户、会话、操作、金额、版本、策略、整数秒过期时间。相同幂等键同请求返回原回执；未知结果阻断再执行，所有状态更改与审计原子提交。 来源：Teammate_output/vv output/1021/Banking-统一版源码(1)/banking-agent/API-CONTRACT.md、Teammate_output/eva output/1020/ver.2/policy_config.json、financial_recommendation_module/matching_core.py。

## 验证与额度

{
  "verified_at": "2026-10-22T09:19:02.078870+00:00",
  "integration": {
    "run": 20,
    "passed": 20,
    "failures": [],
    "errors": [],
    "skipped": []
  },
  "vv_engine": {
    "passed": 15,
    "cases": [
      "账单分类合计与总账一致",
      "权限按查询订阅交易分开",
      "订阅取消只减少未来支出，不能重复取消",
      "关闭确认不执行，申购需验证，不能重复提交",
      "目标、产品、预算、档案或授权变化使确认失效",
      "筛选引擎处理风险期限金额与缺失资料",
      "失败不会改动账本，未知结果冻结并查询一次",
      "赎回申请不提前到账，次日查询后守恒",
      "到账失败释放占用，未知赎回核对后仍须等到账",
      "未到期不能赎回，占用资金不能重复赎回",
      "中断撤销不回滚资金，恢复仍须重新确认",
      "连续失败与验证错误锁定，解锁不清账",
      "保持流动性不申购，预演无虚构收益",
      "无效金额、期限和超配被拒绝",
      "快照不能绕过内部规则，输入仅作记录不自动执行"
    ]
  },
  "conclusion": "passed"
}

浏览器已验证：明确确认 800 元模拟转账后，余额 ¥38,640 → ¥37,840；总资产 ¥128,640 → ¥127,840；账单增加 800 元支出；刷新保留。知识问答显示 YUKI 原文引用与行号。

额度最新采样：{"observed_at_utc": "2026-10-22 12:30:11 UTC", "stage": "branch_documentation_verification", "windows": [{"id": "codex", "window": "primary", "window_duration_mins": 300, "remaining_percent": 59, "resets_at": 1792689323}], "monitor_window_minutes": 300, "ignore_weekly": true, "threshold_percent": 10, "stop": false, "monitor_status": "observed"}。当前仅检查 5h 窗口；此前周额度中止记录保留在上下文历史中。此处业务验证结果沿用原报告，本次仅完成文档与生成器核对。

## 各分支交接

### eva / 风控与业务工具

复用 ver.2 的 data、tools、models、policy_config 与认证断言契约；从 ver.1 补缺失 scanner 并外层修复脱敏。完整接入权限、预览失效、累计分级和事务内断言校验。

交接文件：reports/branches/eva.md。

后续：交付完整同版本 bank_agent 包及原版测试，关闭原缺失依赖清单；维护模拟银行 API、模拟认证与可替换接口契约；真实银行由组委会接入；卡管理：参考真实银行 APP 的模式补充后端 API、持久状态与前端从卡库选择卡的闭环；当前尚未实现；继续维护风险政策与控制矩阵证据。

### vv / 前端与业务交互

采用 1021 最新 HTML 对应的同一版脚本和样式；保留四主导航、订阅、预演、申赎，换成服务端状态适配器，并加入转账与知识对话面板。刷新保留账本，页面能力说明已更新。

交接文件：reports/branches/vv.md。

后续：把兼容同步 XHR 改为异步视图数据加载，避免主线程等待；将转账记录正式并入任务主导航，而非仅助手面板；继续完善窄屏、无障碍及高延迟状态；当前未宣称完成全尺寸视觉回归。

### YUKI / 知识与评测

纳入 1022 的八份知识文档及参考源码、评测题库；标题修复运行文件名，换用项目现有 BM25 与可追溯引用，无证据时拒答，资料不触发工具执行。

交接文件：reports/branches/YUKI.md。

后续：补充资料的审核人、适用期、权威来源与定期复核流程；将 20 正常、20 边界、10 风险题转成带标注的自动评分集；当前没有声称 50 题全数通过；现金流、储蓄率、流动性已从最新 ZIP 恢复并入库；新增主题须提供可审查来源。

### Ethan / 空交付补位（原分工待确认）

指定目录为空，不能选出最新交付。暂以现有 financial_recommendation_module 为产品匹配补丁来源，新增包内导入和统一金额/目录/期限适配；此名称不代表已核实 Ethan 原本负责推荐。

交接文件：reports/branches/Ethan.md。

后续：补交原职责及最新完整 output、测试、依赖说明和接口契约；确认推荐/计算职责是否归本分支，再接收补位模块；如接入真实产品，提供条款、费用、风险及数据有效性来源；本次仅虚构目录。

### 集成 / 编排与交付

新增可运行的本地 HTTP Agent、SQLite 状态/幂等/审计、规则意图与多轮澄清，统一接入四方资产并生成总版及分支文档。

交接文件：reports/branches/integration.md。

后续：如需开放式自然语言理解，再接入模型 provider 并保持确定性执行边界；维护模拟 API 和接入契约，真实银行由组委会本地部署接入；后续卡管理对接由后端主责、集成负责编排安全；当前模拟会话与本地审计的适用范围须明确。

## 遗留问题与运行方式

- 当前交付规则驱动的本地模拟银行 API 与统一契约；真实银行由组委会收到作品后本地部署接入，不列为团队欠交项。没有接入开放式模型或真实 MFA。

- 身份是服务端创建的演示会话，每个会话有独立虚构账本；不是手机银行真实登录系统。

- 卡申请/挂失、手机号/定时/AA 转账、自动订阅识别与提醒、生日商户联动仍为后续需求，不计入已实现功能。

- 同期原 eva 完整测试无法直接复跑；本报告只统计新的集成测试及 vv 兼容规则检查，不沿用 42 项通过声明。

- 同步页面适配会阻塞主线程，适用于本机演示；未完成所有屏幕尺寸视觉验收。

- SQLite 本地事务不等于分布式银行原子事务，普通本地审计不具备生产防篡改保证。

- 额度工具提供即时快照，没有推送订阅；按用户最新要求只检查 windowDurationMins=300 的 5 小时窗口，剩余严格低于 10% 才存档停止。周额度不参与停止条件；未知额度不等于零。

在本目录运行 `python -m first_agent.server --port 8765`，访问 http://127.0.0.1:8765/ 。验证运行 `python verify_delivery.py`。来源快照在 sources/，原件在 Teammate_output，实际运行代码在 first_agent/ 与 web/。

结论：已形成可运行、可追溯、同账本、可复测的首次本地模拟 Agent，并完成总版和各分支交接。
