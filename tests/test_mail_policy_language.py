"""Generic pre-freeze checks for the declaration language and its two-source receipts."""
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mail_policy_runtime as runtime
import mail_policy_search as search


ROLES = ("approval", "delivery")
KEYS = {"approval": b"approval source", "delivery": b"delivery source"}
KEY = b"scoped comparison key"
SCOPE = "qa-attempt"
EQ_RECIPIENT = {"op": "eq", "field": "recipient"}
EQ_BODY = {"op": "eq", "field": "body"}
LEAVES = [
    *(("eq", field) for field in ("recipient", "body", "items", "names", "sizes", "count")),
    *(("subset", field) for field in ("items", "names", "sizes")),
    ("le", "count"),
]


def fact(attachments=(), recipient="R0", body="B0"):
    return {"recipient": recipient, "body": body, "attachments": attachments}


FACTS = (
    fact(), fact(recipient="R1"), fact(body=""), fact([("a", b"")]),
    fact([("a", b"x")]), fact([("b", b"x")]), fact([("a", b"y")]),
    fact([("a", b"x"), ("a", b"x")]), fact([("a", b"x"), ("a", b"yy")]),
    fact([("a", b"yy"), ("a", b"x")]), fact([("a", b"x"), ("b", b"y")]),
    fact([("b", b"x"), ("a", b"y")]),
)


def full_value(mail, field):
    if field in ("recipient", "body"):
        return mail[field]
    files = mail["attachments"]
    if field == "count":
        return len(files)
    if field == "names":
        return Counter(name for name, _ in files)
    if field == "sizes":
        return Counter(len(blob) for _, blob in files)
    assert field == "items"
    return Counter(blob for _, blob in files)


def signed(policy, config, grant, delivered):
    return {
        role: runtime.issue(policy, config[role], role, SCOPE, value, KEY, KEYS[role])
        for role, value in zip(ROLES, (grant, delivered))
    }


@pytest.mark.parametrize("invalid", [
    None, {}, [], {"op": "eq"}, {"op": "eq", "field": "sender"},
    {"op": "subset", "field": "body"}, {"op": "le", "field": "items"},
    {"op": "gte", "field": "count"}, {"op": "eq", "field": "count", "value": 1},
    {"not": [EQ_BODY]}, {"all": EQ_BODY}, {"any": [True]}, {"all": [], "any": []},
])
def test_malformed_declarations_are_rejected(invalid):
    with pytest.raises(ValueError):
        runtime.compile_policy(invalid)


@pytest.mark.parametrize("op,field", LEAVES)
def test_each_leaf_against_complete_facts_and_partial_evidence(op, field):
    policy = {"op": op, "field": field}
    decide = runtime.compile_policy(policy)
    views = [runtime.project(policy, runtime.KNOWN, SCOPE, mail, KEY) for mail in FACTS]
    # Every single-field pair, including asymmetric menus, must be sound whenever decisive.
    pairs = list(product(sorted(runtime.KNOWN), repeat=2))
    total = set(runtime.observation_plans(op, field))
    for i, j in product(range(len(FACTS)), repeat=2):
        a, d = full_value(FACTS[i], field), full_value(FACTS[j], field)
        truth = (a == d) if op == "eq" else (d <= a)
        assert decide({"approval": views[i], "delivery": views[j]}) is truth
        for left, right in pairs:
            verdict = decide({"approval": {left: views[i][left]}, "delivery": {right: views[j][right]}})
            if verdict is not None or (left, right) in total:
                assert verdict is truth, (left, right, i, j)


@pytest.mark.parametrize("join,known,expected", [
    ("all", True, None), ("all", False, False),
    ("any", True, True), ("any", False, None),
])
def test_kleene_connectives_with_missing_observation(join, known, expected):
    views = {"approval": {"recipient.raw": "R0"},
             "delivery": {"recipient.raw": "R0" if known else "R1"}}
    for children in ([EQ_RECIPIENT, EQ_BODY], [EQ_BODY, EQ_RECIPIENT]):
        assert runtime.evaluate({join: children}, views) is expected
    assert runtime.evaluate({"not": EQ_BODY}, views) is None
    assert runtime.evaluate({"not": EQ_RECIPIENT}, views) is (not known)
    assert runtime.evaluate({"all": []}, views) is True
    assert runtime.evaluate({"any": []}, views) is False


@pytest.mark.parametrize("role", ROLES)
def test_receipts_bind_every_source_to_the_policy_and_attempt(role):
    config = {r: ["recipient.raw"] for r in ROLES}
    original = signed(EQ_RECIPIENT, config, FACTS[0], FACTS[0])
    verify = lambda records: runtime.verify(EQ_RECIPIENT, config, SCOPE, records, KEYS)
    assert verify(original) == "authorized"
    other = next(r for r in ROLES if r != role)
    edited = deepcopy(original[role])
    edited["fields"]["recipient.raw"] = "R1"
    replacements = [
        runtime.issue(EQ_BODY, config[role], role, SCOPE, FACTS[0], KEY, KEYS[role]),
        runtime.issue(EQ_RECIPIENT, config[role], role, "old", FACTS[0], KEY, KEYS[role]),
        runtime.issue(EQ_RECIPIENT, config[role], role, SCOPE, FACTS[0], KEY, KEYS[other]),
        original[other], edited,
    ]
    for replacement in replacements:
        assert verify({**original, role: replacement}) == "unknown"
    assert verify({other: original[other]}) == "unknown"
    assert verify(signed(EQ_RECIPIENT, config, None, FACTS[0])) == "unauthorized"
    assert verify(signed(EQ_RECIPIENT, config, FACTS[0], None)) == "unknown"


def test_tag_values_rotate_with_the_binding_and_domain():
    fields = ["recipient.tag", "attachment_bytes.item_tags", "attachment_bytes.bag_tag"]
    config = {role: fields for role in ROLES}
    mail = fact([("a", b"x"), ("a", b"x")], recipient="eA==")
    records = signed(EQ_RECIPIENT, config, mail, mail)
    baseline = records["approval"]["fields"]
    assert baseline == records["delivery"]["fields"]
    values = [baseline[field]["value"] for field in fields]
    assert values[1][0] == values[1][1]
    assert len({values[0], values[1][0], values[2]}) == 3
    for policy, attempt, key in ((EQ_BODY, SCOPE, KEY), (EQ_RECIPIENT, "other", KEY),
                                 (EQ_RECIPIENT, SCOPE, b"rotated key")):
        rotated = runtime.project(policy, fields, attempt, mail, key)
        for field in fields:
            assert rotated[field]["scope"] != baseline[field]["scope"]
            assert rotated[field]["value"] != baseline[field]["value"]
        assert runtime.evaluate(EQ_RECIPIENT, {"approval": baseline, "delivery": rotated}) is None


def test_compiler_uses_available_fields_and_reports_an_independently_checked_collision():
    domain = {"max_attachments": 0, "recipients": ["R0", "R1"], "bodies": ["B0"]}
    offered = {r: ["recipient.tag", "recipient.raw"] for r in ROLES}
    result = search.compile_policy(EQ_RECIPIENT, offered, domain=domain)
    assert result["feasible"]
    assert result["selected"] == {r: ["recipient.tag"] for r in ROLES}
    assert search.audit_config(EQ_RECIPIENT, result["selected"], domain=domain)["sufficient"]
    limited = {"approval": ["recipient.raw"], "delivery": []}
    result = search.compile_policy(EQ_RECIPIENT, limited, domain=domain)
    assert not result["feasible"] and result["selected"] is None
    audit = search.audit_config(EQ_RECIPIENT, limited, domain=domain)
    assert not audit["sufficient"]
    for witness in (result["witness"], audit["witness"]):
        positive, negative = witness["within"], witness["violation"]
        assert positive["approval"]["recipient"] == negative["approval"]["recipient"]
        assert positive["approval"]["recipient"] == positive["delivery"]["recipient"]
        assert negative["approval"]["recipient"] != negative["delivery"]["recipient"]
