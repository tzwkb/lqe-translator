"""Bind merged LQE result arrays to the split generation that produced them."""

from __future__ import annotations

from pathlib import Path

from lqe_split_contract import canonical_digest, validate_manifest_structure


SCHEMA = "lqe.result-contract"
VERSION = 1


def result_contract_path(results_path: Path) -> Path:
    path = Path(results_path)
    return path.with_name(f"{path.stem}.contract.json")


def build_result_contract(manifest: dict, results: list[dict]) -> dict:
    manifest = validate_manifest_structure(manifest)
    payload = {
        "schema": SCHEMA,
        "version": VERSION,
        "manifest_digest": manifest["manifest_digest"],
        "state_fingerprint": manifest["state_fingerprint"],
        "split_fingerprint": manifest["split_fingerprint"],
        "results_digest": canonical_digest(results),
    }
    payload["contract_digest"] = canonical_digest(payload)
    return payload


def validate_result_contract(
    contract: object,
    manifest: dict,
    results: list[dict],
    *,
    label: str,
) -> None:
    if not isinstance(contract, dict):
        raise ValueError(f"{label}: result contract must be an object")
    expected = build_result_contract(manifest, results)
    if contract != expected:
        raise ValueError(
            f"{label}: result contract is stale or does not match its payload"
        )
