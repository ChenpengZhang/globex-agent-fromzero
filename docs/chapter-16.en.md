# Chapter 16: File Persistence and Recovery

## Goal

This chapter makes a shopping conversation survive a backend restart without
introducing a relational database. It adds two deliberately separate forms of
persistence:

```text
AgentState snapshot   restores the Agent's internal conversation context
Conversation log      restores human-readable turns and execution records
```

The distinction is important. An Agent state is framework-specific runtime
data used to continue reasoning, while a conversation history is an
application-facing record used by the API and frontend. Neither representation
is forced to serve both responsibilities.

The file adapters are an intermediate learning implementation. The ports and
application flow remain stable when Chapter 17 replaces them with database
adapters.

## DDD Boundaries

The chapter keeps persistence concerns behind inward-facing contracts:

```text
Domain
├── SessionStore
├── ConversationStore
├── ConversationTurn
└── ConversationEventRecord

Application
├── SessionRegistry
├── MainAgentOrchestrator
└── GetConversationHistoryUseCase

Infrastructure
├── JsonFileSessionStore
├── JsonFileConversationStore
└── safe_storage_name

Presentation
├── GET /commerce/sessions/{session_id}/history
└── React history loading
```

The Domain defines what can be saved and read, but it does not know about
paths, JSONL, FastAPI, or React. Infrastructure implements those ports. The
Application layer decides when persistence occurs and enforces the history
query workflow. Presentation only translates transport data.

`SessionStore` and `ConversationStore` are separate because they have different
data shapes and write patterns. A session snapshot replaces an earlier value;
conversation turns and events form an append-only record.

## Agent State Recovery

`SessionRegistry` remains the owner of live Agent instances and per-session
execution locks. When a session is first requested in the current process, it
follows this path:

```text
get_or_create(session_id, buyer_id)
    ├── live entry exists → verify buyer → reuse Agent
    └── no live entry
          └── SessionStore.load(session_id)
                ├── no snapshot → build a fresh Agent
                ├── valid snapshot → restore AgentState → build Agent
                ├── another buyer → reject
                └── unreadable snapshot → log warning → build fresh Agent
```

`MainAgentFactory.build(state=...)` injects the restored `AgentState` into the
framework Agent. The factory still owns construction, so the registry does not
need to know the Agent's model, tools, prompt, or configuration.

After each Agent execution, the orchestrator calls `SessionRegistry.persist()`
inside `finally`. This attempts to save state after successful and failed turns.
The persisted envelope contains both the owner and the framework state:

```json
{
  "buyer_id": "buyer-001",
  "state_json": "{...serialized AgentState...}"
}
```

Saving the buyer ID with the state preserves session ownership after a process
restart. A matching session ID is therefore not enough to load another buyer's
Agent context.

Snapshot failures are logged and do not replace the business response with a
persistence error. This is a best-effort policy suitable for the current
learning stage.

## Human-Readable Conversation Log

The conversation log stores three record kinds in one JSONL file per session:

```text
session   buyer ownership, locale, currency, creation/update timestamps
turn      buyer or Agent text, model, latency, timestamp
event     event type, structured payload, occurrence timestamp
```

JSONL writes one JSON object per line. Appending a new turn or event does not
require parsing and rewriting all earlier records. Repeated `session` records
act like metadata updates; `find_session()` uses the latest one while retaining
the original creation time.

The stored buyer turn contains `raw_query`, not the internal message augmented
with `<shopping-context>`. This keeps the visible history readable and prevents
transport/runtime metadata from leaking into the chat transcript.

The Agent turn is written only when a final answer exists. If execution fails,
the buyer's attempted turn and non-token error trace can still be retained, but
an empty Agent reply is not invented.

## Event Capture

The orchestrator temporarily subscribes to the existing event bus for the
session being executed:

```text
acquire session lock
    → subscribe temporary trace queue
    → run Agent and publish events
    → unsubscribe
    → drain queue into ConversationEventRecord values
    → append records
```

Subscription begins after acquiring the per-session execution lock. This keeps
two queued requests for the same session from collecting each other's trace.

`token.delta` events are intentionally excluded from durable storage. Hundreds
of token fragments add volume but do not improve history recovery because the
final Agent turn already contains the completed text. Higher-level events such
as `final.result`, `error`, and future tool/sub-Agent events remain structured.

Stored events are currently an observability record only. The history endpoint
returns readable turns, and the WebSocket still delivers only live events; this
chapter does not implement event replay.

## Safe File Names

External session IDs are never used directly as paths. `safe_storage_name()`
combines a readable, restricted prefix with a truncated SHA-256 digest:

```text
original external ID
    → keep letters, numbers, hyphen, underscore for a short prefix
    → append a hash of the complete original value
```

The restricted prefix prevents path traversal, while the digest distinguishes
values that sanitize to the same readable text, such as `a/b` and `ab`.

Runtime data is organized below the configured data directory:

```text
data/
├── sessions/
│   └── <safe-session-name>.json
└── conversations/
    └── <safe-session-name>.jsonl
```

## History Use Case and HTTP API

`GetConversationHistoryUseCase` provides the Application boundary for history
queries. It:

1. validates and normalizes `session_id`, `buyer_id`, and `limit`;
2. verifies that conversation metadata exists;
3. verifies buyer ownership before reading turns;
4. asks the store for the newest requested turns in original order; and
5. maps Domain records to output DTOs.

The Presentation layer exposes:

```http
GET /commerce/sessions/{session_id}/history?buyer_id=buyer-001&limit=50
```

The response contains `session_id` and readable buyer/Agent turns. The boundary
uses the following status behavior:

```text
200   history returned
403   session belongs to another buyer
404   conversation session does not exist
422   path/query validation failed
```

The current ownership check is important isolation, but `buyer_id` is still a
client-provided learning identifier rather than authenticated identity.

## Frontend Recovery

When React starts or `shopping_session_id` changes, it requests history before
enabling message submission:

```text
load browser buyer/session IDs
    → request history
        ├── 200 → validate response → render stored turns
        ├── 404 → treat as a new empty conversation
        └── other failure → display an error notice
```

The effect has a cancellation guard so a slower response for an old session
cannot overwrite a newly selected conversation. Network data is checked at
runtime before it enters view state. The page restores only chat turns; it does
not restore old streaming fragments or replay the event timeline.

## Complete Runtime Flow

One successful turn now crosses the system as follows:

```text
React
  → POST /commerce/intents
  → FastAPI request DTO
  → SubmitIntentInput
  → MainAgentOrchestrator
      → SessionRegistry.get_or_create
          → load AgentState snapshot when needed
      → acquire per-session lock
      → subscribe to event trace
      → Agent.reply_stream
      → publish token.delta and final.result
      → finally:
          → save AgentState snapshot
          → save readable buyer/Agent turns
          → save non-token execution events
          → reset ShoppingContext
  → final HTTP response

Later reload
  → GET history
  → GetConversationHistoryUseCase
  → ConversationStore
  → React renders restored turns
```

## Failure Policy

This chapter keeps the Agent workflow available even when optional recording
fails:

- unreadable or malformed Agent snapshots fall back to a fresh Agent;
- a snapshot owned by another buyer is rejected rather than ignored;
- state-save failures are logged;
- conversation-save failures are logged;
- malformed JSONL lines are skipped while valid records remain readable; and
- Agent execution errors are still re-raised after persistence is attempted.

The policy favors continuity, but it does not provide transactional consistency
between the Agent snapshot, conversation log, and business repositories.

## Verification

The completed implementation was checked with:

```text
backend regression suite:                  248 passed
frontend TypeScript + Vite production build: passed
```

Coverage includes state restore across registry instances, ownership after
restart, save-on-failure behavior, safe file names, metadata refresh, ordered
and limited history, malformed-line tolerance, event batches, UseCase mapping,
HTTP status behavior, and the orchestrator-to-history path.

## Current Limitations

- File I/O is synchronous even though the port methods are asynchronous.
- Snapshot replacement is not an atomic file transaction.
- JSONL appends have no cross-process lock.
- The two files are not committed as one transaction and can temporarily
  disagree after a crash.
- A corrupt snapshot starts a fresh Agent rather than reconstructing state from
  readable turns.
- Conversation events are stored but cannot yet be queried or replayed.
- There is no retention, compaction, migration, indexing, or backup strategy.
- In-memory orders and inventory still disappear after process restart.
- Buyer IDs provide isolation checks but are not authentication credentials.

These limitations are intentional. Chapter 17 introduces relational database
persistence behind the same ports, allowing the project to study schemas,
transactions, constraints, and database adapters without mixing those concepts
into the first recovery implementation. Long-term buyer memory follows in
Chapter 18.
