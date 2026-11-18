"""Cross-tool controlled replay. From the root: PYTHONPATH=src .venv/bin/python scripts/run_cross_tool_evidence_replay.py"""
import argparse
import csv
import itertools
import json
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from evidence_pilot_data import data_manifest, load_cases

APPROVAL, INDEX, MAIL = "approval", "request_index", "mailbox"
MISSING = "unavailable"
ABSTAIN = "unknown"
PEOPLE = ("target", "alternate")
# A key lookup reveals only a lookup key, not the outcome or the decision.
KEY = "bound_key"


def decision(history):
    evidence = dict(history)
    mail = evidence.get(MAIL, MISSING)
    grant = evidence.get(APPROVAL, MISSING)
    if mail == "not_delivered":
        return "within_policy"
    if mail in PEOPLE and grant != MISSING:
        return "within_policy" if grant == mail else "violation"
    return ABSTAIN


def sources(route):
    return (APPROVAL, MAIL) if route == "direct" else (APPROVAL, INDEX, MAIL)


def worlds(condition):
    masks = [(True, True)] if condition == "complete" else list(itertools.product((True, False), repeat=2))
    return [(grant, mail, ga, ma) for grant, mail, (ga, ma) in
            itertools.product(("none", *PEOPLE), ("not_delivered", *PEOPLE), masks)]


@lru_cache(None)
def responses(source, history, condition):
    # Design prior over hypothetical cases. Neither strategy can inspect the running database.
    counts = Counter()
    for grant, mail, ga, ma in worlds(condition):
        answers = {APPROVAL: grant if ga else MISSING, MAIL: mail if ma else MISSING, INDEX: KEY}
        if all(answers[field] == observation for field, observation in history):
            counts[answers[source]] += 1
    return tuple(counts.items())


@lru_cache(None)
def choice(history, route, budget, condition, order=()):
    """Maximize correct determinate coverage, then minimize reads over the design distribution.

    A fixed ranking skips a query if taking it cannot yield a decision within
    the remaining budget, even with optimal subsequent choices. The same
    feasibility and stopping checks are shared with the planner.
    """
    if decision(history) != ABSTAIN:
        return (1.0, 0.0, None)
    if budget == 0:
        return (0.0, 0.0, None)
    seen = dict(history)
    best = (0.0, 0.0, None)
    for query in order or sources(route):
        if query in seen or (route == "indexed" and query == MAIL and seen.get(INDEX) != KEY):
            continue
        branches = responses(query, history, condition)
        n = sum(count for _, count in branches)
        coverage = cost = potentially_decidable = 0.0
        for value, count in branches:
            child = tuple(sorted((*history, (query, value))))
            resolved, reads, _ = choice(child, route, budget - 1, condition, order)
            coverage += count * resolved / n
            cost += count * reads / n
            if order:
                potentially_decidable += count * choice(child, route, budget - 1, condition)[0]
        candidate = (round(coverage, 12), round(1 + cost, 12), query)
        if order:
            if potentially_decidable > 0:
                return candidate
        elif (candidate[0], -candidate[1]) > (best[0], -best[1]):
            best = candidate
    return best


@lru_cache(None)
def fixed_order(route, budget, condition):
    # Strong comparator: all permutations, exactly on the scenario distribution at hand.
    def rank(order):
        coverage, reads, _ = choice((), route, budget, condition, order)
        return (-coverage, reads, order)
    return min(itertools.permutations(sources(route)), key=rank)


def build_backend():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE grants(attempt TEXT PRIMARY KEY, recipient TEXT);
        CREATE TABLE deliveries(attempt TEXT PRIMARY KEY, recipient TEXT);
        CREATE TABLE approvals_api(attempt TEXT PRIMARY KEY, answer TEXT);
        CREATE TABLE request_index(attempt TEXT PRIMARY KEY, message_key TEXT UNIQUE);
        CREATE TABLE receipt_api(message_key TEXT PRIMARY KEY, terminal TEXT);
    """)
    return db


def seed(db, attempt, route, grant, mail, ga, ma):
    # These two tables are the scorer's state. Source visibility never modifies them.
    if grant != "none":
        db.execute("INSERT INTO grants VALUES (?, ?)", (attempt, grant))
    if mail != "not_delivered":
        db.execute("INSERT INTO deliveries VALUES (?, ?)", (attempt, mail))
    key = attempt if route == "direct" else f"msg/{attempt}"
    if route == "indexed":
        db.execute("INSERT INTO request_index VALUES (?, ?)", (attempt, key))
    if ga:
        db.execute("INSERT INTO approvals_api VALUES (?, ?)", (attempt, grant))
    if ma:
        db.execute("INSERT INTO receipt_api VALUES (?, ?)", (key, mail))


def score_truth(db, attempt):
    unmatched = db.execute("""
        SELECT 1 FROM deliveries d LEFT JOIN grants g
          ON d.attempt=g.attempt AND d.recipient=g.recipient
        WHERE d.attempt=? AND g.attempt IS NULL
    """, (attempt,)).fetchone()
    return "violation" if unmatched else "within_policy"


def receipt_first(seen, route, remaining):
    """Handwritten rule. A definite non-delivery is sufficient by itself."""
    if decision(tuple(seen.items())) != ABSTAIN:
        return None
    if route == "indexed" and INDEX not in seen:
        return INDEX if remaining >= 2 else None
    if MAIL not in seen:
        return MAIL
    if seen[MAIL] in PEOPLE and APPROVAL not in seen:
        return APPROVAL
    return None


def audit(db, attempt, route, budget, condition, policy):
    # Only this executor accesses records, once per logged read. Policy inputs
    # are (route, budget, condition, query responses) and never scorer tables.
    priority = fixed_order(route, budget, condition) if policy == "fixed" else ()
    history = ()
    queries = []
    message_key = attempt if route == "direct" else None
    while len(queries) < budget:
        if policy == "read_all":
            query = next((q for q in (INDEX, MAIL, APPROVAL)
                          if q in sources(route) and q not in queries), None)
        elif policy == "receipt_first":
            query = receipt_first(dict(history), route, budget - len(queries))
        else:
            _, _, query = choice(history, route, budget-len(queries), condition, priority)
        if query is None:
            break
        if query == INDEX:
            row = db.execute("SELECT message_key FROM request_index WHERE attempt=?", (attempt,)).fetchone()
            message_key = row[0] if row else None
            observed = KEY if row else MISSING
        elif query == MAIL:
            assert message_key is not None
            row = db.execute("SELECT terminal FROM receipt_api WHERE message_key=?", (message_key,)).fetchone()
            observed = row[0] if row else MISSING
        else:
            row = db.execute("SELECT answer FROM approvals_api WHERE attempt=?", (attempt,)).fetchone()
            observed = row[0] if row else MISSING
        queries.append(query)
        history = tuple(sorted((*history, (query, observed))))
    return decision(history), ",".join(queries), len(queries)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=Path("outputs/cross_tool_evidence_replay"))
    out = p.parse_args().output_dir
    out.mkdir(parents=True, exist_ok=True)
    natural = load_cases()
    eligible = [row for row in natural if row["single_target"] and row["linkage"] in ("adjacent", "id_name")]
    db = build_backend()
    counts = defaultdict(Counter)
    pairs = defaultdict(Counter)
    with (out / "paired_replay.csv").open("w", newline="") as handle:
        wr = csv.writer(handle)
        wr.writerow(["group", "call", "tool", "route", "condition", "world", "budget", "truth",
                     "adaptive", "fixed", "adaptive_queries", "fixed_queries", "adaptive_reads", "fixed_reads"])
        for case in eligible:
            route = "direct" if case["linkage"] == "id_name" else "indexed"
            for condition in ("complete", "visibility_stress"):
                for i, world in enumerate(worlds(condition)):
                    attempt = f"{case['call_key']}/{condition}/{i}"
                    seed(db, attempt, route, *world)
                    truth = score_truth(db, attempt)
                    for budget in (1, 2, 3):
                        results = {}
                        for policy in ("adaptive", "fixed", "receipt_first", "read_all"):
                            verdict, qs, reads = audit(db, attempt, route, budget, condition, policy)
                            results[policy] = (verdict, qs, reads)
                            if verdict not in (truth, ABSTAIN):
                                raise RuntimeError(f"Unsound decision at {attempt}")
                            for group in (case["tool"], "all"):
                                c = counts[condition, budget, group, policy]
                                c.update(n=1, reads=reads, correct=int(verdict == truth),
                                         wrong=int(verdict not in (truth, ABSTAIN)), unknown=int(verdict == ABSTAIN))
                        a, f = results["adaptive"], results["fixed"]
                        pair = pairs[condition, budget]
                        pair.update(n=1, decision_disagreement=int(a[0] != f[0]), fewer=int(a[2] < f[2]),
                                    more=int(a[2] > f[2]), equal=int(a[2] == f[2]))
                        wr.writerow([case["trajectory_id"], case["call_key"], case["tool"], route,
                                     condition, i, budget, truth, a[0], f[0], a[1], f[1], a[2], f[2]])
    metrics = [dict(condition=c, budget=b, group=g, policy=p, **values)
               for (c,b,g,p), values in sorted(counts.items())]
    summary = dict(manifest=data_manifest(), scanned_calls=len(natural), eligible_calls=len(eligible),
                   eligible_trajectories=len({r["trajectory_id"] for r in eligible}),
                   cases_by_tool=dict(Counter(r["tool"] for r in eligible)),
                   fixed_orders=[dict(route=r, condition=c, budget=b, order=fixed_order(r,b,c))
                                 for r,c,b in itertools.product(("direct","indexed"),
                                 ("complete","visibility_stress"), (1,2,3))],
                   metrics=metrics, paired=[dict(condition=c,budget=b,**x) for (c,b),x in pairs.items()])
    (out / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print("eligible", summary["eligible_calls"], summary["eligible_trajectories"], summary["cases_by_tool"])
    for row in metrics:
        if row["group"] == "all":
            print(row)


if __name__ == "__main__":
    main()
