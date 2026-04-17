"""事件系统 - 解耦所有组件"""

import asyncio
from typing import Callable, Any, Optional
from enum import Enum
from datetime import datetime
from msgspec import Struct, field
from uuid import uuid4
import inspect

from ..utils.logging import logger


class EventPriority(Enum):
    """事件优先级"""
    HIGHEST = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LOWEST = 4


class SystemEvent(Enum):
    """系统事件类型"""
    
    # 生命周期事件
    AGENT_STARTED = "agent.started"
    AGENT_SHUTDOWN = "agent.shutdown"
    AGENT_SHUTDOWN_COMPLETE = "agent.shutdown.complete"
    
    # 会话事件
    SESSION_CREATED = "session.created"
    SESSION_RESUMED = "session.resumed"
    SESSION_DELETED = "session.deleted"
    SESSION_SWITCHED = "session.switched"
    
    # 对话事件
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_PROCESSING = "message.processing"
    MESSAGE_RESPONSE_READY = "message.response.ready"
    MESSAGE_SENT = "message.sent"
    MESSAGE_STREAM_CHUNK = "message.stream.chunk"
    
    # 记忆事件
    MEMORY_WORKING_ADDED = "memory.working.added"
    MEMORY_EPISODIC_COMPRESSED = "memory.episodic.compressed"
    MEMORY_SEMANTIC_ADDED = "memory.semantic.added"
    MEMORY_SEMANTIC_RECALLED = "memory.semantic.recalled"
    MEMORY_SEMANTIC_ADDED_RESPONSE = "memory.semantic.added.response"
    MEMORY_SEMANTIC_RECALLED_RESPONSE = "memory.semantic.recalled.response"
    
    # 工具事件
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"
    
    # 持久化事件
    PERSISTENCE_SAVE_STARTED = "persistence.save.started"
    PERSISTENCE_SAVE_COMPLETED = "persistence.save.completed"
    PERSISTENCE_SAVE_FAILED = "persistence.save.failed"
    
    # 错误事件
    ERROR_OCCURRED = "error.occurred"
    MODEL_ERROR = "error.model"
    TOOL_ERROR = "error.tool"
    
    # 后台任务事件
    BACKGROUND_TASK_SUBMITTED = "background.task.submitted"
    BACKGROUND_TASK_COMPLETED = "background.task.completed"
    BACKGROUND_TASK_FAILED = "background.task.failed"


class Event(Struct):
    """事件"""
    
    type: SystemEvent
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    source: str = "unknown"
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
    
    @property
    def type_str(self) -> str:
        return self.type.value


class Subscription:
    """订阅信息"""
    
    def __init__(
        self,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
        filter_func: Optional[Callable[["Event"], bool]] = None,
    ):
        self.id = str(uuid4())[:8]
        self.handler = handler
        self.priority = priority
        self.once = once
        self.filter_func = filter_func
        self.handler_name = self._get_handler_name(handler)
    
    def _get_handler_name(self, handler: Callable) -> str:
        if hasattr(handler, '__name__'):
            return handler.__name__
        elif hasattr(handler, '__class__'):
            return f"{handler.__class__.__name__}.handle"
        elif hasattr(handler, '__self__'):
            return f"{handler.__self__.__class__.__name__}.{getattr(handler, '__name__', 'handle')}" # type: ignore
        else:
            return str(handler)[:50]


class EventBus:
    """事件总线 - 完全解耦的发布订阅，带完整追踪日志"""

    def __init__(self, enable_trace: bool = True):
        self._subscribers: dict[SystemEvent, list[Subscription]] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._stats = {
            "published": 0,
            "delivered": 0,
            "errors": 0,
            "filtered": 0,
        }
        
        self.enable_trace = enable_trace
        
        # 🆕 请求-响应机制
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._response_timeout = 30.0  # 默认超时

    # ==================== 生命周期 ====================

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._event_worker())
        
        if self.enable_trace:
            logger.info("🚀 [EventBus] 事件总线已启动")

    async def stop(self) -> None:
        """停止事件总线"""
        if not self._running:
            return
        
        if self.enable_trace:
            logger.info(f"🛑 [EventBus] 正在停止... (队列剩余: {self._event_queue.qsize()})")
        
        self._running = False
        
        # 🆕 取消所有等待中的请求
        for request_id, future in list(self._pending_requests.items()):
            if not future.done():
                future.set_exception(asyncio.CancelledError("EventBus stopped"))
        self._pending_requests.clear()
        
        # 🆕 等待工作器处理完当前事件
        if self._worker_task and not self._worker_task.done():
            try:
                # 给工作器一点时间处理当前事件
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        remaining = self._event_queue.qsize()
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
                self._event_queue.task_done()
            except (asyncio.QueueEmpty, ValueError):
                break
        
        if self.enable_trace:
            logger.info(f"🛑 [EventBus] 事件总线已停止 (丢弃 {remaining} 个未处理事件)")
            logger.info(f"   📊 统计: 发布 {self._stats['published']}, "
                    f"投递 {self._stats['delivered']}, "
                    f"过滤 {self._stats['filtered']}, "
                    f"错误 {self._stats['errors']}")

    async def _event_worker(self) -> None:
        """事件处理工作器"""
        logger.debug("🔄 [EventBus] 工作器线程已启动")
        
        while self._running:
            try:
                # 🆕 关键：直接 await，不要用 wait_for
                event = await self._event_queue.get()
                
                if self.enable_trace:
                    logger.debug(f"📬 [EventBus] 从队列取出事件: {event.type.value} (队列剩余: {self._event_queue.qsize()})")
                
                await self._process_event(event)
                self._event_queue.task_done()
                
            except asyncio.CancelledError:
                logger.debug("🛑 [EventBus] 工作器收到取消信号")
                break
            except Exception as e:
                logger.error(f"❌ [EventBus] 事件处理异常: {e}", exc_info=True)
                self._stats["errors"] += 1
                # 🆕 即使处理失败，也要标记任务完成
                try:
                    self._event_queue.task_done()
                except ValueError:
                    pass
        
        logger.debug(f"🛑 [EventBus] 工作器线程已停止 (running={self._running})")

    # ==================== 订阅管理 ====================

    def subscribe(
        self,
        event_type: SystemEvent,
        handler: Callable[[Event], Any],
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        sub = Subscription(handler, priority, once, filter_func)
        
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(sub)
        self._subscribers[event_type].sort(key=lambda s: s.priority.value)
        
        if self.enable_trace:
            filter_info = " (带过滤)" if filter_func else ""
            once_info = " (一次性)" if once else ""
            logger.debug(
                f"📌 [EventBus] 订阅: '{event_type.value}' -> {sub.handler_name}"
                f"{filter_info}{once_info} [优先级: {priority.name}]"
            )
        
        return sub.id

    def subscribe_all(
        self,
        event_types: list[SystemEvent],
        handler: Callable[[Event], Any],
        priority: EventPriority = EventPriority.NORMAL,
    ) -> list[str]:
        return [self.subscribe(et, handler, priority) for et in event_types]

    def unsubscribe(self, subscription_id: str) -> bool:
        for event_type, subs in self._subscribers.items():
            for sub in subs:
                if sub.id == subscription_id:
                    subs.remove(sub)
                    if self.enable_trace:
                        logger.debug(f"🔕 [EventBus] 取消订阅: {subscription_id} ({sub.handler_name})")
                    return True
        return False

    # ==================== 事件发布 ====================

    def publish(self, event: Event, immediate: bool = False) -> None:
        if self.enable_trace:
            data_preview = self._format_data_preview(event.data)
            logger.info(
                f"📢 [EventBus] 事件触发: '{event.type.value}' "
                f"(来源: {event.source}, ID: {event.id}) {data_preview}"
            )
        
        if immediate:
            asyncio.create_task(self._process_event(event))
        else:
            try:
                self._event_queue.put_nowait(event)
                self._stats["published"] += 1
            except asyncio.QueueFull:
                logger.warning(f"⚠️ [EventBus] 事件队列已满，丢弃事件: {event.type.value}")

    # 🆕 异步请求-响应（非阻塞）
    async def request(
        self,
        event: Event,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        发送请求事件并等待响应（异步非阻塞）
        
        Args:
            event: 请求事件
            timeout: 超时时间（秒），默认 30 秒
            
        Returns:
            第一个有效响应结果
        """
        request_id = event.id
        
        # 创建 Future 等待响应
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future
        
        try:
            # 发布请求事件
            self.publish(event)
            
            # 等待响应（非阻塞，只挂起当前协程）
            timeout_val = timeout or self._response_timeout
            result = await asyncio.wait_for(future, timeout=timeout_val)
            return result
            
        except asyncio.TimeoutError:
            if self.enable_trace:
                logger.warning(f"⏰ [EventBus] 请求超时: {event.type.value} (ID: {request_id})")
            return None
        except asyncio.CancelledError:
            if self.enable_trace:
                logger.debug(f"🚫 [EventBus] 请求被取消: {event.type.value} (ID: {request_id})")
            return None
        finally:
            self._pending_requests.pop(request_id, None)

    def respond(self, request_event: Event, result: Any) -> None:
        """
        响应请求事件
        
        Args:
            request_event: 原始请求事件
            result: 响应结果
        """
        request_id = request_event.id
        future = self._pending_requests.get(request_id)
        
        if future and not future.done():
            future.set_result(result)
            if self.enable_trace:
                logger.debug(f"✅ [EventBus] 请求响应: {request_event.type.value} (ID: {request_id})")
        else:
            # 如果没有等待者，发布普通响应事件
            response_event = Event(
                type=SystemEvent.MEMORY_SEMANTIC_ADDED_RESPONSE
                if request_event.type == SystemEvent.MEMORY_SEMANTIC_ADDED
                else SystemEvent.MEMORY_SEMANTIC_RECALLED_RESPONSE,
                source="eventbus",
                data={"request_id": request_id, "result": result}
            )
            self.publish(response_event)

    async def _process_event(self, event: Event) -> list[Any]:
        if event.type not in self._subscribers:
            if self.enable_trace:
                logger.debug(f"👻 [EventBus] 事件 '{event.type.value}' 无订阅者")
            return []

        subscribers = self._subscribers[event.type]
        
        if self.enable_trace:
            logger.debug(f"🔄 [EventBus] 处理事件 '{event.type.value}' -> {len(subscribers)} 个订阅者")

        results = []
        to_remove = []
        
        for sub in sorted(subscribers, key=lambda s: s.priority.value):
            if sub.filter_func:
                try:
                    if not sub.filter_func(event):
                        self._stats["filtered"] += 1
                        if self.enable_trace:
                            logger.debug(f"   ⏭️  [EventBus] 跳过 {sub.handler_name} (被过滤器过滤)")
                        continue
                except Exception as e:
                    logger.warning(f"⚠️ [EventBus] 过滤器异常 {sub.handler_name}: {e}")
                    continue
            
            try:
                if self.enable_trace:
                    logger.info(f"   📨 [EventBus] 推送给处理器: {sub.handler_name} 执行")
                
                handler = sub.handler
                start_time = datetime.now()
                
                if inspect.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = await asyncio.to_thread(handler, event)
                
                elapsed = (datetime.now() - start_time).total_seconds() * 1000
                
                if self.enable_trace:
                    logger.info(f"   ✅ [EventBus] {sub.handler_name} 执行完成 ({elapsed:.1f}ms)")
                
                results.append(result)
                self._stats["delivered"] += 1
                
                if sub.once:
                    to_remove.append(sub)
                    
            except Exception as e:
                self._stats["errors"] += 1
                
                if self.enable_trace:
                    logger.error(f"   ❌ [EventBus] {sub.handler_name} 执行失败: {e}")
                
                error_event = Event(
                    type=SystemEvent.ERROR_OCCURRED,
                    source="eventbus",
                    data={
                        "original_event": {
                            "id": event.id,
                            "type": event.type.value,
                            "source": event.source,
                        },
                        "handler": sub.handler_name,
                        "error": str(e)
                    }
                )
                self.publish(error_event)

        for sub in to_remove:
            self._subscribers[event.type].remove(sub)
            if self.enable_trace:
                logger.debug(f"   🗑️  [EventBus] 移除一次性订阅: {sub.handler_name}")

        return results

    def _format_data_preview(self, data: Any) -> str:
        if data is None:
            return ""
        
        if isinstance(data, dict):
            if "content" in data:
                content = str(data["content"])
                preview = content[:50] + "..." if len(content) > 50 else content
                return f"[content: {preview}]"
            elif "name" in data:
                return f"[name: {data['name']}]"
            elif "session_id" in data:
                return f"[session: {str(data['session_id'])[:8]}...]"
            else:
                keys = list(data.keys())[:3]
                return f"[{', '.join(keys)}]"
        
        if isinstance(data, str):
            preview = data[:50] + "..." if len(data) > 50 else data
            return f'"{preview}"'
        
        return f"({type(data).__name__})"

    # ==================== 装饰器 ====================

    def on(self, event_type: SystemEvent, priority: EventPriority = EventPriority.NORMAL):
        def decorator(handler: Callable):
            self.subscribe(event_type, handler, priority)
            return handler
        return decorator

    def once(self, event_type: SystemEvent):
        def decorator(handler: Callable):
            self.subscribe(event_type, handler, once=True)
            return handler
        return decorator

    # ==================== 查询 ====================

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "queue_size": self._event_queue.qsize(),
            "subscriber_count": sum(len(subs) for subs in self._subscribers.values()),
            "event_types": [et.value for et in self._subscribers.keys()],
            "pending_requests": len(self._pending_requests),
        }

    def list_subscribers(self, event_type: Optional[SystemEvent] = None) -> dict:
        if event_type:
            return {
                event_type.value: [
                    {"id": s.id, "handler": s.handler_name, "priority": s.priority.name}
                    for s in self._subscribers.get(event_type, [])
                ]
            }
        return {
            et.value: [
                {"id": s.id, "handler": s.handler_name, "priority": s.priority.name}
                for s in subs
            ]
            for et, subs in self._subscribers.items()
        }