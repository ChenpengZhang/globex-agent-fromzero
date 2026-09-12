# Chapter 18: Long-Term Buyer Memory

## Goal

Chapter 18 adds durable, buyer-scoped preferences to the commerce Agent. A buyer can explicitly ask the Agent to remember a stable preference, use it in later shopping sessions, and withdraw it later.

This is different from conversation history:

- conversation history belongs to a shopping session;
- long-term preferences belong to a buyer;
- restarting the process must not erase either one;
- one-time requirements must remain in the current conversation instead of becoming long-term memory.

The chapter follows the reference project's two-path design:

```text
write path: model → remember/forget tool → PreferenceStore → database
read path:  Orchestrator → PreferenceStore → PreferenceSelector → Agent hint
```

The model decides when an explicit user statement should invoke a memory tool. Deterministic code owns buyer identity, validation, persistence, isolation, deletion, selection limits, and failure behavior.

## Scope

Implemented in this chapter:

- `BuyerPreference` domain object;
- `PreferenceStore` domain port;
- SQLAlchemy table and SQLite adapter;
- remember and forget FunctionTools;
- request-scoped buyer identity through `ShoppingContext`;
- preference selection with optional embedding relevance;
- hint injection into MainAgent and SearchAgent;
- configuration and composition-root wiring;
- unit, integration, isolation, fallback, and cross-session tests.

Not introduced yet:

- Redis caching;
- asynchronous preference extraction;
- automatic inference from every conversation;
- preference editing or semantic merging;
- expiration and administrative moderation;
- distributed cache invalidation.

## DDD Boundaries

### Domain

The Domain contains the meaning and persistence contract:

```text
app/domain/buyer/preference.py
app/domain/buyer/ports/preference_store.py
```

`BuyerPreference` contains:

- `buyer_id` — the durable owner;
- `kind` — `like` or `dislike`;
- `statement` — a standalone preference sentence;
- `created_at` — an immutable creation timestamp.

The object trims identity and statement values and rejects empty identities, empty statements, and unsupported kinds.

`PreferenceStore` exposes only persistence operations:

```python
append(preference)
list_by_buyer(buyer_id)
delete(buyer_id, statement)
```

Relevance search is deliberately absent from this port. If vector ranking were placed on `PreferenceStore`, every persistence adapter would be forced to know about embedding models. Relevance is an application policy, not a persistence responsibility.

### Application

The Application layer contains:

- memory tools that translate Agent calls into domain operations;
- `PreferenceSelector`, which chooses the useful subset for the current request;
- Orchestrator input enrichment;
- SearchAgent dispatch enrichment;
- static prompt rules describing when tools may be called.

### Infrastructure

The Infrastructure layer contains:

- `buyer_preferences` SQL table;
- `SqlPreferenceStore`;
- existing embedding client reused by optional relevance ranking;
- environment settings.

### Composition root

`app/composition.py` creates one preference store and one selector and shares them with tools, task dispatch, and the Orchestrator. This is intentionally explicit. The composition root is allowed to know the domain ports and their concrete infrastructure adapters.

## Persistence Model

The SQL table stores:

```text
id
buyer_id
kind
statement
created_at
```

Important database rules:

- `kind` is constrained to `like` or `dislike`;
- `(buyer_id, kind, statement)` is unique;
- duplicate appends are idempotent;
- reads are ordered by insertion ID;
- deletion is scoped by buyer and exact statement.

The triple uniqueness rule allows two buyers to own the same sentence while preventing repeated tool calls from creating duplicate rows for one buyer and kind.

## Why SQLite, Not Redis

Long-term memory is source-of-truth data. Redis is valuable for acceleration and cross-process coordination, but a cache should not be the only durable owner of buyer preferences.

This chapter therefore writes preferences to SQLite through `PreferenceStore`. Chapter 19 may add Redis in front of the store, but the database remains authoritative:

```text
request → optional Redis cache → PreferenceStore → relational database
```

If Redis is flushed or unavailable, buyer memory can still be rebuilt from the database.

## Write Path: Remembering

The prompt permits `remember_preference_tool` only when the buyer explicitly expresses a stable preference that is expected to survive across purchases.

Examples suitable for memory:

- "I avoid plastic materials."
- "I generally prefer minimalist designs."
- "I usually choose lightweight travel products."

Examples that should remain conversation-only:

- "This time I want a red one."
- "My budget today is 300 CNY."
- "Ship this order to Shanghai."

The tool accepts only:

```text
kind
statement
```

It does not accept `buyer_id` or `shopping_session_id`. Both values come from the trusted `ShoppingContext`, preventing the model from writing memory for another buyer.

The tool publishes `tool.invoke` and `tool.result` events, validates the domain object, writes through the port, and only reports success after persistence succeeds.

## Delete Path: Forgetting

`forget_preference_tool` removes a statement only when the buyer explicitly withdraws a durable preference.

Deletion is intentionally exact:

```text
buyer_id + exact statement
```

Fuzzy deletion would be dangerous because two similar statements can have different meanings. The prompt requires the model to copy the original statement from the injected preference block.

If no exact row exists, the tool does not guess. It returns success with a clear "nothing deleted" result and lists the remaining statements so the model can ask for or use the exact text.

## Read Path and Selection

Before MainAgent handles a request, the Orchestrator loads preferences using the current `buyer_id` and calls:

```python
PreferenceSelector.select(
    preferences=preferences,
    query=current_query,
    top_k=configured_top_k,
)
```

Selection treats the two kinds differently:

- every `dislike` is retained because it represents a restriction or blacklist;
- `top_k` limits only `like` preferences;
- when the number of likes already fits, no embedding call is made;
- with relevance disabled, the most recently created likes are selected;
- with relevance enabled, likes are ranked by cosine similarity to the current query;
- embedding errors, length mismatches, or vector-dimension mismatches fall back to recency.

This preserves safety constraints while bounding the amount of soft personalization injected into context.

## Embedding Calls

The selector reuses the existing `EmbeddingClient` abstraction. Embeddings may therefore come from the configured online OpenAI-compatible API, but they are not required by default.

Default configuration:

```dotenv
PREFERENCE_RELEVANCE_ENABLED=0
PREFERENCE_TOP_K=5
PREFERENCE_SUBAGENT_INJECT=1
```

With relevance disabled, preference selection does not make an extra embedding API call. When enabled and more likes exist than `top_k`, the selector embeds the candidate statements as a batch and embeds the current query once.

No fine-tuning is required. This is retrieval-time similarity, not model training.

## Hint Injection and Prompt Caching

Selected preferences are rendered as a separate user-style internal message:

```text
<buyer-preferences>
- [dislike] Avoid plastic materials
- [like] Prefer minimalist design
</buyer-preferences>
```

They are not interpolated into the static system prompt. Keeping the large system prefix stable is friendlier to provider-side prompt caching, while the short buyer-specific hint remains dynamic.

The readable conversation store receives only the buyer's original query and the Agent's final reply. Internal memory hints are not shown as buyer messages in conversation history.

Within one active session, an unchanged rendered hint is not injected repeatedly. The existing Agent state already contains the earlier hint.

## MainAgent and Sub-Agent Policy

MainAgent receives relevant buyer preferences because it decides how to answer, search, recommend, and dispatch.

SearchAgent also receives the preference hint when a complex search task is dispatched. It cannot see MainAgent's conversation history, so server-side injection prevents the parent model from having to copy hidden memory into `demands`.

TradeAgent does not receive preference hints. A transaction specialist should execute already-confirmed product IDs, SKUs, quantities, addresses, and order commands. Soft recommendation preferences must not reinterpret a confirmed transaction.

## Failure Policy

Long-term personalization is useful but is not required to complete an ordinary shopping request. Therefore:

- preference read failures are logged and the Agent continues without a hint;
- relevance failures fall back to recency;
- SearchAgent injection failures do not block dispatch;
- write and delete failures return explicit tool errors and must not be described as successful.

This distinction keeps optional enrichment fail-open while keeping memory mutations fail-closed.

## Request Flows

Remembering:

```text
Buyer statement
→ MainAgent chooses remember_preference_tool
→ ShoppingContext supplies buyer/session identity
→ BuyerPreference validation
→ SqlPreferenceStore.append
→ buyer_preferences
```

Reading in another session:

```text
New shopping_session_id + same buyer_id
→ Orchestrator loads buyer preferences
→ PreferenceSelector
→ <buyer-preferences> hint
→ MainAgent
→ optional SearchAgent dispatch with the same selected memory
```

Forgetting:

```text
Buyer explicitly withdraws preference
→ MainAgent copies exact stored statement
→ forget_preference_tool
→ buyer-scoped exact delete
→ later new sessions no longer receive that preference
```

## Tests

The chapter adds coverage for:

- domain normalization, validation, timestamping, and immutability;
- SQL round trips, ordering, idempotency, buyer isolation, and constraints;
- remember/forget schemas, context identity, events, failures, and exact deletion;
- dislike retention, like limits, relevance ranking, and safe fallbacks;
- MainAgent injection, session behavior, history cleanliness, and read failures;
- SearchAgent-only injection and buyer isolation;
- settings defaults and invalid values;
- real Agent tool calls through composition and SQLite;
- remember, cross-session read, forget, and post-delete behavior;
- regression coverage for order and sub-Agent flows.

At chapter completion, the backend suite contains 315 passing tests.

## Known Limitations

- The model still decides whether a statement is stable enough to remember; there is no deterministic confirmation workflow yet.
- Preferences are atomic statements rather than structured attributes with confidence, provenance, or expiration.
- Deletion is exact and does not support semantic matching.
- Dislikes are intentionally unbounded, so a buyer with an extreme number of restrictions could create a large hint.
- An already-active Agent session can retain an older hint in its historical state after a preference changes; a newly created session always reads the current database state. State compaction and stale-hint replacement belong in later hardening.
- There is no Redis cache, distributed invalidation, or cross-process memory event yet.

## Next Direction

Chapter 19 introduces Redis and asynchronous work for caching, idempotency, queues, and cross-process events while keeping the relational database authoritative.

The roadmap also reserves Chapter 21 for codebase hardening. That final structural pass can shorten the composition root, reduce duplication, strengthen typing and linting, and consolidate module boundaries after the behavior is fully learned.
