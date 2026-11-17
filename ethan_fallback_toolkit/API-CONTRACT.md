# Toolkit 接口与计算口径 1.0

## 依据

旧展示结构丢失交易类型和商户，无法可靠识别退款、转账或订阅。工具包以完整账本为输入，先校验再计算；所有输出保留“历史输入 / 用户假设 / 计划”的区别。输入不是现实银行凭证，不能据此推断授权或实际执行结果。

## 账本 schema

`schema_version: scenario-1.1`；至少包含 accounts 和 transactions。环境另有 scenario_id、scenario_type、seed、as_of、parameters、simulated:true、ledger_modified:false。

| 对象 | 必要字段 | 规则 |
|---|---|---|
| accounts[] | account_id、currency、initial_balance_minor、balance_minor | ID 唯一；currency=CNY；余额非负整数分 |
| transactions[] | id、account_id、date、amount_minor、type、category、merchant、status | ID 唯一；关联账户存在；ISO 日期；整数分 |
| type | income、income_reversal、expense、transfer_in、transfer_out、refund | income/transfer_in/refund 为非负；其余为非正 |
| status | booked、rejected | 只有 booked 进入余额及财务汇总 |

单项金额绝对值不超过 1,000,000,000 分；bool、浮点、字符串金额被拒绝。原 Ethan 元值仅可经 import_ethan 转换，禁止无提示舍入。所有账户满足期初+已入账流水=期末；不允许日终负余额。日内顺序未知，不伪造逐秒余额。

整理工具仅可将缺失类别/商户标记为“未分类/未知商户”；类型、币种、金额及余额不得猜测。不同 ID 的疑似重复扣款全部保留，直到业务负责人确认；同 ID 重复直接拒绝。退款进入消费抵减，收入冲回需标为 income_reversal。

`import_ethan` 保留 merchant、type、raw_id，以及源中存在的 duplicate_group_id、related_transaction_id、time、subscription_cycle、recurring、transfer_pair_id；保留源内容哈希，省略 user 身份字段。`to_agent_scenario` 是兼容展示投影，不能回用作完整金融分析输入。

## 工具调用

`call_tool(name, arguments)` 返回 `schema_version, tool, simulated, ledger_modified, status, data, error`。成功 status=succeeded；错误 rejected 且 error={code,message}。UNKNOWN_TOOL、INVALID_ARGUMENT、VALIDATION_FAILED 为主要错误码。它不是支付服务，不接受 execute/transfer/approve 等工具名。

12 个工具的必选字段、参数范围见 tool_definitions.json。所有函数只计算返回值，CLI 明确指定输出路径时才写文件。

## 财务计算

| 输出 | 公式 / 边界 |
|---|---|
| income_minor | 工资等收入 - income_reversal |
| gross_expense_minor | expense 负数金额的相反数之和 |
| refund_minor | refund 金额之和 |
| net_expense_minor | gross_expense - refund；退款超本期消费可为负 |
| cash_surplus_minor | income - net_expense；不含全部 transfer_* |
| net_cashflow_minor | 全部 booked signed amounts 之和；含转账 |
| cash_surplus_ratio | cash_surplus / income；income≤0 时 null 并给原因 |
| debt_service_ratio | 输入的每月偿债额 /（期间净收入 / 涉及日历月数）；非正收入时 null |
| liquidity_months | 输入流动资产 / 输入必要月支出；缺参数或支出为零时 null |

比率为小数，保留六位；0.75 表示 75%。金额求和均为整数。跨月期间包含无交易月份；不完整月份也按日历月计，明确标记，不作年化预测。

本人转账和明确的信用卡还款使用 transfer_in/out，仅改变现金，不重复计入消费；刷卡消费记录使用 expense。上游必须有依据完成分类；若只提供未标记的两笔 expense，本包不会假称已自动消除信用卡重复。

## 场景模拟及生活日历

`simulate_cashflow` 输入 start_date/end_date、start_balance_minor、events、minimum_reserve_minor。事件需唯一 id、date、amount_minor 和 basis（user_input/contract/hypothesis）；effective_from 可控制生效。超出期间或未到生效日期的事件列入 excluded_events。此处允许模拟出现负余额，以展示短缺，不自动借款补齐。

最低余额统计期初和每个事件日的日终；另给 conservative_intraday_minimum_minor，假设同日所有支出先于收入。compare_plans 逐一比较命名方案，不自动推荐或执行。取消订阅方案通过删除尚未生效的未来支出表达，不回填已发生现金。

`plan_life_event` 的可用预算为 max(0,available-reserve)。预算超出或预留本已不足时 needs_adjustment，calendar=[]；否则 draft，礼物/餐饮/其他合计严格等于预算。日期不能过去；准备提醒日期早于 as_of 时压到 as_of，避免生成过期任务。零预算合法。

`export_ics` 只接受 draft，输出全天事件、固定 UID/DTSTAMP、正确转义与 75 字节折行的本地 ICS 文本。requires_confirmation:true 表示后续执行仍需确认，并不表示本工具已具备执行能力。

## 手工算例

期初 10,000 元，收入 10,000 元，消费 3,000 元，退款 500 元；本人转出/转入各 2,000 元，另还信用卡 3,000 元。失败消费 9,999.99 元不计账。

- 净消费：2,500 元；现金结余：7,500 元；现金结余率：75%。
- 净现金流：4,500 元；期末账面余额：14,500 元。
- 输入月偿债额 1,000 元，则偿债比 10%；流动资产 6,000 元 / 必要月支出 2,000 元 = 3 个月。

测试依据这些预期值核对，而非把实现结果作为预期值。

结论：本契约对数据来源、单位、计算范围和执行边界作出明确区分，主 Agent 可据此安全调用确定性工具。
