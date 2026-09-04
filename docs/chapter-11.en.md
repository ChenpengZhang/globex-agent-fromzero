# Chapter 11: Sub-Agents and Task Dispatch

## Goal

This chapter extends the single MainAgent into a multi-Agent system without changing the existing Domain, UseCases, or business tools.

The minimum closed loop contains:

- SearchAgent for product search, filtering, comparison, and recommendation.
- TradeAgent for placing, querying, and cancelling orders.
- A MainAgent that retains every business tool and handles simple work directly.
- A `task_dispatch` tool for work that benefits from specialist context isolation or a deeper tool chain.
- A fresh specialist Agent for every dispatch so unrelated tasks do not share conversational state.

RAG, parallel orchestration, event buses, timeouts, retries, and persistence remain out of scope.

## Why Not Dispatch Every Request

A sub-Agent adds at least one extra model call. If a request only requires one product search, direct execution by MainAgent is simpler and uses less latency and fewer tokens.

The project therefore follows a “MainAgent works directly by default and dispatches only when useful” policy:

```text
Simple task
MainAgent → Business Tool → UseCase

Isolated or deeper task
MainAgent → task_dispatch → Specialist Agent → Business Tool → UseCase
```

Sub-Agents are an optional execution path, not a mandatory layer for every request.

## Sub-Agent as Tool

The Orchestrator does not receive a special sub-Agent protocol. Dispatch is exposed as an ordinary `FunctionTool`:

```text
task_dispatch(
    subagent_type="search_agent" | "trade_agent",
    demands="self-contained task"
)
```

From MainAgent's perspective, this remains a standard ReAct loop:

```text
model selects task_dispatch
→ AgentScope invokes the FunctionTool
→ the tool creates a specialist Agent
→ the specialist runs its own ReAct loop
→ its final conclusion becomes a ToolResult for MainAgent
→ MainAgent produces the user-facing response
```

This reuses the existing Toolkit, permission, and ToolResult mechanisms without adding AgentScope-specific branches to the Domain or Orchestrator.

## Specialist Factories

### SearchAgentFactory

SearchAgent can only see `product_search_tool`. It cannot place, query, or cancel orders.

Its responsibilities are to extract retrieval constraints from a self-contained task, call deterministic catalog search, and summarize verified product cards without inventing products, SKUs, prices, inventory, or shipping coverage.

### TradeAgentFactory

TradeAgent can only see the three order tools:

- `place_order_tool`
- `query_order_tool`
- `cancel_order_tool`

It cannot search for or substitute products. An order creation task must still state that the user explicitly confirmed the order.

Both factories construct Agents and their tool sets. Business rules remain in UseCases and the Domain.

## What Is Isolated and What Is Shared

Every dispatch calls the selected factory's `build()` method:

```text
dispatch A → fresh SearchAgent A → AgentState A
dispatch B → fresh SearchAgent B → AgentState B
```

The specialists therefore do not share chat history or intermediate tool results.

They do share the UseCases and repositories injected by the Composition Root:

```text
MainAgent ───────┐
SearchAgent ─────┼→ shared UseCases → shared repositories
TradeAgent ──────┘
```

Conversational isolation and shared business state can coexist. An order placed by TradeAgent remains visible when MainAgent directly invokes the query tool.

## Why demands Must Be Self-Contained

A specialist does not inherit MainAgent's conversation history. MainAgent must include everything necessary in `demands`, such as:

- Search terms, category, budget, currency, and destination country.
- Product ID, SKU ID, and quantity.
- The complete shipping address.
- Whether the user explicitly confirmed the order.
- The order ID and cancellation reason needed by query or cancellation tasks.

This is an intentional boundary. It keeps irrelevant context out of specialist work and makes dispatched tasks easier to test and audit.

## ShoppingContext Across a Specialist Call

The Orchestrator sets `ShoppingContext` at the beginning of a request and restores the previous value with its token when the request ends.

The dispatcher and TradeAgent execute inside the same asynchronous call chain, so the ContextVar remains visible:

```text
Orchestrator sets ShoppingContext
→ MainAgent.reply()
→ task_dispatch()
→ TradeAgent.reply()
→ place_order_tool()
→ ShoppingContext.require_current()
```

The model never controls `buyer_id` as a tool parameter. Order tools continue to obtain identity from trusted request context, which is cleaned after the request.

## Why task_dispatch Is Not Read-Only

The dispatcher may select SearchAgent, but it may also select TradeAgent, which can place or cancel an order.

It therefore has transitive write capability and cannot truthfully be registered as read-only. Composition registers it with `is_read_only=False`, and the project permission rules explicitly allow it. TradeAgent's place and cancel tools retain their own permission rules as well.

## Composition Root Changes

The Composition Root now:

1. Creates shared repositories and UseCases.
2. Creates the model client.
3. Creates SearchAgentFactory and TradeAgentFactory.
4. Obtains business tools from those factories for direct MainAgent use.
5. Creates `task_dispatch` so MainAgent can invoke specialists when useful.

Business-tool assembly is no longer duplicated in Composition:

```text
SearchAgentFactory.build_tools() → product search tools
TradeAgentFactory.build_tools()  → order tools
```

MainAgent and each specialist reuse the same tool definitions and UseCases.

## Tests

Chapter coverage includes:

- The `task_dispatch` FunctionTool schema.
- Correct routing to search_agent and trade_agent.
- Empty demands and unknown Agent types.
- A fresh Agent instance for each dispatch.
- MainAgent → SearchAgent → product_search_tool → MainAgent.
- Isolation of SearchAgent's raw tool results from MainAgent context.
- MainAgent → TradeAgent → place_order_tool.
- Buyer identity propagation through ShoppingContext and TradeAgent.
- Continued support for direct business-tool execution by MainAgent.
- Regression coverage for HTTP, sessions, orders, and inventory.

The complete suite after this chapter is:

```text
160 passed
```

## Current Limitations

- Dispatch selection remains an LLM prompt decision and is probabilistic.
- `task_dispatch` returns natural-language text rather than a strict structured result.
- Multiple dispatches have no explicit parallel-control or observability layer yet.
- Specialist failures do not yet have timeout, retry, or circuit-breaker behavior.
- Repositories remain process-local and in-memory.
- SearchAgent currently uses deterministic catalog retrieval without a knowledge base or tiered RAG.

Later chapters will add knowledge retrieval to SearchAgent while preserving the Agent boundaries introduced here.
