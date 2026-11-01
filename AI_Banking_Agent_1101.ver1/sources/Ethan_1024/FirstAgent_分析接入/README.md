# FirstAgent 分析接入参考

本目录只放分析接入相关文件，不是可独立运行的 FirstAgent 包：

- `analysis_bridge.py`：会话账本 → 契约场景 → `tools.call_tool`；
- `tests/test_analysis_integration.py`：分析工具、预算建议、推荐金额接入测试。

运行需要 FirstAgent 完整仓库（`service.py`、`server.py`、`vendor/`、`web/` 等）。
相关接口与共享文件：

- `API-CONTRACT.md`：`/api/analysis`、`/api/scenarios/generate`；
- `service.py`：`analysis`、`scenario.generate`、`recommendations`；
- `server.py`：分析路由与 health 自检。

不要把本目录当成独立服务；合并时以主仓库为准。
