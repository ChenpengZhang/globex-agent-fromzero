# Chapter 17: Relational Database Persistence

## Goal

Chapter 16 proved the persistence workflow with JSON and JSONL files. This
chapter keeps the same Domain ports and Application orchestration while
replacing those file adapters with asynchronous SQLAlchemy adapters backed by
SQLite.

The chapter focuses on relational persistence concepts:

- an asynchronous database engine and connection lifecycle;
- explicit tables, primary keys, foreign keys, constraints, and indexes;
- transaction boundaries around Store operations;
- mapping between Domain records and ORM rows;
- startup schema bootstrap and shutdown cleanup; and
- recovery through a completely new database connection.

It does not yet persist orders, inventory, vector data, or long-term buyer
preferences.

## Stable Ports, Replaceable Adapters

The central architectural result is that neither the Agent workflow nor the
history UseCase changed:

```text
SessionRegistry
    → SessionStore
        ├── JsonFileSessionStore       Chapter 16
        └── SqlSessionStore            Chapter 17

GetConversationHistoryUseCase
    → ConversationStore
        ├── JsonFileConversationStore  Chapter 16
        └── SqlConversationStore       Chapter 17
```

The ports remain in the Domain layer. SQLAlchemy, SQLite types, SQL statements,
and ORM rows remain in Infrastructure. The Composition Root selects the active
implementation.

This is the practical value of dependency inversion in this project: changing
the storage technology does not change `SessionRegistry`,
`MainAgentOrchestrator`, the history UseCase, FastAPI DTOs, or React.

## Dependencies

The implementation uses:

```text
SQLAlchemy 2.x asyncio API   ORM, SQL construction, transactions, engine
aiosqlite                    asynchronous SQLite DBAPI driver
```

The URL explicitly names both layers:

```text
sqlite+aiosqlite:///relative/path.db
sqlite+aiosqlite:////absolute/path.db
sqlite+aiosqlite:///:memory:
```

`sqlite` selects the SQL dialect; `aiosqlite` selects the asynchronous driver.
This chapter rejects other URL schemes so its SQLite-specific behavior is
explicit rather than accidentally pretending to be database-neutral.

## Engine, Session, and Transaction

These three SQLAlchemy concepts have different responsibilities:

```text
AsyncEngine
    owns database configuration and the connection pool

AsyncSession
    provides one unit-of-work context for SQL and ORM operations

Transaction
    commits all operations together or rolls them all back
```

The engine is application-scoped and is created once in the Composition Root.
`async_sessionmaker` is also created once and injected into both SQL Stores.
Each Store method asks the factory for a short-lived `AsyncSession`.

The Store receives the factory rather than one shared Session because an
`AsyncSession` is mutable unit-of-work state and must not be used concurrently
by unrelated requests.

## SQLite Engine Configuration

`create_database_engine()` creates the `AsyncEngine` and installs a connection
listener on its synchronous facade. Every new SQLite connection receives:

```sql
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

Their roles are:

```text
foreign_keys   enforce parent/child references instead of silently ignoring them
WAL            allow readers to continue while a writer commits
busy_timeout   wait up to 5 seconds for a temporary database write lock
```

WAL improves read/write coexistence but does not turn SQLite into an unlimited
multi-writer database. SQLite still serializes writes.

`bootstrap_schema()` creates a missing parent directory for a file database and
then calls `Base.metadata.create_all()` inside an engine transaction. Calling it
again is safe and does not delete existing rows.

`create_all()` is schema bootstrap, not a migration system. It creates missing
tables but does not reliably transform an existing column or constraint. A
later production stage would introduce Alembic or another explicit migration
workflow.

## Relational Schema

The chapter adds four tables:

```text
conversation_sessions
    ├── conversation_messages
    └── conversation_events

agent_session_states
```

### `conversation_sessions`

One row represents the readable metadata and ownership boundary of a shopping
conversation:

```text
session_id      primary key
buyer_id        owner lookup
locale          latest session locale
currency        latest session currency
created_at      original creation time
last_active_at  most recent touch
```

Messages and events reference this table with foreign keys. They cannot be
inserted for an unknown conversation when foreign-key enforcement is enabled.

### `conversation_messages`

Each row stores one readable buyer or Agent turn. It has a global surrogate
`id` and a conversation-local `turn_index`.

The pair `(session_id, turn_index)` is unique. Two rows therefore cannot occupy
the same position in one conversation, while different conversations can each
have turn zero.

The explicit composite index documents and supports the ordered session query.
SQLite may also create an internal index for the unique constraint; production
query-plan measurements can later decide whether maintaining both is useful.

### `conversation_events`

Events remain separate from chat messages. Their payload uses SQLAlchemy's
`JSON` type, preserving structured tool, error, and final-result data without
turning execution observations into user-visible dialogue.

### `agent_session_states`

This table stores the opaque serialized snapshot used by `SessionRegistry`.
The snapshot already contains the buyer ownership envelope from Chapter 16.

It deliberately has no foreign key to `conversation_sessions`. `SessionStore`
and `ConversationStore` are independent ports, so saving Agent state must not
depend on conversation logging succeeding first.

## Portable Autoincrement Primary Keys

Message and event IDs are declared with:

```python
BigInteger().with_variant(Integer, "sqlite")
```

Production databases commonly use `BIGINT` for growing identifiers. SQLite,
however, gives its special rowid-backed autoincrement behavior specifically to
an `INTEGER PRIMARY KEY`. The type variant preserves the intended large type on
other dialects while emitting the SQLite-compatible type in this chapter.

## `SqlSessionStore`

Agent snapshots have replacement semantics: one session has one current
snapshot. `save()` therefore uses SQLite's native UPSERT:

```text
INSERT new session state
    ON CONFLICT(session_id)
    DO UPDATE snapshot_json and updated_at
```

This is a single atomic SQL statement and avoids a separate “check whether the
row exists” query. Using `sqlalchemy.dialects.sqlite.insert` is appropriate in
Infrastructure because the adapter is intentionally SQLite-specific.

`updated_at` is included explicitly in the conflict update. SQLAlchemy column
`onupdate` behavior is not automatically applied to values inside SQLite's
`ON CONFLICT DO UPDATE` clause.

`load()` uses `AsyncSession.get()` because `session_id` is the primary key. The
Store returns the opaque JSON string required by the Domain port, never the ORM
row.

## `SqlConversationStore`

### Touching session metadata

`touch_session()` reads the session row by primary key. It inserts new metadata,
updates locale/currency/activity for the same buyer, and rejects a different
buyer. The `session_factory.begin()` context commits normally and rolls back if
ownership validation raises.

### Appending turns

`append_turn()` finds the largest `turn_index` for the session and stores the new
turn at the next position:

```text
no earlier turn   → 0
largest index 0   → 1
largest index 17  → 18
```

The current orchestrator's per-session lock serializes this calculation inside
one process. The database unique constraint provides a final integrity check.
Cross-process allocation still needs a stronger strategy before production.

### Reading the newest turns

To return the latest `limit` rows efficiently, SQL first orders by
`turn_index DESC` and applies the limit. Python then reverses that small result
so the caller receives normal reading order:

```text
database result   turn 9, turn 8, turn 7
returned history turn 7, turn 8, turn 9
```

Applying the limit before reversing avoids loading an entire long conversation.

### Appending event batches

`append_events()` verifies that all records belong to one session and adds them
inside one transaction. If one JSON payload cannot be serialized, the whole
batch rolls back; a partial trace is not committed.

### Mapping timestamps

Domain records use timezone-aware ISO strings. SQLite can return naive
`datetime` values even when `DateTime(timezone=True)` is declared. The adapter
therefore normalizes incoming timestamps to UTC and restores an explicit UTC
offset when mapping rows back to Domain records.

This conversion belongs in the adapter because it handles a database-specific
representation mismatch.

## Composition and Lifecycle

Configuration accepts an optional `DATABASE_URL`. When omitted, it uses:

```text
<resolved DATA_DIR>/globex.db
```

The Composition Root creates one engine and one session factory, then injects
that same factory into `SqlSessionStore` and `SqlConversationStore`.

Application startup runs schema bootstrap before serving traffic. Shutdown uses
nested `finally` blocks so the database engine is disposed even if vector-store
cleanup fails.

The production path is now:

```text
FastAPI/CLI startup
    → bootstrap SQLite schema
    → start vector and knowledge resources

request
    → Orchestrator
        → SqlSessionStore
        → SqlConversationStore

FastAPI/CLI shutdown
    → close vector resources
    → dispose AsyncEngine
```

## Recovery Proof

The integration test does not merely construct two Stores around the same live
objects. It:

1. creates the first engine and runs one Agent turn;
2. persists AgentState, conversation metadata, messages, and events;
3. fully disposes the first engine;
4. creates a second engine, session factory, Stores, and SessionRegistry for the
   same database file; and
5. verifies restored Agent context and readable history.

This proves persistence across connection and object lifetimes. It is the same
essential boundary exercised by a backend restart.

## JSON Files Compared with SQLite

```text
Concern                 Chapter 16 files          Chapter 17 SQLite
----------------------  ------------------------  ----------------------------
Snapshot replacement    overwrite one JSON file   primary-key UPSERT
Conversation writes     append JSONL lines         transactional INSERT rows
Ownership lookup        scan latest metadata       primary-key indexed lookup
History limit           read file then slice       ORDER BY + LIMIT in SQL
Integrity               application checks         FK and unique constraints
Batch atomicity          not guaranteed             database transaction
Concurrent access        weak                       locks + timeout + constraints
Schema evolution         implicit record shapes     explicit schema (no migration yet)
```

The file adapters remain useful test/reference implementations. Switching the
Composition Root does not require deleting them.

## Verification

The completed implementation was checked with:

```text
backend regression suite: 267 passed
```

The tests cover:

- schema bootstrap idempotency and data preservation;
- automatic creation of a missing database directory;
- SQLite PRAGMA configuration;
- foreign-key and unique-turn constraints;
- snapshot insert, load, UPSERT, and timestamp refresh;
- conversation metadata ownership and refresh;
- ordered latest-N history and UTC normalization;
- structured event persistence and transaction rollback;
- default and explicit database configuration;
- FastAPI/Container lifecycle compatibility; and
- AgentState plus readable-history recovery through a new engine.

## Current Limitations

- Only `sqlite+aiosqlite` URLs are supported.
- `create_all()` cannot replace a real schema migration tool.
- `max(turn_index) + 1` is protected by an in-process lock, not a distributed
  allocator or retry strategy.
- WAL still permits only one writer at a time.
- Existing Chapter 16 JSON/JSONL files are not automatically imported.
- Orders, inventory, and products still use in-memory repositories.
- Conversation events are persisted but are not queryable or replayable through
  the API.
- There is no retention, archival, backup, encryption-at-rest, or database
  observability policy yet.
- Buyer IDs are still client-provided identifiers rather than authenticated
  principals.

Chapter 18 can now build long-term buyer memory on durable storage while keeping
preferences separate from per-session AgentState and conversation history.
