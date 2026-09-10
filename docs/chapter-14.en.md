# Chapter 14: Realtime Events

## Goal

This chapter makes a running Agent observable before its final HTTP response is ready. It introduces a small in-process event path:

```text
AgentScope reply_stream
→ MainAgentOrchestrator
→ typed TradeEvent
→ InMemoryTradeEventBus
→ subscriber Queue
→ WebSocket
→ client
```

The implementation deliberately excludes background jobs, Redis, persistence, replay, reconnect recovery, and frontend rendering. The synchronous HTTP contract still returns the final text.

## Event Contract

`TradeEvent` is an Application-level observation contract rather than an Order domain event. It describes what the Agent execution is doing without changing Product or Order state.

Each event contains:

```text
shopping_session_id  routing and isolation key
type                 typed event name
payload              event-specific JSON data
occurred_at          UTC timestamp
```

`TradeEventType` currently defines dispatch, tool, token, final, and error names. This chapter actively publishes `token.delta`, `final.result`, and `error`; the remaining names provide a stable vocabulary for later UI instrumentation.

`EventPublisher` is an Application protocol. The Orchestrator depends on this port instead of FastAPI, WebSocket, or the concrete in-memory bus.

## In-Memory Publish/Subscribe

`InMemoryTradeEventBus` routes events by `shopping_session_id`. Every subscriber receives its own `asyncio.Queue`:

```text
session-001
├── browser A → Queue A
└── browser B → Queue B
```

Publishing one event copies the same immutable `TradeEvent` reference into both queues. A shared queue would produce competing-consumer semantics, where browser A and browser B split the stream instead of both seeing it.

`queue.get()` suspends only the waiting coroutine when no event is available. `put_nowait()` lets the Agent continue without waiting for network delivery. Unsubscribe removes disconnected consumers and deletes an empty session entry.

The queue is intentionally unbounded for this MVP. Backpressure and slow-consumer policies are production concerns.

## Mapping AgentScope Events

The Orchestrator now consumes:

```python
agent.reply_stream(..., yield_final_msg=True)
```

It maps AgentScope `TextBlockDeltaEvent` values into the project's stable `token.delta` contract. The final `Msg` supplies the canonical complete text.

This boundary prevents the frontend from depending on AgentScope classes or event schemas. Replacing the Agent framework would require changing the mapper, not every external client.

The real OpenAI-compatible ChatModel uses `stream=True`, allowing text chunks to become visible while generation is in progress. Offline models may emit the complete answer as one delta; the same event path still applies.

On successful completion the Orchestrator publishes `final.result`. On failure it publishes `error` and re-raises the exception, so observability does not change application error semantics. `ShoppingContext` is still reset in `finally`.

## WebSocket Boundary

The client connects to:

```text
WS /commerce/events
```

After the server accepts the WebSocket upgrade, the client sends:

```json
{"shopping_session_id": "session-001"}
```

`ConnectionManager` subscribes to that session and forwards each queued event with `send_json()`. Its `finally` block always unregisters the queue when the connection finishes.

Because the bus has no replay, the client must establish the subscription before submitting the HTTP intent with the same session ID:

```text
choose session ID
→ connect WebSocket
→ send subscription
→ POST /commerce/intents with the same ID
```

The current subscription ID is a routing key, not authentication. Authorization of event streams belongs to the later production-security work.

## Why HTTP Still Returns Final Text

The two outputs have different responsibilities:

```text
SubmitIntentOutput.final_text  direct Application/HTTP/CLI result
final.result event             optional realtime observation
```

An in-memory event may have no subscriber or may be lost on disconnect. Keeping the direct return preserves the existing API, tests, and CLI and avoids prematurely introducing task IDs, durable queues, and event replay.

Clients must treat the WebSocket `final.result` and HTTP `final_text` as the same turn, not append both as separate assistant messages.

## DDD Boundaries

```text
Application
├── TradeEvent / TradeEventType
├── EventPublisher port
└── Orchestrator event mapping

Infrastructure
└── InMemoryTradeEventBus

Presentation
├── ConnectionManager
└── FastAPI WebSocket route
```

Domain aggregates remain unaware of streaming, subscribers, network connections, and AgentScope events. Composition creates one shared bus instance for both publisher and subscriber sides.

## Tests

Offline coverage verifies:

- typed event serialization and UTC timestamps;
- isolation between different shopping sessions;
- fan-out to multiple subscribers of one session;
- unsubscribe cleanup;
- AgentScope delta-to-TradeEvent mapping;
- `token.delta` followed by `final.result`;
- a WebSocket subscription triggered by an HTTP Agent request;
- removal of the subscriber after WebSocket disconnect;
- regressions across all previous chapters.

The complete suite after this chapter is:

```text
211 passed
```

## Current Limitations

- Events exist only inside one Python process.
- Events published before subscription are not replayed.
- Application restart discards all events and subscriptions.
- The unbounded queue has no slow-consumer policy.
- There is no acknowledgement, retry, ordering across processes, or durable history.
- The subscription handshake has no explicit ready acknowledgement.
- Session ID subscription is not yet authenticated.
- Tool and sub-Agent event names exist, but structured publishers are not yet connected.

These limitations are explicit so later persistence, Redis, async-work, and production-hardening chapters can replace transport details without changing the event contract.
