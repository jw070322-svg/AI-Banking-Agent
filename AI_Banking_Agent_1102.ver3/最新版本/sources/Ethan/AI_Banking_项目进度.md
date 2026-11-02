# AI Banking｜环境生成 Agent 项目进度记录

> 用途：持续记录项目目标、已完成事项、关键决定、运行方式和下一步。新开对话时可上传本文件，帮助快速接续。
> 最近更新：2026-10-20

## 1. 项目概况

- **比赛项目：** AI Banking
- **负责模块：** 环境生成 Agent
- **开发环境：** Windows + VS Code + Python
- **项目目录：** `C:\Users\111\Desktop\AI_Banking\环境生成agent`
- **开发原则：** 面向 Python 初学者；一步一步操作；每次只做少量步骤；先检查再修改；不覆盖已经可以运行的代码。

## 2. 当前文件结构

```text
环境生成agent/
├── main.py
├── main_backup.py
├── validator.py
└── output/
    └── 多个已生成的 JSON 场景文件
```

目前尚未创建独立的 `scenario_generator.py` 和 `models.py`；主程序缺少这些模块时会使用内置临时实现。

## 3. 如何运行

在 VS Code 终端中，进入项目目录后执行：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" main.py
```

此前直接输入 `python` / `py` 命令遇到过问题；上面的完整路径命令已成功运行。

程序启动后会显示 A-E 场景菜单，并根据输入需求生成 JSON 文件到 `output` 文件夹。

## 4. 已完成事项

- [x] `main.py` 可以正常启动和运行。
- [x] 已备份主程序为 `main_backup.py`。
- [x] 已创建 `validator.py`，并清理过重复定义的 `validate()` 函数。
- [x] 程序已成功生成 A、B、C、D、E 五类场景 JSON。
- [x] 已验证更明确的 C 类场景描述能够被识别并生成 JSON。
- [x] 最近一次测试成功生成 A 类场景，文件名为 `SCN_A_20261020143301_77087C.json`。
- [x] 运行时确认 `validator` 已加载。

## 5. 当前程序模块状态

运行时输出曾显示：

```text
scenario_generator : 未找到，使用内置临时实现
validator          : 已加载
models             : 未找到（当前使用 dict 结构）
```

这表示 `validator.py` 正在被加载；独立的 `scenario_generator.py`、`models.py` 尚未建立。

### `main.py` 当前职责（根据已检查的代码说明）

1. 接收自然语言需求。
2. 通过关键词/规则解析需求。
3. 调用场景生成逻辑生成场景。
4. 调用 validator 校验场景。
5. 将结果保存为 JSON。
6. 支持连续创建场景。

目前需求解析仍是关键词规则版，尚不能据此认定已接入大语言模型。

## 6. `validator.py` 当前检查

当前新版校验逻辑已知包含：

1. 场景数据必须是非空字典。
2. 必须有 `scenario_id`、`scenario_type`、`user`、`accounts`、`transactions`。
3. `user` 必须是非空字典。
4. `accounts` 必须是非空列表；账户结构有效；检查账户 ID 缺失或重复。
5. 若账户有 `initial_balance` / `balance`，检查数值类型及非负性。
6. `transactions` 必须是非空列表；交易结构有效；检查交易 ID 缺失或重复。
7. 检查交易金额是数字且非负。
8. 检查交易引用的 `account_id` 是否存在。
9. `transaction_type` 必须是 `income` 或 `expense`。
10. A 类场景至少包含一笔收入和一笔支出。

### 尚未完成的校验

- [ ] 独立测试正确数据是否通过、错误数据是否被拒绝。
- [ ] 余额流水对账（需要先确认余额字段的业务定义与交易状态规则）。
- [ ] B 类购物支出增加的专项校验。
- [ ] C 类疑似重复扣款的专项校验。
- [ ] D 类余额不足的专项校验。
- [ ] E 类周期性订阅的专项校验。

注意：相同商户出现多次不一定是重复扣款；应结合金额、时间、交易状态等信息判断。不能只凭部分 JSON 片段断定余额一定不一致。

## 7. 已知数据结构

生成的 JSON 结构示例中包含：

- 顶层：`scenario_id`、`scenario_name`、`scenario_type`、`created_at`
- `user`
- `accounts`：如 `account_id`、`user_id`、`initial_balance`、`balance`
- `transactions`：如 `transaction_id`、`account_id`、`date`、`amount`、`transaction_type`、`category`、`merchant`、`status`
- `scenario_requirements.expected`

样例曾出现类似身份证号、手机号、银行卡号格式的值。分享或提交前应确认这些均为虚构测试数据，不包含真实个人信息。

## 8. 下一步计划

请按顺序推进，每次只做少量操作：

### 第一步：确认终端状态

- 如果 VS Code 终端还在等待输入，输入 `exit` 退出程序。
- 如果已经回到 PowerShell 提示符，则直接继续。

### 第二步：独立测试 `validator.py`

目标是确认：
- 合理的场景数据会通过；
- 缺少账户、负数金额、重复 ID、无效交易类型等错误数据会被拒绝；
- 错误信息清楚，方便定位问题。

测试时先新增一个单独测试文件，不要直接改动当前可运行的 `main.py` 或 `validator.py`。

### 第三步：完善专项业务校验

在基础测试通过后，再逐项增加 B/C/D/E 的规则，并用正例和反例测试。

### 第四步：再考虑模块拆分

等现有逻辑和测试稳定后，再评估是否创建独立的 `scenario_generator.py`、`models.py`，避免一次性大改。

## 9. 重要协作约定

- 每次只推进一个小步骤，先检查现状再修改。
- 修改代码前先备份；优先新增测试文件，避免覆盖能运行的代码。
- 每次完成一个关键节点后更新本文件，记录改动、测试结果、遇到的问题和下一步。
- 如果用户告知平台额度接近上限，应先更新本文件并暂停工作。
- 助手无法读取账号实时剩余额度，也无法在后台持续监控或保证在额度耗尽前主动提醒；用户看到平台提示或感觉额度快用完时，应及时要求保存进度并暂停。

## 10. 下次继续时

新开对话时上传最新版 `AI_Banking_项目进度.md`，并告诉助手：
- 当前 VS Code 终端是否已退出；
- 是否已经创建并运行 validator 的独立测试文件；
- 最近新增或修改了哪些代码。
