"""主动定时器 - 回答后积存主动消息并按可编辑定时器触发。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ...utils.logger import logger
from ..config import InitiativeTimerConfig
from ..events import Event, EventBus, SystemEvent

if TYPE_CHECKING:
    from ...memory.working import WorkingMemoryManager

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


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
    pending_message: str
    reason: str = ""
    user_modified: bool = False


class InitiativeTimerManager:
    """管理回答后由 AI 生成的积存主动消息与定时器。"""

    def __init__(
        self,
        *,
        config: InitiativeTimerConfig,
        model_client: Any,
        event_bus: EventBus,
        character_name: str,
        working_memory: WorkingMemoryManager,
        debug_silent_output: bool = False,
    ) -> None:
        self.config = config
        self.model_client = model_client
        self.event_bus = event_bus
        self.character_name = character_name
        self.working_memory = working_memory
        self.debug_silent_output = debug_silent_output
        self._state: InitiativeTimerState | None = None
        self._generation = 0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def current_payload(self) -> dict[str, Any] | None:
        """返回当前定时器对前端可见的 payload。"""
        if self._state is None or self._state.status != "scheduled":
            return None
        return self._payload(self._state)

    async def schedule_after_response(self, assistant_response: str) -> dict[str, Any] | None:
        """AI 回复完成后生成并设置下一条积存主动消息。"""
        if not self.config.enabled or not assistant_response.strip():
            return None

        decision = await self._decide(assistant_response)
        if not decision:
            return None

        should_schedule = bool(decision.get("should_schedule"))
        message = str(decision.get("message") or "").strip()
        if not should_schedule or not message:
            return None

        message = self._trim_message(message)
        delay_seconds = self._clamp_delay(decision.get("delay_seconds"))
        reason = str(decision.get("reason") or "").strip()

        async with self._lock:
            await self._discard_locked(reason="replaced_by_new_ai_plan", source="ai")
            state = self._create_state(
                delay_seconds=delay_seconds,
                pending_message=message,
                reason=reason,
                source="ai",
                user_modified=False,
            )
            self._state = state
            self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
            self._publish(SystemEvent.INITIATIVE_TIMER_CREATED, state)
            return self._payload(state)

    async def discard(
        self, *, reason: str = "discarded", source: str = "system"
    ) -> dict[str, Any] | None:
        """丢弃当前积存消息。用户新消息进入时调用。"""
        async with self._lock:
            return await self._discard_locked(reason=reason, source=source)

    async def cancel(
        self, *, timer_id: str | None = None, reason: str = "cancelled", source: str = "user"
    ) -> dict[str, Any]:
        """取消当前定时器并丢弃积存消息。"""
        async with self._lock:
            state = self._require_current(timer_id)
            self._generation += 1
            state.status = "cancelled"
            state.updated_at = datetime.now(UTC)
            payload = self._payload(state)
            self._state = None
            self._cancel_task()
            self._publish(
                SystemEvent.INITIATIVE_TIMER_CANCELLED,
                state,
                extra={"reason": reason, "source": source},
            )
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
        pending_message: str | None = None,
    ) -> dict[str, Any]:
        """更新当前定时器触发时间或积存消息。"""
        if delay_seconds is not None and due_at is not None:
            raise ValueError("delay_seconds and due_at cannot be provided together")

        async with self._lock:
            state = self._require_current(timer_id)
            now = datetime.now(UTC)
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

            if pending_message is not None:
                if not self.config.allow_frontend_edit_message:
                    raise ValueError("Frontend editing pending_message is disabled")
                message = self._trim_message(pending_message.strip())
                if not message:
                    raise ValueError("pending_message cannot be empty")
                state.pending_message = message
                changed = True

            if changed:
                self._generation += 1
                state.generation = self._generation
                state.updated_at = now
                state.user_modified = True
                self._cancel_task()
                self._task = asyncio.create_task(self._run_timer(state.timer_id, state.generation))
                self._publish(SystemEvent.INITIATIVE_TIMER_UPDATED, state, extra={"source": "user"})
            return self._payload(state)

    async def trigger(self, *, timer_id: str | None = None, source: str = "user") -> dict[str, Any]:
        """立即触发当前积存主动消息。"""
        async with self._lock:
            state = self._require_current(timer_id)
            return await self._trigger_locked(state, source=source)

    async def shutdown(self) -> None:
        """关闭并取消后台定时任务。"""
        async with self._lock:
            await self._discard_locked(reason="shutdown", source="system")

    async def _decide(self, assistant_response: str) -> dict[str, Any] | None:
        recent_messages = self.working_memory.get_recent(6)
        prompt = f"""你是 {self.character_name}。

你刚刚回复了用户：
{assistant_response}

请判断你是否想在稍后主动补充一句话。要求：
- 如果没有自然、必要、符合角色的补充，就不要设置定时器。
- 如果设置，只写一条短消息，像真实角色稍后主动开口一样自然。
- 延迟秒数必须在 {self.config.min_delay_seconds} 到 {self.config.max_delay_seconds} 之间。
- 只输出 JSON，不要输出解释。

JSON 格式：
{{
  "should_schedule": true/false,
  "delay_seconds": 120,
  "message": "稍后主动说的话",
  "reason": "简短理由"
}}
"""
        messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
        for item in recent_messages:
            role = item.get("role")
            content = item.get("content")
            if isinstance(role, str) and isinstance(content, str) and role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        try:
            response = await self.model_client.chat(
                messages=messages,
                options={
                    "temperature": self.config.decision_temperature,
                    "num_predict": self.config.decision_max_tokens,
                    "max_tokens": self.config.decision_max_tokens,
                },
            )
            content = response.message.content
            text = content.strip() if isinstance(content, str) else ""
            data = self._parse_decision_json(text)
            if self.debug_silent_output:
                logger.info(f"⏲️ [InitiativeTimer] 决策: {data}")
            return data
        except Exception as error:
            logger.error(f"主动定时器决策失败: {error}")
            return None

    @staticmethod
    def _parse_decision_json(text: str) -> dict[str, Any] | None:
        match = _JSON_OBJECT_PATTERN.search(text)
        raw = match.group(0) if match else text
        data = json.loads(raw)
        return data if isinstance(data, dict) else None

    def _create_state(
        self,
        *,
        delay_seconds: int,
        pending_message: str,
        reason: str,
        source: str,
        user_modified: bool,
    ) -> InitiativeTimerState:
        now = datetime.now(UTC)
        self._generation += 1
        return InitiativeTimerState(
            timer_id=str(uuid4())[:8],
            status="scheduled",
            generation=self._generation,
            source=source,
            created_at=now,
            updated_at=now,
            due_at=now + timedelta(seconds=delay_seconds),
            delay_seconds=delay_seconds,
            pending_message=pending_message,
            reason=reason,
            user_modified=user_modified,
        )

    async def _run_timer(self, timer_id: str, generation: int) -> None:
        try:
            while True:
                async with self._lock:
                    state = self._state
                    if not state or state.timer_id != timer_id or state.generation != generation:
                        return
                    remaining = (state.due_at - datetime.now(UTC)).total_seconds()
                    if remaining <= 0:
                        await self._trigger_locked(state, source="timer")
                        return
                await asyncio.sleep(min(remaining, 1.0))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(f"主动定时器任务异常: {error}")

    async def _trigger_locked(self, state: InitiativeTimerState, *, source: str) -> dict[str, Any]:
        self._generation += 1
        state.status = "triggered"
        state.updated_at = datetime.now(UTC)
        message = state.pending_message
        payload = self._payload(state)
        self._state = None
        self._cancel_task()
        self._publish(
            SystemEvent.THINK_ENGINE_INITIATIVE, state, extra={"message": message, "source": source}
        )
        self.event_bus.publish(
            Event(
                type=SystemEvent.MESSAGE_SENT,
                source="initiative_timer",
                data={"content": message, "initiative": True, "timer_id": state.timer_id},
            )
        )
        self._publish(
            SystemEvent.INITIATIVE_TIMER_TRIGGERED,
            state,
            extra={"message": message, "source": source},
        )
        return {"triggered": True, "timer_id": state.timer_id, "message": message, "timer": payload}

    async def _discard_locked(self, *, reason: str, source: str) -> dict[str, Any] | None:
        state = self._state
        if state is None:
            return None
        self._generation += 1
        state.status = "discarded"
        state.updated_at = datetime.now(UTC)
        payload = self._payload(state)
        self._state = None
        self._cancel_task()
        self._publish(
            SystemEvent.INITIATIVE_TIMER_DISCARDED,
            state,
            extra={"reason": reason, "source": source},
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
            task.cancel()
        self._task = None

    def _payload(self, state: InitiativeTimerState) -> dict[str, Any]:
        now = datetime.now(UTC)
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
            "editable_fields": ["due_at", "delay_seconds", "pending_message"]
            if self.config.allow_frontend_edit_message
            else ["due_at", "delay_seconds"],
        }
        if self.config.expose_pending_message:
            payload["pending_message"] = state.pending_message
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

    def _trim_message(self, message: str) -> str:
        return message[: self.config.max_pending_message_chars].strip()

    @staticmethod
    def _parse_due_at(value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
