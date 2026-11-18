"""Inspect naturally recorded send outcomes and possible second reads.

Run at repository root with PYTHONPATH=src .venv/bin/python scripts/audit_natural_send_evidence.py.
Only counts, public row positions and tool names are emitted.
"""

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from trajectory_audit.data import normalize_record
from trajectory_audit.download import ATBENCH_SHA256


CLAW_SHA256 = "bc04db0db900fd63ac4c59ba651584be2dc8dbd51861c98ffeb21f13c9495c8b"
STATUS_FIELDS = {"state", "delivery_state", "deliverystate", "delivery_status",
                 "network_status", "submission_status"}


def load(dataset, digest):
    data = Path(f"data/raw/{dataset}/test.json").read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"Expected pinned {dataset} release")
    return json.loads(data)


def atbench(rows):
    counters, tags, later_calls = defaultdict(Counter), defaultdict(Counter), Counter()
    readbacks = []
    for row_index, raw in enumerate(rows):
        events = normalize_record(raw, row_index).events
        seen = set()
        for index, call in enumerate(events):
            if call.kind != "tool_call" or call.name not in ("send_email", "send_sms"):
                continue
            seen.add(call.name)
            c = counters[call.name]
            c["calls"] += 1
            response = events[index + 1]
            if response.kind != "tool_result":
                continue
            c["adjacent_result"] += 1
            envelope = json.loads(response.content)
            c["success_envelope"] += int(envelope.get("status") == "success")
            result = envelope["result"]
            states = {str(v).casefold() for k, v in result.items()
                      if k.casefold() in STATUS_FIELDS and isinstance(v, str)}
            tags[call.name].update(states)
            c["structured_state_string"] += int(bool(states))
            # Subsequent event counts are per sending attempt, so windows may overlap.
            for offset in range(index + 2, len(events)):
                follow = events[offset]
                if follow.kind != "tool_call":
                    continue
                later_calls[follow.name] += 1
                if follow.name == "list_sms_messages" and events[offset + 1].kind == "tool_result":
                    messages = json.loads(events[offset + 1].content)["result"]["results"]
                    corroborated = any(
                        result.get("sms_id") and result.get("recipient_number")
                        and item.get("id") == result["sms_id"]
                        and item.get("phone") == result["recipient_number"]
                        and bool(item.get("delivered_on"))
                        for item in messages
                    )
                    readbacks.append({"row_index": row_index, "send_event": index,
                                      "read_event": offset, "id_target_delivery_time_match": corroborated})
        for family in seen:
            counters[family]["traces"] += 1
    return {"counts_by_tool": dict(counters), "state_values_by_tool": dict(tags),
            "subsequent_tool_names": later_calls, "list_sms_readback": readbacks}


def claw(rows):
    counters, later_calls, readbacks = defaultdict(Counter), Counter(), []
    for row_index, row in enumerate(rows):
        messages = [e["message"] for e in row["trajectory"]["events"] if e["type"] == "message"]
        calls = {}
        receipts = {}
        for idx, m in enumerate(messages):
            if m["role"] == "assistant":
                for b in m["content"]:
                    if b["type"] == "toolCall":
                        if b["id"] in calls:
                            raise ValueError("duplicate call ID")
                        calls[b["id"]] = (idx, b)
            elif m["role"] == "toolResult":
                if m["toolCallId"] in receipts:
                    raise ValueError("duplicate result ID")
                receipts[m["toolCallId"]] = (idx, m)
        seen = set()
        for call_id, (call_idx, call) in calls.items():
            name = call["name"]
            if name not in ("sendMessage", "gog gmail send"):
                continue
            seen.add(name)
            c = counters[name]
            c["calls"] += 1
            receipt_idx, receipt = receipts[call_id]
            if not (receipt_idx > call_idx and receipt["toolName"] == name):
                raise ValueError("send call/receipt mismatched")
            c["id_name_bound"] += 1
            c["is_error_false"] += int(receipt.get("isError") is False)
            for block in receipt["content"]:
                if block["type"] != "text":
                    continue
                c["text_blocks"] += 1
                try:
                    payload = json.loads(block["text"])
                except json.JSONDecodeError:
                    continue
                c["json_dict_blocks"] += int(isinstance(payload, dict))
            for follow_id, (follow_idx, follow) in calls.items():
                if follow_idx <= receipt_idx:
                    continue
                later_calls[follow["name"]] += 1
                if name == "sendMessage" and follow["name"] == "readMessages":
                    target = str(call["arguments"]["to"]).split(":")[-1]
                    read_target = str(follow["arguments"]["channelId"]).split(":")[-1]
                    body = call["arguments"]["content"].strip().casefold()
                    read_result = receipts[follow_id][1]
                    read_text = " ".join(b.get("text", "") for b in read_result["content"]).casefold()
                    readbacks.append({"row_index": row_index, "send_event": call_idx,
                                      "read_event": follow_idx, "same_target_suffix": target == read_target,
                                      "full_body_substring": bool(body) and body in read_text,
                                      "observed_empty_message": "no messages found" in read_text})
        for name in seen:
            counters[name]["traces"] += 1
    return {"counts_by_tool": dict(counters), "subsequent_tool_names": later_calls,
            "read_messages_readbacks": readbacks}


if __name__ == "__main__":
    print(json.dumps({"atbench": atbench(load("atbench", ATBENCH_SHA256)),
                      "claw": claw(load("atbench_claw", CLAW_SHA256))}, indent=2, sort_keys=True))
