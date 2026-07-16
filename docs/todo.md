# GensokyoWorld 多角色功能 — 交接文档

> 给接手的 AI：本文件是**唯一入口**。先通读本文，再看 `docs/gsk-ai-mulit-character.md`（完整实施计划，含每阶段文件级细节与状态标注）。
> 两份文件都在 `docs/`，随仓库一起提交，clone 即可见。

## 0. 一句话现状

多角色 `GensokyoWorld` 分阶段实施中。**阶段 1a / 1b / 2.2 / 2.1 已完成、已验证全绿、已提交**。下一步从 **阶段 2.3** 继续。

- 基线：上一轮事件总线解耦 `4f2b0a2`；本次交接在其上新增数个 commit（代码 3 个 + 文档 1 个），用 `git log --oneline` 查看最新 HEAD。
- 当前测试：`448 passed`，ruff / ruff format / pyright 全过。
- 所有新代码都是**纯增量**：单角色模式行为零变化，旧测试全绿。

---

## 1. 硬性约束（务必遵守）

1. **不要 `git commit` / `git push`**。完成后只报告改动文件、验证结果、建议 commit message，由用户亲自提交。
2. 动手前先 `git status` 确认工作树；工作树干净时 `git pull --ff-only` 检查上游，有更新则先快进并重新核对接线点。无法 ff / 有冲突 / 有用户改动 → 停止并报告，不擅自 merge/reset/stash。
3. **逐阶段推进**：一次做一个可独立验证的阶段，跑完测试再进下一个。用户在意 token 成本，别一口气堆完多个阶段。
4. 每阶段完成后更新 `docs/gsk-ai-mulit-character.md` 里对应小节的状态标注。

---

## 2. 核心设计原则（贯穿全程，勿违背）

> 来自用户的关键决策，写进计划文档开头的「核心设计原则」小节，这里再强调一遍。

1. **Actor 与模式无关**（✅ 1a/1b 已落地）：同一个 `Agent` 既能独立跑，也能被 World 注入依赖当演员。这是唯一真正共享的东西。
2. **单角色永不为多角色机制付费**：单 actor 场景**不启用 Director**（导演对 1 个角色只能 continue/wait_user，白白多一次 LLM 往返、翻倍 token）、**不走 SharedTranscript/记忆投影**、**不进 World 状态机**。
3. **编排层做成共享抽象，而非两份拷贝**：单角色 Agent 是主循环、多角色 World 是主循环，但主动定时器/回合机制通过计划 §7 的 `DialogueLoop` 协议共享，不复制粘贴。
4. 已发布的 `agent.*` / `scene.*` / CLI / session 格式**保持不动**，World 是其**之上**的增量层。
5. **对话真相源是 Agent，不是 World（落法一，用户已决策）**：working memory / session / 语义记忆继续挂在 `Agent`；World 只叠加 SharedTranscript、WorldStage、记忆投影等多角色专属状态。**明确排除「落法二」**——不把对话数据模型搬进 World。World 记忆隔离靠给 Actor 的 `Agent` 注入 world 作用域记忆根实现（延续 1a 的 `AgentDependencies`），不搬记忆。

---

## 3. 已完成阶段（未提交，全绿）

### ✅ 阶段 1a — Actor 身份 + 共享 ModelClient 注入
- `GensokyoAI/core/agent/runtime_context.py`：新增 `AgentDependencies`（msgspec Struct，字段 `model_client / resource_gates / actor_id / world_id` 全可空）；`AgentRuntimeContext` 加 `actor_id`（默认 `SINGLE_ACTOR_ID`）/ `world_id`。
- `GensokyoAI/core/agent/composition.py`：`AgentComposition.__init__` 接受可选 `deps`；`build()` 中 `model_client` / `resource_gates` 优先复用注入实例，**EventBus 永远每 Actor 独立创建**；`actor_id` 默认取 `character_name`。
- `GensokyoAI/core/agent/_impl.py`：`Agent.__init__` 加 `dependencies` 参数并透传；暴露 `self.actor_id` / `self.world_id`。
- `GensokyoAI/core/agent/__init__.py`：导出 `AgentDependencies`。
- 测试：`tests/test_agent_composition.py`（两 Actor 共享 ModelClient 但 bus/session/scene 隔离等）。

### ✅ 阶段 1b — 工具并行安全 + 批量执行串/并行
- `GensokyoAI/tools/base.py`：`ToolDefinition` / `tool()` 装饰器加 `parallel_safe: bool = True`。
- `remember` / `update_memory` / `scene_switch` 标记 `parallel_safe=False`。
- `GensokyoAI/tools/executor.py`：`execute_batch()` 只读工具并发（gather）、写状态工具按调用顺序串行，结果按入参顺序对齐；`_is_parallel_safe()` 查注册表，外部/未知工具保守视为可并行。
- `GensokyoAI/tools/registry.py`：`register()` 支持 `parallel_safe`（并修复了原 `decorated.name` 潜伏 bug）。
- 测试：`tests/test_tool_context.py::ToolBatchParallelSafetyTests`。

### ✅ 阶段 2.2 — World 数据层（`GensokyoAI/world/`，纯数据无耦合）
- `types.py`：`DirectorAction` / `SpeakerKind`（StrEnum）、`TranscriptEntry`、`DirectorDecision`、`WorldStateSnapshot`、常量 `USER_OCCUPANT_ID = "__user__"`。
- `stage.py`：`WorldStage`（`move` / `move_together` / `scene_of` / `characters_in` / `visible_actor_ids`，`asyncio.Lock` 原子移动）。
- `transcript.py`：`SharedTranscript`（按 scene_id 分片，`add` / `history` / `render_for_scene` / `counts` / 按场景截断上限）。
- `__init__.py`：导出以上。
- 测试：`tests/test_world_data_layer.py`（11 例）。

### ✅ 阶段 2.1 — WorldConfig 配置链
- `config_schema.py`：`WorldActorConfig` / `WorldDirectorConfig` / `WorldTranscriptConfig` / `WorldPersistenceConfig` / `WorldConfig`；`AppConfig.world` 字段。
- `config_loader.py`：`_dict_to_world_config()` 展开 actors 列表与子节；`_WORLD_NESTED_KEYS`。
- `config_merge.py`：world 整节覆盖。
- `config_validator.py`：`_validate_world_data` + actor/director/transcript 子校验；`world` 加入 `_known_top_level_fields()`；文件顶部加了 `from pathlib import Path`。
- `config.py`：再导出 World 配置类。
- `config/default.yaml`：文档化 `world:` 节（`enabled: false`）。
- `config/world_example.yaml`：魔理沙 + 蕾米莉亚「红魔馆」双角色可运行示例（引用的角色卡真实存在）。
- 测试：`tests/test_world_config.py`（11 例）。

---

## 4. 待做阶段（从这里继续）

按计划 §9 顺序，逐阶段做、逐阶段验证。每阶段的**文件级细节在 `docs/gsk-ai-mulit-character.md` 对应小节**。

- **⏳ 2.3 — WorldPersistence + 按世界隔离的记忆命名空间**（下一步）
  - `core/schema_versions.py` 加 `WORLD_SESSION_SCHEMA_VERSION = 1`。
  - 新增 `world/persistence.py`：World 会话存 `sessions/worlds/<sanitized-world-id>/<world-session-id>.json`，复用 `GensokyoAI/utils/path_security.py::sanitize_path_id` + 原子写（参考 `session/persistence.py` 的 `_atomic_write_json` / `.bak` / 备份恢复 / quarantine 写法）。
  - create/list/resume/delete/export；保存 world metadata、stage locations、current actor、protagonist、按场景 transcript、director counters、World 主循环 initiative 状态。
  - **记忆命名空间**（落法一）：给 `AgentDependencies` 加记忆根注入（如 `memory_root` / `memory_namespace`）；`AgentComposition` / `SemanticMemoryManager` 用它，World 模式路径为 `memory/world_<world_id>/<character_name>/`，单角色保持现有 `sessions/<character>/memory/<session_id>`。**不要靠字符串拼接偷改 character_name**。注意：当前 `_impl.py::semantic_memory` property 里硬编码了 `self._memory_base_path / self.character_name / "memory" / session_id`，需改成走注入的记忆根。
- **⏳ 3 — Actor 的 world-turn 桥接**：`Agent.send_world_turn(_stream)`；trigger 文本不入私有 working memory（`record_in_working_memory=False`）；`MessageBuilder.build_continuation()` 保留本轮 world/system contexts。
- **⏳ 4 — Director**：`world/director.py`，复用共享 `ModelClient.chat()` + ThinkEngine 的 JSON schema/降级模式。严格校验 switch 目标在场、熔断 `max_auto_turns` / `max_same_actor_turns`、解析失败 → wait_user。
- **⏳ 5 — GensokyoWorld 主类与状态机**：`world/world.py` / `events.py` / `memory_projector.py` / `initiative.py`。开场（protagonist 是角色→主动开场；是 `__user__`→等用户）、用户回合、场景切换联动 WorldStage + 用户跟随。
- **⏳ 6 — 私有记忆投影**：`WorldMemoryProjector`，段落结束批量为在场角色各写各视角，失败降级不阻塞。
- **⏳ 7 — DialogueLoop 抽象**（去重关键）：`core/dialogue_loop.py` Protocol；`initiative_timer.py` 提取纯调度器依赖回调；`_impl.py` 单角色适配器 + `manage_initiative_timer: bool=True`（World Actor 设 false）；`world/initiative.py` World 主循环计划/触发。
- **⏳ 8 — 持久化恢复**：world bundle + actor session 关联 + export/delete/security。
- **⏳ 9 — Runtime / WebSocket / Console**：`world.*` RPC（init/start/send_message[_stream]/state/roster/transcript/move/session.*/shutdown）、流式 actor 事件、console `world_backend.py` + `--world` + `/world` `/roster` `/stage` `/transcript`。`RuntimeState` 加 `world: GensokyoWorld | None`。
- **⏳ 10 — 文档与完整验收**：README 中英、QUICKSTART、runtime_api、changelog/version、草案状态。

## 5. 关键陷阱（血泪，别踩）

- **多个 Agent 绝不能共享同一个 EventBus**：`ActionPlanner` / `CoreListeners` / `MetricsListeners` 都订阅 `MESSAGE_RECEIVED` 且无 actor 过滤，共享必串台。这是整个隔离架构的根基。共享的只有 ModelClient / resource_gates。
- **共享 ModelClient 的事件归属**：`ModelClient` 构造时绑定一个 `event_bus`，其 `MODEL_CALL_TIMING` / `MODEL_AUTH` 等会全汇到该 bus。多角色装配时应把共享 ModelClient 显式绑 **World bus**，Actor 私有 bus 不承载模型层事件。
- **工具事件总线按调用注入**：内置工具（memory/scene）经 `GensokyoAI/tools/tool_context.py` 的 `ContextVar` 读事件总线，`ToolExecutor.execute()` 里 `bind_tool_context(...)` 注入。若在 ToolExecutor 之外裸调用工具（如测试），必须 `with bind_event_bus(bus):` 或 `bind_tool_context(...)` 包裹，否则取不到总线。详见 `[[tool-event-bus-contextvar]]` 记忆与 `tools/tool_context.py` 顶部 docstring。
- **配置校验阶段不读文件/场景库**：actor character_file、scene id 的存在性留到初始化阶段返回结构化 diagnostics，别在 `config_validator` 里读盘。
- **msgspec Struct 字段顺序**：无默认值字段必须在有默认值字段之前。

## 6. 验证命令（每阶段必跑，对齐 CI）

```bash
uv run pytest -q                      # 全量测试，须全绿
uv run ruff check .                   # lint
uv run ruff format --check .          # 格式（不过就先 uv run ruff format .）
uv run pyright <改动的产品文件>        # 类型检查
```
项目也有 `./normalize_code.cmd`（ruff format + check + pyright + pytest 一条龙）。

## 7. 约定与风格

- 全中文 docstring / 注释，msgspec `Struct`，`field(default_factory=...)` 处理可变默认；enum 用 `StrEnum`（ruff UP042 会拦 `str, Enum`）。
- 目标 Python 3.14；行宽 100；ruff 规则 `E/F/I/UP/B/SIM`。
- 新增 world 相关代码放 `GensokyoAI/world/`；测试放 `tests/test_world_*.py`。
- 引用文件用真实存在的角色卡（`characters/zh_cn/` 下，注意没有 PatchouliKnowledge，用 RemiliaScarlet 等）。

## 8. 未提交改动清单（截至交接）

已改（M）：`core/agent/{__init__,_impl,composition,runtime_context}.py`、`core/config{,_loader,_merge,_schema,_validator}.py`、`tools/{base,executor,registry}.py`、`tools/tool_builtin/{memory_tool,scene}.py`、`tools/tool_context.py`、`config/default.yaml`、`tests/test_agent_composition.py`、`tests/test_tool_context.py`
新增（??）：`GensokyoAI/world/`、`config/world_example.yaml`、`tests/test_world_config.py`、`tests/test_world_data_layer.py`

建议提交拆分（供用户参考，AI 不要自己提交）：
1. `feat(agent): Actor 身份与共享 ModelClient 注入（阶段 1a）`
2. `feat(tools): 工具 parallel_safe 与批量串/并行执行（阶段 1b）`
3. `feat(world): World 数据层 WorldStage/SharedTranscript/类型（阶段 2.2）`
4. `feat(config): WorldConfig 配置链与校验、示例（阶段 2.1）`

