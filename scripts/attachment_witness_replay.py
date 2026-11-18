"""Replay insufficient-schema witnesses against Mailpit; never export mailbox payloads.

Run the Mailpit install step first. Then, from the repository root:
    python scripts/attachment_witness_replay.py
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import secrets
import uuid

from attachment_mail_backend import LocalMailbox
from attachment_projection import issue, verify

ROLES = ("approval", "delivery")
BODY = "Same local witness content."
FILE_NAME = "document.bin"


def concrete_fact(symbolic):
    return {"recipient": f"{symbolic['recipient'].lower()}@witness.invalid",
            "body": BODY,
            "attachments": [(FILE_NAME, symbol.encode("ascii")) for symbol in symbolic["attachments"]]}


def rule_truth(approval, actual):
    if approval["recipient"] != actual["recipient"]:
        return "unauthorized"
    allowed = Counter(blob for _, blob in approval["attachments"])
    for _, observed_blob in actual["attachments"]:
        if allowed[observed_blob] == 0:
            return "unauthorized"
        allowed[observed_blob] -= 1
    return "authorized"


def visible_pattern(evidence):
    """Concrete plaintext and within-attempt equality, including multiplicity per opaque tag.

    Attempt IDs, context-bound MACs, and random labels for opaque tokens differ
    between messages. Their bytes are unavailable semantic features for comparing
    counterfactuals. The declared MAC/attempt bindings are verified separately.
    """
    fields = [evidence[r]["fields"] for r in ROLES]
    observed = {}
    for name in sorted(set(fields[0]) | set(fields[1])):
        if name == "attachment_bytes.item_tags":
            left, right = [Counter(f.get(name, ())) for f in fields]
            histogram = sorted((left[token], right[token]) for token in left.keys() | right.keys())
            observed[name] = (tuple(name in f for f in fields), histogram)
        elif name in {"recipient.tag", "attachment_bytes.bag_tag"}:
            # A one-sided opaque atom reveals only its presence; both expose equality.
            both = all(name in f for f in fields)
            equality = fields[0][name] == fields[1][name] if both else None
            observed[name] = (tuple(name in f for f in fields), equality)
        else:
            observed[name] = [(r, f[name]) for r, f in zip(ROLES, fields) if name in f]
    return observed


def paths(search, manual):
    for deleted, witness in search["deletion_witnesses"].items():
        role, field = deleted.split(".", 1)
        cfg = {r:list(search["selected"][r]) for r in ROLES}
        cfg[role].remove(field)
        yield f"drop:{deleted}", cfg, witness
    for name, witness in search["manual_collision_witnesses"].items():
        if witness is not None:
            yield f"manual:{name}", {r:list(manual[name][r]) for r in ROLES}, witness
    yield "recipient_and_count", {r:["recipient.tag","attachment_count"] for r in ROLES}, search["recipient_and_count_witness"]


def replay_witnesses(search, manual_configs):
    comp = secrets.token_bytes(32)
    keys = {r:secrets.token_bytes(32) for r in ROLES}
    checked = []
    pair_set, world_set = set(), set()
    with LocalMailbox() as mailbox:
        for label, config, witness in paths(search, manual_configs):
            if witness is None:
                raise AssertionError(f"Expected collision for {label}")
            observations, truths, abstract_pair = [], [], []
            for side in ("within","violation"):
                world = witness[side]
                abstract_world = json.dumps(world,sort_keys=True,separators=(",",":"))
                abstract_pair.append(abstract_world)
                world_set.add(abstract_world)
                grant = concrete_fact(world["approval"])
                send = concrete_fact(world["delivery"])
                attempt = uuid.uuid4().hex
                mailbox.submit(attempt, send["recipient"], send["attachments"], send["body"])
                readback = mailbox.read(attempt)
                oracle = mailbox.oracle(attempt)
                if readback is None or oracle is None:
                    raise AssertionError("Mailpit committed state missing")
                truths.append(rule_truth(grant, oracle))
                records = {r:issue(config[r],r,attempt,fact,comp,keys[r])
                           for r,fact in zip(ROLES,(grant,readback))}
                observations.append(visible_pattern(records))
                if verify(config,attempt,records,None,keys) != "unknown":
                    raise AssertionError(f"Verifier decided despite opposite-indistinguishable witness: {label}")
            if truths != ["authorized","unauthorized"] or observations[0] != observations[1]:
                raise AssertionError(f"Concrete mailbox failed to reproduce claimed witness: {label}")
            pair_set.add(tuple(abstract_pair))
            checked.append({"schema_variant":label,"certified_equal_visible_pattern":True,
                            "independent_mime_truths":truths,"verifier":["unknown","unknown"]})
    return {"paths":len(checked), "distinct_abstract_world_pairs":len(pair_set),
            "distinct_abstract_worlds":len(world_set), "separate_smtp_acceptances":2*len(checked),
            "equality_model":"Unmasked fields exact; one-sided opaque atoms alpha-renamed, paired "
                             "opaque domains preserve equality, item tokens preserve joint multiplicity.",
            "cases":checked}


if __name__ == "__main__":
    from attachment_schema_check import run_search

    manual = json.loads(Path(__file__).with_name("attachment_hand_configs.json").read_text())["configs"]
    print(json.dumps(replay_witnesses(run_search(),manual),indent=2))
