# Sequence Diagram Pack

Use or adapt these Mermaid diagrams in design documents and implementation PRs. Remove interactions that do not exist in the actual system.

## Normal Run and Stream

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
    API->>DB: Run state + outbox (one transaction)
    API-->>C: 202 + run_id + stream_url
    B->>O: agent.run.requested
    O->>DB: Persist state transition
    O->>B: progress/result events
    B->>S: ordered events + cursor
    C->>S: GET /runs/{id}/events
    S->>S: Authorize subscription
    S-->>C: snapshot/deltas/terminal
    O->>DB: Persist authoritative completion
```

## SSE Reconnect, Replay, Snapshot

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant S as Stream API
    participant E as Event Store

    C-->>S: Connection drops
    C->>C: Backoff + full jitter
    C->>S: Reconnect with Last-Event-ID
    S->>S: Authenticate + authorize
    S->>E: Read after cursor
    alt retained cursor
        E-->>S: missed events
        S-->>C: replay then live
        C->>C: Deduplicate + apply in order
    else expired cursor
        S-->>C: reset + snapshot cursor
        C->>C: Replace transient state
    end
```

## Token Expiry

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant A as Identity/BFF
    participant S as Stream API

    S-->>C: auth challenge or controlled close
    C->>A: refresh/re-authenticate
    alt success
        A-->>C: scoped credential
        C->>S: reconnect + cursor
        S->>S: validate + re-authorize
        S-->>C: resume/reset
    else failure
        A-->>C: authentication required
        C->>C: terminal state
    end
```

## Duplicate, Retry, DLQ

```mermaid
sequenceDiagram
    autonumber
    participant O as Outbox Relay
    participant B as Broker/Queue
    participant W as Worker
    participant I as Inbox/Dedupe
    participant D as DLQ

    O->>B: publish event
    B->>W: deliver
    W->>I: claim idempotency key
    alt first delivery
        W->>W: effect + inbox commit
        W->>B: ack
    else duplicate
        I-->>W: prior result
        W->>B: ack
    end
    W--xB: failure/no ack
    B->>W: redeliver with backoff
    W->>D: poison after max attempts
```

## Cancel or HITL

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as Run API
    participant DB as Run DB
    participant B as Broker/Queue
    participant O as Orchestrator
    participant T as Tool/Worker

    U->>API: cancel/approve
    API->>API: authorize action/resource
    API->>DB: CAS state + outbox
    API-->>U: 202 idempotent result
    B->>O: command
    O->>O: reject stale or apply once
    O->>T: cancellation/deadline/approval
    T-->>O: acknowledgement/result
    O->>DB: persist terminal/reconciled state
```

