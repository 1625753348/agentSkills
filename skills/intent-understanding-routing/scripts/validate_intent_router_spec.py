#!/usr/bin/env python3
"""Validate the structure and safety assumptions of an intent-routing spec."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "schema_version",
    "router_library",
    "scope",
    "routes",
    "fallback",
    "calibration",
    "evaluation",
    "execution",
}
RISK_LEVELS = {"low", "medium", "high", "critical"}
VALID_ROUTER_TYPES = {"indexed", "decision", "chain", "merge"}


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(data: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings

    missing = sorted(REQUIRED_TOP_LEVEL - data.keys())
    if missing:
        add_error(errors, f"missing top-level fields: {', '.join(missing)}")

    router_library = data.get("router_library")
    if not isinstance(router_library, dict):
        add_error(errors, "router_library must be an object")
        router_library = {}

    router_type = router_library.get("router_type")
    if router_type not in VALID_ROUTER_TYPES:
        add_error(
            errors,
            f"router_library.router_type must be one of {sorted(VALID_ROUTER_TYPES)}",
        )

    constraint = str(router_library.get("constraint", ""))
    if ">=1" not in constraint:
        add_warning(
            warnings,
            "router_library.constraint should explicitly target Semantic Router 1.x",
        )

    scope = data.get("scope")
    if not isinstance(scope, dict):
        add_error(errors, "scope must be an object")
        scope = {}
    for field in ("domains", "languages", "channels"):
        value = scope.get(field)
        if not isinstance(value, list) or not value:
            add_error(errors, f"scope.{field} must be a non-empty list")

    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        add_error(errors, "routes must be a non-empty list")
        routes = []

    route_names: set[str] = set()
    for index, route in enumerate(routes):
        prefix = f"routes[{index}]"
        if not isinstance(route, dict):
            add_error(errors, f"{prefix} must be an object")
            continue

        name = route.get("name")
        if not isinstance(name, str) or not name.strip():
            add_error(errors, f"{prefix}.name must be a non-empty string")
        elif name in route_names:
            add_error(errors, f"duplicate route name: {name}")
        else:
            route_names.add(name)

        handler = route.get("handler")
        if not isinstance(handler, str) or not handler.strip():
            add_error(errors, f"{prefix}.handler must be a non-empty string")

        risk_level = route.get("risk_level")
        if risk_level not in RISK_LEVELS:
            add_error(
                errors,
                f"{prefix}.risk_level must be one of {sorted(RISK_LEVELS)}",
            )

        utterances = route.get("utterances")
        description = route.get("description")
        if router_type == "indexed":
            if not isinstance(utterances, list) or not utterances:
                add_error(
                    errors,
                    f"{prefix}.utterances must be non-empty for IndexedRouter",
                )
            elif len(utterances) < 5:
                add_warning(
                    warnings,
                    f"{prefix}.utterances has fewer than 5 examples",
                )
            if description and (not isinstance(utterances, list) or not utterances):
                add_error(
                    errors,
                    f"{prefix} has a description but no utterances; "
                    "IndexedRouter does not embed descriptions",
                )
        elif router_type == "decision":
            if not isinstance(description, str) or not description.strip():
                add_error(
                    errors,
                    f"{prefix}.description is required for DecisionRouter",
                )

        threshold = route.get("confidence_threshold")
        if threshold is None:
            add_warning(warnings, f"{prefix} has no route-level threshold")
        elif not is_number(threshold) or not 0 <= float(threshold) <= 1:
            add_error(
                errors,
                f"{prefix}.confidence_threshold must be a number from 0 to 1",
            )

        if risk_level in {"high", "critical"} and route.get("requires_confirmation") is not True:
            add_error(
                errors,
                f"{prefix} is {risk_level} risk and must require confirmation",
            )

        if name in {"chitchat", "smalltalk", "small_talk"}:
            add_warning(
                warnings,
                f"{prefix} uses a chitchat route; prefer a risk-gated fallback unless "
                "the route is intentionally measured and maintained",
            )

    fallback = data.get("fallback")
    if not isinstance(fallback, dict):
        add_error(errors, "fallback must be an object")
        fallback = {}
    for field in ("business_miss_policy", "chitchat_handler", "clarification_handler"):
        if not isinstance(fallback.get(field), str) or not fallback.get(field).strip():
            add_error(errors, f"fallback.{field} must be a non-empty string")
    risk_gate = fallback.get("risk_gate")
    if not isinstance(risk_gate, list) or not risk_gate:
        add_error(errors, "fallback.risk_gate must be a non-empty list")
    if fallback.get("cheap_model_tool_access") is not False:
        add_error(
            errors,
            "fallback.cheap_model_tool_access must be false so the chitchat path "
            "cannot call business tools",
        )
    if fallback.get("business_miss_policy") != "risk_gated":
        add_warning(
            warnings,
            "fallback.business_miss_policy is not risk_gated; verify that unmatched "
            "business-like requests cannot fall directly into chitchat",
        )

    calibration = data.get("calibration")
    if not isinstance(calibration, dict):
        add_error(errors, "calibration must be an object")
        calibration = {}
    if calibration.get("method") not in {"platt", "isotonic", None}:
        add_error(errors, "calibration.method should be platt or isotonic")
    if calibration.get("uses_held_out_queries") is not True:
        add_error(errors, "calibration.uses_held_out_queries must be true")
    null_examples = calibration.get("null_examples")
    if not isinstance(null_examples, int) or null_examples < 1:
        add_error(errors, "calibration.null_examples must be a positive integer")
    if calibration.get("thresholds_selected_from_held_out_data") is not True:
        add_warning(
            warnings,
            "calibration.thresholds_selected_from_held_out_data should be true",
        )

    evaluation = data.get("evaluation")
    if not isinstance(evaluation, dict):
        add_error(errors, "evaluation must be an object")
        evaluation = {}
    slices = evaluation.get("slices")
    if not isinstance(slices, list) or not slices:
        add_error(errors, "evaluation.slices must be a non-empty list")
    else:
        required_slices = {
            "hard_negative",
            "none_or_chitchat",
            "ambiguous",
            "multi_intent",
            "context_switch",
            "safety",
        }
        missing_slices = required_slices - set(map(str, slices))
        if missing_slices:
            add_warning(
                warnings,
                f"evaluation.slices is missing recommended slices: {sorted(missing_slices)}",
            )
    metrics = evaluation.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        add_error(errors, "evaluation.metrics must be a non-empty list")

    execution = data.get("execution")
    if not isinstance(execution, dict):
        add_error(errors, "execution must be an object")
        execution = {}
    for field in ("policy_engine_separate", "tool_gateway_validation", "audit_trace_required"):
        if execution.get(field) is not True:
            add_error(errors, f"execution.{field} must be true")
    max_actions = execution.get("max_actions_per_request")
    if not isinstance(max_actions, int) or max_actions < 1:
        add_error(errors, "execution.max_actions_per_request must be a positive integer")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an intent-routing JSON specification."
    )
    parser.add_argument("spec", type=Path, help="Path to the JSON specification")
    args = parser.parse_args()

    try:
        data = json.loads(args.spec.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.spec}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate(data)
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}", file=sys.stderr)

    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"OK: {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
