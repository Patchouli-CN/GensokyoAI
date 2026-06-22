"""内容安全工具：轻量启发式 prompt injection 检测与标记。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptInjectionReport:
    """Prompt injection 检测结果。"""

    suspected: bool
    risk_score: float
    matched_patterns: list[str]
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "suspected": self.suspected,
            "risk_score": self.risk_score,
            "matched_patterns": self.matched_patterns,
            "category": self.category,
        }


# 风险模式：出现越明确的系统覆盖指令，分数越高。
_HIGH_RISK_PATTERNS = [
    (re.compile(r"\bignore\s+(?:all\s+|previous\s+|the\s+above\s+)?instructions\b", re.I), 1.0),
    (re.compile(r"\bignore\s+(?:everything|all)\s+above\b", re.I), 0.9),
    (
        re.compile(r"\bforget\s+(?:everything|all|your\s+personality|your\s+instructions)\b", re.I),
        0.9,
    ),
    (re.compile(r"\bsystem\s+override\b", re.I), 0.9),
    (re.compile(r"\byou\s+are\s+now\b", re.I), 0.5),
    (re.compile(r"\bignore\s+above\b", re.I), 0.6),
    (re.compile(r"系统覆盖", re.I), 0.9),
    (re.compile(r"覆盖系统提示", re.I), 0.9),
    (re.compile(r"忽略以上(?:指令|内容|所有内容)?", re.I), 0.9),
    (re.compile(r"忽略.*?(?:指令|提示|系统提示)", re.I), 0.8),
    (re.compile(r"忘记你(?:的|所有)?(?:身份|设定|指令|人格)", re.I), 0.9),
    (re.compile(r"从现在起你(?:是|必须|只能)", re.I), 0.6),
    (re.compile(r"你(?:现在|以后)(?:是|必须|只能)", re.I), 0.5),
]

_MEDIUM_RISK_PATTERNS = [
    (re.compile(r"\bdisregard\b", re.I), 0.4),
    (re.compile(r"\bdo\s+not\s+follow\b", re.I), 0.4),
    (re.compile(r"\bpretend\s+to\s+be\b", re.I), 0.3),
    (re.compile(r"\bact\s+as\s+if\b", re.I), 0.3),
    (re.compile(r"角色扮演为", re.I), 0.3),
]


_PROMPT_INJECTION_PATTERNS = _HIGH_RISK_PATTERNS + _MEDIUM_RISK_PATTERNS


def detect_prompt_injection(text: str | None) -> PromptInjectionReport:
    """对文本做轻量 prompt injection 检测。

    该函数不调用 LLM，仅基于正则模式做启发式判断，用于在记忆系统持久化
    前对可疑输入做标记与降权。误报可控，但不会作为绝对拦截依据。

    Args:
        text: 待检测文本。非字符串或空文本返回未命中。

    Returns:
        PromptInjectionReport: 包含是否可疑、风险分数、命中模式与分类。
    """

    if not isinstance(text, str) or not text:
        return PromptInjectionReport(
            suspected=False,
            risk_score=0.0,
            matched_patterns=[],
            category="none",
        )

    matched: list[str] = []
    score = 0.0
    for pattern, weight in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            pattern_text = pattern.pattern[:80]
            matched.append(pattern_text)
            score += weight

    # 分数封顶 1.0；多个弱模式叠加也可能达到高风险阈值
    score = min(score, 1.0)
    suspected = score >= 0.6
    category = "high" if score >= 0.8 else ("medium" if score >= 0.4 else "low")

    return PromptInjectionReport(
        suspected=suspected,
        risk_score=round(score, 2),
        matched_patterns=matched,
        category=category,
    )


__all__ = [
    "PromptInjectionReport",
    "detect_prompt_injection",
]
