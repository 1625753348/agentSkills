# Event Contracts

## Envelope

Use CloudEvents 1.0 where possible. Keep transport metadata out of the domain payload.

```json
{
  "specversion": "1.0",
  "id": "evt_01J8Z6J8G1K2V4B7Q9R3",
  "source": "agent-orchestrator",
  "type": "agent.run.completed",
  "subject": "runs/r_123",
  "time": "2026-11-10T03:20:00.125Z",
  "datacontenttype": "application/json",
  "dataschema": "https://schemas.example.com/agent/run-completed/1.2",
  "tenantid": "t_9",
  "runid": "r_123",
  "correlationid": "corr_42",
  "causationid": "evt_01J8Z5...",
  "sequence": 18,
  "idempotencykey": "tool-call-7:result:1",
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "data": {
    "status": "succeeded",
    "output_ref": "object://runs/r_123/output?version=3"
  }
}
```

CloudEvents extension attributes are lowercase. Keep extension names stable and document them. If an existing organization envelope is used, map each field explicitly to the CloudEvents equivalent instead of creating ambiguous duplicates.

Recommended common fields:

| Field | Purpose |
|---|---|
| `id` | Globally unique event identity for deduplication |
| `source` | Producer identity |
| `type` | Stable fact name |
| `subject` | Resource/aggregate affected |
| `time` | Event creation time, not delivery or business effective time |
| `dataschema` | Versioned schema identity |
| `tenantid` | Isolation and authorization scope |
| `runid`, `taskid`, `turnid` | Domain correlation |
| `correlationid` | One user/business workflow |
| `causationid` | Event or command that caused this event |
| `sequence` | Per-stream ordering where required |
| `idempotencykey` | Side-effect deduplication |
| `traceparent` | W3C trace propagation |
| `attempt` | Delivery/processing attempt when applicable |
| `deadline` | Expiry for time-bounded work |

Do not use `time` as the sole ordering mechanism. Clocks drift. Use a per-aggregate sequence or broker partition order where ordering is required.

## Event Naming

Use past-tense facts for events:

- `user.message.created`
- `agent.run.requested`
- `agent.run.started`
- `agent.turn.delta`
- `tool.call.requested`
- `tool.call.completed`
- `agent.approval.required`
- `agent.run.completed`
- `agent.run.failed`
- `agent.run.cancelled`

Use imperative commands for requests:

- `run.start`
- `run.cancel`
- `approval.submit`

Do not mix command and event semantics in one topic if consumers need different authorization or retry behavior.

## UI Stream Events

SSE or WebSocket frames should be small, typed, and ordered per run:

| Event | Payload essentials | Recovery behavior |
|---|---|---|
| `snapshot` | run status, sequence, last cursor, authoritative visible state | Replace transient client state |
| `turn.started` | `run_id`, `turn_id`, sequence | Upsert turn |
| `token.delta` | turn, sequence, text fragment | Coalesce/render; never treat as durable final text |
| `tool.progress` | call ID, phase, safe summary, percent | Latest-value merge |
| `approval.required` | approval ID, action summary, expiry | Persist and require explicit user action |
| `run.completed` | final output/ref, usage summary, sequence | Mark terminal, fetch final object if needed |
| `run.failed` | stable error code, retryable flag, safe message | Mark terminal or offer explicit retry |
| `run.cancelled` | cancel reason, sequence | Mark terminal |
| `reset` | reason, snapshot cursor/URL | Discard unsafe transient state and resync |

`token.delta` is an optimization for rendering. Persist the final message/result separately. If a delta is lost, the client recovers through snapshot/final state rather than reconstructing from heartbeat counts.

## SSE Wire Format

The SSE `id` must match the event's resumable cursor. The `event` field selects the client handler.

```text
id: cur_01J8Z6K3
event: token.delta
data: {"run_id":"r_123","turn_id":"t_1","sequence":41,"text":"Hel"}

id: cur_01J8Z6K4
event: tool.progress
data: {"run_id":"r_123","tool_call_id":"tc_7","phase":"running","percent":35}

id: cur_01J8Z6K5
event: run.completed
data: {"run_id":"r_123","sequence":42,"output_ref":"object://runs/r_123/final"}

```

For multi-line JSON, split data into multiple `data:` lines; do not embed raw untrusted newlines without escaping. Keep event payloads JSON so schema validation and tracing work consistently.

## Errors

Use stable machine-readable codes:

```json
{
  "code": "RUN_DEADLINE_EXCEEDED",
  "category": "timeout",
  "retryable": false,
  "message": "The run exceeded its deadline.",
  "correlation_id": "corr_42",
  "details_ref": "support://error/evt_01J8Z6K5"
}
```

Do not expose stack traces, credentials, internal hostnames, or unrestricted model/tool diagnostics. Separate user-safe messages from operator diagnostics.

## Idempotency

Assign an idempotency key to every externally retryable command and internally redeliverable side effect.

Examples:

- Client create-run command: user-scoped `Idempotency-Key` header, retained at least as long as client retry possibility.
- Approval: `approval_id` plus actor/decision; duplicate submit returns prior result.
- Tool execution: `run_id:tool_call_id:attempt-group`.
- Webhook: provider event ID plus signature verification.

Persist key, request fingerprint, result, and expiry. Reject reuse of the same key with a different payload.

## Ordering and Deduplication

- Define the ordering key, usually `tenant_id:run_id` or `run_id`.
- Emit monotonically increasing sequence per ordering key.
- Consumers reject stale transitions or route them to a reconciliation path.
- Deduplicate by event ID before side effects; keep the dedupe window longer than the maximum replay and redelivery period.
- Do not claim global order from a stream unless the broker configuration guarantees one partition for the whole domain, which usually harms scale.

## Schema and Compatibility

Rules:

- Add optional fields in a backward-compatible minor version.
- Never repurpose an existing field or change its type/meaning.
- Removing or making a field mandatory requires a new major schema version and migration plan.
- Consumers must ignore unknown optional fields.
- Validate on ingress and before publishing.
- Keep examples and schemas in version control with an owner.
- Test old and new producer/consumer combinations during rollout.

Use AsyncAPI 3.x to describe channels, operations, messages, bindings, and security schemes for asynchronous interfaces. Use JSON Schema for payload validation. Use CloudEvents for the envelope rather than inventing another incompatible one.

## Contract Review

- [ ] Fact vs command is unambiguous.
- [ ] Event ID and idempotency key semantics are defined.
- [ ] Sequence/order and dedupe behavior are defined.
- [ ] Timeout, deadline, retryability, and terminal states are defined.
- [ ] Tenant and authorization scope are present.
- [ ] Payload has schema, examples, compatibility rules, and owner.
- [ ] Sensitive data and object references have access controls.
- [ ] Trace/correlation IDs cross every boundary.
- [ ] DLQ and replay preserve enough context for safe recovery.

