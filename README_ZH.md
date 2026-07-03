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
