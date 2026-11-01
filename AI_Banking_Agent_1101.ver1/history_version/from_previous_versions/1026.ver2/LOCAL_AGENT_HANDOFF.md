# 本地 Agent 交接 / AI_Banking_Agent_1026.ver2

## 当前增量上下文

用户最新两项要求：继续修正金融产品收益曲线，并把产品换成银行常见理财。已在本目录完成，基于同父目录 AI_Banking_Agent_1026.ver1 复制，未改原版。见 CURVE_FIX_1026.md 的产品表、精确计算口径和UI证据。

修改集中在 web/journey-engine.js（目录、风险标签、每日预演）、web/projection-chart.js/css（收益坐标、视图、光标与键盘读数）、web/journey-workspace.js（产品卡、独立参数、可见曲线）、web/index.html；新增 tests_frontend/return_chart.cjs 的13项测试，旧期限测试改用明确的R2测试档案。金额仍以整数分处理。已有每月API返回结构兼容，新增day/principal/recovered字段和frequency=daily选项。

复核顺序：先按 CURVE_FIX_1026.md 核对365/360口径（本项目固定360模拟日），再用相同输入独立计算终值；核对UI金额/收益率和月末点；再检查风险、期限、可配置资金；最后查资金守恒及授权链。波动区间不是概率区间，不能添加随意波动冒充净值。每日现金流是月预算的线性插值，图仅绘制投资价值；实际入账时点由现有advance处理。

最新结果：135后端、85前端、115分析模块通过。UI实测现金32.61元收益、负收益-384.29元、90天纯固收25.22元及90天后的平线；切换产品不沿用上一个输入。Wind默认参数仍是手工情景，不是历史数据拟合。真实产品接入应先取得Wind净值和正式条款，再决定映射，不可用内部演示ID替代真实证券代码。

最近额度查询主窗口剩12%、周窗口剩73%，已触发用户设定的15%门槛，本文件和日志已更新。后续若任一窗口剩余低于15%，立即刷新本文件和八字段日志；只写上下文、事实、设计依据和可执行步骤，不记录私有内部推理。

## 用户约定
继续用户给的更新版，验证已改和未改；两种日历（本地、Google）同时保留；每次开页扫描未来7天特殊事件，询问预算，预留同步现金流和金融推荐；支持Wind XLSX真实读取、宏观与板块分析、指数展示；完善自然语言、日期推进、收益曲线；保留八字段创作日志。

**最新保存门槛为可用额度剩余15%（用户2026-10-26明确修改，取代10%）。** 任一可用额度窗口低于15%时即保存交接与日志。保存不等于停止任务。曾在剩余8%时已保存；后续窗口刷新，任务继续。本文件给出事实、设计依据、验证步骤，不依赖内部推理。

## 交付路径与基底
唯一工作目录：`F:\AI_Banking\AI_Banking_Agent_1026.ver2`。
最初基底：`F:\AI_Banking\Banking-整合版-修复(1)\Banking-追问填表版`，未覆盖原件。早期 `F:\AI_Banking\AI_Banking_Agent_1025.ver1` 已弃用，不应从那里继续。
没有Git管理；不再派生子代理。本地服务默认127.0.0.1:8790，独立Cookie banking_session_1026_v2。运行 `python -X utf8 start.py` 或启动网页.bat。最近服务exec session6566，Chrome验收页1015964992；这些ID可能失效，应以新状态为准。

## 完成状态与证据
本轮本地开发和自动化/UI验收完成。最终135后端、85前端、115金融分析模块测试全部通过。统一 `python -X utf8 verify_delivery.py`；机器报告 reports/release-verification.json；分项 latest-integration-tests.json、latest-frontend-tests.json、release-analysis-module.txt。

浏览器已实测：事件新增/编辑；重开页面预算气泡；预留1000元后可配置3640→2640；释放/再次预留；刷新持久；样本XLSX读取5产品1325净值3指数2宏观；候选收益23.93元（合成现金产品，2640元本金180天历史年化延续）；夏普解释；名录小王/林晓/陈晨/张三/李四/王五（后者未准入）；预演年收益-20%半年2640→2361.29；现金流显示事件预留1000、期内活动1000、剩余预留0，未重复扣减。

截图：reports/calendar-bubble-ui.png、market-ui.png、market-recommendation-ui.png、preview-negative-ui.png。XLSX各表渲染并检查在 reports/workbook-previews。开发日志 development_log.jsonl；前端可导出本会话八字段操作日志。

## 核心架构
- Python stdlib HTTP + SQLite是唯一权威状态；Node web/journey-engine.js共用金融状态机。保留转账追问填表、确认、授权、幂等及未知结果核对。
- first_agent/extensions.py：日历、预算、画像、知识名录、市场和日志路由。配置失败原子回滚，预留替换/重放不累加，修改资金使待确认失效。
- calendar_provider.py：本地日历与可选Google只读适配；按上海日期未来7天读取、分页/时区/取消事件处理；凭据只在服务器环境变量；失败缓存不冒充新同步。
- market_data.py：标准XLSX ZIP/XML解析，限制大小/行数/列数，拒绝公式/宏/外链/损坏文件；真实数值保存。总回报口径区分扣费和未扣费；年化、波动、夏普、回撤；排除未来/过时/不足数据和不可表示结果。宏观PMI与指数防守规则、板块过滤；无真实市场输入时明确合成。
- web/planning-market.js/css：独立日历画像/市场面板，预算气泡、本地事件编辑、Google状态、样本和上传、指数宏观、量化候选、日志导出。请求忙时按钮禁用，连接失败有可见反馈。
- journey-engine.js：逐日工资/支出、持仓复利估值；余额不足不扣款。守恒 total+externalOut=initialTotal+externalIn。预演包括复利/负收益/波动敏感性带，固定期结算后才回现金。
- analysis_bridge.py将事件预算映射到budget锁定额和activity_calendar；月度收支映射cashflow_assumptions。分析模块cashflow.py/budget.py据此模拟未来收支，月度预算已含订阅，避免二次计费；流动性模块对计划活动与剩余预留只计一次。customer-view.js显示对应预留拆分。
- service.py不把整套market_data发送到Node；snapshot只公开状态摘要，上传base64不写审计日志。server.py有导入大小上限、模板下载白名单。start.py默认8790。

## 设计与检查框架
以唯一账本/授权链为先；现金、持仓估值、计划预留分开；无数据/授权时明确缺失；推荐先看个人风险/期限/资金再看收益；未来数据按发布日期隔离；一切数学结果可独立回算；不能将合成数据、历史外推、手工阈值称为真实行情或预测。金融分析的每月新增投资空间与当前目标可配置存量是不同指标，UI有各自口径；Wind候选研究使用当前可配置存量，非自动交易建议。

## 明确边界及下一步所需外部输入
1. Google：适配器及模拟测试已完成，但没有真实账户凭据，没有OAuth登录回调UI。用户需按GOOGLE_CALENDAR.md配置只读token或refresh token；配置前始终显示未连接。多用户部署必须先隔离凭据。
2. Wind：已实现模板文件接口，不是Wind终端实时API。等待用户提供真实数据；清单见WIND_DATA_REQUIREMENTS.md。仅CNY，无杠杆/汇率模型。规则阈值未回测优化，没有组合权重优化/完整交易成本。
3. 美团：只有官方入口及按城市品类搜索链接，无自动商户价格读取或下单。
4. 自然语言：增强的是本地规则/知识库和业务工具路由，不是开放域大模型；未支持的复杂意图应说明范围，不假装执行。
5. 模拟时间：开发者工具推进账本日期，页面日历使用真实上海日期。关闭页面后没有后台任务。真实日历预算过期不自动释放，需用户手动处理。

## 继续工作的注意事项
PowerShell，使用python -X utf8避免MSYS/GBK编码。测试临时SQLite/localhost socket若被sandbox阻止，按工具require_escalated审批，不绕过。tools/upgrade_engine.py、integrate_extensions.py、upgrade_preview.py是已执行的一次性改造记录，不可重跑。工作簿生成用artifact-tool，运行银行服务不需要该依赖。

需要增量改动时先读取VALIDATION_1026.md，按上面的测试和界面路径验证，不重做基线。敏感凭据不写源码、表格、日志。创作日志每条严格使用user_id/intent/tool/input/output/risk_check/approval/timestamp八字段。保留原始目录；新版本按用户指定AI_Banking_Agent_MMDD.verN命名。


## 2026-10-26 路径迁移

用户要求的本版本文件夹已移至 `F:\AI_Banking\AI_Banking_Agent_1026.ver2`。今后的新版本只能创建在 `F:\AI_Banking` 直接子目录，见根目录 AGENTS.md。原来源包和旧ZIP保留。移动保持源码、数据库、会话和历史日志；只追加迁移记录。旧服务进程及exec session已停止，启动时从新路径运行start.py；ver1端口8789、ver2端口8790。


## 额度门槛交接（2026-10-26T11:46:02.541168+00:00）

主窗口剩余12%，周窗口剩余73%，已按低于15%的约定保存。当前任务已完成：两个1026版本均从来源目录移到F:\AI_Banking直接子目录，分别586/593个文件在移动前后数量一致；随后仅追加了文档和日志。两版健康接口ready=true，分析模块directory均指向新目录。ver2服务端口8790，当前exec session 68092；运行ID可失效，下次以健康接口及进程状态为准。

接续约束：新版本只在F:\AI_Banking直接子目录创建；以ver2为最新代码，保留ver1；不要从旧路径继续或重建嵌套版。用户要求的常见银行理财替换与曲线修复已完成，细节及335项验证见ver2的CURVE_FIX_1026.md。下一步等待用户新需求或真实Wind数据；不要把虚构预演参数标为真实银行收益。检查框架：先核对目录和版本健康状态，再核对数据来源/单位/时间口径，按风险与可用资金约束验证业务，最后核对数值与UI一致性。


## 更新日志交接（2026-10-26T15:50:59.937056+00:00）
用户要求为 GitHub 项目大致整理更新日志。已读取远端 README（仍为2026-10-20说明），并依据本地核验文档写入本版本 CHANGELOG.md，区分ver1功能补齐、ver2产品/曲线修复和待接入项。本次未推送GitHub或修改远端仓库。额度主窗口已用100%，周窗口已用29%；按15%保存门槛立即更新交接和八字段日志。当前文档任务完成；如用户后续要求发布，应先核对代码是否同步，避免远端说明超前于代码。
