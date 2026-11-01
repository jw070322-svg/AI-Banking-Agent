# 操作摘要接口（本机演示）

入口：`python3 start_review.py`，默认 `http://127.0.0.1:8802/`。

身份沿用服务端 HttpOnly 会话 Cookie。请求体不得指定用户或会话；当前身份只是演示会话，不是真实银行客户身份。校验 Host、Origin、JSON 格式、字段白名单和请求大小。浏览器不能提交“交易成功”或“服务端结果”。

| 方法 / 路径 | 请求 | 作用 |
| --- | --- | --- |
| GET `/api/experience/status` | 无 | 开关、授权代次、记录数量与范围 |
| POST `/api/experience/consent` | `{"enabled":true}` 或 false | 独立开启/撤回摘要记录；不授权交易 |
| POST `/api/experience/events` | `{"epoch":"服务端返回的UUID","events":[{"event_id":"UUID","action":"filter","page":"wealth"}]}` | 每批1–30条，仅接受界面观察 |
| POST `/api/experience/query` | `{}`，可选 `source`、`status`、`action` | 本会话最近100条；关闭后拒绝检索 |
| POST `/api/experience/feedback` | `{"event_id":"UUID","rating":"helpful"}` 或 incorrect | 本人摘要的反馈，不触发知识发布 |
| POST `/api/experience/delete` | `{"confirmation":"删除操作摘要"}` | 删除摘要、反馈和关联，关闭记录并轮换代次 |

统一返回原项目 envelope：schema_version、request_id、status、data、error、trace、simulated。新增接口只改变摘要状态；不得当作银行资金操作接口。

允许页面：overview、spending、wealth、tasks、other。客户端 action 白名单见 `review_additions/experience.py` 的 CLIENT_ACTIONS；没有任意正文、金额、收款人、手机号、卡号、密码、验证码或模型原文参数。未知字段整批拒绝。

事件幂等键为 `(服务端会话,event_id)`；相同事件重传不增加记录，同编号不同内容返回409。授权撤回、重新开启或删除都会轮换 epoch，旧队列不能重新导入。提交时间由服务端生成，不能由浏览器冒充。

`source=client_observation` / `status=unverified` 只说明收到界面行为。`source=server_result` 只能由应用服务包装层产生；保留处理中、结果未知、拒绝、取消等区别。请求尝试和结果通过 xp_attempt_results 关联；已返回结果的开始步骤不重复显示，重试尝试仍可在数据库追查。它不是银行清算凭证。

后台数据和摘要使用同一 SQLite 文件中的不同表，不另建余额。可选摘要写入故障不把已完成业务改报成失败；原银行审计仍随业务事务提交。进程崩溃可能留下开始而无结果的摘要，应以任务回执核对，不能重放扣款。

界面队列保存在 sessionStorage，最多100条；服务端保留本会话最近1000条摘要。不能保证断电、强制退出、清除浏览器数据时零丢失。删除不删除银行账单、原始请求回执和必要银行审计。没有提供合规保存期限承诺或不可篡改审计能力。

`GET /review/source/{document_id}` 仅打开当前知识索引白名单中的原文；必须有有效会话，路径限制在 knowledge，并检查文件哈希。`citation_uri` 提供这个可打开的引用；原 `source_uri` 和 `original_citation_uri` 保留来源线索。

## 人工审阅版本工具

`python3 -m review_additions.releases --operator reviewer current` 查看当前审核材料版本。propose、approve、publish、rollback 子命令参见 `--help`。审批需要另一标识、实际评测报告、显式人工核对声明；引用必须是已有知识库片段且原文、行号、哈希一致。

这是本地操作者工具，无网页发布端点。操作者名称仅是本地审计标签，未接入组织认证，不能证明两名独立自然人完成审批。版本发布仅管理审核材料，不自动更改在线RAG知识库、工具权限或模型权重；生产知识更新仍需小组独立核验。
