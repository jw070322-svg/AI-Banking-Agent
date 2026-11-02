# 1102.ver1 终版交接

先复核额度，读取外层打开说明.md、终版验收记录 reports/final-1102/ 及当前安全自评报告。源码、模型与模拟数据位于本目录，历史入口见 history_version/历史资料索引.md。以下保留早期工作记录。

# 1101.ver1 便携模型交接

先读 便携版使用说明.md 和 HANDOFF_1101_PORTABLE.md。额度任一可信窗口剩余 ≤15% 时暂停业务及 GitHub 写入。以下为继承的 1030 记录。

# 当前交接：1030.ver4 官方原文在线核验

先读 `HANDOFF_1030_ONLINE_VERIFY.json`（最新），再读 `HANDOFF_1030_LOCAL_AI_FIX.json`、`HANDOFF_1030_GUARDIAN_COMPLETE.json` 与 `HANDOFF_1030_PRODUCT_QUOTES.json`。
更早的暂停交接保留原文，仅作历史。

## 官方原文在线核验（最近一轮）

- 入口：`POST /api/knowledge` 带 `online_verify: true`（前端「网站与免费 AI」对话框第二个勾选框）。
- 只在本地无证据且本次显式同意时，抓该术语在知识库里声明的官方页面；不发送问题文本。
- 白名单：csrc.gov.cn / gov.cn / pbc.gov.cn / nfra.gov.cn / guiyang.pbc.gov.cn。AI 网页版只作跳转链接。
- 展示：原文摘录在前，`模型改写（非引用原文）`在后；改写不过校验就只给原文。
- 覆盖：52 条 CSRC 术语可核验；49 条人行术语来源是 PDF，返回 `source_unparseable` 并给链接。
- 证据冻结在 `runtime/online-evidence/`，不含问题原文。

## 上一轮：本地模型接入修复

## 本地千问模型（最近一轮）

- 根因：密钥按版本目录存放而模型服务共享（各版密钥互不相同、当前版没有）；8807 演示入口从不启动模型；启动失败被 DEVNULL 吞掉。
- 修复：共享密钥 `F:\AI_Banking\local-ai\local-model.key`；新增 `first_agent/local_ai_bootstrap.py`；8807/8806 启动前自动拉起；适配器用 `/lora-adapters` 实证；本地 401 显示为「密钥不匹配」。
- 排障入口：`python tools/diagnose_local_model.py`（就绪退出 0）。
- 适配器**质量未改善**：仍不得宣称金融问答准确。
- 模型服务需手动停止：PID 见 `F:\AI_Banking\local-ai\local-ai-status.json`。

## 上一轮：Guardian 接线修复

先读 `HANDOFF_1030_GUARDIAN_COMPLETE.json`（Guardian 轮）与 `HANDOFF_1030_PRODUCT_QUOTES.json`（业务侧）。
暂停交接 `HANDOFF_1030_GUARDIAN_PAUSED.json` 保留原文，仅作历史。

## 入口

- 演示启动器仍是 `启动产品行情版.bat` → http://127.0.0.1:8807/
- 本轮**未重启任何服务**；8804/8806/8807 当前都无监听进程

## 本轮做了什么

1. **修接口**：`ExistingComplianceGuardAdapter` 默认扫描器改用 `CompatibleScanner`，`evaluate` 增加能力回退；`injection.py` 同类缺陷一并修掉。修复前是 `AttributeError`，修复后注入正文与注入参数都能拦。
2. **加验证闸门**：新增 `first_agent/vendor/eva/security/verification.py`。13 项检查全通过才签发含源码哈希的票；`verified=True` 单独传**不生效**，改代码票即作废。组装入口是 `build_verified_runtime()`，默认 `build_runtime()` 行为未变。
3. **建证据桥**：`WebApprovalEvidenceBridge` 只读网页已有 state，校验状态/版本/过期/绑定后签发证据；`RiskAuthorizationRegistry` 增加单条与会话级撤权、策略版本校验。
4. **补归档**：`history_version/from_previous_versions/` 收录 1025.ver1 交接包与 1026/1027 各版交接修订版，共 11 个文件，逐份哈希一致。
5. **核接口**：内部路由与契约双向差集均为 0；外部端点实测 5 个可用，无需升级；指数链 5 个中 4 个走同花顺，931186.CSI 回退本地快照。

## 当前状态（复验值）

| 项目 | 结果 |
|---|---|
| Guardian 专项 | 38 通过 |
| 后端集成 | 240 通过 / 0 失败 / 0 错误 |
| 复核链 | 57 通过 |
| 前端 | 92 通过 |
| 模块自检 | 36 通过 |
| 变更台账 | 新增 71 / 改动 15 / 缺失 0 / 未证实 0 |
| 迁移台账 | 迁移 36 / 未证实 0 |

## 边界（不要越过）

- 网页请求仍未经过 `HardenedToolGateway`；不得表述为「网页已全部走新网关」。
- `build_runtime()` 默认仍是 `Unconfigured*` 适配器，R4 转账继续失败关闭。
- 证据注册表是进程内内存，不是持久账本，也不等于真实资金「恰好一次」。
- 人工业务评分、生产认证、真实银行与本地模型验收仍未完成。

## 接续步骤

1. 复核额度（任一可信窗口 ≤15% 时只写交接与审计后暂停）。
2. `python -X utf8 -m first_agent.vendor.eva.security.verification` 复跑验证闸门。
3. `python run_integration_checks.py`、`run_review_checks.py`、`run_frontend_checks.py`。
4. 改动受基线约束的文件后，在 `tools/build_version_ledger.py` 的 `REASONS` 与 `tools/build_relocation_ledger.py` 的 `INTENTIONAL_EDITS` 登记，再重跑两条台账，确认未证实为 0。

历史材料与旧交接在 `history_version/`；历史基线 JSON 一律只读。
