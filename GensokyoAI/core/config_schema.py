"""配置 schema 定义。"""

from pathlib import Path
from typing import Any, Literal
from enum import Enum

from msgspec import Struct, field

from ..utils.logger import setup_logging


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class AuthConfig(Struct):
    """模型 Provider 认证配置。"""

    auth_type: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    refresh_token: str | None = None
    access_token: str | None = None
    expires_at: float | None = None
    refresh_before_seconds: int = 60
    auth_headers: dict[str, str] = field(default_factory=dict)
    auth_body: dict[str, str] = field(default_factory=dict)
    token_field: str = "access_token"
    expires_in_field: str = "expires_in"
    allow_401_refresh: bool = True


class ModelConfig(Struct):
    """模型配置"""

    provider: str = "ollama"  # LLM Provider: ollama / openai / openrouter / deepseek / gemini / claude
    name: str = "qwen3.5:9b"
    base_url: str | None = None
    api_path: str | None = None
    api_key: str | None = None  # API 密钥（OpenAI/Gemini/Claude 等需要）
    extra_headers: dict[str, str] = field(default_factory=dict)
    auth: AuthConfig | None = None
    model_capabilities_add: list[str] = field(default_factory=list)
    model_capabilities_remove: list[str] = field(default_factory=list)
    web_search_enabled: bool = False
    web_search_strategy: Literal["off", "explicit", "auto"] = "off"
    web_search_context_size: str | None = None
    web_search_user_location: dict[str, Any] = field(default_factory=dict)
    web_search_allow_fallback: bool = True
    web_search_metadata: dict[str, Any] = field(default_factory=dict)
    stream: bool = True
    think: bool = False
    thinking_enabled: bool | None = None
    reasoning_effort: str | None = None
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    timeout: int = 60
    use_proxy: bool = False  # 是否使用代理
    retry_max_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_backoff_factor: float = 2.0
    retry_status_codes: list[int] = field(default_factory=lambda: [500, 502, 503, 504])


class EmbeddingConfig(Struct):
    """Embedding 模型配置"""

    provider: str | None = None  # 默认复用 model.provider
    name: str | None = None  # 必填；未配置时不再误用聊天模型
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int | None = None
    encoding_format: str | None = None
    timeout: int | None = None
    use_proxy: bool | None = None


class TopicGenerationConfig(Struct):
    """话题生成配置"""

    name_max_length: int = 10
    summary_max_length: int = 100


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


class ThinkEngineConfig(Struct):
    """思考引擎配置"""

    enabled: bool = True  # 是否启用静默思考
    think_interval_minutes: int = 5  # 思考间隔（分钟）
    random_walk_steps_min: int = 2  # 随机游走最少步数
    random_walk_steps_max: int = 5  # 随机游走最多步数
    emotional_trigger_threshold: float = 0.5  # 优先选择高情感话题的阈值
    emotional_priority_probability: float = 0.7  # 优先选择高情感话题的概率
    think_temperature: float = 0.7  # 思考时的温度
    think_max_tokens: int = 200  # 思考最大 token 数
    initiative_temperature: float = 0.8  # 生成主动消息时的温度
    initiative_max_tokens: int = 100  # 生成主动消息最大 token 数


class WebSearchAPIConfig(Struct):
    """自有 Web search API Provider 配置。"""

    endpoint: str | None = None
    method: str = "POST"
    api_key: str | None = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    headers: dict[str, str] = field(default_factory=dict)
    request_template: dict[str, Any] = field(default_factory=lambda: {"query": "{query}", "count": "{max_results}"})
    query_params: dict[str, Any] = field(default_factory=dict)
    results_path: str = "results"
    title_path: str = "title"
    url_path: str = "url"
    snippet_path: str = "content"
    published_at_path: str | None = None


class WebSearchToolConfig(Struct):
    """自有 Web search 工具配置。"""

    enabled: bool = False
    provider: str = "bing"  # bing / api / mixed
    max_results: int = 10
    timeout: int = 10
    cache_ttl_seconds: int = 300
    trigger_strategy: Literal["off", "explicit", "auto"] = "explicit"
    freshness_keywords: list[str] = field(
        default_factory=lambda: [
            "今天",
            "今日",
            "现在",
            "当前",
            "最新",
            "新闻",
            "价格",
            "版本",
            "发布",
            "更新",
            "today",
            "latest",
            "news",
            "price",
            "version",
        ]
    )
    prefer_for_characters: list[str] = field(default_factory=list)
    prefer_for_scenarios: list[str] = field(default_factory=list)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    region: str | None = None
    safe_search: str = "moderate"
    snippet_max_length: int = 200
    api: WebSearchAPIConfig = field(default_factory=WebSearchAPIConfig)


class ToolConfig(Struct):
    """工具配置"""

    enabled: bool = True
    builtin_tools: list[str] = field(default_factory=lambda: ["time", "moon", "memory", "system"])
    custom_tools_path: Path | None = None
    web_search: WebSearchToolConfig = field(default_factory=WebSearchToolConfig)


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

    # 调试配置：开启后才输出静默思考、内心决策、推理内容等默认隐藏信息
    debug_silent_output: bool = False

    # 事件追踪日志：开启后 EventBus 会输出每个事件的详细投递日志
    event_trace_enabled: bool = False

    # 子配置
    model: ModelConfig = field(default_factory=ModelConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tool: ToolConfig = field(default_factory=ToolConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    think_engine: ThinkEngineConfig = field(default_factory=ThinkEngineConfig)

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
