"""只读动作契约（DESIGN §4 表格的机器可读版）。

每个动作定义：参数、验证要求、后置状态断言、是否只读。
执行结果由会话采集方（浏览器侧）按契约产出，record 端按契约核验。
"""
from dataclasses import dataclass, field


@dataclass
class ActionContract:
    name: str
    verify: str
    postconditions: dict = field(default_factory=dict)
    read_only: bool = True
    required_for_goal: bool = True
    note: str = ""

    def __post_init__(self):
        if not self.read_only:
            raise ValueError("Phase 2 薄切片只允许只读动作")


CONTRACTS = {
    "open_site": ActionContract(
        name="open_site",
        verify="域名和页面可访问；读回 url/title",
        postconditions={"domain_is_dianping": True, "title_nonempty": True}),
    "select_city": ActionContract(
        name="select_city",
        verify="从真实城市控件选择；读回选中城市与客户城市一致；不臆造city_id",
        postconditions={"selected_city_matches": True},
        note="2026-11-11 观测历史：点击城市曾超时，本切片必须重观测定位符并显式等待。"
             "城市上下文可由已证实URL城市码承载，但'点击选城已执行'不得虚标"),
    "resolve_location": ActionContract(
        name="resolve_location",
        verify="city_only 不宣称GPS定位；设备定位需授权，不得用操作员设备冒充客户位置",
        postconditions={},
        required_for_goal=False,  # city_only 下定位非目标必需（§4.1）
        note="city_only 模式下本动作为无页面操作，记录 skipped 并写 skip_reason"),
    "search": ActionContract(
        name="search",
        verify="可见搜索框输入并提交；核对结果页关键词与城市；空结果单独记录",
        postconditions={"keyword_echo": True, "city_consistent": True},
        note="只读提交公共搜索词；不含事件原文，只含 public_keyword"),
}


def build_step(action, params, seq):
    contract = CONTRACTS.get(action)
    if contract is None:
        raise KeyError(f"未定义的只读动作：{action}")
    return {"seq": seq, "step_id": f"{seq}:{action}", "action": action,
            "params": params, "verify": contract.verify,
            "postconditions": contract.postconditions,
            "read_only": contract.read_only,
            "required_for_goal": contract.required_for_goal,
            "note": contract.note}
