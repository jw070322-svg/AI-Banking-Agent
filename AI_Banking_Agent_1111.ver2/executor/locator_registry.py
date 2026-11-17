"""定位符注册表：候选策略与运行时重观测（DESIGN §4）。

纪律：
- 瞬时元素编号绝不写入脚本（候选只允许 role/name/text/css/placeholder 等稳定策略）。
- 所有候选均为"假设"，必须在实际页面重观测确认后才可用于动作；确认结果只记
  运行时状态与会话证据快照，不回写为本文件常量。
"""
import json
from dataclasses import dataclass, field

ALLOWED_STRATEGIES = {"css", "role_name", "text", "placeholder", "testid"}


@dataclass
class LocatorSpec:
    name: str
    description: str
    candidates: list = field(default_factory=list)
    source: str = "hypothesis:来自2026-11-11只读观察（上海、myInput、请登录），未逐项复核"

    def __post_init__(self):
        if not self.name:
            raise ValueError("LocatorSpec 缺少名称")
        if not self.candidates:
            raise ValueError(f"LocatorSpec {self.name} 缺少候选策略")
        for candidate in self.candidates:
            if candidate.get("strategy") not in ALLOWED_STRATEGIES:
                raise ValueError(f"LocatorSpec {self.name} 含不允许的策略：{candidate}")


class LocatorRegistry:
    def __init__(self, specs):
        self.specs = {spec.name: spec for spec in specs}
        self.observations = {}  # 运行时状态，不持久化为常量

    def candidates_for(self, name):
        if name not in self.specs:
            raise KeyError(f"未注册的定位目标：{name}")
        return list(self.specs[name].candidates)

    def record(self, name, matched, count, note=None):
        """记录一次真实观测结果（只进运行时状态与会话证据）。"""
        if name not in self.specs:
            raise KeyError(f"未注册的定位目标：{name}")
        from workflow import now
        self.observations[name] = {"matched": matched, "count": count,
                                   "observed_at": now(), "note": note}

    def snapshot(self):
        return {"specs": {name: {"description": s.description, "source": s.source,
                                 "candidates": s.candidates}
                          for name, s in self.specs.items()},
                "observations": dict(self.observations)}

    def to_json(self):
        return json.dumps(self.snapshot(), ensure_ascii=False, indent=2)


def default_registry():
    """点评首页只读薄切片所需的定位目标（候选均为假设，待真实页面复核）。"""
    return LocatorRegistry([
        LocatorSpec(
            name="city_current",
            description="页头当前城市入口（观察值曾为'上海'）",
            candidates=[{"strategy": "css", "value": "#city-selector"},
                        {"strategy": "css", "value": ".city-current"},
                        {"strategy": "text", "value": "上海"}]),
        LocatorSpec(
            name="city_panel_item",
            description="城市面板中的目标城市项（如'杭州'）",
            candidates=[{"strategy": "role_name", "value": "link|杭州"},
                        {"strategy": "text", "value": "杭州"}]),
        LocatorSpec(
            name="search_input",
            description="首页搜索框（观察值 name 曾为 myInput）",
            candidates=[{"strategy": "css", "value": "#myInput"},
                        {"strategy": "placeholder", "value": "查询商户或地点"},
                        {"strategy": "role_name", "value": "textbox|"}]),
        LocatorSpec(
            name="search_submit",
            description="搜索提交控件（回车或按钮）",
            candidates=[{"strategy": "css", "value": ".search-btn"},
                        {"strategy": "role_name", "value": "button|搜索"}]),
    ])
