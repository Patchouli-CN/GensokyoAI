# GensokyoAI/scene/types.py

"""场景数据类 - 描述角色所处的环境状态"""

from typing import Any

from msgspec import Struct, field


class Scene(Struct):
    """场景 - 角色所处的环境状态单元

    场景是全局共享的地点定义（如博丽神社、魔法森林），从 scenes/*.yaml 加载。
    description 是注入给模型的正文，让角色无需每轮复述自己身处何地。
    """

    id: str  # 无默认值，放最前
    name: str
    description: str = ""
    atmosphere: str = ""  # 氛围（如"宁静""喧闹"）
    time_of_day: str = ""  # 时段（如"黄昏""深夜"），留空表示不限定
    connected_scenes: list[str] = field(default_factory=list)  # 可直接切往的场景 id
    props: list[str] = field(default_factory=list)  # 场景内的关键物件
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """渲染为注入模型上下文的场景描述文本。"""
        lines = [f"【当前场景 · {self.name}】"]
        if self.description:
            lines.append(self.description)
        details: list[str] = []
        if self.time_of_day:
            details.append(f"时段：{self.time_of_day}")
        if self.atmosphere:
            details.append(f"氛围：{self.atmosphere}")
        if self.props:
            details.append(f"周围：{('、'.join(self.props))}")
        if details:
            lines.append("（" + "；".join(details) + "）")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, scene_id: str, data: dict[str, Any]) -> Scene:
        """从 YAML 字典构建场景，id 以文件/传入 id 为准。"""
        return cls(
            id=scene_id,
            name=str(data.get("name") or scene_id),
            description=str(data.get("description", "")),
            atmosphere=str(data.get("atmosphere", "")),
            time_of_day=str(data.get("time_of_day", "")),
            connected_scenes=list(data.get("connected_scenes", []) or []),
            props=list(data.get("props", []) or []),
            metadata=dict(data.get("metadata", {}) or {}),
        )
