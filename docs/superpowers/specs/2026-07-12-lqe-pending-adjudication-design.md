# LQE 待人工裁决门禁设计

## 目标

让“错误成立，但具体修正译法仍需 PM/TB 裁决”的段落继续进入 LQE 报告和计分，同时禁止其候选译法自动进入修正稿或自动迭代。标准交付默认只包含 LQE 报告和修正稿；独立裁决表不再隐式生成。

## 数据模型

在段级评估条目上增加可选字段：

```json
{
  "id": 23,
  "errors": [],
  "corrected": "候选完整译文",
  "correction_status": "pending_adjudication"
}
```

允许值：

- `suggested`：普通 AI 建议；缺省值，兼容旧任务。
- `pending_adjudication`：错误保留并计分，候选仅供报告审阅，禁止落入修正稿或 `apply-fixes`。
- `approved`：已由 PM/TB 批准，可正常落入修正稿或迭代。

状态属于整段 correction，而不是单条 error，因为导出和迭代写回均以整段完整译文为单位。
若同一段同时含普通可修错误和待裁决错误，`pending_adjudication` 优先，整段保持原译；普通修正也延后到裁决后统一落地。这样会牺牲局部自动修正率，但不会把多 lens 的完整句候选错误拆拼。本批 76 个 pending 段中有 7 个属于这种混合段。

## 状态传播

1. Lens 输出允许携带 `correction_status`。
2. `_norm_lens`、`merge-lenses`、dedup broadcast 和最终 `merge` 必须保留该字段。
3. 同段任一 lens 标记 `pending_adjudication` 时，合并结果保持 pending。
4. 多 lens 出现多个非空候选且未完成显式整合时，默认 pending，禁止仅凭优先级自动落地。
5. 兼容旧任务：字段缺失时视为 `suggested`；本次 job 通过一次性迁移把 76 个已确认候选显式标为 pending。

## 报告行为

- 错误仍进入 `LQA Scorecard`，建议译文仍显示。
- 同一 iteration 重新执行 `write` 时，必须用本次 errors 替换 `error_history` 的末条记录，保证状态迁移能够进入重生成报告。
- `LQE Results.LQE_Status` 对 pending 行显示 `Pending Adjudication`。
- 导读明确说明 pending 候选不可直接落地。
- Scorecard 的 `Fixed` 列对 pending 行显示 `Pending`。
- 评分公式不因 correction 状态改变；状态控制的是修正译文是否可落地，而不是错误是否存在。

## 修正稿与迭代行为

- `suggested` / `approved`：按现有逻辑输出建议译文，状态分别显示 `AI修正` / `人工批准`。
- `pending_adjudication`：保留原译，状态显示 `待人工裁决`。
- `apply-fixes` 必须跳过 pending，并将跳过原因记录到本轮历史。
- CSV/TSV/XLSX 使用同一门禁和计数口径。

## 标准收尾与产物

- `finalize_job.sh` 接受显式 job 目录，避免因固定 skill-root 路径而改走手工旁路。
- 默认产物白名单：`*_lqe.xlsx`、`*_corrected.xlsx`。
- 独立 `待人工裁决_*.xlsx` 仅在未来增加明确 CLI 开关且用户授权时生成；本次不实现该可选功能。
- 本次现有三份交付先备份到 `superseded_20260712/`，再在原标准路径生成两份修复后的标准文件。

## 本批预期结果

- 143 行：`AI修正`。
- 76 行：保持原译，状态 `待人工裁决`。
- 610 行：`未改`。
- LQE 分数保持 96.45 / FAIL；报告中仍保留 76 条候选及其错误说明。
- 原输入、source 文本、sheet 数量和 job iteration 均不改变。

## 测试

1. XLSX 和 CSV 单轮导出：pending 候选不覆盖原译，状态和计数正确。
2. `apply-fixes`：pending 不写入 state，普通建议仍写入。
3. 混合段：同时含普通错误和待裁决错误时，整段不导出、不迭代。
4. 报告：pending 行保留 Suggest translation，并显示 Pending Adjudication。
5. 同轮重写报告：旧 history 被当前 errors 替换，不残留旧状态。
6. lens merge：状态经过 nested/flat schema、multi-lens 和 dedup 后不丢失。
7. 标准收尾：显式 job 路径可用，默认不生成第三份裁决表。
8. 本批集成验证：143/76/610，76 个 pending 的目标文本均等于原译。

## 非目标

- 不重新执行四 lens 语义评估。
- 不修改 96.45 的评分口径。
- 不替 PM/TB 决定 76 个候选的最终译名。
- 不删除旧文件；只做可追溯备份。
