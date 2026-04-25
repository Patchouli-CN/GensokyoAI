# 🌸 GensokyoAI - 幻想乡 AI 角色扮演引擎

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 一个专为角色扮演设计的异步 AI 对话框架，支持 Ollama / OpenAI / DeepSeek / OpenAI Responses / Claude / Gemini 等多种 LLM Provider，提供三层记忆系统、会话管理、工具调用和可扩展后端。

## 🐧 QQ 群：675608356

- **欢迎来提供功能建议、BUG 反馈以及纯粹交流ᗜᴗᗜ！**
- **邀请链接** - [QQ](https://qun.qq.com/universal-share/share?ac=1&authKey=2YjM%2FXyrxGTrkTDQMoxKM5QBzphCJzFxbXnKYDpF%2FVkmuNvH2%2BNaP2Z6l7d9LsB%2B&busi_data=eyJncm91cENvZGUiOiI2NzU2MDgzNTYiLCJ0b2tlbiI6IkROTnRsMVlMcWdPUzExZlp5T2RMbDI5eXBGRVNRcDV1blAxY2crWGhrUjdpaWVXSXoybE5CdFRSb3Q5Z3dCa0giLCJ1aW4iOiIyMjI2OTU2NTc5In0%3D&data=UBToZl_UF-gj5B9gKcj0YXcw7qCwC5DKmrw0Sh2-XNjTejEA31jAi1BONVOvh9v5PB98Y0f_Hz-MDvXiFrwnLA&svctype=4&tempid=h5_group_info) 

## ✨ 核心亮点

> 这一部分面向普通用户：不需要理解代码，也能快速知道 GensokyoAI 能带来什么体验。

### 🎭 像在和真正的角色聊天

GensokyoAI 不是简单的问答机器人，而是围绕“角色扮演”设计的对话引擎。角色可以拥有稳定的人设、说话习惯、问候语和示例对话，在长期交流中更容易保持一致的性格与表达方式。

### 🧠 角色会记住重要的事

对话不会只停留在当前一句话。角色可以保留近期上下文，也能把长期交流压缩成记忆，并围绕话题建立联系；后续对话中，系统会尝试检索相关记忆，帮助角色更自然地想起过去内容。

### 🛠️ 角色可以主动管理记忆

记忆管理不是简单地“全部塞进上下文”。在启用工具调用且模型选择调用记忆工具时，角色可以根据对话内容主动记住或回忆信息，并借助话题和遗忘机制让记忆更像真实交流中的印象，而不是僵硬的记录本。

### 🌙 角色有自己的“心理时间”

启用静默思考后，角色可以在空闲时回顾已有话题、整理思绪；当系统判断时机合适时，还可以主动开口。这让角色不只是被动回答，而更像拥有自己的内心世界。

### 💬 长期会话更顺手

支持创建、保存、恢复、列出和回滚会话。说错话可以撤回，历史会话可以继续，不同角色也可以分别维护自己的交流记录。

### 🔌 可选择不同模型服务

你可以按需求选择本地模型、OpenAI 兼容服务、DeepSeek、Claude 或 Gemini。想要本地免费运行、接入云端大模型，或混合使用不同服务，都可以通过配置完成。

## 🌐 全局介绍

### 🎭 角色配置与角色一致性

- **YAML 角色配置**：用简单配置文件定义角色名称、人设、问候语和示例对话。
- **系统提示词模板**：支持长提示词和示例对话，快速塑造角色性格。
- **角色一致性维护**：通过工作记忆、情景记忆和语义记忆，让角色在长对话中保持上下文和性格一致。

### 🧠 三层记忆系统

| 记忆类型 | 作用 | 实现方式 |
|---------|------|---------|
| **工作记忆** | 当前会话的完整对话 | 滑动窗口，保留最近 N 轮 |
| **情景记忆** | 历史对话的压缩摘要 | 模型自动摘要，关键事件提取 |
| **语义记忆** | 长期知识存储和检索 | 话题感知存储 + 遗忘曲线，默认不依赖向量数据库 |

### 🛠️ 自主记忆工具

在工具调用启用、且所选模型支持并选择调用工具时，角色可以主动管理自己的记忆：

- **`remember` 工具**：AI 自主判断何时记住重要信息。
- **`recall` 工具**：AI 需要时主动检索相关记忆。
- **话题感知存储**：自动将记忆归类到话题，建立关联图谱。
- **遗忘曲线**：基于重要性、情感效价和访问频率的记忆权重调整机制。
- **`update_memory` 工具**：当旧信息过时或不准确时，可以更新已有记忆。

> 💡 **设计哲学**：记忆管理完全交给 AI 自主决策，不做固定规则。最懂角色需要记住什么的，应该是正在扮演它的模型本身。

### 🧠 静默思考引擎（ThinkEngine）

让 AI 拥有自己的“心理时间”：

- **定时触发思考**：AI 在空闲且已有可回顾话题时主动回顾过往话题。
- **随机游走话题图谱**：模拟人类联想式思维。
- **情感驱动优先**：优先思考高情感值的话题。
- **自主决策是否说话**：通过行动规划判断是否主动发起对话；不保证每次思考都会开口。

> 💡 **设计哲学**：真正的角色不应该只是“回答问题”，而应该有自己的内心世界。静默思考让 AI 能够在空闲时整理思绪，并在恰当的时机主动开口。

### 🎯 行动规划系统

| 行动类型 | 说明 |
|---------|------|
| **SPEAK** | 回应用户消息 |
| **INITIATIVE_SPEAK** | 主动发起对话 |
| **THINK** | 静默思考（内部） |
| **REMEMBER** | 主动记住某事 |
| **RECALL** | 主动回忆 |
| **WAIT** | 什么都不做 |

### 💬 强大的会话管理

- ✅ 创建、保存、恢复、列出会话。
- ✅ 支持自动持久化，后台保存流程使用异步 I/O。
- ✅ 会话回滚，说错话可以撤回。
- ✅ 会话按角色保存；启动时选择不同角色即可维护各自的会话记录。

### 🔧 工具调用

内置工具让角色拥有“超能力”：

- `get_current_time`：获取当前时间。
- `get_current_dateinfo`：获取日期和曜日（七曜日！）。
- `get_moon_phase`：获取月相。
- `get_system_info`：获取系统信息。
- `remember` / `recall`：自主记忆管理。
- `update_memory`：更新已有记忆。

工具调用已统一适配多 Provider：OpenAI / DeepSeek / OpenAI Responses / Ollama / Claude / Gemini 会转换为各自官方要求的工具调用格式。DeepSeek 使用独立 Provider 处理 thinking mode 下工具调用所需的 `reasoning_content` 回传；Claude 使用官方 Messages API 的 `tool_use` / `tool_result` content block，不使用 OpenAI 风格的 `role: tool`。

### 🎛️ 智能命令系统

| 命令类型 | 示例 | 说明 |
|---------|------|------|
| **提示词标签** | `<know>内容</know>` | 动态注入参考资料 |
| | `<meta>内容</meta>` | 设定场景 / 元数据 |
| | `<attention>内容</attention>` | 提醒或纠正 AI |
| **系统命令** | `/help`, `/save`, `/new` | 控制程序行为 |
| **聊天命令** | `<think>`, `<whisper>` | 本地显示，不发给 AI |

### 🔌 多 LLM Provider 支持

| Provider | 对话 | 工具调用 | Embeddings | 说明 |
|----------|------|----------|------------|------|
| **Ollama** | ✅ | ✅ | ✅ | 本地模型，默认 Provider |
| **OpenAI** | ✅ | ✅ | ✅ | Chat Completions API，兼容 SiliconFlow / vLLM / Groq 等第三方服务 |
| **DeepSeek** | ✅ | ✅ | ❌ | DeepSeek 官方 OpenAI 兼容 API，支持 thinking mode 与 `reasoning_content` 回传 |
| **OpenAI Responses** | ✅ | ✅ | ✅ | OpenAI 官方 Responses API |
| **Claude** | ✅ | ✅ | ❌ | Anthropic Claude 系列；官方不提供自家 embedding 模型 |
| **Gemini** | ✅ | ✅ 基础 | ✅ | Google Gemini 系列；工具结果当前以文本形式回传 |

> 💡 支持自定义 Provider 注册，可以扩展到其他 LLM API。

### ⚡ 事件驱动架构

- 全异步设计，基于 `asyncio`。
- 事件总线解耦 Agent、后端、工具、记忆和持久化组件。
- 后台任务队列处理异步持久化。
- 支持流式输出和打字机效果。
- 优雅的信号处理和关闭流程，Ctrl+C 安全退出，尽量保证数据不丢失。

### 🔌 可扩展后端

- 抽象后端基类 `BaseBackend`。
- 内置 Rich 美化的控制台后端。
- 命令系统与后端解耦，易于扩展为 WebUI、QQ 机器人、Discord Bot 等。

## 📦 快速开始

### 1. 环境要求

- Python 3.10+
- 以下任选一种 LLM 后端：
  - [Ollama](https://ollama.ai/) 本地运行（默认，免费）
  - OpenAI API Key，或 SiliconFlow 等云端服务
  - DeepSeek API Key
  - Anthropic Claude API Key
  - Google Gemini API Key

### 2. 安装

#### 方式一：使用 UV（推荐）

```bash
git clone https://github.com/Patchouli-CN/GensokyoAI.git
cd GensokyoAI
```

**基础安装 + Ollama（默认 Provider）**

```bash
uv sync --extra ollama
```

**或安装其他 Provider**

```bash
uv sync --extra openai      # OpenAI / DeepSeek / SiliconFlow 等 OpenAI SDK 兼容服务
uv sync --extra claude      # Anthropic Claude
uv sync --extra gemini      # Google Gemini
uv sync --extra all         # 全部 Provider
```

#### 方式二：使用 pip（普通用户不推荐）

```bash
git clone https://github.com/Patchouli-CN/GensokyoAI.git
cd GensokyoAI
pip install -r requirements.txt
```

**按需安装 LLM Provider（pip）**

```bash
pip install ollama          # Ollama（默认）
pip install openai          # OpenAI / DeepSeek / SiliconFlow 等 OpenAI SDK 兼容服务
pip install anthropic       # Anthropic Claude
pip install google-genai    # Google Gemini
```

### 3. 配置主聊天模型

编辑 `config/default.yaml` 中的 `model` 配置。

**Ollama（默认）**

```bash
ollama pull qwen3.5:9b
```

```yaml
model:
  provider: "ollama"
  name: "qwen3.5:9b"
  base_url: "http://localhost:11434"
```

**OpenAI Chat Completions 兼容服务**

```yaml
model:
  provider: "openai"
  name: "gpt-4o"
  api_key: "sk-..."
  base_url: null # 可选，不填则使用 OpenAI 官方；第三方兼容服务填写对应地址
```

**DeepSeek（推荐独立 Provider）**

DeepSeek 虽然兼容 OpenAI SDK，但 thinking mode 下发生工具调用后，后续请求需要回传 `reasoning_content`。因此推荐使用独立的 `deepseek` Provider，而不是把 DeepSeek 配到通用 `openai` Provider 下。

```yaml
model:
  provider: "deepseek"
  name: "deepseek-v4-pro"
  api_key: "sk-..."
  base_url: null              # 默认 https://api.deepseek.com
  thinking_enabled: true      # 默认 true；如需关闭 thinking mode 可设为 false
  reasoning_effort: "high"    # high / max，默认 high
```

**OpenAI Responses API**

```yaml
model:
  provider: "openai_responses"
  name: "gpt-5"
  api_key: "sk-..."
```

**Claude**

```yaml
model:
  provider: "claude"
  name: "claude-sonnet-4-20250514"
  api_key: "sk-ant-..."
```

**Gemini**

```yaml
model:
  provider: "gemini"
  name: "gemini-2.0-flash"
  api_key: "AIza..."
```

### 4. 配置 Embedding 模型（可选）

Embedding 模型与主聊天模型独立配置。只有在你要调用 `ModelClient.embeddings()`、接入向量检索或外部向量存储时才需要配置。

```yaml
embedding:
  provider: "openai"                 # 可省略，默认复用 model.provider
  name: "text-embedding-3-small"     # 必填：不要填写聊天模型
  api_key: "sk-..."                  # 可省略，默认复用 model.api_key
  base_url: null                     # 可省略，默认复用 model.base_url
  dimensions: 1024                   # 可选，仅部分模型支持
  encoding_format: "float"           # 可选：float / base64
```

> 💡 如果主聊天模型使用 Claude，也需要把 embedding 配到 OpenAI / Gemini / Ollama 或其他兼容 Provider。Anthropic 官方不提供 Claude 自家的 embeddings。

### 5. 创建角色（可选）

在 `characters/` 目录或任意你喜欢的位置创建角色文件，例如 `characters/example.yaml`：

```yaml
name: "森近霖之助"
system_prompt: |
  你是森近霖之助，是香霖堂的店主……

greeting: "「欢迎来到香霖堂。」"

example_dialogue:
  - user: "这个道具是什么？"
    assistant: "「这可不是普通的外界道具。」"
```

也可以直接使用 `characters/zh_cn/` 目录中的内置角色。

### 6. 启动对话

```bash
# 新建会话
uv run main_v2.py --character characters/zh_cn/KirisameMarisa.yaml --new-session

# 恢复会话
uv run main_v2.py --character characters/zh_cn/KirisameMarisa.yaml --resume <session_id>

# 列出所有会话
uv run main_v2.py --list-sessions
```

Windows 用户可以直接双击 `run_default_uv.cmd` 或 `run_default_pip.cmd` 快速启动默认角色。

## 🎮 命令行参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--character` | `-c` | 角色配置文件路径 |
| `--config` | - | 应用配置文件路径，默认 `config/default.yaml` |
| `--new-session` | - | 创建新会话 |
| `--resume` | - | 恢复指定 ID 的会话 |
| `--list-sessions` | - | 列出所有历史会话 |
| `--no-stream` | - | 禁用流式输出 |

## 🎨 对话中的命令

### 提示词标签（会传递给 AI）

- `<know>幻想乡位于日本...</know>`：动态注入参考资料。
- `<meta>当前场景：博丽神社...</meta>`：设定场景 / 元数据。
- `<attention>记住，你现在很困...</attention>`：提醒或纠正 AI 行为。

### 系统命令

- `/help`：显示帮助。
- `/exit` 或 `/quit`：退出程序。
- `/save`：保存当前会话。
- `/new`：创建新会话。
- `/back`：回滚上一轮对话。
- `/sessions`：列出历史会话。
- `/stream on/off`：切换流式输出。
- `/clear`：清空提示词上下文。
- `/errors`：查看最近错误统计。

### 聊天命令（仅本地显示，不发送给 AI）

- `<think>内心独白</think>`：表达角色内心想法。
- `<whisper>悄悄话</whisper>`：小声说话。
- `<ooc>出戏内容</ooc>`：戏外交流。
- `<describe>环境描写</describe>`：场景描述。
- `<action>角色动作</action>`：动作描写。

## 🔧 配置说明

### 主模型配置

```yaml
model:
  provider: "ollama"                 # ollama / openai / deepseek / openai_responses / claude / gemini
  name: "qwen3.5:9b"                 # 主聊天模型名称
  base_url: "http://localhost:11434" # API 地址，部分 Provider 可为空
  api_key: "your-api-key"            # API Key，本地 Ollama 可为空
  thinking_enabled: null             # DeepSeek 专用；null 表示使用 Provider 默认值
  reasoning_effort: null             # DeepSeek 专用；null 表示默认 high，可选 high / max
  temperature: 0.7
  max_tokens: 4096
  timeout: 300
  use_proxy: false
```

### Embedding 配置

```yaml
embedding:
  provider: null        # null 表示默认复用 model.provider
  name: null            # 必填；不再默认使用 model.name，避免误用聊天模型
  base_url: null        # null 表示复用 model.base_url
  api_key: null         # null 表示复用 model.api_key
  dimensions: null      # OpenAI text-embedding-3-* 支持缩短维度
  encoding_format: null # OpenAI 支持 float / base64
  timeout: null         # null 表示复用 model.timeout
  use_proxy: null       # null 表示复用 model.use_proxy
```

当前语义记忆默认使用“话题感知存储 + LLM 打分 / 关键词”的轻量方案，不强制依赖向量数据库；`ModelClient.embeddings()` 提供统一 embedding 能力，供后续向量检索、推荐或外部存储集成使用。

### 思考引擎配置

```yaml
think_engine:
  enabled: true                       # 是否启用静默思考
  think_interval_minutes: 5           # 思考间隔（分钟）
  random_walk_steps_min: 2            # 随机游走最少步数
  random_walk_steps_max: 5            # 随机游走最多步数
  emotional_trigger_threshold: 0.5    # 优先选择高情感话题的阈值
  emotional_priority_probability: 0.7 # 优先选择高情感话题的概率
  think_temperature: 0.7              # 思考时的温度
  think_max_tokens: 200               # 思考最大 token 数
```

### 记忆系统配置

```yaml
memory:
  working_max_turns: 20              # 工作记忆最大轮数
  episodic_threshold: 50             # 触发情景记忆压缩的消息数
  episodic_keep_recent: 10           # 压缩时保留最近消息数
  semantic_enabled: true             # 是否启用语义记忆
  semantic_top_k: 5                  # 检索时返回的话题数
  semantic_similarity_threshold: 0.7 # 相关性阈值
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `GENSOKYOAI_PROVIDER` | 主模型 Provider | `ollama` |
| `GENSOKYOAI_MODEL` | 主模型名称 | `qwen3.5:9b` |
| `GENSOKYOAI_API_KEY` | 主模型 API 密钥 | - |
| `GENSOKYOAI_BASE_URL` | 主模型 API 地址 | - |
| `GENSOKYOAI_THINKING_ENABLED` | DeepSeek thinking mode 开关 | Provider 默认值 |
| `GENSOKYOAI_REASONING_EFFORT` | DeepSeek 推理强度 high / max | `high` |
| `GENSOKYOAI_EMBEDDING_PROVIDER` | Embedding Provider | 默认复用主模型 Provider |
| `GENSOKYOAI_EMBEDDING_MODEL` | Embedding 模型名称 | - |
| `GENSOKYOAI_EMBEDDING_API_KEY` | Embedding API 密钥 | 默认复用主模型 API Key |
| `GENSOKYOAI_EMBEDDING_BASE_URL` | Embedding API 地址 | 默认复用主模型 API 地址 |
| `GENSOKYOAI_EMBEDDING_DIMENSIONS` | Embedding 输出维度 | - |
| `GENSOKYOAI_EMBEDDING_ENCODING_FORMAT` | Embedding 编码格式 | - |
| `GENSOKYOAI_EMBEDDING_TIMEOUT` | Embedding 超时时间 | 默认复用主模型 timeout |
| `GENSOKYOAI_EMBEDDING_USE_PROXY` | Embedding 是否使用代理 | 默认复用主模型 use_proxy |
| `GENSOKYOAI_LOG_LEVEL` | 日志级别 | `INFO` |
| `GENSOKYOAI_LOG_CONSOLE` | 控制台日志开关 | `true` |
| `GENSOKYOAI_MEMORY_WORKING_TURNS` | 工作记忆最大轮数 | `20` |

## 🏗️ 项目结构

```text
GensokyoAI/
├── GensokyoAI/                 # 主包目录
│   ├── backends/               # 后端抽象与实现
│   ├── background/             # 后台任务系统
│   ├── commands/               # 命令系统
│   ├── core/                   # 核心模块
│   │   ├── agent/              # Agent、模型客户端、Provider、响应处理
│   │   │   ├── providers/      # Ollama / OpenAI / DeepSeek / OpenAI Responses / Claude / Gemini 等 Provider
│   │   │   ├── _impl.py        # Agent 主类
│   │   │   ├── model_client.py # LLM 客户端 Facade
│   │   │   └── types.py        # 统一响应、消息、工具调用类型
│   │   ├── config.py           # 配置管理（YAML + 环境变量）
│   │   ├── events.py           # 事件总线
│   │   └── exceptions.py       # 自定义异常
│   ├── memory/                 # 工作记忆、情景记忆、语义记忆
│   ├── session/                # 会话管理与持久化
│   ├── tools/                  # 工具注册、工具执行、内置工具
│   └── utils/                  # 工具函数
├── characters/                 # 角色配置文件
│   ├── example.yaml            # 角色模板
│   └── zh_cn/                  # 中文内置角色
├── config/
│   └── default.yaml            # 默认配置
├── tests/                      # 回归测试
├── main_v2.py                  # 入口文件
├── pyproject.toml              # 项目配置（UV）
├── requirements.txt            # pip 依赖列表
├── run_default_uv.cmd          # Windows UV 快速启动脚本
├── run_default_pip.cmd         # Windows pip 快速启动脚本
└── README.md
```

## 🔧 高级用法

### 编程方式使用

```python
import asyncio
from GensokyoAI.core.agent import Agent
from GensokyoAI.backends.console import ConsoleBackendBuilder

async def main():
    agent = Agent(character_file="characters/zh_cn/SaigyoujiYuyuko.yaml")
    backend = ConsoleBackendBuilder(agent).with_stream_mode(True).build()
    await backend.run_interactive()

asyncio.run(main())
```

### 注册自定义工具

```python
from GensokyoAI.tools.base import tool

@tool(description="获取幻想乡的天气")
async def get_gensokyo_weather(location: str = "博丽神社") -> str:
    """获取指定地点的天气"""
    return f"{location}今天天气晴朗，适合喝茶"
```

### 扩展自定义后端

```python
from GensokyoAI.backends.base import BaseBackend

class WebBackend(BaseBackend):
    async def start(self):
        # 启动 Web 服务器
        pass

    async def send(self, message: str) -> str:
        return await self.agent.send(message)

    async def stop(self):
        pass

    def set_stream_handler(self, handler):
        self._stream_handler = handler
```

### 注册自定义 LLM Provider

```python
from GensokyoAI.core.agent.providers import ProviderFactory, BaseProvider
from GensokyoAI.core.agent.types import UnifiedResponse, UnifiedMessage, StreamChunk

class MyProvider(BaseProvider):
    async def chat(self, model, messages, tools=None, options=None, **kwargs):
        return UnifiedResponse(
            message=UnifiedMessage(role="assistant", content="Hello!"),
            model=model,
        )

    async def chat_stream(self, model, messages, tools=None, options=None, **kwargs):
        yield StreamChunk(content="Hello!")

# 注册后即可在配置中使用 provider: "my_llm"
ProviderFactory.register("my_llm", MyProvider)
```

## 🧪 测试

```bash
python -m unittest tests.test_claude_provider_conversion tests.test_deepseek_provider tests.test_model_client_embeddings
python -m compileall GensokyoAI tests
```

当前测试覆盖 Claude 官方 `tool_use` / `tool_result` 格式转换、工具调用 ID 保留、extended thinking 预算约束，DeepSeek thinking mode 参数、`reasoning_content` 与工具调用聚合，以及独立 embedding Provider / 模型路由。

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

如果你：

- 写了新的角色配置文件，欢迎分享到 `characters/` 目录。
- 开发了新的后端（QQ、Discord、Telegram 等），欢迎 PR。
- 发现了 bug 或有功能建议，请提交 Issue。

## 📝 待办事项

- [x] 多 LLM Provider 支持（Ollama / OpenAI / DeepSeek / Claude / Gemini）
- [ ] WebUI 后端（Gradio / FastAPI）
- [ ] 多角色同时对话
- [ ] 语音输入 / 输出
- [ ] 更多内置工具

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- [Ollama](https://ollama.ai/) - 本地模型运行
- [OpenAI](https://openai.com/) - OpenAI API 及兼容生态
- [Anthropic](https://www.anthropic.com/) - Claude 系列模型
- [Google](https://ai.google.dev/) - Gemini 系列模型
- [Rich](https://github.com/Textualize/rich) - 终端美化
- [msgspec](https://github.com/jcrist/msgspec) - 高性能序列化
- [ayafileio](https://github.com/Patchouli-CN/ayafileio) - 高性能异步文件 I/O
- [上海爱丽丝幻乐团](http://www16.big.or.jp/~zun/) - 创造了幻想乡

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Patchouli-CN/GensokyoAI&type=Date)](https://star-history.com/#Patchouli-CN/GensokyoAI&Date)

---

**Made with ❤️ and 🍵 in Gensokyo**

*“只有华丽并不是魔法，弹幕最重要的是火力 DA⭐ZE！” —— 雾雨魔理沙*
