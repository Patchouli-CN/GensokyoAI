"""冲突检测器 - 识别"想说但不宜说"的张力

蕾米莉亚：命运会告诉你，不是所有冲动都该被付诸行动。
"""

from msgspec import Struct
from enum import Enum, auto
from .motivation_evaluator import MotivationProfile


class ConflictType(Enum):
    """冲突类型"""

    NONE = auto()  # 无冲突，自由表达
    APPROACH_AVOIDANCE = auto()  # 趋避冲突：想说但怕后果
    EMOTIONAL_LEAKAGE = auto()  # 情绪泄露：情绪太强，说出来可能失态
    TIMING = auto()  # 时机冲突：话题重要但当前时机不对
    IDENTITY = auto()  # 身份冲突：想说的话不符合角色性格


class ConflictResult(Struct):
    """冲突检测结果"""

    has_conflict: bool = False
    conflict_type: ConflictType = ConflictType.NONE
    intensity: float = 0.0  # 冲突强度 0-1
    recommendation: str = ""  # 建议："克制"/"换种方式"/"直接表达"


class ConflictDetector:
    """冲突检测器 - 在动机和行动之间设置闸门"""

    def detect(
        self,
        motivation: "MotivationProfile",
        emotional_valence: float,
        is_first_meeting: bool = False,
    ) -> ConflictResult:
        """检测是否存在表达冲突"""

        # 规则1：情绪泄露检测
        if motivation.emotional_charge > 0.8 and abs(emotional_valence) > 0.7:
            # 情绪太强，直接说出来可能"失态"
            leak_intensity = min(motivation.emotional_charge * abs(emotional_valence), 1.0)
            if leak_intensity > 0.6:
                return ConflictResult(
                    has_conflict=True,
                    conflict_type=ConflictType.EMOTIONAL_LEAKAGE,
                    intensity=leak_intensity,
                    recommendation="克制" if leak_intensity > 0.8 else "换种方式",
                )

        # 规则2：情景不匹配（想说不适合的话题）
        if motivation.expression_drive > 0.5 and motivation.situational_relevance < 0.3:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.TIMING,
                intensity=0.5,
                recommendation="换种方式" if motivation.expression_drive < 0.7 else "克制",
            )

        # 规则3：初见的社交距离
        if is_first_meeting and motivation.relational_need > 0.6:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.IDENTITY,
                intensity=0.4,
                recommendation="换种方式",
            )

        return ConflictResult()
