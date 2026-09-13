# Chapter 19: Redis and Asynchronous Work

## Goal

Chapter 19 separates accepting a shopping request from executing the Agent. The HTTP API can now enqueue work and return a task ID immediately, while a separate Worker performs the slow model and tool calls. Redis also avoids repeated embedding calls, supports a guarded semantic reply cache, and carries realtime events between the Worker and API processes.

The completed asynchronous path is:

```text
Browser
  ├─ POST /commerce/intents/async ──→ API ──→ Redis Stream
  │                                  ↑          │
  │                                  │ task ID  ↓
  │                                  │        Worker ──→ Orchestrator ──→ Agent
  │                                  │          │
  ├─ GET /commerce/tasks/{id} ───────┴──────────┤ status in Redis
  │                                             │
  └─ WebSocket ←── API ←── Redis Pub/Sub ←──────┘ events
```

The original synchronous `POST /commerce/intents` endpoint remains available for simple debugging. It executes the Orchestrator directly and does not use the queue.

## Why Redis Has Three Roles

Redis is one server, but the chapter deliberately uses different data structures for different guarantees.

| Need | Redis mechanism | Reason |
|---|---|---|
| Embedding and semantic reply cache | String containing JSON, with TTL | Direct key lookup and automatic expiry |
| Idempotency reservation and task status | String, with TTL | Atomic `SET NX` and inexpensive status polling |
| Background task delivery | Stream and consumer group | Pending entries, ACK, redelivery, and multiple consumers |
| Cross-process realtime events | Pub/Sub channel | Low-latency fan-out; durability is unnecessary because polling is the fallback |

Redis is not the source of truth for products, orders, conversations, or buyer preferences. SQLite remains authoritative for durable business data.

## DDD Boundaries

### Domain

`app/domain/queue/ports/task_queue.py` defines the queue language used by the application:

- `IntentTask` is the immutable work envelope;
- `TaskState` is `queued`, `running`, `retrying`, `done`, or `failed`;
- `TaskStatus` is the buyer-scoped observable result;
- `TaskQueue` is the port implemented by Redis Streams.

The Domain does not import Redis. It only expresses what reliable task delivery must provide.

### Application

`EnqueueIntentUseCase` owns the submission workflow: session ownership validation, idempotency claim, priority choice, enqueue, rollback of a failed reservation, and `task.queued` publication.

`GetTaskStatusUseCase` owns existence and buyer-ownership checks. The HTTP layer cannot read another buyer's task merely by guessing its ID.

`IdempotencyStore` is an application-facing protocol because idempotency is workflow policy, not a commerce entity and not a Redis-specific concept.

### Infrastructure

Infrastructure implements the technical mechanisms:

- `RedisCache` wraps optional Redis access;
- `CachedEmbeddingClient` decorates the existing embedding port;
- `SemanticCache` stores and compares safe reply candidates;
- `RedisIdempotency` performs atomic reservation and compare-and-delete release;
- `RedisStreamTaskQueue` implements reliable task delivery;
- `RedisEventBackplane` transports events across processes;
- `InMemoryTradeEventBus` still performs local session fan-out and optionally mirrors events to the backplane.

### Presentation and process entry points

FastAPI exposes submission, status polling, synchronous compatibility, history, and WebSocket endpoints. `app/worker.py` is a separate process entry point. Both processes build the same dependency graph, but only the API listens to Redis Pub/Sub; the Worker publishes events while executing tasks.

## Embedding Cache

`CachedEmbeddingClient` is a decorator around the existing `EmbeddingClient`:

```text
caller → CachedEmbeddingClient → Redis hit → vector
                              └→ miss → online embedding API → Redis → vector
```

The key contains the embedding model and a SHA-256 digest of model plus input text. This prevents vectors produced by different models from sharing a cache entry. Vectors are JSON arrays in Redis Strings and expire after seven days.

A Redis failure is treated as a cache miss. The underlying embedding client still decides whether vector generation itself succeeds.

## Semantic Reply Cache

The semantic cache can reuse a final first-turn answer when a new query is sufficiently close to an earlier query. It stores at most 30 entries in one buyer-scoped bucket for 24 hours. Every entry contains normalized query text, final reply, and vector.

The cache namespace includes:

- buyer identity;
- relevant buyer-preference fingerprint;
- chat model;
- embedding model;
- a fingerprint of the MainAgent source.

This isolation prevents one buyer from receiving another buyer's reply and invalidates old answers after relevant model, prompt, or preference changes.

The cache intentionally refuses stateful or mutating requests, including orders, payments, cancellations, pronoun-dependent follow-ups, and remember/forget operations. It is also skipped whenever the session already has history. A semantic hit publishes `cache.hit` followed by the ordinary final result.

Semantic cache failures are fail-open: they reduce performance but do not block the Agent.

## Idempotent Submission

The browser sends a fresh `idempotency_key` for each intentional user action and reuses it if the same HTTP operation is retried. The server combines it with buyer identity and hashes it into a Redis key. On a duplicate request, the response uses the shopping session stored with the winning task rather than a newly generated session ID.

Reservation uses:

```text
SET key task-id NX EX 300
```

Only the first caller acquires the key. Concurrent or retried callers receive the winning task ID instead of creating duplicate work. If the Stream transaction fails, a Lua compare-and-delete script releases the reservation only when it still contains that caller's task ID.

When a client omits `idempotency_key`, the server derives a deterministic fallback from the normalized request payload. Explicit keys are preferable because they distinguish two intentional, identical questions from one network retry.

Idempotency is strict for the asynchronous endpoint: if Redis cannot decide ownership, submission returns `503` instead of guessing and possibly creating duplicate work.

## Atomic Enqueue and Task Status

`RedisStreamTaskQueue.enqueue` uses one Redis transaction to:

1. append the serialized `IntentTask` to a Stream;
2. create its `queued` status with a one-hour TTL.

This prevents the visible task status from existing without its task, or the task from being queued without a status under ordinary Redis transaction semantics.

Status transitions are:

```text
queued → running → done
            │
            └→ retrying → running → ... → failed
```

The API returns `202 Accepted` with `shopping_session_id`, `task_id`, and the current state. `GET /commerce/tasks/{task_id}?buyer_id=...` returns the status, final text, error, and an approximate queue position. Status expires after one hour, so a missing status produces `404`.

## Redis Streams, ACK, and Recovery

Two Streams are used:

- `globex:intents` for ordinary work;
- `globex:intents:large` for long-conversation work.

The Worker prefers the normal Stream. When priority routing is enabled, an existing session at or above `QUEUE_LARGE_REQUEST_TURNS` enters the large Stream so a long context does not block short requests as easily.

All workers join the `globex-workers` consumer group. A message is acknowledged only after the Orchestrator succeeds and `done` status is saved. If a Worker stops after delivery but before ACK, Redis retains that message in the group's Pending Entries List.

`XAUTOCLAIM` recovers entries idle for at least one minute. The adapter keeps a scan cursor per Stream so recovery can advance across a large pending set instead of repeatedly inspecting only its beginning.

On an Agent exception:

- before the delivery limit, status becomes `retrying` and the message remains pending;
- after `QUEUE_MAX_DELIVERIES`, status becomes `failed`, the message is copied to `globex:intents:dead`, and the original is acknowledged.

Malformed messages go directly to the dead-letter Stream. The dead-letter entry records the source Stream, source message ID, payload, and failure reason.

This is at-least-once delivery, not exactly-once execution. The queue may redeliver work after a crash. Business mutations such as order placement still need their own durable business idempotency before running multiple Worker processes aggressively; that belongs to production hardening.

## Worker Lifecycle

`process_task` writes `running`, publishes `task.started`, reconstructs `SubmitIntentInput`, invokes the existing Orchestrator, and finally writes `done` plus final text. It deliberately lets exceptions escape so the queue adapter—not the Worker function—owns retry and dead-letter policy.

The Worker creates a unique consumer name from hostname, process ID, and a random suffix. `SIGINT` and `SIGTERM` stop new reads and allow current tasks to finish before infrastructure resources close.

## Cross-Process Events

The original event bus was memory-only. After API and Worker separation, an event published inside the Worker would otherwise be invisible to WebSockets connected to the API process.

`RedisEventBackplane` publishes an envelope to `globex:events:{shopping_session_id}`. Every process instance has an origin ID. The API subscribes to `globex:events:*`, ignores its own mirrored events, converts remote payloads back into typed `TradeEvent` objects, and delivers them locally without republishing. This prevents event loops and duplicate browser delivery.

Pub/Sub is intentionally ephemeral. A disconnected browser can miss token or trace events. The durable completion path is task-status polling, so the frontend still receives `final_text` even if its WebSocket reconnects late.

## Frontend Flow

The React client now:

1. sends the request to the asynchronous endpoint with a fresh idempotency key;
2. receives a task ID immediately;
3. keeps the WebSocket for live tokens and execution events;
4. polls task status every 500 ms until `done` or `failed`;
5. deduplicates the final reply if both WebSocket and polling deliver it.

The timeline recognizes `task.queued`, `task.started`, and `cache.hit`. An error event no longer ends the browser wait immediately because a failed delivery may still be retried; terminal task status makes that decision.

## Configuration and Running

Start Redis locally, then configure:

```dotenv
REDIS_URL=redis://localhost:6379/0
QUEUE_ENABLED=1
WORKER_CONCURRENCY=1
QUEUE_MAX_DELIVERIES=3
QUEUE_PRIORITY_ENABLED=1
QUEUE_LARGE_REQUEST_TURNS=30
SEMANTIC_CACHE_ENABLED=1
SEMANTIC_CACHE_THRESHOLD=0.95
```

Run the API and Worker in separate terminals:

```bash
uv run uvicorn app.presentation.server:build_app --factory
uv run python -m app.worker
```

Then run the frontend as before. If `QUEUE_ENABLED=0`, the synchronous endpoint still works, but the asynchronous endpoint returns `503` and the chapter-19 frontend cannot submit work.

## Failure Policy

- Embedding and semantic caches fail open because they are performance features.
- Queue submission and idempotency fail closed because ambiguity could duplicate Agent work.
- Queue read errors are logged and retried.
- Pub/Sub subscription reconnects after transient failures.
- Pub/Sub event loss is tolerated because task polling is authoritative for completion.
- Durable commerce and memory data remain in SQLite.

## Tests

Coverage includes cache hit/miss/corrupt payload behavior, embedding batching, semantic safety rules and isolation, idempotency races and conditional release, Stream creation and atomic enqueue, priority selection, status transitions, queue depth, ACK, pending retry, `XAUTOCLAIM` cursor recovery, dead-letter handling, Worker execution, asynchronous HTTP ownership and failure mapping, local/remote event delivery, and frontend type/build verification.

At chapter completion, the official `tests/` suite contains 450 passing backend tests, and the TypeScript/Vite production build succeeds.

## Known Limitations

- Semantic buckets use read-modify-write; concurrent cache writes can lose a cache candidate, which affects hit rate but not correctness.
- Refreshing a semantic bucket refreshes the whole bucket TTL.
- Semantic answers may remain stale until their 24-hour TTL, although model, prompt, preference, and buyer isolation reduce unsafe reuse.
- Redis task status is operational data and expires; durable conversation replies remain in SQLite.
- Pub/Sub does not replay missed events.
- Dead-letter copy and original ACK are two Redis operations, so a crash between them can duplicate a dead-letter record rather than lose the pending original.
- At-least-once task delivery does not make external business side effects exactly once.
- Multiple Worker processes can execute different tasks for the same session concurrently; distributed session serialization is deferred to production hardening. The learning-safe default is one Worker with concurrency one.
- A continuously busy normal Stream can delay large-conversation tasks; fair scheduling is deferred until real workload measurements justify it.

## Next Direction

Chapter 20 can now focus on production hardening: durable business idempotency, distributed session coordination, authentication, tracing, rate limits, resilience policies, evaluations, deployment, and operations. Chapter 21 remains the final structural cleanup after the behavior is understood.
