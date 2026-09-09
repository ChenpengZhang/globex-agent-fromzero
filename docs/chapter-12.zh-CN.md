# 第十二章：品类知识 RAG

## 本章目标

本章在第十一章的 SearchAgent 边界内加入第一条真正的 RAG 链路，让 Agent 可以回答“应该怎么挑”一类问题，而不只是在种子商品中做确定性搜索。

本章实现的最小闭环是：

```text
knowledge/*.md
→ TextParser
→ ApproxTokenChunker
→ Embedding API
→ Qdrant

用户问题
→ SearchAgent / MainAgent
→ category_insight_tool
→ KnowledgeBase.search
→ query embedding + vector similarity
→ ToolResult（content/source/score）
→ Agent 最终回答
```

这一实现参考完整项目的品类知识库结构，但暂不加入商品向量检索、Rerank 和多级降级。那些属于下一章的检索策略，而不是本章知识库的职责。

## 两类检索不能混为一谈

当前系统现在有两条语义不同的检索路径。

### 品类知识检索

回答的是：

- 登机箱应该关注哪些指标？
- 旅行背包有哪些常见避坑点？
- 某个品类通常处于什么价格区间？

它返回的是知识片段，不能证明某个商品存在、在售、有库存或可以配送。

### 具体商品检索

回答的是：

- 有哪些 300 元以内的旅行装备？
- 哪个 SKU 有库存并且能寄到中国？
- 给我比较 P1001 和 P1003。

它读取商品仓储，并由确定性代码执行价格、库存和配送约束。

因此 SearchAgent 的规则是：

```text
“怎么挑”                    → category_insight_tool
“有哪些具体商品”             → product_search_tool
“先告诉我怎么挑，再推荐商品”  → 先知识工具，再商品工具
```

Embedding 适合寻找语义相关内容，但不应承担预算上限、库存大于零或配送国家等硬约束。这些规则必须继续留在确定性的 UseCase 和 Domain 中。

## DDD 边界

品类知识库位于 Infrastructure：

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

原因是 embedding 服务、Qdrant 和文件解析都是可替换的技术细节，不是电商领域规则。

`category_insight_tool` 位于 Application，因为它把外部检索能力适配成 Agent 可以调用的用例入口。它只负责校验参数、调用知识库和整理返回结构，不定义商品价格、库存或订单规则。

本章没有为了“形式上的 DDD”创建一个空洞的 Domain 知识实体。当前知识只是辅助 Agent 判断的只读内容，尚未形成需要领域不变量保护的聚合。

## 构建与启动为什么分开

`build_category_knowledge_base(settings)` 只构造对象：

- 创建 embedding model。
- 根据配置选择本地或远程 Qdrant。
- 创建 AgentScope `KnowledgeBase`。

它不连接外部资源，也不导入文档。实际初始化由 `Container.startup()` 完成：

```text
build_container()
→ 构造依赖图

container.startup()
→ 打开 vector store
→ bootstrap_category_knowledge()
→ 确保 collection 存在
→ 导入尚未存在的 Markdown 文档
```

这种分离让 Composition Root 的组装保持同步、可测试，也让 CLI 和 FastAPI 可以在各自的生命周期中可靠地打开和关闭资源。

CLI 使用 `try/finally`；FastAPI 使用 lifespan。两者最终都保证调用 `Container.shutdown()`。

## 文档如何变成向量

`bootstrap_category_knowledge` 对每个 Markdown 文件执行：

1. `TextParser.parse` 把文件解析成带结构的文本段。
2. `ApproxTokenChunker` 用近似 token 数切分，当前大小为 512、重叠为 50。
3. `KnowledgeBase.insert_document` 调用 embedding model，把每个 chunk 转成向量。
4. 文本、向量和 metadata 一起写入 Qdrant。

这里的 chunk text 会真正参与两件事：

- 写入时，它是 embedding API 的输入，也是后续返回给 Agent 的原文依据。
- 查询时，Qdrant 用问题向量寻找最接近的 chunk，工具再把 chunk text 放进 ToolResult。

如果只保存向量而不保存文本，Agent 最终只会拿到一串相似度和坐标，无法知道应该引用什么知识。

## Embedding 实际在哪里发生

本项目不在本机手写向量计算公式。`OpenAIEmbeddingModel` 通过 OpenAI-compatible `/embeddings` 接口调用线上模型：

```text
插入文档：insert_document(chunks)
         → embedding_model 对 chunk text 发起 API 请求

查询知识：knowledge_base.search(queries)
         → embedding_model 对用户问题发起 API 请求
         → Qdrant 计算问题向量与文档向量的相似度
```

默认情况下 embedding 复用 LLM 网关的 base URL 和 API key；如果提供商不同，可以单独设置 `EMBEDDING_BASE_URL` 和 `EMBEDDING_API_KEY`。

Embedding 通常不需要在项目早期精调。更合理的优化顺序是：

1. 提高知识文档质量。
2. 调整 chunk 大小与重叠。
3. 改进 query 表达或加入 query rewrite。
4. 引入混合检索与 Rerank。
5. 建立评测集观察指标。
6. 只有证据表明通用 embedding 无法区分领域语义时，再考虑训练或精调。

索引和查询必须使用相同的 embedding 模型与维度。更换模型或维度后，旧 collection 中的向量不能直接继续使用，必须重建索引或迁移到新 collection。

## Chunk 策略的取舍

当前采用 512/50 的近似 token 切分，是一个适合 MVP 的折中：

- chunk 太大：上下文完整，但容易混入多个主题，召回不够精确，token 成本也更高。
- chunk 太小：匹配更聚焦，但上下文容易破碎，答案可能缺少条件或例外。
- overlap 为相邻 chunk 保留少量共同上下文，但也会增加向量数量与重复结果。

更复杂的生产实现可以按 Markdown 标题、表格或语义边界切分，但应先通过评测证明有必要。

## 幂等导入与 source metadata

Markdown 文件名的 stem 被用作稳定的 `document_id`。启动时先读取已有文档 ID，只导入尚不存在的文件：

```text
travel-gear.md → document_id = "travel-gear"
```

这样重复启动不会反复插入同一文档或重复调用 embedding API。

每个文档还保留 `source` metadata。检索工具返回：

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

`source` 使结果可追踪；`score` 便于调试和未来设置阈值。但 score 不是事实置信度，不应被解释成“这句话有 91.33% 的概率正确”。

当前幂等策略只识别“是否存在同名 document_id”，还不能检测同名文件内容是否已更新。这是 MVP 的明确限制。

## 本地 Qdrant 与远程 Qdrant

当 `QDRANT_URL` 为空时，qdrant-client 使用本地路径：

```text
.data/qdrant_category_knowledge
```

这适合单进程学习和调试，不需要额外启动服务。配置 `QDRANT_URL` 后可切换为远程 Qdrant，更适合多个应用实例共享索引。

两种模式复用同一个 `KnowledgeBase` 和工具接口，因此上层 Agent 不需要知道存储部署方式。

## 为什么复用 AgentScope KnowledgeBase

与直接调用 qdrant-client 相比，AgentScope `KnowledgeBase` 提供了统一的文档、chunk、embedding 和 vector store 协作接口，代码更接近完整项目，也减少了本章的基础设施样板代码。

代价是 Application 当前直接标注了 AgentScope `KnowledgeBase` 类型，技术抽象还没有完全隔离。如果未来需要支持多个 RAG 框架或让 Application 完全不认识 AgentScope，可以在 Application 定义 `CategoryKnowledgeRetriever` port，由 Infrastructure 实现。MVP 暂不增加这一层，因为目前只有一个实现，提前抽象会增加理解成本。

## 错误与降级

知识库启动导入失败时，`bootstrap_category_knowledge` 记录 warning 并返回 0，使商品搜索和订单功能仍能启动。运行时知识搜索失败时，工具返回显式 `[error]`，提示 Agent 不得猜测答案。

这是“显式降级”：系统可以继续提供不依赖知识库的能力，但不会悄悄把知识检索失败伪装成“没有相关知识”。下一章会把同样的原则扩展到商品分级检索。

## 测试

本章新增和更新的测试覆盖：

- 离线确定性 embedding，不请求真实 API。
- Markdown 导入与 document metadata。
- 重复 bootstrap 不重复插入或重复 embedding。
- 查询文本确实经过 embedding，并召回相关 chunk。
- Qdrant 不可用时的启动降级。
- `category_insight_tool` schema、输入校验和错误返回。
- content、source、score 的 ToolResult 结构。
- SearchAgent → category tool → ToolResult → 最终回答。
- FastAPI lifespan 打开、初始化并关闭 vector store。
- 原有商品、订单、会话和子 Agent 链路无回归。

完成本章后，全套测试为：

```text
172 passed
```

## 当前限制

- 只有一篇示例品类知识文档。
- 同名文档修改后不会自动重建向量。
- 没有相似度阈值、去重或引用展示层。
- 没有真实 embedding 服务的自动集成测试，避免测试产生网络依赖和费用。
- Product Search 仍是确定性关键词/二元切分检索。
- 尚未加入商品向量检索、Rerank 和显式分级降级链。

下一章将在不改变品类知识工具边界的情况下，为“具体商品检索”加入 embedding、Rerank 与 fallback 策略。
