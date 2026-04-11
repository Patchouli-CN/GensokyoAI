"""会话管理器"""

from .context import SessionContext
from .persistence import SessionPersistence
from ..memory.working import WorkingMemoryManager
from ..core.config import SessionConfig
from ..utils.logging import logger


class SessionManager:
    """会话管理器"""

    def __init__(self, config: SessionConfig, character_id: str):
        self.config = config
        self.character_id = character_id
        self._persistence = SessionPersistence(config.save_path)
        self._sessions: dict[str, SessionContext] = {}
        self._current_session_id: str | None = None
        self._working_memories: dict[str, WorkingMemoryManager] = {}

        self._load_sessions()

    def _load_sessions(self) -> None:
        """加载历史会话"""
        sessions = self._persistence.list_sessions(self.character_id)
        for sess in sessions:
            self._sessions[sess.session_id] = sess
            # 加载工作记忆
            messages = self._persistence.load_messages(sess.session_id)
            if messages:
                wm = WorkingMemoryManager(max_turns=self.config.max_sessions)
                for msg in messages:
                    wm.add_message(msg["role"], msg["content"])
                self._working_memories[sess.session_id] = wm
        logger.info(f"加载了 {len(self._sessions)} 个历史会话")

    def create_session(self) -> SessionContext:
        """创建新会话"""
        session = SessionContext(character_id=self.character_id)
        self._sessions[session.session_id] = session
        self._working_memories[session.session_id] = WorkingMemoryManager(
            max_turns=self.config.max_sessions
        )
        self._current_session_id = session.session_id
        self._persistence.save_session(session)
        # 保存空消息列表
        self._persistence.save_messages(session.session_id, [])
        logger.info(f"创建会话: {session.session_id}")
        return session

    async def create_session_async(self) -> SessionContext:
        """创建新会话（异步）"""
        session = SessionContext(character_id=self.character_id)
        self._sessions[session.session_id] = session
        self._working_memories[session.session_id] = WorkingMemoryManager(
            max_turns=self.config.max_sessions
        )
        self._current_session_id = session.session_id

        # 异步保存
        await self._persistence.save_session_async(session)
        await self._persistence.save_messages_async(session.session_id, [])

        logger.info(f"异步创建会话: {session.session_id}")
        return session

    def get_session(self, session_id: str) -> SessionContext | None:
        """获取会话"""
        return self._sessions.get(session_id)

    def get_current_session(self) -> SessionContext | None:
        """获取当前会话"""
        if self._current_session_id:
            return self._sessions.get(self._current_session_id)
        return None

    def set_current_session(self, session_id: str) -> bool:
        """设置当前会话"""
        if session_id in self._sessions:
            self._current_session_id = session_id
            return True
        return False

    def list_sessions(self) -> list[SessionContext]:
        """列出所有会话"""
        return list(self._sessions.values())

    def get_working_memory(self, session_id: str | None = None) -> WorkingMemoryManager:
        """获取工作记忆"""
        sid = session_id or self._current_session_id
        if not sid:
            raise ValueError("No active session")

        if sid not in self._working_memories:
            # 尝试从持久化加载
            messages = self._persistence.load_messages(sid)
            wm = WorkingMemoryManager(max_turns=self.config.max_sessions)
            for msg in messages:
                wm.add_message(msg["role"], msg["content"])
            self._working_memories[sid] = wm

        return self._working_memories[sid]

    def save_working_memory(self, session_id: str | None = None) -> None:
        """保存工作记忆到持久化"""
        sid = session_id or self._current_session_id
        if not sid:
            return

        wm = self._working_memories.get(sid)
        if wm:
            messages = wm.get_context()
            self._persistence.save_messages(sid, messages)
            logger.debug(f"保存工作记忆: {sid}, {len(messages)} 条消息")

            # 同时更新会话的 total_turns
            session = self._sessions.get(sid)
            if session:
                session.total_turns = len(messages) // 2
                # 立即保存会话信息
                self._persistence.save_session(session)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            if session_id in self._working_memories:
                del self._working_memories[session_id]
            self._persistence.delete_session(session_id)
            if self._current_session_id == session_id:
                self._current_session_id = None
            return True
        return False

    def save_current(self) -> None:
        """保存当前会话"""
        if self._current_session_id:
            # 保存工作记忆（会自动更新 total_turns 和保存会话）
            self.save_working_memory()
        logger.debug(f"会话已保存: {self._current_session_id}")
