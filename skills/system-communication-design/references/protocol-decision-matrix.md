# Protocol Decision Matrix

## Selection Principle

Choose the least capable transport that satisfies the hardest requirement. A system can use several channels; optimize each path independently. Do not force all communication through one protocol merely for uniformity.

Use these dimensions:

- Direction: request/response, server-to-client stream, client-to-server stream, or full duplex.
- Latency and interactivity: one final response, incremental output, or continuous control.
- Durability: can a message be lost, replayed, or reconstructed from state?
- Ordering: global, per aggregate key, or unnecessary.
- Fan-out: one consumer, one consumer group, or many independent subscribers.
- Network boundary: browser, mobile, partner webhook, private service mesh, or same process.
- Operational cost: gateway compatibility, connection scale, storage, replay retention, and on-call complexity.

## Comparison Matrix

| Option | Best fit | Direction | Native recovery | Main strengths | Main limits |
|---|---|---|---|---|---|
| HTTPS + JSON | CRUD, commands, queries, snapshots | Client to server, request/response | Client retries the request | Universal tooling, cache/CDN, simple auth | No incremental server push; long requests tie up connections |
| SSE | Token streams, progress, notifications, one-way result streams | Server to client over HTTP | EventSource reconnects; resume needs server support | Simple HTTP deployment, proxy-friendly, text event framing, easy replay cursor | One-way only; native EventSource has limited request controls; intermediaries may buffer |
| fetch + SSE | Streaming where the client needs Authorization headers, POST, or custom controls | Server to client | Must implement reconnect, cursor, and parser | Request flexibility and streaming with standard HTTP | More client code; parser errors and lifecycle are application-owned |
| WebSocket | Voice, collaboration, barge-in, high-frequency bidirectional control | Full duplex | No built-in session resume | Low overhead after handshake, binary support, interactive | Connection state, auth refresh, reconnect, backpressure, fan-out and proxy timeouts are application-owned |
| Webhook | Partner/service notifications, asynchronous callbacks | Server to server | Sender retries; receiver deduplicates | Decoupled and universally supported | At-least-once, out-of-order, spoofing/replay risk, endpoint lifecycle and retry management |
| gRPC streaming | Controlled service-to-service RPC, typed streaming | Unary, server, client, or bidirectional | Deadlines and retries are call-policy dependent | Schema-first, HTTP/2 multiplexing, backpressure primitives, deadlines | Browser support generally requires a gateway/proxy; infrastructure maturity required |
| In-process EventBus | Decoupling modules inside one process | Publish/subscribe | None unless combined with persistence | Very low latency and simple code | Not cross-process; default implementations may be synchronous; events can vanish on crash |
| Durable queue/stream | Work distribution, fan-out, buffering, replay | Asynchronous producer to consumer groups | Broker-dependent redelivery and retention | Decoupling, buffering, scaling, retry/dead-letter patterns | Operational cost; ordering and delivery semantics must be explicit |

## External Channel Guidance

### HTTPS + JSON

Use for commands that create or mutate work when a final response is enough. Return `202 Accepted` plus a task ID or stream URL when processing is asynchronous.

Design mutations with idempotency keys when the same request can be retried. For unsafe operations, do not assume HTTP retry behavior makes them safe. Use explicit versions or conditional requests where lost updates matter.

### SSE

Use SSE when the server emits a sequence of events and the client does not need a persistent client-to-server channel. Typical events are model deltas, tool progress, status changes, heartbeat comments, completion, and failure.

Use fetch + SSE when the browser must send `Authorization`, use a POST body, attach custom tracing headers, or control parsing. Fetch does not provide EventSource's automatic reconnection or `Last-Event-ID` behavior; implement these explicitly.

Native EventSource constraints:

- It uses HTTP GET and does not expose a general API for arbitrary request headers.
- Cross-origin credentials require explicit configuration; server CORS and cookies must both be correct.
- It has built-in reconnection behavior, but the server must emit event IDs and support replay to close data gaps.
- Returning a `204 No Content` response can be used to stop a browser reconnection loop when the stream is intentionally finished.

SSE is not a reliable log by itself. Persist the authoritative event history or state projection, and keep only a bounded replay window in the stream service. If the cursor is older than retention, send a `reset` or `snapshot_required` event rather than pretending continuity.

Deployment checks:

- Response media type is `text/event-stream`.
- Disable response buffering and transformation at proxies/CDNs where supported.
- Use periodic comment heartbeats so idle proxies do not silently kill the connection.
- Account for connection limits and configure HTTP/2 or enough HTTP/1.1 capacity where relevant.
- Test through the real gateway, CDN, service mesh, load balancer, and corporate proxy.

### WebSocket

Use for continuous user input, audio, collaboration, frequent interruption, or controls where a new HTTP request per action is wasteful. Keep ordinary file upload and long-running command initiation on HTTP; WebSocket should carry what genuinely benefits from duplex communication.

The application must define:

- Handshake authentication and Origin validation.
- Per-message or per-subscription authorization.
- Message schema, request IDs, acknowledgements, and duplicate handling.
- Heartbeat/ping-pong and idle timeout.
- Reconnect with exponential backoff and full jitter; WebSocket has no automatic reconnect.
- Session resume, missed-message recovery, and resynchronization from state.
- Per-connection outbound queue limits and slow-consumer policy.
- Token expiry behavior and a bounded re-authentication flow.

### Hybrid Control/Data Plane

A robust Agent UI often uses:

- HTTPS for create, snapshot, query, and cancel commands.
- WebSocket for low-latency controls, barge-in, and acknowledgements.
- SSE for ordered server output and incremental text/progress.

Do not make correctness depend on simultaneous delivery across two sockets. Include `run_id`, `turn_id`, `sequence`, and `event_id` so the client can merge or resynchronize. If mixed-channel complexity is not justified, use WebSocket for both control and data or HTTP commands plus SSE.

### Webhook

Use for cross-system notifications. A webhook is an asynchronous at-least-once interface, not a synchronous RPC.

Treat the receiver as idempotent: verify signature and timestamp, reject stale replays, deduplicate by provider event ID, persist before acknowledging, and process asynchronously. Define a retry schedule, a dead-letter/manual replay path, and an endpoint rotation/revocation process.

## Internal Channel Guidance

### In-process EventBus

Use only when publisher and subscriber share a process and the event can be lost on crash without violating correctness.

Important traps:

- A synchronous event bus executes listeners on the publisher path unless configured otherwise.
- Adding asynchronous execution removes blocking but still does not make delivery durable.
- Logging, points, notifications, and tool execution with business side effects should not be acknowledged to the user as completed merely because an in-memory event was queued.

For durable side effects, write the domain change and an outbox record in one database transaction, then publish asynchronously. Or use a durable broker with publisher confirms and the appropriate acknowledgement pattern.

### Queue vs Stream

Use a work queue when jobs are assigned to competing consumers and should disappear after successful acknowledgement. Use a durable stream/log when multiple consumer groups must replay history, ordering is partition/key based, or retention is part of the recovery design.

Selection questions:

- Must a new consumer replay historical events?
- Is ordering needed globally or only per `run_id`/tenant?
- Is the workload command-like (do once) or fact-like (broadcast and replay)?
- How long must events survive consumer downtime?
- What are the broker's delivery, retention, partition, and acknowledgement semantics?

Do not infer semantics from vendor slogans. Record the concrete configuration: acknowledgement mode, consumer commit timing, visibility timeout, retention, maximum in-flight messages, retry, and dead-letter policy.

## Topology Patterns

### Agent Run

1. Client calls `POST /runs` and receives `202` with `run_id`.
2. API writes run state and `agent.run.requested` to an outbox in one transaction.
3. Publisher sends the event to a durable internal channel.
4. Router/orchestrator claims the run, persists state transitions, and emits progress/result events.
5. Stream service consumes/multiplexes events, assigns or preserves a resumable cursor, and fans out SSE/WebSocket frames.
6. Client reconnects with `Last-Event-ID`; stream service replays or returns a snapshot cursor.
7. Completion is persisted independently of whether the client is still connected.

### Multi-Agent Router/Worker

- Router decides decomposition; workers execute with bounded concurrency.
- Each task has a stable `task_id`, parent `run_id`, deadline, retry count, and idempotency key.
- Use per-task work queues for competing workers.
- Publish immutable result facts; do not let workers mutate shared orchestration state directly.
- Persist the task graph so a router restart can reconstruct what is pending, running, succeeded, and failed.
- Handle duplicate worker results by task ID and idempotent state transition.

### Human-in-the-Loop

- Approval is a first-class event with `approval_id`, actor, decision, timestamp, and policy context.
- Approval events are idempotent and expire.
- The run state machine must reject approval for a stale or already-resolved request.
- Resume must not replay the approved side effect twice.

## Decision Record Template

| Field | Value |
|---|---|
| Interaction path | |
| Hard requirements | |
| Selected protocol | |
| Rejected alternatives | |
| Delivery semantics | |
| Recovery mechanism | |
| Authentication/authorization | |
| Operational owner | |
| Cost and limits | |
| Revisit trigger | |

