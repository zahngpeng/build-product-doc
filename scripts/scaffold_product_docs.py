#!/usr/bin/env python3
"""按项目、端口、模块和身份创建中文产品文档目录。"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "模板"
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建结构化中文产品文档目录。")
    parser.add_argument("--project-root", required=True, help="项目根目录。")
    parser.add_argument("--project-name", required=True, help="项目名称。")
    parser.add_argument("--docs-dir", default="docs/product", help="文档输出目录。")
    parser.add_argument("--role", action="append", default=[], help="角色名称，可重复传入。")
    parser.add_argument("--module", action="append", default=[], help="模块名称，可重复传入。")
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        metavar="角色=端口一,端口二",
        help="设置角色使用的端口，并据此生成端口产品视图。",
    )
    parser.add_argument(
        "--module-role",
        action="append",
        default=[],
        metavar="模块=角色一,角色二",
        help="设置模块适用的身份；未设置时默认使用全部角色。",
    )
    parser.add_argument(
        "--include-core-pages",
        action="store_true",
        help="为所有适用身份和端口创建列表页、详情页PRD。",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅显示计划，不创建文件。")
    return parser.parse_args()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def safe_segment(value: str, label: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"{label}名称无效：{value!r}")
    return cleaned


def parse_mapping(entries: list[str], label: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"{label}必须使用“名称=值一,值二”的格式：{entry!r}")
        key, raw_values = entry.split("=", 1)
        key = key.strip()
        values = unique(raw_values.split(","))
        if not key or not values:
            raise ValueError(f"{label}存在空名称或空值：{entry!r}")
        result[key] = values
    return result


def ensure_inside(project_root: Path, output_root: Path) -> None:
    try:
        output_root.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("--docs-dir必须位于项目根目录内") from exc


def render(template_relative: str, context: dict[str, str]) -> str:
    template_path = TEMPLATE_ROOT / template_relative
    content = template_path.read_text(encoding="utf-8")
    for key, value in context.items():
        content = content.replace("{{" + key + "}}", value)
    unresolved = sorted(set(PLACEHOLDER_RE.findall(content)))
    if unresolved:
        raise ValueError(
            f"模板{template_relative}仍有未替换内容：{', '.join(unresolved)}"
        )
    return content


class Writer:
    def __init__(self, project_root: Path, output_root: Path, dry_run: bool) -> None:
        self.project_root = project_root
        self.output_root = output_root
        self.dry_run = dry_run
        self.created: list[Path] = []
        self.skipped: list[Path] = []

    def add(self, relative: str, template: str, context: dict[str, str]) -> None:
        destination = self.output_root / relative
        if destination.exists():
            self.skipped.append(destination)
            return
        content = render(template, context)
        self.created.append(destination)
        if self.dry_run:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def report(self) -> None:
        action = "计划创建" if self.dry_run else "已创建"
        print(f"{action}{len(self.created)}份文档：{self.output_root}")
        for path in self.created:
            print(f"  + {path.relative_to(self.project_root)}")
        if self.skipped:
            print(f"已跳过{len(self.skipped)}份现有文档")
            for path in self.skipped:
                print(f"  = {path.relative_to(self.project_root)}")


def role_endpoints(role: str, endpoints: dict[str, list[str]]) -> str:
    values = endpoints.get(role, [])
    return "、".join(values) if values else "[待确认]"


def endpoint_roles(
    endpoint: str,
    roles: list[str],
    endpoints: dict[str, list[str]],
) -> list[str]:
    return [role for role in roles if endpoint in endpoints.get(role, [])]


def mermaid_label(value: str) -> str:
    return re.sub(r"[\r\n\"[\]{}]+", " ", value).strip() or "待确认"


def information_structure(
    project_name: str,
    roles: list[str],
    modules: list[str],
    endpoints: dict[str, list[str]],
) -> tuple[str, str]:
    endpoint_values = unique(
        [endpoint for values in endpoints.values() for endpoint in values]
    )

    lines = [
        "flowchart TD",
        f'    P["项目：{mermaid_label(project_name)}"]',
        '    RG["角色与身份"]',
        '    EG["产品端口"]',
        '    MG["业务模块"]',
        "    P --> RG",
        "    P --> EG",
        "    P --> MG",
    ]
    rows = [
        f"| P | — | 1 | {project_name} | 产品 | 全部 | 全部 | — | 产品总PRD |",
        "| RG | P | 2 | 角色与身份 | 分组 | 全部 | 全部 | — | 业务模块按身份文档 |",
        "| EG | P | 2 | 产品端口 | 分组 | 全部 | 全部 | — | 端口产品视图、信息架构与导航结构 |",
        "| MG | P | 2 | 业务模块 | 分组 | 全部 | 全部 | — | 产品功能架构 |",
    ]

    for index, role in enumerate(roles or ["[待确认角色]"], 1):
        node_id = f"R{index:02d}"
        lines.append(f'    {node_id}["角色：{mermaid_label(role)}"]')
        lines.append(f"    RG --> {node_id}")
        rows.append(
            f"| {node_id} | RG | 3 | {role} | 角色 | {role} | "
            f"{role_endpoints(role, endpoints)} | — | 业务模块按身份文档 |"
        )

    for index, endpoint in enumerate(endpoint_values or ["[待确认端口]"], 1):
        node_id = f"E{index:02d}"
        lines.append(f'    {node_id}["端口：{mermaid_label(endpoint)}"]')
        lines.append(f"    EG --> {node_id}")
        roles_for_endpoint = endpoint_roles(endpoint, roles, endpoints)
        role_summary = "、".join(roles_for_endpoint) if roles_for_endpoint else "[待确认]"
        rows.append(
            f"| {node_id} | EG | 3 | {endpoint} | 端口 | {role_summary} | "
            f"{endpoint} | — | 端口功能清单、端口核心业务旅程 |"
        )

    for index, module in enumerate(modules or ["[待确认模块]"], 1):
        module_id = f"M{index:02d}"
        object_id = f"O{index:02d}"
        page_id = f"PG{index:02d}"
        lines.extend(
            [
                f'    {module_id}["模块：{mermaid_label(module)}"]',
                f'    {object_id}["核心业务对象：[待确认]"]',
                f'    {page_id}["页面与交互：[待确认]"]',
                f"    MG --> {module_id}",
                f"    {module_id} --> {object_id}",
                f"    {module_id} --> {page_id}",
            ]
        )
        rows.extend(
            [
                f"| {module_id} | MG | 3 | {module} | 业务模块 | [待确认] | "
                f"[待确认] | {module_id} | {module}模块主PRD |",
                f"| {object_id} | {module_id} | 4 | [待确认对象] | 业务对象 | "
                f"[待确认] | [待确认] | {module_id} | {module}字段字典 |",
                f"| {page_id} | {module_id} | 4 | [待确认页面] | 页面集合 | "
                f"[待确认] | [待确认] | [待确认页面ID] | 信息架构与导航结构 |",
            ]
        )

    return "\n".join(lines), "\n".join(rows)


def project_context(
    project_name: str,
    roles: list[str],
    modules: list[str],
    endpoints: dict[str, list[str]],
    today: str,
) -> dict[str, str]:
    role_rows = "\n".join(
        f"| {role} | [待确认] | [待确认] | [待确认] | {role_endpoints(role, endpoints)} |"
        for role in roles
    )
    if not role_rows:
        role_rows = "| [待确认] | [待确认] | [待确认] | [待确认] | [待确认] |"

    module_rows = "\n".join(
        f"| M{index:02d} | {module} | [待确认] | [待确认] | [待确认] |"
        for index, module in enumerate(modules, 1)
    )
    if not module_rows:
        module_rows = "| [待确认] | [待确认] | [待确认] | [待确认] | [待确认] |"

    endpoint_values = unique(
        [endpoint for values in endpoints.values() for endpoint in values]
    )
    information_diagram, information_rows = information_structure(
        project_name,
        roles,
        modules,
        endpoints,
    )
    navigation_sections = "\n\n".join(
        (
            f"### 2.{index} {endpoint}\n\n"
            f"适用身份：{'、'.join(endpoint_roles(endpoint, roles, endpoints)) or '[待确认]'}\n\n"
            "[待确认]"
        )
        for index, endpoint in enumerate(endpoint_values, 1)
    )
    if not navigation_sections:
        navigation_sections = "### 2.1 [待确认端口]\n\n适用身份：[待确认]\n\n[待确认]"

    return {
        "PROJECT_NAME": project_name,
        "DATE": today,
        "ROLE_TABLE_ROWS": role_rows,
        "ENDPOINT_SUMMARY": "、".join(endpoint_values) if endpoint_values else "[待确认]",
        "MODULE_TABLE_ROWS": module_rows,
        "ROLE_HEADER_CELLS": " | ".join(roles) if roles else "[待确认角色]",
        "ROLE_SEPARATOR_CELLS": "|".join("---" for _ in (roles or ["待确认角色"])),
        "ENDPOINT_NAVIGATION_SECTIONS": navigation_sections,
        "INFORMATION_STRUCTURE_DIAGRAM": information_diagram,
        "INFORMATION_STRUCTURE_ROWS": information_rows,
    }


def validate_arguments(
    roles: list[str],
    modules: list[str],
    endpoints: dict[str, list[str]],
    module_roles: dict[str, list[str]],
) -> None:
    unknown_endpoint_roles = sorted(set(endpoints) - set(roles))
    if unknown_endpoint_roles:
        raise ValueError(
            "--endpoint引用了未通过--role声明的角色："
            + "、".join(unknown_endpoint_roles)
        )

    unknown_modules = sorted(set(module_roles) - set(modules))
    if unknown_modules:
        raise ValueError(
            "--module-role引用了未通过--module声明的模块："
            + "、".join(unknown_modules)
        )

    unknown_roles = sorted(
        {
            role
            for mapped_roles in module_roles.values()
            for role in mapped_roles
            if role not in roles
        }
    )
    if unknown_roles:
        raise ValueError(
            "--module-role引用了未通过--role声明的角色："
            + "、".join(unknown_roles)
        )


def scaffold() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError(f"项目根目录不存在：{project_root}")

    output_root = (project_root / args.docs_dir).resolve()
    ensure_inside(project_root, output_root)

    roles = unique(args.role)
    modules = unique(args.module)
    endpoints = parse_mapping(args.endpoint, "--endpoint")
    module_roles = parse_mapping(args.module_role, "--module-role")
    validate_arguments(roles, modules, endpoints, module_roles)

    today = dt.date.today().isoformat()
    common = project_context(args.project_name, roles, modules, endpoints, today)
    writer = Writer(project_root, output_root, args.dry_run)

    project_files = [
        ("01_项目总体方案.md", "项目级产品文档/项目总体方案模板.md"),
        ("02_产品总PRD.md", "项目级产品文档/产品总PRD模板.md"),
        ("03_项目范围与版本规划.md", "项目级产品文档/项目范围与版本规划模板.md"),
        ("04_产品功能架构.md", "项目级产品文档/产品功能架构模板.md"),
        ("05_信息架构与导航结构.md", "项目级产品文档/信息架构与导航结构模板.md"),
    ]
    for index, (filename, template) in enumerate(project_files, 1):
        context = dict(common, DOC_ID=f"DOC-P-{index:03d}")
        if template == "项目级产品文档/产品功能架构模板.md":
            rows = "\n".join(
                f"| M{module_index:02d} | {module} | [待确认] | [待确认] | [待确认] | [待确认] |"
                for module_index, module in enumerate(modules, 1)
            )
            context["MODULE_TABLE_ROWS"] = rows or (
                "| [待确认] | [待确认] | [待确认] | [待确认] | [待确认] | [待确认] |"
            )
        writer.add(f"01_项目级产品文档/{filename}", template, context)

    role_indexes = {role: index for index, role in enumerate(roles, 1)}
    endpoint_values = unique(
        [endpoint for values in endpoints.values() for endpoint in values]
    )
    for endpoint_number, endpoint in enumerate(endpoint_values, 1):
        endpoint_safe = safe_segment(endpoint, "端口")
        endpoint_dir = f"02_端口产品视图/E{endpoint_number:02d}_{endpoint_safe}"
        roles_for_endpoint = endpoint_roles(endpoint, roles, endpoints)
        endpoint_context = dict(
            common,
            ENDPOINT_NAME=endpoint,
            ENDPOINT_ROLES="、".join(roles_for_endpoint) if roles_for_endpoint else "[待确认]",
        )
        writer.add(
            f"{endpoint_dir}/01_{endpoint_safe}端口功能清单.md",
            "端口产品视图/端口功能清单模板.md",
            dict(endpoint_context, DOC_ID=f"DOC-E{endpoint_number:02d}-001"),
        )
        writer.add(
            f"{endpoint_dir}/02_{endpoint_safe}端口核心业务旅程.md",
            "端口产品视图/端口核心业务旅程模板.md",
            dict(endpoint_context, DOC_ID=f"DOC-E{endpoint_number:02d}-002"),
        )

    for module_number, module in enumerate(modules, 1):
        module_safe = safe_segment(module, "模块")
        module_dir = f"03_业务模块/M{module_number:02d}_{module_safe}"
        module_context = dict(common, MODULE_NAME=module)

        module_files = [
            (f"01_{module_safe}模块主PRD.md", "业务模块主文档/模块主PRD模板.md"),
            (f"02_{module_safe}模块功能清单.md", "业务模块主文档/模块功能清单模板.md"),
            (f"03_{module_safe}业务流程.md", "业务模块主文档/业务流程模板.md"),
            (f"04_{module_safe}状态流转.md", "业务模块主文档/状态流转模板.md"),
            (f"05_{module_safe}字段字典.md", "业务模块主文档/字段字典模板.md"),
        ]
        for index, (filename, template) in enumerate(module_files, 1):
            writer.add(
                f"{module_dir}/01_业务模块主文档/{filename}",
                template,
                dict(module_context, DOC_ID=f"DOC-M{module_number:02d}-{index:03d}"),
            )

        selected_roles = module_roles.get(module, roles)
        for role in selected_roles:
            role_number = role_indexes[role]
            role_safe = safe_segment(role, "角色")
            identity_dir = f"{module_dir}/02_按身份/R{role_number:02d}_{role_safe}"
            identity_context = dict(
                module_context,
                ROLE_NAME=role,
                ROLE_ENDPOINTS=role_endpoints(role, endpoints),
            )
            writer.add(
                f"{identity_dir}/01_{role_safe}{module_safe}模块主PRD.md",
                "按身份模块文档/身份模块主PRD模板.md",
                dict(
                    identity_context,
                    DOC_ID=f"DOC-M{module_number:02d}-R{role_number:02d}-001",
                ),
            )
            writer.add(
                f"{identity_dir}/02_{role_safe}{module_safe}模块功能清单.md",
                "按身份模块文档/身份模块功能清单模板.md",
                dict(
                    identity_context,
                    DOC_ID=f"DOC-M{module_number:02d}-R{role_number:02d}-002",
                ),
            )
            writer.add(
                f"{identity_dir}/04_{role_safe}{module_safe}验收PRD.md",
                "验收文档/验收PRD模板.md",
                dict(
                    identity_context,
                    DOC_ID=f"DOC-M{module_number:02d}-R{role_number:02d}-003",
                    ACCEPTANCE_NAME=f"{role}{module}",
                ),
            )

            if args.include_core_pages:
                selected_endpoints = endpoints.get(role, ["端口待确认"])
                for endpoint_number, endpoint in enumerate(selected_endpoints, 1):
                    endpoint_safe = safe_segment(endpoint, "端口")
                    page_dir = (
                        f"{identity_dir}/03_页面PRD/"
                        f"E{endpoint_number:02d}_{endpoint_safe}"
                    )
                    page_base = (
                        f"P-M{module_number:02d}-R{role_number:02d}-"
                        f"E{endpoint_number:02d}"
                    )
                    page_common = dict(
                        identity_context,
                        ENDPOINT_NAME=endpoint,
                        COMPONENT_ID="[待确认组件ID]",
                        COMPONENT_NAME="[待确认组件]",
                    )
                    writer.add(
                        f"{page_dir}/{page_base}-001_{module_safe}列表页PRD.md",
                        "页面PRD/列表页PRD模板.md",
                        dict(
                            page_common,
                            DOC_ID=f"DOC-{page_base}-001",
                            PAGE_ID=f"{page_base}-001",
                            PAGE_NAME=f"{module}列表页",
                        ),
                    )
                    writer.add(
                        f"{page_dir}/{page_base}-002_{module_safe}详情页PRD.md",
                        "页面PRD/详情页PRD模板.md",
                        dict(
                            page_common,
                            DOC_ID=f"DOC-{page_base}-002",
                            PAGE_ID=f"{page_base}-002",
                            PAGE_NAME=f"{module}详情页",
                        ),
                    )

    writer.report()
    return 0


def main() -> int:
    try:
        return scaffold()
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
