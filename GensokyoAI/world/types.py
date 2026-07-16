"""GensokyoWorld 核心数据类型。

纯数据结构（msgspec Struct / Enum），不含编排逻辑，便于独立单元测试与序列化。
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from msgspec import Struct, field

# 用户在舞台上的固定占位 id；同时用作 protagonist 哨兵（主角是用户时）。
USER_OCCUPANT_ID = "__user__"


class DirectorAction(StrEnum):
    """导演每轮的调度动作。"""

    CONTINUE = "continue"  # 当前角色继续说
    SWITCH = "switch"  # 换一个角色上场
    WAIT_USER = "wait_user"  # 把话筒交还用户


class SpeakerKind(StrEnum):
    """共享剧本中一条发言的来源类别。"""

    USER = "user"
    CHARACTER = "character"
    SYSTEM = "system"  # 公开场景事件，如"魔理沙从魔法森林来到红魔馆"


class TranscriptEntry(Struct):
    """共享剧本中的一条记录（舞台上可被看到/听到的内容）。

    只承载公开信息；导演 reason、模型推理、私有记忆结果绝不写入。
    """

    scene_id: str
    speaker_kind: SpeakerKind
    speaker_id: str  # 角色 actor_id / USER_OCCUPANT_ID / "system"
    speaker_name: str
    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class DirectorDecision(Struct):
    """导演一次决策的结构化结果。"""

    action: DirectorAction
    next_actor_id: str | None = None  # action=SWITCH 时的目标 actor_id
    reason: str = ""  # 调度理由，仅调试/日志可见，不进剧本
    confidence: float = 0.0
    fallback_applied: bool = False  # 是否因非法决策/解析失败触发了降级


class WorldStateSnapshot(Struct):
    """World 当前状态的只读快照，供前端 / Runtime 查询。"""

    world_id: str
    session_id: str | None = None
    protagonist: str = USER_OCCUPANT_ID
    current_actor_id: str | None = None
    waiting_for_user: bool = True
    # occupant_id -> scene_id（含 USER_OCCUPANT_ID）
    stage: dict[str, str] = field(default_factory=dict)
    # actor_id -> 显示名
    roster: dict[str, str] = field(default_factory=dict)
    # scene_id -> 该场景剧本条数
    transcript_counts: dict[str, int] = field(default_factory=dict)


class WorldSessionRecord(Struct):
    """可独立持久化的 World 会话记录。

    Director 与 World initiative 尚未落地，因此对应状态先使用可序列化映射保留扩展
    边界；后续阶段由实际组件负责与其强类型状态互转，不在本数据层猜测业务字段。
    """

    world_id: str
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    protagonist: str = USER_OCCUPANT_ID
    current_actor_id: str | None = None
    waiting_for_user: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    roster: dict[str, str] = field(default_factory=dict)
    # actor_id -> 该 Actor 的私有 session_id；完整恢复编排在阶段 8 接入。
    actor_sessions: dict[str, str] = field(default_factory=dict)
    stage: dict[str, str] = field(default_factory=dict)
    transcript: dict[str, list[TranscriptEntry]] = field(default_factory=dict)
    director_state: dict[str, Any] = field(default_factory=dict)
    initiative_state: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """更新最后修改时间。"""
        self.updated_at = time.time()


class WorldPersistenceDiagnostic(Struct, frozen=True):
    """恢复 World 存档时返回的结构化诊断。"""

    code: str
    severity: str
    message: str
    actor_id: str | None = None


class WorldLoadResult(Struct):
    """World 存档及其 roster 兼容性诊断。"""

    record: WorldSessionRecord
    diagnostics: list[WorldPersistenceDiagnostic] = field(default_factory=list)
