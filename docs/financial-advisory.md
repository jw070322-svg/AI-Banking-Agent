# 金融产品顾问：当前能力与集成边界

更新日期：2026-10-20。本次交付包含两个可独立运行的演示原型，尚未接入为统一 Agent。

## 1. 项目定位

项目主线继续覆盖**账单分析、订阅／代扣管理、智能转账**。金融产品顾问保留为 P2 扩展，利用现金需求、风险承受能力与用款期限解释产品匹配，并通过情景假设检查现金缓冲。保存推荐方案不代表已申购，也不能替代业务执行回执。

量化投顾、组合优化、市场预测、回测及真实交易均不属于当前实现。

## 2. 两个独立原型

| 内容 | Dashboard | 独立推荐模块 |
|---|---|---|
| 入口 | `Dashboard/dashboard_ui.py` | `financial_recommendation_module/rule_driven.py`、`data_driven.py` |
| 目的 | 财务总览、产品比较、情景验证和模拟方案留存 | 对比显式规则排序与相近用户历史评分形成的偏好估计 |
| 数据 | 4 个虚构产品、合成历史流水和可修改的画像假设 | 10 个虚构客户、7 个虚构产品、16 条虚构评分 |
| 约束 | 风险、计划金额、最低金额、锁定期及现金储备 | 风险、预算、最低金额、锁定与赎回时长、币种、有效状态及事实完整性 |
| 输出 | 匹配／排除原因、资金缺口、模拟方案和活动日志 | 推荐候选、排除原因、规则贡献或邻居评分证据 |
| 依赖 | 固定版本 Streamlit | 两种匹配方法仅用标准库；Excel 读取器另需 openpyxl |

两套代码目前没有互相调用。Dashboard 内部使用整数分，推荐模块的 `budget_cny` 等字段使用人民币元；产品目录、画像与期限规则也不同。接入前必须统一数据契约和单位，不能直接互传金额。

## 3. Dashboard 行为

程序先将风险偏好与承受能力的较低值作为风险上限，再检查资金、最低金额和期限等硬约束，最后按偏好排序。修改画像或所选产品会撤销旧确认；保存时重新检查当前条件，仅记录模拟方案，不扣款或申购。

情景验证比较现金缓冲与额外支出、延期收入带来的额外缓冲需求。这是确定性教学假设，未模拟市场价格、费用、税收、赎回延迟或违约，也不是逐日现金流预测。

默认额度明确标为模拟模式。配置 `BANKING_QUOTA_FILE` 后，应用读取可信宿主持续更新的 Codex 五小时额度快照；独立程序没有直接查询通用 Plus 订阅额度的接口。剩余量严格低于 10%，或快照不可用／过期时，停止新匹配、情景计算及新方案保存，保留已有成果下载。轮询不提供硬实时保证。

详细运行配置、界面说明和开发记录见 [Dashboard 文档](../Dashboard/main_dashboard.md)。

## 4. 推荐算法与数据限制

两种方法共用事实资格检查，排序不能覆盖硬约束的拒绝结果。

- **规则方法**按目标、类别偏好、可取用时长和已知费用计算示例规则分，并展示各规则贡献。
- **数据方法**依据相近参考客户的演示评分估计偏好，展示邻居支持；证据不足时返回 `no_evidence`，不补造历史评分。

两种分数含义不同，不能直接相加，也都不是收益预测、适当性概率或合规认证。每个推荐产品是独立候选，不代表同时买入整个列表的投资组合。示例评测只用于验证程序机制，不能证明真实客户或市场上的效果。

最初指定的 `EDE20261017.xlsx` 未能读取，其表结构、字段、单位和记录均未核验。附带数据明确为虚构样例；Excel 适配器和映射模板只提供接入入口。真实工作簿推荐、真实数据预测验证及生产金融政策审查均未完成。

算法、样例输出和历史验证记录见 [推荐模块架构](../financial_recommendation_module/architecture.md)。

## 5. 运行与测试

以下命令在仓库根目录、已启用的独立 Python 环境中执行。

```console
python -m pip install -r Dashboard/requirements.txt
python -m streamlit run Dashboard/dashboard_ui.py
```

算法演示可独立运行：

```console
python financial_recommendation_module/rule_driven.py --user-id U001 --top-k 3
python financial_recommendation_module/data_driven.py --user-id U001 --top-k 3
python financial_recommendation_module/data_driven.py --evaluate
python -m unittest discover -s financial_recommendation_module -p "test_*.py" -v
python -m unittest discover -s Dashboard/tests -p "test_*.py" -v
```

仅使用 Excel 读取器时，额外安装依赖：

```console
python -m pip install openpyxl==3.1.5
python financial_recommendation_module/workbook_adapter.py --help
```

本次暂存版本已通过 29 项 Dashboard 测试及 32 项推荐模块测试，共 61 项。推荐模块内 `validation_report.json` 保留 2026-10-17 的历史验证记录。上述测试不包含真实工作簿集成或银行业务端到端验证。

## 6. 后续集成与发布范围

主线三个场景和安全执行优先。顾问接入时需统一现金与预算口径、画像／产品版本和结果契约，由编排器处理缺失信息、确认与任务状态，并分别记录建议、业务提交及执行回执。

仓库示例保持合成数据。真实工作簿、归一化客户记录、API 凭证、会话导出、实际额度快照、虚拟环境与缓存不随演示代码发布。
