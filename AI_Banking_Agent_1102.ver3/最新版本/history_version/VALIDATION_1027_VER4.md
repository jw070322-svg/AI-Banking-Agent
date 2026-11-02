# 1027.ver4 金融知识与本地训练状态

## 已实现

`knowledge/finance_terms.tsv` 收录134个中文金融术语、10个主题；包含别名、原创通俗解释和风险边界。`tools/build_finance_knowledge.py` 为10类生成Markdown、结构化词典、训练/保留数据及索引。18份来源文档共283个索引块；官方投教材料按主题提供延伸参考，并非每条解释都已由机构逐字核验。金融术语范围开放，本版未覆盖全部术语，未知内容保留现有拒答/缺证处理。

`first_agent/finance_lexicon.py` 仅对明确的术语释义、比较和裸词执行匹配，优先长词，遇未知复合词不以相近短词冒充；`first_agent/service.py` 和 `extensions.py` 将其接入知识接口和自然语言助手。一般业务、账户查询和写操作仍走原有权限及确认流程。术语知识解释不代表当前产品条款、实时利率、个人适当性或交易建议。

美团网站入口改为 `https://www.meituan.com/`，覆盖网站面板、日历商户入口和后台返回；大众点评入口不变。该官网不等于商户API，不承诺价格、库存或预约可自动获取。

## 验证

- `reports/latest-integration-tests.json`：157项后端通过；`reports/latest-frontend-tests.json`：85项前端通过。此前完整回归因旧测试预期与新索引不一致而失败，调整测试为同时验证旧资料存在和新术语引用后重跑通过。
- `tests/test_finance_knowledge.py` 对每个词条的两个问法、别名比较、未知词、交易语句及本地助手接口进行检查；该检查验证映射，不能证明134条解释的全部事实均正确。
- 浏览器实际输入“什么是债券基金”，展示通俗解释、风险提示和官方参考，见 `reports/finance-answer-browser.png`；网站面板显示美团官网链接。
- `reports/finance-live.json` 以独立演示会话验证4种问法、参考资料、美团官网链接和账本不变。
- 现有数据权限、无网页上传Wind、需确认的对外搜索和金融交易确认不因词库而改变。

## 模型训练：完整数据实验已完成，尚未部署

数据分为220条训练样本和48条按术语隔离的保留样本，均为通用投教资料，不含客户数据。完整实验使用全部220条训练、48条保留，CPU训练2轮、完成56次优化步骤，训练适配器见 `training/lora-finance-qwen05b-full`。保留集平均token损失4.7592→3.3894，详见 `reports/finance-lora-training-full.json`；这是损失指标，不是事实正确率或安全认证。

`reports/finance-lora-generation-full.json` 对三个保留问题做了训练前后实际生成对照：模型对最短持有期的回答含无关续写，LPR存在表述不准确且重复，保险等待期定义错误并重复无关内容。因此适配器尚未转换或部署。较早的小样本试验及其错误见 `reports/finance-lora-training.json` 和 `reports/finance-lora-generation.json`。

用户实际看到的金融解释仍来自有参考的词库；原版Qwen2.5-0.5B GGUF的无依据回答仍被拦截。未调用付费API。

当前仅为本机演示，不代表银行生产安全认证。问卷正式评分、真实客户适当性和网络隔离仍未完成。
