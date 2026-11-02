# 宏观量化研究：离线接口契约

版本：`macro-quant-1.0`。这是离线文件与纯函数契约，**没有新增HTTP接口**。既有 `/api/recommendations` 仍运行原偏好排序与预算规则。

## 调用与数据责任

```python
from quant_recommender import load_json, recommend

config = load_json("params.json")
data = load_json("example_input.json")
result = recommend(data, config)
```

`recommend` 不修改输入、不访问网络、不读取当前系统时间、不写账本。CLI 用 `--config`、`--input`、`--output` 指定本地文件。重复JSON键、NaN/Infinity、布尔冒充金额/评级等非法输入被拒绝；结构/类型不符合契约抛出 `ValueError`。合法但支持不足的数据返回带原因的 `abstain`。

全部字段定义在 `params.json` 的 `input_fields`、`feature_definitions`、`parameter_definitions` 和 `output_definitions`。核心读取数值参数；说明字段保留供审查。输入中扩展的来源清单和滚动验证快照不代表核心已核验外部来源。

| 上游责任 | 交付内容 |
|---|---|
| 宏观/市场数据适配器 | 实际历史版本、统计期、可用时刻、制度ID、固定市场指数、源文件证据 |
| 产品数据适配器 | 当期适当性事实、历史可投资集合、相同30自然日到账标签、历史期限/费率 |
| 现有服务 | 已批准预算 `budget_basis.applied_minor`、风险意愿/能力、资金期限、原预算警告 |
| 本模型 | 时间/数值校验、共同情景与支持检查、精确费用/CVaR、排序与排除诊断 |

预算以CNY整数分传入，不转换为浮点元重新计算。最低申购金额是含申购费的总支出。客户账本、账户、身份及交易指令都不属于本输入。

## 三种正常结果

| status | 含义 | 调用方行为 |
|---|---|---|
| `ok` | 至少一个合格产品分数超过现金门槛 | 展示研究备选及依据，不自动申购 |
| `no_positive_score` | 没有超过门槛的合格备选 | 不强制推荐；现金作为零超额分数比较基准 |
| `abstain` | 当前信息、历史支持或数据口径不满足要求 | 显示 `reason_codes`，不能把空列表当成“市场安全” |

`ranking` 是最多 `top_k` 个独立备选；`evaluated` 保留可计算的非正分结果；`excluded` 给出产品门槛/历史缺失原因。`diagnostics` 提供情景、标准化、概率和支持信息。所有返回带 `research_only=true`、`ledger_modified=false`、数据类别及输入/配置哈希。

CVaR为 `loss=-excess` 的带符号尾部均值，可为负。所有收益与分数都是H日小数单位。相同输入与配置生成相同结果；输出哈希用于复算一致性，不证明外部数据是真实的。

## 与既有系统接续

本轮不把新模型加入 HTTP 工具白名单或交易执行链。之后若接入，必须先补真实PIT数据并冻结验证后的参数，再由服务端把已授权的产品与预算映射为本契约。宏观分数不能改变现有推荐预算，不可绕过预览、验证、确认和回执规则。原先分析上限为零的回退及应急金提示继续遵从既有决议。

真实数据不足时应明确保持研究拒绝；若产品希望展示原有偏好排序，必须标明该结果来自原模型，不得将其包装为本模型的有效宏观排名。
