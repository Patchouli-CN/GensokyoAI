"""环境变量配置覆盖。"""

import os

from .config_schema import AppConfig, AuthConfig, LogLevel


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """应用环境变量。"""
    if os.getenv("GENSOKYOAI_PROVIDER"):
        config.model.provider = os.getenv("GENSOKYOAI_PROVIDER")  # type: ignore
    if os.getenv("GENSOKYOAI_MODEL"):
        config.model.name = os.getenv("GENSOKYOAI_MODEL")  # type: ignore
    if os.getenv("GENSOKYOAI_API_KEY"):
        config.model.api_key = os.getenv("GENSOKYOAI_API_KEY")  # type: ignore
    if os.getenv("GENSOKYOAI_BASE_URL"):
        config.model.base_url = os.getenv("GENSOKYOAI_BASE_URL")  # type: ignore
    if os.getenv("GENSOKYOAI_API_PATH"):
        config.model.api_path = os.getenv("GENSOKYOAI_API_PATH")  # type: ignore
    if os.getenv("GENSOKYOAI_AUTH_TYPE"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.auth_type = os.getenv("GENSOKYOAI_AUTH_TYPE")  # type: ignore
    if os.getenv("GENSOKYOAI_TOKEN_URL"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.token_url = os.getenv("GENSOKYOAI_TOKEN_URL")  # type: ignore
    if os.getenv("GENSOKYOAI_ACCESS_TOKEN"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.access_token = os.getenv("GENSOKYOAI_ACCESS_TOKEN")  # type: ignore
    if os.getenv("GENSOKYOAI_REFRESH_TOKEN"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.refresh_token = os.getenv("GENSOKYOAI_REFRESH_TOKEN")  # type: ignore
    if os.getenv("GENSOKYOAI_CLIENT_ID"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.client_id = os.getenv("GENSOKYOAI_CLIENT_ID")  # type: ignore
    if os.getenv("GENSOKYOAI_CLIENT_SECRET"):
        config.model.auth = config.model.auth or AuthConfig()
        config.model.auth.client_secret = os.getenv("GENSOKYOAI_CLIENT_SECRET")  # type: ignore
    if os.getenv("GENSOKYOAI_RETRY_MAX_ATTEMPTS"):
        config.model.retry_max_attempts = int(os.getenv("GENSOKYOAI_RETRY_MAX_ATTEMPTS"))  # type: ignore
    if os.getenv("GENSOKYOAI_RETRY_INITIAL_DELAY"):
        config.model.retry_initial_delay = float(os.getenv("GENSOKYOAI_RETRY_INITIAL_DELAY"))  # type: ignore
    if os.getenv("GENSOKYOAI_RETRY_BACKOFF_FACTOR"):
        config.model.retry_backoff_factor = float(os.getenv("GENSOKYOAI_RETRY_BACKOFF_FACTOR"))  # type: ignore
    if os.getenv("GENSOKYOAI_RETRY_STATUS_CODES"):
        config.model.retry_status_codes = [
            int(code.strip())
            for code in os.getenv("GENSOKYOAI_RETRY_STATUS_CODES", "").split(",")
            if code.strip()
        ]  # type: ignore
    if os.getenv("GENSOKYOAI_THINKING_ENABLED"):
        config.model.thinking_enabled = os.getenv("GENSOKYOAI_THINKING_ENABLED").lower() == "true"  # type: ignore
    if os.getenv("GENSOKYOAI_REASONING_EFFORT"):
        config.model.reasoning_effort = os.getenv("GENSOKYOAI_REASONING_EFFORT")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_PROVIDER"):
        config.embedding.provider = os.getenv("GENSOKYOAI_EMBEDDING_PROVIDER")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_MODEL"):
        config.embedding.name = os.getenv("GENSOKYOAI_EMBEDDING_MODEL")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_API_KEY"):
        config.embedding.api_key = os.getenv("GENSOKYOAI_EMBEDDING_API_KEY")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_BASE_URL"):
        config.embedding.base_url = os.getenv("GENSOKYOAI_EMBEDDING_BASE_URL")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_DIMENSIONS"):
        config.embedding.dimensions = int(os.getenv("GENSOKYOAI_EMBEDDING_DIMENSIONS"))  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_ENCODING_FORMAT"):
        config.embedding.encoding_format = os.getenv("GENSOKYOAI_EMBEDDING_ENCODING_FORMAT")  # type: ignore
    if os.getenv("GENSOKYOAI_EMBEDDING_TIMEOUT"):
        config.embedding.timeout = int(os.getenv("GENSOKYOAI_EMBEDDING_TIMEOUT"))  # type: ignore
    if embedding_use_proxy := os.getenv("GENSOKYOAI_EMBEDDING_USE_PROXY"):
        config.embedding.use_proxy = embedding_use_proxy.lower() == "true"
    if os.getenv("GENSOKYOAI_LOG_LEVEL"):
        config.log_level = LogLevel(os.getenv("GENSOKYOAI_LOG_LEVEL"))
    if os.getenv("GENSOKYOAI_LOG_CONSOLE"):
        config.log_console = os.getenv("GENSOKYOAI_LOG_CONSOLE").lower() == "true"  # type: ignore
    if debug_silent_output := os.getenv("GENSOKYOAI_DEBUG_SILENT_OUTPUT"):
        config.debug_silent_output = debug_silent_output.lower() == "true"
    if event_trace_enabled := os.getenv("GENSOKYOAI_EVENT_TRACE_ENABLED"):
        config.event_trace_enabled = event_trace_enabled.lower() == "true"
    if os.getenv("GENSOKYOAI_MEMORY_WORKING_TURNS"):
        config.memory.working_max_turns = int(
            os.getenv("GENSOKYOAI_MEMORY_WORKING_TURNS")  # type: ignore
        )
    return config
