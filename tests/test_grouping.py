from trajectory_audit.grouping import derive_semantic_groups, group_diagnostics, grouping_text


def _record(index: int, label: int, request: str, tool: str) -> dict:
    return {
        "id": index,
        "label": label,
        "tool_used": [{"name": tool}],
        "contents": [[{"role": "user", "content": request}]],
    }


def test_grouping_text_masks_identifiers_and_excludes_labels() -> None:
    row = _record(
        1,
        1,
        "Email account-93828 at person@example.com using https://example.com/a/42",
        "send_email",
    )
    text = grouping_text(row)
    assert "person@example.com" not in text
    assert "https://" not in text
    assert "emailtoken" in text.lower()
    assert "send_email" in text
    assert "unsafe" not in text


def test_semantic_groups_and_diagnostics_cover_every_record() -> None:
    rows = [
        _record(1, 0, "Send a project update by email", "send_email"),
        _record(2, 1, "Email a private report externally", "send_email"),
        _record(3, 0, "Read a file from the shared drive", "read_file"),
        _record(4, 1, "Delete every file in the shared drive", "delete_file"),
    ]
    groups, vectorizer, model = derive_semantic_groups(rows, n_groups=2, random_state=7)
    diagnostics = group_diagnostics(rows, groups, vectorizer, model)
    assert len(groups) == len(rows)
    assert len(set(groups)) == 2
    assert sum(item["size"] for item in diagnostics) == len(rows)

