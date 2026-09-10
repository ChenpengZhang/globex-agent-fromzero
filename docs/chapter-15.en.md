# Chapter 15: React Frontend

## Goal

This chapter adds a usable browser boundary without moving business rules into
the browser. The UI can submit a shopping intent, display streamed Agent text,
fall back to the final HTTP response, preserve browser identity, start a new
shopping session, and show an execution timeline.

The chapter was implemented as one complete module so the learning path can
continue with persistence and long-term memory. The frontend remains a client of
the existing backend contracts; it does not duplicate the Agent, retrieval, or
order workflows.

## Runtime Paths

One user turn uses two coordinated channels:

```text
React form
   └── POST /commerce/intents
           └── SubmitIntentInput → MainAgentOrchestrator
                                   └── final_text HTTP response

React event adapter
   └── WS /commerce/events
           └── session subscription
               └── token.delta / final.result / error
```

The WebSocket is opened before the user submits an intent. Both requests carry
the same `shopping_session_id`, so the in-memory event bus can route only that
session's events to the page.

The HTTP response is still authoritative and acts as a fallback when the
WebSocket is late or disconnected. `appendFinalTurn()` ignores an immediately
repeated final answer, preventing `final.result` and `final_text` from rendering
the same Agent message twice.

## Frontend Structure

```text
frontend/
├── src/
│   ├── App.tsx                    UI orchestration and state
│   ├── api.ts                     HTTP adapter
│   ├── eventStream.ts             WebSocket adapter and reconnect lifecycle
│   ├── session.ts                 browser identity helpers
│   ├── types.ts                   transport and view contracts
│   ├── styles.css                 responsive visual system
│   └── components/
│       ├── EventTimeline.tsx       non-token execution events
│       ├── ProductCards.tsx        prepared structured search results
│       └── OrderCard.tsx           prepared structured order result
├── vite.config.ts                 local HTTP/WS proxy
└── package.json                   build and development commands
```

`App.tsx` is the presentation composition point. It coordinates browser state
and calls adapters, but it does not know how catalog search, RAG, inventory, or
orders are implemented.

## Buyer Identity and Shopping Session

The browser stores two different identifiers in `localStorage`:

```text
buyer_id              stable browser-level customer identity
shopping_session_id   one conversation and Agent-state boundary
```

Reloading the page keeps both values. Choosing **New conversation** replaces
only the shopping session ID, clears the visible conversation, and creates a
fresh backend Agent session on the next request. The buyer ID remains stable so
Chapter 16 can associate durable preferences and history with the same buyer.

These random IDs are learning-stage identifiers, not authentication tokens.
Production identity and authorization remain later concerns.

## WebSocket Lifecycle

`connectEventStream()` owns the browser WebSocket rather than placing socket
details throughout the components. It:

1. derives `ws://` or `wss://` from the current page;
2. connects to `/commerce/events`;
3. sends the session subscription after the socket opens;
4. parses and validates incoming event envelopes;
5. reconnects after a short delay when the connection closes; and
6. returns a cleanup function that cancels retry timers and closes the socket.

React calls that cleanup function whenever the session changes or the component
unmounts. This matters in development because React Strict Mode intentionally
re-runs effects to expose unsafe lifecycle code.

The current UI marks the connection as ready after the socket opens and the
subscription message is sent. Chapter 14's server does not yet return an
explicit subscription acknowledgement, so this is transport readiness rather
than a guaranteed replay boundary.

## Event and View State

`types.ts` defines a discriminated `TradeEvent` union. TypeScript can therefore
narrow the payload from `event.type`, while `isTradeEvent()` performs a small
runtime envelope check because network input cannot be trusted solely from a
compile-time type assertion.

The UI treats events according to responsibility:

```text
token.delta    append temporary streaming text
final.result   commit the canonical Agent turn and clear temporary text
error          stop the busy state and show an error notice
other events   retain up to 100 entries for the execution timeline
```

Chat turns and event observations are separate state. A timeline item is not a
chat message, and a token delta is not stored as hundreds of permanent turns.

## Product and Order Cards

`ProductCards` and `OrderCard` are implemented against typed structured payloads
for future `tool.result` events. They intentionally render nothing when such an
event is absent.

The current backend publishes only `token.delta`, `final.result`, and `error`.
Therefore the cards are structurally ready but are not yet active in a real
conversation. The UI does not parse free-form LLM text or invent product/order
data. A later instrumentation step should publish safe Application DTOs from the
tool boundary, after which these components can render without changing domain
logic.

## Vite Proxy

During development, the browser loads the UI from port 5173 while FastAPI runs
on port 8000. Vite proxies `/commerce` for both HTTP and WebSocket traffic:

```text
browser http://127.0.0.1:5173/commerce/intents
    → FastAPI http://127.0.0.1:8000/commerce/intents

browser ws://127.0.0.1:5173/commerce/events
    → FastAPI ws://127.0.0.1:8000/commerce/events
```

Using same-origin relative URLs keeps API locations out of React components and
avoids a development-only CORS configuration.

## Usability and Accessibility

The interface includes:

- responsive desktop and mobile layouts;
- clear connection, busy, and error states;
- keyboard submission with Shift+Enter for a newline;
- disabled duplicate submission while one turn is active;
- starter prompts and a new-conversation action;
- semantic form labels, status roles, and live transcript announcements; and
- visible buyer/session suffixes for debugging session isolation.

The layout was visually inspected at desktop and 390-pixel mobile widths. The
browser console showed no application errors while the frontend was running.

## Running the Full Flow

Start FastAPI from the project root:

```bash
uv run uvicorn app.presentation.server:build_app --factory
```

Start Vite in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` and submit a purchase request. Model and embedding
environment variables are still backend configuration and must be set as
described in the main README.

## Verification

This chapter was checked with:

```text
frontend TypeScript + Vite production build: passed
backend regression suite:                  211 passed
desktop and mobile browser rendering:      passed
```

## Current Limitations

- Conversation turns are not persisted by the backend and disappear when a new
  session is selected.
- The WebSocket has reconnect but no event replay or ready acknowledgement.
- Structured tool/sub-Agent events are not yet published by the backend.
- The browser IDs are not authentication or authorization.
- There are no frontend component or end-to-end automated tests yet.
- Agent text is rendered as plain text rather than Markdown.

Chapter 16 can now add persistence, session recovery, conversation history, and
long-term buyer preferences behind stable application boundaries.
