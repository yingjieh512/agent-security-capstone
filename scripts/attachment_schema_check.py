"""Exhaustively check a finite catalogue for the held-out attachment policy.

This external checker does not import or modify the frozen send-log compiler.
Run with Python 3.10+: python scripts/attachment_schema_check.py
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations, combinations_with_replacement, product
import json
from pathlib import Path


ROLES = ("approval", "delivery")
RECIPIENT = "recipient.tag"
ITEMS = "attachment_bytes.item_tags"
BAG = "attachment_bytes.bag_tag"
COUNT = "attachment_count"
RAW_RECIPIENT = "recipient.raw"
RAW_ITEMS = "attachment_content.raw"
MENU = (RECIPIENT, ITEMS, BAG, COUNT, RAW_RECIPIENT, RAW_ITEMS)
SYMBOLS = ("A", "B", "C")


def finite_facts():
    # The first two bags give short, readable inclusion counterexamples.
    bags = [("A", "B"), ("A",)]
    for n in range(3):
        for bag in combinations_with_replacement(SYMBOLS, n):
            if bag not in bags:
                bags.append(bag)
    return list(product(("R0", "R1"), bags))


def permitted(grant, delivery):
    excess = Counter(delivery[1]) - Counter(grant[1])
    return grant[0] == delivery[0] and not excess


def observable_channel(field, grant, delivery, mask):
    """mask bits select sources (1=grant, 2=delivery); each tag domain is separate."""
    left, right = bool(mask & 1), bool(mask & 2)
    if field == RECIPIENT:
        return grant[0] == delivery[0] if left and right else None
    if field == BAG:
        return grant[1] == delivery[1] if left and right else None
    if field == ITEMS:
        # A token's actual spelling and the iteration order carry no information.
        # The verifier can count each visible token separately at both sources.
        g = Counter(grant[1]) if left else Counter()
        d = Counter(delivery[1]) if right else Counter()
        return tuple(sorted((g[t], d[t]) for t in g.keys() | d.keys()))
    sources = [fact for fact, enabled in ((grant, left), (delivery, right)) if enabled]
    if field == COUNT:
        return tuple(len(fact[1]) for fact in sources)
    if field == RAW_RECIPIENT:
        return tuple(fact[0] for fact in sources)
    if field == RAW_ITEMS:
        return tuple(fact[1] for fact in sources)
    raise ValueError(field)


def shape(config):
    """Map visible fields to channels in this witness model.

    Each occurrence has the same filename and size. A list of either reveals
    its length. Body and source statuses are constant on these positive records.
    """
    active = []
    for k, field in enumerate(MENU):
        equivalent = {field}
        if field == COUNT:
            equivalent.update(("attachment_names.raw", "attachment_sizes.list"))
        mask = sum(1 << i for i, role in enumerate(ROLES) if equivalent.intersection(config[role]))
        if mask:
            active.append(4 * k + mask)
    supported = {*MENU, "attachment_names.raw", "attachment_sizes.list", "body.raw", "status"}
    if any(set(config[role]) - supported for role in ROLES):
        raise ValueError("Unmodeled projection")
    return tuple(active)


def describe(world):
    return {role: {"recipient": who, "attachments": list(items)}
            for role, (who, items) in zip(ROLES, world)}


def search_data():
    worlds = list(product(finite_facts(), repeat=2))
    data = []
    for grant, delivery in worlds:
        features = tuple(observable_channel(field, grant, delivery, mask)
                         for field in MENU for mask in range(4))
        data.append((features, permitted(grant, delivery)))
    return worlds, data


def collision(config, worlds, data):
    active = shape(config)
    first = {}
    for i, (features, label) in enumerate(data):
        signature = tuple(features[j] for j in active)
        previous = first.setdefault(signature, i)
        if data[previous][1] != label:
            yes, no = (i, previous) if label else (previous, i)
            return {
                "within": describe(worlds[yes]), "violation": describe(worlds[no]),
                "common_observation": [
                    {"field": MENU[j // 4], "roles": [r for b, r in enumerate(ROLES) if j % 4 & (1 << b)],
                     "value": value} for j, value in zip(active, signature)
                ],
            }
    return None


def exposure_cost(config):
    fields = [f for role in ROLES for f in config[role]]
    return fields.count(RAW_ITEMS), fields.count(RAW_RECIPIENT), len(fields)


def minimum_additions(base, sufficient):
    # Any sufficient menu subset stays sufficient if a baseline retains more
    # fields. In the finite world identical names/sizes already provide count.
    available = {role: set(base[role]) for role in ROLES}
    for fields in available.values():
        if fields & {"attachment_names.raw", "attachment_sizes.list"}:
            fields.add(COUNT)
    best = None
    repairs = set()
    for candidate in sufficient:
        added = {role: tuple(f for f in candidate[role] if f not in available[role]) for role in ROLES}
        cost = exposure_cost(added)
        if best is None or cost < best:
            best, repairs = cost, set()
        if cost == best:
            repairs.add(tuple(added[role] for role in ROLES))
    return {"cost": list(best), "optimal_additions": [
        dict(zip(ROLES, map(list, repair))) for repair in sorted(repairs)
    ]}


def prune_existing(base, sufficient_shapes):
    """Minimize over subconfigurations that a deployment can produce by deletion."""
    choices = [[subset for n in range(len(base[role]) + 1)
                for subset in combinations(base[role], n)] for role in ROLES]
    best_cost = None
    optimum_count = 0
    selected = None
    for a, d in product(*choices):
        config = {"approval": a, "delivery": d}
        if shape(config) not in sufficient_shapes:
            continue
        fields = a + d
        cost = (fields.count("body.raw") + fields.count(RAW_ITEMS),
                fields.count("attachment_names.raw") + fields.count(RAW_RECIPIENT), len(fields))
        if best_cost is None or cost < best_cost:
            best_cost, optimum_count = cost, 0
            selected = {role: list(config[role]) for role in ROLES}
        if cost == best_cost:
            optimum_count += 1
    return {
        "selected": selected,
        "removed": {role: [f for f in base[role] if f not in selected[role]]
                    for role in ROLES} if selected is not None else None,
        "subsets": len(choices[0]) * len(choices[1]), "optimal_config_count": optimum_count,
        "cost": list(best_cost) if best_cost is not None else None,
    }


def run_search():
    worlds, data = search_data()
    role_subsets = [fields for k in range(len(MENU) + 1) for fields in combinations(MENU, k)]
    best_cost = None
    winners = []
    sufficient = []
    sufficient_by_field_count = Counter()
    for a, d in product(role_subsets, repeat=2):
        config = {"approval": a, "delivery": d}
        if collision(config, worlds, data) is not None:
            continue
        sufficient.append(config)
        cost = exposure_cost(config)
        sufficient_by_field_count[cost[-1]] += 1
        if best_cost is None or cost < best_cost:
            best_cost, winners = cost, []
        if cost == best_cost:
            winners.append({role: list(config[role]) for role in ROLES})
    if not winners:
        raise AssertionError("No sufficient configuration in the finite catalogue")
    selected = winners[0]
    manual = json.loads(Path(__file__).with_name("attachment_hand_configs.json").read_text())["configs"]
    hand_witnesses = {name: collision(config, worlds, data) for name, config in manual.items()}
    # All possible shapes in this model were checked above, including the
    # empty shape. Body/status add no channel and names/sizes expose counts.
    sufficient_shapes = {shape(config) for config in sufficient}
    prune_inputs = {name: manual[name] for name in ("full_operational", "expert_minimal")}
    prune_inputs["expert_with_body_names"] = {
        role: manual["expert_minimal"][role] + ["body.raw", "attachment_names.raw"] for role in ROLES
    }
    deletions = {}
    for role in ROLES:
        for field in selected[role]:
            reduced = {source: list(fields) for source, fields in selected.items()}
            reduced[role].remove(field)
            deletions[f"{role}.{field}"] = collision(reduced, worlds, data)
    count_only = {role: [RECIPIENT, COUNT] for role in ROLES}
    return {
        "checker": "external finite observational-equivalence search; frozen compiler unchanged",
        "worlds": len(worlds), "within_worlds": sum(label for _, label in data),
        "model": {
            "recipients": ["R0", "R1"], "attachment_values": list(SYMBOLS), "max_items_per_role": 2,
            "metadata": "All byte symbols have the same length and filename. Bodies are constant.",
            "source_condition": "Grant present and single-recipient mail accepted; envelope status is common infrastructure.",
            "observations": "Fresh opaque tags support within-attempt equality in their own domain. Item tags are unordered multisets. Raw symbols are visible when selected.",
        },
        "candidate_fields_per_role": list(MENU), "configs_examined": len(role_subsets) ** 2,
        "sufficient_configs": sum(sufficient_by_field_count.values()),
        "sufficient_configs_by_total_field_count": dict(sorted(sufficient_by_field_count.items())),
        "minimum_field_count": min(sufficient_by_field_count),
        "cost_order": ["raw attachment field count", "raw recipient field count", "total role-field count"],
        "selected_cost": list(best_cost), "optimal_config_count": len(winners), "selected": selected,
        "deletion_witnesses": deletions, "manual_collision_witnesses": hand_witnesses,
        "manual_minimum_additions": {name: minimum_additions(config, sufficient)
                                     for name, config in manual.items()},
        "pruned_existing": {name: prune_existing(base, sufficient_shapes) for name, base in prune_inputs.items()},
        "pruning_cost_order": ["recoverable content role-fields (body or attachment bytes)",
                               "raw identifier role-fields (recipient or filename)", "total role-field count"],
        "pruning_sensitivity_control": "expert_with_body_names adds body.raw and attachment_names.raw at each source to expert_minimal; constructed after the pilot as a sensitivity control.",
        "recipient_and_count_witness": collision(count_only, worlds, data),
        "scope": "Minimal only for these fields, roles, worlds, protocol assumptions and cost. The search does not generate projection operators or measure wire bytes.",
    }


if __name__ == "__main__":
    print(json.dumps(run_search(), indent=2))
