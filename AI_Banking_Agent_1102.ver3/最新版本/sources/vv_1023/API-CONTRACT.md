# 前端模拟适配说明（不是 FirstAgent 服务端接口契约）

当前无 HTTP 业务 API，方法是浏览器本地确定性模拟，不包含同步 XHR。不得把这里的方法当作组长已经实现的 API。

`BankLocal.createSession()` 创建持久化适配器，外部 state/catalog 为副本；每次规则调用后保存快照。账单、总览、任务和卡片都从同一适配器读取。

## 本地方法

- `authorize({read,subscriptions,trade,cards})`：read/subscriptions/trade为契约范围；cards是本地扩展，不发送后台。转账使用trade。24小时是本地演示授权策略，不是服务端契约规定；变更使未确认操作失效。
- `propose('transfer', recipientId, amountMinor, {cardId})`：名册收款人、整数分金额、付款借记卡。验证余额、状态、累计日限额。
- `propose('card_limit', cardId, newLimitMinor)`：100–50000元范围，不能低于当日已用额度。
- `propose('card_lock'|'card_unlock'|'card_loss', cardId)`：只生成绑定对象的确认，不立即改变卡状态。
- `propose('card_apply')`：申请虚构借记卡。
- `verify(opId,'246810')` 与 `execute(opId, mode)`：mode为success/failed/unknown；前端演示，无真实身份验证。
- `reconcile(opId,result)`：只查询原未知操作；pending/success/failed；不重发。
- `settleCard(opId,result)`：申请受理后至少下一模拟日，success创建模拟卡，failed拒绝。
- `cancel(opId)`：仅取消awaiting_confirmation；不回滚已完成金融操作。
- 原申购/赎回/订阅/目标/预算/预演/时钟方法继续复用。

状态：awaiting_confirmation / invalidated / cancelled / unknown / processing / succeeded / failed。

## 数据所有权与持久化

快照schema=3，key=banking-unified-demo-v3。包含version、revision、整数分金额、cards、contacts、operations、events、transactions、consent等。新标签页载入会推进快照revision，旧标签页在下次写入前检测冲突并要求刷新。快照不是防篡改数据库，浏览器可被用户修改，不可用于生产授权。

未知结果不先扣款或改卡；全局阻止后续写业务，先查询。申请processing不当作开卡。转账发生externalOut，资产守恒基准为total()+externalOut===initialTotal。

## 后续集成

需要组长最新FirstAgent代码、正式API-CONTRACT.md及语嫣卡管理接口的对象/状态/错误/验证约定。按服务端权威状态调整适配器与调用方异步流程；幂等、权限、验证、持久审计在服务端实施。不能仅替换URL后继续信任本地结果选择器、验证码或余额。此轮未接真实模型和银行服务。


## FirstAgent 1.0.0 契约对齐更新

已收到的原文保存在 `FIRSTAGENT-CONTRACT-1.0.0.md`，不覆盖原文。`contract-client.js` 提供异步 HTTP 请求层和显式 BankGateway 入口；UI 调用 `BankGateway.createLocalSession()`，默认**不发出任何后台业务请求**。

已在本地规则实现：转账归入 trade；含本次当日累计≤100000分为黄色确认，超过为红色验证；预览300秒、红色断言120秒，均以真实时间整数epoch秒校验；过期不执行。模拟业务日期仍使用毫秒；1月30天，结算额外1天。

HTTP请求层：`BankGateway.createBackendClient({baseURL:'http://localhost:8000/'})`（仅调用形式示例，8000不是已知服务端口）。调用方显式创建才会连接；无自动切换、无请求失败后退回本地扣账。`start()`建立cookie会话；`snapshot()`读服务端快照。

转账命令采用 `client.previewTransfer({amount_minor:80000,beneficiary_name:'小王',account_id:'ACC-4821'})` 等命令构造器，返回固定 `{path,method,body,key}`，再 `await client.send(command)`。网络错误后保留同一命令/幂等键；不自动重试，已提交操作先查原回执。命令参数改变须新键。同键不同参数在客户端也拒绝。服务端仍须实施权威幂等。

专用转账 preview/verify/confirm/cancel/reconcile，不把transfer塞进RPC。RPC仅开放原文白名单；authorize仅传read/subscriptions/trade三类。只接受整数分和ACC-4821；不把本地银行卡ID当作后台账户ID。响应保留schema_version/request_id/status/data/error/trace/simulated外壳，未知状态/坏响应拒绝，不据此改账。查询具体operation及events也有异步方法。

本地卡片有自己的限制规则，服务端eva硬限额配置文件尚未收到；未把1000元分级阈值当作银行硬限额。卡管理接口仍不存在于该契约，不猜路径、不假装对接。

**仍需联调**：当前UI仍是本地状态所有者；请求层已实现并以替身传输测试，不代表UI已切换服务端。拿到FirstAgent后，需要根据真实data嵌套字段、联系人名单、断言返回、错误码、服务地址及Host/Origin规则，完成异步UI调用、服务端快照刷新和记录整合。到时必须停用本地写账，不能两份账本一起扣款。建议同源托管，而不是从file页面跨域请求。卡管理另等语嫣契约。
