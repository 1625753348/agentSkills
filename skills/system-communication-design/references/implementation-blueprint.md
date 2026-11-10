# Implementation Blueprint

## Reference Topology

```text
Browser / Mobile / Partner
        |
        | HTTPS commands, snapshots, cancellation
        | SSE or WebSocket event delivery
        v
API Gateway + BFF / Edge Auth
        |
        +--> Run API ----+
        |                |
        +--> Stream API  |  durable run state + outbox + event store/replay
                         |
                         v
                  Event Broker / Durable Log
                         |
          +--------------+---------------+
          |              |               |
     Orchestrator     Tool Worker     Notification Worker
          |
          +--> Model / Tool adapters with deadlines and cancellation
```

Key boundaries:

- The run API owns admission, idempotency, and the initial transaction.
- The orchestrator owns run state transitions; it is the single logical writer for a run.
- Workers execute bounded tasks and publish immutable results.
- The event store owns replay cursors; the stream API owns fan-out and slow-client policy.
- The broker decouples durable facts. High-rate token deltas may use a transient fan-out path plus durable checkpoints.

## External API Shape

```http
POST /v1/runs
Idempotency-Key: <caller-key>
Authorization: Bearer <token>

202 Accepted
{"run_id":"r_123","status":"queued","stream_url":"/v1/runs/r_123/events"}
```

```http
GET /v1/runs/{run_id}
GET /v1/runs/{run_id}/snapshot
POST /v1/runs/{run_id}/cancel
POST /v1/runs/{run_id}/input
POST /v1/runs/{run_id}/approvals/{approval_id}
```

Optional stream:

```http
GET /v1/runs/{run_id}/events
Last-Event-ID: <opaque-cursor>
Accept: text/event-stream
```

Optional duplex control:

```text
WSS /v1/runs/{run_id}/control
```

Do not make the UI depend on a socket remaining alive to know the run's terminal state. `GET /runs/{id}` and the authoritative result store remain the source of truth.

## Run State Machine

```text
queued -> running -> waiting_approval -> running -> completed
   |        |              |              |
   +--------+--------------+--------------+-> failed
   +--------+--------------+--------------+-> cancelling -> cancelled
```

Rules:

- Transitions are persisted with optimistic versioning or a compare-and-set condition.
- Each transition emits one event with a stable ID and sequence.
- Repeating the same transition is idempotent and does not emit a duplicate business effect.
- A late result for a cancelled run is recorded as diagnostic evidence but does not silently revive the run.
- Approval is valid only for a matching pending approval and unexpired deadline.

## Minimal Data Model

| Table/collection | Purpose |
|---|---|
| `agent_run` | Current run state, version, owner, tenant, deadline |
| `run_task` | Task graph, status, attempts, lease, idempotency key |
| `run_event` | Replayable event projection with cursor and retention |
| `run_snapshot` | Last authoritative visible state and cursor |
| `outbox_event` | Transactional publication queue |
| `inbox_consumed` | Consumer dedupe/result record |
| `approval_request` | Pending approval, action scope, expiry, decision |
| `idempotency_record` | External request key, fingerprint, response |

Index authorization scopes and retention fields. Partition high-volume event tables or streams by tenant/run according to measured load.

## Internal Topics

Durable facts:

- `agent.run.requested`
- `agent.run.started`
- `agent.run.completed`
- `agent.run.failed`
- `agent.run.cancelled`
- `agent.approval.required`
- `agent.approval.resolved`
- `tool.call.completed`

High-rate transient output:

- `agent.turn.delta` or an equivalent fan-out channel
- `agent.tool.progress`

For each topic define owner, partition key, retention, schema, max payload, delivery semantics, retry, and DLQ. For deltas, coalesce before fan-out where possible. Persist checkpoints and final output; do not rely on every token delta being replayed.

## SSE Server Pseudocode

```text
handle_stream(run_id, last_event_id, principal):
  authorize(principal, "stream:subscribe", run_id)
  set headers: text/event-stream, no-cache/no-transform, proxy buffering disabled
  acquire per-principal and per-run stream limits
  cursor = validate_cursor(last_event_id)

  if cursor is expired or invalid:
    snapshot = load_authorized_snapshot(run_id)
    emit "reset" with snapshot cursor
    cursor = snapshot.cursor
  else:
    bounded_replay(run_id, cursor)

  register_connection(run_id, cursor, bounded_queue)
  while connection is authorized and run is not terminal:
    event = next_event_or_heartbeat()
    if queue high:
      coalesce_deltas_or_disconnect_for_resync()
    emit event with stable id/name/data
  close after terminal event is flushed or timeout/policy requires re-auth
```

Required behavior:

- Replay and live subscription must be joined without a gap or duplicate unsafely applied.
- Store a cursor only after the client processes the event.
- A client that cannot keep up is disconnected or resynced; it must not block other subscribers.
- Check authorization again when permissions can change during a long stream.

## Spring Boot Mapping

This is an implementation sketch, not a substitute for the selected framework's security model.

```java
@GetMapping(value = "/v1/runs/{runId}/events",
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public SseEmitter stream(
        @PathVariable String runId,
        @RequestHeader(value = "Last-Event-ID", required = false) String cursor,
        Authentication authentication) {
    access.check(authentication, "stream:subscribe", runId);

    SseEmitter emitter = new SseEmitter(45_000L);
    streamService.attach(runId, cursor, authentication, emitter);
    return emitter;
}
```

`SseEmitter` does not supply durable replay, heartbeat correctness, backpressure, or tenant authorization. Implement those services explicitly. Use a bounded executor and remove attachments on completion, error, timeout, and client disconnect.

## Fetch SSE Client Pseudocode

```ts
async function streamRun(runId: string, signal: AbortSignal) {
  let cursor: string | null = null;
  let attempt = 0;

  while (!signal.aborted) {
    try {
      const response = await fetch(`/v1/runs/${runId}/events`, {
        headers: cursor ? { "Last-Event-ID": cursor } : {},
        signal,
      });

      if (response.status === 401) {
        await refreshSessionOnce();
        continue;
      }
      if (response.status === 403 || response.status === 400) {
        return terminal(response.status);
      }
      if (response.status === 429 || response.status === 503) {
        await sleep(retryAfterOrBackoff(response, attempt++));
        continue;
      }
      if (!response.ok || !response.body) {
        throw new Error(`stream failed: ${response.status}`);
      }

      const openedAt = Date.now();
      for await (const event of parseSse(response.body)) {
        if (event.type === "reset") {
          replaceWithSnapshot(event.data);
        } else {
          applyEventIdempotently(event);
        }
        if (event.id) cursor = event.id;
        if (isTerminal(event)) return;
      }

      attempt = Date.now() - openedAt > 30_000 ? 0 : attempt + 1;
    } catch (error) {
      if (signal.aborted) return;
      attempt += 1;
    }

    await sleep(fullJitter(500, 30_000, attempt));
  }
}
```

The parser must handle multi-line `data:`, comments/heartbeats, CRLF/LF, event names, IDs, and dispatch boundaries. Test it with fragmented chunks and malformed lines.

## Authentication/Authorization Integration

Sequence:

1. Gateway validates session/token and routes to the BFF/run service.
2. Service validates issuer, audience, signature, expiry, and required scopes.
3. Resource policy checks tenant/run ownership/action.
4. Stream service repeats the resource check before replay and subscription.
5. Worker receives a scoped delegated identity or a least-privilege service identity.
6. Tool adapters validate their own audience/scope and record audit context.
7. Token expiry triggers refresh/reconnect or a controlled close.

Never trust `tenant_id` or `run_id` supplied only in a payload when it can be derived or verified from an authenticated context.

## Durable Publisher

Create/update domain state and outbox in one transaction. Relay with at-least-once semantics:

```text
BEGIN
  update agent_run
  insert outbox_event(event_id, topic, partition_key, payload, created_at)
COMMIT

relay:
  claim outbox row with lease
  publish with broker confirmation
  mark published with compare-and-set
  retry transient errors
  alert on age/attempt threshold
```

Consumers use `event_id` or a business key in `inbox_consumed` and commit that record with the business effect. Acknowledge after commit. Replays must be safe.

## Cancellation and Human Approval

Cancellation endpoint:

1. Authorize `run:cancel`.
2. Compare-and-set `cancelling`; return `202` for first and repeated calls.
3. Publish one durable cancel command with idempotency key.
4. Propagate cancellation/deadline to active model/tool calls.
5. Persist `cancelled` only after workers acknowledge or the reconciliation deadline passes.

Approval endpoint:

1. Authorize `run:approve` for the specific action and resource.
2. Lock/compare-and-set the pending approval.
3. Persist decision and outbox event atomically.
4. Resume the run once; duplicate submit returns the existing decision.
5. Expired, stale, or mismatched approvals fail closed.

## Implementation Sequence and Gates

| Phase | Deliverables | Exit gate |
|---|---|---|
| 0. Architecture gate | ADR, candidate matrix, topology, assumptions | Every interaction has a protocol, owner, and rejection rationale |
| 1. Security skeleton | BFF/issuer, token validation, tenant/resource policy, Origin/CORS/CSRF | Unauthorized and cross-tenant tests fail closed |
| 2. Durable state | Run schema, state machine, idempotency, outbox | Restart/duplicate create does not create duplicate runs |
| 3. Internal execution | Broker/queue, orchestrator, worker lease, inbox/dedupe, DLQ | Kill consumer mid-flight; recovery is deterministic |
| 4. SSE delivery | Event store, cursor, replay, snapshot, heartbeat, bounded queues | Network drop and cursor expiry recover correctly |
| 5. Optional duplex | WebSocket control, barge-in, ack, reconnect, re-auth | Mixed control/data plane has no correctness gap |
| 6. Observability | Logs, metrics, traces, dashboards, alerts, audit | Can identify failing run and recovery point end to end |
| 7. Load and rollout | Backpressure, quotas, chaos tests, canary, rollback | SLOs hold at expected peak and degraded mode is explicit |

## Test Additions

- Unit: state transitions, cursor parser, SSE parser, idempotency, HMAC verification.
- Contract: CloudEvents/AsyncAPI/JSON Schema backward and forward compatibility.
- Integration: outbox relay, broker confirmation, duplicate delivery, DLQ redrive.
- End-to-end: browser reconnect, proxy buffering, token expiry, forbidden subscription.
- Resilience: kill stream service, worker, broker, and database connection during a run.
- Load: active connections, event fan-out, large output, slow consumers, reconnect storm after outage.
- Security: IDOR, cross-tenant cursor, replay of old webhook, expired token, forged event source.

## Deployment Gates

Before production:

- Gateway/CDN timeout and buffering settings are verified in staging.
- Connection and replay capacities are load-tested with reconnect storms.
- Token/key rotation is rehearsed.
- Dashboards and alerts cover run completion, reconnect recovery, outbox age, consumer lag, and DLQ.
- A kill switch can stop new admissions without breaking existing runs.
- Rollback preserves event history and supports both old and new schema versions.

