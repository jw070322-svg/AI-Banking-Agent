# AI Banking SecondAsgent

本轮根据最新队友产出，增加卡管理、新版转账及独立测试场景。所有金融行为为本地模拟；真实银行 API 由组委会收到作品后本地部署接入。目录按用户指定命名，Python 包名保留 first_agent。

## 启动

需要 Python 3.11+、Node.js 18+；仅用标准库，无需下载依赖。

```powershell
cd F:\AI_Banking\SecondAsgent
python -m first_agent.server --port 8767
# 或 .\run_agent.ps1
```

打开 http://127.0.0.1:8767/ ，Ctrl+C 停止。首次启动建立本目录 runtime/agent.sqlite3，没有复制 FirstAgent 的旧账本。必须通过 HTTP 访问。

## 演示与验证

1. 授权中心分别开启查询、订阅、交易、卡管理，24 小时有效。
2. 转账选择虚构收款人及付款卡，生成预览后明确确认；当日累计超过 1000 元需演示码 246810。
3. 卡管理支持限额、限制、解锁、挂失与申请。卡变更需验证和确认；挂失不可解锁；申请需推进次一模拟日查询审核。
4. 任务与记录统一展示金融操作；失败不扣款，未知先核实原操作。刷新保留状态。
5. 右下角 Agent 支持“给张三转账 800 元”、账单及知识问答。输入“生成普通银行用户场景”，点“生成独立测试场景”；不会覆盖银行账本。

```powershell
python verify_delivery.py
python write_reports.py
```

验证使用临时数据库，已通过 32 项集成及 35 项 JS 检查。报告生成器依据已有验证与额度记录生成文档，不自动查询账户额度。

## 交接文件

- [总版总结](summary.md)、[结构化总结](summary.json)、[统一接口](API-CONTRACT.md)
- 分工改动：[eva](reports/branches/eva.md)、[vv](reports/branches/vv.md)、[YUKI](reports/branches/YUKI.md)、[Ethan](reports/branches/Ethan.md)、[集成](reports/branches/integration.md)
- reports/code_changes.json 与 reports/diffs/：本轮逐文件完整补丁。
- reports/source_inventory_20261023.json：105 个输入的时间、大小及哈希。
- context_log.md/json：步骤、依据、状态及额度；只检查 5h，低于 10% 中止归档。

## 边界

规则解析、演示验证码和本机会话不是生产银行认证。同步 XHR 尚未异步改造；场景不自动导入用户账本；旧聊天和新页面的虚构联系人目录尚未合并。sources 为参考快照，实际运行代码在 first_agent 与 web。详细限制见 summary.md。

结论：SecondAsgent 可独立运行和复测，本轮卡管理、转账及场景整合已交付；真实银行接入由组委会负责。
