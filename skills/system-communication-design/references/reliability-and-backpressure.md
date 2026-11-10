# Reliability and Backpressure

## Non-Negotiable Rules

1. State delivery semantics explicitly. Prefer at-least-once and idempotent consumers.
2. Persist authoritative state before exposing progress as durable completion.
3. A reconnect is not a recovery unless the server can prove continuity with a cursor or a snapshot.
4. A heartbeat proves liveness, not correctness or delivery.
5. A bounded queue is safe only when its overflow policy is defined.
6. Retry only idempotent operations unless the server enforces an idempotency key.
7. Stop or re-authenticate on permanent errors; do not retry forever.

## SSE Connection State Machine

Use this states plus explicit UI behavior:

| State | Meaning | Allowed next states |
|---|---|---|
| `CONNECTING` | Opening HTTP stream or waiting for first event | `OPEN`, `RECONNECTING`, `TERMINAL` |
| `OPEN` | Stream active and heartbeat within deadline | `DEGRADED`, `RECONNECTING`, `COMPLETED`, `TERMINAL` |
| `DEGRADED` | Data late, buffer high, or transport suspect | `OPEN`, `RECONNECTING`, `TERMINAL` |
| `RECONNECTING` | Backoff/refresh in progress | `CONNECTING`, `TERMINAL` |
| `COMPLETED` | Terminal run state received and persisted | none |
| `TERMINAL` | Unauthorized, forbidden, invalid request, or unrecoverable stream | after user action only |

On reconnect, send the last accepted cursor as `Last-Event-ID` when using native EventSource, or as the agreed header/query parameter with fetch SSE. Only move the cursor after the client has durably processed the event. Keep a small dedupe window because a replay may overlap the last delivered event.

## Retry Policy

Use exponential backoff with full jitter:

```text
raw_delay = min(cap_ms, base_ms * 2^attempt)
delay_ms = random_uniform(0, raw_delay)
```

Starting point for an interactive stream:

- `base_ms`: 500
- `cap_ms`: 30,000
- Reset the attempt counter after a connection remains healthy for at least 30 seconds.
- Keep a persistent retry loop at the cap while the user still has the run open.
- Honor `Retry-After` for `429` and `503`; use the larger of backoff and server guidance.

Error handling:

| Condition | Action |
|---|---|
| Network drop, timeout, 5xx | Reconnect with backoff; resume from cursor |
| `401` | Refresh credentials once; if refresh fails, move to terminal re-authentication |
| `403`, invalid tenant, revoked run access | Stop; do not retry |
| `400`, malformed cursor | Request a snapshot or restart the run view |
| `429` / `503` | Honor `Retry-After`, then reconnect with jitter |
| `204` on native EventSource | Treat as intentional stream termination; do not reopen |
| Cursor outside replay retention | Send/request snapshot; issue a new cursor |

For non-streaming commands, retry only with an idempotency key. Use bounded attempts and surface the final ambiguous outcome; never imply a side effect succeeded when the client did not receive a confirmed result.

## Server Stream Lifecycle

Recommended starting values; tune using measured traffic:

- Heartbeat comment every 15 seconds.
- Idle timeout around 45 seconds, greater than two heartbeat intervals.
- Per-connection outbound queue: 256 events or 1 MiB, whichever is lower.
- High watermark: 70%; low watermark: 40%.
- Replay retention: at least the maximum expected reconnect window, for example 30 minutes.
- Maximum active streams per user/tenant and global connection limits.

Response shape:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
X-Accel-Buffering: no

id: 018f...
event: token
data: {"run_id":"r_123","turn_id":"t_1","sequence":41,"text":"hello"}

: keepalive

```

Do not place secrets or large state snapshots in every event. Use references/URLs only if access is separately authorized. Emit a compact typed event and let the client fetch a snapshot when required.

## Replay and Snapshot Recovery

Store:

- `stream_id` or `run_id`
- opaque monotonic `event_id`
- optional `sequence` per stream/aggregate
- event type and JSON payload
- creation time
- retention expiry
- tenant and authorization scope

Replay algorithm:

1. Authenticate and authorize the requested stream.
2. Parse `Last-Event-ID`.
3. If the cursor is valid and retained, replay events after it in order.
4. Continue live streaming with a dedupe point at the replay/live seam.
5. If the cursor is invalid or expired, return `reset` containing a snapshot cursor.
6. Client replaces local transient state with the snapshot, then continues from that cursor.

Do not use database auto-increment IDs as public cursors. They can reveal volume, complicate migrations, and create cross-tenant leaks. Use opaque cursor IDs with server-side validation.

## Bounded Buffers and Slow Consumers

### Server side

Never let one slow client block event production. Options, in order of preference:

1. Keep a bounded per-client queue and coalesce harmless deltas.
2. Disconnect the slow client with a retryable status/event when high watermark is sustained.
3. Require snapshot resynchronization instead of replaying an unbounded stream.
4. For durability-critical facts, persist them separately; the stream is only a delivery optimization.

Overflow policy must distinguish:

- Token/text deltas: coalesce or drop intermediate deltas; preserve final text/state.
- Progress percentages: keep only the latest value.
- State transitions, approvals, tool side effects, completion, failure: never silently drop; persist and resync.

### Client side

Use a bounded queue and render throttling. Store:

- last accepted cursor
- rolling dedupe IDs
- state snapshot or projection
- buffer bytes/events and overflow state

When full, stop applying deltas, show a degraded indicator, fetch/await a snapshot, and continue from the snapshot cursor. Do not grow memory until the tab crashes.

## Internal Delivery and Idempotency

Use the transactional outbox pattern when a database update and event publication must agree:

1. In one transaction, update domain state and insert an outbox row.
2. A relay publishes the outbox row with retry and publisher confirmation where available.
3. Mark it sent only after confirmation; tolerate duplicate publication.
4. Consumers deduplicate using the event ID or business idempotency key.

Consumer design:

- Claim work with a lease/visibility timeout.
- Persist the effect and inbox/dedupe record in one transaction when possible.
- Acknowledge only after the effect is committed.
- On duplicate, return the prior result rather than repeating side effects.
- Retry transient errors with exponential backoff and jitter.
- Route poison messages to a DLQ after a bounded attempt count.
- Record failure reason, original payload reference, attempt count, and replay operator.
- Keep dedupe retention longer than the maximum replay/redelivery window.

Choose ordering by aggregate key such as `run_id` or `tenant_id:run_id`. Do not require global ordering unless the business truly needs it.

## Backpressure

Apply pressure end to end:

- API: per-user/tenant run quotas and bounded concurrent runs.
- Orchestrator: bounded worker pool, queue-depth threshold, `429`/admission rejection before overload.
- Model/tool calls: deadlines, cancellation, retry budgets, circuit breakers.
- Broker: consumer lag thresholds, maximum in-flight messages, pause/resume consumption.
- Stream service: high/low watermarks, delta coalescing, slow-client disconnect.
- Client: bounded render queue, throttled DOM updates, snapshot recovery.

Cancellation must be idempotent. Persist a terminal `cancel_requested`/`cancelled` transition and propagate cancellation tokens to active tools. A late worker result must not overwrite a cancelled run as successful unless the state machine explicitly allows that transition.

## Failure Test Matrix

| Scenario | Expected behavior |
|---|---|
| Wi-Fi drops for 2 minutes | Reconnect with jitter, replay from cursor, no duplicate visible side effect |
| Proxy buffers response | Heartbeat and deployment checks expose or prevent the issue |
| Cursor older than retention | Snapshot reset, then live continuation |
| User token expires during stream | Close/refresh/re-authenticate path; no endless unauthorized retry |
| Consumer dies after side effect before ack | Redelivery is deduplicated by inbox key |
| Same event delivered twice | One business effect; prior result returned |
| Events arrive out of order | State machine rejects stale transitions or reorders by sequence |
| Slow client queue reaches high watermark | Coalesce/disconnect/resync without blocking producers |
| Broker unavailable | Outbox retains records; publishing resumes without lost domain commits |
| Poison message | Bounded retry, DLQ, alert, and controlled replay |
| Approval retried | Single approval effect; stale approval rejected |
| Broadcast fan-out storm | Per-client limits and admission control prevent global stall |

## Observability

Track at minimum:

- Active streams, connection success/failure rate, reconnect count, reconnect duration.
- Time to first event, event delivery latency, heartbeat age, replay count, snapshot resets.
- Per-client buffer depth, slow-client disconnects, dropped/coalesced deltas.
- Outbox age, publish failures, consumer lag, retry count, DLQ count, duplicate suppression.
- Auth failures by reason, token refresh failures, unauthorized subscription attempts.
- `run_id`/`correlation_id`/trace propagation across HTTP, stream, broker, worker, and tool calls.

Define SLOs for time to first token, completion notification delivery, reconnect recovery, and unauthorized-access rate. Alert on sustained lag or replay-window exhaustion, not only process health.

