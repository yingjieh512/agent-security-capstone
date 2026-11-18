"""Compile and authenticate privacy-minimized single-send evidence. Python standard library.

python -m trajectory_audit.send_log --policy recipient_body --omit '*.pair.*'
The writers have separate signing keys and share a protected comparison-key service.
The offline verifier has the role MAC keys, but does not need the comparison key.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
import hashlib
import hmac
from itertools import combinations, groupby, product
import json
from pathlib import Path

ROLES = ("approval", "delivery")
POLICIES = {"recipient": ("recipient",), "recipient_body": ("recipient", "body"),
            "explain": ("recipient", "body")}
CATALOG = tuple(sorted(
    [f"{role}.present" for role in ROLES]
    + [f"{role}.pair.{kind}" for role, kind in product(ROLES, ("tag", "stable"))]
    + [f"{role}.{dimension}.{kind}" for role, dimension, kind in
       product(ROLES, ("recipient", "body"), ("raw", "stable", "tag"))]
))
# A source can assert a confirmed negative (explicitly no grant / terminal no delivery),
# or a single recipient and exact UTF-8 body. A missing source is outside this alphabet.
LOCAL_STATES = (None, *product(("R0", "R1"), ("B0", "B1")))
WORLDS = tuple(product(LOCAL_STATES, repeat=2))


def wire(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def mac(key, obj):
    return base64.urlsafe_b64encode(hmac.digest(key, wire(obj), "sha256")).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Schema:
    policy: str
    fields: tuple[str, ...]

    def __post_init__(self):
        if self.policy not in POLICIES or len(set(self.fields)) != len(self.fields):
            raise ValueError("Unknown policy or duplicate fields")
        if set(self.fields) - set(CATALOG):
            raise ValueError("Unsupported field")
        object.__setattr__(self, "fields", tuple(sorted(self.fields)))

    @property
    def schema_id(self):
        return schema_id(self)


@lru_cache(None)
def schema_id(schema):
    return hashlib.sha256(wire(["send-log-v1", schema.policy, schema.fields])).hexdigest()


def _decision(policy, world):
    grant, delivery = world
    if delivery is None:
        return "within"
    if policy == "explain":
        if grant is None:
            return "no_grant"
        if grant[0] != delivery[0]:
            return "wrong_recipient"
        return "within" if grant[1] == delivery[1] else "wrong_body"
    dimensions = POLICIES[policy]
    permitted = grant is not None and all(
        grant[i] == delivery[i] for i, name in enumerate(("recipient", "body")) if name in dimensions
    )
    return "within" if permitted else "violation"


def _local_value(field, fact):
    _, dimension, *_ = field.split(".")
    if dimension == "present":
        return fact is not None
    if fact is None:
        return None
    if dimension == "pair":
        return tuple(fact)  # Framed pair, not concatenated strings.
    return fact[0 if dimension == "recipient" else 1]


def _observation(fields, values):
    # Equality is observable only inside a common dimension/encoding. Nonces,
    # MAC bytes and the names of isolated opaque tokens do not distinguish worlds.
    classes = {}
    signature = []
    for field, value in zip(fields, values):
        parts = field.split(".")
        if len(parts) == 2 or value is None:
            signature.append(value)
        else:
            atoms = classes.setdefault(tuple(parts[1:]), {})
            signature.append(atoms.setdefault(value, len(atoms)))
    return tuple(signature)


@lru_cache(maxsize=2048)
def _lookup(policy, fields):
    table = {}
    collision = None
    first = {}
    for world in WORLDS:
        values = (_local_value(field, world[0 if field.startswith("approval.") else 1])
                  for field in fields)
        signature = _observation(fields, values)
        label = _decision(policy, world)
        if signature in first and _decision(policy, first[signature]) != label:
            if collision is None:
                collision = {_decision(policy, first[signature]): first[signature], label: world}
            table[signature] = "unknown"
        else:
            first.setdefault(signature, world)
            table.setdefault(signature, label)
    return table, collision


def privacy_cost(fields):
    """Prefer no raw bodies, then no raw recipients, no cross-attempt tags, then fewer fields."""
    return (sum(f.endswith(".body.raw") for f in fields), sum(f.endswith(".recipient.raw") for f in fields),
            sum(f.endswith(".stable") for f in fields), len(fields))


def compile_schema(policy, allowed=None):
    fields = Schema(policy, CATALOG if allowed is None else tuple(allowed)).fields
    # If the whole menu is insufficient, no projection of the menu can resolve its collision.
    _, collision = _lookup(policy, fields)
    if collision:
        return {"policy": policy, "feasible": False, "allowed": list(fields), "witness": collision}
    # If some fully local one-attempt solution exists, every raw or globally
    # linkable option ranks strictly behind it under the chosen privacy objective.
    minimal_exposure = tuple(f for f in fields if not f.endswith((".raw", ".stable")))
    search = minimal_exposure if _lookup(policy, minimal_exposure)[1] is None else fields
    subsets = (combo for n in range(len(search)+1) for combo in combinations(search, n))
    examined = 0
    ranked = sorted(subsets, key=lambda s: (privacy_cost(s), s))
    for cost, group in groupby(ranked, privacy_cost):
        sufficient = []
        for candidate in group:
            examined += 1
            observations, counterexample = _lookup(policy, candidate)
            if counterexample is None:
                # Among ties prefer fewer distinguishable equality patterns.
                # Raw values can reveal identity: that exposure is penalized first.
                sufficient.append((len(observations), candidate))
        if sufficient:
            observable_patterns, candidate = min(sufficient)
            smaller = (s for n in range(len(candidate)) for s in combinations(fields, n))
            shorter_winner = next((s for s in smaller if _lookup(policy, s)[1] is None), None)
            return {"policy": policy, "feasible": True, "fields": list(candidate),
                    "also_minimum_field_count": shorter_winner is None,
                    "observable_equality_patterns": observable_patterns,
                    "schema_id": Schema(policy, candidate).schema_id, "worlds": len(WORLDS),
                    "menu_size": len(fields), "possible_subsets": 2**len(fields),
                    "subsets_examined_in_cost_order": examined, "privacy_cost": cost,
                    "deletion_witnesses": {
                        f: _lookup(policy, tuple(other for other in candidate if other != f))[1]
                        for f in candidate}}
    raise AssertionError("Full menu was feasible")


def issue(schema, role, attempt, fact, comparison_key, source_key):
    """Authenticate one source-local fact. None means a *confirmed* negative terminal fact.

    Do not call this for missing approvals or pending/absent deliveries: omit the
    record. The caller must supply a unique, never-reused attempt ID and a
    canonical single recipient identity. No raw field is emitted unless selected.
    """
    if role not in ROLES or not isinstance(attempt, str) or not attempt:
        raise ValueError("Expected a source role and an attempt ID")
    body_needed = any(f.startswith((role + ".body.", role + ".pair.")) for f in schema.fields)
    if fact is not None:
        if (not isinstance(fact, tuple) or len(fact) != 2 or not isinstance(fact[0], str)
                or not fact[0] or not (isinstance(fact[1], str) or (fact[1] is None and not body_needed))):
            raise ValueError("Expected a single canonical recipient and the body if required by this schema")
    payload = {}
    for field in schema.fields:
        if not field.startswith(role+"."):
            continue
        value = _local_value(field, fact)
        if value is not None and (field.endswith(".tag") or field.endswith(".stable")):
            _, dimension, kind = field.split(".")
            domain = ["send-log/eq/v1", dimension, kind]
            if kind == "tag":
                domain.append(attempt)
            value = mac(comparison_key, [*domain, value])
        payload[field] = value
    header = {"v": 1, "schema": schema.schema_id, "role": role, "attempt": attempt, "data": payload}
    return {**header, "mac": mac(source_key, header)}


def verify(schema, attempt, records, source_keys):
    """Return a forced policy outcome (including explain codes); invalid input yields unknown."""
    seen = set()
    available = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"v", "schema", "role", "attempt", "data", "mac"}:
            return "unknown"
        role = record["role"]
        if (not isinstance(role, str) or role not in ROLES or role not in source_keys or role in seen
                or type(record["v"]) is not int or record["v"] != 1
                or record["schema"] != schema.schema_id or record["attempt"] != attempt
                or not isinstance(record["mac"], str) or not record["mac"].isascii()):
            return "unknown"
        data = record["data"]
        expected = {f for f in schema.fields if f.startswith(role+".")}
        if not isinstance(data, dict) or set(data) != expected:
            return "unknown"
        for field, value in data.items():
            if field.endswith(".present") and type(value) is not bool:
                return "unknown"
            if not field.endswith(".present") and value is not None and not isinstance(value, str):
                return "unknown"
        header = {k: record[k] for k in ("v", "schema", "role", "attempt", "data")}
        if not hmac.compare_digest(record["mac"], mac(source_keys[role], header)):
            return "unknown"
        seen.add(role)
        available.update(data)
    fields = tuple(sorted(available))
    signature = _observation(fields, (available[f] for f in fields))
    return _lookup(schema.policy, fields)[0].get(signature, "unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=POLICIES, default="recipient")
    parser.add_argument("--omit", action="append", default=[], help="Remove matching source fields (glob)")
    parser.add_argument("--capabilities", type=Path, help="JSON object mapping both source roles to allowed projection names")
    args = parser.parse_args()
    allowed = CATALOG
    if args.capabilities:
        caps = json.loads(args.capabilities.read_text(encoding="utf-8"))
        if not isinstance(caps, dict) or set(caps) != set(ROLES):
            parser.error("Capabilities must list approval and delivery (empty lists are valid)")
        if any(not isinstance(caps[r], list) or not all(isinstance(x, str) for x in caps[r]) for r in ROLES):
            parser.error("Each source must declare a list of projection names")
        allowed = tuple(f"{r}.{name}" for r in ROLES for name in caps[r])
        if set(allowed) - set(CATALOG):
            parser.error("Unsupported projection in capability declaration")
    allowed = [f for f in allowed if not any(fnmatchcase(f, pat) for pat in args.omit)]
    print(json.dumps(compile_schema(args.policy, allowed), indent=2))


if __name__ == "__main__":
    main()
