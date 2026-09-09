# 第十三章：商品分级检索

## 本章目标

本章把第三章的确定性关键词检索扩展为一条可降级的两阶段商品检索链：

```text
embedding_rerank
    ↓ Reranker 未配置或失败
embedding_only
    ↓ Embedding 或 Qdrant 失败
keyword_2gram
```

品类知识 RAG 与商品检索仍是两个独立系统：

```text
category_insight_tool
→ 检索 Markdown 知识 chunk
→ 回答“应该怎么挑”

product_search_tool
→ 检索 Product 候选
→ 回答“有哪些真实商品”
```

本章不加入缓存、BM25、到手价计算或大规模离线评测，重点是看清 embedding、向量索引、Reranker、硬过滤和 fallback 各自的职责。

## 完整数据管线

### 启动建库

```text
ProductRepository.list_all()
→ Product.searchable_text()
→ EmbeddingClient.embed_batch()
→ ProductVectorIndex.ensure_ready()
→ ProductVectorIndex.upsert_products()
→ Qdrant
```

`searchable_text()` 汇总标题、品牌、品类、描述和 SKU 规格。线上 embedding 服务负责计算向量，Qdrant 负责保存和搜索向量。

### 用户查询

```text
normalized_query
→ EmbeddingClient.embed()
→ ProductVectorIndex.search(top_n=8)
→ VectorHit(product_id, score)
→ ProductRepository.find_by_ids()
→ Reranker（可选）
→ 价格/币种/配送硬过滤
→ top_k
→ ProductCard
```

Qdrant 只负责找候选 ID。商品仓储仍然是价格、SKU、库存和配送事实的来源。

## 检索端口与 DDD

Domain 的 Catalog ports 定义三个能力：

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

Infrastructure 提供具体实现：

```text
OpenAIEmbeddingClient → OpenAI-compatible /embeddings
QdrantProductIndex    → qdrant-client
HttpReranker          → /rerank HTTP 协议
```

UseCase 只依赖端口，不知道 URL、HTTP JSON、Qdrant point 或第三方 SDK 类型。Composition Root 根据配置选择具体 Adapter。

从更严格的分层角度，这些端口也可以放进 Application ports，因为检索编排不是 Product 聚合的不变量。当前项目保留参考项目的 `domain/catalog/ports` 结构，把它们视为 Catalog 子域向外声明的能力需求。

## OpenAI-compatible Embedding Adapter

商品检索没有直接依赖 AgentScope 的 embedding 类型，而是使用自己的 `EmbeddingClient` port。Infrastructure 通过 HTTP 调用：

```text
POST {EMBEDDING_BASE_URL}/embeddings
{
  "model": "...",
  "input": ["product text 1", "product text 2"]
}
```

响应按 `index` 排序后再返回，保证向量与输入文本仍然一一对应。客户端还把批量大小限制为 10，避免部分兼容网关在大批量输入时返回空 body。

第十二章的 `OpenAIEmbeddingModel` 服务于 AgentScope KnowledgeBase；本章的 `OpenAIEmbeddingClient` 服务于项目自己的检索端口。它们可以使用同一个线上模型和凭据，但面向不同抽象。

## Qdrant 商品索引

每个商品被写成一个 Qdrant point：

```text
Point
├── id      = UUID5("globex/product/P1001")
├── vector  = searchable_text 的 embedding
└── payload = {"product_id": "P1001"}
```

UUID5 是确定性的。同一个 `product_id` 每次得到相同 point ID，因此 upsert 会更新原 point，而不是插入重复记录。

Payload 只保存 `product_id`，不复制价格、库存和完整 Product。这样不会让 Qdrant 与 ProductRepository 同时成为商品事实来源。

本地模式把数据放在：

```text
.data/qdrant_product_vectors
```

配置 `QDRANT_URL` 后则使用远程 Qdrant。上层端口保持不变。

当前 upsert 能更新仍存在的商品，但不会自动删除已经从 Repository 移除的旧 point；也会在每次启动时重新计算全部商品 embedding。这些属于后续索引同步与缓存问题。

## 第一阶段：向量召回

Qdrant collection 使用 cosine distance。查询时先将 `normalized_query` 转成向量，再取前 8 个候选。

这里使用 `top_n=8` 而不是直接使用用户请求的 `top_k`，是为了给后续精排和硬过滤留下候选空间。例如召回的 8 个商品中有 3 个超预算，仍可能返回 5 个合法结果。

Qdrant 返回：

```python
VectorHit(
    product_id="P1003",
    score=0.87,
)
```

向量分数表示 embedding 空间中的相似度，不表示事实正确率。UseCase 根据 ID 回到 ProductRepository 读取最新聚合，并按 VectorHit 顺序重新组装，避免 Repository 返回顺序破坏相关性排序。

## 第二阶段：Reranker

Embedding 检索是 bi-encoder：问题和商品分别编码，速度快、适合大规模召回，但交互信息有限。

Reranker 通常是 cross-encoder：它共同阅读 query 和每个候选 document，判断细粒度相关性，通常更准确，但调用成本和延迟更高。

因此本章只对少量向量候选精排：

```text
全部商品 → 向量召回 8 个 → Rerank 8 个 → top_k
```

HTTP 服务可能按分数而不是输入顺序返回结果。`HttpReranker` 使用每项的 `index` 把分数还原到原 document 位置，并拒绝重复、越界或缺失的 index/score。

Rerank 成功后，ProductCard 的 `score` 是 reranker score；未精排时则是 cosine score。因此只有结合 `recall_strategy` 才能解释 score，不应跨策略直接比较数值。

## 显式降级链

UseCase 返回两个观测字段：

```json
{
  "recall_strategy": "embedding_rerank",
  "rerank_applied": true
}
```

行为矩阵为：

| 状态 | recall_strategy | rerank_applied |
|---|---|---|
| 向量召回和 Rerank 成功 | `embedding_rerank` | `true` |
| Reranker 未配置 | `embedding_only` | `false` |
| Reranker 调用或协议失败 | `embedding_only` | `false` |
| Embedding 调用失败 | `keyword_2gram` | `false` |
| Qdrant 调用失败 | `keyword_2gram` | `false` |
| 向量没有有效候选 | `keyword_2gram` | `false` |
| 向量候选只包含已删除 ID | `keyword_2gram` | `false` |

降级不改变硬约束，也不会把失败伪装成精排成功。Reranker 失败时保留已有向量顺序；只有第一阶段向量召回不可用或无有效候选时才回到关键词。

## 硬约束为什么不交给向量模型

向量和 Reranker 只判断相关性。价格上限、币种和配送国家继续由确定性代码执行：

```text
retrieval score
→ candidate Product
→ _rejected_reason(product, spec)
→ accepted / filtered_out
```

即使一个 899 元登机箱获得最高相似度，在 300 元预算请求中仍必须被过滤。`filtered_out` 会给出 `over_price_cap` 或 `ship_to_unavailable`，让 Agent 区分“没有召回”与“召回但不满足约束”。

参考项目采用“召回 → 精排 → 硬过滤”。另一种方案是先硬过滤再精排，可以减少 Reranker 成本，但需要把可过滤字段同步到向量索引，增加一致性问题。当前候选只有 8 个，因此保持参考项目顺序更清晰。

## 生命周期与故障边界

Composition 创建共享的 embedder、商品向量 index 和可选 reranker，并注入 `CatalogSearchUseCase`。

启动时：

```text
bootstrap_product_index()
→ 批量 embedding
→ ensure collection
→ upsert products
```

建库失败只记录 warning，应用继续提供关键词检索、品类知识和订单功能。关闭时 `Container.shutdown()` 释放商品 Qdrant client 和品类知识 vector store。

`HttpReranker` 每次调用使用短生命周期 HTTP client，目前没有需要在 Container 中关闭的长期连接。

## 方法取舍

### 只用关键词

优点是确定、便宜、离线可用；缺点是同义表达和无词面重合的查询召回较弱。

### 只用向量

语义召回更强、索引速度快；但对细微条件的排序可能不够准确，而且依赖 embedding 服务和向量库。

### 向量加 Reranker

通常获得更好的 Top-K 排序，但增加一次服务调用、延迟和费用。因此 Reranker 是可选增强，失败不应拖垮召回。

### Hybrid Search

生产系统还可以并行执行 BM25/关键词与向量召回，再使用 RRF 等算法融合。它通常比“向量失败才用关键词”更能兼顾精确词匹配和语义召回，但需要额外索引、融合策略和评测。本章暂不引入。

## 测试

本章测试完全离线，覆盖：

- OpenAI-compatible embedding 请求、批处理、排序和错误响应。
- 确定性 UUID5 point ID。
- 本地 Qdrant collection、upsert 幂等和 cosine 搜索。
- 商品索引 bootstrap 成功、空库和失败降级。
- embedding-only 召回及 VectorHit 顺序。
- 向量后价格/配送硬过滤。
- embedding、Qdrant、空结果和过期 ID 的关键词 fallback。
- Reranker HTTP 协议、乱序 index 回位和错误校验。
- Reranker 改变排序、失败保留向量顺序。
- Composition 有/无 Reranker 的装配策略。
- 真实本地 Qdrant + 确定性 embedding + fake Reranker 的完整检索链。
- HTTP、Agent、订单、库存和会话功能无回归。

完成本章后，全套测试为：

```text
206 passed
```

## 当前限制

- 商品种子库很小，还没有衡量 Recall@K、MRR 或 NDCG 的评测集。
- 每次启动都会重新 embedding 全部商品。
- 查询向量没有缓存，相同问题会重复请求线上服务。
- 删除商品不会自动清理旧 point。
- 没有向量相似度阈值或 hybrid/BM25 融合。
- Reranker Adapter 未实现认证 header，适合无认证或网关内鉴权服务。
- 自动测试不访问真实 embedding/rerank API，以保持确定性并避免费用。

后续的缓存和生产强化章节会处理重复计算、索引同步、观测与评测问题。
