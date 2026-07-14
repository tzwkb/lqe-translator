# LQE SDLXLIFF 1.2 原生输入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `lqe-translator` 原生读取单个或目录批量 SDLXLIFF 1.2，保留句段、标签、上下文和保护证据，并生成固定列 LQE 报告与 corrected Excel。

**Architecture:** 新增独立 `lqe_inputs` 适配层，负责格式发现、SDLXLIFF 解析、规则匹配和可审计 manifest；`lqe_io.py` 只负责 profile/CLI 优先级、共享 LQE state 和产物发布。报告与导出按 `input_format` 分派，原表格路径保持原行为，SDLXLIFF 第一版不回写 XML。

**Tech Stack:** Python 3.14，标准库 `dataclasses/enum/fnmatch/hashlib/json/pathlib/re/xml.etree.ElementTree/unittest`，`openpyxl`。

## Global Constraints

- 本计划在 `2026-07-14-lqe-no-terminology-mode.md` 完成后执行，并复用其 scope 与原子 JSON 写入接口。
- 第一版只解析 XLIFF 1.2 + SDL namespace；XLIFF 2.0 明确失败。
- 单 TU 多 `mrk mtype="seg"` 必须按 `mid` 和 SDL seg-def 配对，不得只取第一个。
- 目录递归发现结果按 POSIX 相对路径排序；同文件内部保持 XML 文档顺序。
- 文本、边界空白、tail、嵌套内联元素、QName 和属性不得因导入而丢失。
- 未知扩展不影响句段结构时保留并记录；造成边界或配对歧义时失败，不猜测。
- 不在 state/manifest 复制 SDL header 中可能存在的大型 base64 `internal-file`。
- 内容类型、项目排除和严格 TM 保护只由显式 profile/CLI 配置启用；不得内置 CC/FF 判断。
- 默认 TM 策略只生成候选；严格三条件为 `origin=tm + percent=100 + text-match=SourceAndTarget`。
- SDL locked 段始终保护为 `SOURCE_LOCKED`；与 TM 原因和证据分开保存。
- SDL `LQE Results` 固定为 5 个来源列 + 6 个 LQE 列；不得透传全部私有 metadata。
- 第一版只生成 corrected Excel，不修改、覆盖或重建任何 SDLXLIFF XML。
- SDL 读取只写入新的 job 目标；若目标 state 或 helper artifact 已存在则失败，重新处理必须使用新 job。
- 表格输入、历史 state、评分、修订写入权和 MasterTB 流程不得回归。
- `lqe-translator` 目录当前不是 Git 仓库；不得擅自初始化仓库。每个任务以定向测试和哈希/语法检查作为检查点。

---

### Task 1: 输入格式发现与 SDLXLIFF 解析核心

**Files:**
- Create: `scripts/lqe_inputs/__init__.py`
- Create: `scripts/lqe_inputs/sdlxliff.py`
- Create: `tests/fixtures/sdlxliff/multi_segment.sdlxliff`
- Create: `tests/fixtures/sdlxliff/extensions.sdlxliff`
- Create: `tests/test_sdlxliff_input.py`

**Interfaces:**
- Produces: `detect_input_format(path: Path, requested: str) -> Literal["tabular", "sdlxliff"]`。
- Produces: `SDLXLIFFImportError(ValueError)`。
- Produces dataclasses: `SDLXLIFFOptions`、`SerializedMixedContent`、`SDLXLIFFImportResult`。
- Produces: `read_sdlxliff(path: Path, *, options: SDLXLIFFOptions) -> SDLXLIFFImportResult`。
- Produces: `serialize_mixed(element: Element, namespace_map: dict[str, str]) -> SerializedMixedContent`。

- [ ] **Step 1: 创建匿名最小 fixtures**

`multi_segment.sdlxliff` 至少包含两个 `<file>`，其中一个 TU 有两个 source/target `mrk`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2"
       xmlns:sdl="http://sdl.com/FileTypes/SdlXliff/1.0">
  <file original="dialogs.xml" source-language="zh-CN" target-language="en-US">
    <body>
      <trans-unit id="tu-1">
        <seg-source><mrk mtype="seg" mid="1"> 你<x id="x1"/>好 </mrk><mrk mtype="seg" mid="2">第二句</mrk></seg-source>
        <target><mrk mtype="seg" mid="1"> Hello<x id="x1"/> </mrk><mrk mtype="seg" mid="2">Second</mrk></target>
        <sdl:seg-defs>
          <sdl:seg id="1" conf="Translated" origin="tm" percent="100" text-match="SourceAndTarget"/>
          <sdl:seg id="2" conf="Draft" locked="true"/>
        </sdl:seg-defs>
      </trans-unit>
    </body>
  </file>
  <file original="ui.xml" source-language="zh-CN" target-language="en-US">
    <body><trans-unit id="tu-2"><source>开始</source><target>Start</target><sdl:seg-defs><sdl:seg id="3"/></sdl:seg-defs></trans-unit></body>
  </file>
</xliff>
```

`extensions.sdlxliff` 使用匿名 vendor namespace，覆盖嵌套元素、tail、`ph/bx/ex/bpt/ept/it/sub/g`、非结构性 extension metadata，以及内容为 `QUJDREVGR0g=` 的最小 `internal-file`；不得包含客户原文。

测试常量必须是 fixture 的字面预期，不得调用生产序列化器反推：

```python
XLIFF_QNAME = "{urn:oasis:names:tc:xliff:document:1.2}"
EXPECTED_SIGNATURE = (
    (XLIFF_QNAME + "g", (("id", "g1"),)),
    (XLIFF_QNAME + "x", (("id", "x1"),)),
    (XLIFF_QNAME + "bx", (("id", "bx1"),)),
    (XLIFF_QNAME + "ex", (("id", "ex1"),)),
    (XLIFF_QNAME + "ph", (("id", "ph1"),)),
    (XLIFF_QNAME + "bpt", (("id", "bpt1"),)),
    (XLIFF_QNAME + "ept", (("id", "ept1"),)),
    (XLIFF_QNAME + "it", (("id", "it1"),)),
    (XLIFF_QNAME + "sub", ()),
    (XLIFF_QNAME + "mrk", (("mid", "inner1"), ("mtype", "protected"))),
)
```

另建最小目录 fixtures：嵌套的 `a/dialogs.sdlxliff`、根目录 `b.sdlxliff`、缺 TU ID/seg ID 的合法回退、重复 TU ID、空 target、双空段、comment definition、`last_modified_by` 和三个不满足严格 TM 条件的反例。非法 XML、XLIFF 2.0、缺 source、重复完整定位键、`mid` 错配和结构性未知扩展可在测试临时目录动态生成。

- [ ] **Step 2: 写 parser 失败测试**

```python
def test_imports_all_files_and_multiple_mrk_in_order(self):
    result = read_sdlxliff(FIXTURES / "multi_segment.sdlxliff", options=SDLXLIFFOptions())
    self.assertEqual([s["id"] for s in result.segments], [0, 1, 2])
    self.assertEqual([s["source_ref"]["sdl_segment_id"] for s in result.segments], ["1", "2", "3"])
    self.assertEqual(result.segments[0]["source_ref"]["relative_path"], "multi_segment.sdlxliff")

def test_recursive_directory_order_and_missing_ids_are_stable(self):
    result = read_sdlxliff(self.recursive_fixture_dir, options=SDLXLIFFOptions())
    refs = [segment["source_ref"] for segment in result.segments]
    self.assertEqual([ref["relative_path"] for ref in refs], sorted(ref["relative_path"] for ref in refs))
    self.assertEqual(len(refs), len({tuple(ref.values()) for ref in refs}))
    self.assertTrue(any(ref["tu_id"] is None for ref in refs))
    self.assertTrue(all("tu_index" in ref for ref in refs))

def test_reads_status_comment_modifier_and_empty_target(self):
    result = read_sdlxliff(self.metadata_fixture, options=SDLXLIFFOptions())
    metadata = result.segments[0]["metadata"]["sdlxliff"]
    self.assertEqual(metadata["confirmation"], "Translated")
    self.assertEqual(metadata["comment"], "Anonymous review note")
    self.assertEqual(metadata["last_modified_by"], "AnonymousUser")
    self.assertEqual(result.segments[1]["target_plain"], "")

def test_mixed_content_preserves_tags_tails_and_whitespace(self):
    result = read_sdlxliff(FIXTURES / "extensions.sdlxliff", options=SDLXLIFFOptions())
    segment = result.segments[0]
    self.assertTrue(segment["source"].startswith(" "))
    self.assertTrue(segment["source"].endswith(" "))
    self.assertIn("<", segment["source"])
    self.assertEqual(segment["metadata"]["sdlxliff"]["source_tag_signature"], EXPECTED_SIGNATURE)
    self.assertIn("urn:vendor:test", segment["metadata"]["sdlxliff"]["source_raw_xml"])

def test_xliff2_and_ambiguous_mid_fail_with_file_context(self):
    for fixture, message in (("xliff2.xlf", "XLIFF 1.2"), ("bad_mid.sdlxliff", "mid")):
        with self.subTest(fixture=fixture):
            with self.assertRaisesRegex(SDLXLIFFImportError, message):
                read_sdlxliff(self.temp_fixture(fixture), options=SDLXLIFFOptions())
```

- [ ] **Step 3: 运行测试并确认红灯**

Run from repository root: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFParserTests`

Expected: FAIL because `lqe_inputs` does not exist.

- [ ] **Step 4: 建立适配器类型和格式发现**

定义以下稳定类型：

```python
@dataclass(frozen=True)
class SDLXLIFFOptions:
    tm_protection: str = "candidate-only"
    content_type_rules: tuple[dict, ...] = ()
    exclude_rules: tuple[dict, ...] = ()

@dataclass(frozen=True)
class SerializedMixedContent:
    display: str
    plain: str
    raw_xml: str
    tag_signature: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

@dataclass
class SDLXLIFFImportResult:
    headers: list[str]
    rows_raw: list[list[str]]
    segments: list[dict]
    source_lang: str
    target_lang: str
    input_paths: list[str]
    manifest: dict
    tm_candidates: dict
```

`detect_input_format()` 只接受 `auto/tabular/sdlxliff`。auto 单文件按后缀识别；目录递归扫描，只有 SDLXLIFF 时识别为 SDL，空目录或混合受支持格式目录失败。显式 `sdlxliff` 目录只选择递归发现的 `.sdlxliff`，允许旁存表格或说明文件但在 manifest 记录未选择的受支持文件；显式格式与单文件后缀不符时失败。表格目录仍不支持。

- [ ] **Step 5: 实现安全句段配对和混合内容序列化**

递归发现文件并按 POSIX 相对路径排序，再遍历每个 XML 的所有 `<file>` 和 TU。source 优先使用 `<seg-source>` 的顶层 `mrk[mtype=seg]`，不存在 seg-source 时才安全回退 `<source>`；target 的 segmentation marker 必须按 `mid` 一一配对，内层非 segmentation `mrk` 作为混合内容保留。无 segmentation marker 时只允许一个 source/target 与至多一个 seg-def 的安全回退。缺 target 节点生成空 target；TU ID 或 SDL Segment ID 缺失时把字段保留为 `None` 并用 `tu_index/segment_index` 文档序号参与定位。`source_ref` 固定包含 `relative_path/file_index/tu_id/tu_index/sdl_segment_id/segment_index`。不同 `<file>` 中重复 TU ID 合法；缺 source、同一内部 file 中重复 TU+segment 业务定位键、重复 mid、多个 seg-def 无边界或 `mid` 错配立即抛错。

根节点必须是 XLIFF 1.2 namespace，且文档使用受支持 SDL namespace；2.0 或 namespace 伪装立即失败。用 `iterparse(start-ns)` 收集 namespace map，序列化器不得调用 `.strip()`；属性按展开 QName 排序，text/tail 逐字保留，原 namespace URI 与 local name 不丢失。`plain` 只拼接可翻译文本，不包含标签名和属性，供词数使用；`display` 保留确定性可读标签，供 Markup 检查。解析 comment definitions、seg-def 状态、`s:value key="last_modified_by"` 等已验证元数据。所有结构错误包含相对路径、TU/segment 上下文及解析器可用行号。

- [ ] **Step 6: 运行 parser 测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFParserTests`

Expected: all parser tests `OK`.

- [ ] **Step 7: 非 Git 检查点**

Run: `python3 -m py_compile scripts/lqe_inputs/__init__.py scripts/lqe_inputs/sdlxliff.py tests/test_sdlxliff_input.py`

Expected: exit code 0.

### Task 2: Profile 输入规则、扩展容错、TM/locked 和 manifest

**Files:**
- Modify: `scripts/lqe_inputs/sdlxliff.py`
- Test: `tests/test_sdlxliff_input.py`

**Interfaces:**
- Produces: `validate_options(raw: object, *, cli_protect_exact_tm: bool = False) -> SDLXLIFFOptions`。
- Produces: `match_content_type(relative_path: str, rules: tuple[dict, ...]) -> tuple[str | None, str | None]`。
- Produces: `match_exclusions(candidate: dict, rules: tuple[dict, ...]) -> list[dict]`。
- Produces: `is_exact_tm(metadata: dict) -> bool`。
- Produces manifest schema with files, hashes, languages, namespaces, rule matches, exclusions and protection evidence。

- [ ] **Step 1: 写规则和保护失败测试**

```python
def test_profile_rules_are_strict_and_auditable(self):
    options = validate_options({
        "tm_protection": "candidate-only",
        "content_type_rules": [{"id": "dialog", "glob": "**/dialog*.sdlxliff", "content_type": "剧情/对话"}],
        "exclude_rules": [{"id": "rejected", "field": "confirmation", "equals": "Rejected", "reason": "Client excluded"}],
    })
    result = read_sdlxliff(self.rule_fixture_dir, options=options)
    self.assertEqual(result.segments[0]["content_type"], "剧情/对话")
    self.assertEqual(result.manifest["excluded"][0]["rule_ids"], ["rejected"])
    with self.assertRaisesRegex(SDLXLIFFImportError, "segment.id"):
        validate_options({"exclude_rules": [{"id": "bad", "field": "segment.id", "equals": 1, "reason": "unstable"}]})

def test_tm_candidate_and_locked_protection_are_separate(self):
    default = read_sdlxliff(FIXTURES / "multi_segment.sdlxliff", options=SDLXLIFFOptions())
    self.assertFalse(default.segments[0].get("protected", False))
    self.assertEqual(default.tm_candidates["candidate_ids"], [0])
    self.assertEqual(default.segments[1]["protected_reason"], "SOURCE_LOCKED")
    strict = read_sdlxliff(
        FIXTURES / "multi_segment.sdlxliff",
        options=SDLXLIFFOptions(tm_protection="protect-exact-source-and-target"),
    )
    self.assertEqual(strict.segments[0]["protected_reason"], "TM_100_MATCH")
    self.assertEqual(strict.segments[1]["protected_reason"], "SOURCE_LOCKED")

def test_100_percent_alone_is_not_an_exact_tm_candidate(self):
    result = read_sdlxliff(self.tm_negative_fixture, options=SDLXLIFFOptions(
        tm_protection="protect-exact-source-and-target"
    ))
    self.assertEqual(result.tm_candidates["candidate_ids"], [])
    self.assertFalse(any(segment.get("protected") for segment in result.segments))

def test_unknown_extension_is_recorded_or_fails_when_ambiguous(self):
    safe = read_sdlxliff(FIXTURES / "extensions.sdlxliff", options=SDLXLIFFOptions())
    self.assertIn("urn:vendor:test", safe.manifest["extension_namespaces"])
    self.assertNotIn("QUJDREVGR0g=", json.dumps(safe.manifest))
    self.assertTrue(safe.manifest["files"][0]["internal_file"]["present"])
    with self.assertRaisesRegex(SDLXLIFFImportError, "urn:vendor:ambiguous"):
        read_sdlxliff(self.ambiguous_extension_fixture, options=SDLXLIFFOptions())

def test_no_filename_or_directory_content_type_inference(self):
    result = read_sdlxliff(self.path_named_cc_ff, options=SDLXLIFFOptions())
    self.assertTrue(all(not segment.get("content_type") for segment in result.segments))
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFRuleTests`

Expected: FAIL because options validation and rule matching do not exist.

- [ ] **Step 3: 实现严格 profile schema**

允许 `tm_protection/content_type_rules/exclude_rules` 三个顶层键。规则 ID 必填且唯一；content rule 必须有 `glob/content_type`；exclude rule 必须有 `field/reason`，且 `equals`/`regex` 恰好出现一个。允许字段固定为 `relative_path/file_original/confirmation/origin/locked/source/target`。glob 对规范化 POSIX 相对路径做大小写敏感匹配；拒绝段号、未知字段、空 reason、畸形 glob/regex 和不受支持的 TM policy。不得读取 CC、FF、父目录名或普通文件名来推断 content type。

- [ ] **Step 4: 实现规则匹配和保护证据**

content rule 第一个 glob 命中生效；exclude rule 可选 glob 且所有命中都记录。双空段作为内置 `blank-both-sides` 排除，单侧空保留。`is_exact_tm()` 对 origin/text-match 不区分大小写，对 percent 只接受可解析且数值等于 100；缺任一字段返回 False。

locked 与 TM 分别写 `protection_evidence`；同段同时满足时 `SOURCE_LOCKED` 为不可覆盖原因，TM 仍记录为候选证据。`tm_candidates.json` 使用 `candidate_ids` 和逐段三条件 evidence，不把候选误命名为 protected。manifest 至少包含 importer schema/version、排序后的输入文件与 SHA-256、语言声明、namespace、规则命中、纳入/排除计数、TM policy、locked/TM 逐段证据和未选择文件；不保存大型 internal-file 内容，只记录其存在与大小。

- [ ] **Step 5: 运行规则测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFRuleTests`

Expected: all rule tests `OK`.

- [ ] **Step 6: manifest 可序列化检查点**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFRuleTests.test_manifest_is_json_serializable_and_has_file_hashes`

Expected: `OK` and every imported file has a 64-character SHA-256.

### Task 3: 接入 lqe_io、语言契约、原子产物和上下文去重

**Files:**
- Modify: `scripts/lqe_engine.py:190-260`
- Modify: `scripts/lqe_io.py:1-548`
- Modify: `scripts/lqe_io.py:548-675`
- Modify: `scripts/lqe_io.py:1322-1340`
- Modify: `scripts/lqe_chunk.py:103-122`
- Modify: `scripts/lqe_batch.py:70-120`
- Test: `tests/test_sdlxliff_input.py`

**Interfaces:**
- Produces: `normalize_language_tag(value: str) -> str`。
- Produces: `language_tags_match(configured: str, declared: str) -> bool`。
- Produces CLI: `--input-format {auto,tabular,sdlxliff}` and `--protect-exact-tm`。
- Produces common state field: every new read writes canonical `input_format`；SDL additionally writes `input_paths/source_manifest_path/tm_candidates_path/source_ref/metadata.sdlxliff/source_plain/target_plain/context_note`。
- Preserves tabular runtime validation for `--source-col/--target-col`。
- Changes protected-file compatibility: explicit `protect-segments` accepts `candidate_ids` in `tm_candidates.json` without treating candidates as protected during read。

- [ ] **Step 1: 写 CLI、语言、原子性和表格回归失败测试**

```python
def test_cli_reads_directory_without_source_target_columns(self):
    result = self.run_io(
        "read", "--input", self.fixture_dir, "--input-format", "sdlxliff",
        "--source-lang", "zh", "--target-lang", "en",
        "--out", self.job / "state.json",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    state = read_json(self.job / "state.json")
    self.assertEqual(state["input_format"], "sdlxliff")
    self.assertEqual(state["headers"], ["来源文件", "TU ID", "SDL Segment ID", "原文", "译文"])

def test_language_and_structure_errors_are_atomic(self):
    result = self.run_io("read", "--input", self.mixed_language_dir, "--out", self.job / "state.json")
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse((self.job / "state.json").exists())
    self.assertFalse((self.job / "source_manifest.json").exists())
    self.assertFalse((self.job / "tm_candidates.json").exists())

def test_existing_sdl_job_artifact_is_not_overwritten(self):
    state_path = self.job / "state.json"
    state_path.write_text("sentinel", encoding="utf-8")
    result = self.run_io("read", "--input", self.fixture_dir, "--out", state_path)
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(state_path.read_text(encoding="utf-8"), "sentinel")

def test_explicit_sdl_directory_ignores_but_records_other_supported_files(self):
    result = self.run_io(
        "read", "--input", self.mixed_input_dir, "--input-format", "sdlxliff",
        "--out", self.job / "state.json",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    manifest = read_json(self.job / "source_manifest.json")
    self.assertEqual(manifest["unselected_supported_files"], ["notes.csv"])

def test_tabular_read_still_requires_columns(self):
    result = self.run_io("read", "--input", self.csv, "--out", self.job / "state.json")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("--source-col", result.stderr)

def test_tabular_csv_tsv_and_xlsx_success_paths_are_unchanged(self):
    for source in (self.csv, self.tsv, self.xlsx):
        with self.subTest(source=source.name):
            state = self.read_tabular(source, source_col="Source", target_col="Target")
            self.assertEqual(state["input_format"], "tabular")
            self.assertEqual([s["source"] for s in state["segments"]], ["甲", "乙"])

def test_cli_exact_tm_overrides_candidate_only_profile(self):
    result = self.run_io(
        "read", "--input", self.exact_tm_fixture, "--project", self.candidate_profile,
        "--protect-exact-tm", "--out", self.job / "state.json",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(read_json(self.job / "state.json")["segments"][0]["protected_reason"], "TM_100_MATCH")

def test_candidate_file_requires_explicit_protect_segments_decision(self):
    self.read_exact_tm_job(tm_protection="candidate-only")
    state = read_json(self.job / "state.json")
    self.assertFalse(state["segments"][0].get("protected", False))
    result = self.run_io(
        "protect-segments", "--state", self.job / "state.json",
        "--protected-file", self.job / "tm_candidates.json",
        "--reason", "TM_100_MATCH",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    protected = read_json(self.job / "state.json")["segments"][0]
    self.assertTrue(protected["protected"])
    self.assertEqual(protected["protected_reason"], "TM_100_MATCH")

def test_wordcount_uses_plain_text_not_inline_attributes(self):
    state = self.read_inline_job(
        source='甲<x id="attribute_should_not_count"/>乙 AB',
        wordcount_basis="source-chars",
    )
    self.assertEqual(state["wordcount"], 3)
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFIntegrationTests`

Expected: FAIL because `read` still requires source/target columns and opens input with openpyxl.

- [ ] **Step 3: 实现语言规范和输入分发**

`normalize_language_tag()` 把 `_` 转为 `-`，基础语言小写、四字母 script Title Case、两字母 region 大写并保留其余子标签；`language_tags_match()` 允许 profile 基础码 `zh` 匹配声明 `zh-CN`，但完整 `zh-TW` 不匹配 `zh-CN`。同批多个声明语言对或 profile/CLI 冲突时，在发布任何 job artifact 前失败。

`read` parser 将 source/target 参数改为可选，tabular 分支进入时自行验证必填；`--protect-exact-tm` 用于 tabular 时明确失败。`cmd_read()` 先检测格式、解析全部 SDL 文件和语言，再创建/发布 job artifacts。

- [ ] **Step 4: 构造 SDL state 和原子辅助文件**

SDL importer 结果映射为固定 headers/rows、连续 ID、逐段 source_ref 和 metadata；`metadata.sdlxliff` 保留 `file_original/source_language/target_language/confirmation/origin/match_percent/text_match/locked/last_modified_by/comment/content_type` 和混合内容证据。顶层 `content_type` 镜像规则结果，`context_note` 使用解析后的 comment（无 comment 时为 `None`），供 chunk/prompt 使用。写入前若目标 `state.json/source_manifest.json/tm_candidates.json/scope.json` 任一已存在则失败，要求使用新 job。所有 JSON 先完整序列化到同目录 staging 临时文件，全部成功后依次 `replace()` helper artifacts，并最后 `replace()` state 作为提交标志；任何解析、语言或 staging 失败都不发布正式文件。发布中断时不得留下 state，并清理本次 helper artifacts。

`tm_candidates.json` 同时写 `candidate_ids` 与含 `id/evidence/source_ref` 的 `segments`。扩展现有 protected-file 解析器显式接受 `candidate_ids`；只有用户实际执行 `protect-segments --protected-file tm_candidates.json` 时才把候选变为 job 保护决定，`read` 本身不得自动消费该文件。

词数使用 `segment.get("source_plain", segment["source"])` 或 target_plain。style guide、checks、confirmed rules、threshold 和 no-terminology scope 继续走共享初始化代码。

- [ ] **Step 5: 把审查上下文加入 chunk 与去重键**

现有 `(source,target,protected)` 去重键扩展为 `(source,target,protected,content_type,text_type_context,context_note)`。chunk 行保留 `content_type/context_note/source_ref`，避免同文同译在剧情与 UI 中错误共用检查结果。`lqe_batch` prompt 同样显示非空 CONTENT_TYPE/CONTEXT。

- [ ] **Step 6: 运行 integration 测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFIntegrationTests`

Expected: all integration tests `OK`.

- [ ] **Step 7: 表格回归检查点**

Run: `python3 scripts/run_tests.py`

Expected: current suite remains green before report/export changes.

### Task 4: 固定报告表、corrected Excel 和通用保护原因

**Files:**
- Modify: `scripts/lqe_io.py:675-760`
- Modify: `scripts/lqe_io.py:799-1148`
- Modify: `scripts/lqe_io.py:1200-1315`
- Modify: `scripts/aggregate_sheets.py`
- Modify: `tests/test_corrected_ownership.py`
- Test: `tests/test_sdlxliff_input.py`

**Interfaces:**
- Produces: `_report_source_table(state: dict) -> tuple[list[str], list[list[object]]]`。
- Produces: `_segment_filename(state: dict, segment: dict) -> str`。
- Produces: `_protection_reason(segment: dict, protected_ids: set[int]) -> str`。
- Produces: `_export_sdlxliff_xlsx(state_path: Path, state: dict, result_entries: dict) -> Path`。
- Changes report labels: `Protected` and `Protection Evidence` replace TM-only labels where both TM and SOURCE_LOCKED are possible.

- [ ] **Step 1: 写报告、导出和保护原因失败测试**

```python
def test_report_has_fixed_eleven_columns_and_per_file_names(self):
    self.finish_sdl_job()
    report = next(self.job.glob("*_lqe.xlsx"))
    workbook = openpyxl.load_workbook(report, data_only=True)
    try:
        sheet = workbook["LQE Results"]
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers, [
            "来源文件", "TU ID", "SDL Segment ID", "原文", "原译",
            "建议译文", "处理方式", "错误详情", "LQE_Iter", "Protected", "Protection Evidence",
        ])
        scorecard_values = [cell.value for row in workbook["LQA Scorecard"] for cell in row]
        self.assertIn("dialogs.xml", scorecard_values)
        self.assertIn("ui.xml", scorecard_values)
    finally:
        workbook.close()

def test_export_creates_corrected_xlsx_without_touching_xml(self):
    before = {p: sha256(p) for p in self.input_files}
    result = self.run_io("export", "--state", self.job / "state.json", "--errors", self.job / "errors.json")
    self.assertEqual(result.returncode, 0, result.stderr)
    output = next(self.job.glob("*_corrected.xlsx"))
    workbook = openpyxl.load_workbook(output, data_only=True)
    try:
        self.assertEqual([c.value for c in workbook.active[1]], ["来源文件", "TU ID", "SDL Segment ID", "原文", "译文"])
    finally:
        workbook.close()
    self.assertEqual(before, {p: sha256(p) for p in self.input_files})

def test_apply_fixes_preserves_source_locked_reason(self):
    self.run_apply_fixes_on_locked_segment()
    segment = read_json(self.job / "state.json")["segments"][0]
    self.assertEqual(segment["protected_reason"], "SOURCE_LOCKED")
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFOutputTests`

Expected: FAIL because report/export still assume a source workbook and TM-only protection.

- [ ] **Step 3: 增加严格报告行构造层**

`_report_source_table()` 对 tabular 返回现有 headers/rows，但验证 `len(rows_raw) == len(segments)`，不再用可能静默截断的 `zip()`。SDL 从 segment/source_ref 构造固定五列，不读取全部 metadata；第一列与 `_segment_filename()` 一样，优先使用非空 `metadata.sdlxliff.file_original`，缺失时回退 `source_ref.relative_path`。物理 SDLXLIFF 路径始终保留在 `source_ref`/manifest。测试数据给 `dialogs.xml` 和 `ui.xml` 各放至少一个错误，确保 Scorecard detail 实际覆盖两个 `<file>`。

- [ ] **Step 4: 修复通用保护原因和 apply-fixes**

报告、跳过记录和 LQE Results 使用 segment 原有 `protected_reason`/`protection_evidence`；只有缺失原因的旧 state 才回退 `TM_100_MATCH`。`cmd_apply_fixes()` 不得把已有 `SOURCE_LOCKED` 覆盖为 TM。locked+TM 同时命中时主原因保持 SOURCE_LOCKED，证据同时保留。

- [ ] **Step 5: 实现 SDL corrected Excel 分支**

`cmd_export()` 在 CSV/XLSX 逻辑之前检查 `input_format == "sdlxliff"`。新 workbook 只写固定五列，以程序验证后的非空 corrected 覆盖译文；受保护、需人工确认但无 corrected、无需修改段保持原译。导出的来源文件使用与报告相同的 `file_original`→`relative_path` 回退。不得调用 XML writer。

`aggregate_sheets.py` 若遇到 SDL child state，明确退出 `SDLXLIFF jobs are not multi-sheet workbooks`，不得出现 openpyxl/KeyError。

- [ ] **Step 6: 运行 output 测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFOutputTests tests.test_corrected_ownership.CorrectedOwnershipOutputTests`

Expected: all selected tests `OK`.

- [ ] **Step 7: 原文件哈希检查点**

Run: `python3 -m unittest -v tests.test_sdlxliff_input.SDLXLIFFOutputTests.test_export_creates_corrected_xlsx_without_touching_xml`

Expected: `OK`; every input SDLXLIFF SHA-256 is unchanged.

### Task 5: 用户文档、总测试入口和完整回归

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_ZH.md`
- Modify: `PM_GUIDE.html`
- Modify: `projects/README.md`
- Modify: `tests/test_documented_contract.py`
- Modify: `tests/test_plain_language.py`
- Modify: `scripts/run_tests.py:760-785`

**Interfaces:**
- Documents: SDLXLIFF 1.2 single/directory input, `--input-format`, `--protect-exact-tm`, profile `sdlxliff` rules, artifacts and no XML writeback boundary。
- Adds regression suite: `tests.test_sdlxliff_input` to `run_tests.py::t25()`。

- [ ] **Step 1: 写文档契约失败测试**

```python
def test_skill_documents_sdlxliff_input_and_boundaries(self):
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    self.assertIn("--input-format sdlxliff", skill)
    self.assertIn("--protect-exact-tm", skill)
    self.assertIn("source_manifest.json", skill)
    self.assertIn("第一版不回写 SDLXLIFF XML", skill)

def test_projects_readme_documents_sdlxliff_rules(self):
    text = (ROOT / "projects/README.md").read_text(encoding="utf-8")
    self.assertIn('"content_type_rules"', text)
    self.assertIn('"exclude_rules"', text)
    self.assertIn('"tm_protection"', text)

def test_run_tests_t25_includes_sdlxliff_suite(self):
    runner = (ROOT / "scripts/run_tests.py").read_text(encoding="utf-8")
    self.assertIn('"tests.test_sdlxliff_input"', runner)
```

- [ ] **Step 2: 运行文档测试并确认红灯**

Run: `python3 -m unittest -v tests.test_documented_contract`

Expected: FAIL because current docs list only Excel/CSV/TSV.

- [ ] **Step 3: 同步文档和总测试入口**

更新输入收集、初始化、TM 保护、报告导出、文件结构和验证章节；列出固定报告列、manifest、候选/严格 TM 差异、locked 保护、未知扩展策略及 XLIFF 2.0/XML 回写边界。`run_tests.py::t25()` 增加 `tests.test_sdlxliff_input`。

- [ ] **Step 4: 运行定向 SDL 和无术语组合测试**

Run: `python3 -m unittest -v tests.test_sdlxliff_input tests.test_no_terminology_mode tests.test_documented_contract tests.test_plain_language`

Expected: all selected tests `OK`.

- [ ] **Step 5: 运行全部现有 unittest**

Run: `python3 -m unittest -v tests.test_correction_builder tests.test_corrected_ownership tests.test_plain_language tests.test_documented_contract tests.test_mastertb_module_contract tests.test_no_terminology_mode tests.test_sdlxliff_input`

Expected: all tests `OK`.

- [ ] **Step 6: 运行完整 skill 回归**

Run: `python3 scripts/run_tests.py`

Expected: all checks pass；文档契约测试确认 T25 的 subprocess argv 包含 `tests.test_sdlxliff_input` 和 `tests.test_no_terminology_mode`。`run_tests.py` 的顶层计数按 check group 计，不要求因同一 T25 内增加 unittest 模块而大于当前 151。

- [ ] **Step 7: 最终范围检查点**

Run: `rg -n "prepare_sdlxliff|skip_terminology|create_skipped_terminology_outputs|filter_precheck" SKILL.md README.md README_ZH.md PM_GUIDE.html projects/README.md scripts docs/check_modules`

Expected: no standard workflow depends on job-local scripts; historical job files remain untouched outside the skill directory.
