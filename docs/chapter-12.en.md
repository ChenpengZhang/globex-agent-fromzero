# Chapter 12: Category-Knowledge RAG

## Goal

This chapter adds the first real RAG path inside the SearchAgent boundary introduced in Chapter 11. The Agent can now answer “how should I choose?” questions instead of only searching deterministic seed products.

The minimum closed loop is:

```text
knowledge/*.md
→ TextParser
→ ApproxTokenChunker
→ Embedding API
→ Qdrant

user question
→ SearchAgent / MainAgent
→ category_insight_tool
→ KnowledgeBase.search
→ query embedding + vector similarity
→ ToolResult (content/source/score)
→ final Agent response
```

The design follows the category-knowledge structure of the complete reference project. Product-vector retrieval, reranking, and tiered fallbacks remain separate work for the next chapter.

## Two Retrieval Problems

The system now has two retrieval paths with different meanings.

Category-knowledge retrieval answers questions about selection criteria, important attributes, reference price ranges, and common pitfalls. Its results cannot prove that a product exists, is available, has inventory, or ships to a destination.

Concrete product retrieval answers which products satisfy a request. It reads the catalog repository and applies deterministic price, stock, and shipping constraints.

SearchAgent therefore follows this routing rule:

```text
“how should I choose?”                 → category_insight_tool
“which concrete products are there?”   → product_search_tool
“teach me, then recommend products”     → knowledge tool, then product tool
```

Embeddings are useful for semantic relevance. They must not enforce hard constraints such as a price ceiling, positive inventory, or destination eligibility. Those rules remain in deterministic UseCases and Domain code.

## DDD Boundaries

The category knowledge base is Infrastructure:

```text
Infrastructure
└── rag/category_knowledge.py
    ├── OpenAIEmbeddingModel
    ├── QdrantStore
    ├── TextParser
    └── ApproxTokenChunker

Application
├── tools/category_insight_tool.py
└── agents/search_agent.py
```

Embedding providers, Qdrant, and file parsing are replaceable technical details rather than commerce rules.

`category_insight_tool` belongs to Application because it adapts retrieval into an Agent-callable operation. It validates input, invokes the knowledge base, and shapes the result. It does not define product, inventory, pricing, or order rules.

The chapter does not invent an empty Domain knowledge entity solely for architectural symmetry. The current knowledge is read-only decision support and has no aggregate invariants to protect.

## Construction Versus Startup

`build_category_knowledge_base(settings)` only constructs dependencies:

- The embedding model.
- A local or remote Qdrant store.
- The AgentScope `KnowledgeBase`.

It does not open resources or ingest documents. `Container.startup()` performs runtime initialization:

```text
build_container()
→ assemble the dependency graph

container.startup()
→ open the vector store
→ bootstrap_category_knowledge()
→ ensure the collection exists
→ ingest Markdown documents not already present
```

This keeps Composition synchronous and testable while allowing CLI and FastAPI to own resource lifecycles correctly. CLI uses `try/finally`; FastAPI uses its lifespan context. Both guarantee `Container.shutdown()`.

## How Documents Become Vectors

For every Markdown document, bootstrap performs four steps:

1. `TextParser.parse` converts the file into structured text sections.
2. `ApproxTokenChunker` splits the sections using an approximate size of 512 tokens and an overlap of 50.
3. `KnowledgeBase.insert_document` asks the embedding model to convert each chunk into a vector.
4. Qdrant stores text, vectors, and metadata together.

Chunk text has two concrete jobs. During ingestion it is the embedding input and the original evidence retained for later use. During retrieval the matching chunk text is returned to the Agent through ToolResult.

Storing only vectors would leave the Agent with similarity coordinates and scores but no source text from which to answer.

## Where Embedding Actually Happens

The application does not implement vector arithmetic locally. `OpenAIEmbeddingModel` calls an OpenAI-compatible `/embeddings` endpoint:

```text
document ingestion: insert_document(chunks)
                  → embed each chunk through the API

knowledge query:   knowledge_base.search(queries)
                  → embed the user question through the API
                  → let Qdrant compare query and document vectors
```

Embedding reuses the LLM gateway URL and key by default. `EMBEDDING_BASE_URL` and `EMBEDDING_API_KEY` can select a separate provider.

Fine-tuning is normally unnecessary at this stage. A better optimization order is to improve source documents, tune chunking, improve query formulation, add hybrid retrieval and reranking, and establish an evaluation set. Training or fine-tuning should come only after evidence shows that a general embedding model cannot distinguish the required domain semantics.

Indexing and querying must use the same embedding model and dimensions. Changing either invalidates compatibility with the existing collection and requires reindexing or a migrated collection.

## Chunking Trade-offs

The current approximate 512/50 token strategy is an MVP compromise:

- Larger chunks preserve context but mix topics, reduce retrieval precision, and cost more tokens.
- Smaller chunks focus matching but can fragment conditions and exceptions.
- Overlap preserves boundary context but increases vector count and duplicate hits.

A production system may split by Markdown headings, tables, or semantic boundaries, but evaluation should justify that complexity first.

## Idempotent Ingestion and Source Metadata

The Markdown filename stem becomes a stable `document_id`. Startup reads existing IDs and ingests only missing documents:

```text
travel-gear.md → document_id = "travel-gear"
```

Repeated starts therefore do not duplicate documents or embedding calls.

Each document retains `source` metadata, and the tool returns a traceable structure:

```json
{
  "insights": [
    {
      "content": "...",
      "source": "travel-gear.md",
      "score": 0.9133
    }
  ]
}
```

The source supports traceability; the score supports debugging and future thresholds. A similarity score is not factual confidence and must not be read as a 91.33% probability that a statement is true.

The current idempotency rule only detects an existing document ID. It does not notice changed content under the same filename, which is an explicit MVP limitation.

## Local and Remote Qdrant

With an empty `QDRANT_URL`, qdrant-client uses local storage at:

```text
.data/qdrant_category_knowledge
```

This is convenient for single-process learning and debugging. Setting `QDRANT_URL` switches to a remote Qdrant service suitable for shared indexes across application instances.

Both modes expose the same `KnowledgeBase` and tool interface, so Agents do not know how the store is deployed.

## Why Reuse AgentScope KnowledgeBase

Compared with calling qdrant-client directly, AgentScope `KnowledgeBase` provides one collaboration model for documents, chunks, embeddings, and vector stores. This follows the reference project and avoids unnecessary infrastructure boilerplate in the learning chapter.

The trade-off is that Application currently type-annotates AgentScope `KnowledgeBase`, so the framework is not completely hidden. If multiple RAG frameworks become necessary, Application can define a `CategoryKnowledgeRetriever` port implemented by Infrastructure. The MVP avoids that extra abstraction while only one implementation exists.

## Failure and Degradation

If startup ingestion fails, `bootstrap_category_knowledge` logs a warning and returns zero, allowing catalog and order capabilities to start. If a runtime knowledge query fails, the tool returns an explicit `[error]` and instructs the Agent not to guess.

This is explicit degradation: capabilities independent of RAG remain available, but retrieval failure is never silently presented as “no relevant knowledge.” The next chapter will apply the same principle to tiered product retrieval.

## Tests

Chapter coverage includes:

- Deterministic offline embeddings without real API calls.
- Markdown ingestion and document metadata.
- Idempotent bootstrap without duplicate insertions or embeddings.
- Query embedding and relevant chunk retrieval.
- Startup degradation when Qdrant is unavailable.
- `category_insight_tool` schema, validation, and error results.
- ToolResult content, source, and score.
- SearchAgent → category tool → ToolResult → final answer.
- FastAPI lifespan opening, initializing, and closing the vector store.
- Regression coverage for catalog, order, session, and sub-Agent flows.

The complete suite after this chapter is:

```text
172 passed
```

## Current Limitations

- Only one sample category document exists.
- Modified content under an existing document ID is not reindexed automatically.
- There is no similarity threshold, deduplication, or citation presentation layer.
- Real embedding integration is intentionally not part of automated tests, avoiding network dependencies and cost.
- Product Search still uses deterministic keyword and Chinese 2-gram matching.
- Product-vector retrieval, reranking, and an explicit fallback chain are not implemented yet.

The next chapter adds embedding, reranking, and fallback strategies to concrete product retrieval without changing the category-knowledge tool boundary.
