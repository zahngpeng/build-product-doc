"""Shared parsing helpers for the product-document scripts."""
from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
    from markdown_it import MarkdownIt
except ImportError as exc:
    raise RuntimeError(
        '缺少脚本依赖。请在当前 Python 环境运行：python -m pip install -r '
        + str(Path(__file__).with_name('requirements.txt'))
    ) from exc


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError('YAML 映射键必须为字符串')
        if key in result:
            raise ValueError(f'YAML 键重复：{key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
MARKDOWN = MarkdownIt('commonmark').enable('table')
PLACEHOLDER_RE = re.compile(r'\{\{[^{}\r\n]+\}\}')
PENDING_RE = re.compile(r'\[待确认[^\]\r\n]*\]')


def frontmatter(text: str) -> tuple[dict, str, int]:
    lines = text.lstrip('\ufeff').splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        raise ValueError('缺少文件开头的 YAML frontmatter')
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None:
        raise ValueError('YAML frontmatter 未闭合')
    try:
        metadata = yaml.load(''.join(lines[1:end]), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f'YAML 格式错误：{exc}') from exc
    if not isinstance(metadata, dict):
        raise ValueError('YAML frontmatter 必须为映射')
    return metadata, ''.join(lines[end + 1:]), end + 1


def heading_name(text: str) -> str:
    return re.sub(r'^(?:\d+(?:\.\d+)*[.、．]?\s*|[一二三四五六七八九十]+[、.．]\s*)', '', text).strip()


def table_cells(line: str) -> list[str]:
    """Split a Markdown table source row without treating escaped pipes as cells."""
    text = line.strip()
    cells, current, slashes = [], [], 0
    for char in text:
        if char == '|' and slashes % 2 == 0:
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
        slashes = slashes + 1 if char == '\\' else 0
    cells.append(''.join(current).strip())
    if text.startswith('|'):
        cells.pop(0)
    if len(cells) > 1 and cells[-1] == '' and text.endswith('|'):
        cells.pop()
    return cells


def module_key(path: Path, docs_root: Path) -> str:
    parts = path.relative_to(docs_root).parts
    if '03_业务模块' in parts:
        index = parts.index('03_业务模块') + 1
        if index < len(parts) - 1:
            return '/'.join(parts[:index + 1])
    return ''
