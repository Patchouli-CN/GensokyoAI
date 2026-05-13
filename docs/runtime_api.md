# Runtime API 契约

本文档描述 GensokyoAI Runtime 对前端、桌面客户端、CLI 与第三方集成暴露的稳定 JSON RPC 契约。

## 版本与兼容性

- 当前协议版本：`1.1.0`
- 当前协议主版本：`1`
- 兼容性策略：同一主版本内可以新增字段和方法；删除字段、修改语义或改变错误结构需要进入 breaking changes。
- 客户端应优先调用 `runtime.info`，再根据 `protocol_version`、`capabilities`、`methods` 与 `legacy_methods` 决定可用功能。

## 发现接口

`runtime.info` 返回运行时元数据：

```json
{
  "name": "GensokyoAI Runtime",
  "package_version": "0.1.0",
  "protocol": "json-lines-rpc",
  "protocol_version": "1.1.0",
  "protocol_major_version": 1,
  "capabilities": ["agent.messaging", "config.validation", "character.validation", "character_package.management", "migration.diagnostics", "resource_control.runtime_gates", "runtime.events", "runtime.versioning"],
  "methods": ["runtime.info", "runtime.health", "config.validate", "character.validate", "character_package.validate", "character_package.preview", "character_package.import", "character_package.export"],
  "legacy_methods": ["init"],
  "schema_versions": {
    "config": 1,
    "session": 1,
    "memory": 1,
    "session_export": 1,
    "character_package": 1
  },
  "config_schema_version": 1,
  "deprecated_methods": [
    {
      "method": "init",
      "replacement": "agent.init",
      "remove_after": "2.0.0"
    }
  ],
  "breaking_changes": [],
  "deprecated_fields": [],
  "compatibility_notes": [
    {
      "scope": "runtime.rpc.legacy_methods",
      "status": "deprecated",
      "message": "Legacy non-namespaced RPC methods remain available for compatibility; new clients should use namespaced methods from runtime.info.methods.",
      "replacement": "Use runtime.info.method_specs to map legacy methods to namespaced replacements."
    }
  ],
  "migration_diagnostics": {
    "recent": [],
    "counts": {"migrated": 0, "skipped": 0, "failed": 0}
  },
  "resource_control": {
    "enabled": true,
    "categories": {"model": 2, "tool": 2, "web_search": 1, "image_generation": 1, "dependency_install": 1},
    "provider_max_concurrent": 2,
    "default_timeout_seconds": 120.0,
    "dependency_install_timeout_seconds": 600,
    "gates": {
      "runtime": {"max_concurrent": 4, "queue_size": 8, "active": 0, "waiting": 0}
    }
  }
}
```

## Runtime 版本与迁移诊断

`runtime.info` 会暴露 package version、Runtime 版本和 schema version 摘要：

- `package_version`：当前 GensokyoAI 包 / 项目版本；优先来自安装包 metadata，源码运行时回退读取 `pyproject.toml`。
- `protocol_version` / `protocol_major_version`：Runtime RPC 协议版本。
- `schema_versions.config`：配置 schema version。
- `schema_versions.session`：会话文件 schema version。
- `schema_versions.memory`：记忆 topic store schema version。
- `schema_versions.session_export`：会话导出包 schema version。
- `schema_versions.character_package`：角色包 schema version；当前 `.gensokyo-character` 格式为 `1`。
- `deprecated_methods`：已废弃 RPC 方法及替代方法。
- `deprecated_fields`：已废弃字段；当前为空数组。
- `compatibility_notes`：兼容性提示；当前包含 legacy 非命名空间 RPC 方法仍兼容但建议迁移到命名空间方法的说明。

`runtime.info.migration_diagnostics` 返回最近迁移摘要：

```json
{
  "recent": [
    {
      "source": "session",
      "status": "migrated",
      "from_schema_version": null,
      "to_schema_version": 1,
      "format": "gensokyoai.session.file",
      "path": "sessions/reimu/example.json",
      "backup_path": "sessions/reimu/example.json.bak",
      "message": "Session file migrated to current schema version.",
      "diagnostics": [],
      "migrated_at": "2026-05-11T00:00:00+00:00"
    }
  ],
  "counts": {"migrated": 1, "skipped": 0, "failed": 0}
}
```

迁移诊断字段说明：

- `source`：迁移来源，例如 `session` 或 `memory.topic_store`。
- `status`：迁移状态，当前会产生 `migrated` 和 `failed`；`skipped` 为预留计数。
- `from_schema_version` / `to_schema_version`：迁移前后 schema version；无版本旧格式为 `null`。
- `format`：迁移后的目标格式名。
- `path`：被迁移文件路径。
- `backup_path`：迁移前备份路径；memory topic store 当前没有备份时为 `null`。
- `message`：用户可读摘要。
- `diagnostics`：结构化诊断列表；失败时包含稳定 `code`、`severity`、`message` 和修复建议。
- `migrated_at`：迁移诊断记录时间。

## RPC 请求格式

HTTP `/rpc` 与 WebSocket 普通 RPC 使用相同请求格式：

```json
{
  "id": "request-1",
  "method": "runtime.health",
  "params": {}
}
```

- `id`：客户端自定义请求编号，可为字符串或数字。
- `method`：方法名，推荐使用带命名空间的新方法名。
- `params`：对象；没有参数时传 `{}` 或省略。

## 成功响应格式

```json
{
  "id": "request-1",
  "ok": true,
  "result": {}
}
```

## 错误响应格式

```json
{
  "id": "request-1",
  "ok": false,
  "error": {
    "code": "method_not_found",
    "error_code": "method_not_found",
    "message": "请求的 Runtime RPC 方法不存在。",
    "technical_message": "Unknown method: bad.method",
    "user_message": "请求的 Runtime RPC 方法不存在。",
    "recoverable": true,
    "action_hint": "请改用 runtime.info 返回的 methods 或 legacy_methods 中列出的方法。",
    "details": {}
  }
}
```

客户端应基于 `code` 或 `error_code` 做稳定分支，不要解析自然语言 `message`。

资源控制触发时会返回 `resource.limit_exceeded`：

```json
{
  "ok": false,
  "error_code": "resource.limit_exceeded",
  "error_object": {
    "code": "resource.limit_exceeded",
    "message": "Runtime 当前资源繁忙，请稍后重试。",
    "recoverable": true,
    "action_hint": "请稍后重试，或调大 resource_control 中对应并发 / 队列配置。",
    "details": {
      "resource": "runtime",
      "reason": "queue_full",
      "max_concurrent": 4,
      "queue_size": 8,
      "active": 4,
      "waiting": 8,
      "action": "agent_message"
    }
  }
}
```

## WebSocket 流式帧

`agent.send_message_stream` 会返回多帧：

```json
{
  "id": "stream-1",
  "ok": true,
  "stream": true,
  "stream_id": "...",
  "event": {"type": "content", "content": "..."},
  "done": false
}
```

结束帧：

```json
{
  "id": "stream-1",
  "ok": true,
  "stream": true,
  "stream_id": "...",
  "done": true,
  "result": {"role": "assistant", "content": "..."}
}
```

取消语义：

- 客户端可通过 WebSocket 发送 `runtime.cancel_stream`，参数为 `{"stream_id": "..."}`，Runtime 会取消对应的流式任务并尽量发送 `cancelled` 事件帧。
- 如果 WebSocket 连接直接断开，Runtime 会取消该连接上仍在运行的 stream task，并清理该连接创建的事件订阅。
- SSE `/events` 客户端断开或关闭响应时，Runtime 会关闭对应事件订阅；重复关闭客户端连接不会要求客户端再调用额外 RPC。
- HTTP `/rpc` 请求如果被客户端取消，底层请求协程会随连接取消而收敛；涉及 Runtime resource gate 的方法仍应依赖服务端 `finally` 路径释放资源。
- 多个 Runtime HTTP app / service 实例之间的 stream task、事件订阅、事件队列、shutdown 生命周期和资源状态相互隔离。

## 配置校验 API

`config.validate` 可在不初始化 Agent 的情况下校验配置文件、内联配置和 Runtime overrides：

```json
{
  "method": "config.validate",
  "params": {
    "config": {"model": {"provider": "openai", "temperature": 3}},
    "model_overrides": {"timeout": 60},
    "embedding_overrides": {"dimensions": 1536}
  }
}
```

返回字段：

- `ok`：是否没有 error 级诊断。
- `source`：`inline` 或 `file`。
- `config_path`：文件模式下的配置路径。
- `diagnostics`：每项包含 `code`、`path`、`severity`、`message` 和可选 `suggestion`。
- `error_count` / `warning_count`：错误和警告数量。

Provider 字段矩阵会区分两类兼容性诊断：

- `config.provider.field_discouraged`：字段通常不需要或只适合自定义网关场景，保持 warning。
- `config.provider.field_unsupported` / `config.provider.api_path_unsupported` / `config.provider.web_search_unsupported`：当前 Provider 明确不支持的字段或能力，返回 error。

## 角色校验 API

`character.validate` 可校验角色文件、角色名或内联角色数据：

```json
{
  "method": "character.validate",
  "params": {
    "character_data": {
      "name": "博丽灵梦",
      "system_prompt": "你是博丽灵梦。",
      "greeting": "你好。",
      "example_dialogue": [{"user": "你好", "assistant": "你好呀。"}]
    }
  }
}
```

返回字段：

- `ok`：是否没有 error 级诊断。
- `source`：`inline` 或 `file`。
- `character_path`：文件模式下的角色路径。
- `preview`：角色名、人设长度、示例数量和 metadata 预览。
- `diagnostics` / `error_count` / `warning_count`：结构化诊断信息。

`character.list` 条目也会包含 `ok`、`preview` 和 `diagnostics`，便于客户端在列表中展示坏角色文件。

## 角色包 API

角色包使用 `.gensokyo-character` 扩展名，本质为安全受限的 zip 包，根目录必须包含 `manifest.yaml`，当前格式名为 `gensokyoai.character.package`，schema version 为 `1`。P3 生态规范扩展后，manifest 支持来源、作者主页、许可证链接、引用来源、外部链接、仓库索引元数据、可选签名字段和 `checksums.sha256`。

`character_package.validate` 校验角色包结构、manifest、包内路径安全、文件大小、角色 YAML、资源路径、生态字段、外部链接 URL scheme 和 checksum：

```json
{
  "method": "character_package.validate",
  "params": {"package_path": "packages/reimu.gensokyo-character"}
}
```

`character_package.preview` 返回同一套 diagnostics，并额外面向 UI 使用 manifest 摘要、角色 preview、文件列表、`trust` 和 `security` 摘要。

`character_package.import` 将角色包导入 `characters` 目录：

```json
{
  "method": "character_package.import",
  "params": {
    "package_path": "packages/reimu.gensokyo-character",
    "locale": "zh_cn",
    "overwrite": false
  }
}
```

`character_package.export` 从已有角色 YAML 生成角色包：

```json
{
  "method": "character_package.export",
  "params": {
    "character_path": "characters/zh_cn/HakureiReimu.yaml",
    "output_path": "packages/reimu.gensokyo-character",
    "package_id": "HakureiReimu",
    "author": "GensokyoAI",
    "license": "MIT",
    "source": "https://example.com/packages/reimu",
    "license_url": "https://opensource.org/license/mit",
    "external_links": [{"label": "发布页", "url": "https://example.com/packages/reimu", "purpose": "source"}],
    "repository": {"id": "touhou/reimu", "url": "https://example.com/index.json"},
    "signature": {"algorithm": "ed25519", "value": "base64-like-signature-value"},
    "assets": [],
    "overwrite": false
  }
}
```

角色包 API 返回字段：

- `ok`：是否没有 error 级诊断。
- `format` / `schema_version`：角色包格式和 schema version。
- `manifest`：包 ID、名称、版本、作者、许可证、来源、外部链接、签名、checksum、角色入口、资源列表等摘要。
- `preview`：复用角色 YAML 校验预览结构。
- `files`：包内文件路径和大小。
- `trust`：信任元数据摘要，包括作者、来源、许可证、签名、checksum 是否声明，以及外部链接数量。
- `security`：安全摘要，包括外部链接是否均为 `https`、checksum 是否有效、是否存在未声明文件、签名校验级别和声明资源数量。
- `diagnostics` / `error_count` / `warning_count`：结构化诊断信息。
- `imported` / `target_path`：导入结果字段。

生态字段诊断规则：

- `author`、`license`、`source`、`signature`、`checksums` 缺失为 warning，便于客户端导入前展示信任提示。
- `source`、`author_url`、`license_url`、`external_links[].url`、`repository.url`、`repository.homepage`、`repository.download_url` 仅允许 `https` URL；非 `https` 为 error。
- `signature` 当前只做字段格式校验，支持识别 `ed25519`、`rsa-pss-sha256` 和 `minisign`，不做真实加密验签；返回的 `security.signature_verification` 固定为 `format_only`。
- `checksums.sha256` 会对包内文件执行 SHA-256 校验；哈希格式错误、目标缺失或内容不匹配为 error。
- `assets` 中声明的资源必须存在；包内除 `manifest.yaml`、`character` 和 `assets` 声明外的额外文件会产生 `character_package.security.undeclared_file` warning。

## 资源控制

Runtime 资源控制由配置段 `resource_control` 控制。当前 Runtime gate 覆盖入口级与深层执行侧：

- `runtime`：Runtime 高成本入口总并发。
- `agent_message`：当前 Runtime 会话消息并发。
- `stream`：流式消息并发。
- `provider`：ModelClient / Provider 调用链总并发。
- `model`：模型调用并发，覆盖 chat、chat_stream、embeddings 和 image_generation。
- `tool`：ToolExecutor 内置工具与外部工具执行并发。
- `web_search`：`web_search` 工具执行并发。
- `image_generation`：图片生成执行并发。
- `dependency_install`：可选依赖安装并发。

`runtime.info.resource_control` 会返回当前配置摘要和 gate 快照。深层 Provider / 工具调用限流与入口级 gate 使用同一套 `resource.limit_exceeded` 错误结构，错误 details 会包含 `resource`、`reason`、`max_concurrent`、`queue_size`、`active`、`waiting` 和 `action`，便于客户端展示恢复建议。

## 会话导出与 schema version

`session.export` 返回机器可读会话包，包含：

- `format`：当前为 `gensokyoai.session.export`。
- `version`：保留的兼容字段。
- `schema_version`：导出包 schema version。
- `session_schema_version`：会话文件 schema version。
- `memory_schema_version`：记忆 topic store schema version。
- `session` / `messages` / `message_count`：会话元信息与消息内容。
- `runtime`：导出时 Runtime 的基本路径和启动状态。

## 事件订阅

SSE `/events` 会推送 Runtime 事件。事件字段会经过敏感信息清洗，`api_key`、`authorization`、`token`、`password` 等字段会替换为 `[redacted]`。

## 记忆管理 API

`memory.list` 列出当前会话语义记忆：

```json
{
  "method": "memory.list",
  "params": {"topic_name": "偏好", "limit": 50, "offset": 0}
}
```

返回包含 `items`、`total`、`limit`、`offset`。每条记忆包含 `id`、`content`、`importance`、`topic`、`topic_name`、`tags`、`memory_type`、`timestamp`。

`memory.search` 搜索当前会话语义记忆：

```json
{
  "method": "memory.search",
  "params": {"query": "喝茶", "top_k": 5, "threshold": 0.7, "include_embedding": true}
}
```

返回每条结果的 `score`、`keyword_score`、可选 `embedding_score`、`matched_by` 与 `diagnostics`。当 embedding provider 未配置、不可用或调用失败时，Runtime 会自动降级到关键词 / 话题检索，并在 `diagnostics.embedding_fallback` 和 `diagnostics.embedding_error` 中说明原因。

`memory.get`、`memory.update`、`memory.delete` 分别按 `memory_id` 读取、更新和删除当前会话语义记忆。`memory.update` 支持更新 `content`、`importance`、`tags`。

`memory.graph` 返回当前会话话题图：

```json
{
  "nodes": [{"id": "topic-1", "name": "偏好", "recall_weight": 0.8}],
  "edges": [],
  "topic_count": 1,
  "edge_count": 0
}
```

## 方法元数据

机器可读方法元数据由代码中的 RPC registry 生成，包含：

- `method`
- `handler`
- `legacy`
- `namespace`
- `deprecated`
- `replacement`
- `remove_after`
