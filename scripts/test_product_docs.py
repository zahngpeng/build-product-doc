"""Regression checks for observable scaffold and validator behavior."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from doc_support import frontmatter
from validate_product_docs import validate

SCRIPTS = Path(__file__).resolve().parent


class ProductDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PRODUCT_DOCS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = self.root / 'docs/product'

    def scaffold(self, *extra, modules=('订单',), roles=('销售员',), endpoints=('销售员=PC',)):
        args = [sys.executable, '-B', '-X', 'utf8', str(SCRIPTS / 'scaffold_product_docs.py'),
                '--project-root', str(self.root), '--project-name', '审核样例']
        for name in modules:
            args.extend(['--module', name])
        for name in roles:
            args.extend(['--role', name])
        for name in endpoints:
            args.extend(['--endpoint', name])
        return subprocess.run(args + list(extra), capture_output=True, text=True, encoding='utf-8')

    def baseline(self):
        result = self.scaffold('--include-core-pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(validate(self.docs)[0], [])

    def page(self):
        return next(self.docs.rglob('*列表页PRD.md'))

    def append(self, text):
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8') + '\n' + text + '\n', encoding='utf-8')

    def errors(self, **kwargs):
        return '\n'.join(validate(self.docs, **kwargs)[0])

    def fingerprint(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_shared_internal_roles_do_not_duplicate_pages(self):
        result = self.scaffold('--include-core-pages', roles=('销售员', '财务', '管理员'),
                               endpoints=('销售员=PC', '财务=PC', '管理员=PC'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.docs.rglob('*.md'))), 14)
        self.assertEqual(len(list(self.docs.rglob('*列表页PRD.md'))), 1)
        self.assertFalse(list(self.docs.rglob('02_按身份')))
        self.assertEqual(self.errors(), '')

    def test_independent_identities_remain_separate(self):
        result = self.scaffold('--layout', 'by-identity', '--include-core-pages',
                               roles=('采购商', '供应商'), endpoints=('采购商=PC', '供应商=PC'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.docs.rglob('*列表页PRD.md'))), 2)
        self.assertEqual(len(list(self.docs.rglob('*验收PRD.md'))), 2)
        self.assertEqual(self.errors(), '')

    def test_module_scope_does_not_require_project_documents(self):
        result = self.scaffold('--scope', 'module', '--include-core-pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.docs / '01_项目级产品文档').exists())
        self.assertEqual(self.errors(), '')
        self.assertEqual(self.errors(scope='module', modules=['M01']), '')
        self.assertIn('缺少项目级文档', self.errors(scope='project'))

    def test_selected_file_ignores_unrelated_errors(self):
        self.baseline()
        bad = self.docs / '无关文档.md'
        bad.write_text('不是正式文档', encoding='utf-8')
        self.assertIn('frontmatter', self.errors())
        self.assertEqual(self.errors(scope='files', files=[str(self.page().relative_to(self.docs))]), '')

    def test_selected_file_can_resolve_context_definition(self):
        self.baseline()
        dictionary = next(self.docs.rglob('*字段字典.md'))
        text = dictionary.read_text(encoding='utf-8')
        text = text.replace('sources: []', 'sources: []\ndefines: [FLD-M01-001]')
        dictionary.write_text(text, encoding='utf-8')
        self.append('引用字段 FLD-M01-001')
        self.assertEqual(self.errors(scope='files', files=[str(self.page().relative_to(self.docs))]), '')

    def test_unresolved_field_is_rejected(self):
        self.baseline()
        self.append('| 顺序 | 字段ID | 列名 |\n|---|---|---|\n| 1 | FLD-M01-MISSING | 缺少定义 |')
        self.assertIn('未定义的ID引用', self.errors())

    def test_rule_definition_and_page_reference(self):
        self.baseline()
        master = next(self.docs.rglob('*模块主PRD.md'))
        with master.open('a', encoding='utf-8') as stream:
            stream.write('\n| 规则ID | 规则 |\n|---|---|\n| BR-M01-001 | 需要权限 |\n')
        self.append('规则 BR-M01-001')
        self.assertEqual(self.errors(), '')

    def test_false_definition_in_projection_does_not_hide_missing_field(self):
        self.baseline()
        dictionary = next(self.docs.rglob('*字段字典.md'))
        with dictionary.open('a', encoding='utf-8') as stream:
            stream.write('\n| 字段ID | 身份 | 差异 |\n|---|---|---|\n| FLD-MISSING | 财务 | 只读 |\n')
        self.assertIn('未定义的ID引用', self.errors())

    def test_duplicate_field_definitions(self):
        self.baseline()
        dictionary = next(self.docs.rglob('*字段字典.md'))
        with dictionary.open('a', encoding='utf-8') as stream:
            stream.write('\n| 字段ID | 字段名称 |\n|---|---|\n| FLD-01 | 数量 |\n| FLD-01 | 金额 |\n')
        self.assertIn('字段ID重复定义', self.errors())

    def test_duplicate_page_id(self):
        self.baseline()
        page_id = frontmatter(self.page().read_text(encoding='utf-8'))[0]['page_id']
        detail = next(self.docs.rglob('*详情页PRD.md'))
        text = detail.read_text(encoding='utf-8')
        detail.write_text(re.sub(r'(?m)^page_id:.*$', 'page_id: ' + page_id, text), encoding='utf-8')
        self.assertIn('页面ID重复', self.errors())

    def test_duplicate_yaml_key(self):
        self.baseline()
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8').replace('sources: []', 'sources: []\nsources: []'), encoding='utf-8')
        self.assertIn('YAML 键重复', self.errors())

    def test_frontmatter_must_be_at_start(self):
        self.baseline()
        p = self.page()
        p.write_text('# 前置正文\n' + p.read_text(encoding='utf-8'), encoding='utf-8')
        self.assertIn('frontmatter', self.errors())

    def test_unknown_document_type(self):
        self.baseline()
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8').replace('list-page-prd', 'list-page-prdd'), encoding='utf-8')
        self.assertIn('未知或缺少 document_type', self.errors())

    def test_empty_known_endpoint_body(self):
        self.baseline()
        p = next(self.docs.rglob('*端口功能清单.md'))
        p.write_text('---' + p.read_text(encoding='utf-8').split('---', 2)[1] + '---\n', encoding='utf-8')
        self.assertIn('文档正文为空', self.errors())

    def test_heading_alias_and_renumbering(self):
        self.baseline()
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8').replace('## 4. 查询区域', '## 40. 查询条件'), encoding='utf-8')
        self.assertEqual(self.errors(), '')

    def test_heading_in_fenced_code_is_not_a_real_section(self):
        self.baseline()
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8').replace('## 4. 查询区域', '```text\n## 4. 查询区域\n```'), encoding='utf-8')
        self.assertIn('缺少章节', self.errors())

    def test_chinese_and_lowercase_placeholders(self):
        self.baseline()
        self.append('{{项目名称}} {{projectName}}')
        self.assertIn('未替换模板变量', self.errors())

    def test_broken_relative_link(self):
        self.baseline()
        self.append('[缺失](missing.md)')
        self.assertIn('本地链接目标不存在', self.errors())

    def test_reference_style_link(self):
        self.baseline()
        self.append('[缺失][ref]\n\n[ref]: missing.md')
        self.assertIn('本地链接目标不存在', self.errors())

    def test_encoded_link_with_spaces_and_fragment(self):
        self.baseline()
        target = self.page().parent / '有 空格.txt'
        target.write_text('内容', encoding='utf-8')
        self.append('[文档](%E6%9C%89%20%E7%A9%BA%E6%A0%BC.txt#不检查锚点)')
        self.assertEqual(self.errors(), '')

    def test_link_and_id_inside_fence_are_ignored(self):
        self.baseline()
        self.append('```text\n[示例](missing.md) FLD-EXAMPLE\n```')
        self.assertEqual(self.errors(), '')

    def test_table_column_mismatch(self):
        self.baseline()
        self.append('| A | B |\n|---|---|\n| 1 | 2 | 3 |')
        self.assertIn('表格列数不一致', self.errors())

    def test_escaped_table_pipe(self):
        self.baseline()
        self.append('| A | B |\n|---|---|\n| 1 \\| 2 | 3 |')
        self.assertEqual(self.errors(), '')

    def test_draft_is_distinct_from_final(self):
        self.baseline()
        self.assertEqual(self.errors(), '')
        self.assertIn('待确认', self.errors(phase='final'))
        self.assertIn('sources', self.errors(phase='final'))

    def test_dry_run_creates_no_files(self):
        result = self.scaffold('--dry-run', '--include-core-pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.docs.exists())

    def test_identical_rerun_preserves_user_edits(self):
        self.baseline()
        self.append('用户追加的已确认说明。')
        before = self.fingerprint()
        result = self.scaffold('--include-core-pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_reordered_modules_preserve_existing_ids_and_contents(self):
        self.assertEqual(self.scaffold(modules=('订单', '库存')).returncode, 0)
        before = self.fingerprint()
        result = self.scaffold(modules=('库存', '订单'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_layout_change_rejected_before_writing(self):
        self.baseline()
        before = self.fingerprint()
        result = self.scaffold('--layout', 'by-identity')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, self.fingerprint())

    def test_existing_identity_layout_is_inferred(self):
        self.assertEqual(self.scaffold('--layout', 'by-identity').returncode, 0)
        before = self.fingerprint()
        self.assertEqual(self.scaffold().returncode, 0)
        self.assertEqual(before, self.fingerprint())

    def test_missing_endpoint_is_rejected_before_writing(self):
        result = self.scaffold('--include-core-pages', endpoints=())
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.docs.exists())

    def test_module_name_is_not_a_responsibility(self):
        self.baseline()
        master = self.docs / '01_项目级产品文档/02_产品总PRD.md'
        text = master.read_text(encoding='utf-8')
        self.assertIn('| 订单（M01） | [待确认] |', text)
        self.assertNotIn('| M01 | 订单 |', text)

    def test_yaml_quotes_in_names_are_escaped(self):
        result = self.scaffold(modules=('订单"示例',))
        self.assertEqual(result.returncode, 0, result.stderr)
        for p in self.docs.rglob('*.md'):
            self.assertIsInstance(frontmatter(p.read_text(encoding='utf-8'))[0], dict)

    def test_scope_paths_cannot_escape(self):
        self.baseline()
        self.assertIn('不在文档目录', self.errors(scope='files', files=['../../outside.md']))

    def test_flow_rule_is_a_reference_to_the_master(self):
        self.baseline()
        master = next(self.docs.rglob('*模块主PRD.md'))
        with master.open('a', encoding='utf-8') as stream:
            stream.write('\n| 规则ID | 规则 |\n|---|---|\n| BR-M01-001 | 需要权限 |\n')
        flow = next(self.docs.rglob('*业务流程与状态流转.md'))
        with flow.open('a', encoding='utf-8') as stream:
            stream.write('\n| 规则ID | 触发场景 |\n|---|---|\n| BR-M01-001 | 提交 |\n')
        self.assertEqual(self.errors(), '')

    def test_final_scoped_document_with_sources(self):
        self.docs.mkdir(parents=True)
        (self.docs / '补充说明.md').write_text(
            '---\ndoc_id: DOC-SUP-001\ndocument_type: supplement\n'
            'sources: ["用户已确认：仅调整显示顺序"]\n---\n# 显示顺序\n按已确认顺序展示。\n',
            encoding='utf-8')
        self.assertEqual(validate(self.docs, phase='final'), ([], []))

    def test_invalid_source_shape_is_rejected(self):
        self.baseline()
        p = self.page()
        p.write_text(p.read_text(encoding='utf-8').replace('sources: []', 'sources: true'), encoding='utf-8')
        self.assertIn('sources 必须', self.errors())

    def test_generic_page_template(self):
        from scaffold_product_docs import render
        self.baseline()
        content = render('页面PRD/其他页面PRD模板.md', dict(
            DOC_ID='DOC-GENERIC', PAGE_ID='P-M01-E01-003', ROLE_NAME='销售员',
            PAGE_NAME='编辑订单', MODULE_NAME='订单', ENDPOINT_NAME='PC',
            COMPONENT_ID='[待确认]', COMPONENT_NAME='[待确认]', DATE='2026-09-08'))
        (self.page().parent / '编辑订单.md').write_text(content, encoding='utf-8')
        self.assertEqual(self.errors(), '')


    def document(self, name, body, kind='supplement', extra=''):
        self.docs.mkdir(parents=True, exist_ok=True)
        path = self.docs / name
        path.write_text(
            f'---\ndoc_id: DOC-{path.stem}\ndocument_type: {kind}\n'
            f'sources: ["隔离测试已确认事实"]\n{extra}---\n{body}\n', encoding='utf-8')
        return path

    def test_conflicting_action_definition_in_one_document(self):
        self.document('flow.md', '## 业务流程\n| 动作ID | 动作名称 |\n|---|---|\n'
                      '| ACT-M01-001 | 保存草稿 |\n| ACT-M01-001 | 作废订单 |\n'
                      '## 状态流转\n不适用。', 'module-business-flow-state-transition')
        self.assertIn('ID冲突定义', self.errors())

    def test_identical_action_summary_and_split_controls_are_allowed(self):
        self.document('flow.md', '## 业务流程\n| 动作ID | 动作名称 |\n|---|---|\n'
                      '| ACT-M01-001 | 保存草稿 |\n\n'
                      '| 动作ID | 动作名称 |\n|---|---|\n| ACT-M01-001 | 保存草稿 |\n\n'
                      '| 动作ID | 失败处理 |\n|---|---|\n| ACT-M01-001 | 保留输入 |\n'
                      '## 状态流转\n不适用。', 'module-business-flow-state-transition')
        self.assertEqual(self.errors(), '')

    def test_malformed_table_separator_is_rejected(self):
        self.document('table.md', '# 表格\n| 字段 | 结果 |\n|---|---|---|\n| 数量 | 增加10 |')
        self.assertIn('分隔行列数', self.errors())

    def test_malformed_table_inside_code_fence_is_ignored(self):
        self.document('code.md', '# 示例\n\x60\x60\x60text\n| 字段 | 结果 |\n'
                      '|---|---|---|\n| 数量 | 增加10 |\n\x60\x60\x60')
        self.assertEqual(self.errors(), '')

    def test_selected_empty_module_is_not_skipped(self):
        self.assertEqual(self.scaffold('--scope', 'module').returncode, 0)
        (self.docs / '03_业务模块/M02_库存').mkdir()
        errors = self.errors(scope='module', modules=['M01', 'M02'])
        self.assertIn('M02_库存', errors)
        self.assertIn('模块公共文档缺少', errors)

    def test_single_empty_module_reports_missing_documents(self):
        (self.docs / '03_业务模块/M02_库存').mkdir(parents=True)
        self.assertIn('模块公共文档缺少', self.errors(scope='module', modules=['M02']))

    def test_r_and_err_references_are_checked(self):
        self.document('reference.md', '# 引用\nR-M01-MISSING 和 ERR-M01-MISSING')
        errors = self.errors()
        self.assertIn('未定义的ID引用：R-M01-MISSING', errors)
        self.assertIn('未定义的ID引用：ERR-M01-MISSING', errors)

    def test_custom_prefix_can_be_checked_without_renumbering(self):
        self.document('custom.md', '# 引用\nCUSTOM-M01-MISSING')
        self.assertEqual(self.errors(), '')
        self.assertIn('CUSTOM-M01-MISSING', self.errors(id_prefixes=['CUSTOM']))

    def test_invalid_custom_prefix_is_rejected(self):
        self.document('custom.md', '# 内容\n正常说明。')
        self.assertIn('编号前缀', self.errors(id_prefixes=['.*']))

    def test_r_and_err_definitions_resolve_in_authority_tables(self):
        self.baseline()
        master = next(self.docs.rglob('*模块主PRD.md'))
        with master.open('a', encoding='utf-8') as stream:
            stream.write('\n| 规则ID | 规则 |\n|---|---|\n| R-M01-001 | 权限检查 |\n')
        flow = next(self.docs.rglob('*业务流程与状态流转.md'))
        with flow.open('a', encoding='utf-8') as stream:
            stream.write('\n| 异常ID | 异常 |\n|---|---|\n| ERR-M01-001 | 权限不足 |\n')
        self.append('执行 R-M01-001，失败见 ERR-M01-001。')
        self.assertEqual(self.errors(), '')

    def test_master_scene_is_a_reference_to_flow(self):
        self.baseline()
        master = next(self.docs.rglob('*模块主PRD.md'))
        with master.open('a', encoding='utf-8') as stream:
            stream.write('\n| 引用场景ID | 场景 |\n|---|---|\n| SCN-M01-001 | 重复提交 |\n')
        self.assertIn('SCN-M01-001', self.errors())
        flow = next(self.docs.rglob('*业务流程与状态流转.md'))
        with flow.open('a', encoding='utf-8') as stream:
            stream.write('\n| 场景ID | 场景 |\n|---|---|\n| SCN-M01-001 | 重复提交 |\n')
        self.assertEqual(self.errors(), '')

    def test_module_only_append_keeps_previous_files(self):
        self.assertEqual(self.scaffold('--scope', 'module').returncode, 0)
        before = self.fingerprint()
        result = self.scaffold('--scope', 'module', modules=('库存',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.docs / '03_业务模块/M02_库存').is_dir())
        after = self.fingerprint()
        self.assertTrue(all(after.get(path) == digest for path, digest in before.items()))
        self.assertEqual(self.errors(), '')

    def test_module_only_subset_reuses_nonfirst_existing_module(self):
        self.assertEqual(self.scaffold('--scope', 'module', modules=('订单', '库存')).returncode, 0)
        before = self.fingerprint()
        result = self.scaffold('--scope', 'module', modules=('库存',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_new_identity_pages_use_project_endpoint_ids(self):
        result = self.scaffold('--layout', 'by-identity', '--include-core-pages',
                               roles=('甲', '乙'), endpoints=('甲=PC,APP', '乙=APP'))
        self.assertEqual(result.returncode, 0, result.stderr)
        pages = list(self.docs.rglob('*列表页PRD.md'))
        app_pages = [p for p in pages if p.parent.name.endswith('_APP')]
        self.assertEqual(len(app_pages), 2)
        self.assertTrue(all(p.parent.name == 'E02_APP' for p in app_pages))

    def test_reordered_roles_endpoints_keep_files(self):
        self.assertEqual(self.scaffold('--layout', 'by-identity', '--include-core-pages',
                                      roles=('甲', '乙'), endpoints=('甲=PC,APP', '乙=APP')).returncode, 0)
        before = self.fingerprint()
        result = self.scaffold('--layout', 'by-identity', '--include-core-pages',
                               roles=('乙', '甲'), endpoints=('乙=APP', '甲=APP,PC'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_existing_legacy_endpoint_folder_is_preserved(self):
        result = self.scaffold('--layout', 'by-identity', '--include-core-pages',
                               roles=('甲', '乙'), endpoints=('甲=PC,APP', '乙=APP'))
        self.assertEqual(result.returncode, 0, result.stderr)
        identity = self.docs / '03_业务模块/M01_订单/02_按身份/R02_乙/03_页面PRD'
        old = identity / 'E02_APP'
        legacy = identity / 'E01_APP'
        # Simulate a historical role-local endpoint number only inside this test workspace.
        self.assertTrue(old.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(legacy.resolve().is_relative_to(self.root.resolve()))
        old.rename(legacy)
        for page in list(legacy.glob('*.md')):
            page.write_text(page.read_text(encoding='utf-8').replace('R02-E02', 'R02-E01'), encoding='utf-8')
            page.rename(page.with_name(page.name.replace('R02-E02', 'R02-E01')))
        before = self.fingerprint()
        result = self.scaffold('--layout', 'by-identity', '--include-core-pages',
                               roles=('甲', '乙'), endpoints=('甲=PC,APP', '乙=APP'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_ambiguous_existing_module_numbers_stop_before_writes(self):
        (self.docs / '03_业务模块/M01_订单').mkdir(parents=True)
        (self.docs / '03_业务模块/M01_库存').mkdir()
        before = self.fingerprint()
        result = self.scaffold('--scope', 'module', modules=('客户',))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, self.fingerprint())

    def test_sanitized_module_name_collision_is_rejected(self):
        result = self.scaffold('--scope', 'module', modules=('订单/报价', '订单\\报价'))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.docs.exists())

    def test_split_function_tables_preserve_single_authority(self):
        self.baseline()
        functions = next(self.docs.rglob('*模块功能清单.md'))
        with functions.open('a', encoding='utf-8') as stream:
            stream.write('\n| 功能ID | 功能点 | 功能说明 |\n|---|---|---|\n'
                         '| F-M01-001 | 新增订单 | 保存销售资料 |\n\n'
                         '| 功能ID | 角色 | 页面ID |\n|---|---|---|\n'
                         '| F-M01-001 | 销售员 | 不适用 |\n')
        self.append('使用 F-M01-001。')
        self.assertEqual(self.errors(), '')

    def test_action_control_reference_does_not_create_definition(self):
        self.document('flow.md', '## 业务流程\n| 动作ID | 失败处理 |\n|---|---|\n'
                      '| ACT-M01-MISSING | 保留输入 |\n## 状态流转\n不适用。',
                      'module-business-flow-state-transition')
        self.assertIn('未定义的ID引用：ACT-M01-MISSING', self.errors())

    def test_append_after_nonconsecutive_module_number(self):
        (self.docs / '03_业务模块/M07_历史模块').mkdir(parents=True)
        result = self.scaffold('--scope', 'module', modules=('新模块',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.docs / '03_业务模块/M08_新模块').is_dir())
        self.assertTrue((self.docs / '03_业务模块/M07_历史模块').is_dir())

    def test_id_prefix_cli_reports_actual_coverage(self):
        self.document('custom.md', '# 引用\nCUSTOM-M01-MISSING')
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8',
                                 str(SCRIPTS / 'validate_product_docs.py'),
                                 '--project-root', str(self.root), '--id-prefix', 'CUSTOM'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1)
        self.assertIn('CUSTOM-M01-MISSING', result.stdout)
        self.assertIn('自动检查编号前缀', result.stdout)

    def test_split_module_function_template_retains_information(self):
        from doc_support import table_cells
        template = SCRIPTS.parent / 'assets/模板/业务模块主文档/模块功能清单模板.md'
        headers = set()
        for line in template.read_text(encoding='utf-8').splitlines():
            if line.startswith('| 功能ID |'):
                headers.update(table_cells(line))
        required = {'功能ID', '一级功能', '二级功能', '功能点', '业务对象', '功能说明',
                    '角色', '端口', '前置条件', '触发方式', '输入', '规则ID/核心规则',
                    '成功输出', '失败与异常', '状态影响', '页面ID', '权限要求',
                    '优先级', '版本', '状态', '来源'}
        self.assertTrue(required.issubset(headers), required - headers)

    def test_readable_trace_headers_are_valid_definitions(self):
        self.document('flow.md', '## 业务流程\n'
                      '| 动作ID | 对应页面 | 正文操作 |\n|---|---|---|\n'
                      '| ACT-M01-001 | 编辑页 | 保存内容 |\n\n'
                      '| 影响面ID | 正文中的数据名称 | 含义与归属 |\n|---|---|---|\n'
                      '| EF-M01-001 | 内容记录 | 业务模块 |\n\n'
                      '| 时点ID | 对应页面操作 | 中文时点说明 |\n|---|---|---|\n'
                      '| TP-M01-001 | 保存 | 保存成功时 |\n'
                      '## 状态流转\n| 状态ID | 名称 |\n|---|---|\n'
                      '| ST-M01-001 | 有效 |', 'module-business-flow-state-transition')
        self.assertEqual(self.errors(), '')

    def test_component_title_is_a_valid_name(self):
        self.baseline()
        self.append('| 组件ID | 标题 | 类型 |\n|---|---|---|\n'
                    '| CMP-M01-001 | 确认取消 | 弹窗 |')
        self.assertEqual(self.errors(), '')


if __name__ == '__main__':
    unittest.main()
