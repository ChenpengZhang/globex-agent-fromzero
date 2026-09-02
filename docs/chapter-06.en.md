# Chapter 6: FastAPI HTTP Boundary

## Goal

This chapter adds an HTTP Presentation Adapter alongside the CLI. External clients can submit shopping intents as JSON while reusing the Orchestrator introduced in Chapter 5.

```text
HTTP JSON
    ↓
SubmitIntentRequest (Pydantic)
    ↓
SubmitIntentInput (Application)
    ↓
MainAgentOrchestrator
    ↓
SubmitIntentOutput
    ↓
SubmitIntentResponse (Pydantic)
```

## HTTP DTOs and Application DTOs

`SubmitIntentRequest` and `SubmitIntentResponse` belong to Presentation. They handle JSON parsing, HTTP validation, OpenAPI Schema generation, and response serialization.

`SubmitIntentInput` and `SubmitIntentOutput` belong to Application. They define use-case input and output independently of the transport protocol. CLI and HTTP both convert into the same Application DTO, so Agent invocation logic is not duplicated.

Similar fields do not imply identical responsibilities:

```text
Pydantic DTO       external HTTP contract
Application DTO    internal application contract
```

## FastAPI Application Factory

`build_app(container=None)` uses an application factory instead of fixing all dependencies at module import time.

Production startup omits the Container and lets the Composition Root create the real model and business dependencies. Tests inject a network-free Container. HTTP tests therefore do not contact an external model or require test credentials.

## Endpoints

### GET /health

Returns the basic process health state:

```json
{"status": "ok"}
```

At this stage, health only means that the application can respond. It does not yet verify future external dependencies such as models or databases.

### POST /commerce/intents

Accepts buyer, locale, currency, raw query, and an optional session ID. If the session ID is missing, the server generates a `session-` prefix followed by eight hexadecimal characters.

The route only translates protocols: HTTP DTO → Application DTO → Orchestrator → HTTP Response. It contains no search, tool, or Agent reasoning logic.

## Pydantic Validation

The HTTP boundary:

- Strips leading and trailing whitespace.
- Requires non-empty buyer ID and raw query values.
- Normalizes currency to uppercase.
- Restricts currency to a three-letter code.
- Returns HTTP 422 for invalid requests.

Application DTO validation remains necessary because CLI, Worker, and other non-HTTP adapters do not pass through Pydantic.

## Network-Free API Tests

FastAPI `TestClient` uses an injected `ScriptedChatModel` and covers:

- The health endpoint.
- Automatic session ID generation.
- Preservation of caller-provided session IDs.
- Injection of default locale and currency into the Agent message.
- Currency normalization.
- HTTP 422 responses for missing buyer/query values, blank queries, and invalid currencies.

The chapter adds 7 tests. All 30 tests in the suite pass.

## Current Limitations

- The session ID is currently only a request and response field.
- Every request still shares the single MainAgent and AgentState stored in the Container.
- Different sessions and buyers do not yet have isolated context.
- There is no authentication, persistence, streaming response, or WebSocket support.

The current API must not be treated as a safe multi-user chat service.

## Next Chapter

The next chapter introduces `MainAgentFactory` and `SessionRegistry`:

```text
session-A → Agent A → AgentState A
session-B → Agent B → AgentState B
```

Sessions will also be bound to buyers to prevent different buyers from reusing the same conversation.
