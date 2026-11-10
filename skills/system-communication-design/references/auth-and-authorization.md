# Authentication and Authorization

## Separate the Questions

- Authentication: Who is calling? User, browser session, service workload, webhook sender, or device.
- Authorization: May this principal perform this action on this resource, tenant, agent, tool, or event stream?
- Delegation: Is an agent acting for the user? If so, with what reduced scope and audience?
- Transport security: Is the channel protected against interception and impersonation?

An authenticated user is not automatically authorized for every run, event topic, file, tool, or tenant. Enforce authorization at the resource boundary and again when subscribing to a stream.

## Recommended Authentication Patterns

| Caller | Preferred baseline | Avoid |
|---|---|---|
| Browser application | OIDC Authorization Code + PKCE through a BFF, HttpOnly Secure SameSite session cookie | Long-lived access tokens in localStorage; implicit flow; password grant |
| Native/mobile app | OIDC Authorization Code + PKCE, OS secure storage, short-lived access token + rotating refresh token | Static client secret embedded in the app |
| Service to service | Workload identity with mTLS and/or OAuth client credentials; short-lived, audience-scoped token | Shared static API key across all services |
| Partner webhook sender | HMAC signature over timestamp + raw body, key rotation, replay window | IP allowlist as the only control |
| SSE/WebSocket browser session | BFF cookie or a short-lived, single-use stream ticket; authenticate the handshake; re-authenticate before token expiry | Long-lived bearer token in query string |
| Agent acting for a user | OAuth token exchange or equivalent delegation; downscoped, audience-bound credential | Copying the user's full-session token into every tool |

OAuth 2.1 is still a draft consolidation of OAuth 2.0 security best current practice. For production requirements, use the applicable published RFCs and the current OAuth Security BCP, not the draft label alone.

## Browser and BFF

Prefer a backend-for-frontend:

1. Browser redirects to the identity provider.
2. BFF completes Authorization Code + PKCE.
3. Browser receives an HttpOnly, Secure, appropriately scoped session cookie.
4. BFF attaches short-lived access tokens to internal calls.
5. Browser never receives refresh tokens or broad service credentials.

For cookie-authenticated state-changing HTTP calls, implement CSRF protection (for example, same-site cookies plus an origin check and CSRF token). Do not rely on CORS alone as CSRF defense.

For cross-origin SSE:

- With credentials, return an exact allowed origin and `Access-Control-Allow-Credentials: true`; wildcard origins are invalid with credentials.
- Check `Origin` on stream creation where appropriate.
- Keep GET streams side-effect free.
- Use fetch + SSE when custom Authorization or tracing headers are required.

If native EventSource is a hard requirement and bearer authentication is needed, prefer a short-lived single-use ticket exchanged over an authenticated endpoint. Bind the ticket to user, tenant, stream, origin, expiry, and one-time use. Never put a long-lived token in a URL, referrer, access log, or analytics event.

## WebSocket

Browser WebSocket APIs do not provide a general custom `Authorization` header. Prefer:

1. Same-origin HttpOnly session cookie plus strict Origin validation, or
2. A short-lived single-use ticket obtained through an authenticated HTTPS call.

Handshake requirements:

- Validate `Origin` against an explicit allowlist.
- Authenticate before accepting subscriptions or commands.
- Authorize each channel/run subscription, not only the socket.
- Limit connections per principal, tenant, and IP/device.
- Bind the connection to tenant and session identifiers.
- Reject unknown subprotocols and oversized first frames.

Token lifecycle:

- Do not keep an expired token active for the lifetime of the socket.
- Send a re-authentication challenge before expiry or close with a policy/application close code.
- Require the client to refresh and reconnect.
- Do not include token material in close reasons, logs, or message payloads.

## Access Token Validation

For JWT access tokens:

- Verify the signature with trusted keys from the expected issuer and an explicit algorithm allowlist.
- Validate `iss`, `aud`, `exp`, `nbf`, and clock skew.
- Validate tenant, scope, role, or delegation claims only after cryptographic validation.
- Cache JWKS safely and refresh on an unknown key ID.
- Reject tokens with unexpected audiences, issuers, token types, or missing scopes.
- Do not parse claims and trust them before verification.
- Do not implement cryptographic primitives yourself.

Opaque tokens require introspection or an equivalent trusted validation path. Cache introspection only within the token's validity and revocation constraints.

## Authorization Model

Use coarse scopes for API capability and a resource policy for the actual object:

- `run:create`, `run:read`, `run:cancel`, `run:approve`, `tool:invoke`, `stream:subscribe`.
- Resource subject: user/service, tenant, run owner, workspace membership, agent/tool ID.
- Action: read/write/cancel/approve/invoke/subscribe.
- Context: tenant, data classification, approval status, deadline, IP/device risk if relevant.

Required checks:

- `run_id` belongs to the authenticated tenant and principal.
- Event cursor and replay are scoped to the same authorization context.
- Tool calls use the user's delegated scope or a dedicated service identity with least privilege.
- File/object references are re-authorized on access, not trusted because they appeared in an event.
- Admin/support access is explicit, time-bounded, audited, and visibly disclosed where appropriate.
- Approval does not grant broader permissions than the requested action.

For agent tool invocation, prefer per-tool audiences and short-lived delegated credentials. Treat model output as untrusted input to the authorization layer; never let the model decide its own permissions.

## Service Identity and Secrets

- Put services in a workload identity or mutually authenticated service mesh.
- Use mTLS for transport identity; use audience-scoped authorization tokens when application-level identity is required.
- Use short-lived credentials and automatic rotation.
- Keep secrets out of images, repositories, localStorage, URLs, event payloads, and logs.
- Use a secret manager with audited access; separate development, staging, and production keys.
- Support overlapping key IDs and rotation; verify old keys only during the documented overlap window.

## Webhook Verification

Use a versioned signature scheme:

```text
canonical = timestamp + "." + raw_body
signature = HMAC-SHA256(secret, canonical)
X-Webhook-Timestamp: 1760000000
X-Webhook-Signature: v1=<hex>
```

Verification order:

1. Read the raw body before JSON parsing.
2. Reject missing, stale, or future timestamps outside the replay window.
3. Compute the expected HMAC and compare in constant time.
4. Accept only supported signature versions/key IDs.
5. Persist provider event ID and process idempotently.
6. Acknowledge only after durable acceptance; process side effects asynchronously.

Rotate secrets with overlapping key IDs. Never log the full secret or signature material.

## Stream and Topic Authorization

- Authorize the stream URL and each subscribed run/channel.
- Re-check long-lived stream authorization when permissions or tenant membership change.
- Protect internal topics by producer/consumer identity and topic-level ACLs.
- Encrypt in transit; encrypt at rest where the broker or platform requires it.
- Do not place secrets, raw credentials, full prompts with sensitive data, or unrestricted tool outputs on a broadly visible bus.
- Apply payload size limits, schema validation, and rate limits at ingress.

## Audit and Abuse Controls

Record security-relevant events:

- authentication success/failure and token refresh failure
- authorization denial with resource/action, without secrets
- stream subscription and replay
- approval, cancellation, tool invocation, and admin access
- webhook signature/replay rejection
- key rotation and policy changes

Apply rate limits and quotas by user, tenant, IP/device, stream type, and cost. Protect expensive model/tool paths with admission control, not only post-hoc monitoring.

## Authentication Checklist

- [ ] Every external endpoint states its authentication method.
- [ ] Every resource has an authorization policy, not only a scope check.
- [ ] SSE/WebSocket subscriptions are authorized per stream.
- [ ] Token expiry behavior is defined for long-lived connections.
- [ ] No long-lived credential is placed in a URL.
- [ ] Origin/CORS/CSRF behavior is specified for browser channels.
- [ ] Service identities use mTLS/workload identity or audience-scoped short-lived tokens.
- [ ] Webhooks use timestamped HMAC and idempotency.
- [ ] Secrets rotate without downtime and are never logged.
- [ ] Security denials, approvals, and tool calls are auditable.

