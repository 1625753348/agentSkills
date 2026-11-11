# Intent IR 与上下文状态

## 分层意图模型

不要用单个标签表示完整意图。推荐把一次输入解析成以下维度：

| 维度 | 回答的问题 | 示例 |
|---|---|---|
| Domain Intent | 属于哪个业务域 | 订单、售后、商品、账户、营销 |
| Action Intent | 要执行什么动作 | 查询、修改、创建、取消、发送 |
| Response Mode | 期望怎样返回 | 文本、表格、Excel、图片、链接 |
| Context Intent | 与现有任务的关系 | 新任务、继续、修改、取消、确认 |
| Risk Intent | 有什么风险信号 | 金额、隐私、不可逆、越权 |
| Execution Intent | 适合哪种执行方式 | RAG、SQL、Workflow、Tool、Agent |

这是“理解结果”，不是“执行权限”。`Intent IR` 可以标记“请求退款”，但不能自行声明“用户有退款权限”。

## 推荐的 Intent IR

```json
{
  "schema_version": "1.0",
  "request_id": "req_123",
  "conversation_id": "conv_456",
  "turn_id": "turn_7",
  "normalized_input": "查询本月库存低于警戒线的 SKU，生成 Excel，然后发给采购经理",
  "locale": "zh-CN",
  "domain_intents": [
    {"name": "inventory.read", "confidence": 0.96, "source": "semantic_router"},
    {"name": "inventory.analyze", "confidence": 0.93, "source": "llm_parser"},
    {"name": "report.generate", "confidence": 0.91, "source": "llm_parser"},
    {"name": "message.send", "confidence": 0.90, "source": "llm_parser"}
  ],
  "actions": [
    {
      "action_id": "A1",
      "action_type": "query",
      "target": "inventory",
      "parameters": {
        "period": "current_month",
        "condition": "below_warning_threshold"
      }
    },
    {
      "action_id": "A2",
      "action_type": "analyze",
      "target": "inventory",
      "parameters": {
        "condition": "below_warning_threshold"
      }
    },
    {
      "action_id": "A3",
      "action_type": "generate_file",
      "target": "excel",
      "parameters": {"format": "xlsx"}
    },
    {
      "action_id": "A4",
      "action_type": "send_message",
      "target": "purchasing_manager",
      "parameters": {}
    }
  ],
  "response_mode": "file",
  "context_intent": "new_task",
  "risk_signals": ["external_message", "business_data"],
  "execution_intent": "workflow",
  "slots": {},
  "dependencies": [
    {"from_action_id": "A1", "to_action_id": "A2", "type": "data_dependency"},
    {"from_action_id": "A2", "to_action_id": "A3", "type": "data_dependency"},
    {"from_action_id": "A3", "to_action_id": "A4", "type": "approval_dependency"}
  ],
  "confidence": 0.91,
  "clarification_required": false,
  "fallback_reason": null
}
```

### 字段使用规则

- `confidence` 必须标明来源和是否校准；不要把 LLM 自报的概率当成真实正确率。
- `actions` 允许为空：纯知识问答、闲聊和澄清请求不需要虚构动作。
- 槽位分为“已确认”“有默认值”“缺失”三态；缺失关键槽位时设置 `clarification_required=true`，不要用猜测值执行写操作。
- `risk_signals` 只描述事实信号，例如“包含金额”“请求外部发送”“涉及个人数据”；是否允许由 Policy Engine 决定。
- `execution_intent` 是建议执行入口，最终路由仍需 Policy Engine 和 Router 的联合决策。
- trace 中保留使用的路由版本、编码器版本、规则版本、解析器版本和校准版本。

## 复合意图与 DAG

多意图不是把所有标签拼接后随便并行执行。对每个动作建立显式依赖：

- `data_dependency`：前一个动作的输出是后一个动作的输入。
- `temporal_dependency`：后一个动作必须在前一个动作完成后执行。
- `approval_dependency`：执行前必须取得用户或人工审批。
- `resource_dependency`：多个动作竞争同一库存、额度或状态资源。

固定、可预测的多步业务流程优先编译成 `Workflow`；开放式、需要动态选工具或子任务协作的请求才交给 `Planner` / `Agent Runtime`。Router 只决定入口，不负责代替 Planner 编排所有步骤。

## 状态分离

| 状态 | 建议存储 | 作用 |
|---|---|---|
| ConversationState | Redis | 当前会话、最近消息、活动任务指针 |
| IntentState | Redis/PostgreSQL | 当前意图、槽位、上下文关系和待澄清问题 |
| TaskState | PostgreSQL | 业务任务、状态机、审批和幂等键 |
| RunState | PostgreSQL + checkpoint | Agent/Workflow 执行状态和恢复点 |
| EventLog | 持久化事件存储 | 审计、重放和指标 |

不要把“当前对话”与“系统已执行到哪里”混成一个对象。用户说“刚才那个”时，Context Resolver 应基于 `IntentState` 和 `TaskState` 解析引用，而不是重新跑一次独立分类就覆盖旧状态。

## 上下文关系

至少区分：

- `continuation`：继续之前的任务或补充槽位。
- `modification`：修改之前的约束、筛选条件、收件人或输出格式。
- `new_task`：明确开始另一个任务；旧任务保留或按策略挂起。
- `cancellation`：取消当前任务；取消应幂等。
- `confirmation`：确认待执行的计划或高风险动作。
- `clarification_answer`：回答系统上一轮的追问。
- `correction`：纠正上一轮的实体或槽位。

规则：

1. 先读取活动任务和待确认问题，再判断新输入是否真的是新意图。
2. 用户切换话题时，不让旧槽位污染新任务。
3. 用户说“算了”时，要判断是取消任务、撤销最后一个动作，还是仅仅否定当前回答。
4. 修改请求只改变被明确指定或被上下文指向的字段，其他字段保持不变。
5. 任何推断都应记录在 Intent IR 的 trace 中，便于复盘。

## 模块边界

| 模块 | 应该负责 | 不应该负责 |
|---|---|---|
| Input Normalizer | 统一格式、保留实体、纠正可逆噪声 | 猜测缺失的业务信息 |
| Rule Matcher | 高精度固定命令和确定性信号 | 处理开放式长尾语义 |
| Semantic Router | 快速筛选候选业务路由 | 决定权限或直接执行工具 |
| LLM Intent Parser | 结构化理解、槽位和多动作提议 | 覆盖系统策略或自行授权 |
| Context Resolver | 指代、省略、状态继承和话题切换 | 重新定义所有业务规则 |
| Intent IR Builder | 归一化、校验和版本化意图 | 绕过 schema 校验 |
| Policy Engine | 安全、权限、审批和可执行性 | 猜测用户真实意图 |
| Planner / Runtime | 编排、执行、恢复和异常处理 | 修改路由阈值或权限结论 |

## 实现检查

- 每个 schema 都有版本、向后兼容规则和拒绝未知字段的策略。
- 分类器、解析器、规则和上下文解析都能返回“无法确定”，不要把低置信度硬编码成某个业务意图。
- 对复合请求设置最大动作数、循环检测、重复动作检测和总预算。
- 所有有副作用的动作都有幂等键、确认绑定、超时和审计记录。
