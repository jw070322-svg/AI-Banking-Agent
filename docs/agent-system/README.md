# AI Banking Agent 系统提示词与契约包 · 1027.ver1

本版本交付可直接加载的系统提示词、接口设计和通过真实本机HTTP调用得到的合成档案。银行演示应用仍位于相邻 `AI_Banking_Agent_1026.ver2`；本目录是独立提示词/契约包，未复制或升级该应用运行代码。

## 使用入口

- [系统提示词](prompts/banking_environment_system.md)：14节中文指令，覆盖档案生成、API数据门面、知识回退、个性化预算、Wind研究、附件、风控、日志、GitHub和额度暂停。
- [Wind Agent JSON任务书](contracts/wind_agent_guide.json)：可交给账号内实际可用的Wind官方Agent/终端助手；包括5类优先理财、5张标准表、数据口径、字段核验、质量及交付要求。它是项目交换规范，字段映射需由Wind字典验证。
- [统一接入契约](contracts/integration_contract.json)与[JSON Schemas](contracts/tool_schemas.json)：区分现有API和预留能力，规定RAG、安全、生活服务与Provider替换条件。
- [五份档案汇总](examples/dossiers.json)：R1→A、R2→C、R3→D、R4→E、R5→F。每份也有独立JSON；R1–R5是档案编号。API未提供风险测评，均保持null。
- [API验收记录](reports/dossier-api-verification.json)：五份HTTP请求、账户对账与幂等重放已实际通过；原始响应在 reports/raw-environment-responses，仅为合成证据，含评测字段，禁止注入线上待测Agent。
- [30项行为验收规范](contracts/behavior_evaluations.json)：覆盖检索失败、越权、预算、未来数据、Provider切换和15%额度边界。这些为待运行的模型评测用例，不计作已通过测试。
- [知识回退示例](examples/knowledge_fallback.json)、[交接模板](examples/handoff.template.json)、[变更记录](docs/changes.md)、[创作日志](development_log.jsonl)。

## 加载方式

读取系统提示词文本作为宿主的system/developer指令；将运行时上下文、附件引用、用户请求和真实工具注册表作为独立输入传入。固定规则与不可信材料分别加载。宿主必须注册工具并执行服务端授权、验证和状态写入，不能靠提示词创建接口或安全网关。

本设计按 [OpenAI Docs 提示词指南](https://developers.openai.com/api/docs/guides/prompt-engineering)组织角色、指令、例子和上下文，按[工具指南](https://developers.openai.com/api/docs/guides/tools)区分工具定义与调用。无需指定某个模型，也不要求任何模型API密钥来阅读、校验此交付包。

## 本轮实际验证与待接入能力

已通过：现有环境生成HTTP API生成R1–R5，逐账户核对初始余额+已入账流水=当前余额，金额类型检查，同参数同幂等键重放；JSON解析与证据哈希校验。

待实现/配置：完整档案读取数据门面、真实银行Provider、真实Wind取数、美团/大众点评商户API、Baidu/免费AI自动回退、可插拔RAG/安全服务，以及真实模型行为评测。现有应用自身的权限、知识库和市场导入功能与本包预留接口不能混称为同一项已完成集成。

当前用户最新额度规则为**任一可信窗口剩余<=15%时暂停新业务及GitHub写入，只保存必要交接和审计**。这覆盖1026旧版“保存后继续”的约定。额度未知不能编造数值；新版本仍只放在 `F:\AI_Banking` 直接子目录。

## 复现样本

需要Python标准库和相邻1026.ver2的环境生成模块。以下在本目录PowerShell运行；示例端口8792仅监听本机。

```powershell
$env:ENV_AGENT_IDEMPOTENCY_DB="$PWD\runtime\environment-idempotency.sqlite3"
python -X utf8 '..\AI_Banking_Agent_1026.ver2\modules\环境生成agent\scenario_server.py' --port 8792
```

在另一个终端运行：

```powershell
python -X utf8 tools/collect_dossiers.py --base-url http://127.0.0.1:8792 --reference-date 2026-10-27
python -X utf8 tools/validate_package.py
```

已发布的静态样本是审计fixture，不能用于实时客户决策。业务读取仍必须经过环境Agent数据门面；工具未实现时明确返回能力缺失。HTTP原始响应保留本地采集时间与request_id；固定seed/日期用于重现业务数据，不保证随机生成的标识符逐字节相同。
