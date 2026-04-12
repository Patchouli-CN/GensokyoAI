"""
GenskoyoAI - 幻想乡 AI 角色扮演引擎
=====================================

一个专为角色扮演设计的异步 AI 对话框架，提供完整的记忆系统、
会话管理、工具调用和可扩展的后端支持。

核心特性
--------

🎭 **角色扮演优化**
    - 支持 YAML 格式的角色配置文件
    - 系统提示词模板和示例对话
    - 角色一致性维护

🧠 **三层记忆系统**
    - 工作记忆 (Working Memory)：当前会话的完整对话上下文
    - 情景记忆 (Episodic Memory)：历史对话的压缩摘要
    - 语义记忆 (Semantic Memory)：基于向量检索的长期知识存储

💬 **会话管理**
    - 会话创建、保存、恢复和列表
    - 自动持久化，支持异步 I/O
    - 会话回滚和切换

🔧 **工具调用 (Function Calling)**
    - 内置工具：时间、月相、系统信息
    - 装饰器式工具注册
    - 并行工具执行

🎛️ **智能命令系统**
    - 标签模式：<know>、<meta>、<attention> 等
    - 前缀模式：/help、/save、/new 等
    - 提示词上下文累积

⚡ **异步架构**
    - 全异步设计，基于 asyncio
    - 后台任务队列处理记忆和持久化
    - 流式和非流式响应支持

🔌 **可扩展后端**
    - 抽象后端基类 BaseBackend
    - 内置 Rich 美化的控制台后端
    - 可扩展为 WebUI、QQ 机器人等


快速开始
--------

1. 安装依赖：
   pip install ollama msgspec rich loguru ayafileio numpy pyyaml

2. 确保 Ollama 运行并下载模型：
   ollama pull qwen3.5:9b
   ollama pull nomic-embed-text  # 用于语义记忆

3. 创建角色配置文件 (characters/my_role.yaml)：
   name: "角色名"
   system_prompt: "你的角色设定..."
   greeting: "开场白"

4. 启动对话：
   python main_v2.py --character characters/my_role.yaml --new-session


命令行参数
----------
--character, -c    角色名称或配置文件路径
--config           配置文件路径 (默认: config/default.yaml)
--new-session      创建新会话
--resume SESSION   恢复指定会话
--list-sessions    列出所有历史会话
--no-stream        禁用流式输出


环境变量
--------
GENSKOYAI_MODEL                覆盖模型名称
GENSKOYAI_LOG_LEVEL            日志级别 (DEBUG/INFO/WARNING/ERROR)
GENSKOYAI_LOG_CONSOLE          控制台日志开关 (true/false)
GENSKOYAI_MEMORY_WORKING_TURNS 工作记忆最大轮数


示例
----
>>> from GenskoyoAI import Agent, ConsoleBackendBuilder
>>>
>>> # 创建 Agent
>>> agent = Agent(character_file="characters/yuyuko.yaml")
>>>
>>> # 创建控制台后端并运行
>>> backend = ConsoleBackendBuilder(agent).build()
>>> await backend.run_interactive()


许可证
------
MIT License

作者
------
Patchouli-CN <3072252442@qq.com>

版本历史
--------
0.1.0 (2026-04-12)
    - 初始版本
    - 完整的三层记忆系统
    - 控制台后端和命令系统
    - 工具调用支持
"""

__version__ = "0.1.0"
__author__ = "Patchouli-CN"
__license__ = "MIT"
__email__ = "3072252442@qq.com"

# 导出主要类和函数
from GenskoyoAI.core.agent import Agent, StreamChunk
from GenskoyoAI.core.config import AppConfig, ConfigLoader, CharacterConfig
from GenskoyoAI.backends import BaseBackend, ConsoleBackend, ConsoleBackendBuilder
from GenskoyoAI.core.exceptions import (
    GenskoyoError,
    AgentError,
    ConfigError,
    MemoryError,
    ToolError,
    SessionError,
    ModelError,
)

__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    "__license__",
    # 核心类
    "Agent",
    "StreamChunk",
    "AppConfig",
    "ConfigLoader",
    "CharacterConfig",
    # 后端
    "BaseBackend",
    "ConsoleBackend",
    "ConsoleBackendBuilder",
    # 异常
    "GenskoyoError",
    "AgentError",
    "ConfigError",
    "MemoryError",
    "ToolError",
    "SessionError",
    "ModelError",
]
