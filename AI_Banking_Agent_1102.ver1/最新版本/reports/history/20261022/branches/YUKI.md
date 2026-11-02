# YUKI / 知识与评测：代码修改明细

记录范围：首次集成已实施修改及本次文档补全。依据、修改与验证先列，结论置于末尾。原输出目录未改；共享 service.py 按职责分别说明。

## 选版、缺失判断及补丁依据

1022 最新 ZIP 有 19 个有效文件，已有解压目录只有 15 个；仅看解压目录会误判三篇知识缺交。排除 __MACOSX 后从 ZIP 恢复现金流、储蓄率、流动性及银行业务知识库说明。恢复的是队友已交付内容，不是集成时编造的银行知识。原目录未改。

原 simple_RAG 会给无关文档附加分数，长中文句子的检索和来源表示也不足。保留它作为参考源码，实际运行复用项目 RAG/banking_rag，使用 BM25、中文双字分词和可核查证据。补丁编号 P05。

## 逐文件与逐模块记录

| 文件/目录 | 处理方式 | 已实施内容 |
|---|---|---|
| [sources/YUKI/](<F:/AI_Banking/FirstAgent/sources/YUKI>) | 来源快照及 ZIP 恢复 | 保存 README、说明、评测题库、simple_RAG.py 和资料原件；历史乱码文件保留用于核对，不全量直接扫描进运行知识库。 |
| [knowledge/01-现金流.md](<F:/AI_Banking/FirstAgent/knowledge/01-现金流.md>) | 从 ZIP 补回 | 原解压目录缺失，按正文标题恢复可读文件名；原文字节及哈希保留。 |
| [knowledge/02-储蓄率.md](<F:/AI_Banking/FirstAgent/knowledge/02-储蓄率.md>) | 从 ZIP 补回 | 同上，已入索引，不再列为缺失主题。 |
| [knowledge/03-流动性.md](<F:/AI_Banking/FirstAgent/knowledge/03-流动性.md>) | 从 ZIP 补回 | 同上，已由自动化及浏览器验证检索。 |
| [sources/YUKI/docs/银行业务知识库.md](<F:/AI_Banking/FirstAgent/sources/YUKI/docs/银行业务知识库.md>) | 从 ZIP 补回 | 恢复资料总说明，作为交接来源文档，不计为第九篇运行知识。 |
| [knowledge/04-债务比率.md](<F:/AI_Banking/FirstAgent/knowledge/04-债务比率.md>)、[knowledge/05-风险管理.md](<F:/AI_Banking/FirstAgent/knowledge/05-风险管理.md>) | 规范运行副本文件名 | 按正文标题命名，保留最新原文；未改写公式或添加现实银行规则。 |
| [knowledge/06-合规边界.md](<F:/AI_Banking/FirstAgent/knowledge/06-合规边界.md>)、[knowledge/07-订阅管理.md](<F:/AI_Banking/FirstAgent/knowledge/07-订阅管理.md>)、[knowledge/08-旅行预算.md](<F:/AI_Banking/FirstAgent/knowledge/08-旅行预算.md>) | 规范运行副本文件名 | 同上，总计八篇显式入库资料。 |
| [knowledge/manifest.json](<F:/AI_Banking/FirstAgent/knowledge/manifest.json>) | 新增清单 | 为八篇文档登记 id/path/title/kind/revision/source_uri/sha256/valid_from/valid_until；来源精确到 ZIP 内 entry，kind 标为 educational_demo，未确认的有效期保留 null。 |
| [knowledge/index.json](<F:/AI_Banking/FirstAgent/knowledge/index.json>) | 构建索引 | 由显式 manifest 建索引，保留分块、行号、文档哈希及检索信息；文件名恢复不改变原文哈希。 |
| [first_agent/vendor/rag/corpus.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/corpus.py>) | 原样复用 | 显式资料导入、哈希校验、路径检查、保留行号分块及索引写入。 |
| [first_agent/vendor/rag/retrieval.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/retrieval.py>) | 原样复用 | BM25 和中文检索；不是本轮重写排序算法。 |
| [first_agent/vendor/rag/service.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/service.py>) | 原样复用并接入 | 离线摘录、grounded/no_evidence、业务数据边界及引用结构；本次没有配置生成模型客户端。 |
| [first_agent/vendor/rag/providers.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/providers.py>)、cli.py、__main__.py、__init__.py | 原样保留包内容 | 保持原项目包结构及可选扩展入口；不代表已经启用外部模型或逐个 CLI 验收。 |
| [first_agent/service.py](<F:/AI_Banking/FirstAgent/first_agent/service.py>) | 新增业务接线 | 初始化 RAGService；缺 index 时按 manifest 构建；knowledge 动作调用 ask 并添加教育演示提示；chat 非业务查询回退到知识检索。 |
| [web/agent-panel.js](<F:/AI_Banking/FirstAgent/web/agent-panel.js>) | 共享前端展示 | 展示回答、证据与引用 JSON；界面实现归 vv，资料正确性由 YUKI 维护。 |

## 接口与能力边界

- `POST /api/knowledge` 输入 question/top_k，金融响应外壳与 RAG 的 data.status 分开；引用包含来源、文档哈希及行号。没有依据时返回 no_evidence，不编造答案。
- 个人余额/交易事实通过业务工具读取，知识资料不会触发转账或写操作。chat 的规则仍按关键词路由；例如含“现金流”的问题可能进入账单工具，并未实现任意语义问题分类。
- 运行资料由 manifest 显式选取，sources 中乱码/可读双副本不会重复入库。八篇原文列表和逐项哈希见 [knowledge/manifest.json](<F:/AI_Banking/FirstAgent/knowledge/manifest.json>)；四个恢复文件及完整 ZIP entry 清单见 [reports/yuki-archive-recovery.json](<F:/AI_Banking/FirstAgent/reports/yuki-archive-recovery.json>)。

## 验证与后续交接

既有 test_rag_sources_no_evidence_and_no_side_effect 覆盖原文引用、无关问题和不改余额；test_recovered_archive_knowledge_is_indexed 覆盖恢复内容；浏览器记录覆盖债务比率和流动性引用。此前 20 正常、20 边界、10 风险评测题仍是队友题库，未声称 50 题全部自动评分通过。

后续补充资料审核人、适用期和明确来源，完善评测标注与自动评分。现金流、储蓄率、流动性已恢复，应从旧“缺失”清单移除。真实银行条款与真实 API 由组委会接入阶段提供；当前资料只按教育演示标注。

## 可核对的来源差异

下表由当前来源副本与运行文件逐字节比较生成。相同表示原样复用，不计为逻辑修改。

| 来源 | 运行文件 | 字节比较 |
|---|---|---|
| [__init__.py](<F:/AI_Banking/RAG/banking_rag/__init__.py>) | [__init__.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/__init__.py>) | 相同 |
| [__main__.py](<F:/AI_Banking/RAG/banking_rag/__main__.py>) | [__main__.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/__main__.py>) | 相同 |
| [cli.py](<F:/AI_Banking/RAG/banking_rag/cli.py>) | [cli.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/cli.py>) | 相同 |
| [corpus.py](<F:/AI_Banking/RAG/banking_rag/corpus.py>) | [corpus.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/corpus.py>) | 相同 |
| [providers.py](<F:/AI_Banking/RAG/banking_rag/providers.py>) | [providers.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/providers.py>) | 相同 |
| [retrieval.py](<F:/AI_Banking/RAG/banking_rag/retrieval.py>) | [retrieval.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/retrieval.py>) | 相同 |
| [service.py](<F:/AI_Banking/RAG/banking_rag/service.py>) | [service.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/rag/service.py>) | 相同 |

### 八篇原文哈希核对

| 运行原文 | SHA-256 | 与清单一致 |
|---|---|---|
| [01-现金流.md](<F:/AI_Banking/FirstAgent/knowledge/01-现金流.md>) | `6fe87830da12a7d7f7d97e4c8d6e0fadeb30df1078c7ce1677ca3450e9fc4e5d` | 是 |
| [02-储蓄率.md](<F:/AI_Banking/FirstAgent/knowledge/02-储蓄率.md>) | `4c47eb2fbfcc38972f7196621bec1da4be6102aa656d286f4c1aaa99a5927be9` | 是 |
| [03-流动性.md](<F:/AI_Banking/FirstAgent/knowledge/03-流动性.md>) | `ee49ea4511d6d502070f7259ee817202f746923c8ff416398d4322b6e498ff29` | 是 |
| [04-债务比率.md](<F:/AI_Banking/FirstAgent/knowledge/04-债务比率.md>) | `67daf7b142ccb22f1560c78dba137f68fc8844fc04d5e6d76c4d219dda685951` | 是 |
| [05-风险管理.md](<F:/AI_Banking/FirstAgent/knowledge/05-风险管理.md>) | `bedfd82a94fbbdf232f85ca887392662b43160af01b126ceaecfe3422cae69bb` | 是 |
| [06-合规边界.md](<F:/AI_Banking/FirstAgent/knowledge/06-合规边界.md>) | `cbd5a374060c0fa6ec06a51ef25931342be7a647ba2004f59435eabb531ae72d` | 是 |
| [07-订阅管理.md](<F:/AI_Banking/FirstAgent/knowledge/07-订阅管理.md>) | `15848d84a89f800e4084b99ece4fc6cb66ca203bfd95f429dcd403fa72591db5` | 是 |
| [08-旅行预算.md](<F:/AI_Banking/FirstAgent/knowledge/08-旅行预算.md>) | `e97ce5bf453e1b10c0da4fbe26f1eac14c044fc9717c87d116397d06073f279d` | 是 |

## 测试与报告入口

此前验证报告：[verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)；浏览器证据：[browser-verification.json](<F:/AI_Banking/FirstAgent/reports/browser-verification.json>)。本次只核对来源、文档覆盖和报告生成，不冒称重跑业务测试。

统一接口：[API-CONTRACT.md](<F:/AI_Banking/FirstAgent/API-CONTRACT.md>)；补丁来源：[patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)；交付文件哈希：[file_manifest.json](<F:/AI_Banking/FirstAgent/reports/file_manifest.json>)。

结论：本分工的已实施修改、原样复用、补丁来源、接口影响、验证依据与尚未完成项已分开记录；后续协作以当前 FirstAgent 代码及统一契约为准。
