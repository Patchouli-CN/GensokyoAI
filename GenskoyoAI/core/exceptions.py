"""自定义异常"""
#GenskoyoAI\core\exceptions.py

class GenskoyoError(Exception):
    """基础异常类"""

    pass


class ConfigError(GenskoyoError):
    """配置错误"""

    pass


class AgentError(GenskoyoError):
    """Agent 错误"""

    pass


class MemoryError(GenskoyoError):
    """记忆系统错误"""

    pass


class ToolError(GenskoyoError):
    """工具系统错误"""

    pass


class SessionError(GenskoyoError):
    """会话错误"""

    pass


class ModelError(GenskoyoError):
    """模型调用错误"""

    pass
