# 第 19 章：Redis 与异步任务

## 本章目标

第 19 章把“接收购物请求”和“执行 Agent”拆成两个阶段。HTTP API 现在可以先把任务放进队列并立即返回 task ID，独立 Worker 再执行耗时的模型与工具调用。Redis 同时用于减少重复 embedding 调用、保护性地复用语义相近回复，以及在 Worker 与 API 进程之间传递实时事件。

完整异步链路如下：

```text
浏览器
  ├─ POST /commerce/intents/async ──→ API ──→ Redis Stream
  │                                  ↑          │
  │                                  │ task ID  ↓
  │                                  │        Worker ──→ Orchestrator ──→ Agent
  │                                  │          │
  ├─ GET /commerce/tasks/{id} ───────┴──────────┤ Redis 中的状态
  │                                             │
  └─ WebSocket ←── API ←── Redis Pub/Sub ←──────┘ 实时事件
```

原来的同步入口 `POST /commerce/intents` 继续保留，方便单进程调试。它会直接等待 Orchestrator 完成，不经过任务队列。

## 为什么 Redis 在这里有三种用法

虽然都是同一个 Redis 服务，但不同需求需要不同的数据结构和可靠性语义。

| 需求 | Redis 机制 | 原因 |
|---|---|---|
| Embedding 与语义回复缓存 | 带 TTL 的 String，内容为 JSON | 按 key 直接读取并自动过期 |
| 幂等占位与任务状态 | 带 TTL 的 String | 支持原子的 `SET NX`，轮询读取成本低 |
| 后台任务投递 | Stream + Consumer Group | 支持 Pending、ACK、重新投递和多消费者 |
| 跨进程实时事件 | Pub/Sub Channel | 低延迟广播；允许丢失，因为状态轮询负责兜底 |

Redis 不是商品、订单、对话或买家偏好的权威数据源。这些需要长期保存的业务数据仍以 SQLite 为准。

## DDD 边界

### Domain

`app/domain/queue/ports/task_queue.py` 定义应用层使用的队列语言：

- `IntentTask`：不可变的任务信封；
- `TaskState`：`queued`、`running`、`retrying`、`done`、`failed`；
- `TaskStatus`：按 buyer 隔离、可对外查询的执行状态；
- `TaskQueue`：由 Redis Stream Adapter 实现的端口。

Domain 不导入 Redis，只表达可靠任务投递需要具备什么能力。

### Application

`EnqueueIntentUseCase` 负责提交工作流：校验 session 所有权、声明幂等占位、计算优先级、入队、入队失败时回滚占位，以及发布 `task.queued`。

`GetTaskStatusUseCase` 负责存在性与 buyer 所有权校验。客户端不能只靠猜中 task ID 就读取另一个买家的结果。

`IdempotencyStore` 是面向 Application 的协议。幂等性属于应用工作流策略，不是电商领域实体，也不应该与 Redis 绑定。

### Infrastructure

Infrastructure 提供具体技术实现：

- `RedisCache`：封装可选 Redis 访问；
- `CachedEmbeddingClient`：装饰已有 embedding 端口；
- `SemanticCache`：保存并比较安全的回复候选；
- `RedisIdempotency`：原子占位与 compare-and-delete 释放；
- `RedisStreamTaskQueue`：可靠任务投递；
- `RedisEventBackplane`：跨进程事件传输；
- `InMemoryTradeEventBus`：继续负责进程内 session 广播，并可把事件同步到 backplane。

### Presentation 与进程入口

FastAPI 暴露异步提交、状态轮询、同步兼容、历史和 WebSocket 接口。`app/worker.py` 是独立 Worker 入口。API 与 Worker 会组装相同依赖，但只有 API 订阅 Redis Pub/Sub；Worker 在执行任务时发布事件。

## Embedding 缓存

`CachedEmbeddingClient` 是已有 `EmbeddingClient` 外面的一层装饰器：

```text
调用方 → CachedEmbeddingClient → Redis 命中 → vector
                              └→ 未命中 → 线上 embedding API → Redis → vector
```

Key 包含 embedding 模型名以及“模型名 + 输入文本”的 SHA-256 摘要，避免不同模型生成的向量共用缓存。向量以 JSON 数组写入 Redis String，七天后自动过期。

Redis 出错会被视作缓存未命中。真正的向量生成是否成功，仍由被包装的 embedding client 决定。

## 语义回复缓存

Semantic Cache 可以在新的首轮问题与旧问题足够相似时，复用之前的最终回复。每个 buyer 范围的 bucket 最多保存 30 条，TTL 为 24 小时。每条包含标准化 query、最终 reply 和 vector。

缓存 namespace 同时包含：

- buyer 身份；
- 相关买家偏好的 fingerprint；
- chat model；
- embedding model；
- MainAgent 源码 fingerprint。

这样既不会把甲买家的回复给乙买家，也会在相关模型、提示词或偏好变化后自然切换到新的缓存空间。

缓存会主动拒绝有状态或有副作用的请求，包括下单、支付、取消、依赖代词的追问、记住与撤回偏好。只要 session 已经有历史，也不会读取或写入 Semantic Cache。命中时会发布 `cache.hit`，随后仍发布普通的最终结果事件。

Semantic Cache 采用 fail-open：失败只影响性能，不阻塞 Agent。

## 幂等提交

浏览器为每次用户主动操作生成一个新的 `idempotency_key`；如果同一个 HTTP 操作因为网络问题重试，就复用这个 key。服务端把它与 buyer 身份组合，再哈希成 Redis key。重复请求返回时会采用获胜任务中保存的 shopping session，而不是这次请求临时生成的新 session ID。

占位使用：

```text
SET key task-id NX EX 300
```

只有第一个调用者能获得该 key。并发请求或网络重试会拿到已经获胜的 task ID，不会生成重复任务。如果 Stream 事务失败，Lua compare-and-delete 脚本只会在占位值仍属于当前 task ID 时删除它，避免误删别人的新占位。

客户端不传 `idempotency_key` 时，服务端会根据标准化请求内容生成确定性兜底值。但显式 key 更好，因为它可以区分“用户真的连续问了两次相同问题”和“一次请求被网络重试”。

异步入口的幂等判断采用 fail-closed：Redis 无法判断占位归属时返回 `503`，不会冒险重复创建任务。

## 原子入队与任务状态

`RedisStreamTaskQueue.enqueue` 使用同一个 Redis transaction：

1. 把序列化后的 `IntentTask` 追加到 Stream；
2. 创建带一小时 TTL 的 `queued` 状态。

在普通 Redis 事务语义下，这可以避免“已经有 task 状态但没有真正入队”，或者“任务已经入队但查不到状态”。

状态流转为：

```text
queued → running → done
            │
            └→ retrying → running → ... → failed
```

API 返回 `202 Accepted`，内容包含 `shopping_session_id`、`task_id` 和当前状态。`GET /commerce/tasks/{task_id}?buyer_id=...` 返回状态、最终文本、错误和近似队列位置。状态一小时后过期，此时查询返回 `404`。

## Redis Stream、ACK 与恢复

项目使用两条 Stream：

- `globex:intents`：普通任务；
- `globex:intents:large`：长对话任务。

Worker 优先读取普通 Stream。开启优先级路由后，已有历史达到 `QUEUE_LARGE_REQUEST_TURNS` 的 session 会进入 large Stream，降低长上下文任务阻塞短请求的概率。

所有 Worker 加入 `globex-workers` Consumer Group。只有 Orchestrator 成功并写入 `done` 状态后，消息才会 ACK。如果 Worker 已经收到消息，但在 ACK 前停止，Redis 会把该消息留在 Consumer Group 的 Pending Entries List 中。

`XAUTOCLAIM` 会取回空闲至少一分钟的 Pending 消息。Adapter 为两条 Stream 分别保存扫描 cursor，因此大量 Pending 数据也能逐步向后扫描，而不是一直检查开头。

Agent 执行抛出异常时：

- 未达到最大投递次数：状态变成 `retrying`，消息继续留在 Pending；
- 达到 `QUEUE_MAX_DELIVERIES`：状态变成 `failed`，消息复制到 `globex:intents:dead`，然后 ACK 原消息。

无法解析的消息直接进入死信 Stream。死信会保存来源 Stream、来源 message ID、原始 payload 和失败原因。

这里实现的是 at-least-once，而不是 exactly-once。Worker 崩溃后，同一任务可能重新执行。因此订单这类业务副作用仍需要自己的持久化业务幂等机制，才能放心地扩大多 Worker 并发；这属于后续生产强化。

## Worker 生命周期

`process_task` 依次写入 `running`、发布 `task.started`、重建 `SubmitIntentInput`、调用已有 Orchestrator，最后写入 `done` 和最终文本。异常会继续向外抛，因为重试与死信策略应该由 Queue Adapter 统一负责，而不是散落在 Worker 函数里。

Worker 的 consumer name 由 hostname、进程 ID 和随机后缀组成。收到 `SIGINT` 或 `SIGTERM` 后，它停止读取新任务，等待当前任务结束，再关闭基础设施资源。

## 跨进程事件

原来的 EventBus 只存在于内存中。API 与 Worker 拆成两个进程后，Worker 内发布的事件不会自动出现在连接 API 的 WebSocket 上。

`RedisEventBackplane` 把事件信封发布到 `globex:events:{shopping_session_id}`。每个进程实例都有 origin ID。API 订阅 `globex:events:*`，忽略自己同步到 Redis 的事件，把远程 payload 恢复为类型化 `TradeEvent`，然后只做本地投递而不再次发布。这样可以避免事件循环和浏览器重复收到同一事件。

Pub/Sub 有意采用非持久语义。浏览器断线时可能错过 token 或 trace，但任务状态轮询负责最终完成结果，所以即使 WebSocket 较晚重连，前端仍能拿到 `final_text`。

## 前端流程

React 客户端现在会：

1. 使用新的 idempotency key 调用异步入口；
2. 立即取得 task ID；
3. 保持 WebSocket，接收 token 和执行事件；
4. 每 500 ms 轮询任务，直到 `done` 或 `failed`；
5. 如果 WebSocket 与轮询都返回最终文本，进行去重。

时间线新增 `task.queued`、`task.started` 和 `cache.hit`。收到一次 error event 不再立即结束等待，因为本次投递可能还会重试；是否终止由最终任务状态决定。

## 配置与启动

先启动本地 Redis，然后配置：

```dotenv
REDIS_URL=redis://localhost:6379/0
QUEUE_ENABLED=1
WORKER_CONCURRENCY=1
QUEUE_MAX_DELIVERIES=3
QUEUE_PRIORITY_ENABLED=1
QUEUE_LARGE_REQUEST_TURNS=30
SEMANTIC_CACHE_ENABLED=1
SEMANTIC_CACHE_THRESHOLD=0.95
```

分别启动 API 与 Worker：

```bash
uv run uvicorn app.presentation.server:build_app --factory
uv run python -m app.worker
```

前端仍按之前方式启动。`QUEUE_ENABLED=0` 时，同步入口仍可用，但异步入口会返回 `503`，第 19 章版本的前端也无法提交任务。

## 失败策略

- Embedding 与 Semantic Cache 是性能能力，采用 fail-open；
- 任务提交与幂等判断涉及重复执行风险，采用 fail-closed；
- Queue 读取失败会记录日志并重试；
- Pub/Sub 订阅遇到临时异常会重新连接；
- Pub/Sub 丢失事件可以接受，因为任务轮询才是完成状态的权威来源；
- 长期业务数据与买家记忆仍保存在 SQLite。

## 测试

测试覆盖缓存命中/未命中/损坏数据、embedding 批处理、语义安全规则与隔离、幂等竞争和条件释放、Stream 建立与原子入队、优先级选择、状态流转、队列深度、ACK、Pending 重试、`XAUTOCLAIM` cursor 恢复、死信、Worker 执行、异步 HTTP 所有权与异常映射、本地/远程事件投递，以及前端类型检查与构建。

本章结束时，正式 `tests/` 目录共有 450 项后端测试通过，TypeScript/Vite 生产构建也通过。

## 已知限制

- Semantic bucket 使用 read-modify-write，并发写入时可能丢掉某个缓存候选；这只影响命中率，不影响业务正确性。
- 更新 bucket 会刷新整个 bucket 的 TTL。
- 语义回复在 24 小时 TTL 内可能变旧；模型、提示词、偏好和 buyer 隔离降低了错误复用风险，但不能完全消除时效问题。
- Redis task status 属于会过期的运行数据；持久对话回复仍进入 SQLite。
- Pub/Sub 不会补发断线期间的事件。
- 复制死信与 ACK 原消息是两个 Redis 操作；两者之间崩溃可能产生重复死信，但不会直接丢掉仍 Pending 的原消息。
- At-least-once 任务投递不能自动保证外部业务副作用 exactly-once。
- 多个 Worker 进程可能并行处理同一 session 的不同任务；分布式 session 串行化留给生产强化。本学习项目的安全默认值是单 Worker、并发数 1。
- 普通 Stream 持续繁忙时，长对话任务可能被延后；等真实负载数据出现后，再在生产强化阶段设计公平调度。

## 下一步

第 20 章可以集中处理生产强化：持久化业务幂等、分布式 session 协调、鉴权、Tracing、限流、韧性策略、评测、部署与运维。第 21 章继续保留为理解完全部行为后的最终结构整理。
