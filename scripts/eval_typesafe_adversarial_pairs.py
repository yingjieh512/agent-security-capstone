"""Replay the frozen three-arm ATBench holdout with TypeSafe jev-1.13.0.

The exact Jev adversarial ``prompt`` becomes TypeSafe System One's ``state``.
The official full-trajectory Noul question and 0.5 threshold are fixed. The
runner never shortens a prompt: context failures and explicit truncation are
recorded separately from judge predictions. API keys are never logged.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import getpass
import json
import os
from pathlib import Path
import random
import sys
import time
from urllib.error import HTTPError, URLError

import eval_jev_adversarial_pairs as paired
from eval_typesafe_atbench import (
    DEFAULT_MODEL, ENDPOINT, QUESTIONS, THRESHOLD, RateLimiter,
    canonical_json, digest, parse_response, post_system_one, retry_delay,
)


QUESTION = QUESTIONS["full"]
QUESTION_SHA256 = digest(canonical_json(QUESTION))
PREDICTIONS = (0, 1)
DEFAULT_STATES = Path("outputs/jev-adversarial-trajectories-holdout100-tail/states.jsonl")
SUPPORTED_MODELS = ("jev-1.13.0", "jev-1.14.0")


def default_output(model: str) -> Path:
    return Path(f"outputs/typesafe-adversarial-holdout100-tail-{model}")


def load_states(path: Path, expected_parents: int | None = 100) -> list[dict]:
    """Require exact prompts and hashes, then reuse the Jev triplet validator."""

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if "prompt" not in raw or "input_sha256" not in raw:
            raise ValueError(f"state line {line_number} needs prompt and input_sha256")
        if not isinstance(raw["prompt"], str) or raw["input_sha256"] != digest(raw["prompt"]):
            raise ValueError(f"state line {line_number} has an input hash mismatch")
    states = paired.load_states(path, None)
    parents = {row["parent_id"] for row in states}
    if expected_parents is not None and len(parents) != expected_parents:
        raise ValueError(f"expected {expected_parents} parent trajectories, found {len(parents)}")
    if len(states) != 3 * len(parents):
        raise ValueError("the fixed holdout requires one clean/control/attack triplet per parent")
    if any(row["gold"] != 1 for row in states):
        raise ValueError("this holdout requires gold-unsafe trajectories")
    if any(row["middle_truncated"] for row in states):
        raise ValueError("the fixed holdout requires untruncated input prompts")
    if not states:
        raise ValueError("no states selected")
    return states


def _redact(value: object, api_key: str) -> str:
    text = str(value)
    return text.replace(api_key, "[REDACTED]") if api_key else text


def _redact_response(response: object, api_key: str) -> object:
    if isinstance(response, dict):
        return {_redact_response(key, api_key): _redact_response(value, api_key)
                for key, value in response.items()}
    if isinstance(response, list):
        return [_redact_response(value, api_key) for value in response]
    if isinstance(response, str) and api_key:
        return response.replace(api_key, "[REDACTED]")
    return response


def classify_http_error(code: int, body: str) -> str:
    lowered = body.lower()
    if code in (400, 413, 422) and any(
        word in lowered for word in ("max_tokens_exceeded", "context", "too long", "token limit")
    ):
        return "context_rejected"
    if code == 413 or (code == 400 and "request size" in lowered):
        return "request_size_rejected"
    return "http_error"


def call_system_one(prompt: str, api_key: str, limiter: RateLimiter,
                    max_attempts: int, model: str) -> tuple[dict | None, tuple[float, int, int] | None,
                                                str | None, str | None, int]:
    """Return a valid response or a distinct failure; never shorten ``prompt``."""

    for attempt in range(1, max_attempts + 1):
        try:
            limiter.wait()
            result = post_system_one(prompt, QUESTION, model, api_key)
            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(result, dict) and (
                result.get("truncated") is True
                or (isinstance(usage, dict) and usage.get("truncated") is True)
            ):
                return result, None, "server_truncated", "server reported truncation", attempt
            parsed = parse_response(result, model)
            return result, parsed, None, None, attempt
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            error_type = classify_http_error(exc.code, body)
            error = _redact(f"HTTP {exc.code}: {body}", api_key)
            if exc.code not in (429, 500, 502, 503, 504, 529) or attempt == max_attempts:
                return None, None, error_type, error, attempt
            limiter.cooldown(retry_delay(exc, attempt))
        except (URLError, TimeoutError, ConnectionError) as exc:
            if attempt == max_attempts:
                return None, None, "transport_error", _redact(exc, api_key), attempt
            limiter.cooldown(min(2 ** attempt, 30))
        except (ValueError, TypeError, KeyError) as exc:
            return None, None, "invalid_response", _redact(exc, api_key), attempt
        except Exception as exc:
            return None, None, "unexpected_error", _redact(exc, api_key), attempt
    raise AssertionError("unreachable")


def replay_state(state: dict, api_key: str, limiter: RateLimiter,
                 max_attempts: int, model: str) -> dict:
    started = time.perf_counter()
    response, parsed, error_type, error, attempts = call_system_one(
        state["prompt"], api_key, limiter, max_attempts, model
    )
    probability, input_tokens, output_tokens = parsed if parsed else (None, None, None)
    return {
        "id": state["id"],
        "parent_id": state["parent_id"],
        "family": state["family"],
        "variant": state["variant"],
        "gold": state["gold"],
        "endpoint": ENDPOINT,
        "requested_model": model,
        "returned_model": response.get("model") if response else None,
        "question_sha256": QUESTION_SHA256,
        "threshold": THRESHOLD,
        "input_sha256": state["input_sha256"],
        "input_chars": len(state["prompt"]),
        "middle_truncated": state["middle_truncated"],
        "source_event_index": state["source_event_index"],
        "transform_sha256": state["transform_sha256"],
        "prediction": int(probability >= THRESHOLD) if probability is not None else None,
        "unsafe_probability": probability,
        "prompt_tokens": input_tokens,
        "output_tokens": output_tokens,
        "raw_response": _redact_response(response, api_key),
        "error_type": error_type,
        "error": error,
        "attempts": attempts,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def load_prior(path: Path, states: list[dict], order_seed: int,
               model: str) -> dict[str, dict]:
    expected = {state["id"]: state for state in states}
    prior: dict[str, dict] = {}
    if not path.exists():
        return prior
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        state = expected.get(str(row.get("id")))
        if state is None:
            continue
        identifier = state["id"]
        fixed = {
            "id": identifier,
            "parent_id": state["parent_id"],
            "family": state["family"],
            "variant": state["variant"],
            "gold": state["gold"],
            "endpoint": ENDPOINT,
            "requested_model": model,
            "question_sha256": QUESTION_SHA256,
            "threshold": THRESHOLD,
            "input_sha256": state["input_sha256"],
            "order_seed": order_seed,
        }
        for key, value in fixed.items():
            if row.get(key) != value:
                raise ValueError(f"saved {key} differs for {identifier} at line {line_number}")
        if row.get("prediction") in PREDICTIONS:
            response = row.get("raw_response")
            if not isinstance(response, dict):
                raise ValueError(f"saved successful row lacks raw response for {identifier}")
            if response.get("truncated") is True or (
                isinstance(response.get("usage"), dict)
                and response["usage"].get("truncated") is True
            ):
                raise ValueError(f"saved successful row was truncated for {identifier}")
            probability, input_tokens, output_tokens = parse_response(response, model)
            if (row["prediction"] != int(probability >= THRESHOLD)
                    or row.get("unsafe_probability") != probability
                    or row.get("prompt_tokens") != input_tokens
                    or row.get("output_tokens") != output_tokens):
                raise ValueError(f"saved verdict differs from raw response for {identifier}")
        if prior.get(identifier, {}).get("prediction") not in PREDICTIONS:
            prior[identifier] = row
    return prior


def summarize(states: list[dict], predictions: dict[str, dict], pairs: list[dict],
              bootstrap_replicates: int, bootstrap_seed: int, order_seed: int,
              model: str) -> dict:
    rows = [predictions[state["id"]] for state in states]
    counts = defaultdict(int)
    for row in rows:
        if row["error_type"]:
            counts[row["error_type"]] += 1
    families = sorted({pair["family"] for pair in pairs})

    def section(items: list[dict], section_states: list[dict], section_seed: int) -> dict:
        return {
            "arms": paired.arm_stats(section_states, predictions),
            "unsafe": {
                **paired.pair_metrics(items, 1),
                "bootstrap_95_ci": paired.bootstrap_ci(items, 1, bootstrap_replicates, section_seed),
            },
            "benign": {
                **paired.pair_metrics(items, 0),
                "bootstrap_95_ci": paired.bootstrap_ci(items, 0, bootstrap_replicates, section_seed + 1),
            },
        }

    return {
        "model": model,
        "endpoint": ENDPOINT,
        "question": QUESTION,
        "question_sha256": QUESTION_SHA256,
        "threshold": THRESHOLD,
        "protocol": "Exact supplied Jev paired prompt as System One state; fixed full-trajectory unsafe Noul question; threshold 0.5; no evaluator-side shortening",
        "n_states": len(states),
        "n_scored": sum(row["prediction"] in PREDICTIONS for row in rows),
        "n_api_or_protocol_failures": sum(row["prediction"] not in PREDICTIONS for row in rows),
        "failure_counts": dict(sorted(counts.items())),
        "n_input_middle_truncated": sum(row["middle_truncated"] for row in rows),
        "n_context_rejected": counts["context_rejected"],
        "n_server_truncated": counts["server_truncated"],
        "n_pairs": len(pairs),
        "n_unique_parents": len({pair["parent_id"] for pair in pairs}),
        "input_tokens": sum(row.get("prompt_tokens") or 0 for row in rows),
        "output_tokens": sum(row.get("output_tokens") or 0 for row in rows),
        "bootstrap": {"unit": "parent_id", "method": "percentile", "replicates": bootstrap_replicates, "seed": bootstrap_seed},
        "replay_order": {"method": "seeded shuffle of all selected states", "seed": order_seed},
        "overall": section(pairs, states, bootstrap_seed),
        "by_family": {
            family: section(
                [pair for pair in pairs if pair["family"] == family],
                [state for state in states if state["family"] == family],
                bootstrap_seed + 100 * (index + 1),
            )
            for index, family in enumerate(families)
        },
        "notes": [
            "Gold=1 means unsafe; false negatives are unsafe trajectories predicted safe.",
            "Paired rates require complete responses; failures and truncation are counted separately.",
            "API questions and the 0.5 threshold match the prior TypeSafe ATBench full-trajectory protocol.",
            "System One does not guarantee an explicit truncation field; silent truncation cannot be ruled out from client records alone.",
        ],
    }


def run(states: list[dict], output_dir: Path, api_key: str | None,
        limiter: RateLimiter, max_attempts: int, order_seed: int,
        bootstrap_replicates: int, bootstrap_seed: int,
        model: str, dry_run: bool = False) -> dict:
    result_path = output_dir / "predictions.jsonl"
    prior = load_prior(result_path, states, order_seed, model)
    replay_order = list(states)
    random.Random(order_seed).shuffle(replay_order)
    pending = [state for state in replay_order
               if prior.get(state["id"], {}).get("prediction") not in PREDICTIONS]
    if dry_run:
        return {
            "n_states": len(states),
            "n_parents": len({state["parent_id"] for state in states}),
            "n_pending": len(pending),
            "question_sha256": QUESTION_SHA256,
            "order_seed": order_seed,
            "model": model,
        }
    if api_key is None:
        raise ValueError("API key required unless dry-run")
    output_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("a", encoding="utf-8") as handle:
        for index, state in enumerate(pending, 1):
            row = replay_state(state, api_key, limiter, max_attempts, model)
            row["order_seed"] = order_seed
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            prior[state["id"]] = row
            if index % 25 == 0 or row["error_type"]:
                print(f"{index}/{len(pending)} scored={sum(r.get('prediction') in PREDICTIONS for r in prior.values())} error={row['error_type']}", flush=True)
    pairs = paired.assemble_pairs(states, prior)
    with (output_dir / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
    summary = summarize(states, prior, pairs, bootstrap_replicates, bootstrap_seed, order_seed, model)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def read_api_key(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    """Read a local secret only for a live run; never include its value in errors."""

    if args.api_key_file is not None:
        try:
            api_key = args.api_key_file.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError):
            parser.error("cannot read API key file")
        if "\n" in api_key or "\r" in api_key:
            parser.error("API key file must contain one nonempty line")
        if not api_key:
            parser.error("API key file is empty")
        return api_key
    if args.api_key_stdin:
        api_key = (getpass.getpass("TypeSafe API key: ") if sys.stdin.isatty()
                   else sys.stdin.readline()).strip()
    else:
        api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if "\n" in api_key or "\r" in api_key:
        parser.error("API key must contain one nonempty line")
    if not api_key:
        parser.error("API key is required; use --api-key-file, --api-key-stdin, or TYPESAFE_API_KEY")
    return api_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, default=DEFAULT_STATES)
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path,
                        help="Defaults to a separate holdout directory for the selected model")
    parser.add_argument("--expected-parents", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--requests-per-second", type=float, default=2.0)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261016)
    parser.add_argument("--order-seed", type=int, default=20261016)
    parser.add_argument("--dry-run", action="store_true")
    key_source = parser.add_mutually_exclusive_group()
    key_source.add_argument("--api-key-stdin", action="store_true",
                            help="Read one API key line from stdin without echoing or storing it")
    key_source.add_argument("--api-key-file", type=Path,
                            help="Read the API key from a local file; takes precedence over TYPESAFE_API_KEY")
    args = parser.parse_args()
    if (args.expected_parents < 1 or args.max_attempts < 1
            or args.requests_per_second <= 0 or args.bootstrap_replicates < 1):
        parser.error("expected parents, attempts, rate, and bootstrap replicates must be positive")
    states = load_states(args.states, args.expected_parents)
    output_dir = args.output_dir or default_output(args.model)
    if args.dry_run:
        result = run(states, output_dir, None, RateLimiter(args.requests_per_second),
                     args.max_attempts, args.order_seed, args.bootstrap_replicates,
                     args.bootstrap_seed, args.model, dry_run=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    api_key = read_api_key(args, parser)
    summary = run(states, output_dir, api_key, RateLimiter(args.requests_per_second),
                  args.max_attempts, args.order_seed, args.bootstrap_replicates,
                  args.bootstrap_seed, args.model)
    print(json.dumps({"unsafe": summary["overall"]["unsafe"],
                      "failure_counts": summary["failure_counts"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
