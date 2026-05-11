"""配置管理兼容入口。

新代码优先从 config_schema、config_loader、config_merge、config_env 导入；
旧代码仍可继续从本模块导入 AppConfig、ConfigLoader 等名称。
"""

from .character_validator import CharacterValidator
from .config_env import apply_env_overrides
from .config_loader import ConfigLoader
from .config_merge import ConfigMerger
from .config_schema import (
    AppConfig,
    AuthConfig,
    CharacterConfig,
    EmbeddingConfig,
    LogLevel,
    MemoryConfig,
    ModelConfig,
    ResourceControlConfig,
    SessionConfig,
    ThinkEngineConfig,
    ToolConfig,
    TopicGenerationConfig,
    WebSearchAPIConfig,
    WebSearchToolConfig,
)
from .config_validator import ConfigDiagnostic, ConfigValidationError, ConfigValidator

__all__ = [
    "AppConfig",
    "AuthConfig",
    "CharacterConfig",
    "CharacterValidator",
    "ConfigLoader",
    "ConfigDiagnostic",
    "ConfigMerger",
    "ConfigValidationError",
    "ConfigValidator",
    "EmbeddingConfig",
    "LogLevel",
    "MemoryConfig",
    "ModelConfig",
    "ResourceControlConfig",
    "SessionConfig",
    "ThinkEngineConfig",
    "ToolConfig",
    "TopicGenerationConfig",
    "WebSearchAPIConfig",
    "WebSearchToolConfig",
    "apply_env_overrides",
]
