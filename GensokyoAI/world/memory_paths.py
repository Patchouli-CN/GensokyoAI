"""World 模式长期语义记忆的安全命名空间。"""

from pathlib import Path

from ..utils.path_security import sanitize_path_id


def build_world_memory_root(base_path: Path, world_id: str, character_name: str) -> Path:
    """构造 ``memory/world_<world_id>/<character_name>`` 长期记忆根。

    world id 与角色名分别净化，避免通过修改角色显示名伪造命名空间，也确保同一
    World 的多个会话自然复用同一角色长期记忆。
    """
    safe_world_id = sanitize_path_id(world_id)
    safe_character_name = sanitize_path_id(character_name)
    return Path(base_path) / "memory" / f"world_{safe_world_id}" / safe_character_name
