# LQE Scorecard Filename 修复：开发日志与测试验收报告

## 1. 基本信息

| 项目 | 内容 |
|---|---|
| 任务 | `0712_CC_FF_20260713` |
| 代码仓库 | `Langlobal/lqe-translator` |
| 修复日期 | 2026-07-14 |
| 修复对象 | LQE 报告 `LQA Scorecard` 的错误明细 `File name` 列 |
| 影响分组 | CC、FF |
| 运行模式 | 单轮 LQE |
| 验收结论 | PASS |

## 2. 问题描述

修复前，`LQA Scorecard` 顶部的任务级文件名和下方错误明细的 `File name` 使用了同一个数据来源。

任务通过汇总工作簿运行时，明细行错误地统一显示汇总文件名：

```text
0712_CC_review_source
0712_FF_review_source
```

明细行应显示每个 Segment 对应的原始来源相对路径，例如：

```text
7月11日AIPE交稿/03_dialogs_words_text_AIPE结果.xlsx.sdlxliff
新手引导配置表.xlsx.sdlxliff
```

顶部 `B4` 的任务级汇总文件名用途正确，不属于本次缺陷。

## 3. 根因分析

原生成逻辑直接使用汇总输入文件名填充所有错误明细：

```python
"filename": Path(state["input_path"]).stem,
```

`state["input_path"]` 指向 `*_review_source.xlsx`，因此每条明细都得到相同的汇总名。

真实来源路径并未丢失，已经保存在：

```text
state.headers 中的“来源相对路径”列
state.rows_raw 中各 Segment 对应的原始行
```

缺陷属于报告生成器取错字段，不是输入数据缺失或 Excel 手工填写错误。

## 4. 开发日志

### 4.1 首次复现

使用两个来源文件构造回归场景：

```text
day1/first.xlsx.sdlxliff
day2/second.xlsx.sdlxliff
```

首次运行测试时，实际结果为：

```python
["aggregate_review_source", "aggregate_review_source"]
```

预期结果为：

```python
["day1/first.xlsx.sdlxliff", "day2/second.xlsx.sdlxliff"]
```

首次测试结果：FAIL，成功复现原问题。

### 4.2 生成器修复

修改文件：

```text
scripts/lqe_io.py
```

#### 新增 `_segment_filename()`

新增来源文件解析函数：

```python
def _segment_filename(state, segment, raw_row=None):
    fallback = Path(state["input_path"]).stem
    headers = state.get("headers") or []
    try:
        source_path_index = headers.index("来源相对路径")
    except ValueError:
        return fallback

    if raw_row is None:
        for candidate, row in zip(
            state.get("segments", []),
            state.get("rows_raw", []),
        ):
            if candidate.get("id") == segment.get("id"):
                raw_row = row
                break

    if not raw_row or source_path_index >= len(raw_row):
        return fallback

    value = raw_row[source_path_index]
    return (
        str(value).strip()
        if value is not None and str(value).strip()
        else fallback
    )
```

行为规则：

1. 优先读取当前 Segment 的 `来源相对路径`。
2. 未直接传入原始行时，按 Segment ID 查找对应的 `rows_raw`。
3. 字段不存在、原始行不存在或字段为空时，回退到原汇总文件名。
4. 回退逻辑用于兼容不含 `来源相对路径` 的历史任务。

#### 建立 Segment ID 与原始行映射

```python
raw_rows_by_id = {
    segment["id"]: row
    for segment, row in zip(
        segments,
        state.get("rows_raw", []),
    )
}
```

映射关系：

```text
错误记录 ID
→ Segment ID
→ rows_raw 原始行
→ 来源相对路径
→ Scorecard File name
```

该映射避免依赖错误明细的顺序。一个 Segment 有多个问题时，每条问题仍使用同一个正确来源文件。

#### 替换明细 filename 写入逻辑

修改前：

```python
"filename": Path(state["input_path"]).stem,
```

修改后：

```python
"filename": _segment_filename(
    state,
    seg,
    raw_rows_by_id.get(seg["id"]),
),
```

该修改只影响错误明细的 `File name`，不修改顶部任务级汇总文件名。

#### 调整来源路径列宽

```python
filename_width = (
    70
    if "来源相对路径" in (state.get("headers") or [])
    else 22
)
```

存在来源相对路径时，Scorecard A 列宽度设为 70；历史任务继续使用 22。

### 4.3 新增回归测试

修改文件：

```text
tests/test_corrected_ownership.py
```

新增测试：

| 测试 | 验证内容 |
|---|---|
| `test_scorecard_detail_uses_each_segments_source_relative_path` | 多来源任务的每条 Scorecard 明细使用对应来源路径 |
| `test_scorecard_source_relative_path_column_is_wide_enough` | 存在来源相对路径时，A 列宽度不小于 70 |

### 4.4 交付校验器修正

修改文件：

```text
/Users/spellbook/Documents/LQE 3/jobs/0712_CC_FF_20260713/verify_delivery.py
```

Excel 打开工作簿时会生成 `.~*.xlsx` 锁文件。校验器增加锁文件过滤：

```python
def workbook(job: Path, pattern: str) -> Path:
    return next(
        path
        for path in job.glob(pattern)
        if not path.name.startswith(".~")
    )
```

该修改只影响交付校验文件选择，不改变报告内容。

### 4.5 重新生成报告

使用修复后的生成器重新生成：

```text
/Users/spellbook/Documents/LQE 3/jobs/0712_CC_FF_20260713/CC/0712_CC_FF_20260713_CC_lqe.xlsx
/Users/spellbook/Documents/LQE 3/jobs/0712_CC_FF_20260713/FF/0712_CC_FF_20260713_FF_lqe.xlsx
```

评分和问题数据未重新定义，报告得分保持：

| 分组 | 分数 | 状态 | 问题数 |
|---|---:|---|---:|
| CC | 98.59 | PASS | 235 |
| FF | 98.06 | PASS | 43 |

## 5. 测试记录

### 5.1 针对性回归测试

执行命令：

```bash
python3 -m unittest -v \
  tests.test_corrected_ownership.CorrectedOwnershipOutputTests.test_scorecard_detail_uses_each_segments_source_relative_path \
  tests.test_corrected_ownership.CorrectedOwnershipOutputTests.test_scorecard_source_relative_path_column_is_wide_enough
```

修复后结果：

```text
Ran 2 tests
OK
```

结论：2/2 通过。

### 5.2 修复完成时的完整回归测试

执行命令：

```bash
python3 scripts/run_tests.py
```

结果：

```text
151/151 passed — all green
```

### 5.3 Python 语法检查

执行命令：

```bash
python3 -m py_compile \
  scripts/lqe_io.py \
  tests/test_corrected_ownership.py
```

结果：退出码 0。

## 6. 实际文件验收

### 6.1 Filename 逐行映射

| 分组 | Scorecard 明细范围 | 明细行 | 正确来源文件数 | 汇总名残留 | 错配 |
|---|---|---:|---:|---:|---:|
| CC | `A37:A271` | 235 | 13 | 0 | 0 |
| FF | `A37:A79` | 43 | 1 | 0 | 0 |

说明：

- CC 的 21 个输入文件中，有 13 个文件产生错误明细，因此 Scorecard 出现 13 个来源文件。
- FF 的全部错误均来自 `新手引导配置表.xlsx.sdlxliff`。
- CC、FF 顶部 `B4` 继续显示任务级汇总文件名，符合设计。

### 6.2 工作簿结构与公式检查

两份报告均确认包含以下工作表：

```text
说明·导读
LQA Scorecard
LQE Results
```

检查结果：

| 检查项 | CC | FF |
|---|---|---|
| XLSX ZIP 完整性 | PASS | PASS |
| 工作簿可加载 | PASS | PASS |
| 工作表结构 | PASS | PASS |
| 公式错误扫描 | 0 | 0 |
| Filename 映射 | PASS | PASS |
| 顶部汇总名保持 | PASS | PASS |

公式错误扫描范围包括：

```text
#REF!
#DIV/0!
#VALUE!
#NAME?
#N/A
```

### 6.3 视觉验收

对 CC、FF 的全部三个工作表分别进行渲染检查：

- `说明·导读`：内容完整，标题、说明和表格可读。
- `LQA Scorecard`：来源路径可见，表头和明细对齐，无明显截断。
- `LQE Results`：原始列、建议译文、处理方式和错误详情结构正常。

视觉验收结论：PASS。

### 6.4 交付数据一致性

| 分组 | 输入文件 | Segment | 词数 | 问题 | 修改目标行 | TM 保护段 | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| CC | 21 | 1,471 | 36,616 | 235 | 172 | 2 | PASS |
| FF | 1 | 344 | 6,898 | 43 | 30 | 0 | PASS |

两组输入文件集合保持隔离，原始 SDLXLIFF 和原始工作簿未改写。

## 7. 文件哈希

| 文件 | SHA-256 |
|---|---|
| `CC/0712_CC_FF_20260713_CC_lqe.xlsx` | `8ac837a2eb8b753000d830f5d39ffb980adf565e5a455de11a82db11d28e2136` |
| `FF/0712_CC_FF_20260713_FF_lqe.xlsx` | `219a1547c38ae4cf66625c8ff3674274f08fab0857d5ea945a586cd7960f1c53` |

机器可读验收记录：

```text
/Users/spellbook/Documents/LQE 3/jobs/0712_CC_FF_20260713/verification_report.json
```

## 8. 验收标准与结论

| 验收标准 | 结果 |
|---|---|
| Sheet2 明细不再统一使用汇总文件名 | PASS |
| 每条错误使用对应 Segment 的来源相对路径 | PASS |
| 缺少来源字段时保持向后兼容 | PASS |
| 顶部任务级汇总文件名不受影响 | PASS |
| CC、FF 全部受影响报告已重新生成 | PASS |
| 针对性测试通过 | PASS |
| 完整回归测试通过 | PASS |
| 工作簿完整性、公式和视觉检查通过 | PASS |

最终结论：本次 Filename 缺陷已在报告生成器中修复，CC、FF 两份报告均完成重新生成和验收，无遗留错配。
