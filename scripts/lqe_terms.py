import csv
import io
import json
from pathlib import Path
import re

import openpyxl


STATUS_HEADER_RE = re.compile(r"status|状态", re.IGNORECASE)
DENIED_STATUS = "denied"
_ZW_TABLE = {ord(c): None for c in "​‌‍﻿⁠"}
_SOURCE_HEADERS = {
    "source",
    "zh",
    "src",
    "原文",
    "中文_cn",
    "中文",
    "chinese",
    "chinese_prc",
    "zh_cn",
    "zh-cn",
    "简中",
    "中文简体",
    "source text",
    "术语 zhcn",
}
_TARGET_HEADERS = {
    "target",
    "en",
    "tgt",
    "译文",
    "en_us",
    "english",
    "翻译",
    "英文",
    "thai",
    "th",
    "泰语",
    "泰文",
    "target text",
}
_CONFIRMED_HEADERS = {"confirmed", "approved", "已确认", "已批准"}
_PROTECTED_HEADERS = {"protected", "locked", "已保护", "锁定"}


class TermContractError(ValueError):
    pass


def parse_terminology_comment(comment: object) -> dict | None:
    """Recover canonical terminology fields from legacy display comments.

    New issues carry structured fields. This parser exists only for old artifacts
    and treats apostrophes inside targets as data, not closing delimiters.
    """
    if not isinstance(comment, str):
        return None
    marker = "' → expected "
    marker_at = comment.find(marker)
    if marker_at <= 0:
        return None
    source_at = comment.rfind("'", 0, marker_at)
    if source_at < 0:
        return None
    source = comment[source_at + 1:marker_at]
    if not source:
        return None

    candidates = comment[marker_at + len(marker):].strip()
    protected_suffix = " [PROTECTED]"
    if candidates.endswith(protected_suffix):
        candidates = candidates[:-len(protected_suffix)]

    targets = []
    position = 0
    while position < len(candidates):
        if candidates[position] != "'":
            return None
        target_at = position + 1
        quote_at = candidates.find("'", target_at)
        closing_at = None
        next_at = None
        while quote_at >= 0:
            suffix_at = quote_at + 1
            if suffix_at < len(candidates) and candidates[suffix_at] == "(":
                category_end = candidates.find(")", suffix_at + 1)
                if category_end < 0:
                    quote_at = candidates.find("'", quote_at + 1)
                    continue
                suffix_at = category_end + 1
            if candidates.startswith("[TB:", suffix_at):
                status_end = candidates.find("]", suffix_at + 4)
                if status_end < 0:
                    quote_at = candidates.find("'", quote_at + 1)
                    continue
                suffix_at = status_end + 1

            if suffix_at == len(candidates):
                closing_at = quote_at
                next_at = len(candidates)
                break
            if candidates.startswith(" or '", suffix_at):
                closing_at = quote_at
                next_at = suffix_at + len(" or ")
                break
            if candidates.startswith((";", " but ", ", but "), suffix_at):
                closing_at = quote_at
                next_at = len(candidates)
                break
            quote_at = candidates.find("'", quote_at + 1)

        if closing_at is None:
            return None
        target = candidates[target_at:closing_at]
        if not target:
            return None
        targets.append(target)
        position = next_at

    if not targets:
        return None
    return {"term_source": source, "expected_targets": targets}


def terminology_issue_fields(issue: object) -> dict | None:
    if not isinstance(issue, dict):
        return None
    source = issue.get("term_source")
    targets = issue.get("expected_targets")
    if (
        isinstance(source, str)
        and source
        and isinstance(targets, list)
        and targets
        and all(isinstance(target, str) and target for target in targets)
    ):
        return {"term_source": source, "expected_targets": list(targets)}
    if issue.get("category") != "Terminology":
        return None
    return parse_terminology_comment(issue.get("comment"))


def clean_term_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).translate(_ZW_TABLE).strip()


def normalize_status(value: object) -> str:
    return clean_term_text(value).casefold()


def _pick_header(headers: list[str], candidates: set[str], fallback: int) -> int:
    for index, header in enumerate(headers):
        if header.casefold() in candidates:
            return index
    if fallback < len(headers):
        return fallback
    raise TermContractError(f"terminology columns not found; headers={headers}")


def _single_optional_header(
    headers: list[str], predicate, label: str
) -> int | None:
    matches = [index for index, header in enumerate(headers) if predicate(header)]
    if len(matches) > 1:
        names = [headers[index] for index in matches]
        raise TermContractError(
            f"multiple {label} columns detected: {names}; disambiguate before read"
        )
    return matches[0] if matches else None


def _parse_bool(value: object, *, field: str, row: int) -> bool | None:
    if value is None or clean_term_text(value) == "":
        return None
    if type(value) is bool:
        return value
    normalized = clean_term_text(value).casefold()
    if normalized in {"true", "1", "yes", "y", "是"}:
        return True
    if normalized in {"false", "0", "no", "n", "否"}:
        return False
    raise TermContractError(
        f"terminology row {row} has invalid {field} boolean {value!r}"
    )


def _rows_to_items(headers: list[object], rows: list[tuple | list]) -> list[dict]:
    normalized_headers = [clean_term_text(value) for value in headers]
    source_index = _pick_header(normalized_headers, _SOURCE_HEADERS, 0)
    target_index = _pick_header(normalized_headers, _TARGET_HEADERS, 1)
    status_index = _single_optional_header(
        normalized_headers,
        lambda header: bool(header and STATUS_HEADER_RE.search(header)),
        "status",
    )
    confirmed_index = _single_optional_header(
        normalized_headers,
        lambda header: header.casefold() in _CONFIRMED_HEADERS,
        "confirmation",
    )
    protected_index = _single_optional_header(
        normalized_headers,
        lambda header: header.casefold() in _PROTECTED_HEADERS,
        "protection",
    )

    def cell(row, index):
        return row[index] if index is not None and index < len(row) else None

    items = []
    for row_number, row in enumerate(rows, start=2):
        source = clean_term_text(cell(row, source_index))
        if not source:
            continue
        item = {
            "source": source,
            "target": clean_term_text(cell(row, target_index)),
        }
        status = clean_term_text(cell(row, status_index))
        if status:
            item["status"] = status
        confirmed = _parse_bool(
            cell(row, confirmed_index), field="confirmed", row=row_number
        )
        protected = _parse_bool(
            cell(row, protected_index), field="protected", row=row_number
        )
        if confirmed is not None:
            item["confirmed"] = confirmed
        if protected is not None:
            item["protected"] = protected
        items.append(item)
    return items


def load_terminology_items(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"terminology file not found: {path}")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("items")
        if not isinstance(items, list):
            raise TermContractError("terminology JSON must be an array or contain items[]")
        return items
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        rows = list(
            csv.reader(
                io.StringIO(path.read_bytes().decode("utf-8-sig")),
                delimiter=delimiter,
            )
        )
        if not rows:
            return []
        return _rows_to_items(rows[0], rows[1:])
    if suffix in {".xlsx", ".xlsm"}:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
        if not rows:
            return []
        return _rows_to_items(list(rows[0]), rows[1:])
    raise TermContractError(f"unsupported terminology format: {suffix}")


def _mapping_flags(value: object, status: str) -> tuple[bool | None, bool]:
    if isinstance(value, dict):
        if type(value.get("confirmed")) is not bool:
            raise TermContractError(
                f"term_status_map[{status!r}] must define boolean confirmed"
            )
        protected = value.get("protected", False)
        if type(protected) is not bool:
            raise TermContractError(
                f"term_status_map[{status!r}].protected must be boolean"
            )
        return value["confirmed"], protected
    if isinstance(value, str):
        normalized = value.strip().casefold().replace("_", "-")
        aliases = {
            "confirmed": (True, False),
            "unconfirmed": (False, False),
            "reference": (False, False),
            "confirmed+protected": (True, True),
            "confirmed-protected": (True, True),
            "unconfirmed+protected": (False, True),
            "unconfirmed-protected": (False, True),
            "protected": (None, True),
        }
        if normalized in aliases:
            return aliases[normalized]
    raise TermContractError(
        f"unsupported term_status_map value for {status!r}: {value!r}"
    )


def _normalize_status_map(raw: object) -> dict[str, tuple[bool | None, bool]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TermContractError("profile.term_status_map must be an object")
    normalized = {}
    for raw_status, value in raw.items():
        status = normalize_status(raw_status)
        if not status:
            raise TermContractError("profile.term_status_map contains an empty status")
        if status == DENIED_STATUS:
            raise TermContractError("Denied must not be mapped; it is always excluded")
        if status in normalized:
            raise TermContractError(
                f"profile.term_status_map contains duplicate status {raw_status!r}"
            )
        normalized[status] = _mapping_flags(value, clean_term_text(raw_status))
    return normalized


def _normalize_protected_statuses(raw: object) -> set[str]:
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise TermContractError(
            "protected_statuses must be an array of non-empty strings"
        )
    normalized = set()
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not clean_term_text(value):
            raise TermContractError(
                f"protected_statuses[{index}] must be a non-empty string"
            )
        normalized.add(normalize_status(value))
    return normalized


def canonicalize_terms(
    items: list,
    *,
    term_status_map: object = None,
    protected_statuses: object = None,
) -> list[dict]:
    if not isinstance(items, list):
        raise TermContractError("terminology must be an array")
    status_map = _normalize_status_map(term_status_map)
    protected_set = _normalize_protected_statuses(protected_statuses)
    if DENIED_STATUS in protected_set:
        protected_set.remove(DENIED_STATUS)

    output = []
    missing_confirmation: set[str] = set()
    missing_protection: set[str] = set()
    for term_index, term in enumerate(items):
        if not isinstance(term, dict):
            raise TermContractError(f"terminology entry {term_index} must be an object")
        source = clean_term_text(term.get("source"))
        if not source:
            continue
        raw_senses = term.get("senses") if "senses" in term else [term]
        if not isinstance(raw_senses, list):
            raise TermContractError(f"terminology entry {term_index}.senses must be an array")
        senses = []
        for sense_index, raw in enumerate(raw_senses):
            if not isinstance(raw, dict):
                raise TermContractError(
                    f"terminology entry {term_index} sense {sense_index} must be an object"
                )
            target = clean_term_text(raw.get("target"))
            if not target:
                continue
            raw_status = clean_term_text(raw.get("status"))
            status = normalize_status(raw_status)
            if status == DENIED_STATUS:
                continue
            confirmed = raw.get("confirmed") if "confirmed" in raw else None
            protected = raw.get("protected") if "protected" in raw else None
            if confirmed is not None and type(confirmed) is not bool:
                raise TermContractError(
                    f"terminology {source!r}/{target!r} confirmed must be boolean"
                )
            if protected is not None and type(protected) is not bool:
                raise TermContractError(
                    f"terminology {source!r}/{target!r} protected must be boolean"
                )
            mapping = status_map.get(status) or status_map.get("*")
            if mapping is not None:
                mapped_confirmed, mapped_protected = mapping
                if confirmed is None:
                    confirmed = mapped_confirmed
                elif mapped_confirmed is not None and confirmed != mapped_confirmed:
                    raise TermContractError(
                        f"terminology {source!r}/{target!r} conflicts with term_status_map"
                    )
                if protected is None:
                    protected = mapped_protected
                elif mapped_protected and not protected:
                    raise TermContractError(
                        f"terminology {source!r}/{target!r} conflicts with protection mapping"
                    )
            if status in protected_set:
                protected = True
            marker = raw_status or "<no status>"
            if confirmed is None:
                missing_confirmation.add(marker)
            if protected is None:
                missing_protection.add(marker)
            sense = {"target": target}
            for key in ("status", "category", "definition"):
                value = clean_term_text(raw.get(key))
                if value:
                    sense[key] = value
            sense["confirmed"] = confirmed
            sense["protected"] = protected
            senses.append(sense)
        if senses:
            if len(raw_senses) > 1 or "senses" in term:
                output.append({"source": source, "senses": senses})
            else:
                output.append({"source": source, **senses[0]})

    if missing_confirmation:
        values = sorted(missing_confirmation, key=str.casefold)
        raise TermContractError(
            "terminology requires an explicit confirmation mapping; "
            f"unmapped status values: {values}"
        )
    if missing_protection:
        values = sorted(missing_protection, key=str.casefold)
        raise TermContractError(
            "terminology requires explicit protected flags or status mapping; "
            f"unmapped status values: {values}"
        )
    return output


def load_canonical_terminology(
    path: Path,
    *,
    term_status_map: object = None,
    protected_statuses: object = None,
) -> list[dict]:
    return canonicalize_terms(
        load_terminology_items(path),
        term_status_map=term_status_map,
        protected_statuses=protected_statuses,
    )
