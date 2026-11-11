# 官方依据与版本说明

核对日期：2026-11-11。Semantic Router 的 1.x 与 0.x API 差异很大；实现前以项目锁定的版本和官方页面为准。

## Semantic Router 1.x

- 总入口：<https://docs.aurelio.ai/docs/semantic-router/v1>
- Introduction：<https://docs.aurelio.ai/docs/semantic-router/v1/get-started/introduction>
- Quickstart：<https://docs.aurelio.ai/docs/semantic-router/v1/get-started/quickstart>
- Routes：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/components/routes>
- Routers：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/components/routers>
- Calibration：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/features/calibration>
- Chain 与 Merge：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/features/composition>
- Decision models：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/features/decision-models>
- Save/load：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/guides/save-load-from-file>
- Migration：<https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/guides/migration-to-v1>

## 本项目采用的关键事实

- 1.x 使用 `IndexedRouter`、`DecisionRouter`、`Chain` 和 `Merge`；0.x 的 `SemanticRouter` 和 `score_threshold` 不能混用。
- `IndexedRouter` 嵌入 utterances；`DecisionRouter` 读取 description。
- 1.x 默认没有阈值，未命中要依赖校准后的显式阈值。
- `fit()` 使用留出集做概率校准；不可以使用路由自己的 utterances。
- 阈值可以设置在调用、路由和路由器级别；精确优先级以当前官方文档为准。
- 混合检索通过给 `IndexedRouter` 传入 `sparse_encoder` 和 `alpha` 实现。
- `Chain` 适合快速优先、慢速兜底；`Merge` 适合并行融合，但必须先统一校准尺度。
- 1.x 去掉了动态路由与 `function_call`；路由只选入口，工具参数和执行由应用侧完成。

## 用户提供的设计文档

用户提供的《企业级 AI Agent Intent Engine 设计与实现方案》作为业务架构输入，其中采用的模块边界、Intent IR、L0-L4 级联、Policy Engine、状态拆分和分阶段落地已被吸收到本 skill。该文档不是 Semantic Router 官方规范；涉及库 API 时必须用上面的官方 1.x 页面复核。
