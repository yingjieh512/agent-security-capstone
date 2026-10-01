from trajectory_audit.additional_experiments_cli import build_parser


def test_additional_cli_exposes_both_standalone_experiments() -> None:
    parser = build_parser()
    cross = parser.parse_args(["cross-release", "--ece-bins", "15"])
    risk = parser.parse_args(["risk-exposed", "--groups", "25"])
    assert cross.command == "cross-release"
    assert cross.ece_bins == 15
    assert risk.command == "risk-exposed"
    assert risk.groups == 25
