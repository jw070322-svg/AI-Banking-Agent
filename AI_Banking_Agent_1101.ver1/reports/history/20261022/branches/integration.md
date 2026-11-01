# 集成 / 编排与交付：代码修改明细

记录范围：首次集成已实施修改及本次文档补全。依据、修改与验证先列，结论置于末尾。原输出目录未改；共享 service.py 按职责分别说明。

## 架构补位依据与修改边界

原 Orchestrator/agent_orchestrator.py 为 0 字节，eva 编排包又缺关键依赖，不能直接拼接运行。新增 FirstAgent 集成包，用 vv 业务引擎作为唯一模拟账本规则来源，以 SQLite 持久化状态，接入 eva 校验、项目推荐与 RAG。原始协作产出不回写；P01/P03/P04/P05/P06 的来源见 [reports/patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)。

## 新增服务与逐方法改动

[first_agent/service.py](<F:/AI_Banking/FirstAgent/first_agent/service.py>) 整体为新增集成实现，按职责拆分如下；安全细节见 eva，推荐细节见 Ethan，知识接入见 YUKI。

| 方法/常量 | 已实施内容 |
|---|---|
| SCHEMA / POLICY_VERSION / METHODS / READ | 固定响应版本与演示策略版本，限制 RPC 方法白名单及读取动作权限。 |
| canonical / digest / stamp / integer / Fault | 稳定 JSON、哈希、UTC 审计时间、整数分校验、统一业务异常。 |
| __init__ | 检查 Node；创建 sessions/requests/audit 表；用 closing 关闭初始化数据库连接，修复 Windows 句柄占用；初始化 RAG 和安全 gate。 |
| connect / transaction | SQLite WAL、20 秒等待、BEGIN IMMEDIATE；成功 commit、异常 rollback、finally close，串行化共享数据库的修改。 |
| engine / engine_call | subprocess 参数数组启动 Node worker，JSON stdin/stdout，15 秒超时；接收新状态和业务结果；策略错误需保留的锁定/失败计数显式持久化。 |
| create_session / load | 服务端随机会话，当前演示客户 CUST-001；初始化 transfer_ops/daily_transfers/task_log/clarification；无效会话拒绝。 |
| audit / envelope / require | 参数脱敏后同事务写审计；统一 schema_version/request_id/status/data/error/trace/simulated；scope 与客户资源检查。 |
| call | 哈希绑定 action+args；同会话同幂等键同请求返回原响应，改参冲突拒绝；业务异常按 persist 标志保留或恢复状态；状态、审计、幂等响应一起提交。 |
| pending / bound_hash / attach / check_pending | 定位当前会话操作、预览绑定、300 秒 TTL 与失效检查。 |
| invalidate_transfers / pending_from_engine_assertion / public_state | 转账预览失效同步；引擎红色操作补充断言过期检查；快照移除 session_id 和嵌套 assertion。 |
| dispatch | 白名单 RPC、snapshot、accounts、transactions、subscriptions、recommend、knowledge、转账全流程、operation、chat、events 分发；最多返回当前会话 100 条审计；没有动态执行任意工具。 |
| transfer_policy / transfer_preview / transfer_confirm | 临时 eva 校验适配唯一余额；创建绑定预览；明确确认和模拟断言；success/failed/unknown 三种结果。 |
| apply_transfer / transfer_reconcile | 外部转出同步账本总额、累计、回执和账单；unknown 核实原操作后记账，不重复发起。 |
| recommendations | vv 目录和 profile 转原推荐契约，金额/风险/期限与执行侧保持一致。 |
| chat | 1–2000 字符、输入扫描、他人账户关键词拒绝；转账姓名/金额缺失或多个候选时澄清并持久保存；取消待澄清请求；账户、账单、订阅、推荐多工具只读编排及 plan/depends_on；其余进入知识检索；对话不自动扣款。 |

## HTTP 服务、浏览器与启动文件

| 文件/区域 | 新增或修改内容 |
|---|---|
| [first_agent/server.py](<F:/AI_Banking/FirstAgent/first_agent/server.py>) / make_server | 标准库 ThreadingHTTPServer，默认仅 127.0.0.1；封装 Handler，主入口提供 --port/--db。 |
| send_json / sid / safe_host | UTF-8 JSON、no-store/nosniff、HttpOnly/SameSite=Strict cookie；会话读取；本机 Host 与 Origin 校验。 |
| do_GET | health、snapshot、账户/账单/订阅/产品/审计、operation 路由；静态文件解析后必须仍在 web 内，防止路径穿越。 |
| do_POST | application/json、1–65536 字节、根对象及非有限数字校验；session 复用有效 cookie；其他 POST 强制 Idempotency-Key；异常不输出内部堆栈。 |
| [first_agent/engine_worker.cjs](<F:/AI_Banking/FirstAgent/first_agent/engine_worker.cjs>) | Node 服务端执行原 vv 引擎；每事务一请求，详见 vv 文档。 |
| [first_agent/security.py](<F:/AI_Banking/FirstAgent/first_agent/security.py>)、vendor 各包 | 新 scanner 外层修复、包结构补齐及原有组件适配；原样复用与逻辑修改在各分工中分开记录。 |
| [first_agent/__init__.py](<F:/AI_Banking/FirstAgent/first_agent/__init__.py>)、[first_agent/vendor/__init__.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/__init__.py>) | 新增包入口，使 python -m first_agent.server 可执行。 |
| `run_agent.ps1` | 定位自身目录后运行 python -m first_agent.server --port 8765。 |
| `README.md` | 运行环境、启动和验证方法、会话持久化、模拟验证码、交付入口及已实现边界。 |
| `API-CONTRACT.md` | 统一整数分、天/月转换、模拟/真实时钟、响应结构、权限、幂等、HTTP 路由、RPC 白名单、状态机与失败/未知语义。 |

## 验证代码与实际验证范围

[tests/test_integration.py](<F:/AI_Banking/FirstAgent/tests/test_integration.py>) 为新增集成测试，使用临时 SQLite、可注入时钟、线程与进程池及 HTTP cookie 客户端；不以真实银行为依赖。共 20 项：默认拒绝/未知工具；跨会话隔离；单账本幂等持久恢复；金额及归属；累计红色验证；预览过期/撤权/暂停；未知阻断和核实；线程只提交一次；多进程只提交一次；订阅取消与申购同账本；申购断言超时回滚；赎回恢复及结算；RAG 证据/无证据/无副作用；ZIP 恢复资料入索引；多轮多工具；歧义金额；推荐一致性/缺档案；脱敏保留哈希；三次失败锁定；HTTP cookie/Origin/静态文件/刷新。

[tests/vv_core.cjs](<F:/AI_Banking/FirstAgent/tests/vv_core.cjs>) 沿用 15 项规则检查，修改加载路径和六个月结算边界；详见 vv。`verify_delivery.py` 新增统一运行入口，收集 Python 与 Node 结果，生成 integration-tests.txt、vv-tests.json、verification.json；失败返回非零退出码。

既有报告为 20+15 项通过，验证时间见 [reports/verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)；浏览器额外验证模拟转账、账单联动、刷新和服务重启持久恢复、知识引用。当前文档续作未重新运行业务测试，不能把旧时间标成新的测试时间。

## 来源盘点、报告与本次文档修改

- [.work/build_first_agent.py](<F:/AI_Banking/.work/build_first_agent.py>)（位于项目根目录）是首轮组装脚本：盘点 output、选择并复制来源、解压与整理运行资产。它不是最终增量迁移器，重跑可能覆盖后续修复，交接时应以 FirstAgent 当前代码为准。
- sources/ 保留各分工参考快照；source_inventory 记录源文件时间、大小、哈希；archive-comparison、vv-style-comparison、yuki-archive-recovery 记录内容比较及恢复事实。
- `write_reports.py` 生成总版、上下文、补丁映射、各分工文档和交付哈希清单。本次接入 `write_branch_details.py`，使重新生成报告也能保留逐文件明细、原样复用表和实际源差异。
- `write_branch_details.py` 为本次新增文档生成代码：按职责记录所有新增方法及改动，直接比较参考源/运行文件生成 diff；复用文件同时核验 SHA-256；自动链接本地文件。
- 本次修正 YUKI 已恢复资料仍写缺失的问题，并明确卡管理尚未接入；同步真实银行由组委会接入的交付边界。
- 额度规则按用户最新指示仅监测 windowDurationMins=300 的 5h 窗口；剩余严格小于 10% 停止，周额度不参与停止。工具只提供采样快照，不能宣称实时推送。历史周额度中止仍保留为历史记录，当前规则覆盖旧规则。
- context_log.md/json 保存此前中止记录及续作，summary.md/json 和五份分支文档同步；file_manifest.json 在报告写完后重建，不包含 runtime、缓存及清单自身。

## 后续边界与责任

团队交付本地模拟银行 API、清晰接口契约和可替换接入边界；组委会负责真实银行部署接入。现有 service.py 仍直接组合 MockBank 与 Node，并没有已经完成的独立 BankAdapter 插件系统，不能把可替换设计目标写成已存在的类。

尚未实现完整卡管理、手机号/定时/AA 转账、自动订阅识别提醒、生日商户联动及开放式模型。卡管理建议 eva 负责后端、vv 负责界面、集成负责编排安全、YUKI 负责说明与验收；Ethan 原职责待确认。同步 XHR、有限规则理解、演示会话认证和本地审计均有明确适用范围。

## 可核对的来源差异

service.py、server.py、security.py、engine_worker.cjs、HTTP 集成测试及交付脚本均为新增集成文件；不存在完整旧实现可作逐行 diff。新增职责已在前文逐方法列出。

## 测试与报告入口

此前验证报告：[verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)；浏览器证据：[browser-verification.json](<F:/AI_Banking/FirstAgent/reports/browser-verification.json>)。本次只核对来源、文档覆盖和报告生成，不冒称重跑业务测试。

统一接口：[API-CONTRACT.md](<F:/AI_Banking/FirstAgent/API-CONTRACT.md>)；补丁来源：[patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)；交付文件哈希：[file_manifest.json](<F:/AI_Banking/FirstAgent/reports/file_manifest.json>)。

结论：本分工的已实施修改、原样复用、补丁来源、接口影响、验证依据与尚未完成项已分开记录；后续协作以当前 FirstAgent 代码及统一契约为准。
