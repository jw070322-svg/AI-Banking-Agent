# 预算建议参数化回测

- 生成时间：2026-10-24T04:56:14+00:00
- 场景数：7
- 压力变体：base, spending+20%, income-20%, balance-30%, combined, balance~0
- 周期：30, 90 天
- 策略数：13

## 基准策略（储蓄 1 个月 / 投资 3 个月）

| 场景 | 压力 | 周期 | 月度结余 | 储蓄建议 | 投资建议 | 动作 | 数据质量 |
|---|---|---|---:|---:|---:|---|---|
| SCENARIO_A | balance-30% | 30 | ¥8,325.37 | ¥7,160.65 | ¥222.23 | invest | ok |
| SCENARIO_A | balance-30% | 90 | ¥8,325.37 | ¥2,386.88 | ¥74.07 | invest | ok |
| SCENARIO_A | balance~0 | 30 | ¥8,325.37 | ¥0.00 | ¥0.00 | none | ok |
| SCENARIO_A | balance~0 | 90 | ¥8,325.37 | ¥0.00 | ¥0.00 | none | ok |
| SCENARIO_A | base | 30 | ¥8,325.37 | ¥8,325.37 | ¥4,777.89 | invest | ok |
| SCENARIO_A | base | 90 | ¥8,325.37 | ¥3,905.43 | ¥1,592.63 | invest | ok |
| SCENARIO_A | combined | 30 | ¥5,272.63 | ¥5,272.63 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_A | combined | 90 | ¥5,272.63 | ¥2,155.61 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_A | income-20% | 30 | ¥5,966.45 | ¥5,966.45 | ¥4,777.89 | invest | ok |
| SCENARIO_A | income-20% | 90 | ¥5,966.45 | ¥3,905.43 | ¥1,592.63 | invest | ok |
| SCENARIO_A | spending+20% | 30 | ¥7,631.55 | ¥7,631.55 | ¥2,696.43 | invest | ok |
| SCENARIO_A | spending+20% | 90 | ¥7,631.55 | ¥3,674.16 | ¥898.81 | invest | ok |
| SCENARIO_B | balance-30% | 30 | ¥13,523.88 | ¥7,583.19 | ¥419.57 | invest | ok |
| SCENARIO_B | balance-30% | 90 | ¥13,523.88 | ¥2,527.73 | ¥139.85 | invest | ok |
| SCENARIO_B | balance~0 | 30 | ¥13,523.88 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_B | balance~0 | 90 | ¥13,523.88 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_B | base | 30 | ¥13,523.88 | ¥13,294.69 | ¥6,131.07 | invest | ok |
| SCENARIO_B | base | 90 | ¥13,523.88 | ¥4,431.56 | ¥2,043.69 | invest | ok |
| SCENARIO_B | combined | 30 | ¥9,386.38 | ¥6,434.46 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_B | combined | 90 | ¥9,386.38 | ¥2,144.82 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_B | income-20% | 30 | ¥10,102.74 | ¥10,102.74 | ¥6,131.07 | invest | ok |
| SCENARIO_B | income-20% | 90 | ¥10,102.74 | ¥4,431.56 | ¥2,043.69 | invest | ok |
| SCENARIO_B | spending+20% | 30 | ¥12,807.52 | ¥12,145.96 | ¥3,549.62 | invest | ok |
| SCENARIO_B | spending+20% | 90 | ¥12,807.52 | ¥4,048.65 | ¥1,183.20 | invest | ok |
| SCENARIO_C | balance-30% | 30 | ¥9,519.46 | ¥9,519.46 | ¥7,032.58 | invest | ok |
| SCENARIO_C | balance-30% | 90 | ¥9,519.46 | ¥3,531.45 | ¥2,344.19 | invest | ok |
| SCENARIO_C | balance~0 | 30 | ¥9,519.46 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_C | balance~0 | 90 | ¥9,519.46 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_C | base | 30 | ¥9,519.46 | ¥9,519.46 | ¥9,519.46 | invest | ok |
| SCENARIO_C | base | 90 | ¥9,519.46 | ¥5,608.17 | ¥4,420.91 | invest | ok |
| SCENARIO_C | combined | 30 | ¥6,903.21 | ¥6,903.21 | ¥5,531.67 | invest | ok |
| SCENARIO_C | combined | 90 | ¥6,903.21 | ¥3,268.60 | ¥1,843.89 | invest | ok |
| SCENARIO_C | income-20% | 30 | ¥7,259.39 | ¥7,259.39 | ¥7,259.39 | invest | ok |
| SCENARIO_C | income-20% | 90 | ¥7,259.39 | ¥5,608.17 | ¥4,420.91 | invest | ok |
| SCENARIO_C | spending+20% | 30 | ¥9,163.28 | ¥9,163.28 | ¥9,163.28 | invest | ok |
| SCENARIO_C | spending+20% | 90 | ¥9,163.28 | ¥5,345.32 | ¥3,920.61 | invest | ok |
| SCENARIO_D | balance-30% | 30 | ¥6,266.28 | ¥363.01 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | balance-30% | 90 | ¥6,266.28 | ¥121.00 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | balance~0 | 30 | ¥6,266.28 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_D | balance~0 | 90 | ¥6,266.28 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_D | base | 30 | ¥6,266.28 | ¥2,760.72 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | base | 90 | ¥6,266.28 | ¥920.24 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | combined | 30 | ¥3,549.45 | ¥0.00 | ¥0.00 | none | ok |
| SCENARIO_D | combined | 90 | ¥3,549.45 | ¥0.00 | ¥0.00 | none | ok |
| SCENARIO_D | income-20% | 30 | ¥4,281.24 | ¥2,760.72 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | income-20% | 90 | ¥4,281.24 | ¥920.24 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | spending+20% | 30 | ¥5,534.49 | ¥1,714.38 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_D | spending+20% | 90 | ¥5,534.49 | ¥571.46 | ¥0.00 | build_emergency_fund | ok |
| SCENARIO_E | balance-30% | 30 | ¥15,193.37 | ¥15,193.37 | ¥15,193.37 | invest | low_spending |
| SCENARIO_E | balance-30% | 90 | ¥15,193.37 | ¥15,193.37 | ¥15,193.37 | invest | low_spending |
| SCENARIO_E | balance~0 | 30 | ¥15,193.37 | ¥0.00 | ¥0.00 | none | low_spending |
| SCENARIO_E | balance~0 | 90 | ¥15,193.37 | ¥0.00 | ¥0.00 | none | low_spending |
| SCENARIO_E | base | 30 | ¥15,193.37 | ¥15,193.37 | ¥15,193.37 | invest | low_spending |
| SCENARIO_E | base | 90 | ¥15,193.37 | ¥15,193.37 | ¥15,193.37 | invest | low_spending |
| SCENARIO_E | combined | 30 | ¥11,783.88 | ¥11,783.88 | ¥11,783.88 | invest | low_spending |
| SCENARIO_E | combined | 90 | ¥11,783.88 | ¥11,783.88 | ¥11,783.88 | invest | low_spending |
| SCENARIO_E | income-20% | 30 | ¥11,969.29 | ¥11,969.29 | ¥11,969.29 | invest | low_spending |
| SCENARIO_E | income-20% | 90 | ¥11,969.29 | ¥11,969.29 | ¥11,969.29 | invest | low_spending |
| SCENARIO_E | spending+20% | 30 | ¥15,007.96 | ¥15,007.96 | ¥15,007.96 | invest | low_spending |
| SCENARIO_E | spending+20% | 90 | ¥15,007.96 | ¥15,007.96 | ¥15,007.96 | invest | low_spending |
| SCENARIO_F | balance-30% | 30 | ¥14,585.20 | ¥10,004.64 | ¥4,092.70 | invest | ok |
| SCENARIO_F | balance-30% | 90 | ¥14,585.20 | ¥3,334.88 | ¥1,364.23 | invest | ok |
| SCENARIO_F | balance~0 | 30 | ¥14,585.20 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_F | balance~0 | 90 | ¥14,585.20 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_F | base | 30 | ¥14,585.20 | ¥14,585.20 | ¥10,835.68 | invest | ok |
| SCENARIO_F | base | 90 | ¥14,585.20 | ¥5,582.54 | ¥3,611.89 | invest | ok |
| SCENARIO_F | combined | 30 | ¥10,485.80 | ¥9,058.87 | ¥1,964.59 | invest | ok |
| SCENARIO_F | combined | 90 | ¥10,485.80 | ¥3,019.62 | ¥654.86 | invest | ok |
| SCENARIO_F | income-20% | 30 | ¥11,076.97 | ¥11,076.97 | ¥10,835.68 | invest | ok |
| SCENARIO_F | income-20% | 90 | ¥11,076.97 | ¥5,582.54 | ¥3,611.89 | invest | ok |
| SCENARIO_F | spending+20% | 30 | ¥13,994.03 | ¥13,994.03 | ¥8,707.57 | invest | ok |
| SCENARIO_F | spending+20% | 90 | ¥13,994.03 | ¥5,267.28 | ¥2,902.52 | invest | ok |
| SCENARIO_G | balance-30% | 30 | ¥10,855.61 | ¥10,855.61 | ¥10,855.61 | invest | ok |
| SCENARIO_G | balance-30% | 90 | ¥10,855.61 | ¥5,517.37 | ¥4,304.11 | invest | ok |
| SCENARIO_G | balance~0 | 30 | ¥10,855.61 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_G | balance~0 | 90 | ¥10,855.61 | ¥0.00 | ¥0.00 | fix_cashflow | shortfall |
| SCENARIO_G | base | 30 | ¥10,855.61 | ¥10,855.61 | ¥10,855.61 | invest | ok |
| SCENARIO_G | base | 90 | ¥10,855.61 | ¥8,252.42 | ¥7,039.16 | invest | ok |
| SCENARIO_G | combined | 30 | ¥7,956.53 | ¥7,956.53 | ¥7,956.53 | invest | ok |
| SCENARIO_G | combined | 90 | ¥7,956.53 | ¥5,344.49 | ¥3,888.58 | invest | ok |
| SCENARIO_G | income-20% | 30 | ¥8,320.51 | ¥8,320.51 | ¥8,320.51 | invest | ok |
| SCENARIO_G | income-20% | 90 | ¥8,320.51 | ¥8,252.42 | ¥7,039.16 | invest | ok |
| SCENARIO_G | spending+20% | 30 | ¥10,491.63 | ¥10,491.63 | ¥10,491.63 | invest | ok |
| SCENARIO_G | spending+20% | 90 | ¥10,491.63 | ¥8,079.54 | ¥6,623.62 | invest | ok |

## 储蓄缓冲敏感性（投资固定 3 个月）

| 储蓄缓冲 | 正储蓄案例 | 正储蓄率 | 平均储蓄额 |
|---:|---:|---:|---:|
| 0 | 74/84 | 88.10% | ¥6,639.04 |
| 1 | 68/84 | 80.95% | ¥5,918.05 |
| 2 | 60/84 | 71.43% | ¥5,110.83 |
| 3 | 56/84 | 66.67% | ¥4,261.70 |

## 投资缓冲敏感性（储蓄固定 1 个月）

| 投资缓冲 | 正投案例 | 正投率 | 平均投资额 |
|---:|---:|---:|---:|
| 1 | 68/84 | 80.95% | ¥5,918.05 |
| 2 | 60/84 | 71.43% | ¥5,110.83 |
| 3 | 56/84 | 66.67% | ¥4,261.70 |
| 6 | 32/84 | 38.10% | ¥2,793.94 |

## 不变量

通过

## 边界

- 数据来自 A~G 合成场景及压力缩放，不代表真实用户分布；
- 1/3/6 个月是原型策略，不是监管标准；
- 压力变体只缩放金额，不改变日期、订阅周期和锁定期；
- 结论适合验证规则稳定性，不能替代真实脱敏数据回测。
