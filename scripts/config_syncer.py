#!/usr/bin/env python3
"""将 default.yaml 的新增字段/block 同步到本地配置文件中。

仅添加目标文件中不存在的键，已设置的键值不做任何修改。
嵌套 dict 递归处理，列表/标量按整体判断。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def deep_merge(source: dict, target: dict) -> dict:
    """递归补全 target 中缺失的 source 键，保留 target 已有值。"""
    result = dict(target)
    for key, value in source.items():
        if key not in result:
            result[key] = value
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = deep_merge(value, result[key])
    return result


def collect_diff(source: dict, target: dict, prefix: str = "") -> list[str]:
    """收集 source 中有但 target 中缺失的键路径，用于 dry-run 输出。"""
    missing: list[str] = []
    for key, value in source.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in target:
            missing.append(path)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            missing.extend(collect_diff(value, target[key], path))
    return missing


def sync_config(
    source_path: Path,
    target_path: Path,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> int:
    """将 source 的格式同步到 target。返回新增键的数量。"""
    if not source_path.exists():
        print(f"错误: 源文件不存在 {source_path}")
        return -1
    if not target_path.exists():
        print(f"错误: 目标文件不存在 {target_path}")
        return -1

    with open(source_path, encoding="utf-8") as f:
        source = yaml.safe_load(f)
    with open(target_path, encoding="utf-8") as f:
        target = yaml.safe_load(f)

    if not isinstance(source, dict) or not isinstance(target, dict):
        print("错误: 两个文件都必须包含顶层 YAML mapping")
        return -1

    missing = collect_diff(source, target)
    if not missing:
        print("已是最新格式，无需同步。")
        return 0

    print(f"发现 {len(missing)} 个缺失的键:")
    for path in missing:
        print(f"  + {path}")

    if dry_run:
        print("\n[dry-run] 未修改目标文件。")
        return len(missing)

    if backup:
        backup_path = target_path.with_suffix(target_path.suffix + ".bak")
        backup_path.write_bytes(target_path.read_bytes())
        print(f"\n已备份至 {backup_path}")

    merged = deep_merge(source, target)
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(
            merged,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            indent=2,
            width=120,
        )

    print(f"已写入 {len(missing)} 个新增键到 {target_path}")
    return len(missing)


def main() -> None:
    parser = argparse.ArgumentParser(description="将 default.yaml 的新增字段同步到本地配置文件")
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=Path("config/default.yaml"),
        help="源文件路径（默认: config/default.yaml）",
    )
    parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=Path("config/local.yaml"),
        help="目标文件路径（默认: config/local.yaml）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示差异，不修改目标文件",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不备份目标文件",
    )
    args = parser.parse_args()

    result = sync_config(
        args.source.resolve(),
        args.target.resolve(),
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    main()
