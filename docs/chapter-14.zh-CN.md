# 第十四章：实时事件

## 本章目标

本章让 Agent 在最终 HTTP 回复准备完成之前就可以被观察，建立一条小型的进程内事件链：

```text
AgentScope reply_stream
→ MainAgentOrchestrator
→ 类型化 TradeEvent
→ InMemoryTradeEventBus
→ 订阅者 Queue
→ WebSocket
→ 客户端
```

本章明确不引入后台任务、Redis、持久化、事件回放、断线恢复和前端渲染。现有同步 HTTP 契约仍然返回最终文本。

## 事件契约

`TradeEvent` 是 Application 层的运行观测契约，不是 Order 领域事件。它描述 Agent 正在做什么，但不改变 Product 或 Order 状态。

每个事件包含：

```text
shopping_session_id  路由与隔离键
type                 类型化事件名
payload              事件专属 JSON 数据
occurred_at          UTC 时间戳
```

`TradeEventType` 定义了调度、工具、token、最终结果和错误等名称。本章已实际发布 `token.delta`、`final.result` 和 `error`；其余名称为后续 UI 观测保留稳定语汇。

`EventPublisher` 是 Application 协议。Orchestrator 依赖这个端口，而不依赖 FastAPI、WebSocket 或具体内存总线。

## 内存发布订阅

`InMemoryTradeEventBus` 按 `shopping_session_id` 路由事件。每个订阅者都拥有自己的 `asyncio.Queue`：

```text
session-001
├── 浏览器 A → Queue A
└── 浏览器 B → Queue B
```

发布一个事件时，同一个不可变 `TradeEvent` 引用会被放入两个 Queue。如果共用一个 Queue，就会变成竞争消费：A 和 B 分瓜事件，而不是都看到完整事件流。

Queue 为空时，`queue.get()` 只挂起当前等待协程。`put_nowait()` 让 Agent 无需等待网络发送完成就能继续。退订会删除断开的消费者，并在 session 没有订阅者时删除空记录。

当前 MVP 故意使用无界 Queue，背压和慢消费者策略属于生产化问题。

## AgentScope 事件映射

Orchestrator 现在消费：

```python
agent.reply_stream(..., yield_final_msg=True)
```

它把 AgentScope `TextBlockDeltaEvent` 映射为项目稳定的 `token.delta` 契约，最终 `Msg` 则提供权威的完整文本。

这个边界不让前端依赖 AgentScope 类和事件格式。未来更换 Agent 框架时，只需改映射器，不需改所有外部客户端。

真实 OpenAI-compatible ChatModel 使用 `stream=True`，文本块可在生成过程中立即被观察。离线模型可能将整段答案作为一个 delta，但仍走同一条事件管线。

成功时 Orchestrator 发布 `final.result`；失败时发布 `error` 并继续抛出异常，保证观测不改变应用错误语义。`ShoppingContext` 仍在 `finally` 中恢复。

## WebSocket 边界

客户端连接：

```text
WS /commerce/events
```

服务端接受 WebSocket 升级后，客户端发送：

```json
{"shopping_session_id": "session-001"}
```

`ConnectionManager` 订阅该 session，并通过 `send_json()` 转发 Queue 中的每个事件。连接结束时，`finally` 保证 Queue 一定被退订。

由于当前总线不回放历史，客户端必须先建立订阅，再使用同一 session ID 提交 HTTP intent：

```text
选择 session ID
→ 连接 WebSocket
→ 发送订阅消息
→ 用同一 ID POST /commerce/intents
```

当前订阅 ID 只是路由键，不是鉴权凭据。事件流授权属于后续生产安全工作。

## HTTP 为什么仍返回最终文本

两条输出承担不同职责：

```text
SubmitIntentOutput.final_text  Application/HTTP/CLI 直接返回值
final.result event             可选的实时观测通知
```

内存事件可能没有订阅者，也可能因断线丢失。保留直接返回能继续支持既有 API、测试和 CLI，也避免提前引入 task ID、持久队列和事件回放。

客户端应把 WebSocket `final.result` 和 HTTP `final_text` 视为同一轮结果，不能把两者追加成两条 Agent 消息。

## DDD 边界

```text
Application
├── TradeEvent / TradeEventType
├── EventPublisher port
└── Orchestrator 事件映射

Infrastructure
└── InMemoryTradeEventBus

Presentation
├── ConnectionManager
└── FastAPI WebSocket 路由
```

Domain 聚合不知道流式输出、订阅者、网络连接或 AgentScope 事件。Composition 创建唯一的共享 Bus，同时供发布端和订阅端使用。

## 测试

本章离线测试覆盖：

- 类型化事件序列化与 UTC 时间戳；
- 不同 shopping session 之间的隔离；
- 同一 session 的多订阅者广播；
- 退订清理；
- AgentScope delta 到 TradeEvent 的映射；
- `token.delta` 后跟 `final.result` 的顺序；
- HTTP 触发 Agent 时 WebSocket 订阅能收到事件；
- WebSocket 断开后订阅者被移除；
- 前十三章全量回归。

完成本章后，全套测试为：

```text
211 passed
```

## 当前限制

- 事件只存在于一个 Python 进程内。
- 订阅前发布的事件不会回放。
- 应用重启会丢失所有事件和订阅。
- 无界 Queue 没有慢消费者策略。
- 没有确认、重试、跨进程顺序或持久历史。
- 订阅握手没有显式的 ready 确认。
- session ID 订阅尚未鉴权。
- 工具和子 Agent 事件名已存在，但尚未连接结构化发布者。

这些限制被明确记录，使后续持久化、Redis、异步任务和生产强化可以替换传输细节，而不改变事件契约。
