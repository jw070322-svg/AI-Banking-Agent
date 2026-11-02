"""AI Banking 金融数据分析内核。

对外暴露的核心能力：
- aggregate：分类 / 月度 / 年度账单汇总（金额全部为整数分）；
- anomaly：异常交易识别（重复扣款、失败转账、还款、续费、调价、异常大额消费等）；
- cashflow：订阅负担率与未来 30/90 天现金流投影；
- budget：按月度结余和现金流最低余额，给出每月可安全储蓄/投资额；
- evaluate：用环境生成 Agent 的 expected_insights 当标准答案，评估识别效果；
- loader：读取契约 JSON 或环境生成 Agent 的内部 JSON。

设计边界：只读数据，不写账本、不发起交易；所有金额使用 CNY 整数分。
"""

from .aggregate import (
    annual_report,
    category_breakdown,
    monthly_report,
    overall_summary,
)
from .anomaly import detect_anomalies
from .budget import budget_advice
from .cashflow import project_cashflow, subscription_burden
from .evaluate import evaluate_detection
from .liquidity import available_liquidity
from .loader import load_scenario, normalize_scenario

__all__ = [
    "annual_report",
    "category_breakdown",
    "monthly_report",
    "overall_summary",
    "detect_anomalies",
    "subscription_burden",
    "project_cashflow",
    "available_liquidity",
    "budget_advice",
    "evaluate_detection",
    "load_scenario",
    "normalize_scenario",
]
