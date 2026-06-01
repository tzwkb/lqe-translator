"""Shared scoring constants for lqe_calc.py and lqe_io.py."""

CATEGORY_PARENT = {
    "Terminology": "Terminology", "Locale convention": "Design", "Other": "Other",
    "Addition": "Accuracy", "Omission": "Accuracy", "Mistranslation": "Accuracy",
    "Untranslated": "Accuracy", "Punctuation": "Fluency", "Spelling": "Fluency",
    "Grammar": "Fluency", "Inconsistency": "Style", "Company style": "Style",
    "Unidiomatic": "Style", "Length": "Design", "Markup": "Design",
    "Culture specific reference": "Accuracy",
}
CATEGORY_ORDER = tuple(CATEGORY_PARENT)
WEIGHTS = {
    "Terminology": 1.5, "Locale convention": 1.0, "Other": 1.0,
    "Addition": 1.5, "Omission": 1.5, "Mistranslation": 1.5, "Untranslated": 1.5,
    "Punctuation": 1.0, "Spelling": 1.0, "Grammar": 1.5,
    "Inconsistency": 1.5, "Company style": 1.5, "Unidiomatic": 1.5,
    "Length": 1.0, "Markup": 1.5, "Culture specific reference": 1.5,
}
SEVERITY_POINTS = {"Neutral": 0, "Minor": 1, "Major": 5, "Critical": 10}
FORCED_SEVERITY = {
    "Terminology": "Major", "Untranslated": "Major",
    "Markup":       "Major", "Length":       "Major",
}
VALID_CATEGORIES = set(CATEGORY_ORDER)
VALID_SEVERITIES = {"Neutral", "Minor", "Major", "Critical"}

_PARENT_REMAP = {
    "Accuracy": "Mistranslation", "Fluency": "Grammar",
    "Style": "Unidiomatic", "Verity": "Culture specific reference", "Design": "Markup",
}


def normalize_category(cat: str) -> str:
    return _PARENT_REMAP.get(cat, cat)


def apply_severity(cat: str, sev: str) -> str:
    return FORCED_SEVERITY.get(cat, sev.strip().capitalize() if sev else "Minor")


def raw_points(counts: dict) -> int:
    return sum(SEVERITY_POINTS.get(sev, 0) * n for sev, n in counts.items())


def weighted_points(cat: str, counts: dict) -> float:
    return WEIGHTS.get(cat, 1.0) * raw_points(counts)
