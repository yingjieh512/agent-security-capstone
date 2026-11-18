"""Extract observable send-call evidence shapes without storing raw message values.

The pinned datasets have no independent mailbox or approval ledger. These rows
describe available fields and linkage strength. A quoted destination in an
earlier user message, an API status, or a provider message ID is not a verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

from trajectory_audit.data import load_records
from trajectory_audit.download import ATBENCH_REVISION, ATBENCH_SHA256


AT_PATH = Path("data/raw/atbench/test.json")
CLAW_PATH = Path("data/raw/atbench_claw/test.json")
CLAW_REVISION = "75f70f4bfd8305e33e22006e1e6eeb668684d3f2"
CLAW_SHA256 = "bc04db0db900fd63ac4c59ba651584be2dc8dbd51861c98ffeb21f13c9495c8b"

TARGET_FIELDS = {
    "send_email": ("to", "mTo", "receiver", "email", "Correo_Delivery"),
    "send_sms": ("to", "mobile_number", "mobiles", "mno", "phone_number",
                 "number", "phone", "phonenumbers"),
    "sendMessage": ("to",),
    "gog gmail send": ("to", "--to"),
}
# Exact field-name allowlists after case/underscore normalization. Read only
# top-level API fields and ATBench's designated result map, not arbitrary text.
STATUS_KEYS = {"status", "state", "deliverystatus", "deliverystate", "submissionstatus"}
MESSAGE_KEYS = {"messageid", "emailid", "smsid", "transactionid", "id"}
RECIPIENT_KEYS = {"to", "recipient", "recipients", "recipientaddress", "recipientnumber",
                  "destination", "destinationnumber", "acceptedrecipients", "receiver",
                  "accepted", "mobiles"}


def data_manifest():
    return {
        "ATBench": {"revision": ATBENCH_REVISION, "sha256": ATBENCH_SHA256, "rows": 1000},
        "Claw": {"revision": CLAW_REVISION, "sha256": CLAW_SHA256, "rows": 500},
    }


def _primary_values(tool, args):
    if not isinstance(args, dict):
        return ()
    values = []
    for key in TARGET_FIELDS[tool]:
        if key in args:
            raw = args[key]
            items = raw if isinstance(raw, list) else [raw]
            values.extend(str(item).strip() for item in items if type(item) in (str, int))
    return tuple(values)


def _target(tool, args, values):
    """Recognize one explicit scalar recipient, not a guessed list or alias resolution."""
    if not isinstance(args, dict) or any(args.get(k) for k in ("cc", "bcc", "--cc", "--bcc")):
        return None
    if len(values) != 1:
        return None
    target = values[0]
    if not target or any(delimiter in target for delimiter in (";", ",", "\n")):
        return None
    if tool in ("send_email", "gog gmail send") and not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", target):
        return None
    if tool == "send_sms" and not re.fullmatch(r"\+?\d+", target):
        return None
    return target


def _literal_in_user(target, user):
    if target is None:
        return False
    # Conservative literal comparison. A no-match can reflect spelling or a
    # task where the recipient is specified by reference.
    pattern = r"(?<![\w@+.-])" + re.escape(target) + r"(?![\w@+-]|\.\w)"
    return any(re.search(pattern, text) is not None for text in user)


def _json_object(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _call_row(dataset, record_no, call_index, tool, args, user, linkage, documents,
              envelope_is_error, result_blocks, result_texts, observer):
    values = _primary_values(tool, args)
    target = _target(tool, args, values)
    trajectory_id = f"{dataset.lower()}:row{record_no}"
    keys = {k.lower().replace("_", "") for document in documents for k in document}
    row = {
        "trajectory_id": trajectory_id,
        "source_row": record_no,
        "call_key": f"{trajectory_id}:call{call_index}",
        "call_index": call_index,
        "dataset": dataset,
        "tool": tool,
        "linkage": linkage,
        "single_target": target is not None,
        "target_user_literal": _literal_in_user(target, user),
        "structured_result": bool(documents),
        "result_has_status": bool(keys & STATUS_KEYS),
        "result_has_message_id": bool(keys & MESSAGE_KEYS),
        "result_has_recipient": bool(keys & RECIPIENT_KEYS),
        "envelope_is_error": envelope_is_error,
        "result_blocks": result_blocks,
    }
    if observer is not None:
        # Private in-memory access for independent text corroboration coding.
        # Persistent per-call data contains no message or destination values.
        observer(row=row.copy(), target=target, primary_to_fields=values, prior_user_texts=tuple(user),
                 result_texts=tuple(result_texts))
    return row


def _at_calls(path, observer):
    for record_no, record in enumerate(load_records(path)):
        user = []
        for i, event in enumerate(record.events):
            if event.kind == "message" and event.role == "user":
                user.append(event.content)
            if event.kind != "tool_call" or event.name not in ("send_email", "send_sms"):
                continue
            following = record.events[i + 1:i + 2]
            if following and following[0].kind == "tool_result":
                linkage = "adjacent"
                result_texts = [following[0].content]
                obj = _json_object(result_texts[0])
                documents = [obj] if obj is not None else []
                if obj is not None and isinstance(obj.get("result"), dict):
                    documents.append(obj["result"])
            else:
                linkage, documents, result_texts = "missing", [], []
            yield _call_row("ATBench", record_no, i, event.name, _json_object(event.arguments),
                            user, linkage, documents, None, int(linkage == "adjacent"),
                            result_texts, observer)


def _claw_calls(rows, observer):
    for record_no, row in enumerate(rows):
        messages = [(i, e["message"]) for i, e in enumerate(row["trajectory"]["events"])
                    if e["type"] == "message"]
        responses = defaultdict(list)
        id_count = Counter()
        for i, msg in messages:
            if msg["role"] == "toolResult":
                responses[msg.get("toolCallId")].append((i, msg))
            if msg["role"] == "assistant":
                id_count.update(b.get("id") for b in msg["content"] if b["type"] == "toolCall")
        user = []
        call_index = 0
        for i, msg in messages:
            if msg["role"] == "user":
                user.extend(b["text"] for b in msg["content"] if b["type"] == "text")
            if msg["role"] != "assistant":
                continue
            for block in msg["content"]:
                if block["type"] != "toolCall":
                    continue
                call_index += 1
                tool = block["name"]
                if tool not in ("sendMessage", "gog gmail send"):
                    continue
                cid = block.get("id")
                linked = responses.get(cid, [])
                bound = (cid and id_count[cid] == 1 and len(linked) == 1
                         and linked[0][0] > i and linked[0][1].get("toolName") == tool)
                linkage = "id_name" if bound else ("ambiguous" if linked else "missing")
                result = linked[0][1] if bound else {}
                blocks = result.get("content", [])
                result_texts = [b["text"] for b in blocks if isinstance(b.get("text"), str)]
                documents = [obj for text in result_texts if (obj := _json_object(text)) is not None]
                yield _call_row("Claw", record_no, call_index, tool, block.get("arguments"),
                                user, linkage, documents, result.get("isError"), len(blocks),
                                result_texts, observer)


def load_cases(at_path=AT_PATH, claw_path=CLAW_PATH, *, observer=None):
    """Return metadata by call; split by trajectory_id. An optional callback can
    code literal corroboration in memory before the raw text is discarded.
    """
    at_path, claw_path = Path(at_path or AT_PATH), Path(claw_path or CLAW_PATH)
    for path, expected in ((at_path, ATBENCH_SHA256), (claw_path, CLAW_SHA256)):
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Unexpected dataset checksum: {path}")
    rows = list(_at_calls(at_path, observer))
    rows.extend(_claw_calls(json.loads(claw_path.read_text(encoding="utf-8")), observer))
    if len({r["call_key"] for r in rows}) != len(rows):
        raise ValueError("Call identifiers are not unique")
    return rows


if __name__ == "__main__":
    cases = load_cases()
    print(f"{len(cases)} calls in {len({r['trajectory_id'] for r in cases})} trajectories")
    for tool in TARGET_FIELDS:
        subset = [r for r in cases if r["tool"] == tool]
        print(tool, len(subset), {k: sum(bool(r[k]) for r in subset) for k in (
            "single_target", "target_user_literal", "structured_result", "result_has_status",
            "result_has_message_id", "result_has_recipient", "envelope_is_error")})
