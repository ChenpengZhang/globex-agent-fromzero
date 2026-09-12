# Globex Agent From Zero

English | [简体中文](README.zh-CN.md)

An educational rebuild of a complete cross-border commerce Agent, developed chapter by chapter from a minimal MVP.

The project references the complete `globex-agent` repository in the parent directory, but does not import it as a runtime dependency. Each capability is reimplemented in isolation so its purpose, DDD boundary, tests, and trade-offs remain understandable before the next layer is introduced.

## Goals

- Learn Agent development without starting from a production-sized codebase.
- Preserve the original project's DDD architecture and core design intent.
- Keep every chapter runnable, testable, and explainable.
- Keep deterministic business rules out of the LLM.
- Progress gradually from one Agent to a full-stack, production-oriented system.

## Design Principles

- Domain code does not depend on AgentScope, FastAPI, databases, or caches.
- Application UseCases coordinate business workflows and domain aggregates.
- Agent Tools are thin adapters around UseCases, not containers for business rules.
- Infrastructure implements replaceable ports defined by the inner layers.
- The Composition Root is the only module that knows all concrete implementations.
- Prices, inventory, ownership, and order state are validated by deterministic code.
- Every chapter receives automated tests and separate Chinese and English notes.

## Relationship to the Reference Project

```text
globex-agent/            Complete reference implementation
globex-agent-fromzero/   Incremental learning implementation
```

The reference project helps verify architectural direction. The from-zero project remains independent and may use simpler implementations until a later chapter introduces the production mechanism.

## Current Architecture

```text
app/
├── domain/          Business objects, invariants, state machines, ports
├── application/     UseCases, application DTOs, Agents, Tools
├── infrastructure/  LLM and persistence adapters
├── presentation/    CLI and HTTP boundaries
└── composition.py   Dependency assembly
```

The current product-search request path is:

```text
CLI / HTTP
    ↓
MainAgentOrchestrator
    ↓
SessionRegistry
    ↓
Session-scoped MainAgent
    ↓
Product Search FunctionTool
    ↓
CatalogSearchUseCase
    ↓
ProductRepository
    ↓
InMemoryProductRepository
```

The category-knowledge RAG path is:

```text
Markdown knowledge → chunking → embedding → Qdrant
                                           ↑
User → Agent → category_insight_tool → query embedding
                                      ↓
                         content + source + score
```

Concrete product retrieval now uses an explicit tiered pipeline:

```text
embedding + Qdrant → optional reranker → deterministic hard filters
        ↓ failure          ↓ failure
   keyword 2-gram     vector order
```

The order side currently contains:

```text
Order aggregate
└── Order (aggregate root and state machine)
    ├── Address (shipping snapshot)
    └── OrderLine × N (product and price snapshots)
        └── Money (monetary operations)

OrderRepository (Domain port)
    ↓
InMemoryOrderRepository + Application DTOs
    ↓
Place / Query / Cancel Order UseCases
```

Long-term buyer memory now follows a separate durable path:

```text
remember / forget tool → PreferenceStore → SQLite buyer_preferences
                                              ↓
new request → PreferenceSelector → buyer-scoped hint → MainAgent
                                                   └→ SearchAgent when dispatched
```

## Current Capabilities

- Minimal single-Agent runtime and real ChatModel integration.
- Product, SKU, Money, and repository abstractions.
- Deterministic keyword and Chinese 2-gram catalog retrieval.
- Product Search FunctionTool and ReAct integration.
- Application Orchestrator and DTO boundary.
- FastAPI HTTP boundary.
- Session-scoped AgentState isolation and buyer binding.
- Address, OrderLine, Order state machine, and OrderRepository port.
- Deterministic place/query/cancel flows with inventory compensation.
- Request-scoped ShoppingContext and order Agent Tools.
- SearchAgent, TradeAgent, and context-isolated task dispatch.
- Category-knowledge RAG with Markdown chunking and Qdrant.
- Explicit separation between selection knowledge and product facts.
- Product-vector indexing, optional reranking, and explicit fallbacks.
- Typed realtime events, token streaming, and session-scoped WebSocket delivery.
- Responsive React shopping chat with HTTP submission and WebSocket streaming.
- Persistent browser buyer/session identities, reconnect handling, and event timeline.
- Buyer-scoped long-term preferences stored in SQLite across sessions and restarts.
- Explicit remember/forget tools, safe exact deletion, and relevance-aware hint selection.
- Preference hints for MainAgent and SearchAgent without exposing buyer identity to tools.
- Offline tests for Domain, UseCases, Tools, RAG, HTTP, and sessions.

The current suite contains 315 passing backend tests. The frontend also passes its
TypeScript and production Vite build.

## Setup

The project uses Python, uv, AgentScope, and FastAPI.

Configure an OpenAI-compatible model endpoint:

```bash
export LLM_BASE_URL=<OpenAI-compatible endpoint>
export LLM_API_KEY=<api key>
export LLM_MODEL=<model name>
```

Configure an OpenAI-compatible embedding model. It reuses the LLM
endpoint and key unless separate embedding credentials are provided:

```bash
export EMBEDDING_MODEL=<embedding model name>
export EMBEDDING_DIM=<vector dimensions>
```

Reranking is optional. Leave its URL empty to use vector order:

```bash
export RERANKER_BASE_URL=<rerank endpoint root>
export RERANKER_MODEL=<reranker model name>
```

Run the CLI:

```bash
uv run python -m app.presentation.cli
```

Run the HTTP API:

```bash
uv run uvicorn app.presentation.server:build_app --factory
```

In another terminal, run the React frontend:

```bash
cd frontend
npm install
npm run dev
```

Then open `http://127.0.0.1:5173`. Vite proxies both HTTP and WebSocket
`/commerce` traffic to the backend on port 8000.

Run the test suite:

```bash
uv run pytest
```

Do not commit real API keys or other secrets.

## Roadmap

| Chapter | Status | Scope |
|---|---|---|
| 1. Minimal Agent | Complete | Settings, ChatModel, MainAgent, CLI, Composition |
| 2. Catalog Domain | Complete | Money, SKU, Product, repository port and seed data |
| 3. Deterministic Retrieval | Complete | Search specification and keyword retrieval UseCase |
| 4. Agent Tool | Complete | FunctionTool, Toolkit, ReAct, offline fake model |
| 5. Application Boundary | Complete | Orchestrator and application DTOs |
| 6. HTTP API | Complete | FastAPI DTOs, app factory, error boundary |
| 7. Multi-Session Isolation | Complete | Agent factory, session registry, buyer binding, locks |
| 8. Order Domain | Complete | Address, OrderLine, Order state machine, repository port |
| 9. Order Transaction Flow | Complete | Inventory compensation, repository adapter, order UseCases |
| 10. Order Agent Tools | Complete | Transaction tools and end-to-end Agent integration |
| 11. Sub-Agents | Complete | SearchAgent, TradeAgent, task dispatch and isolation |
| 12. Category-Knowledge RAG | Complete | Markdown ingestion, embeddings, Qdrant, knowledge tool |
| 13. Tiered Product Retrieval | Complete | Product embeddings, reranking, explicit fallbacks |
| 14. Realtime Events | Complete | Typed events, streaming, WebSocket delivery |
| 15. Frontend | Complete | React chat, streaming, session identity, prepared cards, event timeline |
| 16. File Persistence and Recovery | Complete | JSON session snapshots, JSONL conversations, history recovery |
| 17. Relational Database Persistence | Complete | Async SQLAlchemy, SQLite schema, database adapters, composition switch |
| 18. Long-Term Buyer Memory | Complete | Preferences, remember/forget tools, relevance selection, hint injection |
| 19. Redis and Async Work | Planned | Caches, idempotency, queue, cross-process events |
| 20. Production Hardening | Planned | Resilience, tracing, auth, evaluation, deployment |
| 21. Codebase Hardening | Planned | Composition cleanup, duplication reduction, typing, linting, and structural consolidation |

The fixed high-level path is:

```text
Order transaction flow
→ Order Agent Tools
→ Sub-Agents
→ RAG and tiered retrieval
→ WebSocket events
→ React frontend
→ File persistence and conversation recovery
→ Relational database persistence
→ Long-term buyer memory
→ Redis caching, idempotency, and queues
→ Production hardening, evaluation, and deployment
→ Codebase hardening and structural consolidation
```

## Documentation

Each completed chapter has separate Chinese and English design notes:

```text
docs/chapter-XX.zh-CN.md
docs/chapter-XX.en.md
```

The notes explain the chapter's goal, design decisions, boundaries, tests, limitations, and next direction.
