"""Shared scoring constants for lqe_calc.py and lqe_io.py."""

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


def load_style_guide(state: dict) -> str:
    path = state.get("sg_path", "")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8")
    return state.get("style_guide", "")
