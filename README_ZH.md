# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

## 概览

游戏本地化 LQE/MTPE 质检、评分和报告生成 Agent Skill，支持项目 profile、确定性预检查、多 lens AI 评估和 Excel 报告。

## 文档对齐说明

本 README_ZH.md 与英文 README.md 使用同一项目事实，但采用中文读者更容易扫描的结构。命令、路径、配置键和示例数据保持原样。

## 主要能力

- 从 Excel 输入和项目 profile 初始化 LQE 任务。
- 在 AI 评估前运行确定性预检查。
- 计算分数并生成迭代/最终报告。
- 支持大文件多 lens 评估。

## 主要能力

- 支持 ZH 源文到 EN/TH 等目标语言的 LQE。
- 内置项目 profile、术语、风格指南和评分规则。
- 生成可交付的 Excel/PM 报告。

## 使用方式

PM 可先阅读 PM_GUIDE.html；技术使用按 README 目录结构、jobs 和 scripts 流程执行。

## 注意事项

长 README 中的脚本说明、目录结构和评分规则保持原样。

## 命令与配置参考

以下命令、路径和配置键保持原样，复制时请以实际环境为准。

```bash
pip install openpyxl requests python-docx -q
```

```bash
python scripts/run_tests.py
```

```bash
SCRIPTS=~/.claude/skills/lqe-translator/scripts
```

```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "<file>.xlsx" --project <game>/<lang> \
  --source-col "<col>" --target-col "<col>" \
  --out "jobs/<file_stem>/state.json"
```

```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "<file>.xlsx" \
  --source-col "<col>" \
  --target-col "<col>" \
  --style-guide "<sg.docx>" \
  --terminology "<terms.xlsx>" \
  --out "jobs/<file_stem>/state.json"
```

```bash
python "$SCRIPTS/lqe_io.py" pre-check \
  --state "jobs/<stem>/state.json" \
  --out "jobs/<stem>/errors.json"
```

```json
[
  {"id": 0, "errors": [{"category": "Mistranslation", "severity": "Major", "comment": "..."}], "corrected": "Fixed text"},
  {"id": 1, "errors": [], "corrected": null}
]
```

```bash
python "$SCRIPTS/lqe_calc.py" \
  --state "jobs/<stem>/state.json" \
  --errors "jobs/<stem>/errors.json" \
  --threshold 98
```

## 对应技术覆盖

### 目录结构

- `scripts/` 保存 LQE 读取、预检查、评分、分块、多 lens 合并和报告生成脚本。
- `languages/<code>/` 保存语言属性和语言层评估说明。
- `projects/<game>/<lang>/` 保存项目 profile、检查规则、术语、风格指南和输入资源。
- `jobs/<file_stem>/` 是每个 LQE 任务的工作目录，保存状态、错误、迭代报告和最终报告。

### 标准工作流

1. `lqe_io.py read` 从 Excel 输入和项目 profile 初始化任务。
2. `lqe_io.py pre-check` 执行确定性检查，生成初始 `errors.json`。
3. AI 评估在同一错误文件中补充判断型错误和修正建议。
4. `lqe_calc.py` 根据权重、严重性和字数计算分数。
5. FAIL 时用 `apply-fixes` 进入下一轮；PASS 时用 `write` 生成最终报告。

### 确定性预检查

预检查覆盖目标文本残留中文、标记不匹配、变量缺失、换行数量、数字变化、长度限制、千分位、空格和术语缺失等问题。术语、未翻译、标记和长度类问题会被视为 Major。

### 大文件多 Lens

大文件按 T/A/G/R 四类 lens 拆分：术语、准确性、语法和语域。脚本负责拆分、合并、结构校验、类别归属和去重，降低长文件漏报风险。

### 评分

分数按错误类别权重和严重性点数计算，默认阈值为 98。初始化时锁定 wordcount，后续迭代不改变字数基准。

## 补充评分与命令说明

### AI 评估输出

AI 评估读取预检查生成的 `errors.json` 和 `sg.txt` 风格指南，在同一 JSON 中补充判断型错误。每个错误应包含类别、严重性、说明和必要的 `corrected` 修正文本。

### FAIL 迭代

当分数低于阈值时，`apply-fixes` 会归档当前错误、应用修正、生成本轮 Excel 报告，并进入下一轮 AI 评估。每一轮错误文件和报告都保留在 job 目录中。

### PASS 报告

当分数达到阈值时，`write` 会生成最终 `*_lqe.xlsx`，包含错误、分数和迭代历史，供 PM 或质量负责人交付/归档。

### 辅助命令

英文 README 中的辅助命令覆盖分块、lens 合并、结构校验、类别归属、去重、最终汇总和一键 finalize。中文 README 保留这些命令的路径和参数，不翻译可执行内容。

### 错误类别

评分公式按错误类别权重和严重性点数计算。Neutral 不扣分，Minor、Major、Critical 逐级增加扣分；Terminology、Untranslated、Markup、Length 等类别在脚本中有强制严重性规则。

## 英文章节对应说明

### Directory Structure

对应中文的“目录结构”。英文 README 的目录树保留完整路径，中文说明解释每层目录在 LQE 流程中的作用。

### Setup

对应中文的安装、测试和 `SCRIPTS` 路径配置。执行命令保持英文 README 原样，避免破坏复制使用。

### Workflow

对应中文的“标准工作流”。Initialize、Pre-check、AI Evaluation、Calculate Score、FAIL 修复和 PASS 报告六个阶段在两种语言中语义一致。

### Large Files — Multi-Lens Fan-Out

对应中文的“大文件多 Lens”。T/A/G/R 分工、split、merge-lenses、validate-lenses、reconcile 和 merge 是同一套长文件评估流程。

### Scoring Formula / Error Categories / Auxiliary Commands

对应中文的“评分”“错误类别”和“辅助命令”。公式、类别名和脚本参数保持英文原样，解释文本用中文说明。

### PM Guide

PM 操作说明放在 `PM_GUIDE.html`；README 面向维护者和执行 Agent，解释 job 目录、脚本流程、评分和报告生成。

## 交付与维护说明

### 报告交付

每次 FAIL 迭代都会生成对应的 `*_lqe_iter{N}.xlsx`，最终 PASS 生成 `*_lqe.xlsx`。交付时应确认最终报告、迭代历史、分数、错误类别和修正文本都在 job 目录中可追溯。

### Profile 维护

项目 profile 应维护语言、术语、风格指南、检查规则和 adjudication 说明。新增语言或项目时，不应只复制脚本，还要补齐 `languages/` 和 `projects/` 下的配置层。

### Lens 维护

多 lens 流程依赖 `docs/lenses/` 中的分工说明。调整错误类别、召回策略或合并规则时，需要同步更新 lens spec、校验脚本和 README 说明。

### 批处理与断点

`lqe_batch.py` 和相关脚本用于输出预算控制、批处理和可恢复运行。长文件任务应优先使用可恢复流程，避免中断后丢失已完成的评估结果。

### 验证

修改评分、预检查或分块逻辑后，应运行 `python scripts/run_tests.py`，确认 23 个内置检查、profile、batch 和 feedback smoke 流程仍可通过。
