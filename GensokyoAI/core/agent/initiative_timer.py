"""主动定时器 - 回答后积存主动发言摘要并按可编辑定时器触发。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ...utils.helpers import utc_now
from ...utils.logger import logger
from ..config import InitiativeTimerConfig
from ..events import Event, EventBus, SystemEvent
from .types import ProviderCapability

if TYPE_CHECKING:
    from ...memory.working import WorkingMemoryManager

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_INITIATIVE_TIMER_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "should_schedule": {"type": "boolean"},
        "delay_seconds": {"type": "integer"},
        "summary": {"type": "string"},
        "reason": {"type": "string"},
        "enthusiasm": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "角色当前主动交流的热情度，0~1；越高则等待时间越短",
        },
    },
    "required": ["should_schedule", "delay_seconds", "summary", "reason"],
    "additionalProperties": False,
}
_INITIATIVE_TIMER_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "initiative_timer_decision",
        "strict": True,
        "schema": _INITIATIVE_TIMER_DECISION_SCHEMA,
    },
}


@dataclass
class InitiativeTimerState:
    timer_id: str
    status: str
    generation: int
    source: str
    created_at: datetime
    updated_at: datetime
    due_at: datetime
    delay_seconds: int
    pending_summary: str
    reason: str = ""
    user_modified: bool = False
    hesitation_round: int = 0  # 0=正常定时器, >0=第N轮犹豫重试


class InitiativeTimerManager:
    """管理回答后由 AI 生成的积存主动发言摘要与定时器。"""

    def __init__(
        self,
        *,
        config: InitiativeTimerConfig,
        model_client: Any,
        event_bus: EventBus,
        character_name: str,
        working_memory: WorkingMemoryManager,
        debug_silent_output: bool = False,
        trigger_handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]] | None = None,
    ) -> None:
        self.config = config
        self.model_client = model_client
        self.event_bus = event_bus
        self.character_name = character_name
        self.working_memory = working_memory
        self.debug_silent_output = debug_silent_output
        self.trigger_handler = trigger_handler
        self._state: InitiativeTimerState | None = None
        self._generation = 0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_assistant_response: str | None = None  # 犹豫重试时复用
        self._pace_stamps: list[datetime] = []  # 最近几次回复完成时间，用于 auto 延迟

    def current_payload(self) -> dict[str, Any] | None:
        """返回当前定时器对前端可见的 payload。"""
        if self._state is None or self._state.status != "scheduled":
            return None
        return self._payload(self._state)

    async def schedule_after_response(self, assistant_response: str) -> dict[str, Any] | None:
        """AI 回复完成后生成并设置下一条积存主动发言摘要。

        决策为"不发言"时优先进入犹豫链；若未开启犹豫或犹豫耗尽，
        默认会创建一条兜底自然再考虑定时器，避免角色长期失去主动能力。
        """
        if not self.config.enabled or not assistant_response.strip():
            logger.trace("[InitiativeTimer] schedule_after_response 被禁用或回复为空，跳过")
            return None

        self._last_assistant_response = assistant_response
        self._pace_stamps.append(utc_now())
        if len(self._pace_stamps) > 5:
            self._pace_stamps = self._pace_stamps[-5:]

        logger.debug(f"[InitiativeTimer] 开始为 {self.character_name} 决策下一轮主动发言")
        decision = await self._decide(assistant_response, hesitation_round=0)
        if not decision:
            logger.debug("[InitiativeTimer] 决策解析失败，进入不发言处理流程")
            return await self._handle_no_schedule(reason="decision_parse_failed")

        should_schedule = bool(decision.get("should_schedule"))
        summary = str(decision.get("summary") or "").strip()
        if not should_schedule or not summary:
            reason = str(decision.get("reason") or "no_schedule_or_empty_summary").strip()
            logger.debug(f"[InitiativeTimer] AI 决定不主动发言或摘要为空，原因: {reason}")
            return await self._handle_no_schedule(reason=reason)

        summary = self._trim_summary(summary)
        delay_seconds = self._clamp_delay(decision.get("delay_seconds"))
        enthusiasm = decision.get("enthusiasm")
        delay_seconds = self._apply_enthusiasm(delay_seconds, enthusiasm)
        reason = str(decision.get("reason") or "").strip()

        logger.debug(
            f"[InitiativeTimer] AI 决定主动发言，摘要: {summary[:40]}..., "
            f"原始延迟: {self._clamp_delay(decision.get('delay_seconds'))}s, "
            f"热情度: {enthusiasm}, 调整后延迟: {delay_seconds}s"
        )

        async with self._lock:
            await self._discard_locked(reason="replaced_by_new_ai_plan", source="ai")
            state = self._create_state(
                delay_seconds=delay_seconds,
                pending_summary=summary,
                reason=reason,
                source="ai",
                user_modified=False,
                hesitation_round=0,
            )
            self._state = state
            self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
            self._publish(SystemEvent.INITIATIVE_TIMER_CREATED, state)
            logger.info(
                f"[InitiativeTimer] 已创建主动定时器 {state.timer_id}, "
                f"触发时间: {state.due_at.isoformat()}"
            )
            return self._payload(state)

    # ------------------------------------------------------------------
    # 犹豫重试
    # ------------------------------------------------------------------

    async def _handle_no_schedule(
        self, *, reason: str, round_num: int = 1
    ) -> dict[str, Any] | None:
        """AI 未设置定时器时，先尝试犹豫链，失败后进入兜底定时器。"""
        logger.debug(f"[InitiativeTimer] 处理不发言情况，原因: {reason}, 犹豫轮次: {round_num}")
        payload = await self._try_hesitate(round_num)
        if payload is not None:
            return payload
        return await self._try_schedule_fallback(reason=reason)

    async def _try_hesitate(self, round_num: int) -> dict[str, Any] | None:
        """AI 决定不发言时，按开关决定是否进入犹豫重试链。"""
        if not self.config.hesitation_enabled:
            logger.trace("[InitiativeTimer] 犹豫功能已关闭")
            return None
        max_rounds = self.config.hesitation_max_rounds
        if max_rounds <= 0 or round_num > max_rounds:
            logger.debug(
                f"[InitiativeTimer] 犹豫轮次 {round_num} 超过最大值 {max_rounds}，停止犹豫"
            )
            return None
        async with self._lock:
            payload = self._schedule_reconsider_timer(round_num)
            logger.info(
                f"[InitiativeTimer] 进入第 {round_num} 轮犹豫，{self.config.hesitation_delay_seconds} 秒后重新决策"
            )
            return payload

    async def _try_schedule_fallback(self, *, reason: str) -> dict[str, Any] | None:
        """创建默认兜底自然再考虑定时器，避免不设定定时器导致长期沉默。"""
        if not self.config.fallback_on_no_schedule:
            logger.debug("[InitiativeTimer] 未开启兜底定时器，直接放弃")
            return None
        summary = self._trim_summary(str(self.config.fallback_summary or "").strip())
        if not summary:
            logger.debug("[InitiativeTimer] 兜底摘要为空，不创建兜底定时器")
            return None
        fallback_reason = str(self.config.fallback_reason or "").strip() or reason
        async with self._lock:
            await self._discard_locked(reason="replaced_by_fallback", source="fallback")
            state = self._create_state(
                delay_seconds=self._clamp_delay(self.config.fallback_delay_seconds),
                pending_summary=summary,
                reason=fallback_reason,
                source="fallback",
                user_modified=False,
                hesitation_round=0,
            )
            self._state = state
            self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
            self._publish(SystemEvent.INITIATIVE_TIMER_CREATED, state)
            logger.info(
                f"[InitiativeTimer] 已创建兜底定时器 {state.timer_id}, "
                f"原因: {fallback_reason}, 延迟: {state.delay_seconds}s"
            )
            return self._payload(state)

    def _resolve_hesitation_delay(self) -> int:
        """解析犹豫延迟：若为 'auto' 则根据对话节奏动态计算，否则用配置值。"""
        raw = self.config.hesitation_delay_seconds
        if isinstance(raw, str) and raw.strip().lower() == "auto":
            return self._compute_auto_delay()
        try:
            seconds = int(raw)
        except TypeError, ValueError:
            return 180
        return max(1, seconds)

    def _compute_auto_delay(self) -> int:
        """根据最近几次回复间隔动态计算犹豫等待时间。

        节奏快 → 等待短；节奏慢 → 等待长。夹在 30~600 秒之间。
        """
        stamps = self._pace_stamps
        if len(stamps) < 2:
            logger.trace("[InitiativeTimer] 回复节奏样本不足，使用默认犹豫延迟 180s")
            return 180
        intervals: list[float] = []
        for i in range(1, len(stamps)):
            delta = (stamps[i] - stamps[i - 1]).total_seconds()
            if delta > 0:
                intervals.append(delta)
        if not intervals:
            logger.trace("[InitiativeTimer] 无有效回复间隔，使用默认犹豫延迟 180s")
            return 180
        avg_interval = sum(intervals) / len(intervals)
        # 弹性系数：节奏快等短一点，节奏慢等比放大
        delay = int(avg_interval * 0.8)
        result = max(30, min(600, delay))
        logger.debug(f"[InitiativeTimer] 自动犹豫延迟: 平均间隔 {avg_interval:.1f}s -> {result}s")
        return result

    def _schedule_reconsider_timer(self, round_num: int) -> dict[str, Any] | None:
        """调度一轮犹豫重试定时器（调用方必须持锁）。"""
        state = self._create_state(
            delay_seconds=self._resolve_hesitation_delay(),
            pending_summary="",
            reason=f"hesitation_round_{round_num}",
            source="reconsider",
            user_modified=False,
            hesitation_round=round_num,
        )
        self._state = state
        self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
        logger.debug(f"[InitiativeTimer] 犹豫重试定时器 {state.timer_id} 已调度，第 {round_num} 轮")
        return self._payload(state)

    async def _handle_reconsider(self, round_num: int) -> None:
        """犹豫定时器到期：重新让 AI 判断是否发言。"""
        assistant_response = self._last_assistant_response or ""
        if not assistant_response:
            logger.debug("[InitiativeTimer] 犹豫重试时没有缓存的上一次回复，放弃")
            return

        logger.debug(f"[InitiativeTimer] 第 {round_num} 轮犹豫到期，重新决策")
        decision = await self._decide(assistant_response, hesitation_round=round_num)
        if not decision:
            await self._handle_no_schedule(
                reason="reconsider_parse_failed", round_num=round_num + 1
            )
            return

        should_schedule = bool(decision.get("should_schedule"))
        summary = str(decision.get("summary") or "").strip()
        if not should_schedule or not summary:
            reason = str(decision.get("reason") or "reconsider_no_schedule").strip()
            logger.debug(f"[InitiativeTimer] 犹豫重试后仍决定不发言，原因: {reason}")
            await self._handle_no_schedule(reason=reason, round_num=round_num + 1)
            return

        # AI 终于决定发言了！
        summary = self._trim_summary(summary)
        delay_seconds = self._clamp_delay(decision.get("delay_seconds"))
        enthusiasm = decision.get("enthusiasm")
        delay_seconds = self._apply_enthusiasm(delay_seconds, enthusiasm)
        reason = str(decision.get("reason") or "").strip()

        logger.debug(
            f"[InitiativeTimer] 犹豫重试后决定主动发言，摘要: {summary[:40]}..., "
            f"调整后延迟: {delay_seconds}s"
        )

        async with self._lock:
            await self._discard_locked(reason="replaced_by_reconsider", source="ai")
            state = self._create_state(
                delay_seconds=delay_seconds,
                pending_summary=summary,
                reason=reason,
                source="ai",
                user_modified=False,
                hesitation_round=0,
            )
            self._state = state
            self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
            self._publish(SystemEvent.INITIATIVE_TIMER_CREATED, state)
            logger.info(
                f"[InitiativeTimer] 犹豫后创建主动定时器 {state.timer_id}, "
                f"触发时间: {state.due_at.isoformat()}"
            )

    # ------------------------------------------------------------------
    # 公共操作
    # ------------------------------------------------------------------

    async def discard(
        self, *, reason: str = "discarded", source: str = "system"
    ) -> dict[str, Any] | None:
        """丢弃当前积存摘要。用户新消息进入时调用。"""
        logger.debug(f"[InitiativeTimer] 外部请求丢弃定时器，原因: {reason}, 来源: {source}")
        async with self._lock:
            return await self._discard_locked(reason=reason, source=source)

    async def cancel(
        self, *, timer_id: str | None = None, reason: str = "cancelled", source: str = "user"
    ) -> dict[str, Any]:
        """取消当前定时器并丢弃积存摘要。"""
        async with self._lock:
            state = self._require_current(timer_id)
            self._generation += 1
            state.status = "cancelled"
            state.updated_at = utc_now()
            payload = self._payload(state)
            self._state = None
            self._cancel_task()
            self._publish(
                SystemEvent.INITIATIVE_TIMER_CANCELLED,
                state,
                extra={"reason": reason, "source": source},
            )
            logger.info(f"[InitiativeTimer] 定时器 {state.timer_id} 被取消，原因: {reason}")
            return {
                "cancelled": True,
                "timer_id": state.timer_id,
                "status": "cancelled",
                "timer": payload,
            }

    async def update(
        self,
        *,
        timer_id: str | None = None,
        delay_seconds: int | float | None = None,
        due_at: str | None = None,
        pending_summary: str | None = None,
    ) -> dict[str, Any]:
        """更新当前定时器触发时间或积存摘要。"""
        if delay_seconds is not None and due_at is not None:
            raise ValueError("delay_seconds and due_at cannot be provided together")

        async with self._lock:
            state = self._require_current(timer_id)
            now = utc_now()
            changed = False
            if due_at is not None:
                parsed_due_at = self._parse_due_at(due_at)
                seconds = max(1, int((parsed_due_at - now).total_seconds()))
                state.delay_seconds = self._clamp_delay(seconds)
                state.due_at = now + timedelta(seconds=state.delay_seconds)
                changed = True
            elif delay_seconds is not None:
                state.delay_seconds = self._clamp_delay(delay_seconds)
                state.due_at = now + timedelta(seconds=state.delay_seconds)
                changed = True

            if pending_summary is not None:
                if not self.config.allow_frontend_edit_summary:
                    raise ValueError("Frontend editing pending_summary is disabled")
                summary = self._trim_summary(pending_summary.strip())
                if not summary:
                    raise ValueError("pending_summary cannot be empty")
                state.pending_summary = summary
                changed = True

            if changed:
                self._generation += 1
                state.generation = self._generation
                state.updated_at = now
                state.user_modified = True
                self._cancel_task()
                self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
                self._publish(SystemEvent.INITIATIVE_TIMER_UPDATED, state, extra={"source": "user"})
                logger.info(
                    f"[InitiativeTimer] 定时器 {state.timer_id} 已更新，"
                    f"新触发时间: {state.due_at.isoformat()}, 摘要: {state.pending_summary[:40]}..."
                )
            return self._payload(state)

    async def trigger(self, *, timer_id: str | None = None, source: str = "user") -> dict[str, Any]:
        """立即触发当前积存主动摘要。"""
        logger.debug(f"[InitiativeTimer] 外部请求立即触发定时器，来源: {source}")
        async with self._lock:
            state = self._require_current(timer_id)
            return await self._trigger_locked(state, source=source)

    async def shutdown(self) -> None:
        """关闭并取消后台定时任务。"""
        logger.debug("[InitiativeTimer] 关闭并清理定时器")
        async with self._lock:
            await self._discard_locked(reason="shutdown", source="system")

    # ------------------------------------------------------------------
    # 决策
    # ------------------------------------------------------------------

    async def _decide(
        self, assistant_response: str, *, hesitation_round: int = 0
    ) -> dict[str, Any] | None:
        recent_messages = self.working_memory.get_recent(6)
        context_text = self._format_context_for_decision(recent_messages, assistant_response)

        hesitation_note = ""
        if hesitation_round > 0:
            remaining = self.config.hesitation_max_rounds - hesitation_round
            hesitation_note = f"（注意：这已是第 {hesitation_round} 次请你重新考虑是否主动发言"
            if remaining > 0:
                hesitation_note += f"，你还有 {remaining} 次犹豫机会"
            else:
                hesitation_note += "，这是最后一次机会，若仍不需要则放弃"
            hesitation_note += "。）\n"

        system_prompt = f"""你是 {self.character_name}。

现在不是对用户说话，而是在向 GensokyoAI 系统提交你的内部主动发言决定。
这个决定仍然必须由你以 {self.character_name} 的身份、性格、动机和当前上下文来完成；系统只负责读取你提交的机器可解析状态。

请判断你是否想在稍后主动补充一句话。要求：
- 这是内部决策提交，不是用户可见台词；不要把结果写成角色发言、对白、旁白或解释。
- 这里的“不设置定时器”表示你本轮明确放弃稍后主动补充；如果系统没有其他兜底，这会让你在用户再次输入前不再主动开口。
- 为了更拟真地保留角色的主动性，除非当前上下文确实没有任何自然、必要、符合角色的补充，否则优先设置一个短到中等延迟的定时器。
- 如果设置，只写"稍后主动发言意图的一句话摘要"，不要写完整可发送话术。
- 摘要只描述到点后要围绕什么思考和表达，真正说出口的话会在触发时重新生成。
- 延迟秒数必须在 {self.config.min_delay_seconds} 到 {self.config.max_delay_seconds} 之间。
- 额外输出一个 0~1 的 enthusiasm（热情度）：越高表示你当前越想主动继续聊，系统会把等待时间按 `delay_seconds * (1 - enthusiasm)` 缩短；如果不确定可填 0.5。
- 只输出一个原始 JSON 对象；不要输出 Markdown 代码块、角色引号、解释文本或任何前后缀。
{hesitation_note}
"""

        user_prompt = f"""你刚刚回复了用户：
{assistant_response}

近期对话上下文：
{context_text}

请根据以上上下文提交决定。输出必须且只能是下面的 JSON 对象，不要有任何其他内容：

{{
  "should_schedule": true/false,
  "delay_seconds": 120,
  "summary": "稍后主动发言意图的一句话摘要",
  "reason": "简短理由",
  "enthusiasm": 0.5
}}
"""

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.trace(
            f"[InitiativeTimer] 决策请求 messages:\n{json.dumps(messages, ensure_ascii=False, indent=2)}"
        )

        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                decision_max_tokens = max(self.config.decision_max_tokens, 200)
                options: dict[str, Any] = {
                    "temperature": self.config.decision_temperature,
                    "num_predict": decision_max_tokens,
                    "max_tokens": decision_max_tokens,
                }
                if self._supports_structured_output():
                    options["response_format"] = _INITIATIVE_TIMER_RESPONSE_FORMAT

                response = await self.model_client.chat(
                    messages=messages,
                    options=options,
                )
                content = response.message.content
                text = content.strip() if isinstance(content, str) else ""
                if not text:
                    logger.warning("主动定时器决策模型返回空内容，跳过")
                    return None

                logger.trace(f"[InitiativeTimer] 决策原始响应: {text!r}")
                data = self._parse_decision_json(text)
                if data is not None:
                    logger.debug(f"[InitiativeTimer] 决策解析成功: {data}")
                    return data

                # 解析失败，尝试一次重试
                if attempt < max_retries:
                    logger.warning("主动定时器决策未返回合法 JSON，准备重试一次")
                    messages.append({"role": "assistant", "content": text[:1000]})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "你上一条回复不是合法的 JSON。请严格按照要求只输出 JSON 对象，"
                                "不要写成角色台词、对白或解释。请重试。"
                            ),
                        }
                    )
                    continue

                return None
            except Exception as error:
                logger.error(f"主动定时器决策失败: {error}")
                return None

        return None

    def _format_context_for_decision(
        self, recent_messages: list[dict[str, Any]], current_response: str
    ) -> str:
        """把近期对话格式化为决策上下文，避免重复放入当前刚生成的回复。"""
        lines = []
        for item in recent_messages:
            role = item.get("role")
            content = item.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                continue
            if role not in {"user", "assistant"}:
                continue
            # 避免把刚生成的 assistant 回复再当成上下文末尾，否则模型会误以为要继续对白
            if role == "assistant" and content.strip() == current_response.strip():
                continue
            label = "User" if role == "user" else self.character_name
            lines.append(f"{label}: {content.strip()}")
        if not lines:
            return "（无更早上下文）"
        return "\n".join(lines)

    def _supports_structured_output(self) -> bool:
        supports = getattr(self.model_client, "supports", None)
        if callable(supports):
            try:
                return bool(supports(ProviderCapability.STRUCTURED_OUTPUT))
            except Exception as error:
                logger.warning(f"主动定时器结构化输出能力判断失败，将使用普通 JSON 提示: {error}")
        return False

    @staticmethod
    def _parse_decision_json(text: str) -> dict[str, Any] | None:
        match = _JSON_OBJECT_PATTERN.search(text)
        raw = match.group(0) if match else text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            preview = raw.replace("\r", "\\r").replace("\n", "\\n")[:300]
            logger.error(f"主动定时器决策 JSON 解析失败: {error}; raw={preview!r}")
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _create_state(
        self,
        *,
        delay_seconds: int,
        pending_summary: str,
        reason: str,
        source: str,
        user_modified: bool,
        hesitation_round: int = 0,
    ) -> InitiativeTimerState:
        now = utc_now()
        self._generation += 1
        state = InitiativeTimerState(
            timer_id=str(uuid4())[:8],
            status="scheduled",
            generation=self._generation,
            source=source,
            created_at=now,
            updated_at=now,
            due_at=now + timedelta(seconds=delay_seconds),
            delay_seconds=delay_seconds,
            pending_summary=pending_summary,
            reason=reason,
            user_modified=user_modified,
            hesitation_round=hesitation_round,
        )
        logger.trace(
            f"[InitiativeTimer] 创建状态 #{self._generation} {state.timer_id}: "
            f"source={source}, delay={delay_seconds}s, reason={reason}"
        )
        return state

    @staticmethod
    def _apply_enthusiasm(base_delay: int, enthusiasm: float | None) -> int:
        """根据热情度调整等待时间。

        公式：wait_sec = base_delay * (1 - enthusiasm)
        热情度越高，等待越短；未提供或无效时不调整；结果受默认 30~600 限制。
        """
        if enthusiasm is None:
            logger.trace("[InitiativeTimer] 未提供热情度，不调整延迟")
            return base_delay
        enthusiasm = max(0.0, min(1.0, float(enthusiasm)))
        adjusted = int(base_delay * (1.0 - enthusiasm))
        result = max(30, min(600, adjusted))
        logger.trace(
            f"[InitiativeTimer] 热情度调整: base={base_delay}s, enthusiasm={enthusiasm:.2f}, "
            f"adjusted={adjusted}s, clamped={result}s"
        )
        return result

    async def _run_timer(self, timer_id: str, generation: int) -> None:
        try:
            while True:
                trigger_args: dict[str, Any] | None = None
                should_reconsider = False
                reconsider_round = 0
                async with self._lock:
                    state = self._state
                    if not state or state.timer_id != timer_id or state.generation != generation:
                        logger.trace(
                            f"[InitiativeTimer] 定时器 {timer_id} 已失效或代数不匹配，退出循环"
                        )
                        return
                    remaining = (state.due_at - utc_now()).total_seconds()
                    if remaining <= 0:
                        if state.source == "reconsider":
                            should_reconsider = True
                            reconsider_round = state.hesitation_round
                            self._state = None
                            self._cancel_task()
                            logger.debug(
                                f"[InitiativeTimer] 犹豫定时器 {timer_id} 到期，进入第 {reconsider_round} 轮重新决策"
                            )
                        else:
                            trigger_args = self._prepare_trigger_locked(state, source="timer")
                            logger.info(
                                f"[InitiativeTimer] 定时器 {timer_id} 到期，准备触发主动消息"
                            )
                    else:
                        trigger_args = None
                if should_reconsider:
                    await self._handle_reconsider(reconsider_round)
                    return
                if trigger_args is not None:
                    await self._execute_trigger_handler(trigger_args)
                    return
                await asyncio.sleep(min(remaining, 1.0))
        except asyncio.CancelledError:
            logger.trace(f"[InitiativeTimer] 定时器 {timer_id} 任务被取消")
            raise
        except Exception as error:
            logger.error(f"主动定时器任务异常: {error}")

    def _prepare_trigger_locked(
        self, state: InitiativeTimerState, *, source: str
    ) -> dict[str, Any]:
        """在锁内完成状态变更，返回触发参数供锁外回调使用。"""
        self._generation += 1
        state.status = "triggered"
        state.updated_at = utc_now()
        pending_summary = state.pending_summary
        payload = self._payload(state)
        self._state = None
        self._cancel_task()
        self._publish(
            SystemEvent.INITIATIVE_TIMER_TRIGGERED,
            state,
            extra={"pending_summary": pending_summary, "source": source},
        )
        logger.debug(
            f"[InitiativeTimer] 定时器 {state.timer_id} 状态变为 triggered, source={source}"
        )
        return {
            "timer_id": state.timer_id,
            "pending_summary": pending_summary,
            "reason": state.reason,
            "source": source,
            "timer": payload,
        }

    async def _execute_trigger_handler(self, trigger_args: dict[str, Any]) -> dict[str, Any]:
        """在锁外执行 trigger_handler（可能调用 LLM，耗时较长）。"""
        logger.debug(
            f"[InitiativeTimer] 执行 trigger_handler, timer_id={trigger_args.get('timer_id')}"
        )
        result: dict[str, Any] | None = None
        if self.trigger_handler is not None:
            result = await self.trigger_handler(trigger_args)
        logger.debug(f"[InitiativeTimer] trigger_handler 返回: {result}")
        return {
            "triggered": True,
            "timer_id": trigger_args.get("timer_id", ""),
            "pending_summary": trigger_args.get("pending_summary", ""),
            "timer": trigger_args.get("timer", {}),
            "result": result,
        }

    async def _trigger_locked(self, state: InitiativeTimerState, *, source: str) -> dict[str, Any]:
        """立即触发（由 trigger() 调用，已在锁内）。状态变更在锁内，回调在锁外。"""
        trigger_args = self._prepare_trigger_locked(state, source=source)
        return await self._execute_trigger_handler(trigger_args)

    async def _discard_locked(self, *, reason: str, source: str) -> dict[str, Any] | None:
        state = self._state
        if state is None:
            return None
        self._generation += 1
        state.status = "discarded"
        state.updated_at = utc_now()
        payload = self._payload(state)
        self._state = None
        self._cancel_task()
        self._publish(
            SystemEvent.INITIATIVE_TIMER_DISCARDED,
            state,
            extra={"reason": reason, "source": source},
        )
        logger.debug(
            f"[InitiativeTimer] 定时器 {state.timer_id} 被丢弃，原因: {reason}, 来源: {source}"
        )
        return payload

    def _require_current(self, timer_id: str | None = None) -> InitiativeTimerState:
        state = self._state
        if state is None or state.status != "scheduled":
            raise ValueError("No active initiative timer")
        if timer_id and timer_id != state.timer_id:
            raise ValueError("initiative timer id does not match current timer")
        return state

    def _cancel_task(self) -> None:
        task = self._task
        if task and not task.done() and task is not asyncio.current_task():
            logger.trace("[InitiativeTimer] 取消旧定时任务")
            task.cancel()
        self._task = None

    def _payload(self, state: InitiativeTimerState) -> dict[str, Any]:
        now = utc_now()
        remaining = max(0, int((state.due_at - now).total_seconds()))
        payload: dict[str, Any] = {
            "timer_id": state.timer_id,
            "status": state.status,
            "generation": state.generation,
            "source": state.source,
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
            "due_at": state.due_at.isoformat(),
            "delay_seconds": state.delay_seconds,
            "remaining_seconds": remaining,
            "reason": state.reason,
            "user_modified": state.user_modified,
            "hesitation_enabled": self.config.hesitation_enabled,
            "hesitation_round": state.hesitation_round,
            "hesitation_max": self.config.hesitation_max_rounds,
            "fallback_on_no_schedule": self.config.fallback_on_no_schedule,
            "is_fallback": state.source == "fallback",
            "editable_fields": ["due_at", "delay_seconds", "pending_summary"]
            if self.config.allow_frontend_edit_summary
            else ["due_at", "delay_seconds"],
        }
        if self.config.expose_pending_summary:
            payload["pending_summary"] = state.pending_summary
        return payload

    def _publish(
        self,
        event_type: SystemEvent,
        state: InitiativeTimerState,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        data = self._payload(state)
        if extra:
            data.update(extra)
        self.event_bus.publish(Event(type=event_type, source="initiative_timer", data=data))

    def _clamp_delay(self, value: Any) -> int:
        try:
            seconds = int(value)
        except TypeError, ValueError:
            seconds = self.config.min_delay_seconds
        return max(self.config.min_delay_seconds, min(self.config.max_delay_seconds, seconds))

    def _trim_summary(self, summary: str) -> str:
        return summary[: self.config.max_pending_summary_chars].strip()

    @staticmethod
    def _parse_due_at(value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
