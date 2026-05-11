"""配置加载器与角色配置加载。"""

from pathlib import Path
from typing import Any

import yaml

from .config_schema import (
    AppConfig,
    CharacterConfig,
    EmbeddingConfig,
    LogLevel,
    MemoryConfig,
    ModelConfig,
    SessionConfig,
    ThinkEngineConfig,
    TopicGenerationConfig,
)
from .config_merge import ConfigMerger
from .config_env import apply_env_overrides


class ConfigLoader(ConfigMerger):
    """配置加载器"""

    def __init__(self):
        self._config: AppConfig | None = None
        super().__init__()

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
            config = self.merge(config, user_config)

        # 3. 环境变量覆盖
        config = apply_env_overrides(config)

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
        """字典转配置对象，并记录用户显式提供的字段。"""
        config = AppConfig()
        self._provided_fields[id(config)] = set(data.keys())

        if "log_level" in data:
            config.log_level = LogLevel(data["log_level"])
        if "log_console" in data:
            config.log_console = data["log_console"]
        if "log_file" in data and data["log_file"]:
            config.log_file = Path(data["log_file"])
        if "debug_silent_output" in data:
            config.debug_silent_output = bool(data["debug_silent_output"])
        if "event_trace_enabled" in data:
            config.event_trace_enabled = bool(data["event_trace_enabled"])

        if "model" in data:
            model_data = data["model"] or {}
            config.model = ModelConfig(**model_data)
            self._provided_fields[id(config.model)] = set(model_data.keys())
        if "embedding" in data:
            embedding_data = data["embedding"] or {}
            config.embedding = EmbeddingConfig(**embedding_data)
            self._provided_fields[id(config.embedding)] = set(embedding_data.keys())
        if "memory" in data:
            memory_data = data["memory"] or {}
            topic_generation_data = memory_data.get("topic_generation")
            memory_obj_data = dict(memory_data)
            memory_obj_data.pop("topic_generation", None)
            config.memory = MemoryConfig(**memory_obj_data)
            if isinstance(topic_generation_data, dict):
                config.memory.topic_generation = TopicGenerationConfig(**topic_generation_data)
            self._provided_fields[id(config.memory)] = set(memory_data.keys())
            if isinstance(topic_generation_data, dict):
                self._provided_fields[id(config.memory.topic_generation)] = set(topic_generation_data.keys())
        if "tool" in data:
            tool_data = data["tool"] or {}
            config.tool = self._dict_to_tool_config(tool_data)
            self._provided_fields[id(config.tool)] = set(tool_data.keys())
            if isinstance(tool_data.get("web_search"), dict):
                self._provided_fields[id(config.tool.web_search)] = set(tool_data["web_search"].keys())
                if isinstance(tool_data["web_search"].get("api"), dict):
                    self._provided_fields[id(config.tool.web_search.api)] = set(tool_data["web_search"]["api"].keys())
        if "session" in data:
            session_data = data["session"] or {}
            config.session = SessionConfig(**session_data)
            self._provided_fields[id(config.session)] = set(session_data.keys())

        if "think_engine" in data:
            think_engine_data = data["think_engine"] or {}
            config.think_engine = ThinkEngineConfig(**think_engine_data)
            self._provided_fields[id(config.think_engine)] = set(think_engine_data.keys())

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
