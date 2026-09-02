# 跨境 Agent 第七章：多会话隔离

## 本章目标

本章让 `shopping_session_id` 从普通请求字段变成真正的会话路由键。每个新 session 获得独立 MainAgent 和 AgentState，同一 session 的后续请求复用原 Agent。

```text
MainAgentFactory
    ↓
SessionRegistry
├── session-A / buyer-A → Agent A → AgentState A
├── session-B / buyer-A → Agent B → AgentState B
└── session-C / buyer-B → Agent C → AgentState C
```

## MainAgentFactory

Factory 保存模型和工具等创建依赖，并通过 `build()` 统一创建新的 Agent。SessionRegistry 不需要知道 prompt、Toolkit 或 ReAct 配置。

多个 Agent 可以共享无状态模型客户端和只读工具，但每次 `build()` 都生成新的 Agent 与 AgentState。

Factory 与 Agent 职责不同：Agent 是有状态运行实例，Factory 是无状态创建策略。

## SessionRegistry

Registry 保存 `shopping_session_id → SessionEntry` 映射。SessionEntry 包含：

- session ID
- 绑定的 buyer ID
- 独立 Agent
- 同 session 执行锁

同一 session 与 buyer 会返回同一 SessionEntry；不同 session 会调用 Factory 创建不同 Agent。

## Buyer 绑定

session 首次创建时绑定 buyer。另一个 buyer 复用相同 session 时抛出 `SessionOwnershipError`，HTTP 层映射为 409 Conflict。

这只是会话一致性保护，不是身份认证。当前 buyer ID 仍来自请求正文，可以被客户端伪造；真实系统应从可信登录 Token 中取得 buyer ID。

## 并发控制

Registry 使用 creation lock 和双重检查，防止多个并发首请求为同一 session 创建多个 Agent。

每个 SessionEntry 还有独立 execution lock，使同一 session 的多次请求串行修改 AgentState；不同 session 使用不同 lock，可以并发执行。

## Orchestrator

Orchestrator 不再持有单一 Agent，而是先根据 session 与 buyer 从 Registry 取得 SessionEntry，然后在该 session 的 execution lock 内调用 Agent。

```text
SubmitIntentInput
    ↓
SessionRegistry.get_or_create()
    ↓
SessionEntry.execution_lock
    ↓
SessionEntry.agent.reply()
```

## 延迟创建

Container 启动时 session 数量为零。只有收到新 session 请求时才创建 Agent，避免为不存在的会话预先分配状态。

## 测试与验收

本章全套共 37 项测试，全部通过。新增测试覆盖：

- 同 session、同 buyer 复用同一 Agent。
- 不同 session 获得不同 Agent 与 AgentState。
- 不同 buyer 复用 session 被拒绝。
- 20 个并发创建请求只产生一个 SessionEntry。
- 不同 session 的私有上下文不会串线。
- 同 session 的多轮问题与回复都会保留。
- HTTP 层将所有权冲突映射为 409。

## 当前限制

- Registry 只存在于当前 Python 进程。
- 服务重启后所有 session 消失。
- 多进程或多实例部署时，每个进程拥有自己的 Registry。
- 没有 session 过期和清理机制，长期运行会持续占用内存。
- buyer ID 尚未经过认证。

## 下一章

下一章开始订单业务 Domain，建立 Address、OrderLine、Order 聚合状态机和 OrderRepository 端口。会话持久化将在后面的存储章节单独实现。
