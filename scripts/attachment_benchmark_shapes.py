"""Choose non-sensitive size templates for synthetic SMTP messages in the attachment pilot."""
from __future__ import annotations

import json

from evidence_pilot_data import data_manifest
from run_send_field_inventory import load_payloads

EMAIL_TOOLS = (("ATBench", "send_email"), ("Claw", "gog gmail send"))


def load_templates():
    """Return extremes by UTF-8 body size, then call key, per pinned single-target email cohort."""
    groups = {pair: [] for pair in EMAIL_TOOLS}
    # load_payloads verifies both release checksums before processing the original arguments.
    for record in load_payloads():
        pair = record["dataset"], record["tool"]
        if pair in groups and record["recipient"] and record["body"]:
            groups[pair].append((len(record["body"].encode("utf-8")), record["call_key"]))
    templates = []
    for (dataset, tool), candidates in groups.items():
        if len(candidates) < 2 or len({key for _, key in candidates}) != len(candidates):
            raise ValueError(f"Expected distinct, eligible original calls for {dataset}/{tool}")
        ordered = sorted(candidates)
        for size, key in (ordered[0], ordered[-1]):
            templates.append(dict(dataset=dataset, tool=tool, call_key=key, body_bytes=size))
    return templates


if __name__ == "__main__":
    result = load_templates()
    assert len({r["call_key"] for r in result}) == 4
    assert all(r["body_bytes"] > 0 and set(r) == {"dataset","tool","call_key","body_bytes"} for r in result)
    print(json.dumps({"sources": data_manifest(), "templates": result}, indent=2))
