# 1027.ver4 接续文档：金融术语与本地模型训练

当前版本 `F:\AI_Banking\AI_Banking_Agent_1027.ver4`，继承1027.ver3，未复制 runtime 或旧数据库；新的项目版本只可放在 `F:\AI_Banking` 直接子目录。继续前先查可信额度；任一额度窗口剩余 <=15% 时停止新业务和 GitHub 写操作，只保存本地交接与八字段审计，然后暂停；暂停后必须用户明确继续并复核额度。仅记录事实、证据和接续方案，不记录私有思维链。

## 本轮要求与已完成

用户要求丰富自然语言助手金融名词知识库、美团入口使用 meituan.com、训练本地模型回答金融问题。保留免费本地模型、不得调用付费 API、不得对未经核实的金融回答放行等先前约定。

- `knowledge/finance_terms.tsv` 为原创中文投教概括：134个名词、10类；不声称涵盖所有可能的金融术语，也未逐条经过专业机构审核。来源按主题关联公开官方投教资料，并非每个链接逐条证明每句话。
- `tools/build_finance_knowledge.py` 生成10份Markdown文档、`knowledge/finance_glossary.json`、清单和RAG索引；`reports/finance-knowledge-build.json` 记录134词、18文档、283索引块。生成220条训练样本和48条保留样本，按术语分组切分；没有客户数据。
- `first_agent/finance_lexicon.py` 对明确释义问题和词条对比进行保守匹配，提供官方同类参考；未知复合词不会因为含有已知短词而被当作对应定义。助手路由及 `/api/knowledge` 实际接入；会继续保留一般RAG和无依据模型结果拦截。
- 美团官网入口在网站面板、日历页面及后台链接中统一为 `https://www.meituan.com/`，不自动读取商户数据。
- 浏览器已实际提问“什么是债券基金”，显示风险提示及参考资料；截图 `reports/finance-answer-browser.png`，并核实网站面板入口为 meituan.com。完整后端157项和前端85项通过；证据见 `reports/latest-integration-tests.json` 与 `reports/latest-frontend-tests.json`。独立HTTP验收 `reports/finance-live.json`：4个金融问法均命中有参考的词条，美团链接正确、账本不变。

## 训练事实与待办

本机CPU完整训练试验已完成：使用全部220条训练样本、48条按术语隔离的保留样本，2轮共56次优化，训练540672个LoRA参数；保留样本平均token损失4.7591975→3.3893964。适配器保存在 `training/lora-finance-qwen05b-full`，报告为 `reports/finance-lora-training-full.json`。样本为原创通用投教概括，无客户数据；未调用付费API。之前24条训练样本、6条保留样本的小试验保存在 `training/lora-finance-qwen05b` 与 `reports/finance-lora-training.json`。

独立生成对照见 `reports/finance-lora-generation-full.json`：对3个未见术语，模型对最短持有期含无关续写、LPR表述不准确且重复、保险等待期定义错误且续写无关内容；因此模型未通过事实评估，损失下降不意味着金融能力可靠。实际应用仍由llama.cpp加载原Qwen2.5-0.5B Q4_K_M，训练适配器尚未转换或部署，词库回答与原有无依据回答拦截不变。

环境 `F:\AI_Banking\local-ai\finetune-venv` 使用 torch 2.8.0+cpu、transformers 4.56.2、peft 0.17.1、gguf 0.19.0。机器有约8GB显存的RTX 5060 Laptop，但GPU版PyTorch下载超时，训练在CPU运行。本地GGUF经transformers解量化加载，SHA256记录在训练报告。训练脚本 `tools/train_finance_lora.py --run-name full --epochs 2` 与生成对照脚本 `tools/evaluate_finance_lora.py --run-name full` 已运行；训练输出目录已存在不会覆盖。数据按术语分割但规模较小，3例生成对照不能代表所有金融问题。

后续先构建更大、更独立且经专业审核的数据集并评估事实、拒答、隐私和安全；考虑更合适本地模型及计算条件。若评估达标，再使用与llama.cpp匹配的官方LoRA转换工具转换并测试，确认执行权限、数据保护和回答质量后才考虑部署，不得关闭安全拦截。参考 https://huggingface.co/docs/transformers/main/quantization/gguf 和 https://github.com/ggml-org/llama.cpp/blob/master/convert_lora_to_gguf.py 。

## 运行及后续

`python start.py` 默认 http://127.0.0.1:8796，最近服务 exec session 39892，模型仍在8794；下次先核验版本、进程和额度。现有 Wind 本地快照、空候选的风险说明、无上传入口、权限分离等保持上轮约束，详见 `HANDOFF_1027_VER3.md`。

后续优先：核查生成对照报告，开展事实、安全评测和llama.cpp适配器转换兼容验证；更新真实部署状态和八字段日志。禁止把所有金融术语或生产安全能力声称已完成，未经正式资料和批准不能实现问卷评分或真实交易。
