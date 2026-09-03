# 跨境 Agent 第十章：订单 Agent Tools

## 本章目标

本章把第九章已经验证的下单、查询和取消 UseCase 暴露给 MainAgent。Tool 只转换参数和返回结果，不复制库存、金额、所有权或订单状态规则。

```text
HTTP SubmitIntent
    ↓
Orchestrator + ShoppingContext
    ↓
Session-scoped MainAgent
    ↓
Order FunctionTool
    ↓
Order UseCase
    ↓
Domain / Repository
    ↓
OrderOutput → ToolChunk → MainAgent reply
```

## 请求级 ShoppingContext

Orchestrator 在每次 Agent 执行前创建 ShoppingContextSnapshot，其中包含：

- shopping_session_id
- buyer_id
- locale
- currency

ContextVar 让当前异步任务及其内部 Tool 调用读取同一个快照，同时隔离并发任务。它不是普通全局变量，不同请求不会互相覆盖 buyer。

Agent 执行结束后，Orchestrator 使用 ContextVar.set() 返回的 reset token 恢复先前上下文。reset token 不是登录 Token；它只是精确恢复嵌套 ContextVar 状态的凭证。

`try/finally` 保证模型失败、工具异常或任务取消时也会清理上下文。

## Buyer 身份不进入 Tool Schema

三个订单 Tool 的参数中都没有 buyer_id：

```text
place_order_tool(items, shipping_address)
query_order_tool(order_id)
cancel_order_tool(order_id, reason)
```

Tool 使用 `ShoppingContext.require_current()` 取得 buyer，再构造 Application Input DTO。LLM 无法通过工具参数选择或伪造另一个 buyer。

这仍不等于完整认证。当前 HTTP 请求正文中的 buyer_id 尚未由可信身份系统验证；未来应从登录 Token 或服务端安全上下文建立 ShoppingContext。

## 薄订单 Tools

`order_tools.py` 定义三个构建函数：

- build_place_order_tool
- build_query_order_tool
- build_cancel_order_tool

每个工具只执行以下职责：

```text
LLM 结构化参数
→ Address / Application Input DTO
→ UseCase.execute()
→ OrderOutput
→ JSON ToolChunk
```

成功结果使用 dataclasses.asdict() 转为 JSON。错误结果使用 `[error]` 前缀和 ToolResultState.ERROR，让 Agent 能明确区分成功与失败。

金额已经由 MoneyOutput 同时提供 minor unit 和 major unit 字符串，Tool 与 Agent 不需要计算价格。

## MainAgent 交易规则

MainAgent prompt 现在明确区分：

- 搜索商品必须调用 product_search_tool。
- 创建订单前需要准确的商品、SKU、数量和完整地址。
- 用户明确确认后才能调用 place_order_tool。
- 总价必须来自下单工具结果。
- 查询调用 query_order_tool。
- 取消需要订单号与原因，并调用 cancel_order_tool。
- 工具返回错误时不能声称交易成功。

prompt 约束模型如何选择工具，Domain 与 UseCase 仍是最终业务规则边界。

## AgentScope 写工具权限

FunctionTool 的读写属性为：

```text
product_search_tool   read-only
place_order_tool      write
query_order_tool      read-only
cancel_order_tool     write
```

AgentScope 默认会把非只读工具停在 ASKING 状态，等待 UserConfirmResultEvent。当前 MVP 的 HTTP/Orchestrator 还没有确认事件协议，而用户确认发生在 MainAgent 对话层。

因此 `allow_business_tools()` 只为 `place_order_tool` 和 `cancel_order_tool` 添加精确 ALLOW rule。它没有全局关闭权限引擎，未来文件、Shell 或其他危险工具仍受默认确认策略保护。

规则添加是幂等的，同一个 Agent 重复配置不会产生重复 rule。

当前方案沿用原项目的对话确认思路，但 prompt 不是绝对安全边界。生产强化阶段应增加确定性的待确认操作、确认令牌或完整 UserConfirmResultEvent API。

## Composition 接线

Composition 将三个工具函数包装为 FunctionTool，并与 product_search_tool 一起注入 MainAgentFactory。每个 session 创建的新 MainAgent 都获得相同工具能力，但保持独立 AgentState。

工具和 Agent 共享 UseCase/Repository 对象，保证：

- 下单后查询能读取同一订单。
- 取消能找到下单时扣减库存的同一商品对象。
- buyer 来自当前请求上下文。

## 端到端链路

离线脚本模型在同一 session 中依次发出三个真实 ToolCall：

```text
明确确认下单
→ place_order_tool
→ 创建 GBX-000001，扣减库存

查询 GBX-000001
→ query_order_tool
→ 返回 CONFIRMED

取消 GBX-000001
→ cancel_order_tool
→ 返回 CANCELLED，恢复库存
```

最终订单归属当前 buyer，库存恢复到初始值，并且请求结束后 ShoppingContext 为 None。

## 测试与验收

全套共 152 项测试，全部通过。本章新增 10 项测试，覆盖：

- ContextVar 缺失、嵌套恢复和并发任务隔离。
- Orchestrator 只在 Agent reply 期间暴露 ShoppingContext。
- 三个 FunctionTool 的名称、Schema 与读写参数。
- Tool 下单、查询、取消完整流程。
- buyer 不进入 Tool Schema，其他 buyer 无法查询或取消订单。
- 错误地址不会扣库存。
- 缺少请求上下文时 Tool 返回错误。
- Composition、MainAgent、Tool、UseCase、Domain 和仓储的完整离线调用链。

## 当前限制

- buyer ID 仍来自未认证的 HTTP 请求正文。
- 对话确认主要由 prompt 约束，没有确定性确认令牌。
- 没有直接订单 HTTP API。
- 没有 WebSocket 工具事件和流式回复。
- 订单与库存只存在于当前进程内存。
- 尚未拆分 SearchAgent 和 TradeAgent。

## 下一章

第十一章引入子 Agent。MainAgent 保留完整业务能力，同时增加 SearchAgent、TradeAgent 和任务派发工具，只在需要专业上下文隔离或较深任务链时进行派发。
