# 两种日历同时保留

项目内日历可直接添加事件、日期、城市；Google 日历有独立只读适配器，二者一起参与未来七天预算提醒。没有配置 Google 凭据时明确显示未连接，本地日历照常可用。当前交付没有真实 Google 凭据，因此只完成模拟接口测试，尚未完成真实账号联调。

服务器支持两种授权配置，凭据请用环境变量提供，不要写入源码、xlsx 或日志：

- 临时联调：`BANKING_GOOGLE_ACCESS_TOKEN`。
- 持续使用：`BANKING_GOOGLE_CLIENT_ID`、`BANKING_GOOGLE_CLIENT_SECRET`、`BANKING_GOOGLE_REFRESH_TOKEN`。
- 可选：`BANKING_GOOGLE_CALENDAR_ID`，默认 `primary`。

Google Cloud 项目须启用 Calendar API，并由日历所有者完成 OAuth 授权，范围使用 `https://www.googleapis.com/auth/calendar.events.readonly`。本版提供令牌消费与刷新，**未提供浏览器 OAuth 登录和回调页面**。配置后重启 `python -X utf8 start.py`。仅为本机单人演示；多用户部署必须先实现用户独立凭据存储和权限隔离，不能共享服务器级凭据。

每次页面加载通过 `POST /api/page/open` 读取一次，范围为上海时区今天00:00到第7天00:00（结束不含）。Google端展开重复事件，处理分页、全天事件、时区、取消事件。生日、纪念日、聚餐、婚礼等关键词识别特殊事件；其他事件仍可查看。失败时展示失败状态，缓存不用于本次提醒。不是后台定时扫描，关页后不运行。

提醒只询问，不自动划款。客户确认预算后减少可投资额度，重复提交不重复累加；释放后恢复额度；过期预留保持到手工释放。预留属于资金计划，不是银行账户冻结。已有必要用款若包含同一事件，请调整「其他必要用款」避免重复计算。

美团部分保留餐厅、蛋糕、花店搜索入口和官方美食入口，只在点击时把城市和品类放入外部搜索，不传事件标题或预算。尚未接入美团 API 或自动读取商户价格，不进行下单。

接口依据：[Google events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)。
