# 使用指南

## 快速开始

### 1. 环境

- Python 3.10+
- 以下任一 LLM 后端：
  - [Ollama](https://ollama.ai/) 本地运行（默认，免费）
  - OpenAI API Key，或 SiliconFlow 等云端服务
  - DeepSeek API Key
  - Anthropic Claude API Key
  - Google Gemini API Key

### 2. 安装

#### 拉取源代码
```bash
git clone https://github.com/Patchouli-CN/GensokyoAI.git
cd GensokyoAI
```

#### 方式一：使用 UV（推荐）

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

> DeepSeek 虽然兼容 OpenAI SDK，但 thinking mode 下发生工具调用后，后续请求需要回传 `reasoning_content`。因此推荐使用独立的 `deepseek` Provider，而不是把 DeepSeek 配到通用 `openai` Provider 下。

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
> 如果主聊天模型使用 Claude，也需要把 embedding 配到 OpenAI / Gemini / Ollama 或其他兼容 Provider。Anthropic 官方不提供 Claude 自家的 embeddings。

```yaml
embedding:
  provider: "openai"                 # 可省略，默认使用 model.provider
  name: "text-embedding-3-small"     # 必填：不要填写聊天模型
  api_key: "sk-..."                  # 可省略，默认使用 model.api_key
  base_url: null                     # 可省略，默认使用 model.base_url
  dimensions: 1024                   # 可选，仅部分模型支持
  encoding_format: "float"           # 可选：float / base64
```

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

## 命令行参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--character` | `-c` | 角色配置文件路径 |
| `--config` |  | 应用配置文件路径，默认 `config/default.yaml` |
| `--new-session` |  | 创建新会话 |
| `--resume` |  | 恢复指定 ID 的会话 |
| `--list-sessions` |  | 列出所有历史会话 |
| `--no-stream` |  | 禁用流式输出 |

## 对话中的命令

### 提示词标签（传递给 AI）

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

## 配置说明

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

### 静默调试输出

默认情况下，静默思考、主动说话决策理由、模型推理内容等内部信息会被隐藏，避免内心独白或推理内容污染正常对话与工作记忆。调试时可以统一开关。
可以通过配置文件开启：

```yaml
debug_silent_output: true
```

或环境变量开启：

```bash
GENSOKYOAI_DEBUG_SILENT_OUTPUT=true
```

开启后会显示 / 记录静默思考摘要、主动发言决策细节，并允许 `reasoning_content` 写入调试事件；通常情况建议保持该项为 `false`。

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
| `GENSOKYOAI_DEBUG_SILENT_OUTPUT` | 是否输出静默思考、主动决策理由和推理内容等调试信息 | `false` |
| `GENSOKYOAI_LOG_CONSOLE` | 控制台日志开关 | `true` |
| `GENSOKYOAI_MEMORY_WORKING_TURNS` | 工作记忆最大轮数 | `20` |

## 高级用法

### 程序调用

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

## 测试

```bash
python -m unittest tests.test_claude_provider_conversion tests.test_deepseek_provider tests.test_model_client_embeddings
python -m compileall GensokyoAI tests
```

当前测试覆盖 Claude 官方 `tool_use` / `tool_result` 格式转换、工具调用 ID 保留、extended thinking 预算约束，DeepSeek thinking mode 参数、`reasoning_content` 与工具调用聚合，以及独立 embedding Provider / 模型路由。