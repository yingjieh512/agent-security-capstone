"""Conservative parsing and partial views for the public R-Judge corpus.

R-Judge stores an interaction as nested rounds with explicit ``user``,
``agent``, and ``environment`` turns.  Agent turns contain separate ``thought``
and ``action`` fields.  The dataset does *not* mark a terminal answer, so this
module deliberately exposes ``last_action_only`` rather than pretending that
the last action is a final answer.

Gold ``risk_description`` values and taxonomy fields are retained only in the
raw record for provenance.  None of the view builders render them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .data import (
    DataFormatError,
    TrajectoryEvent,
    TrajectoryRecord,
    canonical_json,
    canonical_text,
)


RJUDGE_VIEW_NAMES = (
    "full",
    "user_only",
    "action_only",
    "last_action_only",
)


@dataclass(frozen=True)
class RJudgeLoadResult:
    """Normalized records plus corpus-integrity diagnostics."""

    records: tuple[TrajectoryRecord, ...]
    raw_rows: int
    duplicate_input_ids: tuple[str, ...]
    file_count: int
    file_sha256: Mapping[str, str]

    @property
    def deduplicated_rows(self) -> int:
        return len(self.records)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event(
    events: list[TrajectoryEvent],
    kind: str,
    role: str,
    content: Any,
) -> None:
    events.append(
        TrajectoryEvent(
            index=len(events),
            kind=kind,
            role=role,
            content=canonical_text(content),
        )
    )


def normalize_rjudge_record(
    raw: Mapping[str, Any],
    *,
    source_file: str,
    index: int = 0,
) -> TrajectoryRecord:
    """Normalize one R-Judge row without inferring undocumented semantics."""

    if not isinstance(raw, Mapping):
        raise DataFormatError(
            f"R-Judge row {index} in {source_file} must be an object"
        )
    label = raw.get("label")
    if type(label) is not int or label not in (0, 1):
        raise DataFormatError(
            f"R-Judge row {index} in {source_file} has invalid label {label!r}"
        )
    contents = raw.get("contents")
    if not isinstance(contents, list):
        raise DataFormatError(
            f"R-Judge row {index} in {source_file} has non-list contents"
        )

    identifier = canonical_text(raw.get("id")) or f"{source_file}:{index}"
    profile = canonical_text(raw.get("profile"))
    events: list[TrajectoryEvent] = []
    if profile:
        _event(events, "message", "system", profile)

    for round_index, round_value in enumerate(contents):
        if not isinstance(round_value, list):
            raise DataFormatError(
                f"R-Judge row {identifier} round {round_index} must be a list"
            )
        for turn_index, turn in enumerate(round_value):
            if not isinstance(turn, Mapping):
                raise DataFormatError(
                    f"R-Judge row {identifier} round {round_index} turn "
                    f"{turn_index} must be an object"
                )
            role = canonical_text(turn.get("role")).lower()
            if role == "user":
                # The official evaluator skips null user content.
                if turn.get("content") is not None:
                    _event(events, "message", "user", turn.get("content"))
            elif role == "agent":
                if turn.get("thought") not in (None, ""):
                    _event(events, "reasoning", "assistant", turn.get("thought"))
                if turn.get("action") is not None:
                    # R-Judge calls this field an action.  It may contain a tool
                    # invocation or natural-language response, so do not parse it
                    # into an invented tool schema or a terminal completion.
                    _event(events, "agent_action", "assistant", turn.get("action"))
            elif role == "environment":
                value = turn.get("content")
                _event(
                    events,
                    "tool_result",
                    "tool",
                    "<NULL>" if value is None else value,
                )
            else:
                raise DataFormatError(
                    f"R-Judge row {identifier} has unsupported role {role!r}"
                )

    if not any(event.kind == "agent_action" for event in events):
        raise DataFormatError(f"R-Judge row {identifier} has no agent action")

    category = source_file.split("/", 1)[0] if "/" in source_file else ""
    metadata = {
        "source_file": source_file,
        "category": category,
        "scenario": canonical_text(raw.get("scenario")),
        "attack_type": canonical_text(raw.get("attack_type")),
    }
    return TrajectoryRecord(
        record_id=identifier,
        label=label,
        events=tuple(events),
        metadata=metadata,
        raw=dict(raw),
    )


def _official_input_signature(raw: Mapping[str, Any]) -> str:
    """Hash exactly the fields supplied before the official judge prompt."""

    payload = {
        "profile": raw.get("profile"),
        "contents": raw.get("contents"),
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def load_rjudge_directory(
    data_dir: str | Path,
    *,
    deduplicate_inputs: bool = True,
) -> RJudgeLoadResult:
    """Load all ``*.json`` files in the R-Judge category directories.

    ``deduplicate_inputs`` removes later rows whose official judge input
    (``profile`` plus ``contents``) is byte-equivalent after canonical JSON
    serialization.  The current public repository has 571 rows and two such
    duplicates, yielding the 569 distinct inputs reported by the paper.
    """

    root = Path(data_dir)
    paths = sorted(root.glob("*/*.json"))
    if not paths:
        raise FileNotFoundError(f"no R-Judge JSON files under {root}")

    records: list[TrajectoryRecord] = []
    hashes: dict[str, str] = {}
    seen_inputs: dict[str, str] = {}
    duplicate_ids: list[str] = []
    seen_ids: set[str] = set()
    raw_rows = 0
    for path in paths:
        relative = path.relative_to(root).as_posix()
        hashes[relative] = _sha256_file(path)
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise DataFormatError(f"invalid JSON in {relative}: {exc.msg}") from exc
        if not isinstance(document, list):
            raise DataFormatError(f"R-Judge file {relative} must contain an array")
        for row_index, row in enumerate(document):
            raw_rows += 1
            if not isinstance(row, Mapping):
                raise DataFormatError(
                    f"R-Judge row {row_index} in {relative} must be an object"
                )
            record_id = canonical_text(row.get("id")) or f"{relative}:{row_index}"
            if record_id in seen_ids:
                raise DataFormatError(f"duplicate R-Judge id {record_id!r}")
            seen_ids.add(record_id)
            signature = _official_input_signature(row)
            if deduplicate_inputs and signature in seen_inputs:
                duplicate_ids.append(record_id)
                continue
            seen_inputs.setdefault(signature, record_id)
            records.append(
                normalize_rjudge_record(
                    row,
                    source_file=relative,
                    index=row_index,
                )
            )

    return RJudgeLoadResult(
        records=tuple(records),
        raw_rows=raw_rows,
        duplicate_input_ids=tuple(duplicate_ids),
        file_count=len(paths),
        file_sha256=hashes,
    )


def _section(title: str, items: Sequence[str]) -> str:
    return f"[{title}]\n" + ("\n\n".join(items) if items else "<NONE>")


def build_rjudge_views(record: TrajectoryRecord) -> dict[str, str]:
    """Build four label-free views with R-Judge-native event semantics."""

    full_items: list[str] = []
    users: list[str] = []
    actions: list[str] = []
    counters: Counter[str] = Counter()
    labels = {
        ("message", "system"): "PROFILE",
        ("message", "user"): "USER",
        ("reasoning", "assistant"): "AGENT_THOUGHT",
        ("agent_action", "assistant"): "AGENT_ACTION",
        ("tool_result", "tool"): "ENVIRONMENT",
    }
    for event in record.events:
        label = labels.get((event.kind, event.role))
        if label is None:
            raise DataFormatError(
                f"unexpected normalized R-Judge event {event.kind}/{event.role}"
            )
        position = counters[label]
        counters[label] += 1
        body = event.content if event.content else "<EMPTY>"
        rendered = f"[{label} {position:04d}]\n{body}"
        full_items.append(rendered)
        if label == "USER":
            users.append(rendered)
        elif label == "AGENT_ACTION":
            actions.append(rendered)

    last_action = actions[-1] if actions else "<NONE>"
    return {
        "full": "[VIEW full]\n\n" + _section("TRAJECTORY", full_items),
        "user_only": "[VIEW user_only]\n\n" + _section("USER_MESSAGES", users),
        "action_only": "[VIEW action_only]\n\n" + _section("AGENT_ACTIONS", actions),
        "last_action_only": (
            "[VIEW last_action_only]\n\n[LAST_AGENT_ACTION]\n" + last_action
        ),
    }


def corpus_diagnostics(load_result: RJudgeLoadResult) -> dict[str, Any]:
    """Return JSON-serializable provenance and schema diagnostics."""

    records = load_result.records
    return {
        "raw_rows": load_result.raw_rows,
        "deduplicated_rows": len(records),
        "duplicate_input_ids_removed": list(load_result.duplicate_input_ids),
        "file_count": load_result.file_count,
        "label_counts": {
            str(label): count
            for label, count in sorted(Counter(record.label for record in records).items())
        },
        "attack_type_counts": dict(
            sorted(Counter(record.metadata["attack_type"] for record in records).items())
        ),
        "category_counts": dict(
            sorted(Counter(record.metadata["category"] for record in records).items())
        ),
        "source_group_count": len(
            {record.metadata["source_file"] for record in records}
        ),
        "file_sha256": dict(load_result.file_sha256),
    }


__all__ = [
    "RJUDGE_VIEW_NAMES",
    "RJudgeLoadResult",
    "build_rjudge_views",
    "corpus_diagnostics",
    "load_rjudge_directory",
    "normalize_rjudge_record",
]
