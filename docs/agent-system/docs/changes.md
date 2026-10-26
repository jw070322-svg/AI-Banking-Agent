# 2026-10-27 变更记录：系统提示词与结构化契约

本次为新增文档包，发布到仓库功能分支 `docs/banking-agent-system-20261027` 的 `docs/agent-system/` 目录。既有应用代码没有在本次文档提交中改造。

| 文件组 | 修改前 | 修改后 | 验证 |
|---|---|---|---|
| prompts/banking_environment_system.md | 无此系统提示词 | 14节可加载指令，涵盖全部需求及公开决策摘要 | 文档审阅 |
| contracts/wind_agent_guide.json | 无机器可读任务书 | 五类产品、五表字段、溯源和质量规则 | 严格JSON与单位契约检查 |
| contracts/integration_contract.json、tool_schemas.json | 无本包扩展契约 | 数据门面、RAG、安全、生活服务、额度及八字段日志约定 | JSON解析、核心字段核对；完整Schema元验证待执行 |
| contracts/behavior_evaluations.json | 无本包模型评测规范 | 30个输入/工具状态/预期行为用例 | 仅规范检查，模型评测未执行 |
| examples/ | 无本次样本 | API生成的R1–R5摘要及知识回退/交接格式 | 来源哈希、账户对账、金额和评测字段隔离 |
| reports/raw-environment-responses/ | 无本次原始证据 | 五次生成API的合成响应，含评测参考字段 | 仅审计/离线校验；禁止作为线上客户视图或待测输入 |
| tools/ | 无复现与校验入口 | HTTP采集与文档包验证脚本 | 实际运行通过 |
| development_log.jsonl | 无本包日志 | 八字段开发记录 | 顶层字段集合严格核对 |
| README.md、docs/material_manifest.json | 无本包入口与材料清单 | 使用说明、已验证/待接入状态、输入附件哈希 | 来源与路径核对 |

逐文件的修改前/后SHA-256见 reports/change_manifest.json；新文件的before_sha256为null。完整新增内容见GitHub提交diff，发布结果另存本地reports/repository-delivery.json。

本次实际通过的是5份环境API样本及10项包验证；1026.ver2的335项历史测试不是本次文档包或远端CI的测试计数。完整读取门面、真实第三方连接和模型行为评测仍需后续接入。

最新额度规则：remaining<=15%时暂停业务，仅保存交接和审计。根目录AGENTS.md及本地交接已同步该新约定。
