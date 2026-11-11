# Semantic Router 1.x 落地

本文依据 2026-11-11 查阅的官方 1.x 文档整理。先确认项目锁定的是 1.x；0.x 的 `SemanticRouter`、`score_threshold`、动态函数调用和 `sync()` 不是 1.x API，不能直接照搬。

官方入口：<https://docs.aurelio.ai/docs/semantic-router/v1>

## 安装与基本模型

```bash
pip install -qU "semantic-router[fastembed]>=1,<2"
```

```python
from semantic_router import IndexedRouter, Route
from semantic_router.encoders import FastEmbedEncoder

order_status = Route(
    name="order.status",
    utterances=[
        "我的订单到哪了",
        "帮我查一下物流",
        "这个包裹什么时候到",
        "订单怎么还没发货",
    ],
    description="仅查询已有订单的状态、物流或预计送达。不处理退款、取消或改地址。",
    confidence_threshold=0.86,
    metadata={"handler": "order_status_pipeline", "risk": "low"},
)

refund_create = Route(
    name="refund.create",
    utterances=[
        "我要退款",
        "这个东西我不想要了，退钱",
        "帮我申请退货退款",
        "收到的商品坏了，怎么退",
    ],
    description="发起退款或退货申请。不查询退款进度，不处理支付争议。",
    confidence_threshold=0.94,
    metadata={"handler": "refund_pipeline", "risk": "high"},
)

router = IndexedRouter(
    encoder=FastEmbedEncoder(name="BAAI/bge-small-en-v1.5"),
    routes=[order_status, refund_create],
    confidence_threshold=0.80,
)
```

`RouteChoice` 的核心字段是 `name`、`confidence`、`calibrated`。未设置阈值时，最佳路由总会返回，即使匹配很弱；要靠 `name is None` 做 fallback，必须先设置阈值。

## 两种语义边界表达

### IndexedRouter 使用 utterances

`IndexedRouter` 只嵌入 utterances，不嵌入 description。description 可以用于存储和展示，但不能指望它改变相似度匹配。

因此：

- utterances 必须像真实用户会说的话，而不是内部业务标签。
- 每个路由通常从 5 到 20 条高质量真实表达开始，按长尾误差补充，不要一次穷举几百条。
- 近邻意图要有硬负例测试；不要只在对应路由里堆积正例。
- 商品型号、订单号、SKU 等精确 token 不能只靠 dense embedding；必要时用稀疏编码、规则抽取或确定性校验。

### DecisionRouter 使用 description

```python
from semantic_router import DecisionRouter, Route
from semantic_router.decision_models import TypeSafeDecisionModel

routes = [
    Route(
        name="billing.refund",
        description=(
            "用户要求退回已经支付的款项、发起退款或退货退款。"
            "不包含购买前的价格咨询，也不包含仅查询退款进度。"
        ),
    ),
    Route(
        name="billing.refund_status",
        description=(
            "用户只查询已提交退款的进度、到账时间或失败原因。"
            "如果用户同时要求新退款，应优先选择 billing.refund。"
        ),
    ),
]

decision_router = DecisionRouter(
    model=TypeSafeDecisionModel(),
    routes=routes,
    confidence_threshold=0.90,
)
```

DecisionRouter 的模型直接读取 description，适合表达包含/排除边界、重叠规则和指令性边界。它通常比本地向量检索慢，适合放在 `Chain` 的后段或只有低流量、高复杂度路由时使用。

## 混合路由

```python
from semantic_router import IndexedRouter
from semantic_router.encoders import BM25Encoder, FastEmbedEncoder

hybrid = IndexedRouter(
    encoder=FastEmbedEncoder(name="BAAI/bge-small-en-v1.5"),
    sparse_encoder=BM25Encoder(),
    routes=[order_status, refund_create],
    alpha=0.7,  # dense 权重；1.0 为纯 dense，0.0 为纯 sparse
    confidence_threshold=0.85,
)
```

`alpha` 没有跨业务通用的最优值。用包含商品编码、型号和专有词汇的留出集测量 top-1、误路由和安全切片，再选择权重。稀疏检索是精度增强，不是实体合法性的证明。

## Chain 与 Merge

```python
from semantic_router import Chain, DecisionRouter, IndexedRouter

fast = IndexedRouter(
    encoder=encoder,
    routes=routes,
    confidence_threshold=0.82,
)
slow = DecisionRouter(
    model=TypeSafeDecisionModel(),
    routes=routes,
)

router = Chain(routers=[fast, slow])
```

- `Chain` 先调用快速路由；快速路由达到自己的阈值就停止，否则顺延到慢路由。
- 第一个路由器必须有阈值并经过校准，否则它会“总是回答”，后面的路由器永远不会执行。
- `Merge` 并行融合多个路由器；只有所有组成路由器都校准到概率尺度时，平均值才有意义。
- 组合路由器的 routes 应保持一致，并按官方文档核对当前版本的构造和阈值行为。

## 校准、阈值和评估

### 正确顺序

1. 定义业务路由和边界。
2. 收集与 utterances 不重叠的真实或仿真留出集。
3. 为无业务路由样本标注 `None`。
4. 调用 `fit()` 校准。
5. 在测试集上选择阈值，检查召回、误路由、闲聊误拦截和风险切片。
6. 用完全独立的测试集调用 `evaluate()`。

```python
router.fit(
    X=held_out_queries,
    y=held_out_labels,  # 无业务路由使用 None
    method="platt",
)
router.confidence_threshold = 0.85
router.evaluate(X=test_queries, y=test_labels)
```

`fit()` 后 `RouteChoice.confidence` 才是概率尺度（`calibrated=True`）；未校准时它只是当前编码器的原始分数。阈值优先级为：调用级 `threshold=`、路由级 `confidence_threshold`、路由器级 `confidence_threshold`，最后才是“无阈值”。

### 不能做的事

- 不要用路由自己的 utterances 做 `fit()` 或最终评估；它们会以接近 1.0 的相似度匹配自己，导致校准失真。
- 不要在更换 encoder、重写路由、改变语言或大幅改变流量分布后沿用旧阈值。
- 不要把离线 ECE 好看当成上线充分条件；还要看高风险切片的 false execution。

## “未命中业务路由”的安全实现

```python
choice = router(query)

if choice.name is not None:
    return dispatcher.dispatch(choice.name, query, context)

if risk_gate(query, context):
    # 有订单、金额、账户、写操作、敏感数据或安全信号
    return clarify_or_human(query, context)

return chitchat_handler(query, context)
```

关键点不是把 `None` 直接命名为闲聊，而是把 `None` 当作“没有高价值业务路由命中”的信号，再由风险门控决定去向。风险门控不是另一个无限的意图分类器，而是少量高精度规则、实体检测、上下文状态和安全策略的组合。

## 1.x 常见坑

- `IndexedRouter` 不等同于 0.x 的 `SemanticRouter`。
- `score_threshold` 已改为 `confidence_threshold`，且 1.x 默认没有阈值。
- 1.x 去掉了动态路由和 `function_call`；先选路由，再由应用或 LLM 填参数并调用工具。
- `limit=1` 返回一个 `RouteChoice`，`limit=None` 或其他正整数返回列表；未过阈值时 `name` 为空。
- 路由文件不应保存 API key 或连接密钥；从环境变量读取，并在加载时检查。
- 远程索引是路由的单一事实源；使用 `add()`/`remove()` 明确管理变更，并重新校准受影响的阈值。
- 保存到 YAML/JSON 时使用当前 1.x 的 `to_yaml(path=...)`、`load_router(path=...)` 形式。
