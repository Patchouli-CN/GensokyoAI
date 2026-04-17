"""会话持久化"""

# GensokyoAI\session\persistence.py

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
        # 添加 session_id -> character_id 的映射缓存
        self._session_index: dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        """构建会话索引"""
        self._session_index.clear()
        if not self.base_path.exists():
            return

        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                char_name = char_dir.name
                for session_file in char_dir.glob("*.json"):
                    session_id = session_file.stem
                    self._session_index[session_id] = char_name
        logger.debug(f"构建会话索引完成，共 {len(self._session_index)} 个会话")

    def _add_to_index(self, character_id: str, session_id: str) -> None:
        """添加到索引"""
        self._session_index[session_id] = character_id

    def _remove_from_index(self, session_id: str) -> None:
        """从索引移除"""
        self._session_index.pop(session_id, None)

    def _get_session_path(self, character_id: str, session_id: str) -> Path:
        """获取会话文件路径"""
        char_path = self.base_path / character_id
        char_path.mkdir(parents=True, exist_ok=True)
        return char_path / f"{session_id}.json"

    def save_session(self, session: SessionContext) -> None:
        """保存会话（同步，用于兼容）"""
        path = self._get_session_path(session.character_id, session.session_id)
        self._add_to_index(session.character_id, session.session_id)

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
            self._add_to_index(session.character_id, session.session_id)

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
        """保存消息（同步）- 优化版"""
        # 使用索引快速定位
        char_id = self._session_index.get(session_id)
        if char_id:
            session_file = self.base_path / char_id / f"{session_id}.json"
            if session_file.exists():
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["messages"] = messages
                if "session" in data:
                    data["session"]["total_turns"] = len(messages) // 2
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug(f"消息已保存: {session_id}, {len(messages)} 条")
                return

        # 降级：遍历查找（同时更新索引）
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    self._add_to_index(char_dir.name, session_id)
                    with open(session_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["messages"] = messages
                    if "session" in data:
                        data["session"]["total_turns"] = len(messages) // 2
                    with open(session_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.debug(f"消息已保存: {session_id}, {len(messages)} 条")
                    return

        logger.warning(f"未找到会话文件: {session_id}")

    async def save_messages_async(self, session_id: str, messages: list[dict]) -> None:
        """保存消息（异步）- 优化版"""
        async with self._lock:
            # 使用索引快速定位
            char_id = self._session_index.get(session_id)
            if char_id:
                session_file = self.base_path / char_id / f"{session_id}.json"
                if session_file.exists():
                    async with ayafileio.open(session_file, "r", encoding="utf-8") as f:
                        content = await f.read()
                        data = json.loads(content)
                    data["messages"] = messages
                    if "session" in data:
                        data["session"]["total_turns"] = len(messages) // 2
                    async with ayafileio.open(session_file, "w", encoding="utf-8") as f:
                        await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                    logger.debug(f"消息已异步保存: {session_id}, {len(messages)} 条")
                    return

            # 降级：遍历查找（同时更新索引）
            for char_dir in self.base_path.iterdir():
                if char_dir.is_dir():
                    session_file = char_dir / f"{session_id}.json"
                    if session_file.exists():
                        self._add_to_index(char_dir.name, session_id)
                        async with ayafileio.open(session_file, "r", encoding="utf-8") as f:
                            content = await f.read()
                            data = json.loads(content)
                        data["messages"] = messages
                        if "session" in data:
                            data["session"]["total_turns"] = len(messages) // 2
                        async with ayafileio.open(session_file, "w", encoding="utf-8") as f:
                            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                        logger.debug(f"消息已异步保存: {session_id}, {len(messages)} 条")
                        return

            logger.warning(f"未找到会话文件: {session_id}")

    def load_messages(self, session_id: str) -> list[dict]:
        """加载消息（同步）- 优化版"""
        # 使用索引快速定位
        char_id = self._session_index.get(session_id)
        if char_id:
            session_file = self.base_path / char_id / f"{session_id}.json"
            if session_file.exists():
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                messages = data.get("messages", [])
                logger.debug(f"加载消息: {session_id}, {len(messages)} 条")
                return messages

        # 降级：遍历查找
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    self._add_to_index(char_dir.name, session_id)
                    with open(session_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    messages = data.get("messages", [])
                    logger.debug(f"加载消息: {session_id}, {len(messages)} 条")
                    return messages
        return []

    async def load_messages_async(self, session_id: str) -> list[dict]:
        """加载消息（异步 - 使用 ayafileio）- 优化版"""
        # 使用索引快速定位
        char_id = self._session_index.get(session_id)
        if char_id:
            session_file = self.base_path / char_id / f"{session_id}.json"
            if session_file.exists():
                async with ayafileio.open(session_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                messages = data.get("messages", [])
                logger.debug(f"异步加载消息: {session_id}, {len(messages)} 条")
                return messages

        # 降级：遍历查找
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    self._add_to_index(char_dir.name, session_id)
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

    async def load_session_async(self, character_id: str, session_id: str) -> SessionContext | None:
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
        """删除会话（同步）- 优化版"""
        self._remove_from_index(session_id)

        # 使用索引快速定位
        char_id = self._session_index.get(session_id)
        if char_id:
            session_file = self.base_path / char_id / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
                logger.debug(f"会话已删除: {session_id}")
                return True

        # 降级：遍历查找
        for char_dir in self.base_path.iterdir():
            if char_dir.is_dir():
                session_file = char_dir / f"{session_id}.json"
                if session_file.exists():
                    session_file.unlink()
                    logger.debug(f"会话已删除: {session_id}")
                    return True
        return False

    async def delete_session_async(self, session_id: str) -> bool:
        """删除会话（异步）- 优化版"""
        async with self._lock:
            self._remove_from_index(session_id)

            # 使用索引快速定位
            char_id = self._session_index.get(session_id)
            if char_id:
                session_file = self.base_path / char_id / f"{session_id}.json"
                if session_file.exists():
                    await asyncio.to_thread(session_file.unlink)
                    logger.debug(f"会话已异步删除: {session_id}")
                    return True

            # 降级：遍历查找
            for char_dir in self.base_path.iterdir():
                if char_dir.is_dir():
                    session_file = char_dir / f"{session_id}.json"
                    if session_file.exists():
                        await asyncio.to_thread(session_file.unlink)
                        logger.debug(f"会话已异步删除: {session_id}")
                        return True
        return False

    def rebuild_index(self) -> None:
        """重建索引（用于手动刷新）"""
        self._build_index()
        logger.info("会话索引已重建")
