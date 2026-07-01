"""Shared constants & language-attribute layer for lqe_io.py / lqe_checks.py / lqe_calc.py."""

# 父维度对齐 MQM-Core / ISO 5060:2024 七个一级维度：
#   Terminology, Accuracy, Linguistic Conventions, Style,
#   Locale Conventions, Audience Appropriateness, Design and Markup (+ Other)
CATEGORY_PARENT = {
    "Terminology": "Terminology", "Locale convention": "Locale Conventions", "Other": "Other",
    "Addition": "Accuracy", "Omission": "Accuracy", "Mistranslation": "Accuracy",
    "Untranslated": "Accuracy", "Punctuation": "Linguistic Conventions", "Spelling": "Linguistic Conventions",
    "Grammar": "Linguistic Conventions", "Inconsistency": "Style", "Company style": "Style",
    "Unidiomatic": "Style", "Length": "Design and Markup", "Markup": "Design and Markup",
    "Culture specific reference": "Audience Appropriateness",
    "Audience appropriateness": "Audience Appropriateness",
}
CATEGORY_ORDER = tuple(CATEGORY_PARENT)
WEIGHTS = {
    "Terminology": 1.5, "Locale convention": 1.0, "Other": 1.0,
    "Addition": 1.5, "Omission": 1.5, "Mistranslation": 1.5, "Untranslated": 1.5,
    "Punctuation": 1.0, "Spelling": 1.0, "Grammar": 1.5,
    "Inconsistency": 1.5, "Company style": 1.5, "Unidiomatic": 1.5,
    "Length": 1.0, "Markup": 1.5, "Culture specific reference": 1.5,
    "Audience appropriateness": 1.5,
}
# 默认 LISA 档严重度乘数；MQM 指数档 (Critical=25) 见 SEVERITY_POINTS_MQM（opt-in）
SEVERITY_POINTS = {"Neutral": 0, "Minor": 1, "Major": 5, "Critical": 10}
SEVERITY_POINTS_MQM = {"Neutral": 0, "Minor": 1, "Major": 5, "Critical": 25}
FORCED_SEVERITY = {
    "Terminology": "Major", "Untranslated": "Major",
    "Markup":       "Major", "Length":       "Major",
}
VALID_CATEGORIES = set(CATEGORY_ORDER)
VALID_SEVERITIES = {"Neutral", "Minor", "Major", "Critical"}

# AI 若误填"父维度名"而非子类别，归一回退到该维度的代表子类。
# 同时保留旧父类名（Fluency/Design/Verity）与新 MQM 维度名，保证向后兼容。
_PARENT_REMAP = {
    "Accuracy": "Mistranslation",
    "Fluency": "Grammar", "Linguistic Conventions": "Grammar",
    "Style": "Unidiomatic",
    "Verity": "Culture specific reference",
    "Audience Appropriateness": "Culture specific reference",
    "Design": "Markup", "Design and Markup": "Markup",
    "Locale Conventions": "Locale convention",
}


def normalize_category(cat: str) -> str:
    return _PARENT_REMAP.get(cat, cat)


import json
from pathlib import Path


def apply_severity(cat: str, sev: str) -> str:
    return FORCED_SEVERITY.get(cat, sev.strip().capitalize() if sev else "Minor")


def raw_points(counts: dict) -> int:
    return sum(SEVERITY_POINTS.get(sev, 0) * n for sev, n in counts.items())


def weighted_points(cat: str, counts: dict) -> float:
    return WEIGHTS.get(cat, 1.0) * raw_points(counts)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_terms(state: dict) -> list[dict]:
    path = state.get("terms_path", "")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if state.get("terminology"):
        return state["terminology"]
    return []


def term_senses(entry: dict) -> list[dict]:
    """把单义 {source,target,...} / 多义 {source,senses:[...]} 两种形状统一拍平
    成候选列表，每项最多含 target(必有)/status/locked/category/definition。
    是所有脚本读取术语候选译法的唯一入口——不允许绕过它直接读 entry["target"]，
    多义条目没有这个 key。"""
    if "senses" in entry:
        return entry["senses"]
    return [{k: entry[k] for k in ("target", "status", "locked", "category", "definition") if k in entry}]


def group_terms(terms: list[dict]) -> dict[str, list[dict]]:
    """source -> 候选列表（见 term_senses），跨条目累加。"""
    out: dict[str, list[dict]] = {}
    for t in terms:
        src = (t.get("source") or "").strip()
        if src:
            out.setdefault(src, []).extend(term_senses(t))
    return out


def load_style_guide(state: dict) -> str:
    path = state.get("sg_path", "")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8")
    return state.get("style_guide", "")


import re

RE_CJK = re.compile(r'[一-鿿]')

# 语言属性层：languages/<code>/（skill 根，锚定脚本位置而非 CWD）。
# 每语言一个文件夹，固定文件名：attributes.json（语言学事实声明）+ eval_notes.md（语言级
# AI 评估关注点，存在即挂载）。属性不放检查开关；开关由 _lang_toggle_defaults 从属性推导。
# 入层标准：项目 SG 可能推翻的不是属性（em_dash/省略号/引号样式=项目取向，留 checks.json）。
# 合并顺序：内置默认 < 属性推导 < 项目 checks.json < CLI 显式参数。schema 见 languages/README.md。
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_LANG_DIR = _SKILL_ROOT / "languages"


def _target_lang(state_or_pair) -> str:
    if isinstance(state_or_pair, dict):
        lang = state_or_pair.get("target_lang", "")
        pair = state_or_pair.get("language_pair", "")
    else:
        lang, pair = "", state_or_pair or ""
    if not lang and pair and "-" in pair:
        lang = pair.rsplit("-", 1)[-1]
    return lang.strip().lower()


def _load_lang(lang: str) -> dict:
    if not lang:
        return {}
    p = _LANG_DIR / lang / "attributes.json"
    return read_json(p) if p.exists() else {}


def _lang_toggle_defaults(attrs: dict) -> dict:
    """属性 → 内置检查适用性推导（项目 checks.json 仍可覆盖最终开关）。"""
    if not attrs:
        return {}
    d = {}
    if attrs.get("script") == "cjk":
        d["fullwidth_punct"] = False  # CJK 目标语言（ja 等）全角标点合法
    if attrs.get("sentence_terminator", ".") == "none":
        d["terminal_punct"] = False   # N5：无句号体系语言（th）
    if attrs.get("word_delim", "space") != "space":
        d["word_repeat"] = False      # N7：非空格分词语言（th，重复另有 ๆ 体系）
    if attrs.get("script", "latin") != "latin":
        d["intra_word_case"] = False  # N8：非拉丁字母语言无大小写
        d["term_case"] = False        # #7 同理
    return d
