# 跨境 Agent 第五章：应用编排 Orchestrator

## 本章目标

本章在 Presentation 与 Agent 之间加入稳定的应用边界。CLI 不再直接构造 AgentScope `UserMsg` 或调用 `Agent.reply()`，而是提交一个应用意图给 Orchestrator。

```text
CLI
 ↓ SubmitIntentInput
MainAgentOrchestrator
 ↓ UserMsg
MainAgent
 ↓
SubmitIntentOutput
```

## Application DTO

`SubmitIntentInput` 描述一次购物意图所需的应用数据：

- `shopping_session_id`
- `buyer_id`
- `locale`
- `currency`
- `raw_query`

它负责清理字符串、规范化币种，并拒绝缺失的 session、buyer 和 query。它属于 Application，因为它描述一个应用操作，而不是 Product 或 Order 等核心领域对象。

`SubmitIntentOutput` 提供稳定的应用响应：session ID 与最终文本。未来 HTTP、WebSocket 或其他入口可以复用相同输出，不必认识 AgentScope 的 `Msg`。

## MainAgentOrchestrator

Orchestrator 负责组织一次请求：

1. 接收 `SubmitIntentInput`。
2. 将 locale 与 currency 组成 shopping context。
3. 把用户原话转换为 AgentScope `UserMsg`。
4. 调用 MainAgent。
5. 把 Agent 回复转换成 `SubmitIntentOutput`。

Agent 负责理解、推理和工具调用；Orchestrator 负责应用流程。以后会话选择、长期记忆、缓存、事件和错误处理都会进入 Orchestrator，而不是散落在 CLI 或 HTTP 路由中。

## Shopping Context

当前 locale 与 currency 通过以下文本进入模型上下文：

```xml
<shopping-context>
locale: zh-CN
currency: CNY
</shopping-context>
```

这样当用户只说“300 以内”时，模型仍知道预算币种。session ID 不发送给模型，因为它只是系统路由标识，不参与购物判断。

后续会引入服务端 `ShoppingContext`，把身份等可信数据与模型生成参数进一步隔离。

## Presentation 解耦

CLI 现在只依赖 Application：

```text
之前：CLI → AgentScope Agent
现在：CLI → MainAgentOrchestrator → AgentScope Agent
```

因此未来增加 HTTP API 时，CLI 与 HTTP 都可以构造同一种 `SubmitIntentInput`，而不复制 Agent 调用逻辑。

## Composition Root

Composition Root 创建 MainAgent 后继续创建 Orchestrator，并把两者放入 Container。具体模块组装仍只发生在一个位置。

## 测试与验收

本章总计 23 项测试，全部通过。新增测试覆盖：

- Application DTO 的空白清理与大小写规范化。
- 空 session、buyer、query 和非法币种被拒绝。
- Orchestrator 保留 session ID。
- locale、currency 和 raw query 正确进入模型消息。
- 最终 Agent 文本被转换为 `SubmitIntentOutput`。

## 当前限制

- Container 中只有一个 MainAgent，session ID 尚未真正隔离不同会话。
- 没有 HTTP API。
- 没有 Pydantic HTTP DTO。
- 没有统一的异常到 HTTP 状态码映射。

## 下一章

下一章增加 FastAPI，并明确区分 HTTP DTO 与 Application DTO：

```text
HTTP JSON → Pydantic DTO → SubmitIntentInput → Orchestrator
```
