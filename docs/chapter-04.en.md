# Chapter 4: Connecting Catalog Search to the Agent

## Goal

This chapter wraps the tested `CatalogSearchUseCase` in an AgentScope tool and registers it with the MainAgent, creating the first complete ReAct tool-execution loop.

```text
User request
    ↓
MainAgent / ChatModel
    ↓ ToolCallBlock
product_search_tool
    ↓
CatalogSearchUseCase
    ↓ ToolResultBlock
Second ChatModel call
    ↓
Final natural-language response
```

## Tool Adapter

`build_product_search_tool()` is a tool factory. Its outer function receives the system dependency:

```python
build_product_search_tool(catalog_search_usecase)
```

The inner function exposes only the arguments the model is expected to provide:

```text
normalized_query
category
ship_to
top_k
price_max_major
target_currency
```

The model never sees internal objects such as the Repository or UseCase.

The tool does not duplicate search logic. It only:

1. Converts model arguments into `ProductSearchSpec`.
2. Calls `CatalogSearchUseCase`.
3. Serializes the result into a JSON `ToolChunk`.
4. Converts invalid input into an ERROR `ToolChunk`.

## FunctionTool and Schema Generation

When the Python function is wrapped in `FunctionTool`, AgentScope reads:

```text
Function name      → tool name
Docstring          → tool description
Type annotations   → JSON Schema types
Default values     → required or optional arguments
Args section       → argument descriptions
```

`normalized_query` has no default value and is therefore the only required argument. All other parameters may be omitted by the model.

The tool is marked `is_read_only=True` because catalog search does not modify business state. Future order creation and cancellation tools must not use this flag.

## MainAgent and Dependency Injection

The MainAgent now receives its tools as arguments:

```python
create_main_agent(
    model=model,
    tools=[product_search_tool],
)
```

It depends on `ChatModelBase` and `FunctionTool`, not on `InMemoryProductRepository` or `CatalogSearchUseCase`. The Composition Root assembles all concrete dependencies.

Changing the model type dependency from `OpenAIChatModel` to `ChatModelBase` allows the same MainAgent to use a real OpenAI-compatible model or a test model.

## Composition Root

The complete assembly order is:

```text
seed products
    ↓
InMemoryProductRepository
    ↓
CatalogSearchUseCase
    ↓
Python tool function
    ↓
FunctionTool
    ↓
Toolkit
    ↓
MainAgent
```

The CLI did not change when the tool was introduced. It still invokes `container.main_agent.reply()`, demonstrating that Presentation does not need to understand tool construction or business dependencies.

## ReAct Loop

A product request normally requires two model calls:

1. The first call reads the user request and tool Schema and returns a `ToolCallBlock`.
2. AgentScope finds the FunctionTool by name, parses the arguments, and executes the Python function.
3. The tool output is appended to the context as a `ToolResultBlock`.
4. The second model call reads the real catalog result and generates the final response.

`ReActConfig(max_iters=5)` is a safety limit, not a requirement to call the model five times.

## Network-Free Test Model

`ScriptedChatModel` is a reusable test double. It does not contact an external model. Instead, it returns predefined `ChatResponse` objects and records the messages, tools, and tool choice received by each call.

The integration test scripts:

```text
First response: call product_search_tool
Second response: produce a final answer from the tool result
```

The test confirms that:

- The first model call receives the tool Schema.
- The tool is actually executed rather than bypassed by the test.
- The second model call contains a `ToolResultBlock`.
- The tool result contains P1001, P1003, and the budget-filter reason.
- The Agent returns the final text from the second model response.

## Tests and Validation

All 17 tests pass:

- The 13 tests from previous chapters still pass.
- FunctionTool generates the expected Schema.
- Successful tool output is valid JSON.
- Invalid input produces an ERROR ToolChunk.
- The complete model-call, tool-execution, and model-follow-up loop passes without network access.

## Current Limitations

- The CLI processes only one user input.
- There is no separate Orchestrator.
- There is no session ID, buyer ID, locale, or currency context.
- There is no HTTP API.
- There are no streaming events or tool-call observability.

## Next Chapter

The next chapter introduces `MainAgentOrchestrator` and stable application input/output DTOs. Presentation will call an application use case instead of invoking the Agent directly:

```text
CLI → SubmitIntentInput → Orchestrator → MainAgent → SubmitIntentOutput
```
