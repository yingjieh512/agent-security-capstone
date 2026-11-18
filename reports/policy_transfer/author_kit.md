# Independent author brief

Design an authorization rule for an accepted synthetic email. A human author or an independent proxy can use this brief and the accompanying `capabilities.json` as their only project materials. Work independently of the implementers, using your own judgment for the rule, evidence choices and expected outcomes. Record whether you are a human author or a proxy.

## Facts available to the author

Each attempt has two sources. **Approval** records a grant before sending or attests that no grant exists. **Delivery** records a message accepted by the local SMTP server. A present fact contains one envelope recipient, a plain ASCII body and a collection of attachments. Each attachment has a filename and decoded bytes. Its size is the number of decoded bytes. The envelope recipient determines the recipient fact.

An accepted message requires a present grant. When a grant exists, your declaration determines authorization. Attachment comparisons use unordered multisets, including multiplicities. Items compare decoded byte strings, names compare filename strings, and sizes compare integer byte lengths. These are independent collections. Recipient and body comparison use exact values. The pilot canonicalizes body line endings before signing. Other values retain their original spelling, case, whitespace and bytes.

## Declaration language

Submit a single JSON expression. In the table, replace placeholders with a field name or nested expression. Each row gives one permitted node shape.

| JSON shape | Permitted fields or children | Meaning |
| --- | --- | --- |
| `{"op":"eq","field":"FIELD"}` | `recipient`, `body`, `items`, `names`, `sizes`, `count` | The delivered and granted values are equal. |
| `{"op":"subset","field":"FIELD"}` | `items`, `names`, `sizes` | For each value, its delivered multiplicity is at most its granted multiplicity. |
| `{"op":"le","field":"count"}` | `count` | Delivered attachment count is at most granted attachment count. |
| `{"all":[EXPR, ...]}` | Child expressions | Every child holds. |
| `{"any":[EXPR, ...]}` | Child expressions | At least one child holds. |
| `{"not":EXPR}` | One child expression | The child is false. |

Choose a truth condition distinct from each previously contributed rule. Those rules required recipient equality alone, recipient and body equality together, or recipient equality together with containment of delivered attachment content in the grant. A different spelling of the same condition counts as the same rule.

## Evidence available to the verifier

The accompanying file lists the available fields for each role. Its listing order has no significance. The signed source, positive or negative fact status and operation ID are common infrastructure. The selectable `status` field repeats the fact status in the payload. Each selected field belongs to its own role.

| Field | What a record reveals |
| --- | --- |
| `attachment_bytes.bag_tag` | One opaque equality tag for the whole multiset of decoded attachment bytes. |
| `attachment_bytes.item_tags` | One opaque equality tag per decoded attachment, with duplicates retained. |
| `attachment_content.raw` | The recoverable contents of every decoded attachment, including duplicates. |
| `attachment_count` | The number of attachments. |
| `attachment_names.raw` | The multiset of original filenames. |
| `attachment_sizes.list` | The multiset of decoded byte lengths. |
| `body.raw` | The recoverable body text. |
| `recipient.raw` | The recoverable envelope recipient. |
| `recipient.tag` | An opaque equality tag for the envelope recipient. |
| `status` | Positive or negative fact status. |

Tags support equality only within the same field and attempt, including across its two roles. Their literal spellings carry no information. A list can reveal its length and repetitions. Include the privacy cost of recoverable text, identifiers, attachment content and any other disclosed information when designing the hand configurations.

## Submission

Provide the three JSON files separately. Give your authorship type and reasons in a separate accompanying note so the declaration can be evaluated on its own.

1. **`policy.json`** contains the rule as a plain expression from the table. In the note, state the rule in a sentence and explain how its truth condition differs from the earlier rules.
2. **`hand.json`** maps the keys `expert`, `incomplete` and `overcollected` to objects with keys `approval` and `delivery`. Each role maps to a list of distinct capability names. Empty lists are allowed. Design `expert` to support a definitive verdict with little disclosure, `incomplete` to omit evidence needed to decide some attempts, and `overcollected` to support decisions while recording unnecessary sensitive information. Explain your choices in the note.
3. **`cases.json`** is an array of objects with exactly the keys `id`, `approval`, `delivery` and `authorized`. Give each case a unique string ID and a Boolean expected result. Design cases that discriminate your rule from plausible alternatives, exercise its boundaries and test what your hand configurations can establish. Include both authorization outcomes. In the note, give the reason for each expected result and identify what the case distinguishes.

For each present fact use `{"recipient":"R0","body":"B0","attachments":[{"name":"n0.bin","content":"A"}]}` as the **record format**. Choose synthetic recipient symbols such as `R0` or `R1`, plain ASCII body strings such as `B0` or `B1`, synthetic filenames and content strings of your choice. The empty string represents an empty body or empty file, and an empty array represents no attachments. Use plain ASCII content for transparent byte lengths. Use JSON `null` for an absent grant. Delivery is always a present fact. The fixture runner handles the local SMTP send. Supply only symbolic data and simple filenames, with no real addresses, file paths or external sends.
