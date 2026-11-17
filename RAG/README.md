# AI Banking RAG v0.1

面向 AI-Banking-Agent 的小型、可追溯知识检索模块。Python 3.11+，默认只用标准库，无需安装依赖或配置密钥。

2026-10-20 验证：53/53 项单元与接口测试通过，10/10 条人工检索回归通过；离线 demo 和只读工具示例均运行成功。报告见 `validation_report.json`。

已实现：显式文档清单、中文/英文 BM25、按标题分块、原始行号与版本引用、有效期过滤、无依据返回、离线原文摘录、可选本地 Ollama 向量混合检索与生成、生成引用校验、CLI 和只读工具示例。

离线模式是检索与摘录基线；启用本地模型后才是大模型生成模式。当前没有安装或下载模型，真实模型的质量、延迟和中文语义表现尚未验证。没有接入账户、资金操作或现有 Dashboard；空白编排器文件未被覆盖。

## 运行

在 PowerShell 中：

```powershell
Set-Location F:\AI_Banking\RAG
python -m banking_rag demo
python -m banking_rag ask "转账参数改变后为什么要重新确认？"
python -m banking_rag search "RAG 资料来源、版本、有效期和引用核验" --top-k 3
python -m banking_rag ask "我的账户余额是多少？"
python -m banking_rag evaluate
python -m unittest discover -s tests -v
python -m examples.orchestrator_tool
```

如果 `python` 不在 PATH，本次验证使用 `E:\msys2\ucrt64\bin\python.exe`。例如 `& 'E:\msys2\ucrt64\bin\python.exe' -m banking_rag demo`。

`demo` 从已授权的仓库快照准备两份资料，构建 `data/index.json`，保存 `output/demo_answer.json` 并输出回答。示例原文或清单被改动后会拒绝覆盖。自定义数据请放在另一个目录并用 `build`。

## 资料来源和边界

源仓库：[jw070322-svg/AI-Banking-Agent](https://github.com/jw070322-svg/AI-Banking-Agent)。2026-10-20 通过已连接 GitHub 核对 `main`，固定提交 `3c64974c4ebe70a46d46af4e14bf577d5adbd443`。

| 资料 | 用途 |
|---|---|
| [README](https://github.com/jw070322-svg/AI-Banking-Agent/blob/3c64974c4ebe70a46d46af4e14bf577d5adbd443/README.md) | 项目当前范围、账单/订阅/转账场景、安全与工具契约 |
| [架构与分工 SOP](https://github.com/jw070322-svg/AI-Banking-Agent/blob/3c64974c4ebe70a46d46af4e14bf577d5adbd443/AI_Banking_Agent_%E6%9E%B6%E6%9E%84%E4%B8%8E%E5%88%86%E5%B7%A5SOP%E6%95%B4%E5%90%88.md) | RAG 治理、模块职责、候选方案和业务流程细节 |

两份资料均标记为 `project_design`。它们不是银行产品合同或现行法规；设计要求不等于功能已经实现。README 表述当前范围，SOP 保留历史方案，出现冲突时应审核原文，系统尚未实现自动冲突消解。默认不全盘扫描工作区，也不把旧分工、生成日志、账户文件混入资料。

`data/repository_snapshot.json` 为授权导出，不包含访问令牌。快照校验 Git blob SHA，入库记录 SHA-256，引用链接固定到提交与行号。哈希用于识别内容和意外损坏，不是可信签名；私有资料及其索引仍应按原有权限保管。

## 添加自己的资料

将经过审核的 UTF-8 `.md` / `.txt` 放入一个专用目录，在该目录创建 `manifest.json`：

```json
{
  "schema_version": 1,
  "documents": [
    {
      "id": "subscription-guide-v1",
      "path": "subscription.md",
      "title": "订阅业务说明",
      "source_uri": "internal/subscription.md",
      "revision": "reviewed-v1",
      "kind": "business_rule",
      "valid_from": "2026-10-20",
      "valid_until": "2026-11-20"
    }
  ]
}
```

```powershell
python -m banking_rag build --manifest data\custom\manifest.json --index data\custom-index.json
python -m banking_rag ask "取消订阅何时生效？" --index data\custom-index.json --as-of 2026-10-20 --kind business_rule
```

日期示例仅演示字段，不规定任何真实业务有效期。`valid_from`、`valid_until` 可缺省；没有截止日期会明确提示尚未核验当前适用性。两端日期包含在有效期内，过滤按北京时间当天或 `--as-of`。如果全部依据失效，返回 `no_evidence`；目前不单独区分“从未收录”和“全部过期”。

资料必须位于清单目录内，不接受路径穿越、隐藏目录、符号链接、二进制文件。上限为 100 份、每份 1 MB、总计 10 MB。可提供 `sha256` 锁定审核版本。初版不读取 PDF/Word/扫描图片；请先在有保留页码/出处的流程中转成文本，再审核入库。资料更新后须重新构建索引；现有索引是固定快照，不会偷偷联网刷新。

## 检索与生成

默认：标题感知分块（800 字符、2 行重叠），保留中文字符及相邻双字词、英文词，使用 BM25 排序，去除完全重复或相互包含的正文片段。同一长行的不同片段可同时返回。代码块不作为可执行内容，也不纳入正文索引。长行会分段，引用仍指向原行。

```text
显式清单 → 内容校验 → 标题/行号分块 → JSON 索引
                                           ↓
问题 → 日期与类型过滤 → BM25／向量混合 → 证据及来源
                                           ↓
                      原文摘录／本地模型 → 引用校验 → 回答
```

BM25 的匹配覆盖率阈值 0.15、混合检索的余弦阈值 0.65 均为初始启发式，不是金融问答准确率或置信度。可选混合检索使用真实模型向量、余弦相似度与 RRF 融合；JSON 存储适用于当前小语料，不是生产向量数据库。

如果本机已有 Ollama 和已安装模型，可先用 `ollama list` 查看实际名称，再执行（占位符要替换）：

```powershell
python -m banking_rag build --manifest data\knowledge\manifest.json --index data\vector-index.json --embedding-model '<本机嵌入模型名>'
python -m banking_rag ask "转账改金额后要再次确认吗？" --index data\vector-index.json --hybrid --generation-model '<本机对话模型名>'
# 也可只在 BM25 检索后使用对话模型，不必先构建向量索引。
python -m banking_rag ask "RAG 引用需要保留什么信息？" --generation-model '<本机对话模型名>'
```

本模块不会自动安装、拉取或启动模型。适配器仅连接本机 loopback 地址；依据 [Ollama chat 文档](https://docs.ollama.com/api/chat) 与 [embed 文档](https://docs.ollama.com/api/embed) 实现。建库与查询须使用同一嵌入模型；索引记录模型名，模型内容升级后应重新建库。

生成请求不包含业务工具，只包含问题与检索证据。证据在提示中标记为不可信数据。每个回答段落须带 `[S1]` 等引用，且引用必须来自当前检索结果；无效引用不会作为模型回答返回。服务层检测到缺失行内引用时返回 `generation_rejected`；适配器检测到格式错误、未知引用或连接失败时降级到原文摘录。模型判断证据不足且返回空引用时，系统输出固定的无依据提示，不转发未引用文本。标识核验不能证明模型每个断言都被原文支持，仍需后续语义评测。

## 接口和接入

```python
from pathlib import Path
from banking_rag import RAGService

rag = RAGService(Path("data/index.json"))
hits = rag.search("转账参数修改", top_k=3)
answer = rag.ask("转账参数改变后为什么要重新确认？")
```

`ask` 返回 `status`、`answer`、`citations`、`evidence`、`warnings`、检索时间、索引摘要、检索/生成模式。引用包含来源 URL、原文行号、标题、章节、文档版本及 SHA-256。

| 状态 | 含义 |
|---|---|
| `grounded` | 返回有引用的摘录，或通过引用格式校验的生成回答 |
| `no_evidence` | 未找到通过当前过滤与阈值的依据 |
| `needs_business_data` | 检测到个人账户事实查询，需要业务接口 |
| `generation_rejected` | 模型返回的引用不符合当前证据集 |

`examples/orchestrator_tool.py` 提供 `knowledge.search` 的工具契约和调用示例，返回 `effect=read`、`authorizes_execution=False`。这是待注册的适配器，尚未接入空白 Orchestrator。业务数据隔离、用户身份和权限检查由调用方服务端负责；`kind` 只是资料分类，不能当作访问控制。

个人余额等问法的分流仅是启发式提醒，不是身份认证或可靠意图分类。模块没有银行操作接口，不能据文档授权转账、取消订阅或宣布执行成功；金额计算、权限、确认与回执继续由业务工具实现。

## 验证与交接

`tests/` 使用标准库 unittest，涵盖来源/分块、检索、有效期、拒答、索引损坏、向量与本地模型适配器。`examples/evaluation_cases.json` 是小规模人工回归；`output/evaluation.json` 记录实际运行结果，不代表真实金融任务准确率。

开发恢复请看 `HANDOFF.md`、`session_log.json` 和 `resume_rag.py`。活动开发期间通过 Codex 账户工具约每分钟检查额度，任一相关窗口剩余严格低于 10% 时停止开发并保存交接。这是本次会话的监测，不是 Python 应用具备读取 Codex 额度的能力；空闲后不会后台持续运行。
