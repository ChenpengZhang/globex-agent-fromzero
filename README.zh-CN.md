# Globex Agent From Zero

[English](README.md) | 简体中文

这是一个从最小 MVP 开始、逐章重建完整跨境电商 Agent 的学习项目。

项目参考同级目录中的完整 `globex-agent`，但不会把它作为运行时依赖导入。每项能力都会独立重建，先理解它的用途、DDD 边界、测试和取舍，再引入下一层机制。

## 项目目标

- 在不直接面对生产级代码量的情况下学习 Agent 开发。
- 保持原项目的 DDD 架构和核心设计意图。
- 保证每一章都可以运行、测试和解释。
- 不把确定性业务规则交给 LLM。
- 从单 Agent 逐步发展到完整的全栈、生产化系统。

## 设计原则

- Domain 不依赖 AgentScope、FastAPI、数据库或缓存。
- Application UseCase 负责协调业务流程和领域聚合。
- Agent Tool 是 UseCase 的薄适配层，不承载业务规则。
- Infrastructure 实现内层定义的可替换端口。
- Composition Root 是唯一知道所有具体实现并负责接线的位置。
- 价格、库存、所有权和订单状态由确定性代码校验。
- 每章补充自动化测试，并分别记录中英文文档。

## 与参考项目的关系

```text
globex-agent/            完整参考实现
globex-agent-fromzero/   渐进式学习实现
```

参考项目用于核对架构方向。from-zero 项目保持独立，并允许先使用简化实现，直到后续章节再引入对应的生产机制。

## 当前架构

```text
app/
├── domain/          业务对象、不变量、状态机、端口
├── application/     UseCase、Application DTO、Agent、Tool
├── infrastructure/  LLM 与持久化适配器
├── presentation/    CLI 与 HTTP 边界
└── composition.py   依赖组装
```

当前商品查询链路：

```text
CLI / HTTP
    ↓
MainAgentOrchestrator
    ↓
SessionRegistry
    ↓
会话独享的 MainAgent
    ↓
Product Search FunctionTool
    ↓
CatalogSearchUseCase
    ↓
ProductRepository
    ↓
InMemoryProductRepository
```

当前订单侧：

```text
Order 聚合
└── Order（聚合根与状态机）
    ├── Address（收货地址快照）
    └── OrderLine × N（商品与价格快照）
        └── Money（金额运算）

OrderRepository（Domain 端口）
    ↓
InMemoryOrderRepository + Application DTO
    ↓
下单 / 查询 / 取消订单 UseCase
```

## 当前能力

- 最小单 Agent 和真实 ChatModel 接入。
- Product、SKU、Money 与仓储抽象。
- 确定性关键词和中文二元切分检索。
- Product Search FunctionTool 与 ReAct 集成。
- Application Orchestrator 和 DTO 边界。
- FastAPI HTTP 边界。
- 基于 session 的 AgentState 隔离与 buyer 绑定。
- Address、OrderLine、Order 状态机和 OrderRepository 端口。
- 包含库存补偿的确定性下单、查询和取消流程。
- 请求级 ShoppingContext 和订单 Agent Tools。
- SearchAgent、TradeAgent 和上下文隔离的任务派发。
- Domain、UseCase、Tool、HTTP 和会话的离线测试。

当前共有 160 项测试通过。

## 启动方式

项目使用 Python、uv、AgentScope 和 FastAPI。

配置 OpenAI 兼容模型服务：

```bash
export LLM_BASE_URL=<OpenAI-compatible endpoint>
export LLM_API_KEY=<api key>
export LLM_MODEL=<model name>
```

启动 CLI：

```bash
uv run python -m app.presentation.cli
```

启动 HTTP API：

```bash
uv run uvicorn app.presentation.server:build_app --factory
```

运行测试：

```bash
uv run pytest
```

不要提交真实 API Key 或其他敏感信息。

## 路线图

| 章节 | 状态 | 范围 |
|---|---|---|
| 1. 最小单 Agent | 已完成 | Settings、ChatModel、MainAgent、CLI、Composition |
| 2. 商品 Domain | 已完成 | Money、SKU、Product、仓储端口和种子数据 |
| 3. 确定性检索 | 已完成 | 搜索规格和关键词检索 UseCase |
| 4. Agent Tool | 已完成 | FunctionTool、Toolkit、ReAct、离线 Fake Model |
| 5. Application 边界 | 已完成 | Orchestrator 和 Application DTO |
| 6. HTTP API | 已完成 | FastAPI DTO、应用工厂、错误边界 |
| 7. 多会话隔离 | 已完成 | Agent Factory、SessionRegistry、buyer 绑定和并发锁 |
| 8. 订单 Domain | 已完成 | Address、OrderLine、Order 状态机和仓储端口 |
| 9. 订单交易闭环 | 已完成 | 库存补偿、仓储适配器和订单 UseCase |
| 10. 订单 Agent Tools | 已完成 | 交易工具和 Agent 端到端集成 |
| 11. 子 Agent | 已完成 | SearchAgent、TradeAgent、任务派发和隔离 |
| 12–13. RAG 与分级检索 | 当前章节 | 知识检索、Embedding、Rerank 和降级链 |
| 14. 实时事件 | 计划中 | 类型化事件、流式回复和 WebSocket 推送 |
| 15. 前端 | 计划中 | React 对话、商品/订单卡和事件时间线 |
| 16. 持久化与记忆 | 计划中 | SQLite、会话恢复、对话和偏好 |
| 17. Redis 与异步化 | 计划中 | 缓存、幂等、队列和跨进程事件 |
| 18. 生产强化 | 计划中 | 韧性、Tracing、鉴权、评测和部署 |

固定简化路线：

```text
订单交易闭环
→ 订单 Agent Tools
→ 子 Agent
→ RAG 与分级检索
→ WebSocket 实时事件
→ React 前端
→ 持久化与长期记忆
→ Redis 缓存、幂等与队列
→ 生产强化、评测与部署
```

## 章节文档

每个完成章节分别提供中文和英文设计记录：

```text
docs/chapter-XX.zh-CN.md
docs/chapter-XX.en.md
```

文档记录本章目标、设计决策、边界、测试、限制和下一步方向。
