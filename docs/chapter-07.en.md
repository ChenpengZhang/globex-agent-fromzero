# Chapter 7: Multi-Session Isolation

## Goal

This chapter turns `shopping_session_id` from a passive request field into a real conversation routing key. Each new session receives an independent MainAgent and AgentState, while later requests for the same session reuse the existing Agent.

```text
MainAgentFactory
    ↓
SessionRegistry
├── session-A / buyer-A → Agent A → AgentState A
├── session-B / buyer-A → Agent B → AgentState B
└── session-C / buyer-B → Agent C → AgentState C
```

## MainAgentFactory

The Factory stores model and tool construction dependencies and creates Agents consistently through `build()`. SessionRegistry does not need to know prompts, Toolkit configuration, or ReAct settings.

Agents may share a stateless model client and read-only tools, but every `build()` call creates a new Agent and AgentState.

The roles are distinct: an Agent is a stateful runtime instance, while the Factory is a stateless creation policy.

## SessionRegistry

The Registry stores a `shopping_session_id → SessionEntry` mapping. Each SessionEntry contains:

- Session ID
- Bound buyer ID
- Independent Agent
- Per-session execution lock

The same session and buyer receive the same SessionEntry. A different session causes the Factory to create a different Agent.

## Buyer Binding

A session is bound to its buyer when first created. Reuse by another buyer raises `SessionOwnershipError`, which the HTTP layer maps to 409 Conflict.

This is consistency protection, not authentication. Buyer ID still comes from an untrusted request body. A real system must derive it from a trusted login token.

## Concurrency Control

The Registry uses a creation lock with a double check so concurrent first requests cannot create multiple Agents for the same session.

Each SessionEntry also has an execution lock. Requests for the same session modify AgentState sequentially, while different sessions can execute concurrently using different locks.

## Orchestrator

The Orchestrator no longer owns one global Agent. It first retrieves a SessionEntry by session and buyer, then calls that Agent while holding the session execution lock.

```text
SubmitIntentInput
    ↓
SessionRegistry.get_or_create()
    ↓
SessionEntry.execution_lock
    ↓
SessionEntry.agent.reply()
```

## Lazy Creation

The Container starts with zero sessions. An Agent is created only when a new session request arrives, avoiding state allocation for conversations that do not exist.

## Tests and Validation

All 37 tests pass. New coverage verifies:

- Reuse of one Agent for the same session and buyer.
- Different Agents and AgentStates for different sessions.
- Rejection of session reuse by another buyer.
- One SessionEntry under 20 concurrent creation requests.
- Isolation of private context between sessions.
- Preservation of multiple turns in one session.
- HTTP 409 mapping for ownership conflicts.

## Current Limitations

- The Registry exists only in the current Python process.
- All sessions disappear when the service restarts.
- Multi-process or multi-instance deployments have separate Registries.
- There is no session expiration or cleanup, so memory usage grows over time.
- Buyer identity is not authenticated.

## Next Chapter

The next chapter begins the order Domain with Address, OrderLine, an Order aggregate state machine, and an OrderRepository port. Session persistence will be introduced separately in a later storage chapter.
