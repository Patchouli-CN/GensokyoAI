"""配置加载器与角色配置加载。"""

from pathlib import Path
from typing import Any

import yaml

from .config_env import apply_env_overrides
from .config_merge import ConfigMerger
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
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return self._dict_to_config(data)

    def _dict_to_config(self, data: dict[str, Any]) -> AppConfig:
        """字典转配置对象，并记录用户显式提供的字段。"""
        config = AppConfig()
        self._provided_fields[id(config)] = set(data.keys())

        if "log_level" in data:
            config.log_level = LogLevel(data["log_level"])
        unknown_top_level = set(data) - self._known_top_level_fields()
        if unknown_top_level:
            raise ValueError(f"Unknown config fields: {', '.join(sorted(unknown_top_level))}")

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
            self._validate_section_fields("model", model_data, self._struct_field_names(ModelConfig))
            self._validate_numeric_range("model.temperature", model_data.get("temperature"), minimum=0, maximum=2)
            self._validate_numeric_range("model.top_p", model_data.get("top_p"), minimum=0, maximum=1)
            self._validate_numeric_range("model.max_tokens", model_data.get("max_tokens"), minimum=1)
            self._validate_numeric_range("model.timeout", model_data.get("timeout"), minimum=0.001)
            config.model = ModelConfig(**model_data)
            self._provided_fields[id(config.model)] = set(model_data.keys())
        if "embedding" in data:
            embedding_data = data["embedding"] or {}
            self._validate_section_fields("embedding", embedding_data, self._struct_field_names(EmbeddingConfig))
            self._validate_numeric_range("embedding.timeout", embedding_data.get("timeout"), minimum=0.001)
            self._validate_numeric_range("embedding.dimensions", embedding_data.get("dimensions"), minimum=1)
            config.embedding = EmbeddingConfig(**embedding_data)
            self._provided_fields[id(config.embedding)] = set(embedding_data.keys())
        if "memory" in data:
            memory_data = data["memory"] or {}
            self._validate_section_fields("memory", memory_data, self._struct_field_names(MemoryConfig))
            topic_generation_data = memory_data.get("topic_generation")
            memory_obj_data = dict(memory_data)
            memory_obj_data.pop("topic_generation", None)
            config.memory = MemoryConfig(**memory_obj_data)
            if isinstance(topic_generation_data, dict):
                self._validate_section_fields(
                    "memory.topic_generation",
                    topic_generation_data,
                    self._struct_field_names(TopicGenerationConfig),
                )
                config.memory.topic_generation = TopicGenerationConfig(**topic_generation_data)
            self._provided_fields[id(config.memory)] = set(memory_data.keys())
            if isinstance(topic_generation_data, dict):
                self._provided_fields[id(config.memory.topic_generation)] = set(topic_generation_data.keys())
        if "tool" in data:
            tool_data = data["tool"] or {}
            self._validate_tool_config_data(tool_data)
            config.tool = self._dict_to_tool_config(tool_data)
            self._provided_fields[id(config.tool)] = set(tool_data.keys())
            if isinstance(tool_data.get("web_search"), dict):
                self._provided_fields[id(config.tool.web_search)] = set(tool_data["web_search"].keys())
                if isinstance(tool_data["web_search"].get("api"), dict):
                    self._provided_fields[id(config.tool.web_search.api)] = set(tool_data["web_search"]["api"].keys())
        if "session" in data:
            session_data = data["session"] or {}
            self._validate_section_fields("session", session_data, self._struct_field_names(SessionConfig))
            self._validate_numeric_range("session.max_sessions", session_data.get("max_sessions"), minimum=1)
            config.session = SessionConfig(**session_data)
            self._provided_fields[id(config.session)] = set(session_data.keys())

        if "think_engine" in data:
            think_engine_data = data["think_engine"] or {}
            self._validate_section_fields("think_engine", think_engine_data, self._struct_field_names(ThinkEngineConfig))
            self._validate_numeric_range("think_engine.think_interval_minutes", think_engine_data.get("think_interval_minutes"), minimum=1)
            config.think_engine = ThinkEngineConfig(**think_engine_data)
            self._provided_fields[id(config.think_engine)] = set(think_engine_data.keys())

        return config

    @staticmethod
    def _known_top_level_fields() -> set[str]:
        return {
            "log_level",
            "log_console",
            "log_file",
            "debug_silent_output",
            "event_trace_enabled",
            "model",
            "embedding",
            "memory",
            "tool",
            "session",
            "think_engine",
            "character",
            "character_file",
        }

    @staticmethod
    def _struct_field_names(struct_type: type) -> set[str]:
        return set(getattr(struct_type, "__struct_fields__", ()))

    @staticmethod
    def _validate_section_fields(section: str, data: Any, allowed: set[str]) -> None:
        if not isinstance(data, dict):
            raise ValueError(f"Config section '{section}' must be an object")
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown config fields in {section}: {', '.join(sorted(unknown))}")

    @staticmethod
    def _validate_numeric_range(
        field_name: str,
        value: Any,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> None:
        if value is None:
            return
        if not isinstance(value, (int, float)):
            raise ValueError(f"Config field '{field_name}' must be numeric")
        if minimum is not None and value < minimum:
            raise ValueError(f"Config field '{field_name}' must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"Config field '{field_name}' must be <= {maximum}")

    def _validate_tool_config_data(self, data: Any) -> None:
        self._validate_section_fields("tool", data, {"enabled", "builtin_tools", "custom_tools_path", "web_search"})
        web_search = data.get("web_search")
        if isinstance(web_search, dict):
            self._validate_section_fields(
                "tool.web_search",
                web_search,
                {
                    "enabled",
                    "provider",
                    "max_results",
                    "timeout",
                    "cache_ttl_seconds",
                    "trigger_strategy",
                    "freshness_keywords",
                    "prefer_for_characters",
                    "prefer_for_scenarios",
                    "user_agent",
                    "region",
                    "safe_search",
                    "snippet_max_length",
                    "api",
                },
            )
            self._validate_numeric_range("tool.web_search.max_results", web_search.get("max_results"), minimum=1)
            self._validate_numeric_range("tool.web_search.timeout", web_search.get("timeout"), minimum=0.001)
            api = web_search.get("api")
            if isinstance(api, dict):
                self._validate_section_fields(
                    "tool.web_search.api",
                    api,
                    {
                        "endpoint",
                        "method",
                        "api_key",
                        "api_key_header",
                        "api_key_prefix",
                        "headers",
                        "request_template",
                        "query_params",
                        "results_path",
                        "title_path",
                        "url_path",
                        "snippet_path",
                        "published_at_path",
                    },
                )

    def load_character(self, path: Path) -> CharacterConfig:
        """加载角色配置"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return CharacterConfig(
            name=data["name"],
            system_prompt=data["system_prompt"],
            greeting=data.get("greeting", ""),
            example_dialogue=data.get("example_dialogue"),
            metadata=data.get("metadata", {}),
        )
