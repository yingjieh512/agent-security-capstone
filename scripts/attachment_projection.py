"""Authenticated source-local evidence for the single SMTP envelope attachment policy.

The approval snapshot and mailbox each call issue() with their own source key.
An omitted record means evidence is missing. An authenticated fact=None is an
explicit negative. The concrete pilot verifies decisions only for accepted mail.
"""
from __future__ import annotations

from base64 import b64encode
from collections import Counter
import hashlib
import hmac
import json

VERSION = 1
POLICY = "single-envelope-recipient-and-decoded-attachment-byte-submultiset-v1"
ROLES = ("approval", "delivery")
KNOWN = frozenset(("recipient.raw", "recipient.tag", "body.raw", "attachment_names.raw",
                   "attachment_content.raw", "attachment_sizes.list", "attachment_count",
                   "attachment_bytes.bag_tag", "attachment_bytes.item_tags", "status"))


def wire(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(key, message):
    return hmac.new(key, wire(message), hashlib.sha256).hexdigest()


def _encode(blob):
    return b64encode(blob).decode("ascii")


def _blob_tag(key, attempt, encoded):
    return _digest(key, [POLICY, "item", attempt, encoded])


def _projection(field, attempt, fact, key):
    if field == "status":
        return "negative" if fact is None else "present"
    if fact is None:
        return None
    if field == "recipient.raw":
        return fact["recipient"]
    if field == "recipient.tag":
        return _digest(key, [POLICY, "recipient", attempt, fact["recipient"]])
    if field == "body.raw":
        return fact["body"]
    files = fact["attachments"]
    if field == "attachment_count":
        return len(files)
    if field == "attachment_sizes.list":
        return sorted(len(blob) for _, blob in files)
    if field == "attachment_names.raw":
        return sorted(name for name, _ in files)
    encoded = sorted(_encode(blob) for _, blob in files)
    if field == "attachment_content.raw":
        return encoded
    if field == "attachment_bytes.item_tags":
        return sorted(_blob_tag(key, attempt, blob) for blob in encoded)
    if field == "attachment_bytes.bag_tag":
        return _digest(key, [POLICY, "bag", attempt, encoded])
    raise ValueError(f"Unknown field {field!r}")


def issue(fields, role, attempt, fact, comparison_key, source_key):
    names = sorted(fields)
    if role not in ROLES or not isinstance(attempt, str) or not attempt:
        raise ValueError("Expected role and unique operation ID")
    if set(names) - KNOWN or len(set(names)) != len(names):
        raise ValueError("Unrecognized or duplicate field")
    if fact is not None and (not isinstance(fact["recipient"], str) or not fact["recipient"]):
        raise ValueError("A present fact needs one envelope recipient")
    payload = {name: _projection(name, attempt, fact, comparison_key) for name in names}
    header = {"version": VERSION, "policy": POLICY, "role": role, "attempt": attempt,
              "present": fact is not None, "fields": payload}
    return {**header, "mac": _digest(source_key, header)}


def _authenticate(record, names, role, attempt, key):
    header_keys = ("version", "policy", "role", "attempt", "present", "fields")
    if not isinstance(record, dict) or set(record) != {*header_keys, "mac"}:
        return False
    if (type(record["version"]) is not int or record["version"] != VERSION or
            record["policy"] != POLICY or record["role"] != role or record["attempt"] != attempt
            or type(record["present"]) is not bool or not isinstance(record["fields"], dict)
            or set(record["fields"]) != set(names) or not isinstance(record["mac"], str)
            or not record["mac"].isascii()):
        return False
    header = {k: record[k] for k in header_keys}
    return hmac.compare_digest(record["mac"], _digest(key, header))


def _nattachments(fields):
    if "attachment_count" in fields:
        return fields["attachment_count"]
    for name in ("attachment_content.raw", "attachment_bytes.item_tags",
                 "attachment_sizes.list", "attachment_names.raw"):
        if name in fields:
            return len(fields[name])
    return None


def _submultiset(a, b):
    """All copies in a must be available in b."""
    ca, cb = Counter(a), Counter(b)
    return all(count <= cb[key] for key, count in ca.items())


def _included(grant, delivered):
    """True/False only when a comparison is conclusive; None denotes missing evidence."""
    ng, nd = _nattachments(grant), _nattachments(delivered)
    if nd == 0:
        return True
    if ng is not None and nd is not None and nd > ng:
        return False
    for name in ("attachment_content.raw", "attachment_bytes.item_tags"):
        if name in grant and name in delivered:
            return _submultiset(delivered[name], grant[name])
    bag = "attachment_bytes.bag_tag"
    if bag in grant and bag in delivered:
        if grant[bag] == delivered[bag]:
            return True
        if nd is not None and nd == ng:
            return False
    if ("attachment_sizes.list" in grant and "attachment_sizes.list" in delivered
            and not _submultiset(delivered["attachment_sizes.list"], grant["attachment_sizes.list"])):
        return False
    return None


def verify(config, attempt, records, comparison_key, source_keys):
    """Check authenticated evidence. No comparison-key use by the verifier.

    Inputs with mixed raw and token fields across roles are treated as
    incomparable. The same source-independent field representation must be
    available on each side for a positive comparison.
    """
    del comparison_key  # Keeps this API explicit about its offline trust boundary.
    if not isinstance(config, dict) or not isinstance(records, dict) or set(records) - set(ROLES):
        return "unknown"
    if any(role not in config or role not in source_keys for role in ROLES):
        return "unknown"
    for role in ROLES:
        names = config[role]
        if (not isinstance(names, (tuple, list)) or not all(isinstance(name, str) for name in names)
                or set(names) - KNOWN or len(set(names)) != len(names)):
            return "unknown"
        record = records.get(role)
        if record is not None and not _authenticate(record, names, role, attempt, source_keys[role]):
            return "unknown"
    grant, delivery = (records.get(role) for role in ROLES)
    # A policy covering confirmed acceptance only leaves canceled or missing
    # delivery outside scope. Only explicit source attestation proves no grant.
    if grant is None or delivery is None or not delivery["present"]:
        return "unknown"
    if not grant["present"]:
        return "unauthorized"
    g, d = grant["fields"], delivery["fields"]
    recipient = None
    for name in ("recipient.tag", "recipient.raw"):
        if name in g and name in d:
            recipient = g[name] == d[name]
            break
    included = _included(g, d)
    if recipient is False or included is False:
        return "unauthorized"
    if recipient is True and included is True:
        return "authorized"
    return "unknown"
