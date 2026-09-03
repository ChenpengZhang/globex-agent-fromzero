# Chapter 10: Order Agent Tools

## Goal

This chapter exposes the place, query, and cancel UseCases validated in Chapter 9 to MainAgent. Tools convert parameters and results without duplicating inventory, money, ownership, or order-state rules.

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

## Request-Scoped ShoppingContext

Before each Agent execution, Orchestrator creates a ShoppingContextSnapshot containing:

- shopping_session_id
- buyer_id
- locale
- currency

ContextVar lets the current asynchronous task and its Tool calls read one snapshot while isolating concurrent tasks. It is not an ordinary global variable, so buyers from different requests do not overwrite one another.

After Agent execution, Orchestrator uses the reset token returned by ContextVar.set() to restore the previous context. This reset token is not an authentication token; it is an opaque handle for restoring nested ContextVar state accurately.

A `try/finally` block guarantees cleanup after model failures, tool errors, or task cancellation.

## Buyer Identity Is Not a Tool Argument

None of the three order Tools exposes buyer_id:

```text
place_order_tool(items, shipping_address)
query_order_tool(order_id)
cancel_order_tool(order_id, reason)
```

Each Tool calls `ShoppingContext.require_current()` and uses that buyer when constructing an Application Input DTO. The LLM cannot choose or forge another buyer through tool arguments.

This is still not complete authentication. Buyer ID currently comes from an untrusted HTTP body. A future version must establish ShoppingContext from a verified login token or server-side security context.

## Thin Order Tools

`order_tools.py` defines three builders:

- build_place_order_tool
- build_query_order_tool
- build_cancel_order_tool

Each Tool performs only this adaptation:

```text
Structured LLM arguments
→ Address / Application Input DTO
→ UseCase.execute()
→ OrderOutput
→ JSON ToolChunk
```

Successful output is converted to JSON with `dataclasses.asdict()`. Errors use an `[error]` prefix and ToolResultState.ERROR so the Agent can distinguish failure from success.

MoneyOutput already provides both integer minor units and a major-unit string. Tools and the Agent never calculate monetary values.

## MainAgent Transaction Rules

The MainAgent prompt now states that:

- Product discovery must call product_search_tool.
- Order creation requires exact product, SKU, quantity, and complete address data.
- place_order_tool may run only after explicit user confirmation.
- The final total must come from the place-order result.
- Order lookup uses query_order_tool.
- Cancellation requires an order ID and reason and uses cancel_order_tool.
- An Agent cannot claim transaction success after a Tool error.

The prompt guides tool selection. Domain and UseCases remain the final business-rule boundary.

## AgentScope Write-Tool Permissions

The FunctionTool read/write classifications are:

```text
product_search_tool   read-only
place_order_tool      write
query_order_tool      read-only
cancel_order_tool     write
```

AgentScope normally parks non-read-only tools in the ASKING state until a UserConfirmResultEvent arrives. The MVP HTTP/Orchestrator does not yet implement that event protocol, while confirmation already occurs at the MainAgent conversation layer.

`allow_business_tools()` therefore adds precise ALLOW rules only for `place_order_tool` and `cancel_order_tool`. It does not globally bypass the permission engine, so future file, shell, or other dangerous tools retain the default confirmation behavior.

Rule installation is idempotent and cannot add duplicate project rules to the same Agent.

This follows the reference project's conversational-confirmation approach, but a prompt is not an absolute security boundary. Production hardening should add a deterministic pending action, confirmation token, or full UserConfirmResultEvent API.

## Composition Wiring

Composition wraps all three functions as FunctionTools and injects them into MainAgentFactory alongside product_search_tool. Every session-scoped MainAgent receives the same capabilities while keeping an independent AgentState.

Tools and Agents share UseCase and Repository instances, ensuring that:

- Query can read an order created by Place.
- Cancel can restore the same inventory objects changed by Place.
- Buyer identity comes from the current request context.

## End-to-End Flow

An offline scripted model emits three real ToolCalls in one session:

```text
Explicit order confirmation
→ place_order_tool
→ create GBX-000001 and deduct inventory

Query GBX-000001
→ query_order_tool
→ return CONFIRMED

Cancel GBX-000001
→ cancel_order_tool
→ return CANCELLED and restore inventory
```

The final order belongs to the current buyer, stock returns to its initial value, and ShoppingContext is None after request completion.

## Tests and Validation

All 152 tests pass. Chapter 10 adds 10 tests covering:

- Missing ContextVar values, nested restoration, and concurrent task isolation.
- ShoppingContext availability only during Orchestrator Agent execution.
- FunctionTool names, schemas, and read/write configuration.
- A complete place/query/cancel Tool flow.
- Removal of buyer from Tool schemas and rejection of access by another buyer.
- No inventory mutation after an invalid address.
- Tool failure when request context is missing.
- The complete offline Composition → MainAgent → Tool → UseCase → Domain → Repository chain.

## Current Limitations

- Buyer ID still comes from an unauthenticated HTTP body.
- Conversational confirmation is mainly prompt-enforced and has no deterministic confirmation token.
- There are no direct order HTTP endpoints.
- There are no WebSocket tool events or streaming replies.
- Orders and inventory remain in process memory.
- SearchAgent and TradeAgent do not exist yet.

## Next Chapter

Chapter 11 introduces sub-agents. MainAgent retains complete business capability while gaining SearchAgent, TradeAgent, and a dispatch tool for tasks that benefit from specialized context or deeper execution chains.
