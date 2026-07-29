#!/usr/bin/env python3
"""校验中文产品文档的目录和核心内容。"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


DOC_ID_RE = re.compile(r'^doc_id:\s*["\']?([^"\'\n]+)["\']?\s*$', re.MULTILINE)
DOC_TYPE_RE = re.compile(
    r'^document_type:\s*["\']?([^"\'\n]+)["\']?\s*$',
    re.MULTILINE,
)
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")

PROJECT_FILES = [
    "01_项目总体方案.md",
    "02_产品总PRD.md",
    "03_项目范围与版本规划.md",
    "04_产品功能架构.md",
    "05_信息架构与导航结构.md",
]

SCOPES = (
    "all",
    "project",
    "endpoint",
    "module-common",
    "identity",
    "page",
)

REQUIRED_SECTIONS: dict[str, list[str]] = {
    "project-overall": [
        "## 2. 建设目标与成功标准",
        "## 6. 项目范围摘要",
        "## 8. 产品模块规划",
    ],
    "product-master-prd": [
        "## 4. 角色、组织与数据范围",
        "## 6. 信息结构图",
        "### 6.1 信息结构节点说明",
        "### 6.2 结构关系说明",
        "## 7. 核心跨模块业务流程",
        "## 8. 全局业务规则",
        "flowchart TD",
    ],
    "module-master-prd": [
        "## 2. 模块范围与边界",
        "## 5. 公共业务流程",
        "## 7. 公共业务规则",
        "## 10. 异常与边界场景",
    ],
    "module-function-list": [
        "## 功能追踪与覆盖",
        "规则ID/核心规则",
        "失败与异常",
    ],
    "module-business-flow-state-transition": [
        "## 一、业务流程",
        "### 4. 主流程",
        "### 9. 时限、通知与补偿",
        "业务规则与权限校验",
        "## 二、状态流转",
        "### 2. 状态定义",
        "### 3. 状态流转表",
        "### 5. 各角色状态展示与操作",
        "### 7. 超时、自动流转与并发控制",
    ],
    "module-field-dictionary": [
        "## 一、头部字段（单据级）",
        "## 二、明细字段（行项目级）",
        "## 三、状态、金额、审计及派生字段",
        "## 四、枚举与选项",
        "## 五、字段联动、计算与校验",
        "## 六、身份与端口差异",
        "字段ID | 字段名称 | 字段来源 | 取值说明 | 必填性 | 新增页 | 编辑页 | 列表展示 | 可筛选 | 详情展示 | 字段说明 | 备注",
    ],
    "role-module-master-prd": [
        "## 4. 数据范围",
        "## 7. 状态展示与操作",
        "## 9. 字段可见性与编辑原则",
        "## 10. 身份操作权限",
        "## 11. 消息、通知、操作记录与异常",
    ],
    "role-module-function-list": [
        "## 页面与验收追踪",
        "成功结果",
        "失败与异常",
    ],
    "list-page-prd": [
        "## 4. 查询区域",
        "## 5. 列表字段",
        "### 7.4 导出、打印与下载",
        "## 8. 弹窗、抽屉及二次交互",
        "## 9. 页面状态",
        "## 13. 验收标准",
        "| 路由/页面地址 |",
    ],
    "detail-page-prd": [
        "## 4. 信息分组与字段",
        "### 4.3 明细、子表与嵌套数据",
        "## 6. 页面操作",
        "### 6.1 打印、导出与下载",
        "## 7. 弹窗、抽屉及二次交互",
        "## 8. 页面状态",
        "## 12. 验收标准",
        "| 路由/页面地址 |",
    ],
    "generic-page-prd": [
        "## 3. 字段与内容",
        "## 6. 弹窗、抽屉及二次交互",
        "## 7. 页面状态",
        "## 10. 验收标准",
        "| 路由/页面地址 |",
        "| 取消与关闭规则 |",
    ],
    "acceptance-prd": [
        "## 5. 功能与页面验收用例",
        "## 7. 查询与列表验收",
        "## 9. 权限与数据范围验收",
        "## 10. 弹窗、抽屉及交互验收",
        "## 12. 业务规则、边界与并发验收",
        "## 13. 通知与操作记录验收",
        "## 16. 需求覆盖检查",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验结构化中文产品文档。")
    parser.add_argument("--project-root", required=True, help="项目根目录。")
    parser.add_argument("--docs-dir", default="docs/product", help="文档目录。")
    parser.add_argument(
        "--scope",
        choices=SCOPES,
        default="all",
        help=(
            "校验范围：all全量、project项目级、endpoint端口产品视图、"
            "module-common业务模块公共主文档、identity按身份模块文档、page页面PRD。"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="将所有警告视为校验失败。",
    )
    return parser.parse_args()


def contains_all(directory: Path, fragments: list[str]) -> bool:
    if not directory.is_dir():
        return False
    names = [path.name for path in directory.iterdir() if path.is_file()]
    return all(any(fragment in name for name in names) for fragment in fragments)


def scoped_markdown_files(docs_root: Path, scope: str) -> list[Path]:
    if scope == "all":
        return sorted(docs_root.rglob("*.md"))

    files: set[Path] = set()
    if scope == "project":
        files.update((docs_root / "01_项目级产品文档").rglob("*.md"))
    elif scope == "endpoint":
        files.update((docs_root / "02_端口产品视图").rglob("*.md"))
    else:
        modules_dir = docs_root / "03_业务模块"
        if modules_dir.is_dir():
            for module_dir in modules_dir.iterdir():
                if not module_dir.is_dir():
                    continue
                if scope == "module-common":
                    files.update(
                        (module_dir / "01_业务模块主文档").rglob("*.md")
                    )
                    continue
                identities_dir = module_dir / "02_按身份"
                if not identities_dir.is_dir():
                    continue
                for identity_dir in identities_dir.iterdir():
                    if not identity_dir.is_dir():
                        continue
                    if scope == "identity":
                        files.update(identity_dir.glob("*.md"))
                    elif scope == "page":
                        files.update(
                            (identity_dir / "03_页面PRD").rglob("*.md")
                        )
    return sorted(files)


def validate(docs_root: Path, scope: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not docs_root.is_dir():
        return [f"产品文档目录不存在：{docs_root}"], warnings

    project_dir = docs_root / "01_项目级产品文档"
    if scope in {"all", "project"}:
        for filename in PROJECT_FILES:
            if not (project_dir / filename).is_file():
                errors.append(f"缺少项目级文档：{project_dir / filename}")

    endpoints_dir = docs_root / "02_端口产品视图"
    if scope in {"all", "endpoint"}:
        if not endpoints_dir.is_dir():
            message = f"缺少端口产品视图目录：{endpoints_dir}"
            if scope == "endpoint":
                errors.append(message)
            else:
                warnings.append(message)
        else:
            endpoint_dirs = sorted(
                path for path in endpoints_dir.iterdir() if path.is_dir()
            )
            if scope == "endpoint" and not endpoint_dirs:
                errors.append(f"没有可校验的端口产品视图：{endpoints_dir}")
            for endpoint_dir in endpoint_dirs:
                if not contains_all(
                    endpoint_dir,
                    ["端口功能清单", "端口核心业务旅程"],
                ):
                    errors.append(f"端口产品视图不完整：{endpoint_dir}")

    modules_dir = docs_root / "03_业务模块"
    module_scopes = {"all", "module-common", "identity", "page"}
    if scope in module_scopes:
        if not modules_dir.is_dir():
            message = f"缺少业务模块目录：{modules_dir}"
            if scope == "all":
                warnings.append(message)
            else:
                errors.append(message)
        else:
            module_dirs = sorted(
                path for path in modules_dir.iterdir() if path.is_dir()
            )
            if scope != "all" and not module_dirs:
                errors.append(f"没有可校验的业务模块：{modules_dir}")
            for module_dir in module_dirs:
                if scope in {"all", "module-common"}:
                    common_dir = module_dir / "01_业务模块主文档"
                    if not contains_all(
                        common_dir,
                        [
                            "模块主PRD",
                            "模块功能清单",
                            "业务流程与状态流转",
                            "字段字典",
                        ],
                    ):
                        errors.append(f"业务模块主文档不完整：{common_dir}")

                if scope not in {"all", "identity", "page"}:
                    continue

                identities_dir = module_dir / "02_按身份"
                if not identities_dir.is_dir():
                    message = f"模块尚未按身份生成文档：{identities_dir}"
                    if scope == "all":
                        warnings.append(message)
                    else:
                        errors.append(message)
                    continue

                identity_dirs = sorted(
                    path for path in identities_dir.iterdir() if path.is_dir()
                )
                if scope in {"identity", "page"} and not identity_dirs:
                    errors.append(f"没有可校验的身份目录：{identities_dir}")
                for identity_dir in identity_dirs:
                    if scope in {"all", "identity"} and not contains_all(
                        identity_dir,
                        ["模块主PRD", "模块功能清单", "验收PRD"],
                    ):
                        errors.append(f"按身份划分的模块文档不完整：{identity_dir}")

                    if scope not in {"all", "page"}:
                        continue

                    page_dir = identity_dir / "03_页面PRD"
                    page_prds = (
                        [path for path in page_dir.rglob("*.md")]
                        if page_dir.is_dir()
                        else []
                    )
                    if not page_prds:
                        message = f"尚未生成具体页面PRD：{page_dir}"
                        if scope == "all":
                            warnings.append(message)
                        else:
                            errors.append(message)

    markdown_files = scoped_markdown_files(docs_root, scope)
    if scope != "all" and not markdown_files:
        errors.append(f"指定范围没有可校验的Markdown文档：{scope}")
    ids: dict[str, list[Path]] = defaultdict(list)
    pending_count = 0

    for path in markdown_files:
        content = path.read_text(encoding="utf-8")
        if PLACEHOLDER_RE.search(content):
            errors.append(f"存在未替换的模板变量：{path}")

        doc_id_match = DOC_ID_RE.search(content)
        if not doc_id_match:
            errors.append(f"缺少doc_id：{path}")
        else:
            ids[doc_id_match.group(1).strip()].append(path)

        doc_type_match = DOC_TYPE_RE.search(content)
        if not doc_type_match:
            errors.append(f"缺少document_type：{path}")
        else:
            doc_type = doc_type_match.group(1).strip()
            for section in REQUIRED_SECTIONS.get(doc_type, []):
                if section not in content:
                    errors.append(f"缺少章节“{section}”：{path}")

        pending_count += content.count("[待确认]")

    for doc_id, paths in ids.items():
        if len(paths) > 1:
            joined = "、".join(str(path) for path in paths)
            errors.append(f"文档ID重复：{doc_id}，涉及{joined}")

    if pending_count:
        warnings.append(f"共有{pending_count}处[待确认]")

    return errors, warnings


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    docs_root = (project_root / args.docs_dir).resolve()
    try:
        docs_root.relative_to(project_root)
    except ValueError:
        print("错误：--docs-dir必须位于项目根目录内", file=sys.stderr)
        return 2

    errors, warnings = validate(docs_root, args.scope)

    print(f"校验目录：{docs_root}")
    print(f"校验范围：{args.scope}")
    print(f"错误：{len(errors)}")
    for item in errors:
        print(f"  错误：{item}")
    print(f"警告：{len(warnings)}")
    for item in warnings:
        print(f"  警告：{item}")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
