"""Account for every machine hint without turning hints into mandatory errors."""
from __future__ import annotations

from .store import fingerprint


DECISION_SCHEMA = {"decisions": [{"module": "from packet", "chunk_id": 0,
    "id": 0, "precheck_ref": "from packet", "decision": "retained|dismissed",
    "applicability": "same_sense|confirmed|different_sense|grammar_variant|partial_match|not_an_error|insufficient_context",
    "reason": "applicable sense/rule evidence", "target_quote": "literal current target"}]}

STRUCTURED_DECISION_SCHEMA = {"decisions": [{"module": "from hint", "chunk_id": 0,
    "id": 0, "precheck_ref": "from hint",
    "decision": "confirmed_error|no_error; a correct glossary match is no_error",
    "applicability": "same_sense|confirmed|different_sense|grammar_variant|partial_match|not_an_error|insufficient_context",
    "reason": "actual translation defect or why this hint is not an error",
    "target_quote": "literal current target",
    "finding": "null for no_error; for confirmed_error supply {category, severity, comment, needs_confirmation:true, edit:null, resolution_status for terminology}. Do not supply precheck_ref or term metadata here; the program joins frozen facts."}]}


REVIEW_GUIDANCE = """Check every segment against all assigned dimensions in one pass.
Machine prechecks and confirmed glossary matches are candidates, not proof of an error.
For each precheck, record retained/dismissed, applicability, reason and target_quote.
Retain a terminology issue only when the source occurrence has the glossary sense.
A match inside another word/name, a different sense, or an ordinary grammatical
inflection is not a confirmed deviation. Do not infer a bare term from longer entries.
For ordinary words, assess the phrase in context: plural/countability, attributive
forms and religious/cultural senses can differ from a standalone glossary label.
Require an explicit applicable project rule before insisting on an unnatural literal
form. Record genuine uncertainty as insufficient_context; do not invent certainty.
An unspecified preferred form alone does not establish a penalized terminology defect.
Use human_choice_required only for a confirmed defect whose repair choice is unresolved.
Grammar: accept valid coordination with a new clause subject. For numeric placeholders,
prefer a natural number-neutral recast when possible; do not automatically insert (s).
Unless an applicable project rule requires full sentences, conventional UI fragments
and understood subjects in labels/tooltips/item descriptions are valid when meaning is clear.
Do not penalize that convention alone, or charge the same underlying defect in two modules.
Accuracy: check every source component, including both sides of paired outcomes.
Report concrete defects; optional wording preferences remain Neutral.
Keep findings concise: quote the defect and explain the applicable rule once.
Do not see previous scores, a desired score, repair self-evaluations or pass conclusions.
"""


def precheck_items(packets: list[dict]) -> list[dict]:
    items = []
    for packet in packets:
        for segment in packet["segments"]:
            for issue in segment.get("precheck", []):
                ref = issue.get("precheck_ref")
                if not isinstance(ref, str) or not ref:
                    raise ValueError("预检提示缺少可追溯编号")
                items.append({"module": packet["module"], "chunk_id": packet["chunk_id"],
                    "id": segment["id"], "precheck_ref": ref, "source": segment["source"],
                    "target": segment["target"], "issue": issue})
    return items


def _covered_term_hint(item: dict, findings: list, expected: dict) -> bool:
    """One confirmed compound defect may cover an overlapping shorter hint."""
    import re
    hint = item["issue"]
    if hint.get("category") != "Terminology":
        return False
    spans = hint.get("term_spans", {}).get("source", [])
    targets = hint.get("expected_targets", [])
    if not spans or not targets:
        return False
    by_ref = {x["precheck_ref"]: x["issue"] for x in expected.values()
              if (x["module"], x["chunk_id"], x["id"]) == (item["module"], item["chunk_id"], item["id"])}
    for finding in findings:
        covering = by_ref.get(finding.get("precheck_ref"), {})
        outer = covering.get("term_spans", {}).get("source", [])
        full_targets = covering.get("expected_targets", [])
        if (finding.get("category") == "Terminology" and outer and full_targets
                and all(any(b["start"] <= s["start"] and b["end"] >= s["end"] for b in outer) for s in spans)
                and all(any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", f, re.IGNORECASE)
                            for f in full_targets) for t in targets)):
            return True
    return False


def validate_decisions(packets: list[dict], decisions: list, findings: dict) -> None:
    """Validate coverage/evidence consistency, never author semantic verdicts."""
    expected = {(x["module"], x["chunk_id"], x["id"], x["precheck_ref"]): x
                for x in precheck_items(packets)}
    if not isinstance(decisions, list):
        raise ValueError("预检逐项判断必须是列表")
    seen = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("预检逐项判断格式无效")
        key = tuple(decision.get(k) for k in ("module", "chunk_id", "id", "precheck_ref"))
        if key not in expected or key in seen:
            raise ValueError("预检逐项判断包含未知或重复提示")
        seen.add(key)
        item = expected[key]
        if decision.get("decision") not in {"retained", "dismissed"}:
            raise ValueError("预检提示必须明确保留或排除")
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise ValueError("预检逐项判断缺少具体依据")
        quote = decision.get("target_quote")
        if (not isinstance(quote, str) or quote not in item["target"]
                or (item["target"] and not quote.strip())):
            raise ValueError("预检判断引用的译文不在当前版本中")
        applicability = decision.get("applicability")
        if applicability not in {"same_sense", "confirmed", "different_sense", "grammar_variant",
                                 "partial_match", "not_an_error", "insufficient_context"}:
            raise ValueError("预检判断缺少适用性说明")
        kept = any(e.get("precheck_ref") == item["precheck_ref"]
                   for e in findings.get(key[:3], []))
        if not kept and decision["decision"] == "retained":
            kept = _covered_term_hint(item, findings.get(key[:3], []), expected)
        if kept != (decision["decision"] == "retained"):
            raise ValueError("预检逐项判断与实际报告的问题不一致")
        positive = {"same_sense", "confirmed"} if item["issue"]["category"] == "Terminology" else {"confirmed"}
        if kept and applicability not in positive:
            raise ValueError("不适用或未确认的预检提示不能当作已确认错误保留")
    if seen != set(expected):
        raise ValueError("预检提示没有全部说明保留或排除的依据")


def pending_history(history: list[dict], verdicts: list[dict]) -> list[dict]:
    unresolved = {v["issue_id"] for v in verdicts if v["decision"] in {"retained", "inconclusive"}}
    return [i for i in history if i["issue_id"] in unresolved and i.get("severity") not in {"Neutral", "Minor", "Major"}]


def repair_spec(segments: list[dict], errors: list[dict], historical=()) -> list[dict]:
    from .issues import identity
    import copy
    errors = copy.deepcopy(errors)
    by_id = {s["id"]: s for s in segments}
    by_key = {s["segment_key"]: s for s in segments}
    observed = {identity(by_id[r["id"]]["segment_key"], e) for r in errors for e in r["errors"]}
    entries = {r["id"]: r for r in errors}
    for issue in historical:
        key = issue["segment_key"]
        if (issue["status"] not in {"open", "reopened", "disputed"}
                or key not in by_key or issue["issue_id"] in observed):
            continue
        sid = by_key[key]["id"]
        if sid not in entries:
            entries[sid] = {"id": sid, "errors": []}
            errors.append(entries[sid])
        entries[sid]["errors"].extend(copy.deepcopy(issue["findings"]))
    result = []
    for entry in errors:
        issues = [{"issue_ref": fingerprint([entry["id"], n, e]), "finding": e}
                  for n, e in enumerate(entry["errors"]) if e["severity"] != "Neutral"]
        if issues:
            segment = by_id[entry["id"]]
            result.append({"id": segment["id"], "segment_key": segment["segment_key"],
                "source": segment["source"], "target": segment["target"], "issues": issues})
    return result


def validate_repair_coverage(spec: list[dict], repairs: list, *, key_field="id") -> None:
    """A candidate must address all penalized findings on each affected segment."""
    expected = {s[key_field]: {e["issue_ref"] for e in s["issues"]} for s in spec}
    seen = set()
    for repair in repairs:
        key = repair.get(key_field)
        refs = repair.get("addresses")
        if key not in expected or key in seen:
            raise ValueError("修正包含未知、无扣分问题或重复分段")
        if (not isinstance(refs, list) or any(not isinstance(r, str) for r in refs)
                or len(refs) != len(set(refs)) or set(refs) != expected[key]):
            raise ValueError("修正未明确覆盖该段的全部扣分问题")
        seen.add(key)
    if seen != set(expected):
        raise ValueError("自动修正遗漏了仍有扣分问题的分段")
