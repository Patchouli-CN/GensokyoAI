"""配置诊断与校验工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .config_schema import (
    EmbeddingConfig,
    LogLevel,
    MemoryConfig,
    ModelConfig,
    ResourceControlConfig,
    SessionConfig,
    ThinkEngineConfig,
    TopicGenerationConfig,
)

DiagnosticSeverity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class ConfigDiagnostic:
    """单条配置诊断。"""

    code: str
    path: str
    severity: DiagnosticSeverity
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "path": self.path,
            "severity": self.severity,
            "message": self.message,
        }
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


class ConfigValidationError(ValueError):
    """配置校验异常，携带结构化诊断列表。"""

    def __init__(self, diagnostics: list[ConfigDiagnostic]) -> None:
        self.diagnostics = diagnostics
        message = self._format_message(diagnostics)
        super().__init__(message)

    @staticmethod
    def _format_message(diagnostics: list[ConfigDiagnostic]) -> str:
        if not diagnostics:
            return "Config validation failed"
        first = diagnostics[0]
        suffix = f" Suggestion: {first.suggestion}" if first.suggestion else ""
        more = f" ({len(diagnostics)} diagnostics total)" if len(diagnostics) > 1 else ""
        return f"{first.path}: {first.message}.{suffix}{more}"

    def to_dict(self) -> dict[str, Any]:
        return {"diagnostics": [item.to_dict() for item in self.diagnostics]}


class ConfigValidator:
    """配置字典和 Runtime 覆盖参数校验器。"""

    MODEL_OVERRIDE_FIELDS = {
        "provider",
        "name",
        "base_url",
        "api_path",
        "api_key",
        "extra_headers",
        "model_capabilities_add",
        "model_capabilities_remove",
        "web_search_enabled",
        "web_search_strategy",
        "web_search_context_size",
        "web_search_user_location",
        "web_search_allow_fallback",
        "web_search_metadata",
        "stream",
        "think",
        "thinking_enabled",
        "reasoning_effort",
        "temperature",
        "top_p",
        "max_tokens",
        "timeout",
        "use_proxy",
        "retry_max_attempts",
        "retry_initial_delay",
        "retry_backoff_factor",
        "retry_status_codes",
    }
    EMBEDDING_OVERRIDE_FIELDS = {
        "provider",
        "name",
        "base_url",
        "api_key",
        "dimensions",
        "encoding_format",
        "timeout",
        "use_proxy",
    }
    PROVIDERS_REQUIRING_API_KEY = {
        "openai",
        "openrouter",
        "deepseek",
        "openai_responses",
        "claude",
        "gemini",
    }
    KNOWN_PROVIDERS = {*PROVIDERS_REQUIRING_API_KEY, "ollama"}
    PROVIDER_FIELD_MATRIX: dict[str, dict[str, set[str]]] = {
        "ollama": {
            "discouraged": {
                "api_key",
                "auth",
                "api_path",
                "extra_headers",
                "web_search_enabled",
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
                "reasoning_effort",
            },
            "supported_web_search": set(),
        },
        "openai": {
            "discouraged": {
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
            },
            "supported_web_search": set(),
        },
        "openrouter": {
            "discouraged": {
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
            },
            "supported_web_search": set(),
        },
        "deepseek": {
            "discouraged": {
                "api_path",
                "web_search_enabled",
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
            },
            "supported_web_search": set(),
        },
        "openai_responses": {
            "discouraged": set(),
            "supported_web_search": {
                "web_search_enabled",
                "web_search_strategy",
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
                "web_search_allow_fallback",
            },
        },
        "claude": {
            "discouraged": {
                "api_path",
                "web_search_enabled",
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
                "web_search_allow_fallback",
            },
            "supported_web_search": set(),
        },
        "gemini": {
            "discouraged": {
                "api_path",
                "extra_headers",
                "auth",
                "web_search_context_size",
                "web_search_user_location",
                "web_search_metadata",
            },
            "supported_web_search": {
                "web_search_enabled",
                "web_search_strategy",
                "web_search_allow_fallback",
            },
        },
    }

    def validate_config_dict(self, data: dict[str, Any]) -> list[ConfigDiagnostic]:
        diagnostics: list[ConfigDiagnostic] = []
        self._validate_top_level(data, diagnostics)
        if not isinstance(data, dict):
            return diagnostics

        if "log_level" in data:
            self._validate_enum(
                "log_level", data["log_level"], {item.value for item in LogLevel}, diagnostics
            )
        if "model" in data:
            self._validate_model_data(data.get("model") or {}, diagnostics)
        if "embedding" in data:
            self._validate_embedding_data(data.get("embedding") or {}, diagnostics)
        if "memory" in data:
            self._validate_memory_data(data.get("memory") or {}, diagnostics)
        if "tool" in data:
            self._validate_tool_data(data.get("tool") or {}, diagnostics)
        if "session" in data:
            self._validate_session_data(data.get("session") or {}, diagnostics)
        if "think_engine" in data:
            self._validate_think_engine_data(data.get("think_engine") or {}, diagnostics)
        if "resource_control" in data:
            self._validate_resource_control_data(data.get("resource_control") or {}, diagnostics)
        return diagnostics

    def validate_model_overrides(self, overrides: dict[str, Any]) -> list[ConfigDiagnostic]:
        # Runtime overrides historically ignored unknown keys. Keep that compatibility
        # while still validating every accepted override value before applying it.
        data = {
            key: value
            for key, value in overrides.items()
            if value != "" and key in self.MODEL_OVERRIDE_FIELDS
        }
        diagnostics: list[ConfigDiagnostic] = []
        self._validate_model_values("model", data, diagnostics)
        return diagnostics

    def validate_embedding_overrides(self, overrides: dict[str, Any]) -> list[ConfigDiagnostic]:
        # Runtime overrides historically ignored unknown keys. Keep that compatibility
        # while still validating every accepted override value before applying it.
        data = {
            key: value
            for key, value in overrides.items()
            if value != "" and key in self.EMBEDDING_OVERRIDE_FIELDS
        }
        diagnostics: list[ConfigDiagnostic] = []
        self._validate_embedding_values("embedding", data, diagnostics)
        return diagnostics

    @staticmethod
    def raise_for_errors(diagnostics: list[ConfigDiagnostic]) -> None:
        errors = [item for item in diagnostics if item.severity == "error"]
        if errors:
            raise ConfigValidationError(errors)

    def _validate_top_level(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        if not isinstance(data, dict):
            diagnostics.append(
                ConfigDiagnostic(
                    code="config.type.invalid",
                    path="$",
                    severity="error",
                    message="Config root must be an object",
                    suggestion="请确认 YAML 顶层是 key/value 对象。",
                )
            )
            return
        self._validate_unknown_fields("$", data, self._known_top_level_fields(), diagnostics)

    def _validate_model_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("model", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "model", data, self._struct_field_names(ModelConfig), diagnostics
        )
        self._validate_model_values("model", data, diagnostics)

    def _validate_model_values(
        self, section: str, data: dict[str, Any], diagnostics: list[ConfigDiagnostic]
    ) -> None:
        self._validate_numeric_range(
            f"{section}.temperature", data.get("temperature"), diagnostics, minimum=0, maximum=2
        )
        self._validate_numeric_range(
            f"{section}.top_p", data.get("top_p"), diagnostics, minimum=0, maximum=1
        )
        self._validate_numeric_range(
            f"{section}.max_tokens", data.get("max_tokens"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            f"{section}.timeout", data.get("timeout"), diagnostics, minimum=0.001
        )
        self._validate_numeric_range(
            f"{section}.retry_max_attempts", data.get("retry_max_attempts"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            f"{section}.retry_initial_delay",
            data.get("retry_initial_delay"),
            diagnostics,
            minimum=0,
        )
        self._validate_numeric_range(
            f"{section}.retry_backoff_factor",
            data.get("retry_backoff_factor"),
            diagnostics,
            minimum=1,
        )
        self._validate_int_list(
            f"{section}.retry_status_codes",
            data.get("retry_status_codes"),
            diagnostics,
            minimum=100,
            maximum=599,
        )
        self._validate_enum(
            f"{section}.web_search_strategy",
            data.get("web_search_strategy"),
            {"off", "explicit", "auto"},
            diagnostics,
        )
        self._validate_string_list(
            f"{section}.model_capabilities_add", data.get("model_capabilities_add"), diagnostics
        )
        self._validate_string_list(
            f"{section}.model_capabilities_remove",
            data.get("model_capabilities_remove"),
            diagnostics,
        )

        provider = data.get("provider")
        if provider is not None:
            if not isinstance(provider, str) or not provider.strip():
                diagnostics.append(
                    self._error(
                        f"{section}.provider",
                        "Provider must be a non-empty string",
                        "请填写模型服务名称，例如 ollama、openai 或 deepseek。",
                    )
                )
            elif provider not in self.KNOWN_PROVIDERS:
                diagnostics.append(
                    self._warning(
                        f"{section}.provider",
                        f"Unknown provider '{provider}'",
                        "如果这是自定义 Provider，请确认已注册；否则请检查 provider 拼写。",
                        code="config.provider.unknown",
                    )
                )

        if data.get("web_search_enabled") is True and data.get("web_search_strategy") == "off":
            diagnostics.append(
                self._error(
                    f"{section}.web_search_strategy",
                    "web_search_enabled is true but web_search_strategy is off",
                    "启用 Provider 内置联网搜索时，请将 web_search_strategy 设置为 explicit 或 auto。",
                    code="config.model.web_search_conflict",
                )
            )
        if data.get("api_path") is not None and not data.get("base_url"):
            diagnostics.append(
                self._warning(
                    f"{section}.api_path",
                    "api_path is usually meaningful only with base_url",
                    "如果使用自定义代理路径，请同时配置 base_url。",
                    code="config.model.api_path_without_base_url",
                )
            )
        if data.get("auth") is not None and data.get("api_key"):
            diagnostics.append(
                self._warning(
                    f"{section}.auth",
                    "Both api_key and auth are configured",
                    "请确认是否确实需要同时配置静态 API Key 与动态认证。",
                    code="config.model.auth_overlap",
                )
            )
        if (
            provider in self.PROVIDERS_REQUIRING_API_KEY
            and not data.get("api_key")
            and not data.get("auth")
        ):
            diagnostics.append(
                self._warning(
                    f"{section}.api_key",
                    f"Provider '{provider}' usually requires api_key or auth",
                    "请通过配置文件或环境变量提供 API Key；如果由网关注入认证，可忽略此警告。",
                    code="config.model.api_key_missing",
                )
            )
        if isinstance(provider, str):
            self._validate_provider_field_matrix(section, provider, data, diagnostics)

    def _validate_provider_field_matrix(
        self,
        section: str,
        provider: str,
        data: dict[str, Any],
        diagnostics: list[ConfigDiagnostic],
    ) -> None:
        matrix = self.PROVIDER_FIELD_MATRIX.get(provider)
        if not matrix:
            return
        configured_fields = {key for key, value in data.items() if value not in (None, "", [], {})}
        for field_name in sorted(configured_fields & matrix.get("discouraged", set())):
            diagnostics.append(
                self._warning(
                    f"{section}.{field_name}",
                    f"Field '{field_name}' is not normally used by provider '{provider}'",
                    f"请确认 {provider} 是否真的需要 {field_name}；如果不是自定义网关场景，建议移除该字段。",
                    code="config.provider.field_discouraged",
                )
            )
        web_search_fields = {
            "web_search_enabled",
            "web_search_strategy",
            "web_search_context_size",
            "web_search_user_location",
            "web_search_metadata",
            "web_search_allow_fallback",
        }
        configured_web_search_fields = configured_fields & web_search_fields
        supported_web_search = matrix.get("supported_web_search", set())
        unsupported_web_search_fields = configured_web_search_fields - supported_web_search
        if data.get("web_search_enabled") is True and unsupported_web_search_fields:
            diagnostics.append(
                self._warning(
                    f"{section}.web_search_enabled",
                    f"Provider '{provider}' does not expose built-in web search with the configured fields",
                    "如果需要联网搜索，请改用 openai_responses / gemini 的内置搜索，或启用 tool.web_search 自有搜索工具。",
                    code="config.provider.web_search_unsupported",
                )
            )

    def _validate_embedding_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("embedding", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "embedding", data, self._struct_field_names(EmbeddingConfig), diagnostics
        )
        self._validate_embedding_values("embedding", data, diagnostics)

    def _validate_embedding_values(
        self, section: str, data: dict[str, Any], diagnostics: list[ConfigDiagnostic]
    ) -> None:
        self._validate_numeric_range(
            f"{section}.timeout", data.get("timeout"), diagnostics, minimum=0.001
        )
        self._validate_numeric_range(
            f"{section}.dimensions", data.get("dimensions"), diagnostics, minimum=1
        )

    def _validate_memory_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("memory", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "memory", data, self._struct_field_names(MemoryConfig), diagnostics
        )
        self._validate_numeric_range(
            "memory.working_max_turns", data.get("working_max_turns"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            "memory.episodic_threshold", data.get("episodic_threshold"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            "memory.episodic_keep_recent", data.get("episodic_keep_recent"), diagnostics, minimum=0
        )
        self._validate_numeric_range(
            "memory.semantic_top_k", data.get("semantic_top_k"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            "memory.semantic_similarity_threshold",
            data.get("semantic_similarity_threshold"),
            diagnostics,
            minimum=0,
            maximum=1,
        )
        topic_generation = data.get("topic_generation")
        if topic_generation is not None:
            self._validate_object("memory.topic_generation", topic_generation, diagnostics)
            if isinstance(topic_generation, dict):
                self._validate_unknown_fields(
                    "memory.topic_generation",
                    topic_generation,
                    self._struct_field_names(TopicGenerationConfig),
                    diagnostics,
                )
                self._validate_numeric_range(
                    "memory.topic_generation.name_max_length",
                    topic_generation.get("name_max_length"),
                    diagnostics,
                    minimum=1,
                )
                self._validate_numeric_range(
                    "memory.topic_generation.summary_max_length",
                    topic_generation.get("summary_max_length"),
                    diagnostics,
                    minimum=1,
                )

    def _validate_tool_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("tool", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "tool",
            data,
            {"enabled", "builtin_tools", "custom_tools_path", "web_search"},
            diagnostics,
        )
        self._validate_string_list("tool.builtin_tools", data.get("builtin_tools"), diagnostics)
        web_search = data.get("web_search")
        if web_search is not None:
            self._validate_object("tool.web_search", web_search, diagnostics)
            if isinstance(web_search, dict):
                self._validate_unknown_fields(
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
                    diagnostics,
                )
                self._validate_enum(
                    "tool.web_search.provider",
                    web_search.get("provider"),
                    {"bing", "api", "mixed"},
                    diagnostics,
                )
                self._validate_enum(
                    "tool.web_search.trigger_strategy",
                    web_search.get("trigger_strategy"),
                    {"off", "explicit", "auto"},
                    diagnostics,
                )
                self._validate_numeric_range(
                    "tool.web_search.max_results",
                    web_search.get("max_results"),
                    diagnostics,
                    minimum=1,
                )
                self._validate_numeric_range(
                    "tool.web_search.timeout", web_search.get("timeout"), diagnostics, minimum=0.001
                )
                self._validate_numeric_range(
                    "tool.web_search.cache_ttl_seconds",
                    web_search.get("cache_ttl_seconds"),
                    diagnostics,
                    minimum=0,
                )
                self._validate_numeric_range(
                    "tool.web_search.snippet_max_length",
                    web_search.get("snippet_max_length"),
                    diagnostics,
                    minimum=1,
                )
                self._validate_web_search_api(web_search.get("api"), diagnostics)

    def _validate_web_search_api(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        if data is None:
            return
        self._validate_object("tool.web_search.api", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "tool.web_search.api",
            data,
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
            diagnostics,
        )
        self._validate_enum(
            "tool.web_search.api.method", data.get("method"), {"GET", "POST"}, diagnostics
        )

    def _validate_session_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("session", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "session", data, self._struct_field_names(SessionConfig), diagnostics
        )
        self._validate_numeric_range(
            "session.max_sessions", data.get("max_sessions"), diagnostics, minimum=1
        )

    def _validate_think_engine_data(self, data: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        self._validate_object("think_engine", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "think_engine", data, self._struct_field_names(ThinkEngineConfig), diagnostics
        )
        self._validate_numeric_range(
            "think_engine.think_interval_minutes",
            data.get("think_interval_minutes"),
            diagnostics,
            minimum=1,
        )
        self._validate_numeric_range(
            "think_engine.random_walk_steps_min",
            data.get("random_walk_steps_min"),
            diagnostics,
            minimum=0,
        )
        self._validate_numeric_range(
            "think_engine.random_walk_steps_max",
            data.get("random_walk_steps_max"),
            diagnostics,
            minimum=0,
        )
        self._validate_numeric_range(
            "think_engine.emotional_trigger_threshold",
            data.get("emotional_trigger_threshold"),
            diagnostics,
            minimum=0,
            maximum=1,
        )
        self._validate_numeric_range(
            "think_engine.emotional_priority_probability",
            data.get("emotional_priority_probability"),
            diagnostics,
            minimum=0,
            maximum=1,
        )
        self._validate_numeric_range(
            "think_engine.think_temperature",
            data.get("think_temperature"),
            diagnostics,
            minimum=0,
            maximum=2,
        )
        self._validate_numeric_range(
            "think_engine.think_max_tokens", data.get("think_max_tokens"), diagnostics, minimum=1
        )
        self._validate_numeric_range(
            "think_engine.initiative_temperature",
            data.get("initiative_temperature"),
            diagnostics,
            minimum=0,
            maximum=2,
        )
        self._validate_numeric_range(
            "think_engine.initiative_max_tokens",
            data.get("initiative_max_tokens"),
            diagnostics,
            minimum=1,
        )
        min_steps = data.get("random_walk_steps_min")
        max_steps = data.get("random_walk_steps_max")
        if (
            isinstance(min_steps, (int, float))
            and isinstance(max_steps, (int, float))
            and min_steps > max_steps
        ):
            diagnostics.append(
                self._error(
                    "think_engine.random_walk_steps_max",
                    "random_walk_steps_max must be >= random_walk_steps_min",
                    "请确保随机游走最大步数不小于最小步数。",
                    code="config.range.cross_field",
                )
            )

    def _validate_resource_control_data(
        self, data: Any, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        self._validate_object("resource_control", data, diagnostics)
        if not isinstance(data, dict):
            return
        self._validate_unknown_fields(
            "resource_control",
            data,
            self._struct_field_names(ResourceControlConfig),
            diagnostics,
        )
        non_negative_fields = {
            "runtime_queue_size",
            "acquire_timeout_seconds",
            "default_timeout_seconds",
            "dependency_install_timeout_seconds",
        }
        positive_fields = self._struct_field_names(ResourceControlConfig) - {
            "enabled",
            "overflow_policy",
            *non_negative_fields,
        }
        for field_name in sorted(positive_fields):
            self._validate_numeric_range(
                f"resource_control.{field_name}",
                data.get(field_name),
                diagnostics,
                minimum=1,
            )
        for field_name in sorted(non_negative_fields):
            self._validate_numeric_range(
                f"resource_control.{field_name}",
                data.get(field_name),
                diagnostics,
                minimum=0,
            )
        self._validate_enum(
            "resource_control.overflow_policy",
            data.get("overflow_policy"),
            {"reject", "wait"},
            diagnostics,
        )
        if data.get("overflow_policy") == "wait" and data.get("acquire_timeout_seconds") == 0:
            diagnostics.append(
                self._error(
                    "resource_control.acquire_timeout_seconds",
                    "acquire_timeout_seconds must be > 0 when overflow_policy is wait",
                    "排队等待策略需要设置大于 0 的 acquire_timeout_seconds，或改用 reject 策略。",
                    code="config.resource_control.wait_without_timeout",
                )
            )

    def _validate_object(self, path: str, value: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        if not isinstance(value, dict):
            diagnostics.append(
                self._error(
                    path,
                    f"Config section '{path}' must be an object",
                    "请确认该配置段使用 YAML 对象写法。",
                    code="config.section.type",
                )
            )

    def _validate_unknown_fields(
        self,
        section: str,
        data: dict[str, Any],
        allowed: set[str],
        diagnostics: list[ConfigDiagnostic],
    ) -> None:
        unknown = sorted(set(data) - allowed)
        for field_name in unknown:
            path = field_name if section == "$" else f"{section}.{field_name}"
            diagnostics.append(
                self._error(
                    path,
                    f"Unknown config field '{field_name}'",
                    "请检查字段名拼写，或确认当前版本是否支持该配置项。",
                    code="config.field.unknown",
                )
            )

    def _validate_numeric_range(
        self,
        path: str,
        value: Any,
        diagnostics: list[ConfigDiagnostic],
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> None:
        if value is None:
            return
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be numeric",
                    "请填写数字。",
                    code="config.field.type",
                )
            )
            return
        if minimum is not None and value < minimum:
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be >= {minimum}",
                    f"请填写不小于 {minimum} 的数字。",
                    code="config.field.range",
                )
            )
        if maximum is not None and value > maximum:
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be <= {maximum}",
                    f"请填写不大于 {maximum} 的数字。",
                    code="config.field.range",
                )
            )

    def _validate_enum(
        self,
        path: str,
        value: Any,
        allowed: set[str],
        diagnostics: list[ConfigDiagnostic],
    ) -> None:
        if value is None:
            return
        if value not in allowed:
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be one of: {', '.join(sorted(allowed))}",
                    f"请从这些值中选择一个：{', '.join(sorted(allowed))}。",
                    code="config.field.enum",
                )
            )

    def _validate_string_list(
        self, path: str, value: Any, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        if value is None:
            return
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be a list of strings",
                    '请使用字符串列表，例如 ["time", "memory"]。',
                    code="config.field.type",
                )
            )

    def _validate_int_list(
        self,
        path: str,
        value: Any,
        diagnostics: list[ConfigDiagnostic],
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        if value is None:
            return
        if not isinstance(value, list) or any(
            not isinstance(item, int) or isinstance(item, bool) for item in value
        ):
            diagnostics.append(
                self._error(
                    path,
                    f"Config field '{path}' must be a list of integers",
                    "请使用整数列表，例如 [500, 502, 503, 504]。",
                    code="config.field.type",
                )
            )
            return
        for item in value:
            if minimum is not None and item < minimum or maximum is not None and item > maximum:
                diagnostics.append(
                    self._error(
                        path,
                        f"Config field '{path}' contains invalid status code {item}",
                        "HTTP 状态码应在 100 到 599 之间。",
                        code="config.field.range",
                    )
                )
                return

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
            "resource_control",
            "character",
            "character_file",
        }

    @staticmethod
    def _struct_field_names(struct_type: type) -> set[str]:
        return set(getattr(struct_type, "__struct_fields__", ()))

    @staticmethod
    def _error(
        path: str,
        message: str,
        suggestion: str | None = None,
        *,
        code: str = "config.validation.error",
    ) -> ConfigDiagnostic:
        return ConfigDiagnostic(
            code=code, path=path, severity="error", message=message, suggestion=suggestion
        )

    @staticmethod
    def _warning(
        path: str,
        message: str,
        suggestion: str | None = None,
        *,
        code: str = "config.validation.warning",
    ) -> ConfigDiagnostic:
        return ConfigDiagnostic(
            code=code, path=path, severity="warning", message=message, suggestion=suggestion
        )
