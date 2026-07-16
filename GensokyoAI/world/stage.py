"""WorldStage - 角色在场表：谁在哪个场景。

Director 只能从「用户当前所在场景的在场角色」中选角，否则角色会瞬移进对话（穿帮）。
场景移动通过 asyncio.Lock 保证原子性——尤其是"用户跟随当前演员移动"这类
需要同时更新多个占位的复合操作。
"""

from __future__ import annotations

import asyncio

from .types import USER_OCCUPANT_ID


class WorldStage:
    """维护 occupant_id -> scene_id 的在场映射（occupant 含角色与用户）。"""

    def __init__(self, locations: dict[str, str] | None = None) -> None:
        self._locations: dict[str, str] = dict(locations or {})
        self._lock = asyncio.Lock()

    def scene_of(self, occupant_id: str) -> str | None:
        """返回某占位当前所在场景 id（不在场时为 None）。"""
        return self._locations.get(occupant_id)

    def occupants_in(self, scene_id: str) -> list[str]:
        """返回某场景内所有占位 id（含用户），按 id 排序保证确定性。"""
        return sorted(oid for oid, sid in self._locations.items() if sid == scene_id)

    def characters_in(self, scene_id: str) -> list[str]:
        """返回某场景内的角色 actor_id（排除用户占位）。"""
        return [oid for oid in self.occupants_in(scene_id) if oid != USER_OCCUPANT_ID]

    def visible_actor_ids(self, occupant_id: str) -> list[str]:
        """返回与指定占位同场的其他角色 actor_id（排除自己与用户）。

        用于 Director 选角池：只有和用户同场的角色才可能被点名发言。
        """
        scene_id = self._locations.get(occupant_id)
        if scene_id is None:
            return []
        return [aid for aid in self.characters_in(scene_id) if aid != occupant_id]

    async def move(self, occupant_id: str, scene_id: str) -> None:
        """原子地移动单个占位到新场景。"""
        async with self._lock:
            self._locations[occupant_id] = scene_id

    async def move_together(self, occupant_ids: list[str], scene_id: str) -> None:
        """原子地把多个占位一起移动到同一场景。

        用于"用户跟随当前演员移动"：演员与用户必须在同一原子步内落到新场景，
        避免中途出现用户与演员分处两地的瞬时不一致。
        """
        async with self._lock:
            for occupant_id in occupant_ids:
                self._locations[occupant_id] = scene_id

    def set_location(self, occupant_id: str, scene_id: str) -> None:
        """同步布置初始位置（仅用于开场/恢复，非并发路径）。"""
        self._locations[occupant_id] = scene_id

    def snapshot(self) -> dict[str, str]:
        """返回在场映射的拷贝。"""
        return dict(self._locations)
