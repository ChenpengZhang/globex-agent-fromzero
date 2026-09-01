# 跨境Agent第三章
## 本章新增实现功能
- ProductSearchSpec: 标准化搜索条件，避免程序“乱搜”，减少传入参数数量。
- 添加CatalogSearchUseCase：一个简单的搜索流程用例，放入Application层。
- 添加ProductSearchSpec的测试：测试检索条件的标准化类是否在正常运行。
- 添加CatalogSearchUseCase的测试：测试检索的筛选、打分功能是否正常运行。

## 补充：本章目标

本章建立一个完全不依赖 LLM 的商品搜索能力。搜索首先是普通应用业务，后续 Agent 工具只负责把模型参数转换为 `ProductSearchSpec` 并调用它。

```text
ProductSearchSpec
        ↓
CatalogSearchUseCase
        ↓
ProductRepository
        ↓
关键词召回 → 业务过滤 → 排序 → Top-K → 商品卡
```

## ProductSearchSpec

`ProductSearchSpec` 是描述一次搜索条件的值对象，负责集中校验和规范化：

- 去除搜索词和品类两侧的空白。
- 把收货国家规范化为二位大写代码。
- 把目标币种规范化为三位大写代码。
- 把价格上限规范化为 `Decimal`。
- 限制 `top_k` 的合法范围。
- 拒绝空搜索词、负预算和非法代码。

`raw_query` 是用户原话；`normalized_query` 是后续真正参与检索的标准化关键词。当前由调用者直接提供，未来由 Agent 从自然语言中提取。

## CatalogSearchUseCase

UseCase 位于 Application 层，负责组织一次完整搜索：

1. 通过 `ProductRepository` 取得商品。
2. 对 query 和商品可检索文本进行 token 化。
3. 按关键词交集计算基础分数。
4. 对匹配的品类一次性增加 3 分。
5. 应用配送国家、目标币种和预算硬条件。
6. 按分数降序排列。
7. 截取 Top-K，并转换为可序列化商品卡。

关键词算法当前作为 UseCase 的私有实现存在。它不是不可改变的核心领域规则；加入向量召回时，我们会把可替换检索能力抽象为端口，由 Infrastructure 实现。

## 中文 2-gram

中文通常没有空格，例如“旅行装备”。只按空格切分会得到一个完整长词，因此当前实现额外生成连续二元片段：

```text
旅行装备
→ 旅行、行装、装备
```

这只是 MVP 级关键词召回，用来建立确定、可测试的基线，不等同于正式中文分词或语义检索。

## 软条件与硬条件

`category` 当前是软条件：匹配时提高排序分数，但不直接排除其他品类的近似候选。

下面是硬条件：

- `ship_to` 不支持：`ship_to_unavailable`
- 目标币种暂不支持：`currency_unsupported`
- 超过预算：`over_price_cap`

被硬条件拒绝的候选不会静默丢弃，而是进入 `filtered_out`。这让未来的 Agent 能区分“没有找到”和“找到了，但被某项条件挡住”。

## 输出结构

UseCase 返回：

```text
hits                 满足条件的 Top-K 商品卡
filtered_out         命中关键词但不满足硬条件的商品摘要
total_candidates     过滤后、Top-K 截断前的候选数量
recall_strategy      当前固定为 keyword_2gram
```

Domain 内部继续使用 `Money` 保存精确金额，只在 Application 输出边界转换成适合 JSON 的主单位数字。

## 测试覆盖

本章共 13 项测试，覆盖：

- SearchSpec 的值规范化。
- 空 query、非法 top_k、国家代码、负预算和非数字预算。
- 关键词排序。
- category 排名加权。
- 预算过滤与 `over_price_cap`。
- 配送过滤与 `ship_to_unavailable`。
- Top-K 不改变 `total_candidates` 的含义。
- 未知关键词返回空结果。

## 验收结果

本章测试全部通过：`13 passed`。

此时搜索能力可以脱离 AgentScope、模型服务和网络独立运行，Application 只依赖 Domain 定义的 `ProductRepository` 端口。

## 下一章

下一章把 `CatalogSearchUseCase` 包装为 AgentScope `FunctionTool`，注册到 MainAgent 的 `Toolkit`，第一次形成完整的 ReAct 工具调用循环：

```text
用户问题 → 模型选择工具 → Python UseCase → 工具结果 → 模型最终回答
```
