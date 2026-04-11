"""会话持久化"""

import json
import asyncio
from pathlib import Path

import ayafileio

from .context import SessionContext
from ..utils.logging import logger


class SessionPersistence:
    """会话持久化 - 基于 ayafileio 的真异步 I/O"""

    def __init__(self, base_path: Path):
        self.base_path = base_path

        logger.debug(
            f"value the base_path is: {self.base_path}, type: {type(self.base_path).__name__}"
        )
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _get_session_path(self, character_id: str, session_id: str) -> Path:
        """获取会话文件路径"""
        char_path = self.base_path / character_id
        char_path.mkdir(parents=True, exist_ok=True)
        return char_path / f"{session_id}.json"

    def save_session(self, session: SessionContext) -> None:
        """保存会话（同步，用于兼容）"""
        path = self._get_session_path(session.character_id, session.session_id)

        existing_messages = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_messages = data.get("messages", [])

        data = {"session": session.to_dict(), "messages": existing_messages}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"会话已保存: {path}")

    async def save_session_async(self, session: SessionContext) -> None:
        """保存会话（异步 - 使用 ayafileio）"""
        async with self._lock:
            path = self._get_session_path(session.character_id, session.session_id)

            existing_messages = []
            if path.exists():
                async with ayafileio.open(path, "r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                    existing_messages = data.get("messages", [])

            data = {"session": session.to_dict(), "messages": existing_messages}
            async with ayafileio.open(path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        logger.debug(f"会话已异步保存: {path}")

    def save_messages(self, session_id: str, messages: list[dict]) -> None:
        """保存消息（同步）"""
        saved = False
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    with open(session_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["messages"] = messages
                    if "session" in data:
                        data["session"]["total_turns"] = len(messages) // 2
                    with open(session_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    saved = True
                    logger.debug(f"消息已保存: {session_id}, {len(messages)} 条")
                    break

        if not saved:
            logger.warning(f"未找到会话文件: {session_id}")

    async def save_messages_async(self, session_id: str, messages: list[dict]) -> None:
        """保存消息（异步）"""
        async with self._lock:
            # 方案1：直接从 session_id 反查 character_id
            # 需要遍历所有角色的目录
            saved = False

            # 先尝试从已有的会话中查找
            for char_dir in self.base_path.iterdir():
                if char_dir.is_dir():
                    session_file = char_dir / f"{session_id}.json"
                    if session_file.exists():
                        file_path = session_file.resolve()

                        def _save():
                            with open(file_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            data["messages"] = messages
                            if "session" in data:
                                data["session"]["total_turns"] = len(messages) // 2
                            with open(file_path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)

                        await asyncio.to_thread(_save)
                        saved = True
                        logger.debug(
                            f"消息已异步保存: {session_id}, {len(messages)} 条"
                        )
                        break

            if not saved:
                # 如果找不到，说明可能是新会话，需要从 session 对象中获取 character_id
                # 但这里我们没有 session 对象...
                logger.warning(f"未找到会话文件: {session_id}，将使用同步保存创建")
                # 降级到同步保存，它会尝试创建
                self.save_messages(session_id, messages)

    def load_messages(self, session_id: str) -> list[dict]:
        """加载消息（同步）"""
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    with open(session_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    messages = data.get("messages", [])
                    logger.debug(f"加载消息: {session_id}, {len(messages)} 条")
                    return messages
        return []

    async def load_messages_async(self, session_id: str) -> list[dict]:
        """加载消息（异步 - 使用 ayafileio）"""
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    async with ayafileio.open(session_file, "r", encoding="utf-8") as f:
                        content = await f.read()
                        data = json.loads(content)
                    messages = data.get("messages", [])
                    logger.debug(f"异步加载消息: {session_id}, {len(messages)} 条")
                    return messages
        return []

    def load_session(self, character_id: str, session_id: str) -> SessionContext | None:
        """加载会话（同步）"""
        path = self._get_session_path(character_id, session_id)
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return SessionContext.from_dict(data["session"])

    async def load_session_async(
        self, character_id: str, session_id: str
    ) -> SessionContext | None:
        """加载会话（异步 - 使用 ayafileio）"""
        path = self._get_session_path(character_id, session_id)
        if not path.exists():
            return None

        async with ayafileio.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)

        return SessionContext.from_dict(data["session"])

    def list_sessions(self, character_id: str) -> list[SessionContext]:
        """列出所有会话（同步）"""
        sessions = []
        char_path = self.base_path / character_id
        if char_path.exists():
            for file in char_path.glob("*.json"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    sessions.append(SessionContext.from_dict(data["session"]))
                except Exception as e:
                    logger.warning(f"加载会话失败 {file}: {e}")
        return sessions

    async def list_sessions_async(self, character_id: str) -> list[SessionContext]:
        """列出所有会话（异步 - 使用 ayafileio）"""
        sessions = []
        char_path = self.base_path / character_id
        if char_path.exists():
            for file in char_path.glob("*.json"):
                try:
                    async with ayafileio.open(file, "r", encoding="utf-8") as f:
                        content = await f.read()
                        data = json.loads(content)
                    sessions.append(SessionContext.from_dict(data["session"]))
                except Exception as e:
                    logger.warning(f"加载会话失败 {file}: {e}")
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """删除会话（同步）"""
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    session_file.unlink()
                    logger.debug(f"会话已删除: {session_id}")
                    return True
        return False

    async def delete_session_async(self, session_id: str) -> bool:
        """删除会话（异步）"""
        async with self._lock:
            for char_dir in self.base_path.iterdir():
                if char_dir.is_dir():
                    session_file = char_dir / f"{session_id}.json"
                    if session_file.exists():
                        await asyncio.to_thread(session_file.unlink)
                        logger.debug(f"会话已异步删除: {session_id}")
                        return True
        return False
