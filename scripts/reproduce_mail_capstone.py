"""Run the three local capstone experiments and compare them with their archived JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from attachment_mail_backend import ARCHIVE_SHA256, CACHE, VERSION, install


ROOT = Path(__file__).resolve().parents[1]
ARCHIVED = ROOT / "reports" / "solo_mail_audit"
OUTPUT = ROOT / "outputs" / "mail_capstone" / "reproduced"
STAGES = (
    ("demo_mail_policy_workspace.py", "workspace_demo.json"),
    ("run_solo_mail_audit.py", "results.json"),
    ("run_mail_capability_study.py", "capability_results.json"),
)


def install_archive(archive: Path) -> None:
    """Allow offline first install from the same release archive as the frozen installer."""
    _, expected = ARCHIVE_SHA256[(platform.system(), platform.machine())]
    with archive.open("rb") as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Mailpit {VERSION} archive SHA-256 differs from this platform's pinned release")
        source.seek(0)
        CACHE.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=CACHE) as staging, tarfile.open(fileobj=source, mode="r:gz") as package:
            member = package.getmember("mailpit")
            if not member.isfile():
                raise ValueError("Mailpit release archive does not contain a regular mailpit executable")
            binary = Path(staging) / "mailpit"
            with package.extractfile(member) as compressed, binary.open("wb") as output:
                shutil.copyfileobj(compressed, output)
            binary.chmod(0o700)
            binary.replace(CACHE / "mailpit")


def first_difference(expected, actual, path="$"):
    """Return one location; JSON object ordering is immaterial, array order is significant."""
    if type(expected) is not type(actual):
        return f"{path}: expected {type(expected).__name__}, got {type(actual).__name__}"
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return f"{path}: missing {sorted(expected.keys()-actual.keys())}, extra {sorted(actual.keys()-expected.keys())}"
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: expected {len(expected)} entries, got {len(actual)}"
        for i, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = first_difference(expected_item, actual_item, f"{path}[{i}]")
            if difference:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


def reproduce(archive: Path | None = None) -> None:
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or later is required")
    if (platform.system(), platform.machine()) not in ARCHIVE_SHA256:
        raise ValueError("Pinned Mailpit builds are available for macOS/Linux on arm64 or x86-64")
    if archive is not None:
        install_archive(archive)
    elif not (CACHE / "mailpit").is_file():
        print(f"Installing checksum-pinned Mailpit {VERSION} ...", flush=True)
        install()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(ROOT / path) for path in ("src", "scripts")))
    with TemporaryDirectory(prefix="run-", dir=OUTPUT) as tmp:
        for script, filename in STAGES:
            expected = json.loads((ARCHIVED / filename).read_bytes())
            actual_path = Path(tmp) / filename
            command = [sys.executable, "-B", "-S", str(ROOT / "scripts" / script), "--out", str(actual_path)]
            print(f"Running {script} ...", flush=True)
            subprocess.run(command, cwd=ROOT, env=env, check=True)
            difference = first_difference(expected, json.loads(actual_path.read_bytes()))
            if difference:
                mismatch_path = OUTPUT / f"mismatch-{filename}"
                actual_path.replace(mismatch_path)
                raise ValueError(f"{filename} differs from the archived result at {difference}. Actual: {mismatch_path}")
            print(f"Matched {filename}", flush=True)
        for _, filename in STAGES:
            (Path(tmp) / filename).replace(OUTPUT / filename)
    print(f"3 of 3 archived results reproduced. Outputs: {OUTPUT}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailpit-archive", type=Path,
                        help="Provision from the pinned compressed Mailpit release for this host (offline install)")
    args = parser.parse_args()
    try:
        reproduce(args.mailpit_archive)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f"Reproduction failed: {error}\n")


if __name__ == "__main__":
    main()
