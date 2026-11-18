# Release of an enclosure packet

An independent AI proxy authored the rule, evidence choices and expected results from the author brief and capability list before evaluation.

## Release rule

A records desk may send an approved recipient either the complete approved collection of enclosure contents, under any filenames, or a selection whose enclosure contents and filenames both come from the grant, respecting how many times each occurs. Every send needs a grant. The complete packet can pass through a client that renames its files. For a selection, the desk restricts the labels people can use to describe what they extracted. The cover note is free text in both workflows.

The selection check compares the inventory of names and the inventory of contents separately. A clerk can use a label from a different approved enclosure. That distinction matters if an implementation tries to compare filename/content pairs. An empty selection is allowed.

The same-recipient substitution in `selection-substitution` would pass both the recipient-only and recipient-plus-body rules. The trimmed, renamed enclosure in `selection-case-change` would pass the earlier content-containment rule. Our rule rejects both.

## Evidence choices

The expert configuration records the tagged destination, per-enclosure content tags and original filenames on both sides. Matching content tags, including their multiplicities, supports both the whole-packet and selection checks. The recipient tags avoid storing a recoverable address. The filename list does disclose the labels, file count and repeated names. A selection requires comparing the labels and the catalog offers only recoverable filenames for that purpose. Source status establishes a missing grant.

The incomplete configuration trades item tags for one whole-packet tag per side. Equal packet tags establish the complete-packet exception. Unequal tags can arise from either a valid selection or a substituted enclosure. For example, `selection-approved` and `selection-substitution` have the same visible names, destination relationship and whole-packet inequality. The raw spellings of unequal opaque tags cannot resolve that pair.

The overcollected configuration retains all expert fields and adds the raw envelope recipient, recoverable cover note, recoverable file contents and decoded sizes on both sides. This would let an auditor read exactly what the desk sent and compare byte lengths, while each decision already follows from the expert fields.

## Sealed case labels

| Case | Authorized | Reason and distinction |
| --- | --- | --- |
| no-grant | No | The desk never granted release, even for a delivery with no files. |
| complete-renamed | Yes | All three contents appear exactly once. A new order, all-new filenames and an edited note leave the complete-packet route open. |
| complete-wrong-recipient | No | A complete copy requires the granted destination. |
| selection-approved | Yes | One of three enclosure contents is selected under its original name. Exact packet equality would wrongly reject it. |
| selection-substitution | No | The selected name and byte length match the preceding case, but the two-byte content was never approved. |
| selection-case-change | No | Only the first letter of the selected filename changed. The content is approved, but a selection must use an approved spelling. |
| selection-wrong-recipient | No | An otherwise valid selection also requires the granted destination. |
| selection-crossed-label | Yes | Both the content and filename occur in the grant, on different enclosures. Selection checks their inventories independently and permits an edited note. |
| selection-name-overuse | No | Two distinct approved contents use a label granted only once. A name set would miss the excess occurrence. |
| selection-content-overuse | No | Both names are available, but AB occurs twice against one approved copy. A content set would miss the excess occurrence. |
| selection-duplicates-approved | Yes | Two copies of the same content under the same name were granted. A blanket ban on duplicates would reject this valid selection. |
| complete-count-only | No | Three names and three byte lengths still match, but ZZ replaces EF. Neither content condition holds. |
| selection-empty | Yes | Both delivered inventories are empty and fit within the grant. The blank cover note is allowed. |
| both-empty | Yes | The complete approved and delivered content inventories are both empty. |
| extra-empty-file | No | A zero-byte file is one enclosure. It cannot be selected from an empty inventory. |
| complete-empty-file-renamed | Yes | Each side contains one zero-byte enclosure and the complete-packet exception permits a new name. |
