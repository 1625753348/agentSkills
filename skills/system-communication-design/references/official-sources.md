# Official Sources

Use primary standards and vendor documentation. Re-check versions and status when making a new protocol or security decision.

## HTTP and Streaming

- WHATWG HTML, Server-Sent Events: <https://html.spec.whatwg.org/multipage/server-sent-events.html>
  - Covers `text/event-stream`, event framing, `id`, `retry`, reconnection, and `Last-Event-ID`.
  - Do not assume the browser's reconnect closes data gaps without server-side replay.
- RFC 9110, HTTP Semantics: <https://www.rfc-editor.org/rfc/rfc9110.html>
  - Defines safe/idempotent methods, status semantics, and `Retry-After`.
- RFC 6455, The WebSocket Protocol: <https://www.rfc-editor.org/rfc/rfc6455.html>
  - Defines handshake, framing, ping/pong, close codes, and Origin header handling. Reconnect, session resume, and application authorization are not supplied by the protocol.
- gRPC Core Concepts: <https://grpc.io/docs/what-is-grpc/core-concepts/>
  - Covers unary and streaming RPC, deadlines, and HTTP/2-based transport.

## Identity and Security

- RFC 6749, OAuth 2.0 Authorization Framework: <https://www.rfc-editor.org/rfc/rfc6749.html>
- RFC 6750, Bearer Token Usage: <https://www.rfc-editor.org/rfc/rfc6750.html>
- RFC 7636, PKCE: <https://www.rfc-editor.org/rfc/rfc7636.html>
- RFC 9700, OAuth 2.0 Security Best Current Practice: <https://www.rfc-editor.org/rfc/rfc9700.html>
- OAuth 2.1 draft: <https://datatracker.ietf.org/doc/draft-ietf-oauth-v2-1/>
  - Treat as a consolidation draft; verify deployment requirements against published RFCs and the current BCP.
- OpenID Connect Core 1.0: <https://openid.net/specs/openid-connect-core-1_0.html>
- RFC 7519, JWT: <https://www.rfc-editor.org/rfc/rfc7519.html>
- RFC 8446, TLS 1.3: <https://www.rfc-editor.org/rfc/rfc8446.html>
- RFC 8705, Mutual-TLS Client Authentication and Certificate-Bound Access Tokens: <https://www.rfc-editor.org/rfc/rfc8705.html>
- RFC 8693, OAuth 2.0 Token Exchange: <https://www.rfc-editor.org/rfc/rfc8693.html>
- OWASP Authorization Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html>
- OWASP CSRF Prevention Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>

## Event Contracts and Observability

- CloudEvents specification: <https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md>
- AsyncAPI 3.0 specification: <https://www.asyncapi.com/docs/reference/specification/v3.0.0>
- JSON Schema: <https://json-schema.org/specification>
- W3C Trace Context: <https://www.w3.org/TR/trace-context/>
- OpenTelemetry specification: <https://opentelemetry.io/docs/specs/otel/>

## Brokers and Proxies

- Apache Kafka documentation: <https://kafka.apache.org/documentation/>
- RabbitMQ reliability and confirms: <https://www.rabbitmq.com/docs/confirms>
- NGINX proxy buffering: <https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering>

## Application Notes

- Native EventSource behavior and fetch-based streaming have different reconnect responsibilities. State which one is used.
- Spring `ApplicationEventPublisher` and `@EventListener` are in-process mechanisms. `@Async` changes the execution thread but does not create durable delivery; use an outbox or broker for business-critical side effects.
- OAuth 2.1 is not a reason to use implicit or password grants. Use Authorization Code + PKCE for public clients and client credentials or workload identity for services.
- Broker delivery, ordering, and retention depend on configuration. Name the concrete setting and test it instead of citing a generic claim.

