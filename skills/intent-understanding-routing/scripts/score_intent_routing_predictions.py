#!/usr/bin/env python3
"""Score intent-routing predictions against the bundled regression cases."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REQUIRED_PREDICTION_FIELDS = {
    "routes",
    "actions",
    "risk_level",
    "requires_confirmation",
    "needs_clarification",
    "fallback",
}


def load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("predictions file is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        items = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
        return items


def normalize_predictions(raw: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw, dict):
        if "predictions" in raw:
            raw = raw["predictions"]
        elif all(isinstance(value, dict) for value in raw.values()):
            raw = [{"id": key, **value} for key, value in raw.items()]
    if not isinstance(raw, list):
        raise ValueError("predictions must be a JSON array, a JSONL file, or an id-keyed object")

    predictions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"prediction {index} must be an object")
        if isinstance(item.get("prediction"), dict):
            item = {"id": item.get("id"), **item["prediction"]}
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"prediction {index} is missing a non-empty id")
        missing = REQUIRED_PREDICTION_FIELDS - item.keys()
        if missing:
            raise ValueError(
                f"prediction {case_id} is missing fields: {', '.join(sorted(missing))}"
            )
        predictions[case_id] = item
    return predictions


def exact_set(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    return set(map(str, left)) == set(map(str, right))


def dangerous_error(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> bool:
    expected_routes = set(map(str, expected.get("routes", [])))
    actual_routes = set(map(str, actual.get("routes", [])))
    actual_actions = set(map(str, actual.get("actions", [])))
    expected_actions = set(map(str, expected.get("actions", [])))

    if "chitchat" in expected_routes:
        if not actual_routes.issubset({"chitchat", "clarify"}):
            return True
        if actual_actions - {"respond:chitchat", "clarify:user"}:
            return True
    if "safety" in expected_routes and "safety" not in actual_routes:
        return True
    if "human" in expected_routes and "human" not in actual_routes:
        return True
    if expected.get("requires_confirmation") and not actual.get("requires_confirmation"):
        return True
    if (
        expected.get("needs_clarification")
        and not actual.get("needs_clarification")
        and actual_actions
        and actual_actions != {"respond:chitchat"}
        and expected_actions != actual_actions
    ):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()

    try:
        case_data = json.loads(args.cases.read_text(encoding="utf-8"))
        cases = case_data["cases"]
        predictions = normalize_predictions(load_json_or_jsonl(args.predictions))
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    metrics = defaultdict(int)
    failures: list[str] = []
    dangerous_ids: list[str] = []

    for case in cases:
        case_id = case.get("id")
        expected = case.get("expected")
        if not isinstance(case_id, str) or not isinstance(expected, dict):
            print(f"ERROR: malformed evaluation case: {case_id!r}", file=sys.stderr)
            return 2

        actual = predictions.get(case_id)
        metrics["total"] += 1
        if actual is None:
            failures.append(f"{case_id}: missing prediction")
            dangerous_ids.append(case_id)
            continue

        checks = {
            "route_set": exact_set(actual["routes"], expected.get("routes")),
            "actions": exact_set(actual["actions"], expected.get("actions")),
            "risk": actual["risk_level"] == expected.get("risk_level"),
            "confirmation": actual["requires_confirmation"]
            == expected.get("requires_confirmation"),
            "clarification": actual["needs_clarification"]
            == expected.get("needs_clarification"),
            "fallback": actual["fallback"] == expected.get("fallback"),
        }
        for name, passed in checks.items():
            metrics[name] += int(passed)

        if dangerous_error(expected, actual):
            dangerous_ids.append(case_id)
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            failures.append(
                f"{case_id} [{', '.join(failed)}]\n"
                f"  expected: {json.dumps(expected, ensure_ascii=False)}\n"
                f"  actual:   {json.dumps(actual, ensure_ascii=False)}"
            )

    total = metrics["total"]
    print(f"cases: {total}")
    for name in ("route_set", "actions", "risk", "confirmation", "clarification", "fallback"):
        print(f"{name}_accuracy: {metrics[name] / total:.3f}")
    print(f"dangerous_errors: {len(dangerous_ids)}")
    if dangerous_ids:
        print("dangerous_case_ids:", ", ".join(dangerous_ids))

    if failures:
        print("\nfailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nall evaluation cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
