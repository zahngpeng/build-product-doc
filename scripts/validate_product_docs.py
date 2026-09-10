#!/usr/bin/env python3
"""检查产品文档的结构与显式引用；不证明业务语义或验收通过。"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    from doc_support import MARKDOWN, PLACEHOLDER_RE, PENDING_RE, frontmatter, heading_name, module_key, table_cells
except RuntimeError as exc:
    print(f"错误：{exc}", file=sys.stderr)
    raise SystemExit(2)

PROJECT_FILES = [
    "01_项目总体方案.md", "02_产品总PRD.md", "03_项目范围与版本规划.md",
    "04_产品功能架构.md", "05_信息架构与导航结构.md",
]
# Minimum section concepts. Numbering is ignored; aliases are intentional, bounded equivalents.
REQUIRED_SECTIONS = {
    "project-overall": ["建设目标与成功标准", "项目范围摘要", "产品模块规划"],
    "product-master-prd": ["角色、组织与数据范围", "信息结构图", "核心跨模块业务流程", "全局业务规则"],
    "scope-version-plan": ["本期范围", "非本期范围", "版本规划"],
    "functional-architecture": ["功能分层", "模块职责与边界", "模块依赖关系"],
    "information-architecture-navigation": ["页面层级", "页面入口与出口", "跨模块跳转"],
    "endpoint-function-list": ["端口定义", "按业务模块划分的功能清单", "端口边界与不可用能力"],
    "endpoint-core-journey": ["旅程概览", "主旅程", "分支与异常旅程"],
    "module-master-prd": ["模块范围与边界", "公共业务规则", "权限与数据原则", "异常与边界场景"],
    "module-function-list": ["功能边界说明", "功能追踪与覆盖"],
    "module-business-flow-state-transition": ["业务流程", "状态流转"],
    "module-field-dictionary": ["头部字段（单据级）", "明细字段（行项目级）", "状态、金额、审计及派生字段", "枚举与选项", "字段联动、计算与校验"],
    "role-module-master-prd": ["数据范围", "状态展示与操作", "字段可见性与编辑原则", "身份操作权限"],
    "role-module-function-list": ["与模块公共功能的关系", "页面与验收追踪"],
    "list-page-prd": [("查询区域", "查询条件"), "列表字段", "弹窗、抽屉及二次交互", "页面状态", "验收标准"],
    "detail-page-prd": ["信息分组与字段", "页面操作", "弹窗、抽屉及二次交互", "页面状态", "验收标准"],
    "generic-page-prd": ["字段与内容", "页面操作", "页面状态", "验收标准"],
    "acceptance-prd": ["验收范围", "功能与页面验收用例", "权限与数据范围验收", "需求覆盖检查"],
    "supplement": [],
}
PAGE_TYPES = {"list-page-prd", "detail-page-prd", "generic-page-prd"}
DEFAULT_ID_PREFIXES = ("REQ", "F", "BR", "RULE", "RUL", "R", "FLD", "P", "AC", "ST",
                       "STATE", "TR", "TRANS", "STEP", "ACT", "EF", "TP", "OP", "CMP", "SCN", "ERR")


def id_pattern(extra=()):
    prefixes = set(DEFAULT_ID_PREFIXES)
    for prefix in extra:
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
            raise ValueError(f"编号前缀必须是大写字母开头的字母数字串：{prefix!r}")
        prefixes.add(prefix)
    return re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(sorted(prefixes, key=lambda p: (-len(p), p)))
                      + r")-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?![A-Za-z0-9_-])")


ID_RE = id_pattern()
DEFINITION_HEADERS = {
    "product-master-prd": {"规则ID"},
    "module-master-prd": {"需求ID", "规则ID"},
    "module-function-list": {"功能ID"},
    "module-field-dictionary": {"字段ID", "规则ID"},
    "module-business-flow-state-transition": {"步骤ID", "状态ID", "流转ID", "动作ID", "影响面ID", "时点ID", "场景ID", "异常ID"},
    "role-module-master-prd": {"操作ID", "差异ID"},
    "acceptance-prd": {"验收ID"},
    "list-page-prd": {"操作ID", "组件ID"},
    "detail-page-prd": {"操作ID", "组件ID"},
    "generic-page-prd": {"操作ID", "组件ID"},
}

# Only stable identity labels are compared; split control/reference tables may repeat IDs.
IDENTITY_LABELS = {
    "需求ID": ("需求", "需求名称"),
    "规则ID": ("规则名称", "规则"),
    "功能ID": ("功能点", "功能名称"),
    "字段ID": ("字段名称",),
    "步骤ID": ("步骤名称", "步骤", "用户/系统动作"),
    "状态ID": ("状态名称", "名称"),
    "流转ID": ("流转名称",),
    "动作ID": ("动作名称", "动作", "名称", "正文操作"),
    "影响面ID": ("项目业务名称", "影响面名称", "名称", "正文中的数据名称"),
    "时点ID": ("项目时点名称", "时点名称", "名称", "中文时点说明"),
    "场景ID": ("场景名称", "中文场景说明", "场景"),
    "异常ID": ("异常名称", "异常"),
    "操作ID": ("操作", "操作名称", "名称"),
    "组件ID": ("名称", "组件名称", "标题"),
}


def table_separator_errors(body, tokens, offset):
    """Catch malformed tables that Markdown's parser otherwise treats as plain text."""
    lines = body.splitlines()
    excluded = set()
    for token in tokens:
        if token.type in {"fence", "code_block", "html_block"} and token.map:
            excluded.update(range(*token.map))
    problems = []
    for index, line in enumerate(lines):
        if index == 0 or index in excluded or index - 1 in excluded or "|" not in line:
            continue
        cells = table_cells(line)
        if not cells or not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if "|" not in lines[index - 1]:
            continue
        header = table_cells(lines[index - 1])
        if len(cells) != len(header):
            problems.append(f"表格分隔行列数不一致：行 {index + offset + 1}，"
                            f"表头 {len(header)} 列，分隔行 {len(cells)} 列")
    return problems


def selected_module_dirs(root: Path, names: list[str]) -> set[Path]:
    if not names:
        raise ValueError("--scope module 需要至少一个 --module")
    parent = root / "03_业务模块"
    available = [p for p in parent.iterdir() if p.is_dir()] if parent.is_dir() else []
    selected = set()
    for name in names:
        matches = [p for p in available if p.name == name or p.name.startswith(name + "_")]
        if len(matches) != 1:
            raise ValueError(f"模块选择必须唯一匹配目录名或编号：{name}")
        selected.add(matches[0])
    return selected


def parse_document(path: Path, docs_root: Path) -> dict:
    metadata, body, offset = frontmatter(path.read_text(encoding="utf-8-sig"))
    tokens = MARKDOWN.parse(body)
    headings = set()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            headings.add(heading_name(tokens[index + 1].content))
    lines = body.splitlines()
    tables, table = [], None
    for token in tokens:
        if token.type == "table_open":
            table = {"header": [], "rows": []}
        elif token.type == "tr_open" and token.map and table is not None:
            line_number = token.map[0]
            cells = table_cells(lines[line_number])
            if not table["header"]:
                table["header"] = cells
            else:
                table["rows"].append((line_number + offset + 1, cells))
        elif token.type == "table_close":
            tables.append(table)
            table = None
    return dict(path=path, meta=metadata, body=body, offset=offset, tokens=tokens,
                headings=headings, tables=tables, module=module_key(path, docs_root))


def select_files(root: Path, all_files: list[Path], scope: str, modules: list[str], files: list[str]) -> set[Path]:
    if scope == "files":
        if not files:
            raise ValueError("--scope files 需要至少一个 --file（相对文档目录）")
        selected = set()
        for name in files:
            path = (root / name).resolve()
            if not path.is_relative_to(root) or path not in all_files:
                raise ValueError(f"选定文件不存在、不是 Markdown 或不在文档目录内：{name}")
            selected.add(path)
        return selected
    if scope == "module":
        directories = selected_module_dirs(root, modules)
        return {p for p in all_files if any(p.is_relative_to(directory) for directory in directories)}
    return set(all_files)


def check_layout(root: Path, selected: set[Path], scope: str, errors: list[str], warnings: list[str],
                 module_dirs: set[Path] | None = None) -> None:
    if scope == "project":
        for name in PROJECT_FILES:
            if not (root / "01_项目级产品文档" / name).is_file():
                errors.append(f"缺少项目级文档：{name}")
        for name in ["02_端口产品视图", "03_业务模块"]:
            if not (root / name).is_dir():
                warnings.append(f"缺少目录：{name}；请人工确认是否在交付范围")
    if scope not in {"project", "module"}:
        return
    modules = root / "03_业务模块"
    if not modules.is_dir():
        return
    for module in sorted(p for p in modules.iterdir() if p.is_dir()):
        if scope == "module" and module not in (module_dirs or set()):
            continue
        names = [p.name for p in (module / "01_业务模块主文档").glob("*.md")]
        for fragment in ["模块主PRD", "模块功能清单", "业务流程与状态流转", "字段字典"]:
            if not any(fragment in name for name in names):
                errors.append(f"模块公共文档缺少{fragment}：{module.name}")
        identities = module / "02_按身份"
        if identities.is_dir():
            identity_dirs = [p for p in identities.iterdir() if p.is_dir()]
            if not identity_dirs:
                warnings.append(f"身份目录为空：{module}")
            for identity in identity_dirs:
                for fragment in ["模块主PRD", "模块功能清单", "验收PRD"]:
                    if not any(fragment in p.name for p in identity.glob("*.md")):
                        errors.append(f"身份文档缺少{fragment}：{identity}")
        elif not any("验收PRD" in p.name for p in module.glob("*.md")):
            warnings.append(f"模块尚无共享验收PRD：{module.name}")
    if scope == "project":
        endpoints = root / "02_端口产品视图"
        if endpoints.is_dir():
            for endpoint in [p for p in endpoints.iterdir() if p.is_dir()]:
                for fragment in ["端口功能清单", "端口核心业务旅程"]:
                    if not any(fragment in p.name for p in endpoint.glob("*.md")):
                        errors.append(f"端口文档缺少{fragment}：{endpoint.name}")


def validate(docs_root: Path, *, scope: str = "present", modules=None, files=None,
             phase: str = "draft", project_root: Path | None = None, id_prefixes=None) -> tuple[list[str], list[str]]:
    root = docs_root.resolve()
    project_root = (project_root or root).resolve()
    errors, warnings = [], []
    if not root.is_dir():
        return [f"产品文档目录不存在：{root}"], []
    all_files = sorted({p.resolve() for p in root.rglob("*.md") if p.resolve().is_relative_to(root)})
    try:
        pattern = id_pattern(id_prefixes or ())
        module_dirs = selected_module_dirs(root, modules or []) if scope == "module" else None
        selected = select_files(root, all_files, scope, modules or [], files or [])
    except ValueError as exc:
        return [str(exc)], []
    check_layout(root, selected, scope, errors, warnings, module_dirs)
    if not selected:
        return errors + ["本次范围没有 Markdown 文档"], warnings
    documents = []
    for path in all_files:
        try:
            documents.append(parse_document(path, root))
        except (ValueError, OSError) as exc:
            if path in selected:
                errors.append(f"{path}：{exc}")
    doc_ids, page_ids, definitions = defaultdict(list), defaultdict(list), defaultdict(list)
    usages = []
    for doc in documents:
        path, metadata = doc["path"], doc["meta"]
        doc_type = metadata.get("document_type")
        if not isinstance(doc_type, str):
            doc_type = ""
        identifier = metadata.get("doc_id")
        if isinstance(identifier, str) and identifier.strip():
            doc_ids[identifier].append(path)
        if doc_type in PAGE_TYPES and isinstance(metadata.get("page_id"), str):
            page_ids[metadata["page_id"]].append(path)
            definitions[metadata["page_id"]].append((path, doc["module"]))
        explicit = metadata.get("defines", [])
        if isinstance(explicit, list):
            for item in explicit:
                if isinstance(item, str) and item:
                    definitions[item].append((path, doc["module"]))
        owned = DEFINITION_HEADERS.get(doc_type, set())
        field_rows = defaultdict(list)
        identity_rows = defaultdict(list)
        for table in doc["tables"]:
            header = table["header"]
            if not header or header[0] not in owned:
                continue
            # Projection/coverage tables reference IDs; primary field rows include a field name.
            if header[0] == "字段ID" and "字段名称" not in header:
                continue
            if header[0] == "功能ID" and not any(c in header for c in ["功能点", "功能名称"]):
                continue
            if header[0] in {"动作ID", "影响面ID", "时点ID", "状态ID", "操作ID", "组件ID"}:
                if not any(name in header for name in IDENTITY_LABELS[header[0]]):
                    continue
            for line, cells in table["rows"]:
                for item in pattern.findall(cells[0] if cells else ""):
                    definitions[item].append((path, doc["module"]))
                    if header[0] == "字段ID":
                        field_rows[item].append(line)
                    label = next((name for name in IDENTITY_LABELS.get(header[0], ()) if name in header), None)
                    if label and len(cells) > header.index(label):
                        name = cells[header.index(label)].strip()
                        if name:
                            identity_rows[item].append((name, line))
        if path in selected:
            errors.extend(f"{path}：{message}" for message in
                          table_separator_errors(doc["body"], doc["tokens"], doc["offset"]))
            for item, values in identity_rows.items():
                if len({name for name, _ in values}) > 1:
                    errors.append(f"ID冲突定义：{item}，{path}，名称与行 {values}")
            for item, lines in field_rows.items():
                if len(lines) > 1:
                    errors.append(f"字段ID重复定义：{item}，{path}，行 {lines}")
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"缺少有效 doc_id：{path}")
            if doc_type not in REQUIRED_SECTIONS:
                errors.append(f"未知或缺少 document_type：{metadata.get('document_type')!r}，{path}")
            else:
                for required in REQUIRED_SECTIONS[doc_type]:
                    choices = required if isinstance(required, tuple) else (required,)
                    if not any(name in doc["headings"] for name in choices):
                        errors.append(f"缺少章节“{'／'.join(choices)}”：{path}")
            if not doc["body"].strip():
                errors.append(f"文档正文为空：{path}")
            if doc_type in PAGE_TYPES and (not isinstance(metadata.get("page_id"), str) or not metadata["page_id"].strip()):
                errors.append(f"页面缺少 page_id：{path}")
            for key in ["defines", "references"]:
                values = metadata.get(key, [])
                if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                    errors.append(f"{key} 必须是非空 ID 字符串的列表：{path}")
            combined = path.read_text(encoding="utf-8-sig")
            if PLACEHOLDER_RE.search(combined):
                errors.append(f"存在未替换模板变量：{path}")
            if PENDING_RE.search(combined):
                message = f"{path}：{len(PENDING_RE.findall(combined))} 处待确认"
                (errors if phase == "final" else warnings).append(message)
            if not metadata.get("sources"):
                (errors if phase == "final" else warnings).append(f"缺少来源依据 sources：{path}")
            elif not isinstance(metadata["sources"], list) or any(
                not isinstance(value, str) or not value.strip() for value in metadata["sources"]
            ):
                errors.append(f"sources 必须是可定位来源的非空字符串列表：{path}")
            for table in doc["tables"]:
                for line, cells in table["rows"]:
                    if len(cells) != len(table["header"]):
                        errors.append(f"表格列数不一致：{path}:{line}，表头 {len(table['header'])} 列，数据 {len(cells)} 列")
            reference_values = metadata.get("references", [])
            if isinstance(reference_values, list):
                usages.extend((str(v), path, doc["module"]) for v in reference_values if isinstance(v, str))
            for token in doc["tokens"]:
                if token.type != "inline":
                    continue
                usages.extend((v, path, doc["module"]) for v in pattern.findall(token.content))
                for child in token.children or []:
                    if child.type not in {"link_open", "image"}:
                        continue
                    href = child.attrGet("href" if child.type == "link_open" else "src") or ""
                    parsed = urlsplit(href)
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue
                    target = (path.parent / unquote(parsed.path)).resolve()
                    if not target.is_file():
                        errors.append(f"本地链接目标不存在：{path} → {href}")
                    # Anchor correctness and remote availability are explicitly outside this checker.
    for label, ids in [("文档ID", doc_ids), ("页面ID", page_ids)]:
        for item, paths in ids.items():
            if len(set(paths)) > 1 and any(path in selected for path in paths):
                errors.append(f"{label}重复：{item}，涉及 {'、'.join(map(str, paths))}")
    for item, locations in definitions.items():
        grouped = defaultdict(set)
        for path, module in locations:
            grouped[module].add(path)
        for module, paths in grouped.items():
            if len(paths) > 1 and any(path in selected for path in paths):
                errors.append(f"ID 存在多个权威定义：{item}，涉及 {'、'.join(map(str, sorted(paths)))}")
    for item, path, module in sorted(set(usages), key=lambda x: (str(x[1]), x[0])):
        locations = set(definitions.get(item, []))
        local = {p for p, m in locations if m == module}
        global_locations = {p for p, m in locations}
        if not locations:
            errors.append(f"未定义的ID引用：{item}，{path}")
        elif not local and len(global_locations) > 1:
            errors.append(f"跨模块ID引用不唯一：{item}，{path}")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--docs-dir", default="docs/product")
    parser.add_argument("--scope", choices=["present", "project", "module", "files"], default="present",
                        help="默认只检查已有文档；project 才检查完整默认目录。")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--file", action="append", default=[], help="相对文档目录的 Markdown 文件，可重复。")
    parser.add_argument("--phase", choices=["draft", "final"], default="draft")
    parser.add_argument("--strict", action="store_true", help="将本次范围所有警告视为失败。")
    parser.add_argument("--id-prefix", action="append", default=[],
                        help="额外检查的业务编号前缀，如 CUSTOM；可重复，保留默认前缀。")
    args = parser.parse_args()
    if (args.module and args.scope != "module") or (args.file and args.scope != "files"):
        parser.error("--module 仅配合 --scope module；--file 仅配合 --scope files")
    try:
        id_pattern(args.id_prefix)
    except ValueError as exc:
        parser.error(str(exc))
    project = Path(args.project_root).expanduser().resolve()
    root = (project / args.docs_dir).resolve()
    if not root.is_relative_to(project):
        print("错误：--docs-dir 必须位于项目目录内", file=sys.stderr)
        return 2
    errors, warnings = validate(root, scope=args.scope, modules=args.module, files=args.file,
                                phase=args.phase, project_root=project, id_prefixes=args.id_prefix)
    print(f"校验目录：{root}\n范围：{args.scope}；阶段：{args.phase}\n错误：{len(errors)}")
    for item in errors:
        print(f"  错误：{item}")
    print(f"警告：{len(warnings)}")
    for item in warnings:
        print(f"  警告：{item}")
    print("自动检查编号前缀：" + "、".join(sorted(set(DEFAULT_ID_PREFIXES) | set(args.id_prefix))))
    print("其他编号需 --id-prefix 或 defines/references 显式声明；不会自动推断全部项目编号。")
    print("检查范围：元数据、最小章节、显式ID、本地文件链接及表格列数；业务语义、覆盖充分性、链接锚点、远程链接和 Mermaid 语法需另行审核。")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
