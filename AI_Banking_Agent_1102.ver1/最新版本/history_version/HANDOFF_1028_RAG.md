# 1028.ver1 本轮交接

时间：2026-10-28T15:16:50.216318+08:00。本轮已完成新增simple_RAG(3).py的静态比较、增量实现、完整测试及RAG界面验收。最近额度核验主窗口剩余28%，周窗口89%，继续前须重新核验；任一窗口<=15%立即保存暂停。

项目目录F:\AI_Banking\AI_Banking_Agent_1028.ver1，来自1027.ver5。原RAG30个文件逐一hash未变，未新增知识正文；旧资料18份/134术语不改。新增模块、入口、测试、提示词及完整文本见先看这里_1028.md、RAG_MERGE_REPORT.md和reports/rag-additive-validation.json。附件原件在sources/incoming_1028，未执行。根AGENTS规定及八字段日志继续遵守。

新入口start_additive_rag.py通过组合AgentService.rag接入AdditiveRAGService；原RAG先回答，只有no_evidence且无已有证据时尝试本地稀疏TF-IDF及Jaccard。原既有回答、拒答、业务路由、有效期/类型过滤不变。无新HTTP接口，无外网/付费依赖，不改原manifest/index或源码。原start.py/启动网页.bat保留，只使用新入口才能启用新增模块。新服务8799，独立cookie和runtime/rag-additive.sqlite3；最近exec session30438，下一轮需实际核验。

已验证：9新增专项，完整166后端/85前端，真实浏览器问句Can you explain LPR simply?显示原文LPR释义及来源。未带问号的英语请求可能被旧路由拒绝识别，已如实记录而未改旧路由。新接口不自动启动旧模型，不复制旧凭据；本轮仅RAG流程实测。默认RAG阈值为工程规则，非全面事实准确性认证。

前轮未完事项继续保留：模型GGUF/PEFT数值等价性，搜索授权新增路径专项测试，个性化商户字段与跳转完整浏览器验收，旧版文档状态更新等；此轮用户重点为只增不改的RAG，不要把这些前轮待办标成完成。后续如有新知识文件，须单独比对正文并保持本轮原文hash，不要把源码送入金融知识索引。

接续框架：先额度与当前版本，再核对来源/类型/完整性；先原回答和拒绝，再考虑增量证据；以hash、来源行号、API和UI实际结果交叉核验；完整报告先可审计比较摘要后完整正文，不记录私有思维链。
