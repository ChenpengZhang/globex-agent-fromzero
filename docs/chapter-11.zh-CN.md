# 第十一章：子 Agent 与任务派发

## 本章目标

在不改变既有 Domain、UseCase 和业务工具的前提下，把单一 MainAgent 扩展为一个可以按需派发专家的多 Agent 系统。

本章只实现最小闭环：

- SearchAgent 专门处理商品搜索、筛选、比较和推荐。
- TradeAgent 专门处理创建、查询和取消订单。
- MainAgent 继续持有全部业务工具，可以直接完成简单任务。
- `task_dispatch` 把复杂或需要上下文隔离的任务交给专家。
- 每次派发创建新的子 Agent，避免不同子任务共享对话状态。

本章不引入 RAG、并行编排、事件总线、超时、重试或持久化。

## 为什么不把所有请求都交给子 Agent

子 Agent 会额外增加至少一次模型调用。如果一次商品搜索只需要调用一个工具，MainAgent 直接处理更简单，也更节省延迟和 token。

因此系统采用“MainAgent 可以单干，必要时才派发”的策略：

```text
简单任务
MainAgent → Business Tool → UseCase

需要隔离或较深调用链的任务
MainAgent → task_dispatch → Specialist Agent → Business Tool → UseCase
```

子 Agent 是可选的执行路径，不是所有请求都必须经过的新层级。

## Sub-Agent as Tool

当前实现没有给 Orchestrator 增加特殊的子 Agent 协议，而是把派发能力包装为普通 `FunctionTool`：

```text
task_dispatch(
    subagent_type="search_agent" | "trade_agent",
    demands="自包含任务"
)
```

从 MainAgent 的角度看，它仍然在执行标准 ReAct 循环：

```text
模型选择 task_dispatch
→ AgentScope 调用 FunctionTool
→ FunctionTool 创建子 Agent
→ 子 Agent 完成自己的 ReAct 循环
→ 最终结论作为 ToolResult 返回 MainAgent
→ MainAgent 面向用户组织回复
```

这样可以复用现有 Toolkit、权限和 ToolResult 机制，不需要在 Domain 或 Orchestrator 中加入 AgentScope 特有的分支。

## 两类专家 Factory

### SearchAgentFactory

SearchAgent 只能看到 `product_search_tool`。它不能创建、查询或取消订单。

它负责：

- 从自包含任务中提取检索条件。
- 调用确定性的商品搜索工具。
- 根据真实商品卡形成检索结论。
- 不编造商品、SKU、价格、库存或配送范围。

### TradeAgentFactory

TradeAgent 只能看到订单侧三个工具：

- `place_order_tool`
- `query_order_tool`
- `cancel_order_tool`

它不能搜索或自行替换商品。创建订单时仍必须收到“用户已经明确确认”的信号。

两个 Factory 都只负责构建 Agent 和它的工具集合。业务规则仍然位于 UseCase 与 Domain 中。

## 隔离什么，共享什么

每次派发都会调用 Factory 的 `build()`：

```text
dispatch A → fresh SearchAgent A → AgentState A
dispatch B → fresh SearchAgent B → AgentState B
```

因此两个子任务不会共享聊天记录或中间工具结果。

但是它们共享 Composition Root 注入的 UseCase 与 Repository：

```text
MainAgent ───────┐
SearchAgent ─────┼→ shared UseCases → shared repositories
TradeAgent ──────┘
```

所以“Agent 对话状态隔离”和“业务状态共享”可以同时成立。TradeAgent 创建的订单，MainAgent 直接调用查询工具时仍然能够读取。

## demands 为什么必须自包含

子 Agent 不会继承 MainAgent 的聊天历史。MainAgent 必须把完成任务需要的信息全部写入 `demands`，例如：

- 检索词、品类、预算、币种和配送国家。
- product_id、sku_id 和数量。
- 完整收货地址。
- 用户是否已经明确确认下单。
- 查询或取消所需的订单号与取消原因。

这是有意设计的边界。它减少无关上下文进入子任务，也使派发任务更容易测试和审计。

## ShoppingContext 如何穿过子 Agent

Orchestrator 在一次请求开始时设置 `ShoppingContext`，在请求结束时用 token 恢复之前的值。

`task_dispatch` 和 TradeAgent 都在这次异步调用链内运行，所以 ContextVar 会继续可见：

```text
Orchestrator sets ShoppingContext
→ MainAgent.reply()
→ task_dispatch()
→ TradeAgent.reply()
→ place_order_tool()
→ ShoppingContext.require_current()
```

因此 `buyer_id` 不需要放进模型可控制的工具参数。下单工具仍然从可信请求上下文获取身份，请求完成后上下文也会被正确清理。

## 为什么 task_dispatch 不是只读工具

`task_dispatch` 可能派发 SearchAgent，也可能派发 TradeAgent。后者可以创建或取消订单。

因此，即使派发器本身只是在调用另一个 Agent，它也具有传递性的写能力，不能声明为只读。Composition 将它注册为 `is_read_only=False`，权限规则则显式允许当前项目中的该工具执行。

TradeAgent 内部的 `place_order_tool` 和 `cancel_order_tool` 仍然保留各自的权限配置。

## Composition Root 的变化

Composition Root 现在负责：

1. 创建共享 Repository 与 UseCase。
2. 创建一个模型客户端。
3. 创建 SearchAgentFactory 和 TradeAgentFactory。
4. 从两个 Factory 获取业务工具，供 MainAgent 直接使用。
5. 创建 `task_dispatch`，让 MainAgent 可以按需派发专家。

业务工具的组装来源不再在 Composition 中重复：

```text
SearchAgentFactory.build_tools() → product search tools
TradeAgentFactory.build_tools()  → order tools
```

MainAgent 和对应子 Agent 复用相同的工具定义与 UseCase。

## 测试

本章新增或更新的测试覆盖：

- `task_dispatch` 的 FunctionTool schema。
- search_agent 与 trade_agent 的正确路由。
- 空 demands 与非法 Agent 类型。
- 每次派发创建独立 Agent 实例。
- MainAgent → SearchAgent → product_search_tool → MainAgent 完整链路。
- SearchAgent 的原始工具结果不会直接污染 MainAgent 上下文。
- MainAgent → TradeAgent → place_order_tool 完整链路。
- ShoppingContext 中的 buyer 身份可以穿过子 Agent。
- 原有 MainAgent 直接调用业务工具的路径继续工作。
- HTTP、Session、订单与库存功能没有回归。

完成本章后，全套测试为：

```text
160 passed
```

## 当前限制

- 是否派发仍由 LLM 根据提示词判断，具有概率性。
- `task_dispatch` 返回自然语言文本，还没有严格的结构化输出协议。
- 多个派发任务尚未实现显式的并行控制与观测。
- 子 Agent 调用失败尚未加入超时、重试和熔断。
- 所有 Repository 仍是进程内存实现。
- SearchAgent 目前只有确定性目录检索，还没有知识库和分级 RAG。

后续章节将在保持这些 Agent 边界不变的基础上，为 SearchAgent 增加知识检索能力。
