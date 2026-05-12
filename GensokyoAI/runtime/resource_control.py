"""Runtime 资源控制通用组件。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceLimitError(RuntimeError):
    """资源闸门拒绝请求时抛出的结构化异常。"""

    resource: str
    reason: str
    max_concurrent: int
    queue_size: int
    active: int
    waiting: int
    action: str | None = None

    def __post_init__(self) -> None:
        super().__init__(f"Runtime resource gate '{self.resource}' rejected request: {self.reason}")

    def to_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "resource": self.resource,
            "reason": self.reason,
            "max_concurrent": self.max_concurrent,
            "queue_size": self.queue_size,
            "active": self.active,
            "waiting": self.waiting,
        }
        if self.action:
            details["action"] = self.action
        return details


@dataclass
class ResourceGate:
    """Small async gate with bounded waiting queue for Runtime resource classes."""

    name: str
    max_concurrent: int
    queue_size: int
    acquire_timeout_seconds: float
    overflow_policy: str = "reject"
    active: int = 0
    waiting: int = 0

    def __post_init__(self) -> None:
        self.max_concurrent = max(1, int(self.max_concurrent))
        self.queue_size = max(0, int(self.queue_size))
        self.acquire_timeout_seconds = max(0.0, float(self.acquire_timeout_seconds))
        self._semaphore = asyncio.BoundedSemaphore(self.max_concurrent)
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            if self._semaphore.locked() and self.waiting >= self.queue_size:
                raise self._limit_error("queue_full")
            wait_timeout = self.acquire_timeout_seconds
            self.waiting += 1
        try:
            if self.overflow_policy == "wait" and wait_timeout > 0:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=wait_timeout)
            elif self.overflow_policy == "wait":
                await self._semaphore.acquire()
            elif wait_timeout > 0:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=wait_timeout)
            else:
                if self._semaphore.locked():
                    raise TimeoutError("resource acquire timeout")
                await self._semaphore.acquire()
        except TimeoutError as error:
            raise self._limit_error("acquire_timeout") from error
        finally:
            async with self._lock:
                self.waiting = max(0, self.waiting - 1)
        async with self._lock:
            self.active += 1

    async def release(self) -> None:
        async with self._lock:
            self.active = max(0, self.active - 1)
        self._semaphore.release()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "queue_size": self.queue_size,
            "active": self.active,
            "waiting": self.waiting,
            "acquire_timeout_seconds": self.acquire_timeout_seconds,
            "overflow_policy": self.overflow_policy,
        }

    def _limit_error(self, reason: str) -> ResourceLimitError:
        return ResourceLimitError(
            resource=self.name,
            reason=reason,
            max_concurrent=self.max_concurrent,
            queue_size=self.queue_size,
            active=self.active,
            waiting=self.waiting,
        )


@asynccontextmanager
async def resource_scope(
    gate: ResourceGate | None,
    action: str,
) -> AsyncIterator[None]:
    """Acquire and release one optional resource gate."""

    if gate is None:
        yield
        return
    try:
        await gate.acquire()
    except ResourceLimitError as error:
        error.action = action
        raise
    try:
        yield
    finally:
        await gate.release()


def resource_limit_payload(error: ResourceLimitError) -> dict[str, Any]:
    """Return stable structured payload fields for resource limit errors."""

    return {
        "code": "resource.limit_exceeded",
        "technical_message": str(error),
        "user_message": "Runtime 当前资源繁忙，请稍后重试。",
        "recoverable": True,
        "action_hint": "请稍后重试，或调大 resource_control 中对应并发 / 队列配置。",
        "details": error.to_details(),
    }


def build_resource_gates(resource_control: Any) -> dict[str, ResourceGate]:
    """Build all configured Runtime resource gates, including P2 deep gates."""

    config = resource_control
    queue_size = getattr(config, "runtime_queue_size", 8)
    acquire_timeout = getattr(config, "acquire_timeout_seconds", 0.25)
    overflow_policy = getattr(config, "overflow_policy", "reject")
    if not getattr(config, "enabled", True):
        high_limit = 1_000_000
        queue_size = high_limit
        acquire_timeout = 0
        overflow_policy = "wait"
    return {
        "runtime": ResourceGate(
            "runtime",
            getattr(config, "runtime_max_concurrent", 4),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "agent_message": ResourceGate(
            "agent_message",
            getattr(config, "session_max_concurrent", 1),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "provider": ResourceGate(
            "provider",
            getattr(config, "provider_max_concurrent", 2),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "model": ResourceGate(
            "model",
            getattr(config, "model_max_concurrent", 2),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "stream": ResourceGate(
            "stream",
            getattr(config, "stream_max_concurrent", 1),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "tool": ResourceGate(
            "tool",
            getattr(config, "tool_max_concurrent", 2),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "web_search": ResourceGate(
            "web_search",
            getattr(config, "web_search_max_concurrent", 1),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "image_generation": ResourceGate(
            "image_generation",
            getattr(config, "image_generation_max_concurrent", 1),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
        "dependency_install": ResourceGate(
            "dependency_install",
            getattr(config, "dependency_install_max_concurrent", 1),
            queue_size,
            acquire_timeout,
            overflow_policy,
        ),
    }
