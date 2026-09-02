# Chapter 5: Application Orchestration

## Goal

This chapter introduces a stable application boundary between Presentation and the Agent. The CLI no longer constructs AgentScope `UserMsg` objects or calls `Agent.reply()` directly. It submits an application intent to an Orchestrator.

```text
CLI
 ↓ SubmitIntentInput
MainAgentOrchestrator
 ↓ UserMsg
MainAgent
 ↓
SubmitIntentOutput
```

## Application DTOs

`SubmitIntentInput` describes the application data required for one shopping intent:

- `shopping_session_id`
- `buyer_id`
- `locale`
- `currency`
- `raw_query`

It trims strings, normalizes currency, and rejects missing session, buyer, and query values. It belongs to Application because it describes an application operation rather than a core domain object such as Product or Order.

`SubmitIntentOutput` provides a stable application response containing the session ID and final text. Future HTTP, WebSocket, or other adapters can reuse it without depending on AgentScope `Msg` objects.

## MainAgentOrchestrator

The Orchestrator coordinates one request:

1. Receive `SubmitIntentInput`.
2. Build shopping context from locale and currency.
3. Convert the original query into an AgentScope `UserMsg`.
4. Invoke the MainAgent.
5. Convert the Agent reply into `SubmitIntentOutput`.

The Agent is responsible for understanding, reasoning, and tool use. The Orchestrator is responsible for the application workflow. Session selection, long-term memory, caching, events, and error handling can later be added here instead of being duplicated in CLI and HTTP routes.

## Shopping Context

Locale and currency currently enter model context as text:

```xml
<shopping-context>
locale: zh-CN
currency: CNY
</shopping-context>
```

This gives the model a currency when the user only says “under 300.” The session ID is not sent to the model because it is a routing identifier rather than shopping information.

A later server-side `ShoppingContext` will further separate trusted identity data from model-generated arguments.

## Presentation Decoupling

The CLI now depends on Application rather than AgentScope directly:

```text
Before: CLI → AgentScope Agent
After:  CLI → MainAgentOrchestrator → AgentScope Agent
```

When an HTTP API is added, CLI and HTTP can both create the same `SubmitIntentInput` without duplicating Agent invocation logic.

## Composition Root

The Composition Root creates the Orchestrator after assembling the MainAgent and exposes both through the Container. Concrete module wiring still occurs in one place.

## Tests and Validation

All 23 tests pass. New tests cover:

- Whitespace cleanup and case normalization in the Application DTO.
- Rejection of missing session, buyer, query, and invalid currency values.
- Preservation of the session ID by the Orchestrator.
- Injection of locale, currency, and raw query into the model message.
- Conversion of the final Agent text into `SubmitIntentOutput`.

## Current Limitations

- The Container has one MainAgent, so session IDs do not yet isolate conversations.
- There is no HTTP API.
- There are no Pydantic HTTP DTOs.
- Exceptions are not yet mapped to HTTP status codes.

## Next Chapter

The next chapter adds FastAPI and distinguishes HTTP DTOs from Application DTOs:

```text
HTTP JSON → Pydantic DTO → SubmitIntentInput → Orchestrator
```
