
# 🌸 GensokyoAI - 幻想乡 AI 角色扮演引擎

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 一个专为角色扮演设计的异步 AI 对话框架，提供完整的三层记忆系统、会话管理、工具调用和可扩展后端。让你与自己喜欢的角色进行深度、连贯的对话。

## 🐧 QQ群：675608356
- **欢迎来提供功能建议、BUG反馈以及纯粹交流ᗜᴗᗜ！**
- **邀请链接** - https://qun.qq.com/universal-share/share?ac=1&authKey=2YjM%2FXyrxGTrkTDQMoxKM5QBzphCJzFxbXnKYDpF%2FVkmuNvH2%2BNaP2Z6l7d9LsB%2B&busi_data=eyJncm91cENvZGUiOiI2NzU2MDgzNTYiLCJ0b2tlbiI6IkROTnRsMVlMcWdPUzExZlp5T2RMbDI5eXBGRVNRcDV1blAxY2crWGhrUjdpaWVXSXoybE5CdFRSb3Q5Z3dCa0giLCJ1aW4iOiIyMjI2OTU2NTc5In0%3D&data=UBToZl_UF-gj5B9gKcj0YXcw7qCwC5DKmrw0Sh2-XNjTejEA31jAi1BONVOvh9v5PB98Y0f_Hz-MDvXiFrwnLA&svctype=4&tempid=h5_group_info

## ✨ 核心特性

### 🎭 为角色扮演而生
- **YAML 角色配置** - 简单易懂的角色定义文件
- **系统提示词模板** - 支持示例对话，快速塑造角色性格
- **角色一致性维护** - 三层记忆系统确保角色不"出戏"

### 🧠 三层记忆系统
| 记忆类型 | 作用 | 实现方式 |
|---------|------|---------|
| **工作记忆** | 当前会话的完整对话 | 滑动窗口，保留最近 N 轮 |
| **情景记忆** | 历史对话的压缩摘要 | 模型自动摘要，关键事件提取 |
| **语义记忆** | 长期知识存储和检索 | 🆕 独创的话题感知存储，无需向量数据库 |

### 🛠️ 自主记忆工具
角色可以主动管理自己的记忆：
- **`remember` 工具** - AI 自主判断何时记住重要信息
- **`recall` 工具** - AI 需要时主动检索相关记忆
- **话题感知存储** - 自动将记忆归类到话题，建立关联图谱

> 💡 **设计哲学**：记忆管理完全交给 AI 自主决策，不做任何自动规则。因为最懂角色需要记住什么的，正是扮演它的 LLM 本身。

### 💬 强大的会话管理
- ✅ 创建、保存、恢复、列出会话
- ✅ 自动持久化，支持异步 I/O
- ✅ 会话回滚（说错话可以撤回）
- ✅ 会话切换（和不同角色聊天无缝切换）

### 🔧 工具调用
内置工具，让角色拥有"超能力"：
- `get_current_time` - 获取当前时间
- `get_current_dateinfo` - 获取日期和曜日（七曜日！）
- `get_moon_phase` - 获取月相
- `get_system_info` - 系统信息
- `remember` / `recall` - 自主记忆管理

### 🎛️ 智能命令系统
| 命令类型 | 示例 | 说明 |
|---------|------|------|
| **提示词标签** | `<know>内容</know>` | 动态注入参考资料 |
| | `<meta>内容</meta>` | 设定场景/元数据 |
| | `<attention>内容</attention>` | 提醒/纠正 AI |
| **系统命令** | `/help`, `/save`, `/new` | 控制程序行为 |
| **聊天命令** | `<think>`, `<whisper>` | 本地显示，不发给 AI |

### ⚡ 事件驱动架构
- 全异步设计，基于 `asyncio`
- **事件总线**解耦所有组件，易于扩展
- 后台任务队列处理持久化
- 流式输出支持，打字机效果
- 优雅的信号处理和关闭流程

### 🔌 可扩展后端
- 抽象后端基类 `BaseBackend`
- 内置 Rich 美化的控制台后端
- 命令系统与后端解耦，易于扩展为 WebUI、QQ 机器人、Discord Bot 等

## 📦 快速开始

### 环境要求
- Python 3.10+
- [Ollama](https://ollama.ai/) 运行中

### 安装

**方式一：使用 UV（推荐）**
[UV](https://docs.astral.sh/uv/) 是一个极速的 Python 包管理器。
```bash
git clone https://github.com/Patchouli-CN/GensokyoAI.git
cd GensokyoAI
uv sync
```

**方式二：使用 pip**
```bash
git clone https://github.com/Patchouli-CN/GensokyoAI.git
cd GensokyoAI
pip install -r requirements.txt
```

### 下载模型

```bash
# 对话模型（必选）
ollama pull qwen3.5:9b
```

> 💡 **提示：** 可以在 `config/default.yaml` 里修改模型配置。

### 创建角色

在 `characters/` 目录，或者任意你喜欢的地方创建角色文件，例如 `reimu.yaml`：

```yaml
name: "博丽灵梦"
system_prompt: |
  你是博丽灵梦，幻想乡博丽神社的巫女...
  
greeting: "「哟，又是你啊。要喝茶吗？」"

example_dialogue:
  - user: "灵梦，你今天在做什么？"
    assistant: "「当然是——在神社喝茶啊，还能做什么。」"
```

### 启动对话

```bash
# 新建会话
uv run main_v2.py --character characters/reimu.yaml --new-session

# 恢复会话
uv run main_v2.py --character characters/reimu.yaml --resume <session_id>

# 列出所有会话
uv run main_v2.py --list-sessions
```

> 💡 **提示：** Windows 用户可以直接双击 `run_default_uv.cmd` 快速启动默认角色（西行寺幽幽子）。

## 🎮 命令行参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--character` | `-c` | 角色配置文件路径 |
| `--config` | - | 应用配置文件路径（默认 `config/default.yaml`） |
| `--new-session` | - | 创建新会话 |
| `--resume` | - | 恢复指定 ID 的会话 |
| `--list-sessions` | - | 列出所有历史会话 |
| `--no-stream` | - | 禁用流式输出 |

## 🎨 对话中的命令

### 提示词标签（会传递给 AI）
- `<know>幻想乡位于日本...</know>`：动态注入参考资料
- `<meta>当前场景：博丽神社...</meta>`：设定场景/元数据
- `<attention>记住，你现在很困...</attention>`：提醒/纠正 AI 行为

### 系统命令
- `/help`：显示帮助
- `/exit` 或 `/quit`：退出程序
- `/save`：保存当前会话
- `/new`：创建新会话
- `/back`：回滚上一轮对话
- `/sessions`：列出历史会话
- `/stream on/off`：切换流式输出
- `/clear`：清空提示词上下文
- `/errors`：查看最近错误统计

### 聊天命令（仅本地显示，不发送给 AI）
- `<think>内心独白</think>`：表达角色内心想法
- `<whisper>悄悄话</whisper>`：小声说话
- `<ooc>出戏内容</ooc>`：戏外交流
- `<describe>环境描写</describe>`：场景描述
- `<action>角色动作</action>`：动作描写

## 🏗️ 项目结构

```
GensokyoAI/
├── GensokyoAI/                # 主包目录
│   ├── backends/              # 后端抽象与实现
│   │   ├── base.py            # 抽象基类 BaseBackend
│   │   └── console/           # Rich 控制台后端
│   │       ├── _impl.py       # ConsoleBackend 实现
│   │       └── commands.py    # 内置命令处理器
│   │
│   ├── core/                  # 核心模块
│   │   ├── agent/             # Agent 实现
│   │   │   ├── _impl.py       # Agent 主类
│   │   │   ├── lifecycle.py   # 生命周期管理（信号处理）
│   │   │   ├── model_client.py # Ollama 异步客户端
│   │   │   ├── message_builder.py # 消息构建器
│   │   │   ├── response_handler.py # 响应处理器（工具调用）
│   │   │   └── save_coordinator.py # 保存协调器（去重）
│   │   ├── config.py          # 配置管理（YAML + 环境变量）
│   │   ├── events.py          # 事件总线（发布/订阅）
│   │   ├── event_listeners.py # 核心事件监听器
│   │   └── exceptions.py      # 自定义异常
│   │
│   ├── memory/                # 记忆系统
│   │   ├── working.py         # 工作记忆（当前对话）
│   │   ├── episodic.py        # 情景记忆（历史摘要）
│   │   ├── semantic.py        # 语义记忆管理器
│   │   ├── topic_store.py     # 🆕 话题感知存储（核心）
│   │   └── types.py           # 记忆数据类型
│   │
│   ├── session/               # 会话管理
│   │   ├── manager.py         # 会话管理器
│   │   ├── persistence.py     # 异步持久化
│   │   └── context.py         # 会话上下文
│   │
│   ├── commands/              # 命令系统（与后端解耦）
│   │   ├── parser.py          # 命令解析器（标签/前缀）
│   │   ├── executor.py        # 命令执行器
│   │   ├── decorators.py      # @command 装饰器
│   │   ├── context.py         # 命令上下文
│   │   └── result.py          # 命令执行结果
│   │
│   ├── tools/                 # 工具调用系统
│   │   ├── base.py            # @tool 装饰器
│   │   ├── registry.py        # 工具注册中心
│   │   ├── executor.py        # 工具执行器
│   │   └── tool_builtin/      # 内置工具
│   │       ├── time.py        # 时间/日期工具
│   │       ├── moon.py        # 月相工具
│   │       ├── system.py      # 系统信息工具
│   │       └── memory_tool.py # 🆕 自主记忆工具
│   │
│   ├── background/            # 后台任务系统
│   │   ├── manager.py         # 任务管理器（队列+工作器）
│   │   ├── types.py           # 任务数据类型
│   │   └── workers/           # 工作器实现
│   │       ├── base.py        # 工作器基类
│   │       └── persistence_worker.py # 持久化工作器
│   │
│   └── utils/                 # 工具函数
│       ├── logging.py         # 日志配置
│       ├── formatters.py      # 格式化工具
│       ├── helpers.py         # 通用辅助函数
│       └── exec_hook.py       # 异常堆栈美化
│
├── characters/                # 角色配置文件
│   ├── example.yaml           # 角色模板
│   ├── marisa.yaml            # 雾雨魔理沙
│   └── yuyuko.yaml            # 西行寺幽幽子
│
├── config/                    # 应用配置
│   └── default.yaml           # 默认配置
│
├── sessions/                  # 会话存储目录（自动生成）
│   └── {角色名}/               # 按角色分类
│       ├── {session_id}.json  # 会话数据
│       └── memory/            # 记忆数据
│           └── {session_id}/
│               └── topics.json # 话题和记忆
│
├── main_v2.py                 # 入口文件
├── pyproject.toml             # 项目配置（UV）
├── requirements.txt           # 依赖列表
└── README.md                  # 本文档
```

## 🔧 高级用法

### 编程方式使用

```python
import asyncio
from GensokyoAI.core.agent import Agent
from GensokyoAI.backends.console import ConsoleBackendBuilder

async def main():
    # 创建 Agent
    agent = Agent(character_file="characters/yuyuko.yaml")
    
    # 构建控制台后端
    backend = ConsoleBackendBuilder(agent)\
        .with_stream_mode(True)\
        .build()
    
    # 运行交互式对话
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

## 🌍 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `GENSOKYOAI_MODEL` | 覆盖模型名称 | `qwen3.5:9b` |
| `GENSOKYOAI_LOG_LEVEL` | 日志级别 | `INFO` |
| `GENSOKYOAI_LOG_CONSOLE` | 控制台日志开关 | `true` |
| `GENSOKYOAI_MEMORY_WORKING_TURNS` | 工作记忆最大轮数 | `20` |

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

如果你：
- 写了新的角色配置文件，欢迎分享到 `characters/` 目录
- 开发了新的后端（QQ、Discord、Telegram 等），欢迎 PR
- 发现了 bug 或有功能建议，请提交 Issue

## 📝 待办事项

- [ ] WebUI 后端（Gradio/FastAPI）
- [ ] 多角色同时对话
- [ ] 语音输入/输出
- [ ] 更多内置工具

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [Ollama](https://ollama.ai/) - 本地模型运行
- [Rich](https://github.com/Textualize/rich) - 终端美化
- [Loguru](https://github.com/Delgan/loguru) - 优雅的日志
- [msgspec](https://github.com/jcrist/msgspec) - 高性能序列化
- [上海爱丽丝幻乐团](http://www16.big.or.jp/~zun/) - 创造了幻想乡

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Patchouli-CN/GensokyoAI&type=Date)](https://star-history.com/#Patchouli-CN/GensokyoAI&Date)

---

**Made with ❤️ and 🍵 in Gensokyo**

*"只有华丽并不是魔法，弹幕最重要的是火力DA⭐ZE！" —— 雾雨魔理沙*
