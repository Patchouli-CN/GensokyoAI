"""配置管理"""

# GensokyoAI\core\config.py

import os
from pathlib import Path
from typing import Any
from msgspec import Struct, field
from enum import Enum
import yaml

from ..utils.logging import setup_logging


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ModelConfig(Struct):
    """模型配置"""

    name: str = "qwen3.5:9b"
    base_url: str | None = None
    stream: bool = True
    think: bool = False
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    timeout: int = 60
    use_proxy: bool = False  # 🆕 是否使用代理

class TopicGenerationConfig(Struct):
    """话题生成配置"""
    name_max_length: int = 10
    summary_max_length: int = 100
    examples: list[dict] = field(default_factory=list)

class MemoryConfig(Struct):
    """记忆配置"""

    working_max_turns: int = 20
    episodic_threshold: int = 50
    episodic_summary_model: str = "qwen3.5:9b"
    episodic_keep_recent: int = 10
    semantic_enabled: bool = True
    semantic_top_k: int = 5
    semantic_similarity_threshold: float = 0.7
    auto_memory_enabled: bool = True
    auto_memory_model: str = "qwen3.5:9b"
    
    topic_generation: TopicGenerationConfig = field(default_factory=TopicGenerationConfig)


class ToolConfig(Struct):
    """工具配置"""

    enabled: bool = True
    builtin_tools: list[str] = field(default_factory=lambda: ["time", "moon", "memory", "system"])
    custom_tools_path: Path | None = None


class SessionConfig(Struct):
    """会话配置"""

    auto_save: bool = True
    save_path: Path = field(default_factory=lambda: Path("./sessions"))
    max_sessions: int = 100

    def __post_init__(self):
        # 强制转换为 Path 对象
        if not isinstance(self.save_path, Path):
            object.__setattr__(self, "save_path", Path(self.save_path))


class CharacterConfig(Struct):
    """角色配置"""

    name: str
    system_prompt: str
    greeting: str = ""
    example_dialogue: list[dict[str, str]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AppConfig(Struct):
    """应用配置"""

    # 日志配置
    log_level: LogLevel = LogLevel.INFO
    log_console: bool = True
    log_file: Path | None = None

    # 子配置
    model: ModelConfig = field(default_factory=ModelConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tool: ToolConfig = field(default_factory=ToolConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    # 角色
    character: CharacterConfig | None = None
    character_file: Path | None = None

    def __post_init__(self):
        # 确保保存路径存在
        if self.session.save_path:
            self.session.save_path.mkdir(parents=True, exist_ok=True)

        # 应用日志配置
        self._apply_logging_config()

    def _apply_logging_config(self) -> None:
        """应用日志配置"""
        setup_logging(
            log_level=self.log_level.value,
            log_console=self.log_console,
            log_file=self.log_file,
        )


class ConfigLoader:
    """配置加载器"""

    def __init__(self):
        self._config: AppConfig | None = None

    def load(self, config_file: Path | None = None) -> AppConfig:
        """加载配置"""
        config = AppConfig()

        # 1. 加载默认配置
        default_file = Path(__file__).parent.parent.parent / "config" / "default.yaml"
        if default_file.exists():
            config = self._load_yaml(default_file)

        # 2. 加载用户配置文件
        if config_file and config_file.exists():
            user_config = self._load_yaml(config_file)
            config = self._merge(config, user_config)

        # 3. 环境变量覆盖
        config = self._apply_env(config)

        # 4. 重新应用日志配置（确保使用最终配置）
        config._apply_logging_config()

        self._config = config
        return config

    def _load_yaml(self, path: Path) -> AppConfig:
        """从 YAML 加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return self._dict_to_config(data)

    def _dict_to_config(self, data: dict[str, Any]) -> AppConfig:
        """字典转配置对象"""
        config = AppConfig()

        if "log_level" in data:
            config.log_level = LogLevel(data["log_level"])
        if "log_console" in data:
            config.log_console = data["log_console"]
        if "log_file" in data and data["log_file"]:
            config.log_file = Path(data["log_file"])

        if "model" in data:
            config.model = ModelConfig(**data["model"])
        if "memory" in data:
            config.memory = MemoryConfig(**data["memory"])
        if "tool" in data:
            config.tool = ToolConfig(**data["tool"])
        if "session" in data:
            config.session = SessionConfig(**data["session"])

        return config

    def _merge(self, base: AppConfig, override: AppConfig) -> AppConfig:
        """合并配置 - override 优先"""
        result = AppConfig()

        # 日志配置 - override 优先
        result.log_level = (
            override.log_level if override.log_level != LogLevel.INFO else base.log_level
        )
        result.log_console = override.log_console
        result.log_file = override.log_file or base.log_file

        # 其他配置 - override 优先
        result.model = self._merge_model(base.model, override.model)
        result.memory = self._merge_memory(base.memory, override.memory)
        result.tool = self._merge_tool(base.tool, override.tool)
        result.session = self._merge_session(base.session, override.session)
        result.character = override.character or base.character
        result.character_file = override.character_file or base.character_file

        return result

    def _merge_model(self, base: ModelConfig, override: ModelConfig) -> ModelConfig:
        """合并模型配置 - override 优先"""
        return ModelConfig(
            name=override.name if override.name != "qwen3.5:9b" else base.name,
            base_url=override.base_url or base.base_url,
            stream=override.stream,
            think=override.think,
            temperature=override.temperature if override.temperature != 0.7 else base.temperature,
            top_p=override.top_p if override.top_p != 0.9 else base.top_p,
            max_tokens=override.max_tokens if override.max_tokens != 2048 else base.max_tokens,
            timeout=override.timeout if override.timeout != 60 else base.timeout,
        )

    def _merge_memory(self, base: MemoryConfig, override: MemoryConfig) -> MemoryConfig:
        """合并记忆配置 - override 优先"""
        return MemoryConfig(
            working_max_turns=override.working_max_turns
            if override.working_max_turns != 20
            else base.working_max_turns,
            episodic_threshold=override.episodic_threshold
            if override.episodic_threshold != 50
            else base.episodic_threshold,
            episodic_summary_model=override.episodic_summary_model
            if override.episodic_summary_model != "qwen3.5:9b"
            else base.episodic_summary_model,
            episodic_keep_recent=override.episodic_keep_recent
            if override.episodic_keep_recent != 10
            else base.episodic_keep_recent,
            semantic_enabled=override.semantic_enabled,
            semantic_top_k=override.semantic_top_k
            if override.semantic_top_k != 5
            else base.semantic_top_k,
            semantic_similarity_threshold=override.semantic_similarity_threshold
            if override.semantic_similarity_threshold != 0.7
            else base.semantic_similarity_threshold,
            auto_memory_enabled=override.auto_memory_enabled,
            auto_memory_model=override.auto_memory_model
            if override.auto_memory_model != "qwen3.5:9b"
            else base.auto_memory_model,
        )

    def _merge_tool(self, base: ToolConfig, override: ToolConfig) -> ToolConfig:
        """合并工具配置 - 修复覆盖逻辑"""
        return ToolConfig(
            enabled=override.enabled if override.enabled != base.enabled else base.enabled,
            builtin_tools=override.builtin_tools
            if override.builtin_tools != base.builtin_tools
            else base.builtin_tools,
            custom_tools_path=override.custom_tools_path or base.custom_tools_path,
        )

    def _merge_session(self, base: SessionConfig, override: SessionConfig) -> SessionConfig:
        """合并会话配置 - 修复覆盖逻辑"""
        default_path = Path("./sessions")
        return SessionConfig(
            auto_save=override.auto_save
            if override.auto_save != base.auto_save
            else base.auto_save,
            save_path=override.save_path if override.save_path != default_path else base.save_path,
            max_sessions=override.max_sessions
            if override.max_sessions != 100
            else base.max_sessions,
        )

    def _apply_env(self, config: AppConfig) -> AppConfig:
        """应用环境变量"""
        if os.getenv("GENSOKYOAI_MODEL"):
            config.model.name = os.getenv("GENSOKYOAI_MODEL")  # type: ignore
        if os.getenv("GENSOKYOAI_LOG_LEVEL"):
            config.log_level = LogLevel(os.getenv("GENSOKYOAI_LOG_LEVEL"))
        if os.getenv("GENSOKYOAI_LOG_CONSOLE"):
            config.log_console = os.getenv("GENSOKYOAI_LOG_CONSOLE").lower() == "true"  # type: ignore
        if os.getenv("GENSOKYOAI_MEMORY_WORKING_TURNS"):
            config.memory.working_max_turns = int(
                os.getenv("GENSOKYOAI_MEMORY_WORKING_TURNS")  # type: ignore
            )
        return config

    def load_character(self, path: Path) -> CharacterConfig:
        """加载角色配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return CharacterConfig(
            name=data["name"],
            system_prompt=data["system_prompt"],
            greeting=data.get("greeting", ""),
            example_dialogue=data.get("example_dialogue"),
            metadata=data.get("metadata", {}),
        )
