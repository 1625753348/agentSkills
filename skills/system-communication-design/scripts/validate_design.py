#!/usr/bin/env python3
"""Validate the machine-readable communication design specification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXTERNAL_TYPES = {"http", "sse", "websocket", "webhook", "grpc"}
INTERNAL_TYPES = {"in_process_event_bus", "queue", "durable_stream", "database_queue"}
DIRECTIONS = {
    "client_to_server",
    "server_to_client",
    "bidirectional",
    "request_response",
    "server_to_server",
}
DELIVERY = {"at_least_once", "at_most_once", "effectively_once"}
PLACEHOLDERS = ("TODO", "TBD", "FIXME")


class Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def mapping(self, value: Any, path: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error(path, "must be an object")
            return None
        return value

    def sequence(self, value: Any, path: str) -> list[Any] | None:
        if not isinstance(value, list) or not value:
            self.error(path, "must be a non-empty array")
            return None
        return value

    def text(self, value: Any, path: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self.error(path, "must be a non-empty string")
            return None
        if any(token in value.upper() for token in PLACEHOLDERS):
            self.error(path, "contains an unresolved placeholder")
        return value

    def positive_number(self, value: Any, path: str) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            self.error(path, "must be a positive number")
            return None
        return value

    def required(self, obj: dict[str, Any], key: str, path: str) -> Any:
        if key not in obj:
            self.error(f"{path}.{key}", "is required")
            return None
        return obj[key]

    def required_text(self, obj: dict[str, Any], key: str, path: str) -> str | None:
        value = self.required(obj, key, path)
        return self.text(value, f"{path}.{key}") if value is not None else None

    def required_mapping(self, obj: dict[str, Any], key: str, path: str) -> dict[str, Any] | None:
        value = self.required(obj, key, path)
        return self.mapping(value, f"{path}.{key}") if value is not None else None

    def required_sequence(self, obj: dict[str, Any], key: str, path: str) -> list[Any] | None:
        value = self.required(obj, key, path)
        return self.sequence(value, f"{path}.{key}") if value is not None else None

    def validate_retry(self, reliability: dict[str, Any], path: str, *, max_attempts: bool) -> None:
        retry = self.required_mapping(reliability, "retry", path)
        if retry is None:
            return
        if max_attempts:
            self.positive_number(self.required(retry, "max_attempts", f"{path}.retry"), f"{path}.retry.max_attempts")
        else:
            strategy = self.required_text(retry, "strategy", f"{path}.retry")
            if strategy and "jitter" not in strategy.lower():
                self.error(f"{path}.retry.strategy", "must describe jitter for a stream retry policy")
        base = self.positive_number(self.required(retry, "base_ms", f"{path}.retry"), f"{path}.retry.base_ms")
        cap = self.positive_number(self.required(retry, "cap_ms", f"{path}.retry"), f"{path}.retry.cap_ms")
        if base is not None and cap is not None and base > cap:
            self.error(f"{path}.retry", "base_ms must not exceed cap_ms")

    def validate_buffer(self, buffer: Any, path: str, *, client: bool) -> None:
        obj = self.mapping(buffer, path)
        if obj is None:
            return
        self.positive_number(self.required(obj, "max_events", path), f"{path}.max_events")
        if client:
            self.positive_number(self.required(obj, "max_bytes", path), f"{path}.max_bytes")
        else:
            high = self.required(obj, "high_watermark_pct", path)
            low = self.required(obj, "low_watermark_pct", path)
            high_num = self.positive_number(high, f"{path}.high_watermark_pct")
            low_num = self.positive_number(low, f"{path}.low_watermark_pct")
            if high_num is not None and low_num is not None and not low_num < high_num <= 100:
                self.error(path, "watermarks must satisfy 0 < low < high <= 100")
        self.required_text(obj, "overflow_policy", path)

    def validate_sse(self, reliability: dict[str, Any], path: str) -> None:
        self.validate_retry(reliability, path, max_attempts=False)
        resume = self.required_mapping(reliability, "resume", path)
        if resume is not None:
            self.required_text(resume, "cursor_header", f"{path}.resume")
            if self.required(resume, "durable_replay", f"{path}.resume") is not True:
                self.error(f"{path}.resume.durable_replay", "must be true for recoverable SSE")
        heartbeat = self.positive_number(
            self.required(reliability, "heartbeat_ms", path), f"{path}.heartbeat_ms"
        )
        idle = self.positive_number(
            self.required(reliability, "idle_timeout_ms", path), f"{path}.idle_timeout_ms"
        )
        if heartbeat is not None and idle is not None and idle <= heartbeat:
            self.error(path, "idle_timeout_ms must be greater than heartbeat_ms")
        self.validate_buffer(
            self.required(reliability, "server_buffer", path),
            f"{path}.server_buffer",
            client=False,
        )
        self.validate_buffer(
            self.required(reliability, "client_buffer", path),
            f"{path}.client_buffer",
            client=True,
        )

    def validate_external(self, items: list[Any]) -> None:
        for index, raw in enumerate(items):
            path = f"external_channels[{index}]"
            channel = self.mapping(raw, path)
            if channel is None:
                continue
            self.required_text(channel, "name", path)
            channel_type = self.required_text(channel, "type", path)
            if channel_type and channel_type not in EXTERNAL_TYPES:
                self.error(f"{path}.type", f"unknown type; expected one of {sorted(EXTERNAL_TYPES)}")
            self.required_text(channel, "endpoint", path)
            direction = self.required_text(channel, "direction", path)
            if direction and direction not in DIRECTIONS:
                self.error(f"{path}.direction", f"unknown direction; expected one of {sorted(DIRECTIONS)}")
            self.required_text(channel, "auth", path)
            reliability = self.required_mapping(channel, "reliability", path)
            if reliability is None:
                continue
            if channel_type == "sse":
                self.validate_sse(reliability, f"{path}.reliability")
            elif channel_type == "websocket":
                self.required_text(reliability, "reconnect", f"{path}.reliability")
                self.required_text(reliability, "message_ack", f"{path}.reliability")
                self.required_text(reliability, "auth_expiry", f"{path}.reliability")
                self.positive_number(
                    self.required(reliability, "heartbeat_ms", f"{path}.reliability"),
                    f"{path}.reliability.heartbeat_ms",
                )
            elif channel_type == "webhook":
                self.required_text(reliability, "signature", f"{path}.reliability")
                self.positive_number(
                    self.required(reliability, "replay_window_seconds", f"{path}.reliability"),
                    f"{path}.reliability.replay_window_seconds",
                )
                self.required_text(reliability, "idempotency", f"{path}.reliability")
            elif channel_type == "grpc":
                self.positive_number(
                    self.required(reliability, "deadline_ms", f"{path}.reliability"),
                    f"{path}.reliability.deadline_ms",
                )
            elif channel_type == "http":
                self.positive_number(
                    self.required(reliability, "timeout_ms", f"{path}.reliability"),
                    f"{path}.reliability.timeout_ms",
                )
                self.required_text(reliability, "idempotency", f"{path}.reliability")

    def validate_internal(self, items: list[Any]) -> None:
        for index, raw in enumerate(items):
            path = f"internal_channels[{index}]"
            channel = self.mapping(raw, path)
            if channel is None:
                continue
            self.required_text(channel, "name", path)
            channel_type = self.required_text(channel, "type", path)
            if channel_type and channel_type not in INTERNAL_TYPES:
                self.error(f"{path}.type", f"unknown type; expected one of {sorted(INTERNAL_TYPES)}")
            self.required_sequence(channel, "topics", path)
            self.required_text(channel, "auth", path)
            reliability = self.required_mapping(channel, "reliability", path)
            if reliability is None:
                continue
            if channel_type == "in_process_event_bus":
                self.required_text(reliability, "durability", f"{path}.reliability")
                self.required_text(reliability, "failure_mode", f"{path}.reliability")
                continue
            delivery = self.required_text(reliability, "delivery", f"{path}.reliability")
            if delivery and delivery not in DELIVERY:
                self.error(f"{path}.reliability.delivery", f"unknown delivery; expected one of {sorted(DELIVERY)}")
            self.required_text(reliability, "ordering", f"{path}.reliability")
            self.required_text(reliability, "idempotency", f"{path}.reliability")
            self.validate_retry(reliability, f"{path}.reliability", max_attempts=True)
            self.required_text(reliability, "dlq", f"{path}.reliability")
            if "outbox" not in reliability or not isinstance(reliability["outbox"], bool):
                self.error(f"{path}.reliability.outbox", "must be a boolean")
            replay = self.required(reliability, "replay", f"{path}.reliability")
            if not isinstance(replay, bool):
                self.error(f"{path}.reliability.replay", "must be a boolean")
            if channel_type == "durable_stream" and replay is not True:
                self.error(f"{path}.reliability.replay", "durable_stream must support replay")

    def validate_security(self, security: dict[str, Any]) -> None:
        required = (
            "user_authentication",
            "service_authentication",
            "authorization",
            "transport",
            "token_lifecycle",
            "stream_authentication",
            "origin_policy",
            "secrets",
            "audit",
        )
        for key in required:
            self.required_text(security, key, "security")

    def validate(self, document: Any) -> list[str]:
        root = self.mapping(document, "$")
        if root is None:
            return self.errors
        self.required_text(root, "version", "$")
        system = self.required_mapping(root, "system", "$")
        if system is not None:
            self.required_text(system, "name", "system")
            self.required_sequence(system, "actors", "system")
            self.required_mapping(system, "constraints", "system")

        paths = self.required_sequence(root, "interaction_paths", "$")
        if paths is not None:
            for index, raw in enumerate(paths):
                path = f"interaction_paths[{index}]"
                item = self.mapping(raw, path)
                if item is None:
                    continue
                for key in ("id", "kind", "protocol", "auth", "reliability"):
                    self.required_text(item, key, path)
                self.positive_number(
                    self.required(item, "latency_budget_ms", path),
                    f"{path}.latency_budget_ms",
                )

        external = self.required_sequence(root, "external_channels", "$")
        if external is not None:
            self.validate_external(external)
        internal = self.required_sequence(root, "internal_channels", "$")
        if internal is not None:
            self.validate_internal(internal)

        contracts = self.required_mapping(root, "contracts", "$")
        if contracts is not None:
            for key in ("envelope", "schema", "compatibility"):
                self.required_text(contracts, key, "contracts")
            fields = self.required_sequence(contracts, "required_fields", "contracts")
            if fields is not None:
                normalized = {str(value).lower() for value in fields if isinstance(value, str)}
                for required_field in ("specversion", "id", "source", "type"):
                    if required_field not in normalized:
                        self.error("contracts.required_fields", f"must include {required_field}")

        security = self.required_mapping(root, "security", "$")
        if security is not None:
            self.validate_security(security)

        implementation = self.required_mapping(root, "implementation", "$")
        if implementation is not None:
            phases = self.required_sequence(implementation, "phases", "implementation")
            if phases is not None:
                for index, raw in enumerate(phases):
                    path = f"implementation.phases[{index}]"
                    item = self.mapping(raw, path)
                    if item is None:
                        continue
                    for key in ("id", "name", "exit_gate"):
                        self.required_text(item, key, path)
            self.required_sequence(implementation, "observability", "implementation")
            self.required_sequence(implementation, "tests", "implementation")

        decisions = self.required_sequence(root, "decisions", "$")
        if decisions is not None:
            for index, raw in enumerate(decisions):
                path = f"decisions[{index}]"
                item = self.mapping(raw, path)
                if item is None:
                    continue
                self.required_text(item, "decision", path)
                self.required_text(item, "selected", path)
                self.required_sequence(item, "alternatives", path)
                self.required_text(item, "rationale", path)
        return self.errors


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a communication-design JSON specification."
    )
    parser.add_argument("spec", type=Path, help="Path to communication design JSON")
    args = parser.parse_args()

    try:
        document = load_json(args.spec)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    checker = Checker()
    errors = checker.validate(document)
    if errors:
        print(f"INVALID: {len(errors)} issue(s) in {args.spec}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    external_count = len(document.get("external_channels", []))
    internal_count = len(document.get("internal_channels", []))
    decision_count = len(document.get("decisions", []))
    print(
        f"OK: {args.spec} "
        f"({external_count} external, {internal_count} internal, {decision_count} decisions)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

