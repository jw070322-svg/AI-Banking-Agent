# 验证报告索引

本目录由 `backtest_budget.py` 生成。重新运行即可刷新全部报告，数字与 JSON 同源。

| 文件 | 用途 | 读者 |
|---|---|---|
| `budget_backtest_rule_stability.md` | 规则稳定性验证：不变量、确定性、敏感性、压力响应、回归测试 | 评委 / 答辩 |
| `budget_backtest_data_boundaries.md` | 数据边界：场景完整度、可声明 / 不可声明、比赛场景覆盖 | 评委 / 答辩 |
| `budget_backtest.md` | 原始回测结果：基准策略逐场景明细、敏感性表 | 开发 |
| `budget_backtest.json` | 机器可读证据：1092 条案例、策略汇总、失败列表 | 开发 / 复核 |

## 重新生成

```powershell
cd C:\Users\111\Desktop\AI_Banking\主任务_金融分析与量化
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" backtest_budget.py
```

## 一句话结论

当前证明的是“规则实现一致、确定、在合成场景和压力变体下稳定”；
不能证明真实用户准确率。真实数据校准方法见数据边界报告第 6、8 节。
