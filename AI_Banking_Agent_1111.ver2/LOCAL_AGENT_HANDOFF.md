# 点评自动化增量包交接

> **接续首选入口：ENGINEERING_HANDOFF_20261114.md（完整工程式交接，2026-11-14 编纂）。**
> 本文件保留为增量史；状态总览、模块契约、治理规则、试点手册以工程交接文档为准。

本目录是独立流程原型与设计交付包，不是完整银行应用，不修改1102.ver3或1111.ver1。
用户规则：城市取客户资料；关键词取个人特殊事件；预算保持客户输入值。
已实现：结构化需求校验、事件关键词规则基线、整数分预算筛选、步骤契约、运行交接自动生成。
未实现：真实页面执行适配器、客户资料页面接线、千问新权重训练、真实端到端验收。不得将模拟通过标记为这些目标完成。
已核验：1102.ver3 first_agent/external_services.py 仅官网跳转；本地Qwen2.5-0.5B GGUF存在，8797端口不监听；历史交接明确适配器质量未改善。
浏览器：Chrome已打开点评首页，显示上海、myInput搜索框、登录入口；点击城市操作超时，状态未确认。未读取任何客户秘密、未提交个人事件原文或定位。
继续先核验开发额度，任一可信窗口剩余≤15%时仅保存本地交接与审计后暂停。额度不属于银行运行功能。
接续：阅读 DESIGN.md；运行 python -m unittest -v；按DESIGN中的映射将真实客户字段接入；完成浏览器适配器并实测；收集脱敏经审核轨迹后再训练与盲测。

## Phase 1 增量（2026-11-12，千问路径去风险，已执行）

- 已实现：qwen_client.py（严格JSON解析+最多一次格式修复+needs_input回退+证据片段本地核对+词表越界标记+max_tokens=512上限+超长首轮跳过修复）；evaluation/gold_set.json 24例合成金标准；evaluate_gold_set.py 两层基线评测；test_qwen_client.py 假服务器测试15项。Phase 0 加固（词库外置/否定基线/六Schema/一键回归）同日完成。
- 服务核验：llama.cpp b11900（local-ai/llama-b11900），model id=banking-qwen2.5-0.5b，local-model.key 鉴权通过，chat template 正常，temperature=0 可用；原权重，无任何适配器。8797 由本版启动，日志在 reports/phase1/llama-server.log。
- 原权重基线（24例，合成）：原始JSON合规率0.125（围栏率0.8333）；围栏剥离诊断合规率0.9167——格式缺口主要是围栏指令不服从，工程可救；修复轮无效；关键词召回0.2391/精确0.0833；否定排除0.0；应澄清召回0.0；误澄清0.0526；1例重复循环已加防护。详见 reports/phase1/金标准基线报告_1111ver2.md 与 gold_baseline.json。
- 结论用途：该基线是 DESIGN §6 训练决策（Phase 4 采集/Phase 5 适配器训练）的量化依据，不是完成声明；未训练、未发布、未接入工作流 keyword_source 仍为规则基线。
- 仍然未实现：真实页面执行适配器、客户资料页面接线、训练与发布、真实端到端验收。

## Phase 2 增量（2026-11-12，只读执行器薄切片，已执行）

- 已实现：executor/ 包——base.py（ExecutionLog 追加只写日志：每行过 execution_log Schema，status=ok 强制证据文件存在+SHA256一致，杜绝伪造成功；verify_state 状态核验；waiting_user 强制墙检测；只读动作一次重试策略）、locator_registry.py（候选定位策略全为假设、运行时重观测、禁止瞬时元素编号）、readonly_actions.py（open_site/select_city/resolve_location/search 只读契约）、run_session.py（prepare/record/finish 三段式，裁决唯一出自代码）。
- 真实会话（reports/sessions/20261112-003808-b9686bfe，run_id=0f8e1e7ee8ac）：open_site 两次尝试（含一次允许重试）均被点评反爬验证墙重定向（verify.meituan.com，action=spiderindefence，"身份核实/验证中心"）→ waiting_user；步骤2-4 未执行，如实记 skipped；未登录、未绕过验证、无写操作。证据链：截图2张、DOM快照2份、run.jsonl、summary.md、steps.json、locator_snapshot.json。
- 实测修复（来自真实证据）：域名判定改主机名（子串包含曾把回调参数里的 dianping.com 误判为已到官网）；FORCE_WALL_KEYWORDS 增补（身份核实/验证中心/spiderindefence）；skipped 裁决透传真实原因。
- 结论：2026-11-11 的"城市点击超时"仍未被观测到——会话在更早的入口就被反爬墙拦截；浏览器适配器完成度仍是"骨架+证据链"，select_city/search 真实执行、城市/搜索页定位符复核均待验证墙放行后进行。
- 仍然未实现：select_city/search 真实执行、客户资料页面接线、训练与发布、真实端到端验收。

## Phase 2 恢复轮（2026-11-12，用户完成验证后复跑，已执行）

- 用户在受控内置浏览器面板完成滑块验证（登录态仅在受控会话内，外部Chrome不共享）。
- run2（20261112-004857-fd485455）：步骤1采集器遗漏 title_nonempty 计算→状态机ABORT有效→已代码化修复：record 落盘前硬校验 observed_state 必须逐键覆盖 postconditions，缺失即拒绝（含回归测试）。
- run3（20261112-005226-ff200a32，run_id=2664c6dc4073）：
  - **select_city 攻克 2026-11-11 历史超时**：根因=点评页面全局阻断 Playwright actionability（元素 isVisible=true 但点击永不满足），cua 坐标派发可真实触发；citylist 选杭州后子域 cookie 隔离致 m 域不变，按控件已验证 href 导航 www.dianping.com/hangzhou→页头读回「杭州[更换]」→ok。
  - open_site（m.dianping.com 移动版首页无墙可达）与 resolve_location（city_only 跳过）通过。
  - search：#J-search-input 输入成功且回读值=生日餐厅，关键词回显与城市杭州均验证成立；提交层契约内机制穷尽失败（按钮 cua 点击/合成 Enter/dom_cua 节点不可达/受信键入+Enter/最近搜索建议项点击均不跳转）→如实 failed+ABORT，未伪造成功。
- 运行时已证实的定位事实（存在会话证据，不回写注册表常量）：m.dphome 搜索框 #myInput；www 城市站搜索框 #J-search-input；城市列表链接模式 a.link.onecity[href=//www.dianping.com/<城市>]。
- 证据链：两会话 11 张截图 + 9 份 DOM 快照 + run.jsonl + summary.md；证据文件含登录昵称，仅本地留存，报告不复述。
- 仍然未实现：search 结果页到达（提交层疑似需 App 级交互或真实用户事件序列，下一步候选：www 移动版 search 页面观察、或以只读方式研究结果页 URL 规律后由用户确认再试）、客户资料页面接线、训练与发布、真实端到端验收。

## Phase 2 收官（2026-11-12，search经用户接管完成，已执行）

- run4（20261112-011106-8e0c06fb，run_id=10dde9e3a3e9，outcome=completed）：用户在受控面板手动搜索「生日餐厅」（DESIGN §4 waiting_user 用户接管路径，合规），执行器只读取证：URL /search/keyword/3/0_生日餐厅（杭州=3）；页头杭州[更换]；搜索框回显；站点自报**1007个相关商户**；样例淀·sediment(人均￥172)/烛屿(￥121)/山海(￥122)——对合成客户600元总额/4人口径，121/122落区间、172超限（filter_candidates 口径）。关键词回显与城市一致由状态机核验 CONTINUE；动作来源如实标注 user_takeover。
- **工程事实（真实操作证实）**：搜索结果URL规律 `/search/keyword/{城市码}/0_{关键词}`（杭州=3、珠海=206）；shop 链接为哈希ID非数字ID；认领的用户标签页截图表面不可用（3s超时），DOM快照为主证据。
- 至此 Phase 2 四步全部闭环：open_site/resolve_location/select_city（攻克历史超时）/search（用户接管+机器取证）。执行器自动化搜索提交仍未打通（真实提交疑似需 App 级交互），已如实记录于 run3。
- 后续候选：① 用已证实的 URL 规律做只读直导航复跑（需用户确认）；② Phase 3 多品类预算分配（纯本地）；③ 把 filter_candidates 接到结果页真实价格数据（价格类型/口径/来源需逐条核验）。

## Phase 3（2026-11-12，预算组合与交接回填，已执行）

- 已实现：`workflow.allocate_budget()`（DESIGN §5 组合层验证：单品类筛选→选最低价候选→换算最坏区间+已知附加费≤预算上限；verdict ∈ within_budget/partial_overlap_needs_confirmation/over_budget/infeasible_with_current_evidence；人数缺失不推定、价格缺失不虚构）；filter_candidates 证据回填（G5：accepted/excluded/unknown 全桶携带分值/口径/price_kind/来源/采集时间/换算结果）；`write_handoff(plan, output, execution_log=None)` 从 run.jsonl 回填执行字段（R6：坏行拒绝不静默跳过、合并执行块后契约自检、无日志如实写 plan_only）；plan.schema 增 execution 可选块；CLI 增 --execution-log。
- 数据：data/observed_quotes_20261112.json——2026-11-12 用户接管搜索后只读采集的真实人均价（淀·sediment 172 / 烛屿 121 / 山海 122，source_kind=observed，注明为页面参考价不保证结算）。
- 测试：test_phase3.py 15 项（证据回填 4 + 组合验证 8 + 交接回填 3）；全量回归 97 项全绿。
- 端到端样例：reports/phase3/20261112-012415-66b93314/——合成客户+真实餐厅价+合成蛋糕占位→within_budget（最优 534/最坏 564/上限 600），所选餐厅烛屿（121×4=484），淀·sediment 688 超界筛除；执行记录回填自 run4 真实 run.jsonl。
- 边界：组合验证为本地逻辑演示；客户合成、蛋糕价合成占位；不是真实端到端验收，不构成购买指令。
- 后续候选：① 用已证实 URL 规律做只读直导航（需用户确认）；② Phase 4 轨迹采集脚手架（R8）；③ search 自动化提交的进一步观察。

## 顺序执行①②③（2026-11-12，已执行）

- ① search 自动化补全（run5：20261112-012739-6a359f8e，completed）：按用户真实操作证实的 URL 规律只读直导航 `/search/keyword/3/0_{URL编码关键词}` → 四步全 CONTINUE（回显+城市+自报 1008 个结果核验通过，1007→1008 活数据如实记录）。表单提交仍未打通（run3 如实留痕）；本机制依赖城市码映射，未证实的城市码不可臆造。执行器修复：record 容忍缺失 started_at/ended_at。
- ② Phase 4 轨迹脚手架（R8）：`training_pipeline.py`（契约入库→PII 扫描隔离→审核 CLI→按客户×事件模板分组防泄漏划分 70/15/15→仅 approved+train 导出 Qwen messages，synthetic/observed 分报）；`evaluation/gates.py`（预算覆盖=0、隐私外发=0 硬门禁）；5 条合成种子全流水线演示（candidate 0/reviewed 5/quarantine 0，export manifest synthetic:5/observed:0）。全量回归 111 项全绿。**600 条真实轨迹采集未开始；训练未执行。**
- ③ 8797 llama-server 已停止，端口释放；Phase 1 基线报告保留于 reports/phase1/，复评需重启服务。
- 后续候选：① 真实轨迹采集（依赖 Phase 2 只读会话与用户授权）；② Phase 5 训练与门禁评测（依赖 ≥600 条已审核轨迹）；③ 客户资料接线（Phase 6）。

## 下一阶段设计编纂（2026-11-12）
新增 NEXT_AGENT_DEVELOPMENT_DESIGN_20261112.md（设计1.0，待实施），包含工作包A-F：运行状态与门禁、数据隔离与金标准标签、客户读取试点、轨迹采集、训练评测、集成验收。接续先读该文档；首项为A。设计建议阈值需正式评测前冻结，不代表既有验收结果。纠正run5口径：open_site/search成功，select_city/resolve_location跳过；不能宣称四动作均实际执行。本轮未改业务源码、未重跑测试或模型。

## 工作包A+B（2026-11-12，按设计文档实施，已执行）

按设计文档执行顺序完成 A、B，全量回归 **150 项全绿**（新增 39 项：A 28 + B 11）。

- **A（运行状态与发布门禁，§4）**：execution_log Schema v2 字段（action_source/execution_method/skip_reason/required_for_goal/postcondition_evidence——每条后置条件绑定证据文件+SHA256+时间+run_id，跨会话证据拒绝；session_end 双结局记录）；record_step 纪律（skipped 无因拒绝、pe 缺键拒绝、证据哈希强校验）；`compute_goal_outcome`（计划必要未记录步骤按 not_executed→blocked；**run5 历史重算=partial，不追认四动作成功，历史文件未改**）；finish 双结局（run_outcome≠goal_outcome，completed 不自动等于 satisfied，summary 附口径纠正）；`evaluate_release_gate(report, policy)` 三态门禁（§4.2 裁决表逐条实现并测试：缺字段/空样本/金额缺失/重复样本充数/指标未达→incomplete；错误推荐超预算或隐私外发→fail；正常排除超价不计错误；不适用须理由+策略允许；策略未配置禁止发布）；plan.budget_fingerprint（含人数口径）+ 交接回填 run_outcome/goal_outcome。
- **B（训练数据契约 v2，§5）**：trajectory_v2.schema（schema_version=2、gold_output 为训练标签且过契约、customer_group/template_family/duplicate_cluster、reviewer_ref/reviewed_at/review_reason、evidence_manifest）；migrate_v1_to_v2（缺分组标 unknown、时间/gold 留空不补造、输入输出哈希报告、原文件只读）；split_reviewed_v2（关联分量图划分：同客户组/同模板族/同近重复簇任一相同即连边，连通分量整体进同一集；缺分组→needs_grouping 不默认占位；split_manifest 含 no_leakage 交集检查+种子+输入哈希）；export_messages_v2（仅 approved+train+gold 过契约导出，gold 作标签；failure_model 未纠正单独计数拒绝；synthetic/observed 分报）。
- 演示：run5 新口径重算=partial；迁移种子→needs_grouping 拒导出；demo-v2 对（failure_model+gold 纠正）→确定性种子 0 入 train→gold 导出成功、无 gold 的成功预测正确拒导。
- **下一轮：工作包 C（customer_source.py 显式记录ID适配器 + 城市映射登记 + 20 次小规模试点）——前置：须与用户确定真实客户来源及记录选择机制；随后 D（600 条采集与冻结）、E（训练门禁）、F（集成验收）。**

## 工作包C本地接口（2026-11-12，按 ZCODE_FEEDBACK_20261112.md 实施，已执行）

按反馈推进 C 的本地可完成部分；真实客户来源未确定仅阻塞真实试点（20次），不阻塞接口开发。全量回归 **173 项全绿**（新增 23 项）。

- **customer_source.py**：`get_customer_snapshot(record_id, source_config)` 五态状态机——needs_input（ID缺失）/ not_found（查无记录，不自动换客）/ duplicate_record（来源内重复ID）/ source_error（配置缺失、路径或JSON非法、类型或 kind 标记不受支持）/ ok。测试来源与真实来源强制分开标记（config.kind ∈ test_fixture/local_real_file），快照携带 source_kind。`build_plan_from_snapshot`：仅接受 ok 快照，计划绑定 customer_ref_snapshot（ref@版本:指纹）+ customer_snapshot_hash + source_kind，plan Schema 同步扩字段。
- **city_registry.py**：城市映射证据登记（必填 city_name/administrative_region/platform_city_code/source_url/evidence_hash/verified_at；同名城市不同码拒绝自动覆盖需人工重核；重复登记拒绝）；`resolve_city_code` 查无映射或证据过期 → needs_city_resolution 不猜测；`verify_city_evidence` 本地证据哈希复验（缺文件/哈希不匹配如实报告）；`build_search_url` 主机受限（仅 www.dianping.com）+ URL编码，杭州构造结果与 run5 已证实 URL 逐字符一致。
- **已登记映射**：仅杭州=3（证据：run5 search-directnav-dom.txt，哈希 e14a9889…，user_takeover+run5 双重证实）；珠海=206 **未登记**（无本地证据文件，仅为会话观察）——resolve 返回 needs_city_resolution，演示不猜测纪律。
- **门禁缺口修复**（反馈第7条）：policy 必填 evidence_freshness_days（证据过期→incomplete）与 allowed_sources（来源白名单强制执行），带回归测试。
- **fixtures 与干跑**：data/customer_fixtures/{test_customers,duplicate_ids}.json（kind=test_fixture，synthetic）；demo_work_package_c.py 合成干跑（明确标注非试点、不计入 20 次真实试点）：显式ID→计划绑定、口径缺失→needs_input、杭州 resolved/珠海不猜测、URL 构造、证据复验无发现。
- **边界与待办**：真实客户来源及记录ID未确定→真实试点（20次、≥2个有证据城市，涵盖正常/缺参/否定/多品类/无结果/验证墙/价格缺失）保持阻塞；合成不计真实。价格采集记录模块（§6 尾）与设备定位未实现。未提交推送Git、未改旧版及历史证据。
- **再下一轮**：D（600 条采集与冻结）→ E（训练门禁）→ F（集成验收）；C 真实试点须用户提供客户来源与记录ID后执行。
