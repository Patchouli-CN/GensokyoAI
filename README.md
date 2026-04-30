<div align = center>
  <h1>🌸 GensokyoAI - 幻想乡 AI 角色扮演引擎</h1>
  
  [![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
  [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
  [![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
</div>

> 一个专为角色扮演设计的异步 AI 对话框架，支持 Ollama / OpenAI / DeepSeek / OpenAI Responses / Claude / Gemini 等多种 LLM Provider，提供三层记忆系统、会话管理、工具调用和可扩展后端。

[**使用指南**](./user_guide.md)  
[**项目设计**](./project_design.md)

## 交流讨论
**欢迎来提供功能建议、BUG 反馈以及纯粹交流ᗜᴗᗜ！**
- [QQ群: 675608356](https://qun.qq.com/universal-share/share?ac=1&authKey=2YjM%2FXyrxGTrkTDQMoxKM5QBzphCJzFxbXnKYDpF%2FVkmuNvH2%2BNaP2Z6l7d9LsB%2B&busi_data=eyJncm91cENvZGUiOiI2NzU2MDgzNTYiLCJ0b2tlbiI6IkROTnRsMVlMcWdPUzExZlp5T2RMbDI5eXBGRVNRcDV1blAxY2crWGhrUjdpaWVXSXoybE5CdFRSb3Q5Z3dCa0giLCJ1aW4iOiIyMjI2OTU2NTc5In0%3D&data=UBToZl_UF-gj5B9gKcj0YXcw7qCwC5DKmrw0Sh2-XNjTejEA31jAi1BONVOvh9v5PB98Y0f_Hz-MDvXiFrwnLA&svctype=4&tempid=h5_group_info) 

## ✨ 核心亮点

> 无需理解程序逻辑，也能快速知道 GensokyoAI 能带来什么体验。

### 真人般的对话体验

GensokyoAI 不是简单的问答机器人，而是围绕“角色扮演”设计的对话引擎。角色可以拥有稳定的人设、说话习惯、问候语和示例对话，在长期交流中更容易保持一致的性格与表达方式。

### 具有更真实的记忆

对话不会只停留在当前一句话。角色可以保留近期上下文，也能把长期交流压缩成记忆，并围绕话题建立联系；后续对话中，系统会尝试检索相关记忆，帮助角色更自然地想起过去内容。

记忆管理不是简单地“全部塞进上下文”。在启用工具调用且模型选择调用记忆工具时，角色可以根据对话内容主动记住或回忆信息，并借助话题和遗忘机制让记忆更像真实交流中的印象，而不是僵硬的记录本。

### 角色有自然活动

启用静默思考后，角色可以在空闲时回顾已有话题、整理思绪；当系统判断时机合适时，还可以主动开口。这让角色不只是被动回答，而更像拥有自己的内心世界。

### 更好的会话管理

支持创建、保存、恢复、列出和回滚会话。说错话可以撤回，历史会话可以继续，不同角色也可以分别维护自己的交流记录。

### 可选择不同模型服务

你可以按需求选择本地模型、OpenAI 兼容服务、DeepSeek、Claude 或 Gemini。想要本地免费运行、接入云端大模型，或混合使用不同服务，都可以通过配置完成。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

如果你：

- 写了新的角色配置文件，欢迎分享到 `characters/` 目录。
- 开发了新的后端（QQ、Discord、Telegram 等），欢迎 PR。
- 发现了 bug 或有功能建议，请提交 Issue。

## 待办事项

- [x] 多 LLM Provider 支持（Ollama / OpenAI / DeepSeek / Claude / Gemini）
- [ ] WebUI 后端（Gradio / FastAPI）
- [ ] 多角色同时对话
- [ ] 语音输入 / 输出
- [ ] 更多内置工具

## 许可证

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
