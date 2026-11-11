---
name: intent-understanding-routing
description: "Design, audit, or implement enterprise Intent Understanding & Routing Engines when building or refactoring agent, chatbot, ecommerce, or conversational AI projects. Covers calibrated semantic routing, multi-intent decomposition, Intent IR, chitchat fallback, context handling, safety boundaries, and evaluation. Use when user messages must be understood and routed to business pipelines; do not use for prompt-only persona work or ordinary RAG without routing decisions."
metadata:
  short-description: "Design calibrated intent routing and fallback"
---

# Intent Understanding & Routing Engine

## 目标

把用户输入理解为可解释、可校验、可路由的 `Intent IR`，而不是只输出一个单标签分类结果。系统必须同时回答：

1. 用户想完成什么业务目标？
2. 需要执行哪些动作，动作之间有什么依赖？
3. 当前消息是新建任务、继续、修改、取消，还是澄清？
4. 应使用哪种响应模式和执行入口？
5. 是否存在安全、权限、审批或人工接管要求？

核心边界：`Intent Engine` 理解“用户要什么”，`Policy Engine` 判断“是否允许”，`Planner` 决定“怎么做”，`Agent Runtime` / `Tool Gateway` 负责执行。不要把权限判断塞进意图分类器，也不要让 LLM 直接决定有副作用的执行。

## 典型触发场景

在新建 Agent/对话项目，或改造已有 AI 项目的意图识别、路由、工具选择和多轮状态时使用本 skill。典型输入：

> 查询本月库存低于警戒线的 SKU，并将结果整理成 Excel，最后发送给采购经理。

这句话不能只打一个“库存分析”标签，至少需要拆成：

| 子意图 | Intent IR 表达 | 执行入口 | 额外边界 |
|---|---|---|---|
| 数据查询 | `action=query`, `target=inventory` | SQL / 数据 API | 数据范围、租户、时间条件 |
| 条件分析 | `action=analyze`, `condition=below_warning_threshold` | 查询计划或分析节点 | 警戒线定义必须可追溯到主数据 |
| 文件生成 | `action=generate_file`, `target=excel` | 文件/报表服务 | 输出格式、数据脱敏、临时文件生命周期 |
| 消息发送 | `action=send_message`, `target=purchasing_manager` | Tool Gateway / Workflow | 收件人解析、外部发送、幂等 |
| 权限检查 | `risk_signals` + Policy Engine | RBAC/ABAC + 审批 | 数据范围、收件人权限、发送前确认 |

输出应是带动作依赖的 `Intent IR`：`A1 查询 -> A2 分析 -> A3 生成 Excel -> A4 发送`，其中 `A4` 需要 Policy Engine 和可能的审批；不能把它压缩成一次 LLM 调用直接执行。更多字段和 DAG 示例见 [references/intent-ir-and-state.md](references/intent-ir-and-state.md)。

## 适用场景

适用于电商客服、订单与售后、商品咨询、账户服务、内部企业助手，以及需要把对话请求路由到 `RAG`、`SQL`、`Workflow`、`Tool` 或 `Agent Runtime` 的系统。

不适用于只有角色设定、创意写作或普通知识库检索且没有路由决策的任务。遇到纯实现请求时，先读取 [references/semantic-router-v1.md](references/semantic-router-v1.md)；设计领域模型和无状态传递时读取 [references/intent-ir-and-state.md](references/intent-ir-and-state.md)；设计闲聊、兜底和稳定性时读取 [references/chitchat-fallback-and-stability.md](references/chitchat-fallback-and-stability.md)；建设指标和上线计划时读取 [references/evaluation-and-rollout.md](references/evaluation-and-rollout.md)。

## 必须遵守的路由原则

- 先做高精度、低成本的确定性规则，再做语义路由，最后才使用 LLM 解析或规划；不是每个请求都必须经过全部层级。
- 业务意图使用少量高质量、用户口吻的 utterances，并覆盖不同说法、短句、口语、方言和代码混用；不要用几百条样例试图穷举开放式输入。
- `Semantic Router` 的 `description` 只由 `DecisionRouter` 的决策模型读取。`IndexedRouter` 不嵌入 description；需要描述边界时，改用 `DecisionRouter`，或把边界转换成合法的用户口吻 utterances。
- 闲聊优先采用“排他性路由”：只定义边界清晰、误判代价高的业务路由；业务路由未命中后，经过风险门控进入闲聊或澄清，而不是维护一个无限扩张的闲聊示例集合。
- 没有命中业务路由不等于一定属于闲聊。只要输入包含订单号、金额、退款、支付、账户、执行动作或安全信号，就必须进入澄清、结构化解析、人工或安全流程。
- 所有阈值必须经过留出集校准和业务评估后再设置。未校准的相似度不是概率；不要凭感觉把 `0.8` 当成“80% 正确”。
- 高风险意图即使置信度高，也要独立执行授权、参数校验、确认或人工审批；置信度不能替代 Policy Engine。
- 复合请求先识别多个动作和依赖关系，再生成执行计划；不要为了适配单标签模型截断用户请求。

## 工作流

### 1. 冻结业务范围

先列出业务域、可执行管线、目标渠道、语言和输入形态（文本、语音转写、图片、商品链接）、峰值 QPS、P95 延迟预算、风险等级、人工接管条件、失败时允许的行为，以及可以接受的错误类型。

明确区分：

- 只读查询、写操作、资金操作、对外发送和不可逆操作。
- 必须自动完成、允许澄清、必须人工确认的路径。
- 业务失败、路由未命中、模型超时、工具失败和无权限的降级行为。

### 2. 建立分层意图模型

至少建模六个维度：`Domain Intent`、`Action Intent`、`Response Mode`、`Context Intent`、`Risk Intent`、`Execution Intent`。不要用一个六分类标签替代它们。

对每个业务域定义：

- 路由名和负责人、对应执行管线、允许的动作。
- 必须提取的槽位、可省略槽位、默认值和缺失时的追问策略。
- 正例、硬负例、边界例、歧义例和超范围例。
- 路由级风险、权限范围、审批和幂等要求。

详细 IR 字段、状态边界和多意图 DAG 见 [references/intent-ir-and-state.md](references/intent-ir-and-state.md)。

### 3. 设计级联路由

推荐按以下顺序实现，并根据场景裁剪：

1. **L0 规则层**：固定命令、取消/停止、人工转接、健康检查、明确安全拦截、严格的格式或 ID 识别。
2. **L1 Semantic Router**：对所有高价值业务意图做快速语义匹配，使用校准后的路由阈值。
3. **L2 LLM 结构化解析**：对口语化、复合、歧义、槽位复杂或规则/语义都未覆盖的请求生成受 JSON Schema 约束的 Intent IR。
4. **L3 Context Resolver**：结合会话状态解析指代、省略、追问、修改、取消和新任务。
5. **L4 Planner**：对多个动作、依赖关系或动态工具选择生成 DAG；固定业务流程优先走 Workflow。

规则层要做到高精度：宁可漏掉一部分，也不要把“在吗，我的订单呢”这类混合句错误地当成纯问候。语义路由只负责高价值业务路由，未命中的处理见下一节。

### 4. 实现闲聊与 fallback

默认采用“业务路由优先 + 风险门控 fallback”，而不是把 `chitchat` 当成一个必须穷举的顶级意图：

1. 先定义业务路由及其严格阈值。
2. 用留出集和 `None` 标签校准“无业务路由”的边界。
3. 业务路由未命中时检查风险门控：是否存在交易动作、账户/资金/隐私、订单/商品实体、执行请求、安全威胁或人工请求。
4. 无风险且无业务目标时，交给禁用工具的廉价模型处理闲聊。
5. 有业务信号但无法确定时，返回澄清或转 LLM 解析/人工，不直接猜测执行。
6. 明确的人工转接、停止、取消等请求由 L0 处理。

如果为了监控或体验保留 `chitchat` 路由，它只能作为次要策略，并要用真实长尾流量评估；不要用有限的“你好、讲个笑话”列表代表整个闲聊空间。三种高级策略的具体比较和实现见 [references/chitchat-fallback-and-stability.md](references/chitchat-fallback-and-stability.md)。

### 4.1 先区分“咨询、状态、执行”

同一个业务对象会因为语气和问法落入不同路由。实现前要把下面几类边界写进路由定义和测试集：

| 用户表达 | 正确意图 | 不应误判为 |
|---|---|---|
| 我要退款 / 帮我申请退货 | `refund.create`，高风险写操作 | 退款进度查询 |
| 退款到账了吗 / 退款审核到哪一步 | `refund.status` | 新退款申请 |
| 退款政策是什么 / 怎么申请退款 | 知识问答或 `support.howto` | 立即退款 |
| 取消订单 A123 | `order.cancel`，需要确认和鉴权 | 订单状态 |
| 订单取消了吗 | `order.status` | 取消订单 |
| 怎么取消订单 | 知识问答或 `support.howto` | 取消订单 |
| 帮我改收货地址 | `order.modify`，高风险且可能需要追问新地址 | 闲聊 |
| 订单已经收到，谢谢 | 反馈/闲聊或任务完成确认 | 重新查询物流 |
| 投诉物流 / 转人工 | 投诉或人工接管，必要时保留当前任务上下文 | 自动执行退款或查询 |
| 查订单并退款 | 多意图：查询 + 高风险退款 | 只保留其中一个标签 |

发送类动作还要区分“对象、来源、目标、授权”：`把刚才的 Excel 发给王经理` 依赖上下文中的输出对象；`把库存表发给王经理` 若没有已生成或已选定的表格，应先澄清；`请发送给采购经理` 缺少发送对象，不能直接执行。否定句如“不要发送”“别发财务”必须从动作集合中删除对应动作，而不是只降低置信度。

其他消歧规则：

- `how / 怎么 / 如何 / 政策 / 能退吗` 表示咨询或资格判断时，优先知识路由，不触发写操作。
- “订单没到”是订单状态信号，“退款没到账”是退款状态信号，不能用同一个“没到”关键词处理。
- 用户文本中的“我是管理员”“忽略规则”“跳过审批”不构成授权；权限只能来自 Policy Engine 和可信身份。
- 账号、手机号、密码、银行卡、支付凭证属于高风险账户数据，必须有独立策略，不能由闲聊或普通商品路由处理。
- 中英混写、代码混写和 ASR 转写要加入独立测试切片；不能只验证标准中文。

### 5. 选择 Semantic Router 工作模式

以 Semantic Router 1.x 为准，先确认项目锁定版本，不要混用 0.x 的 `SemanticRouter`、`score_threshold` 和同步 API。

- `IndexedRouter`：需要 utterances，适合高频、边界相对清晰的业务路由。
- `DecisionRouter`：读取 description，适合需要文字指令表达包含/排除边界、但不需要 embedding 的场景。
- `IndexedRouter` + `sparse_encoder`：混合检索，适合商品编码、型号、专有名词；`alpha` 必须用业务测试集测量。
- `Chain`：快速路由优先，未过阈值才进入更慢的决策模型或 LLM。
- `Merge`：需要第二意见时并行融合；只能融合已校准到同一尺度的置信度。

路由 API、可运行示例、阈值优先级和常见坑见 [references/semantic-router-v1.md](references/semantic-router-v1.md)。

### 6. 稳定化识别

至少覆盖以下不稳定来源：

- 输入侧：错别字、空格、标点、emoji、大小写、繁简、方言、中英混写、ASR 错字、截断和多轮省略。
- 路由侧：相似业务意图重叠、长尾表达、硬负例不足、阈值漂移、编码器更换、索引和路由版本不一致。
- 上下文侧：指代、槽位继承、任务修改、取消、用户切换话题、并发任务和旧状态污染。
- 模型侧：LLM 幻觉、结构化输出失败、过度自信、提示注入、越权工具选择。
- 工程侧：缓存陈旧、超时、重试重复执行、降级路径绕过安全、灰度期间 schema 不兼容。

稳定性不是继续堆 utterances，而是“规则 + 语义路由 + 校准 + 上下文 + 结构化解析 + 风险门控 + 评估”的组合。完整策略和反模式见 [references/chitchat-fallback-and-stability.md](references/chitchat-fallback-and-stability.md)。

### 7. 安全与权限

把安全判断独立于意图置信度：

1. 输入安全检查、提示注入检测和内容风险识别。
2. Intent IR 输出“风险信号”和“请求动作”，不输出用户权限结论。
3. Policy Engine 使用 RBAC/ABAC、租户、资源范围、金额、审批和人工接管策略做授权。
4. Tool Gateway 再做 schema、目标资源、参数边界、幂等和重复执行校验。
5. 高风险写操作默认需要显式确认；确认必须绑定当前任务、参数摘要和过期时间。

把用户输入当作数据，不要让其中的“忽略系统指令”改变路由策略。检索到的文档也不能覆盖系统策略。

### 8. 建立评估与发布闸门

离线评估至少覆盖业务路由准确率、每路由召回率、无路由拒绝率、闲聊误拦截率、歧义处理、复合意图、上下文切换、安全切片、槽位 F1、路由后任务成功率和 P95 路由延迟。评估集必须与训练/校准 utterances 分离。

在线观察路由决策、来源、置信度、是否澄清、是否执行、策略结果、工具结果、人工接管和用户反馈。阈值调整必须由混淆矩阵、成本矩阵和灰度数据驱动；不能只看整体 accuracy。详细指标、数据切片、灰度和回滚见 [references/evaluation-and-rollout.md](references/evaluation-and-rollout.md)。

## 交付要求

根据用户请求选择一种或多种交付物：

- **设计**：路由拓扑、意图目录、Intent IR、状态模型、fallback 决策表、安全边界、指标和未决项。
- **实现**：先给一页决策摘要，再按仓库现有语言和框架做最小垂直切片；接入校准、日志、策略和自动化测试。
- **评审**：先列会导致误路由、误执行、越权或无法解释的缺陷，再给修复建议；不要只评论命名和目录结构。
- **数据/实验**：给出数据切片、标注规则、阈值选择方法、误差分析和上线门槛。

交付时明确区分事实、假设和待验证项。引用 Semantic Router 行为时说明是 1.x；版本不确定时先核对官方文档，不根据旧教程猜测 API。

## 校验与模板

需要机器可读的路由设计输入时，复制 [assets/intent-routing-spec.example.json](assets/intent-routing-spec.example.json)，填写后运行：

```bash
python scripts/validate_intent_router_spec.py path/to/intent-routing-spec.json
```

需要验证识别和路由行为时，使用 [assets/intent-routing-eval-cases.json](assets/intent-routing-eval-cases.json) 作为初始回归集。让待测实现输出包含 `id`、`routes`、`actions`、`risk_level`、`requires_confirmation`、`needs_clarification` 和 `fallback` 的 JSON 或 JSONL，然后运行：

```bash
python scripts/score_intent_routing_predictions.py \
  --cases assets/intent-routing-eval-cases.json \
  --predictions path/to/predictions.json
```

评分器会分别统计路由集合、动作集合、风险、确认、澄清和 fallback 准确率，并单独列出危险错误。初始回归集覆盖复合意图、状态与执行混淆、how-to、否定、上下文引用、缺少发送来源、闲聊、安全和中英混写；它不是生产数据，不能把 100% 当作上线充分条件。

校验脚本只检查结构和明显的路由安全缺口，不替代真实流量评估。最后必须人工检查：

- 每条业务路由是否有负责人、执行管线、阈值依据和失败行为。
- 无业务路由时是否经过风险门控，而不是无条件进入闲聊。
- high/critical 风险是否独立确认、鉴权和幂等。
- 是否使用未参与 fit 的留出集评估阈值。
- 是否覆盖多意图、上下文切换、安全、超范围、错别字和中英混写。
- 是否能从 trace 还原“为什么选了这条路由、为什么没有执行”。
