# LQE Translator

中文 | [English](README.md)

## 概览

游戏本地化 LQE/MTPE 质检、评分和报告生成 Agent Skill，支持项目 profile、确定性预检查、多 lens AI 评估和 Excel 报告。

## 主要能力

- 支持 ZH 源文到 EN/TH 等目标语言的 LQE。
- 内置项目 profile、术语、风格指南和评分规则。
- 生成可交付的 Excel/PM 报告。

## 使用方式

PM 可先阅读 PM_GUIDE.html；技术使用按 README 目录结构、jobs 和 scripts 流程执行。

## 状态

该仓库仍按当前 README 的说明维护或使用。

## 注意事项

长 README 中的脚本说明、目录结构和评分规则保持原样。

## 命令与配置参考

以下代码块从主 README 保留；命令、路径和配置键不翻译，复制时请以实际环境为准。

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

## 详细技术说明

主 README 保留了原始技术细节、历史说明、完整命令和文件结构。本文件作为中文版本维护核心说明；需要逐项核对命令时，请参照主 README 的代码块和路径。
