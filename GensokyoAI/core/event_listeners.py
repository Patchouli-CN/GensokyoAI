"""事件监听器 - 响应系统事件"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .events import Event, SystemEvent, EventBus
from ..memory.types import TopicMemory, TopicMemoryType
from ..utils.logging import logger

if TYPE_CHECKING:
    from .agent import Agent


class CoreListeners:
    """核心事件监听器"""

    def __init__(self, agent: "Agent", event_bus: EventBus):
        self.agent = agent
        self.event_bus = event_bus
        self._register()

    def _register(self) -> None:
        bus = self.event_bus

        # 会话事件
        bus.subscribe(SystemEvent.SESSION_CREATED, self.on_session_created)
        bus.subscribe(SystemEvent.SESSION_RESUMED, self.on_session_resumed)

        # 对话事件
        bus.subscribe(SystemEvent.MESSAGE_RECEIVED, self.on_message_received)
        bus.subscribe(SystemEvent.MESSAGE_SENT, self.on_message_sent)  # 🔧 合并为异步

        # 记忆事件
        bus.subscribe(SystemEvent.MEMORY_WORKING_ADDED, self.on_working_memory_added)
        bus.subscribe(SystemEvent.MEMORY_EPISODIC_COMPRESSED, self.on_episodic_compressed)

        # 工具事件
        bus.subscribe(SystemEvent.TOOL_CALL_STARTED, self.on_tool_call_started)
        bus.subscribe(SystemEvent.TOOL_CALL_COMPLETED, self.on_tool_call_completed)

        # 持久化事件
        bus.subscribe(SystemEvent.PERSISTENCE_SAVE_COMPLETED, self.on_persistence_saved)

        # 错误事件
        bus.subscribe(SystemEvent.ERROR_OCCURRED, self.on_error)

        logger.debug("核心监听器已注册")

    # ==================== 会话事件 ====================

    async def on_session_created(self, event: Event) -> None:
        session = event.data.get("session")
        if session:
            logger.info(f"会话已创建: {session.session_id[:8]}...")

    async def on_session_resumed(self, event: Event) -> None:
        session = event.data.get("session")
        if session:
            logger.info(f"会话已恢复: {session.session_id[:8]}...")

    # ==================== 对话事件 ====================

    async def on_message_received(self, event: Event) -> None:
        user_input = event.data.get("content", "")
        logger.debug(f"收到消息: {user_input[:50]}...")

        if hasattr(self.agent, "working_memory"):
            self.agent.working_memory.add_message("user", user_input)

    async def on_message_sent(self, event: Event) -> None:
        """异步记录助手消息和日志"""
        response = event.data.get("content", "")
        if hasattr(self.agent, "working_memory") and response:
            self.agent.working_memory.add_message("assistant", response)
            logger.debug(f"记录助手消息: {response[:50]}...")
        logger.debug(f"发送响应: {response[:50]}...")

    # ==================== 记忆事件 ====================

    async def on_working_memory_added(self, event: Event) -> None:
        role = event.data.get("role")
        content = event.data.get("content", "")

        if role == "assistant" and len(content) > 50:
            self.event_bus.publish(
                Event(
                    type=SystemEvent.MEMORY_SEMANTIC_ADDED,
                    source="core.listeners",
                    data={"content": content, "importance": 0.5},
                )
            )

    async def on_episodic_compressed(self, event: Event) -> None:
        episode = event.data.get("episode")
        if episode:
            logger.info(f"情景记忆已压缩: {episode.summary[:50]}...")

    # ==================== 工具事件 ====================

    async def on_tool_call_started(self, event: Event) -> None:
        tool_name = event.data.get("name")
        logger.debug(f"工具调用开始: {tool_name}")

    async def on_tool_call_completed(self, event: Event) -> None:
        tool_name = event.data.get("name")
        result = event.data.get("result", "")
        logger.debug(f"工具调用完成: {tool_name} -> {result[:50] if result else ''}...")

    # ==================== 持久化事件 ====================

    async def on_persistence_saved(self, event: Event) -> None:
        session_id = event.data.get("session_id", "")
        logger.debug(f"会话已持久化: {session_id[:8] if session_id else ''}...")

    # ==================== 错误事件 ====================

    async def on_error(self, event: Event) -> None:
        error = event.data.get("error")
        original_event = event.data.get("original_event", {})
        logger.error(f"事件处理错误 [{original_event.get('type', 'unknown')}]: {error}")


class MemoryServiceListeners:
    """记忆服务监听器 - 响应工具的记忆请求"""

    def __init__(self, agent: "Agent", event_bus: EventBus):
        self.agent = agent
        self.event_bus = event_bus
        self._register()

    def _register(self) -> None:
        self.event_bus.subscribe(
            SystemEvent.MEMORY_SEMANTIC_ADDED,
            self.on_memory_add_request,
        )
        self.event_bus.subscribe(
            SystemEvent.MEMORY_SEMANTIC_RECALLED,
            self.on_memory_recall_request,
        )
        self.event_bus.subscribe(
            SystemEvent.MEMORY_SEMANTIC_UPDATED,
            self.on_memory_update_request,
        )

    async def on_memory_add_request(self, event: Event) -> None:
        """处理记忆添加请求"""
        if not event.source.startswith("tool."):
            return

        data = event.data
        content = data.get("content", "")
        importance = data.get("importance", 0.5)
        topic_name = data.get("topic_name")
        emotional_valence = data.get("emotional_valence", 0.0)

        if not content:
            self.event_bus.respond(event, None)
            return

        try:
            if hasattr(self.agent, "semantic_memory"):
                topic = await self.agent.semantic_memory.add_async(
                    content=content,
                    importance=importance,
                    emotional_valence=emotional_valence,
                    topic_name=topic_name,
                )
                if topic:
                    logger.debug(
                        f"记忆服务: 已存储 -> 话题「{topic.name}」(情感: {topic.emotional_valence:.2f})"
                    )
                    self.event_bus.respond(event, {"topic_name": topic.name, "topic_id": topic.id})
                    return
        except Exception as e:
            logger.error(f"记忆服务: 存储失败 - {e}")

        self.event_bus.respond(event, None)

    async def on_memory_recall_request(self, event: Event) -> None:
        """处理记忆检索请求"""
        if not event.source.startswith("tool."):
            return

        data = event.data
        keyword = data.get("keyword", "")
        category = data.get("category")
        page = data.get("page", 1)

        if not keyword:
            self.event_bus.respond(event, None)
            return

        try:
            if hasattr(self.agent, "semantic_memory"):
                store = self.agent.semantic_memory.store
                results = store.search(query_text=keyword, top_k=20)

                if category:
                    results = [r for r in results if category in r.get("tags", [])]

                if not results:
                    self.event_bus.respond(event, f"「关于 '{keyword}' …我好像没什么印象…」")
                    return

                page_size = 5
                total = len(results)
                total_pages = (total + page_size - 1) // page_size
                page = max(1, min(page, total_pages))
                start = (page - 1) * page_size
                page_data = results[start : start + page_size]

                lines = [f"「关于 '{keyword}' 的记忆：」"]
                for i, item in enumerate(page_data, start=start + 1):
                    content = item.get("content", "")
                    tags = item.get("tags", [])
                    tag_str = f"[{','.join(tags)}]" if tags else ""
                    lines.append(f"  {i}. {tag_str} {content}")

                if total_pages > 1:
                    lines.append(f"  --- 第 {page}/{total_pages} 页 ---")

                self.event_bus.respond(event, "\n".join(lines))
                return

        except Exception as e:
            logger.error(f"记忆服务: 检索失败 - {e}")

        self.event_bus.respond(event, None)

    async def on_memory_update_request(self, event: Event) -> None:
        """处理记忆更新请求"""
        if not event.source.startswith("tool."):
            return

        data = event.data
        topic_name = data.get("topic_name", "")
        new_content = data.get("new_content", "")
        reason = data.get("reason", "信息更新")

        if not topic_name or not new_content:
            self.event_bus.respond(event, None)
            return

        try:
            if hasattr(self.agent, "semantic_memory"):
                store = self.agent.semantic_memory.store
                topic_name_lower = topic_name.lower()

                if topic_name_lower in store._topic_name_index:
                    topic_id = store._topic_name_index[topic_name_lower]
                    topic = store._topics[topic_id]

                    # 创建新记忆，标记取代旧记忆
                    memory = TopicMemory(
                        content=new_content,
                        importance=0.7,  # 更新记忆默认较高重要性
                        memory_type=TopicMemoryType.CORRECTION,
                        supersedes=topic.message_ids[-1] if topic.message_ids else None,
                    )
                    store._memories[memory.id] = memory

                    # 更新话题
                    store._update_topic(topic, memory, 0.7, 10.0)
                    await store._save_async()

                    logger.info(f"记忆服务: 已更新话题「{topic_name}」，原因: {reason}")
                    self.event_bus.respond(event, {"topic_name": topic.name, "updated": True})
                    return

        except Exception as e:
            logger.error(f"记忆服务: 更新失败 - {e}")

        self.event_bus.respond(event, None)


class MetricsListeners:
    """指标收集监听器"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._metrics = {
            "messages_sent": 0,
            "messages_received": 0,
            "tool_calls": 0,
            "memories_added": 0,
            "errors": 0,
        }
        self._register()

    def _register(self) -> None:
        # 🔧 全部改为异步订阅
        self.event_bus.subscribe(SystemEvent.MESSAGE_RECEIVED, self._async_inc_received)
        self.event_bus.subscribe(SystemEvent.MESSAGE_SENT, self._async_inc_sent)
        self.event_bus.subscribe(SystemEvent.TOOL_CALL_COMPLETED, self._async_inc_tool)
        self.event_bus.subscribe(SystemEvent.MEMORY_SEMANTIC_ADDED, self._async_inc_memory)
        self.event_bus.subscribe(SystemEvent.ERROR_OCCURRED, self._async_inc_error)

    async def _async_inc_received(self, event: Event) -> None:
        self._metrics["messages_received"] += 1

    async def _async_inc_sent(self, event: Event) -> None:
        self._metrics["messages_sent"] += 1

    async def _async_inc_tool(self, event: Event) -> None:
        self._metrics["tool_calls"] += 1

    async def _async_inc_memory(self, event: Event) -> None:
        self._metrics["memories_added"] += 1

    async def _async_inc_error(self, event: Event) -> None:
        self._metrics["errors"] += 1

    @property
    def metrics(self) -> dict:
        return self._metrics.copy()


class ErrorListeners:
    """错误事件监听器"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._error_counts: dict[str, int] = {}
        self._last_errors: list[dict] = []
        self._register()

    def _register(self) -> None:
        # 🔧 全部改为异步订阅
        self.event_bus.subscribe(SystemEvent.MODEL_ERROR, self._async_update_model_error)
        self.event_bus.subscribe(SystemEvent.TOOL_ERROR, self._async_update_tool_error)
        self.event_bus.subscribe(SystemEvent.ERROR_OCCURRED, self._async_update_general_error)

    async def _async_update_model_error(self, event: Event) -> None:
        """异步更新模型错误统计并记录日志"""
        data = event.data
        context = data.get("context", "unknown")
        key = f"model:{context}"
        self._error_counts[key] = self._error_counts.get(key, 0) + 1

        error_entry = {
            "timestamp": event.timestamp,
            "type": "model_error",
            "model": data.get("model", "unknown"),
            "context": context,
            "error": data.get("error", "未知错误"),
            "status_code": data.get("status_code"),
        }
        self._last_errors.append(error_entry)
        if len(self._last_errors) > 10:
            self._last_errors.pop(0)

        # 日志记录也合并进来
        status_code = data.get("status_code")
        model = data.get("model", "unknown")
        error_msg = data.get("error", "未知错误")

        if status_code == "502":
            logger.warning(
                f"🔌 [ErrorListener] 502 连接错误 (模型: {model}, 上下文: {context})\n"
                f"   建议检查: 1) Ollama 是否运行 2) 代理设置 3) 防火墙"
            )
        else:
            logger.error(f"🤖 [ErrorListener] 模型错误: {model} - {error_msg}")

    async def _async_update_tool_error(self, event: Event) -> None:
        """异步更新工具错误统计并记录日志"""
        data = event.data
        tool_name = data.get("tool_name", "unknown")
        key = f"tool:{tool_name}"
        self._error_counts[key] = self._error_counts.get(key, 0) + 1

        error_entry = {
            "timestamp": event.timestamp,
            "type": "tool_error",
            "tool": tool_name,
            "error": data.get("error", "未知错误"),
        }
        self._last_errors.append(error_entry)
        if len(self._last_errors) > 10:
            self._last_errors.pop(0)

        logger.error(f"🔧 [ErrorListener] 工具错误: {tool_name} - {data.get('error', '未知错误')}")

    async def _async_update_general_error(self, event: Event) -> None:
        """异步更新通用错误统计并记录日志"""
        key = "general"
        self._error_counts[key] = self._error_counts.get(key, 0) + 1

        error_entry = {
            "timestamp": event.timestamp,
            "type": "general_error",
            "error": event.data.get("error", "未知错误"),
        }
        self._last_errors.append(error_entry)
        if len(self._last_errors) > 10:
            self._last_errors.pop(0)

        data = event.data
        error_msg = data.get("error", "未知错误")
        original_event = data.get("original_event", {})
        logger.error(
            f"❌ [ErrorListener] 通用错误: {error_msg}\n"
            f"   原始事件: {original_event.get('type', 'unknown')}"
        )

    # 查询接口保持不变
    def get_error_stats(self) -> dict:
        return {
            "counts": self._error_counts.copy(),
            "recent": self._last_errors.copy(),
            "total": sum(self._error_counts.values()),
        }

    def has_recent_502(self, within_seconds: int = 60) -> bool:
        cutoff = datetime.now() - timedelta(seconds=within_seconds)
        for err in self._last_errors:
            if err.get("status_code") == "502" and err["timestamp"] > cutoff:
                return True
        return False
