# 新安全入口契约（补充原API-CONTRACT）

启动类：security_integration.runtime.IntegratedService。默认8808，所有原业务接口和数据形状保留；原服务端dependencies字段中的“无需强验证”说明精确改为“本次采用基础确认”，避免被工具输出检测误判。业务验证强度规则不变。

GET /api/security/status：需要有效会话cookie和正常Host。返回mode=local_demo、gateway=HardenedToolGateway、business_dispatches（仅当前会话计数）、separate_bank_ledger=false、real_identity_verified=false。只读状态，不授予权限，不返回参数或任何密钥。

健康标识：AI_Banking_Agent_1101_Guardian_hardened_local_demo。
原JSON/来源/Host/幂等键、授权和开发者令牌规则仍适用。金融订单执行经Guardian风险/合规与原确认；研究请求经Guardian只读管线，联网期间不占银行写锁。

SQLite新增guardian_events与guardian_dispatch，用于固定事件与关联；不保存原始提示词、验证码或任意参数。原审计和金融账本同事务。
控制面和公开行情后处理的准确覆盖范围参见reports/security-integration-1101/routes.json。

增强边界：所有POST拒绝重复JSON字段、NaN等非标准数值、重复Content-Length和Transfer-Encoding；Content-Type必须是application/json，请求体不超过64KiB。400/413/415为相应请求格式拒绝；429 LOGIN_RATE_LIMIT为登录限速。健康及分析状态响应移除directory字段。新Guardian日志sid为摘要，不是Cookie原文。make_server拒绝非本机host配置（LOCAL_ONLY）。

## 【新增】2026-11-01 实机复测

实测新键请求在读取授权撤销后返回 SCOPE_DENIED。同会话、同一旧键、同参数的 /api/rpc summary 请求仍返回原成功响应，未增加 Guardian 调度数。本例属于已知的幂等缓存读取例外。41 项主链用例通过；交付包的报告重生成在历史路径断言处失败。复现与验收条件见 [1101 技术说明](技术设计与复测说明_1101.md)。
