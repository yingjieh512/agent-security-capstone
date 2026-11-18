"""Security and minimization properties of the bounded send-log prototype."""
from copy import deepcopy
from fnmatch import fnmatchcase
from itertools import product

import pytest

from trajectory_audit.send_log import CATALOG, ROLES, Schema, compile_schema, issue, verify


def configured(policy):
    result = compile_schema(policy)
    return Schema(policy, tuple(result["fields"]))


KEYS = {"approval": b"test A", "delivery": b"test D"}
COMPARISON = b"test value comparison key"


def write(schema, attempt, grant, effect):
    return [issue(schema, role, attempt, value, COMPARISON, KEYS[role])
            for role, value in zip(ROLES, (grant, effect))]


def test_compiler_produces_policy_specific_schema_and_loss_witnesses():
    for policy, nfields in [("recipient", 2), ("recipient_body", 2), ("explain", 4)]:
        result = compile_schema(policy)
        assert len(result["fields"]) == nfields and all(f.endswith(".tag") for f in result["fields"])
        for removed, witness in result["deletion_witnesses"].items():
            sub = Schema(policy, tuple(f for f in result["fields"] if f != removed))
            for expected, world in witness.items():
                # Opposite verdicts genuinely collide in the reduced signed evidence semantics.
                assert verify(sub, "id", write(sub, "id", *world), KEYS) == "unknown"
                full = Schema(policy, tuple(result["fields"]))
                assert verify(full, "id", write(full, "id", *world), KEYS) == expected


def test_capability_mismatch_and_no_fabricated_binding():
    allowed = [f for f in CATALOG if not fnmatchcase(f, "delivery.body.*") and not fnmatchcase(f, "delivery.pair.*")]
    assert compile_schema("recipient", allowed)["feasible"]
    assert not compile_schema("recipient_body", allowed)["feasible"]
    assert not compile_schema("recipient", ["approval.recipient.raw","delivery.recipient.tag"])["feasible"]


@pytest.mark.parametrize("policy", ["recipient", "recipient_body"])
def test_fresh_out_of_alphabet_values_match_direct_oracle(policy):
    # Unseen strings, an empty approved body and spelling-sensitive UTF-8 payloads.
    vals = (None, *product(("甲", "Z", "third"), ("", "Résumé", "re\u0301sume")))
    schema = configured(policy)
    for grant, effect in product(vals, repeat=2):
        expected = effect is None or (grant is not None and
                                      (grant[0] == effect[0] if policy == "recipient" else grant == effect))
        assert verify(schema, "fresh", write(schema, "fresh", grant, effect), KEYS) == (
            "within" if expected else "violation")


def test_source_integrity_and_missing_terminal():
    schema = configured("recipient_body")
    x = ("user", "content")
    approval, delivered = write(schema, "one", x, x)
    _, cancelled = write(schema, "one", x, None)
    _, other = write(schema, "two", x, x)
    assert verify(schema, "one", [cancelled], KEYS) == "within"
    for records in ([approval], [delivered], [approval, other], [approval, approval],
                    [{**approval, "role":"delivery"}, delivered]):
        assert verify(schema, "one", records, KEYS) == "unknown"
    tampered = deepcopy(delivered)
    tampered["data"]["delivery.pair.tag"] = None
    assert verify(schema, "one", [approval, tampered], KEYS) == "unknown"
    assert verify(configured("recipient"), "one", [approval, delivered], KEYS) == "unknown"


def test_same_attempt_equalities_survive_and_cross_attempt_tags_rotate():
    schema = Schema("recipient_body", tuple(f"{r}.{d}.tag" for r in ROLES for d in ("recipient", "body", "pair")))
    x = ("x", "x")
    a, d = write(schema, "1", x, x)
    _, another = write(schema, "2", x, x)
    assert a["data"]["approval.recipient.tag"] == d["data"]["delivery.recipient.tag"]
    assert a["data"]["approval.recipient.tag"] != a["data"]["approval.body.tag"]
    assert d["data"]["delivery.recipient.tag"] != another["data"]["delivery.recipient.tag"]


def test_joint_tags_hide_which_dimension_changed_but_diagnostic_mode_distinguishes_it():
    grant = ("A", "a")
    full = configured("explain")
    minimal = Schema("explain", tuple(f"{r}.pair.tag" for r in ROLES))
    for effect, diagnosis in [(("B", "a"), "wrong_recipient"), (("A", "b"), "wrong_body")]:
        assert verify(full, "id", write(full, "id", grant, effect), KEYS) == diagnosis
        assert verify(minimal, "id", write(minimal, "id", grant, effect), KEYS) == "unknown"


def test_source_can_avoid_reading_body_for_recipient_only_policy():
    scoped = configured("recipient")
    assert verify(scoped, "id", write(scoped, "id", ("A", None), ("A", None)), KEYS) == "within"
    with pytest.raises(ValueError):
        write(configured("recipient_body"), "id", ("A", None), ("A", None))
