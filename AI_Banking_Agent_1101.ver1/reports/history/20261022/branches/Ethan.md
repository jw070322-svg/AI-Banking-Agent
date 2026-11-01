# Ethan / 空交付补位（原分工待确认）：代码修改明细

记录范围：首次集成已实施修改及本次文档补全。依据、修改与验证先列，结论置于末尾。原输出目录未改；共享 service.py 按职责分别说明。

## 归属与补位依据

Ethan output 为空，无法依据文件确认 Ethan 原定职责或选取其最新代码。因此此文档是“空交付补位”的交接，不把推荐模块归属当成已确认的人事分工。为首版提供可运行推荐，复用项目 financial_recommendation_module；补丁编号 P02。

## 逐文件改动与原样复用

| 文件 | 处理方式 | 已实施内容及原因 |
|---|---|---|
| [first_agent/vendor/finance/matching_core.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/matching_core.py>) | 原样复用 | 保留原有资格校验、风险/期限/金额/产品事实约束；没有重写核心评分算法。 |
| [first_agent/vendor/finance/rule_driven.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/rule_driven.py>) | 单项代码修改 | from matching_core 改为 from .matching_core，使模块放入 vendor.finance 后可包内导入；其 recommend 被实际运行调用。 |
| [first_agent/vendor/finance/data_driven.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/data_driven.py>) | 单项代码修改 | 同样修正包内导入；保留作为参考/扩展代码，首版未调用数据驱动模型进行推荐，也未训练模型。 |
| [first_agent/vendor/finance/__init__.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/__init__.py>) | 新增包入口 | 支持服务端相对导入。 |
| [first_agent/service.py](<F:/AI_Banking/FirstAgent/first_agent/service.py>) 的 recommendations | 新增统一适配 | 将 vv 当前产品目录映射到原推荐模型，并以当前用户状态、配置资金和目标期限构造 profile。 |
| [tests/test_integration.py](<F:/AI_Banking/FirstAgent/tests/test_integration.py>) | 新增集成验证 | test_recommendation_consistency_and_profile_missing 核对目录/金额/期限及资料缺失行为。 |

## recommendations 适配的全部字段与行为

1. 产品 ID/name/risk 分别映射 product_id/name/risk_level；p.min 从整数分转 min_investment_cny 元。API 和账本仍使用整数分，仅适配层转成推荐模块所需单位。
2. p.term 月按 30 天转 lockup_days，redemption_days 固定 1；用款 horizon_days 为目标月数×30，使推荐与引擎都计入结算等待日。
3. 非锁定产品归 cash/liquidity，其余归 fixed_income/income；沿用同一份 vv 目录，不独立创建另一套可购买产品。
4. redemption 为 unsupported 的产品标记 facts_verified=false、annual_fee_pct=None；其余为当前虚构目录的演示值，不代表真实银行费用。
5. profile 为 valid 时 risk_tolerance=1，否则设 None；risk_capacity=1，不能靠输入任意偏好提高当前风险权限。缺档案时返回 needs_profile_completion。
6. budget_cny 使用 min(state.amount, engine.capacity)/100，避免推荐金额超出当前配置或扣除必要用款、应急金后的资金。
7. objective 接受调用参数，默认 liquidity；preferred_categories 为 cash，top_k 默认 3；输出补 money_unit 说明适配单位。使用规则 recommend，不产生自动申购。
8. 服务通过 `/api/products`、`/api/recommendations` 及 chat 的推荐动作暴露结果；真正执行仍走 vv 资格校验、预览与确认，不把推荐结果当授权。

## 验证与待交接项

既有测试验证推荐使用相同目录、金额和期限，配置金额较低时排除不满足起点的产品，六个月目标不能容纳六个月锁定再加一天结算，档案缺失时请求补资料。记录见 [reports/verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)。data_driven 未运行，不能把规则集成的通过结果算成其模型质量验证。

Ethan 仍需补交原职责、完整 output、测试和依赖说明；确认推荐职责归属后再认领该补位模块。团队目前只需要模拟产品和银行 API；真实产品映射由后续组委会接入处理。

## 可核对的来源差异

下表由当前来源副本与运行文件逐字节比较生成。相同表示原样复用，不计为逻辑修改。

| 来源 | 运行文件 | 字节比较 |
|---|---|---|
| [matching_core.py](<F:/AI_Banking/financial_recommendation_module/matching_core.py>) | [matching_core.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/matching_core.py>) | 有差异 |
| [rule_driven.py](<F:/AI_Banking/financial_recommendation_module/rule_driven.py>) | [rule_driven.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/rule_driven.py>) | 有差异 |
| [data_driven.py](<F:/AI_Banking/financial_recommendation_module/data_driven.py>) | [data_driven.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/finance/data_driven.py>) | 有差异 |

### matching_core.py 的完整文本差异

文本相同；字节差异来自编码或换行表示。

### rule_driven.py 的完整文本差异

```diff
--- F:/AI_Banking/financial_recommendation_module/rule_driven.py
+++ F:/AI_Banking/FirstAgent/first_agent/vendor/finance/rule_driven.py
@@ -21,5 +21,5 @@
 from pathlib import Path
 
-from matching_core import (
+from .matching_core import (
     POLICY_VERSION,
     evaluate_eligibility,
```

### data_driven.py 的完整文本差异

```diff
--- F:/AI_Banking/financial_recommendation_module/data_driven.py
+++ F:/AI_Banking/FirstAgent/first_agent/vendor/finance/data_driven.py
@@ -27,5 +27,5 @@
 from pathlib import Path
 
-from matching_core import (
+from .matching_core import (
     POLICY_VERSION, evaluate_eligibility, profile_errors, sample_history, sample_products,
     sample_users, validate_catalog, validate_top_k,
```

## 测试与报告入口

此前验证报告：[verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)；浏览器证据：[browser-verification.json](<F:/AI_Banking/FirstAgent/reports/browser-verification.json>)。本次只核对来源、文档覆盖和报告生成，不冒称重跑业务测试。

统一接口：[API-CONTRACT.md](<F:/AI_Banking/FirstAgent/API-CONTRACT.md>)；补丁来源：[patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)；交付文件哈希：[file_manifest.json](<F:/AI_Banking/FirstAgent/reports/file_manifest.json>)。

结论：本分工的已实施修改、原样复用、补丁来源、接口影响、验证依据与尚未完成项已分开记录；后续协作以当前 FirstAgent 代码及统一契约为准。
