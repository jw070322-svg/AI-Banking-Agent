# AI_Banking_Agent_1111.ver2 — 点评自动化：设计 + 本地确定性核心

本目录是独立流程原型与设计交付包，**不是完整银行应用**；不修改 1102.ver3 或 1111.ver1。
用户规则：城市取客户资料；关键词取个人特殊事件；预算保持客户输入值。

## 定位与边界

- **已实现**：结构化需求校验、事件关键词规则基线（外置词库+否定前缀初筛+内置兜底）、整数分预算筛选、步骤契约、运行交接自动生成、JSON Schema 契约与一键本地回归。
- **未实现**：真实页面执行适配器、客户资料页面接线、千问新权重训练、真实端到端验收。
- **纪律**：不得将模拟通过标记为上述未实现目标的完成；`live_executed` 恒为 false 直到执行器真实接入并留证。

## 快速开始

```bat
:: 生成示例交接（不启动浏览器、不调用模型，只写 reports 下唯一目录）
python workflow.py example_customer.json

:: 全部单元测试
python -m unittest -v

:: 一键本地回归：单元测试 + Schema 契约校验 + 词库完整性 + 计划往返
python run_all_checks.py
:: 或双击 启动1111本地测试.bat
```

## 目录结构

```
DESIGN.md                        设计与接续说明（9节，含契约表与验收门槛）
DEVELOPMENT_PLAN_ENHANCED.md     增强版系统工程开发计划（已批准路线图）
LOCAL_AGENT_HANDOFF.md           交接：已实现/未实现清单
README.md                        本文件
workflow.py                      确定性核心（build_plan / cents / filter_candidates / write_handoff）
lexicon.py                       词库加载 + 事件→关键词提取（否定前缀基线，内置兜底）
schema_check.py                  受限 JSON Schema 校验器（仅标准库子集）
data/lexicon.json                外置词库（带 lexicon_version，供 keyword_source 审计引用）
schemas/*.schema.json            六个契约：customer_input / plan / merchant_item /
                                 qwen_output / trajectory / execution_log
test_workflow.py                 原12项单元测试（回归基线）
test_lexicon.py                  词库与否定提取测试
test_schemas.py                  Schema 契约与校验器测试
test_cli.py                      命令行端到端（本地、合成输入）
run_all_checks.py                一键回归，结果追加 TEST_RESULTS.txt
启动1111本地测试.bat              Windows 一键入口
example_customer.json            合成演示客户（synthetic:true，非真实客户）
reports/<时间戳-uuid>/            每次运行的 handoff.md + handoff.json
development_log.jsonl            八字段创作日志
```

## 诚实规则（沿用交接口径）

1. `keyword_source` 如实标注来源：外置词库（lexicon_*）或内置兜底（builtin_rules_fallback）；均为规则基线，非千问推理。
2. 否定只做"否定前缀+关键词"连续匹配基线；不可靠匹配写入 `review_flags` 复核标记（不含事件原文），不宣称完整理解。
3. 商户条目先过结构契约再过语义校验，任一失败进 `needs_confirmation`，不当成 0 元或匹配。
4. 预算换算、候选判定、交接生成的所有结论以 TEST_RESULTS.txt 为本轮证据。
5. 测试均为合成输入；不是模型评测，不是真实点评端到端测试。

## 相关文档

- 设计依据与接口契约：[DESIGN.md](DESIGN.md)
- 批准的开发路线图：[DEVELOPMENT_PLAN_ENHANCED.md](DEVELOPMENT_PLAN_ENHANCED.md)
- 接续状态：[LOCAL_AGENT_HANDOFF.md](LOCAL_AGENT_HANDOFF.md)

## 额度提醒

继续任何新 Phase 前，先核验开发额度：任一可信窗口剩余 ≤15% 时，停止新的业务与写操作，只保存本地交接与审计后暂停。


## 真实客户文件填写说明（工作包C真实试点前置）

模板：`data/customer_fixtures/real_customers_TEMPLATE.json`（kind=local_real_file）。
1. 复制模板为你的真实来源文件（如 `data/customer_real/real_customers.json`），保持 `kind: "local_real_file"`。
2. `records` 只填你明确授权试点的记录（显式 record_id；系统绝不遍历选客）。
3. `budget.basis` 必填 per_person/total（缺失则该记录计划转 needs_input，可用于缺参场景）。
4. 真实记录仅本地留存：不提交Git、不写入运行日志与交接正文（交接只带 record_id 与指纹）。
5. 试点统计：`python pilot_ledger.py stats`；证据复验：`python pilot_ledger.py verify`。
