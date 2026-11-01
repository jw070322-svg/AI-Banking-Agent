# 1027.ver1 本地交接

## Context
用户于2026-10-27粘贴完整需求，要求设计环境生成与银行任务Agent的系统提示词，并更新GitHub文件/日志。已作为提示词与契约包处理，未把预留集成虚称为应用运行能力。

## Constraints
新版本只能在F:\AI_Banking直接子目录。当前目录为F:\AI_Banking\AI_Banking_Agent_1027.ver1。银行应用代码仍是1026.ver2。额度最新规则：任一可信窗口剩余<=15%时停止新业务和GitHub写入，仅保存交接和审计后暂停，恢复需用户明确继续；取代旧的保存后继续。思考框架用事实、设计依据和验证步骤表达，不包含私有思维链。

## Completed
系统提示词14节；Wind JSON指南；统一数据门面/RAG/安全/生活服务/额度契约及JSON Schema；30项模型行为验收规范。通过既有环境生成HTTP API实际生成R1–R5（A/C/D/E/F），账户对账、金额类型、幂等重放通过。工具没有返回风险测评，保持null。10项包校验通过，未运行模型评测。

## Evidence
prompts/banking_environment_system.md；contracts/；examples/R1.json到R5.json及dossiers.json；reports/dossier-api-verification.json；reports/package-verification.json；API原始合成响应保留在reports/raw-environment-responses。含评测参考答案的原始响应仅作审计，不作为待测Agent输入。

## Repository
https://github.com/jw070322-svg/AI-Banking-Agent；功能分支docs/banking-agent-system-20261027，基于fcb5c59a11e58233f8093c56d8f539648ba0fcc6。计划以单次提交添加docs/agent-system/下的提示词、契约、样例、校验脚本及开发日志，再创建draft PR；远端结果待写reports/repository-delivery.json。不要默认main已经更新。

## Decision summary
区分样本编号R1–R5、环境类型A–G及产品/工具风险分级。严格统一业务读取门面，附件接收和公开研究有明确边界。银行替换需认证、单位、分页、状态及幂等映射，不能只替换URL。外部AI只是线索，当前金融事实必须核对来源。缺失安全接口停止敏感写入。接口预留、离线规范、实测API与真实第三方接通分别标注。

## Pending
GitHub文档提交、draft PR和关键文件远端核验已完成；发布审计记录已同步，交付完成。未来运行Agent需实现完整数据读取门面、配置真实RAG/安全、Baidu或零费用AI、Wind及美团/点评连接，执行30项模型行为评测与真实银行Provider契约测试。这些不是本次系统提示词设计包已经完成的运行功能。

## Operations
临时环境生成服务端口8792，exec session24758；源码来自1026.ver2/modules/环境生成agent/scenario_server.py，幂等DB通过ENV_AGENT_IDEMPOTENCY_DB指定到本包runtime。采集完成后已停止本次临时服务（exec session24758返回退出）。没有真实金融操作待核对。1026两版服务不应停止。

## Next steps
先检查额度，再读取repository-delivery与远端分支状态；未提交时只发布本包白名单文件，不上传客户数据或runtime。GitHub成功后写交付凭据并报告用户。提示词及验收框架继续以README和契约为准。


## Repository delivery update
功能分支已发布28文件，首提交0aa50c1e9a15f36faab7ea8d953971b0ab4d024e。draft PR：https://github.com/jw070322-svg/AI-Banking-Agent/pull/1，已附加到当前任务；系统提示词、Wind JSON和档案汇总已从远端按commit读取且与本地发布快照完全一致。最终审计提交为181ac15239dfad23521fc7cd0915003a6cb3cf0c；远端审计内容已读回核对。reports/repository-delivery.json已保存实际发布凭据；当前提示词设计任务完成，后续集成以用户新指令为准。最新额度主窗口剩89%、周窗口剩69%，未触发暂停门槛。
