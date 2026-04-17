
# 🌸 GensokyoAI - 幻想乡 AI 角色扮演引擎

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 一个专为角色扮演设计的异步 AI 对话框架，提供完整的三层记忆系统、会话管理、工具调用和可扩展后端。让你与自己喜欢的角色进行深度、连贯的对话。

## ✨ QQ群：675608356

https://qun.qq.com/universal-share/share?ac=1&authKey=2YjM%2FXyrxGTrkTDQMoxKM5QBzphCJzFxbXnKYDpF%2FVkmuNvH2%2BNaP2Z6l7d9LsB%2B&busi_data=eyJncm91cENvZGUiOiI2NzU2MDgzNTYiLCJ0b2tlbiI6IkROTnRsMVlMcWdPUzExZlp5T2RMbDI5eXBGRVNRcDV1blAxY2crWGhrUjdpaWVXSXoybE5CdFRSb3Q5Z3dCa0giLCJ1aW4iOiIyMjI2OTU2NTc5In0%3D&data=UBToZl_UF-gj5B9gKcj0YXcw7qCwC5DKmrw0Sh2-XNjTejEA31jAi1BONVOvh9v5PB98Y0f_Hz-MDvXiFrwnLA&svctype=4&tempid=h5_group_info

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
| **语义记忆** | 长期知识存储和检索 | 向量检索 + 模型提取双模式，自动降级 |

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

### 🎛️ 智能命令系统
| 命令类型 | 示例 | 说明 |
|---------|------|------|
| **提示词标签** | `<know>内容</know>` | 动态注入参考资料 |
| | `<meta>内容</meta>` | 设定场景/元数据 |
| | `<attention>内容</attention>` | 提醒/纠正 AI |
| **系统命令** | `/help`, `/save`, `/new` | 控制程序行为 |
| **聊天命令** | `<think>`, `<whisper>` | 本地显示，不发给 AI |

### ⚡ 高性能异步架构
- 全异步设计，基于 `asyncio`
- 后台任务队列处理记忆和持久化
- 流式输出支持，打字机效果
- 优雅的信号处理和关闭流程

### 🔌 可扩展后端
- 抽象后端基类 `BaseBackend`
- 内置 Rich 美化的控制台后端
- 易于扩展为 WebUI、QQ 机器人、Discord Bot 等

## 📦 快速开始

### 环境要求
- Python 3.10+
- [Ollama](https://ollama.ai/) 运行中

### 安装

**方式一：使用 UV（推荐）**
[UV](https://docs.astral.sh/uv/) 是一个极速的 Python 包管理器。
1. 克隆仓库并进入目录：`git clone https://github.com/Patchouli-CN/GensokyoAI.git` 然后 `cd GensokyoAI`
2. 安装 UV：
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. 同步依赖：`uv sync`（UV 会自动创建虚拟环境并安装所有依赖）

**方式二：使用 pip**
1. 克隆仓库并进入目录：`git clone https://github.com/Patchouli-CN/GensokyoAI.git` 然后 `cd GensokyoAI`
2. 安装依赖：`pip install -r requirements.txt`

### 下载模型

- 对话模型：`ollama pull qwen3.5:9b`
- Embedding 模型：`ollama pull nomic-embed-text`（用于语义记忆）

> 💡 **提示：** 如果有自己享用的模型，可以去`config/default.yaml`里改配置文件。

### 创建角色

在 `characters/` 目录下创建你的角色文件，例如 `reimu.yaml`：

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

**使用 UV 启动（推荐）：**
- 新建会话：`uv run main_v2.py --character characters/reimu.yaml --new-session`
- 恢复会话：`uv run main_v2.py --character characters/reimu.yaml --resume <session_id>`
- 列出会话：`uv run main_v2.py --list-sessions`

**使用 Python 启动：**
- 新建会话：`python main_v2.py --character characters/reimu.yaml --new-session`
- 恢复会话：`python main_v2.py --character characters/reimu.yaml --resume <session_id>`
- 列出会话：`python main_v2.py --list-sessions`

> 💡 **提示：** Windows 用户也可以直接双击 `run_default.cmd`（pip 用户）或 `run_default_uv.cmd`（UV 用户）快速启动默认角色西行寺幽幽子。

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

### 聊天命令（仅本地显示，不会发送给 AI）
- `💭（内心独白内容）`：表达角色内心想法
- `<whisper>（小声）...</whisper>`：小声说话
- `<ooc>出戏内容</ooc>`：戏外交流
- `<describe>环境描写</describe>`：场景描述
- `<action>角色动作</action>`：动作描写

## 🏗️ 项目结构

```
GensokyoAI/
├── backends/           # 后端抽象与实现
│   ├── base.py         # 抽象基类
│   └── console.py      # Rich 控制台后端
├── core/               # 核心模块
│   ├── agent/          # Agent 实现
│   │   ├── _impl.py        # 主类
│   │   ├── lifecycle.py    # 生命周期管理
│   │   ├── model_client.py # 模型客户端
│   │   ├── message_builder.py # 消息构建
│   │   ├── response_handler.py # 响应处理
│   │   └── save_coordinator.py # 保存协调
│   ├── config.py       # 配置管理
│   ├── events.py       # 事件总线
│   └── exceptions.py   # 自定义异常
├── memory/             # 记忆系统
│   ├── working.py      # 工作记忆
│   ├── episodic.py     # 情景记忆
│   └── semantic.py     # 语义记忆（向量检索）
├── session/            # 会话管理
│   ├── manager.py      # 会话管理器
│   └── persistence.py  # 持久化
├── tools/              # 工具调用系统
│   ├── base.py         # 工具装饰器
│   ├── registry.py     # 工具注册中心
│   ├── executor.py     # 工具执行器
│   └── tool_builtin/   # 内置工具
│       ├── time.py
│       ├── moon.py
│       └── system.py
├── background/         # 后台任务系统
│   ├── manager.py      # 任务管理器
│   └── workers/        # 工作器
├── utils/              # 工具函数
├── characters/         # 角色配置文件
├── sessions/           # 会话存储目录
├── config/             # 应用配置
│   └── default.yaml
└── main_v2.py          # 入口文件
```

## 🔧 高级用法

### 编程方式使用

```python
import asyncio
from GensokyoAI import Agent, ConsoleBackendBuilder

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
def get_gensokyo_weather(location: str = "博丽神社") -> str:
    """获取指定地点的天气"""
    # 你的实现
    return f"{location}今天天气晴朗，适合喝茶"
```

### 扩展自定义后端

```python
from GensokyoAI.backends import BaseBackend

class WebBackend(BaseBackend):
    async def start(self):
        # 启动 Web 服务器
        pass
    
    async def send(self, message: str) -> str:
        # 处理 Web 请求
        return await self.agent.send(message)
    
    # ... 实现其他抽象方法
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
- [ ] 向量数据库支持（Chroma/Qdrant）
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

[![Star History Chart](https://api.star-history.com/svg?repos=Patchouyo-CN/GensokyoAI&type=Date)](https://star-history.com/#Patchouli-CN/GensokyoAI&Date)

---

**Made with ❤️ and 🍵 in Gensokyo**

*"只有华丽并不是魔法，弹幕最重要的是火力！" —— 雾雨魔理沙*
