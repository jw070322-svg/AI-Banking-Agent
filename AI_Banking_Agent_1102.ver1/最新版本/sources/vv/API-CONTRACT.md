# 统一版接入边界（建议，尚未上线）

当前所有工具为本地同步沙箱，不存在真实银行 API。生产接入需把规则与账本写入迁移到服务端，不能信任浏览器余额、用户 ID、档案、权限或执行结果。

## 建议资源
- GET /accounts/overview：唯一账本快照、可用资金、持仓及在途资金。
- GET /transactions?month=&category=&query=：账单与分页。
- GET /subscriptions；POST /subscriptions/:id/cancel：周期扣费、取消提案与回执。
- GET /products；GET /profile：权威目录、费用、申赎规则、风险有效期及适配结果。
- POST /proposals：对象、金额（整数分）、目标、产品与档案版本、有效期、资金影响。
- POST /proposals/:id/verify；POST /proposals/:id/confirm：服务端验证令牌与绑定版本；使用幂等键，不能使用页面明文演示码。
- POST /positions/:id/redemptions：校验到期日、持仓与占用，返回 pending/processing 状态，不立即入账。
- GET /operations/:id：权威状态及回执；未知时只查询，不静默重发。
- GET /tasks/:id/events：工具事件与依赖；需服务端持久化、访问控制与完整性保护。
- POST /consents；DELETE /consents/:id：范围、限额、有效期、撤销；敏感操作仍独立确认。

## 状态
awaiting_confirmation / invalidated / cancelled / unknown / processing / succeeded / failed。申购仅服务端成功后更新资金；赎回只有权威结算成功才释放持仓并增加余额。

生产接口需覆盖认证、过期、越权、余额不足、版本冲突、重复提交、限流、执行失败、超时未知、结算失败、审计与人工接管。不能把前端测试选择器当作真实返回。
