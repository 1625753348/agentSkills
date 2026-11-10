# Delivery Artifacts

Use this after the communication decisions are sufficiently stable. The purpose is to turn the design into reviewable diagrams, contracts, code, and tests without losing the decision rationale.

## Design-to-Code Gate

Before changing business code, write a compact decision summary:

- external control and data channels
- internal event/queue/stream choice
- delivery and ordering semantics
- cursor, replay, and snapshot strategy
- authentication, authorization, and delegation
- repository language/framework and target modules
- unresolved constraints that change the implementation

If the user asked for code directly, produce this summary first and proceed without waiting when the choices are clear.

## Required Diagrams

Use Mermaid `sequenceDiagram` unless the repository uses another diagram system. Keep participants at the architectural boundary level. Create only the diagrams that correspond to real risks, but normally include:

1. Normal run: create, persist, publish, execute, stream, complete.
2. SSE reconnect: disconnect, cursor, replay, dedupe, snapshot fallback.
3. Token expiry: reject, refresh/re-auth, reconnect, authorization re-check.
4. Internal duplicate/DLQ: outbox, redelivery, inbox dedupe, retry, DLQ, replay.
5. Cancellation or HITL: authorization, state transition, idempotent command, worker propagation.

Validate Mermaid syntax and participant names. Put diagrams next to the design that they explain; do not generate decorative diagrams for paths that were not designed.

## Contract Artifacts

Generate, according to stack:

- OpenAPI for synchronous HTTP endpoints and error responses.
- AsyncAPI for internal channels/topics and message bindings.
- JSON Schema for event payloads.
- CloudEvents examples for normal, duplicate, retry, failed, and terminal events.
- Webhook signature/replay examples where applicable.

Use one source of truth for generated types where practical. Keep hand-written domain types only when generated types would lose required invariants.

## Code Generation Order

1. Shared IDs, enums, error codes, event envelope, and schemas.
2. Auth middleware and resource policy hooks.
3. Run/command endpoint with idempotency and transaction boundary.
4. Outbox writer and publisher.
5. Consumer/inbox/dedupe/DLQ or equivalent.
6. Event persistence, cursor, replay, and snapshot service.
7. SSE server or WebSocket handler with bounded per-client queues.
8. Client parser, reconnect state machine, bounded buffer, dedupe, and snapshot recovery.
9. Observability and metrics.
10. Unit, contract, integration, failure, and load tests.

Use the repository's existing patterns first. Do not introduce a new broker, auth library, frontend state framework, or schema tool unless the current stack cannot satisfy the requirement.

## Sequence Diagram Templates

Adapt names and calls to the actual code; these are not mandatory exact interactions.

### Normal Run

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as Run API
    participant DB as Run DB
    participant B as Broker/Stream
    participant O as Orchestrator
    participant S as Stream API

    C->>API: POST /runs + Idempotency-Key
    API->>API: Authenticate + authorize
    API->>DB: Insert run + outbox in one transaction
    API-->>C: 202 run_id + stream_url
    B->>O: agent.run.requested
    O->>DB: Persist running state
    O->>B: progress/result events
    B->>S: Ordered events with stable cursors
    C->>S: GET /runs/{id}/events
    S->>S: Authorize subscription
    S-->>C: SSE snapshot/deltas/terminal event
    O->>DB: Persist authoritative completion
```

### SSE Reconnect and Replay

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant S as Stream API
    participant E as Event Store

    C-->>S: TCP/proxy connection drops
    C->>C: Exponential backoff + full jitter
    C->>S: Reconnect with Last-Event-ID=cur_42
    S->>S: Re-authenticate + authorize run
    S->>E: Read events after cur_42
    alt cursor retained
        E-->>S: Events cur_43..cur_50
        S-->>C: Replay then live stream
        C->>C: Deduplicate and apply in sequence
    else cursor expired
        S-->>C: reset + snapshot cursor
        C->>C: Replace transient state with snapshot
    end
```

### Token Expiry During a Long Stream

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant Auth as Identity/BFF
    participant S as Stream API

    S-->>C: Close or auth challenge before/at token expiry
    C->>Auth: Refresh or re-authenticate
    alt refresh succeeds
        Auth-->>C: Scoped credential
        C->>S: Reconnect with credential + cursor
        S->>S: Validate audience/expiry + re-authorize
        S-->>C: Resume or reset
    else refresh fails
        Auth-->>C: Authentication required
        C->>C: Terminal UI state, no retry loop
    end
```

### Duplicate Delivery and DLQ

```mermaid
sequenceDiagram
    autonumber
    participant P as Publisher
    participant O as Outbox Relay
    participant B as Broker/Queue
    participant W as Worker
    participant I as Inbox/Dedupe
    participant D as DLQ

    P->>P: Commit domain state + outbox
    O->>B: Publish event evt_7
    B->>W: Deliver evt_7
    W->>I: Claim idempotency key
    alt first delivery
        W->>W: Commit side effect + inbox record
        W->>B: Acknowledge
    else duplicate
        I-->>W: Prior result
        W->>B: Acknowledge without repeating side effect
    end
    W--xB: Transient failure / no ack
    B->>W: Redeliver with backoff
    W->>D: Poison message after bounded attempts
    D-->>W: Operator-approved replay
```

### Cancellation or HITL

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as Run API
    participant DB as Run DB
    participant B as Broker/Queue
    participant O as Orchestrator
    participant T as Tool/Worker

    U->>API: Cancel or submit approval
    API->>API: Authorize resource/action
    API->>DB: CAS state + outbox event
    API-->>U: 202 idempotent result
    B->>O: cancel/approval command
    O->>O: Reject stale transition or apply once
    O->>T: Propagate cancellation/deadline/approval
    T-->>O: Acknowledge or terminal result
    O->>DB: Persist terminal/reconciled state
```

## Code Review Checklist

- [ ] Protocol choice and rejection rationale match the design.
- [ ] Auth is enforced at endpoint and resource level.
- [ ] Stream and replay authorization use the same tenant/resource policy.
- [ ] Event IDs, cursors, sequences, and idempotency keys are stable and tested.
- [ ] Retry has backoff, jitter, stop conditions, and non-retryable statuses.
- [ ] Server and client buffers are bounded with explicit overflow behavior.
- [ ] Outbox/inbox/DLQ semantics are implemented, not merely documented.
- [ ] Token expiry and re-authentication are handled for long-lived connections.
- [ ] Metrics/traces connect HTTP, stream, broker, worker, and tool boundaries.
- [ ] Tests cover disconnect, duplicate, reorder, restart, expiry, slow consumer, and unauthorized subscription.

