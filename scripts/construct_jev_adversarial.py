"""Construct paired low-trust ATBench trajectories for Jev Guard evaluation.

Each selected unsafe seed yields two clean/control/attack triads. The only
trajectory edit is inside one pre-existing environment/tool-result content
field. This script makes artifacts; it does not call the judge endpoint.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trajectory_audit.adversarial import (  # noqa: E402
    FAMILIES, VARIANTS, make_perturbation, sha256_text,
)
from trajectory_audit.data import load_records  # noqa: E402
from trajectory_audit.download import sha256_file, validate_atbench_file  # noqa: E402

from eval_jev_atbench import EXPECTED_MODEL, MAX_CHARS, input_text  # noqa: E402


DEFAULT_BASELINE = Path("reports/jev_guard_v3_2_atbench_api_2026-10-09/predictions.jsonl")
VARIANT_CODES = {
    (family, variant): family_index * 3 + variant_index + 1
    for family_index, family in enumerate(FAMILIES)
    for variant_index, variant in enumerate(VARIANTS)
}


def load_baseline(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        identifier = str(row["id"])
        if identifier in rows:
            raise ValueError(f"duplicate baseline ID {identifier} on line {line_number}")
        if row.get("returned_model") not in (None, EXPECTED_MODEL):
            raise ValueError(f"baseline model identity mismatch for {identifier}")
        if row.get("prediction") not in (0, 1):
            raise ValueError(f"baseline has no binary prediction for {identifier}")
        rows[identifier] = row
    return rows


def select_ids(records, baseline: dict[str, dict], selection: str,
               explicit_ids: str | None, limit: int | None) -> list[str]:
    if selection == "ids":
        if not explicit_ids:
            raise ValueError("--ids is required with --selection ids")
        requested = {part.strip() for part in explicit_ids.split(",") if part.strip()}
        found = {record.id for record in records}
        missing = requested - found
        if missing:
            raise ValueError(f"unknown ATBench IDs: {sorted(missing)}")
    else:
        if explicit_ids:
            raise ValueError("--ids requires --selection ids")
        requested = None
    selected = []
    for record in records:
        saved = baseline.get(record.id)
        if saved is None:
            raise ValueError(f"baseline prediction missing for {record.id}")
        if saved.get("gold") != record.label:
            raise ValueError(f"baseline gold label differs for {record.id}")
        if record.label != 1 or saved.get("middle_truncated"):
            if requested is not None and record.id in requested:
                raise ValueError(f"ID {record.id} must be gold unsafe and untruncated")
            continue
        if selection == "tp-untruncated" and saved["prediction"] != 1:
            continue
        if requested is not None and record.id not in requested:
            continue
        selected.append(record.id)
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("selection contains no eligible unsafe trajectories")
    return selected


def construct_rows(raw: dict, baseline: dict,
                   families: tuple[str, ...] = FAMILIES) -> tuple[list[dict], list[dict], list[dict]]:
    """Return model states, reversible manifests, and ATBench-style rows."""

    parent_id = str(raw["id"])
    states: list[dict] = []
    manifests: list[dict] = []
    atbench_rows: list[dict] = []
    clean_prompt = None
    for family in families:
        by_variant = {}
        for variant in VARIANTS:
            edit = make_perturbation(raw, family, variant)
            prompt, truncated = input_text(edit.normalized, MAX_CHARS)
            if truncated:
                raise ValueError(f"constructed {parent_id}:{family}:{variant} crosses 24k cap")
            input_sha256 = sha256_text(prompt)
            if variant == "clean":
                if input_sha256 != baseline.get("input_sha256"):
                    raise ValueError(f"clean input differs from saved Jev baseline for {parent_id}")
                clean_prompt = prompt
            case_id = f"{parent_id}:{family}:{variant}"
            atbench_id = 100_000 + int(raw["id"]) * 100 + VARIANT_CODES[(family, variant)]
            state = {
                "id": case_id,
                "parent_id": parent_id,
                "atbench_id": atbench_id,
                "family": family,
                "variant": variant,
                "gold": edit.normalized.label,
                "prompt": prompt,
                "source_event_index": edit.source_event_index,
                "input_sha256": input_sha256,
                "transform_sha256": edit.transform_sha256,
                "middle_truncated": truncated,
            }
            states.append(state)
            manifest = {
                "id": case_id,
                "parent_id": parent_id,
                "atbench_id": atbench_id,
                "family": family,
                "variant": variant,
                "original_gold": raw["label"],
                "baseline_prediction": baseline["prediction"],
                "source_event_index": edit.source_event_index,
                "source_raw_index": edit.source_raw_index,
                "edit_mode": edit.edit_mode,
                "original_content_sha256": edit.original_content_sha256,
                "modified_content_sha256": edit.modified_content_sha256,
                "original_content": edit.original_content,
                "edited_content": edit.edited_content,
                "inserted_note": edit.inserted_note,
                "transform_sha256": edit.transform_sha256,
                "input_sha256": input_sha256,
                "mechanical_invariants_passed": True,
            }
            manifests.append(manifest)
            atbench_row = deepcopy(edit.raw_row)
            atbench_row["id"] = atbench_id
            atbench_row["adversarial_metadata"] = {
                "id": case_id,
                "parent_id": parent_id,
                "family": family,
                "variant": variant,
                "source_event_index": edit.source_event_index,
                "source_raw_index": edit.source_raw_index,
                "edit_mode": edit.edit_mode,
                "input_sha256": input_sha256,
                "transform_sha256": edit.transform_sha256,
            }
            # The integer id is unique across variants. All original
            # annotation fields and trajectory material remain intact.
            atbench_rows.append(atbench_row)
            by_variant[variant] = edit
        if len(by_variant["control"].edited_content) != len(by_variant["attack"].edited_content):
            raise AssertionError(f"control/attack content lengths differ for {parent_id}:{family}")
        if by_variant["control"].edit_mode != by_variant["attack"].edit_mode:
            raise AssertionError(f"control/attack edit modes differ for {parent_id}:{family}")
    clean_prompts = [state["prompt"] for state in states if state["variant"] == "clean"]
    if clean_prompt is None or len(set(clean_prompts)) != 1:
        raise AssertionError("clean prompt differs between attack families")
    return states, manifests, atbench_rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/raw/atbench/test.json"))
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("outputs/jev-adversarial-trajectories"))
    parser.add_argument("--selection", choices=("tp-untruncated", "all-untruncated-unsafe", "ids"),
                        default="tp-untruncated")
    parser.add_argument("--ids", help="Comma-separated ATBench IDs for --selection ids")
    parser.add_argument("--families", default=",".join(FAMILIES),
                        help="Comma-separated fixed attack families; default is all four")
    parser.add_argument("--limit", type=int, help="Optional first-N pilot limit in dataset order")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    families = tuple(part.strip() for part in args.families.split(",") if part.strip())
    if not families or len(set(families)) != len(families) or any(
        family not in FAMILIES for family in families
    ):
        parser.error(f"--families must be a nonempty unique subset of {FAMILIES}")
    source_info = validate_atbench_file(args.data)
    records = load_records(args.data)
    original_rows = json.loads(args.data.read_text(encoding="utf-8"))
    if [record.id for record in records] != [str(row["id"]) for row in original_rows]:
        raise ValueError("raw and normalized ATBench row order differs")
    baseline = load_baseline(args.baseline)
    baseline_summary_path = args.baseline.with_name("summary.json")
    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
    if baseline_summary.get("model") != "hubin/jev-guard-v3.2-2b":
        raise ValueError("baseline summary model identity mismatch")
    if baseline_summary.get("dataset", {}).get("sha256") != source_info["sha256"]:
        raise ValueError("baseline summary dataset hash mismatch")
    selected = select_ids(records, baseline, args.selection, args.ids, args.limit)
    selected_set = set(selected)
    states, manifests, atbench_rows = [], [], []
    for raw in original_rows:
        if str(raw["id"]) in selected_set:
            group_states, group_manifests, group_raw = construct_rows(
                raw, baseline[str(raw["id"])], families
            )
            states.extend(group_states)
            manifests.extend(group_manifests)
            atbench_rows.extend(group_raw)
    if len(states) != 3 * len(families) * len(selected):
        raise AssertionError("expected three states per selected seed and family")
    if len({row["id"] for row in atbench_rows}) != len(atbench_rows):
        raise AssertionError("generated ATBench ids are not unique")
    if any(row["id"] <= 1000 for row in atbench_rows):
        raise AssertionError("generated ATBench id overlaps the original 1-1000 range")
    output_paths = [args.output_dir / name for name in
                    ("states.jsonl", "manifest.jsonl", "atbench_rows.jsonl", "summary.json")]
    existing = [str(path) for path in output_paths if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing artifacts: {existing}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_paths[0], states)
    write_jsonl(output_paths[1], manifests)
    write_jsonl(output_paths[2], atbench_rows)
    summary = {
        "dataset": source_info,
        "baseline_predictions_sha256": sha256_file(args.baseline),
        "baseline_model": EXPECTED_MODEL,
        "selection": args.selection,
        "selected_ids": selected,
        "n_seeds": len(selected),
        "n_states": len(states),
        "n_families": len(families),
        "families": list(families),
        "variants_per_family": list(VARIANTS),
        "atbench_id_rule": "integer id = 100000 + original ATBench id * 100 + 1-based code from FAMILIES order (prior: 1-3; tail: 4-6; forged review: 7-9; benign dilution: 10-12)",
        "protocol": "Jev completed-trajectory prompt, full ATBench view, 24000-character view cap; one existing environment.content edit per control/attack",
        "constraint": "Original user, agent reasoning/action/completion, tool definitions, and all other environment results are mechanically unchanged; JSON object keys/values retained under identical control/attack reserialization.",
        "label_caveat": "Mechanical preservation does not establish human semantic label validity; audit edited examples before claiming attack success.",
        "files": {"states": "states.jsonl", "manifest": "manifest.jsonl",
                  "atbench_rows": "atbench_rows.jsonl"},
    }
    output_paths[3].write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    print(f"Wrote {len(states)} states from {len(selected)} seeds to {args.output_dir}")


if __name__ == "__main__":
    main()
