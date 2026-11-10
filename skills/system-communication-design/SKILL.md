---
name: system-communication-design
description: Design and implement communication architectures for agentic, realtime, and distributed systems. Use when choosing client streaming or control channels, internal event buses or queues, specifying reliability, authentication, sequence diagrams, and then generating code or tests. Do not use for a local library or a simple CRUD API with no streaming, events, or cross-service coordination.
metadata:
  short-description: Design implementable communication and auth
---

# System Communication Design

## 目标

设计任何包含实时交互、Agent、多服务协作或异步任务的系统时，把“通信架构”作为必选章节，而不是附注。输出必须同时覆盖：

- 对外通道：浏览器、移动端、第三方或设备如何调用命令、接收流式结果和发送控制信号。
- 对内通道：进程内事件、跨服务消息、任务调度、状态持久化和失败恢复。
- 可实现性：协议、端点、事件契约、重试参数、缓冲区、鉴权、部署组件、实施顺序和验收测试。

通信选择必须由需求和约束推导，不得只罗列技术名词。不要声称端到端“恰好一次”；默认按至少一次投递设计幂等消费。

## 固定实现流程

按以下顺序执行。前一阶段的决策未闭合时，不进入编码方案。

### 1. 冻结场景与约束

输出一个需求表，至少包含：参与方、交互方向、消息类型、峰值并发、消息大小/频率、允许延迟、断线时长、是否可丢、是否可重放、顺序要求、部署边界、租户隔离、合规与运维约束。

明确区分：

- 控制面：创建任务、取消、暂停、确认（HITL）、订阅和心跳。
- 数据面：token 流、工具进度、日志、音频、文件、状态快照。
- 内部事件：命令、领域事件、任务结果、失败和死信。

如果需求不完整，采用保守默认值并在输出中列出假设，不要静默省略。

### 2. 画出端到端路径

至少画出一条主路径和三条故障路径：

1. 正常请求、事件产生、持久化、消费、回传和确认。
2. 客户端断线后重连与增量恢复。
3. 消费者重启、重复投递或处理超时。
4. 下游阻塞、限流或鉴权失败。

每条路径标明同步边界、持久化点、重试点、取消点和超时预算。进程内 EventBus 不能跨越进程边界；需要跨进程可靠协同时，必须引入消息中间件或持久化日志。

### 3. 选择通信方式

建立候选矩阵，对 HTTP/JSON、SSE、WebSocket、Webhook、gRPC、进程内 EventBus、队列和持久化流逐项比较。至少说明“为什么不用其他候选”。

快速判断：

- 简单命令与查询：HTTPS + JSON。
- 服务端单向流式输出：优先 fetch + SSE；只有需要浏览器原生自动重连且可接受原生 EventSource 的限制时才直接使用 EventSource。
- 双向实时控制、音频、协作画布或频繁打断：WebSocket；复杂 Agent 可用 WebSocket 控制 + SSE 数据混合。
- 跨组织异步通知：Webhook + 签名、重放窗口和幂等键。
- 受控内网、强类型流或双向 RPC：gRPC；浏览器边缘通常需要网关转换。
- 单进程内解耦：进程内 EventBus，但它不提供持久性。
- 跨进程削峰、广播、重放或并行 Worker：队列或持久化流；按投递语义、顺序、保留期和运维成本选取。

详细矩阵、适用/禁用条件和混合拓扑见 [references/protocol-decision-matrix.md](references/protocol-decision-matrix.md)。

### 4. 定义契约

为每个外部端点和内部主题固定：

- 名称、方向、传输、编码、认证方式、幂等策略。
- 必填字段、Schema 版本、示例、错误码和兼容规则。
- 关联字段：`event_id`、`run_id`、`correlation_id`、`causation_id`、`sequence`、`tenant_id`。
- 控制语义：取消、确认、暂停、恢复、完成、失败、过期。

内部事件优先使用 CloudEvents 1.0 信封或能一一映射到它的现有信封；异步 API 与消息契约用 AsyncAPI 3.x 描述。事件类型按“过去发生的事实”命名，命令按“请求执行的动作”命名。

字段语义、SSE 帧格式、错误码、幂等、顺序和 Schema 兼容规则见 [references/event-contracts.md](references/event-contracts.md)。

### 5. 设计可靠性与缓冲

每个通道都必须给出可执行参数和状态机，而不是“失败重试”四个字。至少定义：

- 超时、心跳、空闲检测、重连退避、最大尝试次数和停止条件。
- SSE/WebSocket 的 `event_id`/序号、`Last-Event-ID` 或游标、持久化重放窗口和游标过期后的快照恢复。
- 服务端每连接发送队列的容量、高低水位、丢弃/合并策略和慢消费者处理。
- 客户端有界缓冲、去重窗口、乱序处理、快照重建和内存上限。
- 内部投递语义、幂等表、事务 Outbox、消费重试、退避、死信队列和重放流程。
- 取消与超时如何传播到模型、工具和 Worker；重复取消是否幂等。

SSE 默认必须设计重连与补偿，不能假设网络稳定。具体状态机、参数和故障测试见 [references/reliability-and-backpressure.md](references/reliability-and-backpressure.md)。

### 6. 设计认证与授权

分别回答“是谁”和“能做什么”：

- 用户认证：OIDC/OAuth 2.x、PKCE、会话或短期令牌；浏览器优先 BFF 或 HttpOnly Cookie。
- API 鉴权：TLS 上的 Bearer Token，验证签名、issuer、audience、过期时间、时钟偏移和 scope。
- 服务间认证：mTLS + 工作负载身份或客户端凭证；使用短期、限定 audience 的凭据。
- Webhook：HMAC 签名、时间戳、重放窗口和幂等键。
- SSE/WebSocket：握手期认证、令牌过期后的重连、订阅时逐频道授权、Origin 校验和连接数限制。
- 资源授权：租户、会话、任务和事件主题的细粒度策略；禁止仅凭可猜测 ID 读取。

不要把长期令牌放入 URL。不要把“已登录”当作“可订阅任意 Agent 事件”。鉴权方案、令牌生命周期和检查清单见 [references/auth-and-authorization.md](references/auth-and-authorization.md)。

### 7. 形成实施蓝图

把方案拆成可提交的工程任务，至少包含：

1. 协议与拓扑 ADR。
2. API/AsyncAPI/CloudEvents Schema。
3. 网关、流服务、事件总线和持久化表。
4. 认证中间件、授权策略、密钥配置和轮换。
5. 发布端、消费端、Outbox/Inbox、幂等和 DLQ。
6. 重连、重放、快照、取消和背压。
7. 指标、日志、Trace、告警、容量与压测。
8. 分阶段上线、回滚和兼容策略。

参考可执行结构和代码骨架见 [references/implementation-blueprint.md](references/implementation-blueprint.md)。

设计确认后，不要停在文档。按 [references/delivery-artifacts.md](references/delivery-artifacts.md) 继续生成时序图、接口契约、代码骨架和验证用例。

### 8. 验证后交付

交付前逐项验证：

- 断网、切网、代理缓冲、空闲断开后能恢复，且不重复展示副作用。
- 重复、乱序、延迟、消费者重启和 DLQ 重放有确定行为。
- 令牌过期、越权订阅、跨租户访问和无权限工具调用被拒绝并审计。
- 慢客户端不会拖垮事件生产；缓冲区满时有明确降级。
- 灰度期间新旧客户端与事件 Schema 可共存；回滚不丢状态。
- 关键指标有 SLO、告警阈值和应急开关。

输出模板见 [assets/communication-design-template.md](assets/communication-design-template.md)。机器可校验的输入格式见 [assets/communication-design.example.json](assets/communication-design.example.json)，实现较复杂时用 `scripts/validate_design.py <spec.json>` 检查关键缺口，再生成人类可读方案。

## 交付格式

最终方案按以下顺序输出，缺项时明确标为“未决”并给出阻塞原因：

1. 场景、假设和约束。
2. 端到端拓扑图与数据流。
3. 候选矩阵和选型结论。
4. 端点、主题和事件契约。
5. 可靠性、重试、缓冲、顺序和幂等。
6. 认证、授权、密钥和审计。
7. 实施阶段、组件职责和代码落点。
8. 故障演练、压测、指标、告警和发布/回滚。
9. 风险、未决项和下一验证动作。

对于小型单进程系统，保持方案轻量；但只要出现断线恢复、异步副作用、跨进程通信或权限边界，就必须给出对应的持久性、幂等和授权设计。

## 设计后实现引导

当用户要求“继续实现”“生成代码”或“落地”时，沿用以下顺序，不要重新做一遍大而全的架构讨论：

1. 先产出 1 页设计决策摘要：拓扑、协议、事件契约、投递语义、鉴权边界和未决项。
2. 生成与场景对应的 Mermaid 时序图：正常流、SSE 断线重连、令牌过期、重复投递/DLQ、取消或 HITL。
3. 根据仓库现有语言、框架和目录生成最小垂直切片，优先复用项目已有鉴权、日志、消息和测试设施。
4. 服务端至少包含认证/授权入口、流端点或 WS handler、事件持久化/重放、慢消费者策略、Outbox 和幂等消费。
5. 客户端至少包含有界缓冲、去重、游标提交、指数退避 + full jitter、快照恢复和停止条件。
6. 同步生成 OpenAPI/AsyncAPI/JSON Schema、数据库迁移或配置，以及故障矩阵中的自动化测试。
7. 运行格式化、静态检查和测试；报告实际命令与结果。无法验证的部分明确标为未验证，不要猜测已通过。

如果用户只要设计，不自动改业务代码；如果用户要求直接编码，也先用简短决策摘要锁定协议和契约，再进入实现。重大歧义（例如浏览器必须用原生 EventSource 且需要 Bearer Token）应先说明约束和推荐替代，不能默默选择不安全方案。

## 官方依据

设计时以官方规范为准，并在方案中列出实际采用的版本和链接。常用规范、适用范围与易错点见 [references/official-sources.md](references/official-sources.md)。规范可能更新；需要做新协议或安全结论时，重新核对官方页面。
