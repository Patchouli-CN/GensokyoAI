# GensokyoAI Changelog Template

> Positioning: this changelog is publicly released for ordinary users, client developers, and integrators.
>
> Writing principle: explain user-perceivable changes first, then supplement developer compatibility, migration, and protocol information. Ordinary users should be able to understand "what changes after upgrading, whether old data is affected, and whether manual action is needed."

## Version Number Rules

For version format, where to use `v` and where not, and the difference between Runtime protocol version and schema version, see [`versioning.md`](versioning.md).

Brief rules:

- Public versions and changelog use `vYYYY.M.D.N`; the first version is `v2026.5.13.0`.
- Package version in [`pyproject.toml`](../pyproject.toml) has no `v`; the first version is `2026.5.13.0`.
- Runtime protocol version uses independent semantic versioning without `v`; the first version is `1.0.0`; client compatibility prioritizes `protocol_major_version`.
- Schema versions continue to use integers, e.g. `1`, `2`, `3`.

## Usage

Each time a new version is released, copy the version template below, place it at the top of this file, and delete or write "None" for unused sections.

Each change entry should ideally include:

- What changed.
- Impact on ordinary users.
- Whether manual action is needed.
- Whether old config, old sessions, old memory, character files, or client integration are affected.
- Whether Runtime methods, capabilities, response fields, error structures, or schema versions changed.
- Whether deprecated, removal_pending, removed, or breaking changes are involved; if so, alternatives and migration methods must be given.

---

## Version Template

```markdown
# GensokyoAI vYYYY.M.D.N Changelog

Release date: YYYY-MM-DD

## One-Sentence Summary

Use one or two sentences to explain the most important changes in this version, so ordinary users can quickly judge whether to upgrade.

## New Features

- New: explain the new capability.
  - User impact: explain what new things users can do.
  - Action needed: explain whether config changes, restart, or dependency reinstallation are needed.

## Behavior Changes

- Change: explain behavior changes of existing features.
  - User impact: explain how the experience differs after upgrade.
  - Compatibility: explain whether old usage still works; if a warning is tightened to an error, specify affected configs.
  - Client impact: explain whether Runtime response fields, error codes, capabilities, or method lists changed.

## Bug Fixes

- Fix: explain the fixed issue.
  - Affected scenarios: explain which users may have encountered it.
  - Upgrade recommendation: explain whether affected users are recommended to upgrade.

## Deprecated but Still Compatible

- Deprecated: explain config, fields, RPC methods, or file formats that are not recommended for continued use.
  - Deprecated object: write the full path or method name, e.g. `runtime.info.old_field` or `legacy_method`.
  - Effective version: write version without `v`, e.g. `2026.5.11.0`.
  - Alternative: explain what to use instead; if no alternative, explain why.
  - Planned removal: explain `remove_after`; write "undetermined" if unknown.
  - Runtime declaration: explain whether it has been written into `runtime.info.deprecated_methods` or `runtime.info.deprecated_fields`.

## Removed or Breaking Changes

- Removal: explain capabilities no longer supported.
  - Scope: explain which users or clients are affected.
  - Breaking level: explain whether `RUNTIME_PROTOCOL_MAJOR_VERSION` or schema version needs to be incremented.
  - Migration: explain how to change config, calling methods, or migrate data.
  - Runtime declaration: explain whether it has been written into `runtime.info.breaking_changes`.

## Data Migration and Upgrade Notes

- Data migration: explain whether this version will migrate sessions, memory, config, or character packages.
  - Automatic migration: explain what the program will handle automatically.
  - Backup location: explain where backup files or export packages are.
  - Failure handling: explain where users should look and how to recover if migration fails.

## Installation and Dependency Changes

- Dependency changes: explain whether Python version, pip / uv installation, Provider SDK, Ollama, or system dependencies changed.
  - Ordinary user action: explain whether dependencies need to be reinstalled.
  - Windows user reminder: explain script, path, or permission issues here if involved.

## Runtime / Client Compatibility

- Runtime protocol version: YYYY.M.D.N
- Runtime protocol major: 1
- Supported clients: explain recommended client versions or minimum compatible versions.
- Method changes: list added, deprecated, or removed methods; write "None" if no changes.
- Capability changes: list added, deprecated, or removed capabilities; write "None" if no changes.
- Response field changes: list changes to public response fields such as `runtime.info`, config diagnostics, sessions, memory; write "None" if no changes.
- Deprecated methods / fields: list deprecated methods or fields and explain alternatives; write "None" if no changes.
- Compatibility notes: list compatibility concerns for clients; write "None" if no changes.
- Breaking changes: list breaking changes; write "None" if no changes.

## Schema Versions

| Type | Version | Note |
| --- | --- | --- |
| config schema | 1 | Config file format version |
| session schema | 1 | Session file format version |
| memory schema | 1 | Memory storage format version |
| session export schema | 1 | Session export package format version |
| character package schema | TBD | Character package format version |

## Known Issues

- Issue: explain current known limitations in this version.
  - Workaround: explain how users can bypass it.
  - Future plan: explain which direction it will be handled in later.

## Supplementary Notes for Developers

- Code-level changes: briefly explain important module or API changes.
- Test results: explain whether key tests passed; it is recommended to list actually executed test commands.
- Documentation updates: list documents that need to be read in sync.
- Pre-release checks: confirm that the pre-release checklist in [`versioning.md`](versioning.md) has been completed.
```

---

## Current Project Version Record Starting Point

Official release records start continuous recording from `v2026.5.13.0`. This file is used as a template; specific version records are in the `docs/changelog/` directory:

- [`v2026.5.13.0.md`](../changelog/v2026.5.13.0.md): first public Alpha release.
- [`v2026.6.21.0.md`](../changelog/v2026.6.21.0.md): HTTP/WebSocket entry migration, default search switched to DuckDuckGo, initiative timer prompt optimization.
