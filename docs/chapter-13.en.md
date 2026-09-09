# Chapter 13: Tiered Product Retrieval

## Goal

This chapter extends the deterministic keyword search from Chapter 3 into a degradable, two-stage product retrieval pipeline:

```text
embedding_rerank
    ↓ reranker absent or failed
embedding_only
    ↓ embedding or Qdrant failed
keyword_2gram
```

Category knowledge and product retrieval remain separate systems. `category_insight_tool` retrieves Markdown knowledge for “how should I choose?” questions. `product_search_tool` retrieves real Product candidates for “what can I buy?” questions.

Caching, BM25, landed-price calculation, and large-scale offline evaluation remain out of scope. The chapter focuses on the distinct responsibilities of embeddings, the vector index, reranking, hard constraints, and fallbacks.

## End-to-End Data Flow

Startup indexing:

```text
ProductRepository.list_all()
→ Product.searchable_text()
→ EmbeddingClient.embed_batch()
→ ProductVectorIndex.ensure_ready()
→ ProductVectorIndex.upsert_products()
→ Qdrant
```

Query execution:

```text
normalized_query
→ EmbeddingClient.embed()
→ ProductVectorIndex.search(top_n=8)
→ VectorHit(product_id, score)
→ ProductRepository.find_by_ids()
→ optional Reranker
→ price/currency/shipping hard filters
→ top_k
→ ProductCard
```

Qdrant only finds candidate IDs. The product repository remains the source of truth for prices, SKUs, inventory, and shipping facts.

## Retrieval Ports and DDD

Catalog Domain ports describe three capabilities:

```text
EmbeddingClient
├── embed(text)
└── embed_batch(texts)

ProductVectorIndex
├── ensure_ready(vector_dim)
├── upsert_products(products, embeddings)
└── search(embedding, top_n)

Reranker
└── rerank(query, documents)
```

Infrastructure supplies concrete adapters:

```text
OpenAIEmbeddingClient → OpenAI-compatible /embeddings
QdrantProductIndex    → qdrant-client
HttpReranker          → /rerank HTTP protocol
```

The UseCase depends only on ports and knows nothing about URLs, HTTP JSON, Qdrant points, or third-party SDK objects. The Composition Root selects adapters from configuration.

A stricter layering interpretation could place these interfaces in Application ports because retrieval orchestration is not a Product aggregate invariant. This project retains the reference implementation's `domain/catalog/ports` organization and treats them as capabilities required by the Catalog subdomain.

## OpenAI-Compatible Embedding Adapter

Product retrieval uses its own `EmbeddingClient` port rather than importing an AgentScope embedding type. Infrastructure calls:

```text
POST {EMBEDDING_BASE_URL}/embeddings
{
  "model": "...",
  "input": ["product text 1", "product text 2"]
}
```

Responses are restored by `index` so vectors remain aligned with input texts. Requests are split into batches of ten to avoid compatible gateways that return an empty body for larger batches.

Chapter 12's `OpenAIEmbeddingModel` serves AgentScope KnowledgeBase. This chapter's `OpenAIEmbeddingClient` serves the project's retrieval port. They may share an online model and credentials while targeting different abstractions.

## Qdrant Product Index

Each product becomes one Qdrant point:

```text
Point
├── id      = UUID5("globex/product/P1001")
├── vector  = searchable_text embedding
└── payload = {"product_id": "P1001"}
```

UUID5 is deterministic. The same product ID always maps to the same point, so upsert updates rather than duplicates it.

Payload stores only `product_id`; price, inventory, and the full Product are not copied. This prevents Qdrant and ProductRepository from becoming competing sources of truth.

Local mode stores the index at `.data/qdrant_product_vectors`. Setting `QDRANT_URL` selects remote Qdrant without changing upper-layer interfaces.

Upsert updates products that still exist but does not remove stale points for deleted products. The current startup also re-embeds every product. Index synchronization and embedding caching are later concerns.

## Stage One: Vector Recall

The collection uses cosine distance. Each normalized query is embedded, then Qdrant returns the top eight candidates.

Recall uses `top_n=8` rather than the final `top_k` to leave room for reranking and hard filtering. If three of eight candidates exceed the budget, five valid results may still remain.

Cosine score represents proximity in the embedding space, not factual confidence. The UseCase resolves each candidate ID through ProductRepository and rebuilds the list in VectorHit order, preventing repository return order from destroying relevance order.

## Stage Two: Reranking

Embedding retrieval is a bi-encoder process: query and products are encoded separately. It is fast and suitable for broad recall, but models limited interaction between a specific query and document.

A reranker is commonly a cross-encoder that reads each query-document pair together. It generally improves fine-grained ranking at greater latency and cost. The system therefore reranks only the small recalled candidate set.

HTTP rerank services may return results in score order rather than document order. `HttpReranker` uses each result's `index` to restore alignment and rejects duplicate, out-of-range, or missing indexes and scores.

After successful reranking, ProductCard `score` is the reranker score. Without reranking it is cosine similarity. A score is meaningful only together with `recall_strategy` and should not be compared across strategies as a single calibrated scale.

## Explicit Fallback Chain

The UseCase exposes:

```json
{
  "recall_strategy": "embedding_rerank",
  "rerank_applied": true
}
```

| State | recall_strategy | rerank_applied |
|---|---|---|
| Vector recall and rerank succeed | `embedding_rerank` | `true` |
| Reranker is not configured | `embedding_only` | `false` |
| Reranker call or protocol fails | `embedding_only` | `false` |
| Embedding fails | `keyword_2gram` | `false` |
| Qdrant fails | `keyword_2gram` | `false` |
| Vector recall has no valid candidates | `keyword_2gram` | `false` |
| Vector hits reference only deleted IDs | `keyword_2gram` | `false` |

Fallback never changes hard constraints or reports reranking that did not happen. Reranker failure preserves vector order. Only a failed or empty first-stage recall returns to keywords.

## Why Hard Constraints Stay Deterministic

Vectors and rerankers measure relevance. Price ceilings, currency, and destination eligibility remain deterministic:

```text
retrieval score
→ candidate Product
→ _rejected_reason(product, spec)
→ accepted / filtered_out
```

Even if an 899 CNY cabin case has the highest semantic score, it must be rejected for a 300 CNY request. `filtered_out` exposes `over_price_cap` or `ship_to_unavailable`, allowing the Agent to distinguish no recall from a recalled but invalid product.

The reference implementation uses recall, then rerank, then hard filtering. Filtering before reranking can save cost at scale, but requires filterable facts to be copied into the vector index and introduces consistency concerns. With only eight candidates, the reference order is simpler.

## Lifecycle and Failure Boundaries

Composition creates a shared embedder, product vector index, and optional reranker, then injects them into `CatalogSearchUseCase`.

Startup runs product-text embedding, collection creation, and product upsert. Indexing failure logs a warning and leaves keyword search, category knowledge, and order capabilities available. Shutdown closes both the product Qdrant client and the category-knowledge vector store.

`HttpReranker` currently creates a short-lived HTTP client per call and has no persistent resource for Container to close.

## Alternatives and Trade-offs

Keyword-only retrieval is deterministic, inexpensive, and offline, but weak for synonyms and queries without lexical overlap.

Vector-only retrieval improves semantic recall and scales well, but may rank subtle conditions poorly and depends on embedding and vector services.

Vector recall plus reranking usually improves Top-K quality, at the cost of another service call, latency, and money. Reranking is therefore an optional enhancement rather than a single point of failure.

A production system can also execute BM25/keyword and vector recall in parallel and fuse them with RRF or another algorithm. Hybrid search often combines exact-term and semantic strengths, but requires another index, fusion policy, and evaluation. It is intentionally deferred.

## Tests

Chapter coverage is entirely offline and includes:

- OpenAI-compatible embedding requests, batching, ordering, and errors.
- Deterministic UUID5 point IDs.
- Local Qdrant collections, idempotent upsert, and cosine search.
- Product-index bootstrap success, empty data, and degradation.
- Embedding-only recall and VectorHit order.
- Price and shipping filters after vector recall.
- Keyword fallback for embedding, Qdrant, empty-result, and stale-ID cases.
- Reranker HTTP protocol, index restoration, and validation.
- Reranker reordering and preservation of vector order on failure.
- Composition with and without configured reranking.
- A complete local-Qdrant pipeline using deterministic embeddings and a fake reranker.
- Regression coverage for HTTP, Agents, orders, inventory, and sessions.

The complete suite after this chapter is:

```text
206 passed
```

## Current Limitations

- The seed catalog is too small for Recall@K, MRR, or NDCG evaluation.
- Every startup re-embeds every product.
- Query embeddings are not cached.
- Deleted products do not automatically remove stale points.
- There is no similarity threshold or hybrid/BM25 fusion.
- The reranker adapter does not add an authentication header and currently targets unauthenticated or gateway-authenticated services.
- Automated tests avoid real embedding and rerank APIs for determinism and cost control.

Later caching and production-hardening chapters will address repeated computation, index synchronization, observability, and evaluation.
