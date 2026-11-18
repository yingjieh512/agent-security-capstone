"""Interpret declarative policies over two positive, authenticated mail observations.

An expression is exactly one of {"all": [expr, ...]}, {"any": [expr, ...]},
{"not": expr}, or {"op": op, "field": field}. Equality (eq) compares recipient,
body, items, names, sizes or count. Subset (subset) compares items, names or
sizes as unordered multisets, including duplicate and empty items. Count also
supports le. Both orders read delivery <= approval. Each list is an independent
projection, with no implied association between filename and byte payload.
Bodies and recipients compare as exact supplied strings. Empty all/any have
the standard True/False identities. Missing evidence propagates via strong
Kleene logic: a false conjunct or a true disjunct remains decisive.

issue() receives only one source's fact. Positive facts have a single recipient,
a text body and a sequence of (filename, decoded bytes) attachments. None is an
explicit negative. Receipts sign the declared fields, policy digest, role,
attempt and presence. The two trusted writers share a comparison key for tags
and have separate authenticator keys. Their caller binds each fresh attempt to
one approval snapshot and one terminal delivery. verify() needs no comparison
key. An omitted source or uncommitted delivery yields unknown. A committed
message with authenticated negative approval is unauthorized under every AST.

project() returns the same source-local payload as issue()["fields"]. evaluate()
accepts {"approval": payload, "delivery": payload} for two positive records.
Raw bytes are canonical base64 strings. Tagged payloads have scope and value;
only tags from the same policy, attempt, comparison key and field domain can
be compared. observation_plans() lists unconditional two-source projections
sufficient for a leaf. Individual records may allow further deductions.
"""
from __future__ import annotations

from base64 import b64decode, b64encode
from collections import Counter
import hashlib
import hmac
from itertools import product

if __package__:
    from .attachment_projection import KNOWN, ROLES, wire
else:
    from attachment_projection import KNOWN, ROLES, wire


VERSION = 1
DOMAIN = "mail-declarative-evidence-v1"
RECIPIENT = "recipient.raw"
RECIPIENT_TAG = "recipient.tag"
BODY = "body.raw"
CONTENT = "attachment_content.raw"
NAMES = "attachment_names.raw"
SIZES = "attachment_sizes.list"
COUNT = "attachment_count"
ITEM_TAGS = "attachment_bytes.item_tags"
BAG_TAG = "attachment_bytes.bag_tag"
ARRAYS = (NAMES, SIZES, CONTENT)
TAGGED = {RECIPIENT_TAG, ITEM_TAGS, BAG_TAG}
OP_FIELDS = {"eq": ("recipient", "body", "items", "names", "sizes", "count"),
             "subset": ("items", "names", "sizes"), "le": ("count",)}


def validate(policy):
    """Raise ValueError for unknown, ambiguous, or malformed JSON expressions."""
    if not isinstance(policy, dict):
        raise ValueError("A policy node must be an object")
    keys = set(policy)
    if keys == {"op", "field"}:
        op, field = policy["op"], policy["field"]
        if not isinstance(op, str) or field not in OP_FIELDS.get(op, ()):
            raise ValueError(f"Unsupported comparison {op!r} on {field!r}")
    elif keys == {"not"}:
        validate(policy["not"])
    elif keys in ({"all"}, {"any"}):
        children = next(iter(policy.values()))
        if not isinstance(children, list):
            raise ValueError("all and any require a JSON array of expressions")
        for child in children:
            validate(child)
    else:
        raise ValueError("Unknown or ambiguous policy node")


def policy_digest(policy):
    validate(policy)
    return hashlib.sha256(wire([DOMAIN, policy])).hexdigest()


def observation_plans(op, field):
    """Return (approval capability, delivery capability) pairs for a total leaf."""
    validate({"op": op, "field": field})
    if field == "count":
        sources = (COUNT, *ARRAYS, ITEM_TAGS)
        return tuple(product(sources, repeat=2))
    if field == "sizes":
        return tuple(product((SIZES, CONTENT), repeat=2))
    choices = {"recipient": (RECIPIENT, RECIPIENT_TAG), "body": (BODY,), "names": (NAMES,),
               "items": (CONTENT, ITEM_TAGS, BAG_TAG) if op == "eq" else (CONTENT, ITEM_TAGS)}
    return tuple((name, name) for name in choices[field])


def _mac(key, data):
    return hmac.new(key, wire(data), hashlib.sha256).hexdigest()


def _fields(fields):
    if not isinstance(fields, (list, tuple, set, frozenset)):
        raise ValueError("Expected a collection of capabilities")
    if not all(isinstance(f, str) and f in KNOWN for f in fields) or len(fields) != len(set(fields)):
        raise ValueError("Unknown or duplicate capability")
    return sorted(fields)


def _attempt(attempt):
    if not isinstance(attempt, str) or not attempt:
        raise ValueError("Expected a nonempty attempt ID")


def _project(digest, fields, attempt, fact, key):
    result = {}
    if fact is None:
        return {f: "negative" if f == "status" else None for f in fields}
    if not isinstance(fact, dict):
        raise ValueError("Expected a mail fact")
    if "status" in fields:
        result["status"] = "present"
    if set(fields) & TAGGED:
        scope = _mac(key, [DOMAIN, digest, "scope", attempt])

    def tagged(domain, value):
        return _mac(key, [DOMAIN, digest, domain, attempt, value])

    if RECIPIENT in fields or RECIPIENT_TAG in fields:
        recipient = fact.get("recipient")
        if not isinstance(recipient, str) or not recipient:
            raise ValueError("Expected a single envelope recipient")
        if RECIPIENT in fields:
            result[RECIPIENT] = recipient
        if RECIPIENT_TAG in fields:
            result[RECIPIENT_TAG] = {"scope": scope, "value": tagged("recipient", recipient)}
    if BODY in fields:
        if not isinstance(fact.get("body"), str):
            raise ValueError("Expected a text body")
        result[BODY] = fact["body"]
    if set(fields).intersection((COUNT, *ARRAYS, ITEM_TAGS, BAG_TAG)):
        attachments = fact.get("attachments")
        if not isinstance(attachments, (tuple, list)):
            raise ValueError("Expected an attachment sequence")
        if COUNT in fields:
            result[COUNT] = len(attachments)
        if NAMES in fields:
            names = [name for name, _ in attachments]
            if not all(isinstance(name, str) for name in names):
                raise ValueError("Expected attachment filenames")
            result[NAMES] = sorted(names)
        if set(fields).intersection((SIZES, CONTENT, ITEM_TAGS, BAG_TAG)):
            blobs = [blob for _, blob in attachments]
            if not all(isinstance(blob, bytes) for blob in blobs):
                raise ValueError("Expected decoded attachment bytes")
            if SIZES in fields:
                result[SIZES] = sorted(map(len, blobs))
            if set(fields).intersection((CONTENT, ITEM_TAGS, BAG_TAG)):
                encoded = sorted(b64encode(blob).decode("ascii") for blob in blobs)
                if CONTENT in fields:
                    result[CONTENT] = encoded
                if ITEM_TAGS in fields:
                    result[ITEM_TAGS] = {"scope": scope, "value": sorted(tagged("item", b) for b in encoded)}
                if BAG_TAG in fields:
                    result[BAG_TAG] = {"scope": scope, "value": tagged("bag", encoded)}
    return result


def project(policy, fields, attempt, fact, comparison_key):
    _attempt(attempt)
    return _project(policy_digest(policy), _fields(fields), attempt, fact, comparison_key)


def issue(policy, fields, role, attempt, fact, comparison_key, source_key):
    if role not in ROLES:
        raise ValueError("Unknown source role")
    _attempt(attempt)
    digest = policy_digest(policy)
    payload = _project(digest, _fields(fields), attempt, fact, comparison_key)
    header = {"version": VERSION, "policy": digest, "role": role, "attempt": attempt,
              "present": fact is not None, "fields": payload}
    return {**header, "mac": _mac(source_key, [DOMAIN, "receipt", header])}


def _count(view):
    if COUNT in view:
        return view[COUNT]
    for name in ARRAYS:
        if name in view:
            return len(view[name])
    if ITEM_TAGS in view:
        return len(view[ITEM_TAGS]["value"])
    return None


def _sizes(view):
    if SIZES in view:
        return view[SIZES]
    if CONTENT in view:
        return sorted(len(b64decode(item, validate=True)) for item in view[CONTENT])
    return None


def _matching_tags(grant, delivery, name):
    if name in grant and name in delivery and grant[name]["scope"] == delivery[name]["scope"]:
        return grant[name]["value"], delivery[name]["value"]
    return None


def _bags(op, grant, delivery):
    if op == "eq":
        return Counter(delivery) == Counter(grant)
    return not (Counter(delivery) - Counter(grant))


def _leaf(op, field, grant, delivery):
    if field == "body":
        return grant[BODY] == delivery[BODY] if BODY in grant and BODY in delivery else None
    if field == "recipient":
        if RECIPIENT in grant and RECIPIENT in delivery:
            return grant[RECIPIENT] == delivery[RECIPIENT]
        pair = _matching_tags(grant, delivery, RECIPIENT_TAG)
        return pair[0] == pair[1] if pair else None

    ng, nd = _count(grant), _count(delivery)
    if field == "count":
        if ng is not None and nd is not None:
            return nd == ng if op == "eq" else nd <= ng
        if op == "le" and nd == 0:
            return True
        pair = _matching_tags(grant, delivery, BAG_TAG)
        return True if pair and pair[0] == pair[1] else None

    if op == "subset" and nd == 0:
        return True
    if ng is not None and nd is not None:
        if ng == nd == 0:
            return True
        if nd > ng or (op == "eq" and ng != nd):
            return False
    if field == "names":
        return _bags(op, grant[NAMES], delivery[NAMES]) if NAMES in grant and NAMES in delivery else None
    if field == "sizes":
        gs, ds = _sizes(grant), _sizes(delivery)
        if gs is not None and ds is not None:
            return _bags(op, gs, ds)
    # Equal (or included) bytes imply equal (or included) sizes. The converse
    # does not hold. Names and bytes have no such relationship.
    if CONTENT in grant and CONTENT in delivery:
        bytes_relation = _bags(op, grant[CONTENT], delivery[CONTENT])
    else:
        items = _matching_tags(grant, delivery, ITEM_TAGS)
        bytes_relation = _bags(op, *items) if items else None
    if bytes_relation is True or (field == "items" and bytes_relation is False):
        return bytes_relation
    bag = _matching_tags(grant, delivery, BAG_TAG)
    if bag:
        if bag[0] == bag[1]:
            return True
        if field == "items" and (op == "eq" or (ng is not None and nd == ng)):
            return False
    if field == "items":
        gs, ds = _sizes(grant), _sizes(delivery)
        if gs is not None and ds is not None and not _bags(op, gs, ds):
            return False
    return None


def _compile(node):
    if "op" in node:
        op, field = node["op"], node["field"]
        return lambda g, d: _leaf(op, field, g, d)
    if "not" in node:
        child = _compile(node["not"])

        def negate(g, d):
            value = child(g, d)
            return None if value is None else not value

        return negate
    conjunction = "all" in node
    children = [_compile(child) for child in node["all" if conjunction else "any"]]

    def combine(g, d):
        result = conjunction
        for child in children:
            value = child(g, d)
            if value is (not conjunction):
                return value
            if value is None:
                result = None
        return result

    return combine


def compile_policy(policy):
    """Compile once for repeated evaluations with well-formed positive views."""
    validate(policy)
    expression = _compile(policy)

    def run(views):
        if not isinstance(views, dict) or any(not isinstance(views.get(r), dict) for r in ROLES):
            return None
        grant, delivery = views["approval"], views["delivery"]
        return expression(grant, delivery)

    return run


def evaluate(policy, views):
    return compile_policy(policy)(views)


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _valid_payload(fields, present):
    for name, value in fields.items():
        if name == "status":
            if value != ("present" if present else "negative"):
                return False
        elif not present:
            if value is not None:
                return False
        elif name in (BODY, RECIPIENT):
            if not isinstance(value, str) or (name == RECIPIENT and not value):
                return False
        elif name == COUNT:
            if type(value) is not int or value < 0:
                return False
        elif name in TAGGED:
            if not isinstance(value, dict) or set(value) != {"scope", "value"} or not _hex(value["scope"]):
                return False
            tagged = value["value"]
            if name == ITEM_TAGS:
                if not isinstance(tagged, list) or not all(map(_hex, tagged)) or tagged != sorted(tagged):
                    return False
            elif not _hex(tagged):
                return False
        else:
            if not isinstance(value, list):
                return False
            if name == SIZES:
                if not all(type(n) is int and n >= 0 for n in value):
                    return False
            elif not all(isinstance(s, str) for s in value):
                return False
            if value != sorted(value):
                return False
            if name == CONTENT and any(b64encode(b64decode(s, validate=True)).decode("ascii") != s for s in value):
                return False
    return True


def verify(policy, config, attempt, records, source_keys):
    """Authenticate both source-specific receipts and interpret their projections."""
    digest = policy_digest(policy)
    if not all(isinstance(item, dict) for item in (config, records, source_keys)) or set(records) - set(ROLES):
        return "unknown"
    try:
        _attempt(attempt)
        for role in ROLES:
            names = _fields(config[role])
            receipt = records[role]
            if not isinstance(receipt, dict) or set(receipt) != {
                "version", "policy", "role", "attempt", "present", "fields", "mac"
            }:
                return "unknown"
            header = {k: v for k, v in receipt.items() if k != "mac"}
            if (type(header["version"]) is not int or header["version"] != VERSION or header["policy"] != digest
                    or header["role"] != role or header["attempt"] != attempt or type(header["present"]) is not bool
                    or not isinstance(header["fields"], dict) or set(header["fields"]) != set(names)
                    or not _hex(receipt["mac"])):
                return "unknown"
            if not hmac.compare_digest(receipt["mac"], _mac(source_keys[role], [DOMAIN, "receipt", header])):
                return "unknown"
            if not _valid_payload(header["fields"], header["present"]):
                return "unknown"
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return "unknown"
    if not records["delivery"]["present"]:
        return "unknown"
    if not records["approval"]["present"]:
        return "unauthorized"
    result = _compile(policy)(records["approval"]["fields"], records["delivery"]["fields"])
    return {True: "authorized", False: "unauthorized", None: "unknown"}[result]
