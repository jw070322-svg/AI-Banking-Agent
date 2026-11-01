# eva / 模拟银行接口与风控（卡管理后端主责）：本轮代码修改与交接

## 判断依据

卡状态会直接改变转账可执行性，必须由服务端统一检查；页面禁用按钮不足以保护另一条 API。旧版权限检查也缺少 24 小时到期判断。

## 本轮逐项修改（2026-10-23）

| 文件 | 实际改动及目的 |
|---|---|
| `first_agent/service.py` | require 增加 consentExpiresAt；authorize.cards 仅接受 bool；策略版本升为 integrated-demo-1.1，使旧策略确认不能继续执行。 |
| `first_agent/service.py` | bound_hash 加入付款卡；check_transfer_limits 从共享交易记录累计当日转账，并使用 eva 单笔/日硬限额；transfer_policy 检查默认卡的 active 状态及剩余额度。 |
| `first_agent/service.py` | apply_transfer 同时更新卡片 spent 与 externalOut；初始资产基准不再随出账缩减，使可用资金+持仓+对外转出保持守恒。 |
| `first_agent/service.py` | 红色操作先检查服务端断言期限和绑定，再执行引擎；避免过期断言仅返回笼统的引擎拒绝。失败不扣款，未知结果仍阻止新金融写入。 |
| `tests/test_update.py` | 覆盖两条转账路径共享限额、挂失禁止交易、权限类型、过期、重放、旧状态迁移及未知结果只结算一次。 |

## 首轮保留内容与详细历史

首轮的 ver.1 scanner 补缺、security gate、脱敏、账户越权、增强断言和幂等事务继续保留。原始 eva 包缺件情况未变化；没有宣称其原版 42 项测试通过。

[首轮逐项变更记录](../history/20261022/branches/eva.md)。历史中的“卡管理未实现”“Ethan 空交付”为当时状态，本轮以上文为准。

## 本轮完整代码差异

- `first_agent/service.py`：[完整补丁](../diffs/first_agent__service.py.diff)，SHA-256 `08030e06689af5e482f465db3b17190b1cec8a77f0be9079f238d029a99db276`。

- `tests/test_update.py`：[完整补丁](../diffs/tests__test_update.py.diff)，SHA-256 `ff04c7db46135d33f0f5102c3a065d8f7896f386c4311259f11b872ef1aac5ef`。

## 验证与责任边界

总包实测：32/32 Python 集成检查，35/35 JS 检查；详见 [验证报告](../verification.json)。此结果不等于各队友原版测试全部通过。

卡管理分工：eva 主责后端模拟接口、卡状态与风控；vv 主责卡片库选择与确认交互；集成负责状态/安全/回执串联；Ethan 提供场景测试数据；YUKI 提供知识及评测资料。

## 后续协作

- 维护模拟银行 API 与卡状态/限额契约；真实银行由组委会部署接入。

- 后续提供完整同版本 bank_agent 包及其原版测试。

- 与 vv 对齐错误提示、卡版本变化和任务回执，不另建账本。

结论：复用 eva ver.2 的工具、模型和限额配置，新增两条转账路径共同执行的卡状态、日额度、授权过期和预览绑定约束。
