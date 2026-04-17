"""后台任务管理器 - 基于队列的事件驱动模式"""

# GensokyoAI\background\manager.py

import asyncio
from typing import Callable, Awaitable

from .types import (
    BackgroundTask,
    TaskResult,
    TaskType,
    TaskPriority,
    MemoryTaskData,
    PersistenceTaskData,
)
from .workers import PersistenceWorker
from .workers.base import BaseWorker
from ..utils.logging import logger


class TaskContext:
    """任务上下文管理器，自动处理 task_done"""

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._task = None

    async def __aenter__(self):
        self._task = await self._queue.get()
        return self._task

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._queue.task_done()


class BackgroundManager:
    """后台任务管理器

    职责：
    - 管理任务队列
    - 委托任务给对应的工作器
    - 控制并发数量
    - 不处理具体业务逻辑
    """

    def __init__(self, max_workers: int = 3, max_queue_size: int = 100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

        # 使用 asyncio.Queue 替代轮询
        self._task_queue: asyncio.Queue[BackgroundTask] = asyncio.Queue(maxsize=max_queue_size)

        # 工作器注册表
        self._workers: dict[TaskType, BaseWorker] = {}

        # 运行状态
        self._running = False
        self._worker_tasks: list[asyncio.Task] = []
        self._result_callbacks: list[Callable[[TaskResult], Awaitable[None]]] = []

        # 统计信息
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "timeout": 0,
            "dropped": 0,
        }
        self._stats_lock = asyncio.Lock()

    # ==================== 工作器注册 ====================

    def register_worker(self, task_type: TaskType, worker: BaseWorker) -> "BackgroundManager":
        """注册工作器"""
        self._workers[task_type] = worker
        logger.debug(f"注册工作器: {task_type.name}")
        return self

    def register_persistence_worker(self, worker: PersistenceWorker) -> "BackgroundManager":
        """注册持久化工作器"""
        return self.register_worker(TaskType.PERSISTENCE, worker)

    # ==================== 回调注册 ====================

    def on_complete(self, callback: Callable[[TaskResult], Awaitable[None]]) -> "BackgroundManager":
        """注册完成回调"""
        self._result_callbacks.append(callback)
        return self

    # ==================== 任务提交 ====================

    def submit(self, task: BackgroundTask) -> bool:
        """提交任务到队列"""
        try:
            self._task_queue.put_nowait(task)

            async def _update_stats():
                async with self._stats_lock:
                    self._stats["submitted"] += 1

            asyncio.create_task(_update_stats())
            logger.debug(f"提交任务: {task.name} (优先级: {task.priority.name})")
            return True
        except asyncio.QueueFull:

            async def _update_dropped():
                async with self._stats_lock:
                    self._stats["dropped"] += 1

            asyncio.create_task(_update_dropped())
            logger.warning(f"任务队列已满 ({self.max_queue_size})，丢弃任务: {task.name}")
            return False

    def submit_memory_task(
        self,
        user_input: str,
        assistant_response: str,
        priority: TaskPriority = TaskPriority.LOW,
        timeout: float = 5.0,
    ) -> bool:
        """提交记忆任务"""
        task = BackgroundTask(
            type=TaskType.MEMORY,
            priority=priority,
            name=f"memory_{len(user_input)}",
            data=MemoryTaskData(
                user_input=user_input,
                assistant_response=assistant_response,
            ),
            timeout=timeout,
        )
        return self.submit(task)

    def submit_persistence_task(
        self,
        operation: str,
        data: dict,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float = 10.0,
    ) -> bool:
        """提交持久化任务"""
        task = BackgroundTask(
            type=TaskType.PERSISTENCE,
            priority=priority,
            name=f"persist_{operation}",
            data=PersistenceTaskData(
                operation=operation,
                data=data,
            ),
            timeout=timeout,
        )
        return self.submit(task)

    # ==================== 生命周期 ====================

    async def start(self) -> None:
        """启动管理器"""
        if self._running:
            return

        self._running = True

        # 启动工作协程
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self._worker_tasks.append(task)

        logger.info(f"后台管理器已启动 ({self.max_workers} 个工作器)")

    async def stop(self, wait: bool = True) -> None:
        """停止管理器"""
        if not self._running:
            return

        self._running = False

        if wait:
            # 等待队列清空
            timeout = 5.0
            try:
                await asyncio.wait_for(self._task_queue.join(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"等待队列清空超时，剩余 {self._task_queue.qsize()} 个任务将被丢弃")

        # 取消所有工作器
        for task in self._worker_tasks:
            task.cancel()

        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

        async with self._stats_lock:
            stats = self._stats.copy()

        logger.info(
            f"后台管理器已停止 "
            f"(提交: {stats['submitted']}, "
            f"完成: {stats['completed']}, "
            f"失败: {stats['failed']}, "
            f"超时: {stats['timeout']}, "
            f"丢弃: {stats['dropped']})"
        )

    # ==================== 工作循环 ====================

    async def _worker_loop(self, worker_id: int) -> None:
        """工作器循环 - 使用上下文管理器自动处理 task_done"""
        logger.debug(f"工作器 {worker_id} 已启动")

        while self._running:
            try:
                # 使用上下文管理器，自动处理 task_done
                async with TaskContext(self._task_queue) as task:
                    # 获取对应的工作器
                    worker = self._workers.get(task.type)
                    if worker is None:
                        logger.warning(f"未找到工作器: {task.type.name}")
                        continue  # task_done 会自动调用

                    # 执行任务
                    try:
                        result = await worker.process(task)
                        await self._update_stats(result)

                        # 触发回调
                        for callback in self._result_callbacks:
                            try:
                                await callback(result)
                            except Exception as e:
                                logger.warning(f"回调执行失败: {e}")

                    except asyncio.CancelledError:
                        logger.debug(f"工作器 {worker_id} 任务被取消")
                        raise  # 重新抛出，让外层处理
                    except Exception as e:
                        logger.error(f"任务执行异常: {e}")
                        # task_done 会在上下文管理器退出时自动调用

            except asyncio.CancelledError:
                logger.debug(f"工作器 {worker_id} 已取消")
                break
            except asyncio.TimeoutError:
                # 这个异常不会发生，因为 TaskContext 没有超时
                continue
            except Exception as e:
                logger.error(f"工作器 {worker_id} 发生未预期异常: {e}")
                continue

        logger.debug(f"工作器 {worker_id} 已停止")

    async def _update_stats(self, result: TaskResult) -> None:
        """更新统计信息"""
        async with self._stats_lock:
            self._stats["completed"] += 1
            if not result.success:
                self._stats["failed"] += 1
                if result.error == "timeout":
                    self._stats["timeout"] += 1

    # ==================== 状态查询 ====================

    @property
    def queue_size(self) -> int:
        """当前队列大小"""
        return self._task_queue.qsize()

    @property
    def stats(self) -> dict:
        """获取统计信息"""
        return self._stats.copy()

    def clear_queues(self) -> None:
        """清空所有队列"""
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
                self._task_queue.task_done()
            except asyncio.QueueEmpty:
                break
