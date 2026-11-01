# 2026-10-27 运行版交接：已按15%门槛暂停

最新可信额度主窗口已用85%、剩15%；周窗口已用43%、剩57%。停止新业务/GitHub写入，只保存交接审计。恢复需用户明确继续，先重查额度。此文件取代本目录复制自1026版本的旧交接事实。

## 上下文与授权
用户要求实际连接百度、美团、点评、外部AI；明确不调用付费API，美团/点评可直接跳转官网；免费AI最终指定llama.cpp取代Ollama。不要调用已有DEEPSEEK_API_KEY。当前开发目录F:\AI_Banking\AI_Banking_Agent_1027.ver2，从1026.ver2复制，不含旧runtime；新版本只能在F:\AI_Banking直接子目录。

## 实际完成
- first_agent/external_services.py：真实百度HTTP、h3标题解析、缓存、超时/验证码识别、固定地址/重定向白名单、明显私人信息拦截；llama.cpp本机HTTP适配。
- service.py/server.py：接入knowledge/chat回退；网络请求不持银行SQLite写锁；研究请求独立幂等与审计。解释类问题要求主题在本地证据中，避免“什么是”等通用词导致假命中。
- 新接口：GET /api/external/status，POST /api/external/probe、/api/external/search、/api/local-life/links。既有/api/knowledge实际走回退。
- web/external-services.js/css与index：网站与免费AI面板、搜索/状态入口；planning-market.js事件旁改美团/点评官网链接；journey-workspace助手路由；backend-client研究请求65秒超时；customer-view来源限制展示。
- 原收益曲线、事件预留、Wind XLSX保留。无金融写入、无付费AI调用。

## 安装与运行
官方llama.cpp b11900 CPU包及官方Qwen/Qwen2.5-0.5B-Instruct-GGUF Q4_K_M已下载，发布方SHA256校验通过。F:\AI_Banking\local-ai\llama-installation.json保存路径与哈希。模型491400032字节，sha256=74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db。

应用http://127.0.0.1:8793，最近exec session74565；llama-server在127.0.0.1:8794，alias banking-qwen2.5-0.5b。恢复时核验状态，不依赖session ID。start.py调用start_local_ai.ps1以隐藏窗口启动模型，然后启动应用。tools/install_llama.py可复现安装。

Ollama未安装，相关下载已停止。tools/install_ollama.ps1和local-ai中的未成功下载残留是废弃尝试，不要执行。GitHub普通下载超时，llama.cpp官方资产API成功。

## 验证与必须保留的限制
- reports/release-verification.json：完整回归353项通过（153后端含18新增、85前端、115分析）。此完整回归发生在最后回答拦截修复之前。
- 最后修复后18项external专项再次全部通过，结果见本轮工具输出。
- reports/external-live.json：真实百度验证码状态、真实本机模型响应、幂等重放相同、账本状态完全不变、官方链接正确、付费API调用0。这是最后修复之前的历史证据。
- 小模型在真实测试中错误解释“辛普森悖论”。因此最后修复：没有可核验正文来源时不展示原始模型回答，返回needs_evidence和model_response_received；generation_mode仍记录llama_cpp实际调用。不能把接口连通称为模型答案准确或可靠开放域问答。
- 应用已重启加载最后修复，但尚未再次真实整链验证，也未浏览器验收新面板。
- 百度公开读取目前命中安全验证，无有效搜索结果，无官方API凭据。浏览器手动验证不会自动同步Cookie给后端，不应这样承诺。没有绕过验证。
- 美团/点评依最新用户指示直接跳转官网，无商户API、价格/评分读取、自动预约或下单。
- 本轮未发布GitHub运行代码。上一轮PR#1仅为1027.ver1提示词材料。

## 接续顺序
1. 重查额度及8793/8794状态，确认用户授权继续。
2. tools/verify_external_live.py增加最后回答不含原始模型文本的断言，再执行；当前passed仅证明连接/幂等/账本，不证明答案质量。
3. 浏览器验收网站与AI面板、百度验证提示、商户外链、事件页与助手路由，保存截图。现有85前端测试与语法检查未代替新面板浏览器验收。
4. 更新README/CHANGELOG与最终报告，当前多数仍是旧版复制说明。补八字段日志。发布只上传源码/文档，排除模型/runtime/凭据。
5. 可完善模型服务隔离：当前仅绑定127.0.0.1，但llama-server默认CORS为*。已通过--help确认支持--cors-origins、--no-webui、--no-agent、--api-key-file，尚未配置。应限制来源，必要时使用本地随机token且不进Git。
6. 可靠知识回退仍需可核验正文或更强本地模型加证据约束。当前小模型输出已拦截，不能凭模型记忆生成银行条款、当前价格。

设计依据：先验证连接与来源，再核对隐私及费用；严格区分网络成功、模型响应、事实正确；最后核对账本不变、重试不重复及客户界面清楚呈现受限状态。仅记录事实、决策依据与检查步骤，不包含私有思维链。
