"""Bounded synthesis of separate approval and delivery mail logging schemas.

The menu contains the ten source projections in attachment_projection.KNOWN.
A field at both roles costs two entries. Optimize, in order, the number of raw
fields, the number of entries, the sum of fixed exposure ranks, and lexical
role/field order. Repair keeps the base fields and permits additions from caps.

The model consists of positive, complete records at a fixed binding. Enumerate
every ordered pair of facts in a configurable finite alphabet, up to a maximum
attachment multiplicity. Per-item names and contents vary independently. Exact
byte lengths follow from contents. Bag order has no meaning to this language.
Compare literal fields exactly. Opaque tokens are comparable only within their
projection namespace and scope. Across worlds, quotient by consistent renaming
of these tokens. The two-role multiplicity histogram is a complete invariant
for a pair of unordered token bags. Header, MAC, scope and status are constant
or opaque authentication metadata within this model.

A schema must distinguish every pair with conflicting raw-fact verdicts AND
the frozen runtime must give the right definite answer on every modeled world.
A collision prunes only subsets that cannot distinguish that exact pair.
Missing runtime decisions without a collision are explicitly reported and are
not an information-theoretic impossibility. Minimality is over the finite
domain, declared cost and supplied role-specific menu.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
import heapq
from itertools import combinations_with_replacement, product
import json
from math import comb

if __package__:
    from . import attachment_projection, mail_policy_runtime as runtime
else:
    import attachment_projection
    import mail_policy_runtime as runtime


ROLES = ("approval", "delivery")
FIELDS = tuple(sorted(attachment_projection.KNOWN))
ENTRIES = tuple(product(ROLES, FIELDS))
BITS = {entry: 1 << i for i, entry in enumerate(ENTRIES)}
RANK = {
    "status": 0, "attachment_count": 1, "recipient.tag": 2,
    "attachment_bytes.bag_tag": 2, "attachment_sizes.list": 3,
    "attachment_bytes.item_tags": 4, "recipient.raw": 5,
    "attachment_names.raw": 6, "body.raw": 7, "attachment_content.raw": 8,
}
RAW = sum(bit for (_, field), bit in BITS.items() if field.endswith(".raw"))
DEFAULT_DOMAIN = {
    "recipients": ["a@pilot.invalid", "b@pilot.invalid"],
    "bodies": ["alpha", "beta"],
    "names": ["a.bin", "b.bin"],
    "contents": ["A", "B", "CC"],
    "max_attachments": 2,
}
MAX_WORLDS = 100_000
MODEL_KEY = b"public-finite-model-key-for-source-simulation"
EMPTY = {role: [] for role in ROLES}


def _wire(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _mask(config):
    if not isinstance(config, dict) or set(config) != set(ROLES):
        raise ValueError("Expected approval and delivery field lists")
    result = 0
    for role in ROLES:
        fields = config[role]
        if not isinstance(fields, (list, tuple)) or not all(isinstance(f, str) for f in fields):
            raise ValueError("Expected a sequence of field names")
        if set(fields).difference(FIELDS) or len(set(fields)) != len(fields):
            raise ValueError("Unknown or duplicate projection")
        for field in fields:
            result |= BITS[role, field]
    return result


def _config(mask):
    return {role: [field for field in FIELDS if mask & BITS[role, field]] for role in ROLES}


def _cost(mask):
    indexes = tuple(i for i in range(len(ENTRIES)) if mask & (1 << i))
    return (bin(mask & RAW).count("1"), len(indexes),
            sum(RANK[ENTRIES[i][1]] for i in indexes), indexes)


def _domain(given):
    if given is None:
        given = {}
    if not isinstance(given, dict) or set(given).difference(DEFAULT_DOMAIN):
        raise ValueError("Unsupported finite-domain parameter")
    domain = dict(DEFAULT_DOMAIN, **given)
    bound = domain["max_attachments"]
    if type(bound) is not int or bound < 0 or bound > 4:
        raise ValueError("max_attachments must be an integer in [0, 4]")
    for category in ("recipients", "bodies", "names", "contents"):
        values = domain[category]
        if (not isinstance(values, (list, tuple)) or not values
                or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values)):
            raise ValueError(f"{category} requires distinct Unicode strings")
        if category in ("recipients", "names") and "" in values:
            raise ValueError(f"{category} cannot include an empty string")
    alphabet = len(domain["contents"]) * len(domain["names"])
    facts = (comb(alphabet + bound, bound) * len(domain["recipients"]) * len(domain["bodies"]))
    if facts * facts > MAX_WORLDS:
        raise ValueError(f"Finite-domain limit is {MAX_WORLDS} ordered pairs")
    return domain


def _truth(policy, grant, delivered):
    """Independent oracle on complete facts, without going through the projector."""
    if "all" in policy:
        return all(_truth(p, grant, delivered) for p in policy["all"])
    if "any" in policy:
        return any(_truth(p, grant, delivered) for p in policy["any"])
    if "not" in policy:
        return not _truth(policy["not"], grant, delivered)
    field, op = policy["field"], policy["op"]
    a, d = grant[field], delivered[field]
    if op == "eq":
        return a == d
    if op == "le":
        return d <= a
    return all(n <= a.get(k, 0) for k, n in d.items())


def _raw_fields(fact):
    attachments = fact["attachments"]
    return {
        "recipient": fact["recipient"], "body": fact["body"],
        "items": Counter(content for _, content in attachments),
        "names": Counter(name for name, _ in attachments),
        "sizes": Counter(len(content.encode("utf-8")) for _, content in attachments),
        "count": len(attachments),
    }


def _ids(values):
    seen = {}
    return [seen.setdefault(v, len(seen)) for v in values]


def _item_profile(approved, delivered):
    # Count how many opaque identities have each pair of role multiplicities.
    return tuple(sorted((approved[k], delivered[k]) for k in approved.keys() | delivered.keys()))


class _TraceFields(dict):
    """Record absent membership queries on the frozen runtime's read path.

    The positive-view evaluator uses membership followed by indexed reads of
    present fields. Holding its observed answers fixed preserves that execution
    and verdict. At least one queried absence must change in a successful
    extension. This produces a small necessary branch set for a decoder miss.
    """
    def __init__(self, payload, role, fields, missing):
        super().__init__((f, payload[f]) for f in fields)
        self.role = role
        self.missing = missing

    def __contains__(self, key):
        exists = super().__contains__(key)
        if not exists:
            self.missing.add(BITS[self.role, key])
        return exists

    def get(self, key, default=None):
        return self[key] if key in self else default


class _Model:
    def __init__(self, policy, domain):
        self.engine = runtime.compile_policy(policy)
        atoms = list(product(domain["names"], domain["contents"]))
        bags = [list(bag) for n in range(domain["max_attachments"] + 1)
                for bag in combinations_with_replacement(atoms, n)]
        self.facts = [
            {"recipient": recipient, "body": body, "attachments": [list(item) for item in bag]}
            for recipient, body, bag in product(domain["recipients"], domain["bodies"], bags)
        ]
        self.n = len(self.facts)
        self.worlds = self.n ** 2
        self.description = dict(
            domain, facts_per_role=self.n, worlds=self.worlds,
            scope="positive authenticated sources, one shared attempt, UTF-8 contents, unordered bags",
            token_equivalence="projection-specific consistent renaming across approval and delivery",
        )
        raw = [_raw_fields(f) for f in self.facts]
        self.labels = [_truth(policy, a, d) for a, d in product(raw, repeat=2)]
        self.payloads = []
        for fact in self.facts:
            value = dict(fact, attachments=[(name, content.encode("utf-8"))
                                           for name, content in fact["attachments"]])
            self.payloads.append(runtime.project(policy, FIELDS, "bounded-model", value, MODEL_KEY))
        self.features = {}
        for field in FIELDS:
            if field.endswith(".tag") or field.startswith("attachment_bytes."):
                self._add_opaque(field)
                continue
            literal = _ids(_wire(p[field]) for p in self.payloads)
            self._add_one_role(field, literal)
        self.results = {}

    def _add_one_role(self, field, literal):
        if len(set(literal)) > 1:
            self.features[BITS["approval", field]] = tuple(v for v in literal for _ in literal)
            self.features[BITS["delivery", field]] = tuple(literal * self.n)

    def _add_opaque(self, field):
        # Every source invocation in this model uses the same policy, attempt and key.
        values = [payload[field]["value"] for payload in self.payloads]
        if field == "attachment_bytes.item_tags":
            item_counts = [Counter(items) for items in values]
            self._add_one_role(field, _ids(tuple(sorted(c.values())) for c in item_counts))
            joint = _ids(_item_profile(a, d) for a, d in product(item_counts, repeat=2))
        else:
            joint = [a == d for a, d in product(values, repeat=2)]
        if len(set(joint)) > 1:
            both = BITS["approval", field] | BITS["delivery", field]
            self.features[both] = tuple(joint)

    def world(self, index):
        a, d = divmod(index, self.n)
        return {"approval": deepcopy(self.facts[a]), "delivery": deepcopy(self.facts[d])}

    def separating_masks(self, pair):
        """All minimal ways to distinguish the pair using the projected menu."""
        x, y = pair
        options = [m for m, labels in self.features.items() if labels[x] != labels[y]]
        return tuple(m for m in options if not any(p != m and p & m == p for p in options))

    def audit(self, mask):
        if mask in self.results:
            return self.results[mask]
        tables = [t for m, t in self.features.items() if m & mask == m]
        seen = {}
        collision = None
        for i, gold in enumerate(self.labels):
            signature = tuple(t[i] for t in tables)
            j = seen.setdefault(signature, i)
            if self.labels[j] != gold:
                collision = (i, j) if gold else (j, i)
                break
        if collision is not None:
            result = ("observational_collision", collision, None, 0)
        else:
            fields = _config(mask)
            role_views = {r: [{f: p[f] for f in fields[r]} for p in self.payloads] for r in ROLES}
            pairs = product(role_views["approval"], role_views["delivery"])
            result = ("finite_runtime_verified", None, None, self.worlds)
            for i, (a, d) in enumerate(pairs):
                actual = self.engine({"approval": a, "delivery": d})
                if actual is not self.labels[i]:
                    reason = "runtime_inconclusive" if actual is None else "runtime_wrong"
                    result = (reason, None, (i, actual), i + 1)
                    break
        self.results[mask] = result
        return result

    def runtime_branches(self, mask, index):
        """Return None if correct, or queried absent fields for this world's miss."""
        a, d = divmod(index, self.n)
        selected = _config(mask)
        missing = set()
        views = {
            r: _TraceFields(self.payloads[n], r, selected[r], missing)
            for r, n in zip(ROLES, (a, d))
        }
        if self.engine(views) is self.labels[index]:
            return None
        return tuple(sorted(missing))

    def explain(self, mask):
        reason, pair, failure, checked = self.audit(mask)
        return {
            "sufficient": reason == "finite_runtime_verified", "basis": reason,
            "witness": {"within": self.world(pair[0]), "violation": self.world(pair[1])} if pair else None,
            "failure": ({"world": self.world(failure[0]), "expected": self.labels[failure[0]],
                         "actual": failure[1]} if failure else None),
            "runtime_worlds_checked": checked, "domain": deepcopy(self.description),
        }


@lru_cache(maxsize=4)
def _model(policy_json, domain_json):
    return _Model(json.loads(policy_json), json.loads(domain_json))


def _get_model(policy, domain):
    runtime.validate(policy)
    return _model(_wire(policy), _wire(_domain(domain)))


def audit_config(policy, config, *, domain=None):
    """Return a bounded certificate, indistinguishable pair, or runtime failure."""
    mask = _mask(config)
    return _get_model(policy, domain).explain(mask)


def _solve(policy, base, caps, domain):
    fixed = _mask(base)
    allowed = fixed | _mask(caps)
    model = _get_model(policy, domain)
    variable = allowed & ~fixed
    stats = {"menu_configurations": 1 << bin(variable).count("1"), "candidates_popped": 0,
             "configurations_audited": 0, "collision_constraints": 0,
             "runtime_failure_expansions": 0}
    output = {
        "selected": None, "feasible": False, "domain": deepcopy(model.description), "stats": stats,
        "witness": None, "basis": None,
        "cost_order": ["raw role-field count", "role-field count", "summed exposure rank",
                       "lexicographic role-field sequence"],
        "exposure_ranks": dict(RANK),
    }
    # A full-menu collision persists at every subset. A full-menu runtime failure
    # alone does not justify this shortcut.
    stats["configurations_audited"] += 1
    if model.audit(allowed)[1] is not None:
        output.update(basis="full_menu_observational_collision", witness=model.explain(allowed)["witness"])
        return output

    queue = [(_cost(fixed), fixed)]
    discovered = {fixed}
    constraints = []
    runtime_examples = []
    while queue:
        cost, selected = heapq.heappop(queue)
        stats["candidates_popped"] += 1
        # Children cover every sufficient superset of their parent. An observed
        # opposite-label pair must be split by at least one of its discriminators.
        choices = next((opts for opts in reversed(constraints)
                        if not any(o & selected == o for o in opts)), None)
        if choices is None:
            for index in runtime_examples:
                missing = model.runtime_branches(selected, index)
                if missing is not None:
                    choices = tuple(o for o in missing if o & variable)
                    stats["runtime_failure_expansions"] += 1
                    break
        if choices is None:
            if selected != allowed:
                stats["configurations_audited"] += 1
            reason, pair, failure, _ = model.audit(selected)
            if reason == "finite_runtime_verified":
                output.update(selected=_config(selected), feasible=True, basis=reason,
                              cost=list(cost[:3]), runtime_worlds_checked=model.worlds)
                return output
            if pair is not None:
                choices = tuple(o for o in model.separating_masks(pair) if o & allowed == o)
                constraints.append(choices)
                stats["collision_constraints"] += 1
            else:
                # The concrete runtime miss is a counterexample even when the
                # observation partition admits some other, unimplemented decoder.
                assert failure is not None
                index = failure[0]
                runtime_examples.append(index)
                missing = model.runtime_branches(selected, index)
                assert missing is not None
                choices = tuple(o for o in missing if o & variable)
                stats["runtime_failure_expansions"] += 1
        for option in choices:
            child = selected | option
            if child not in discovered:
                discovered.add(child)
                heapq.heappush(queue, (_cost(child), child))

    output.update(basis="no_schema_with_complete_correct_runtime",
                  full_menu_audit=model.explain(allowed))
    return output


def compile_policy(policy, caps, *, domain=None):
    """Return the minimum feasible role configuration from arbitrary subsets of caps."""
    return _solve(policy, EMPTY, caps, domain)


def repair_config(policy, base, caps, *, domain=None):
    """Return the cheapest superset of base using permitted additions from caps."""
    result = _solve(policy, base, caps, domain)
    result["additions"] = None
    if result["selected"] is not None:
        result["additions"] = _config(_mask(result["selected"]) & ~_mask(base))
    return result


def _selfcheck():
    caps = {role: list(FIELDS) for role in ROLES}
    eq_count = {"op": "eq", "field": "count"}
    eq_body = {"op": "eq", "field": "body"}
    for policy, expected in ((eq_count, "attachment_count"), (eq_body, "body.raw")):
        result = compile_policy(policy, caps)
        assert result["selected"] == {r: [expected] for r in ROLES}, result
        witness = audit_config(policy, EMPTY)["witness"]
        assert witness and set(witness) == {"within", "violation"}
        assert audit_config(policy, result["selected"])["sufficient"]
    asymmetric = {"approval": ["attachment_count"], "delivery": ["attachment_names.raw"]}
    assert compile_policy(eq_count, asymmetric)["selected"] == asymmetric
    mixed = {"approval": ["recipient.raw"], "delivery": ["recipient.tag"]}
    eq_recipient = {"op": "eq", "field": "recipient"}
    assert compile_policy(eq_recipient, mixed)["basis"] == "full_menu_observational_collision"
    repair = repair_config(eq_recipient, mixed, {"approval": ["recipient.tag"], "delivery": []})
    assert repair["additions"] == {"approval": ["recipient.tag"], "delivery": []}
    assert compile_policy({"all": []}, caps)["selected"] == EMPTY
    tautology = {"any": [eq_body, {"not": eq_body}]}
    undecided = audit_config(tautology, EMPTY)
    assert undecided["basis"] == "runtime_inconclusive" and undecided["witness"] is None
    assert compile_policy(tautology, caps)["selected"] == {r: ["body.raw"] for r in ROLES}
    no_decoder = compile_policy(tautology, EMPTY)
    assert not no_decoder["feasible"] and no_decoder["full_menu_audit"]["failure"]["actual"] is None
    print("Bounded synthesis self-check passed")


if __name__ == "__main__":
    _selfcheck()
